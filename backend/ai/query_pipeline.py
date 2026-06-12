"""NL -> QueryPlan -> SQL -> cited results — the auditable query pipeline.

`run_plan()` executes a compiled plan and, for every returned row, records
*why* it matched: which predicate, which column, the matched value, and the
exact character span inside that column. Those citations are what let an
investigator (or a court) trace a result back to the evidence that produced it.

This module does the deterministic execution + citation work. The LLM step
(NL -> QueryPlan) lives in `ai.planner`; `answer_question()` wires them together.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Uuid, bindparam, text
from sqlmodel import Session

from ai.query_compiler import SCHEMA
from ai.query_plan import Op, QueryPlan, Target

_SNIPPET_PAD = 40


@dataclass
class Citation:
    """Evidence locator: a result row traces to this exact span."""

    source_table: str
    row_id: str
    column: str
    matched_value: str
    snippet: str
    char_start: int
    char_end: int


@dataclass
class CitedRow:
    source_table: str
    row_id: str
    event_time: str | None
    preview: str
    citations: list[Citation] = field(default_factory=list)


@dataclass
class QueryAnswer:
    """The full audit bundle returned to the API/UI."""

    question: str
    plan: dict  # QueryPlan as JSON
    sql: str  # rendered SQL (display); per-table bound SQL ran
    rows: list[CitedRow]
    total: int
    planner: str  # "llm" | "stub" — provenance of the plan

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "plan": self.plan,
            "sql": self.sql,
            "total": self.total,
            "planner": self.planner,
            "rows": [
                {
                    **{k: v for k, v in asdict(r).items() if k != "citations"},
                    "citations": [asdict(c) for c in r.citations],
                }
                for r in self.rows
            ],
        }


def _snippet(value: str, start: int, end: int) -> str:
    lo = max(0, start - _SNIPPET_PAD)
    hi = min(len(value), end + _SNIPPET_PAD)
    prefix = "…" if lo > 0 else ""
    suffix = "…" if hi < len(value) else ""
    return f"{prefix}{value[lo:hi]}{suffix}"


def _cite_row(
    target: Target,
    row_map: dict,
    plan: QueryPlan,
) -> list[Citation]:
    """Find every (predicate, column) span that explains this row's match."""
    schema = SCHEMA[target]
    citations: list[Citation] = []
    row_id = str(row_map.get("row_id"))

    for pred in plan.predicates:
        for col in schema.columns_for(pred.field):
            raw = row_map.get(col)
            if raw is None:
                continue
            col_val = str(raw)
            hay = col_val.lower()
            for value in pred.values:
                needle = value.lower()
                if pred.op is Op.contains:
                    idx = hay.find(needle)
                    if idx == -1:
                        continue
                    start, end = idx, idx + len(value)
                elif pred.op in (Op.equals, Op.is_in):
                    if hay != needle:
                        continue
                    start, end = 0, len(col_val)
                else:  # pragma: no cover
                    continue
                citations.append(
                    Citation(
                        source_table=schema.table,
                        row_id=row_id,
                        column=col,
                        matched_value=value,
                        snippet=_snippet(col_val, start, end),
                        char_start=start,
                        char_end=end,
                    )
                )
    return citations


def _preview(target: Target, row_map: dict) -> str:
    """Best human-readable one-liner for a row, table-aware."""
    schema = SCHEMA[target]
    for col in schema.searchable_columns:
        val = row_map.get(col)
        if val:
            s = str(val)
            return s[:160] + ("…" if len(s) > 160 else "")
    return f"{schema.table}:{row_map.get('row_id')}"


def run_plan(
    session: Session, plan: QueryPlan, run_id, question: str = "", planner: str = "llm"
) -> QueryAnswer:
    """Compile + execute `plan` against `run_id`, returning cited results."""
    compiled = plan.compile()
    rows: list[CitedRow] = []

    run_uuid = run_id if isinstance(run_id, uuid.UUID) else uuid.UUID(str(run_id))

    for tq in compiled.table_queries:
        params = dict(tq.params)
        params["run_id"] = run_uuid
        # Type the params whose columns are not plain text, so the one compiled
        # SQL binds correctly on both SQLite (tests) and Postgres (uuid/timestamp).
        typed = [bindparam("run_id", type_=Uuid(as_uuid=True))]
        for tkey in ("time_start", "time_end"):
            if tkey in params:
                params[tkey] = datetime.fromisoformat(params[tkey])
                typed.append(bindparam(tkey, type_=DateTime()))
        stmt = text(tq.sql).bindparams(*typed)
        result = session.execute(stmt, params)
        for mapping in result.mappings():
            row_map = dict(mapping)
            citations = _cite_row(tq.target, row_map, plan)
            event_time = row_map.get("event_time")
            rows.append(
                CitedRow(
                    source_table=SCHEMA[tq.target].table,
                    row_id=str(row_map.get("row_id")),
                    event_time=str(event_time) if event_time is not None else None,
                    preview=_preview(tq.target, row_map),
                    citations=citations,
                )
            )

    # Stable, deterministic ordering across heterogeneous tables: time desc,
    # then table, then row id — so the same plan yields the same row order.
    rows.sort(
        key=lambda r: (
            r.event_time is None,
            r.event_time or "",
            r.source_table,
            r.row_id,
        ),
        reverse=plan.sort.direction.value == "desc",
    )
    rows = rows[plan.offset : plan.offset + plan.limit]

    return QueryAnswer(
        question=question,
        plan=plan.model_dump(mode="json"),
        sql=compiled.rendered_sql,
        rows=rows,
        total=len(rows),
        planner=planner,
    )
