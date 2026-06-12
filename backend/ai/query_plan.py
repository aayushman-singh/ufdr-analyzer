"""Typed query-plan IR — the auditable middle layer of NL -> results.

A forensic reviewer must be able to see *exactly* what a natural-language
question was turned into before any row is read. That contract lives here:

    NL question --(LLM)--> QueryPlan (this IR) --(deterministic)--> SQL --> cited rows

`QueryPlan` is a strict Pydantic model. The LLM only ever produces *this* shape
(validated, never trusted as raw SQL). `compile()` turns a plan into parameter-
bound SQL deterministically — same plan in, byte-identical SQL out — so the SQL
shown in the UI is provably the SQL that ran. Values are always bound parameters;
the IR cannot express raw SQL, so prompt-injection cannot reach the database.

No fallbacks: an unsupported field/op/target raises loudly rather than guessing.
"""

from __future__ import annotations

import enum
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel, Field, field_validator

if TYPE_CHECKING:
    from ai.query_compiler import CompiledQuery


# --------------------------------------------------------------------------
# Enumerations — the closed vocabulary the LLM is allowed to emit.
# --------------------------------------------------------------------------
class Target(str, enum.Enum):
    """A normalized evidence table the plan may read from."""

    messages = "messages"
    calls = "calls"
    contacts = "contacts"
    media = "media"
    aleapp_artifacts = "aleapp_artifacts"


class FieldName(str, enum.Enum):
    """Logical, table-independent field a predicate can constrain.

    The compiler maps each logical field to concrete columns per target table
    (e.g. `text` -> Message.content, Contact.name, AleappArtifact.data ...).
    """

    text = "text"  # free-text body of the record
    participant = "participant"  # any party: sender/receiver/caller/number
    app = "app"  # application name (aleapp artifacts)
    category = "category"  # artifact/media category
    media_type = "media_type"


class Op(str, enum.Enum):
    contains = "contains"  # case-insensitive substring (ILIKE %v%)
    equals = "equals"  # exact match
    is_in = "in"  # membership over a list of values


class Match(str, enum.Enum):
    all = "all"  # AND the predicates together
    any = "any"  # OR the predicates together


class SortDir(str, enum.Enum):
    asc = "asc"
    desc = "desc"


# --------------------------------------------------------------------------
# IR components
# --------------------------------------------------------------------------
class Entity(BaseModel):
    """A salient value extracted from the question (for display/audit, not SQL)."""

    type: str = Field(description="phone|crypto|email|app|person|location|keyword")
    value: str


class TimeRange(BaseModel):
    start: Optional[str] = Field(
        default=None, description="ISO-8601 inclusive lower bound"
    )
    end: Optional[str] = Field(
        default=None, description="ISO-8601 inclusive upper bound"
    )

    @field_validator("start", "end")
    @classmethod
    def _blank_to_none(cls, v: Optional[str]) -> Optional[str]:
        return v or None


class Predicate(BaseModel):
    field: FieldName
    op: Op
    # `values` is always a list so `in` and single-value ops share one shape.
    values: list[str] = Field(min_length=1)

    @field_validator("values")
    @classmethod
    def _strip(cls, vs: list[str]) -> list[str]:
        cleaned = [v.strip() for v in vs if v and v.strip()]
        if not cleaned:
            raise ValueError(
                "predicate.values must contain at least one non-empty string"
            )
        return cleaned


class Sort(BaseModel):
    field: FieldName = FieldName.text
    direction: SortDir = SortDir.desc
    # Only event-time sorting is meaningful across tables; `by_time` opts into it.
    by_time: bool = True


class QueryPlan(BaseModel):
    """The full typed plan. This is what the LLM must produce and what the UI shows."""

    targets: list[Target] = Field(min_length=1)
    predicates: list[Predicate] = Field(default_factory=list)
    match: Match = Match.any
    time_range: Optional[TimeRange] = None
    entities: list[Entity] = Field(default_factory=list)
    sort: Sort = Field(default_factory=Sort)
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0, le=100_000)
    # Free-text restatement of intent, for the audit log. Never reaches SQL.
    rationale: str = ""

    model_config = {"extra": "forbid"}

    def compile(self) -> "CompiledQuery":
        """Deterministically lower this plan to per-target parameter-bound SQL."""
        from ai.query_compiler import compile_plan

        return compile_plan(self)
