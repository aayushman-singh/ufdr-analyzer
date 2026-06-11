"""Deterministic lowering of a `QueryPlan` to parameter-bound SQL.

This is the trust boundary. The LLM never writes SQL; it writes a `QueryPlan`,
and *this* module — pure, deterministic, no I/O — turns the plan into SQL. Two
guarantees follow:

1. **Auditable.** Same plan -> identical SQL + params, every time. The SQL the
   UI shows is the SQL that ran.
2. **Injection-proof.** Every plan value becomes a bound parameter. The IR has
   no way to express raw SQL, so a malicious question cannot reach the database
   as code — only as data inside `LIKE`/`=`/`IN` parameters.

Portability: text matching uses `LOWER(col) LIKE LOWER(:p)` which is
case-insensitive on both PostgreSQL and SQLite, so the same compiled SQL is
exercised by the SQLite test-suite and by the Postgres demo.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ai.query_plan import FieldName, Match, Op, QueryPlan, Target


# --------------------------------------------------------------------------
# Schema registry: logical field -> concrete columns, per target table.
# A logical field absent from a table maps to [] (predicate unsatisfiable there).
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class TableSchema:
    table: str
    time_column: str | None
    fields: dict[FieldName, tuple[str, ...]]

    def columns_for(self, fname: FieldName) -> tuple[str, ...]:
        return self.fields.get(fname, ())

    @property
    def searchable_columns(self) -> tuple[str, ...]:
        seen: list[str] = []
        for cols in self.fields.values():
            for c in cols:
                if c not in seen:
                    seen.append(c)
        return tuple(seen)


SCHEMA: dict[Target, TableSchema] = {
    Target.messages: TableSchema(
        table="message",
        time_column="timestamp",
        fields={
            FieldName.text: ("content",),
            FieldName.participant: ("sender", "receiver"),
        },
    ),
    Target.calls: TableSchema(
        table="call",
        time_column="timestamp",
        fields={
            FieldName.participant: ("caller", "receiver"),
        },
    ),
    Target.contacts: TableSchema(
        table="contact",
        time_column=None,
        fields={
            FieldName.text: ("name",),
            FieldName.participant: ("number",),
        },
    ),
    Target.media: TableSchema(
        table="media",
        time_column=None,
        fields={
            FieldName.text: ("original_path", "storage_path"),
            FieldName.media_type: ("media_type",),
            FieldName.category: ("media_type",),
        },
    ),
    Target.aleapp_artifacts: TableSchema(
        table="aleappartifact",
        time_column="created_at",
        fields={
            FieldName.text: ("data", "filename"),
            FieldName.app: ("filename", "file_path", "category"),
            FieldName.category: ("category", "filename"),
        },
    ),
}


@dataclass
class TableQuery:
    """One target table's compiled SELECT plus the metadata citations need."""
    target: Target
    sql: str
    params: dict[str, object]
    projected_columns: tuple[str, ...]  # searchable cols included in SELECT
    time_column: str | None


@dataclass
class CompiledQuery:
    plan: QueryPlan
    table_queries: list[TableQuery] = field(default_factory=list)

    @property
    def rendered_sql(self) -> str:
        """Human-readable, all targets concatenated. For display/audit only."""
        if not self.table_queries:
            return "-- (no satisfiable target table for this plan)"
        blocks = []
        for tq in self.table_queries:
            rendered = tq.sql
            for key, val in tq.params.items():
                token = f":{key}"
                literal = "'" + str(val).replace("'", "''") + "'"
                rendered = rendered.replace(token, literal)
            blocks.append(rendered.strip())
        return ";\n\n".join(blocks)


def _predicate_clause(
    schema: TableSchema,
    pred,
    p_index: int,
    params: dict[str, object],
) -> str | None:
    """Build the SQL boolean for one predicate against one table.

    Returns None when the predicate's logical field maps to no column in this
    table (i.e. the predicate is provably unsatisfiable here).
    """
    cols = schema.columns_for(pred.field)
    if not cols:
        return None

    ors: list[str] = []
    for ci, col in enumerate(cols):
        if pred.op is Op.contains:
            for vi, value in enumerate(pred.values):
                key = f"p{p_index}_c{ci}_v{vi}"
                params[key] = f"%{value}%"
                ors.append(f"LOWER({col}) LIKE LOWER(:{key})")
        elif pred.op is Op.equals:
            for vi, value in enumerate(pred.values):
                key = f"p{p_index}_c{ci}_v{vi}"
                params[key] = value
                ors.append(f"{col} = :{key}")
        elif pred.op is Op.is_in:
            placeholders = []
            for vi, value in enumerate(pred.values):
                key = f"p{p_index}_c{ci}_v{vi}"
                params[key] = value
                placeholders.append(f":{key}")
            ors.append(f"{col} IN ({', '.join(placeholders)})")
        else:  # pragma: no cover - enum is closed
            raise ValueError(f"Unsupported op: {pred.op!r}")
    return "(" + " OR ".join(ors) + ")"


def compile_plan(plan: QueryPlan) -> CompiledQuery:
    """Lower a validated `QueryPlan` into per-target parameter-bound SQL."""
    compiled = CompiledQuery(plan=plan)

    for target in plan.targets:
        schema = SCHEMA.get(target)
        if schema is None:  # pragma: no cover - enum is closed
            raise ValueError(f"Unknown target table: {target!r}")

        params: dict[str, object] = {}
        where: list[str] = ["run_id = :run_id"]  # :run_id bound by the executor

        # Predicates ------------------------------------------------------
        clauses: list[str] = []
        unsatisfiable_required = False
        for i, pred in enumerate(plan.predicates):
            clause = _predicate_clause(schema, pred, i, params)
            if clause is None:
                if plan.match is Match.all:
                    # A required predicate this table can never satisfy -> skip table.
                    unsatisfiable_required = True
                    break
                continue  # match=any: this predicate just can't fire here
            clauses.append(clause)

        if unsatisfiable_required:
            continue
        if plan.predicates and not clauses:
            # Every predicate was unsatisfiable for this table -> no rows.
            continue
        if clauses:
            joiner = " AND " if plan.match is Match.all else " OR "
            where.append("(" + joiner.join(clauses) + ")")

        # Time range ------------------------------------------------------
        if plan.time_range and schema.time_column:
            if plan.time_range.start:
                params["time_start"] = plan.time_range.start
                where.append(f"{schema.time_column} >= :time_start")
            if plan.time_range.end:
                params["time_end"] = plan.time_range.end
                where.append(f"{schema.time_column} <= :time_end")

        # Projection ------------------------------------------------------
        projected = schema.searchable_columns
        select_cols = ["id AS row_id", *projected]
        if schema.time_column:
            select_cols.append(f"{schema.time_column} AS event_time")
        else:
            select_cols.append("NULL AS event_time")

        # Quote the table identifier: `call` and `user` are SQL reserved words
        # on PostgreSQL. Double quotes are portable to SQLite too.
        sql = (
            f"SELECT {', '.join(select_cols)}\nFROM \"{schema.table}\"\nWHERE "
            + "\n  AND ".join(where)
        )

        # Ordering + limit ------------------------------------------------
        if plan.sort.by_time and schema.time_column:
            sql += f"\nORDER BY {schema.time_column} {plan.sort.direction.value.upper()}"
        params["limit"] = plan.limit
        sql += "\nLIMIT :limit"

        compiled.table_queries.append(
            TableQuery(
                target=target,
                sql=sql,
                params=params,
                projected_columns=projected,
                time_column=schema.time_column,
            )
        )

    return compiled
