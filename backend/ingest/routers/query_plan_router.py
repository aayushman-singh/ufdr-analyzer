"""Auditable NL-query endpoint: question -> QueryPlan IR -> SQL -> cited rows.

This is the route behind the headline feature. Unlike the legacy `/query`
endpoint (which returns an opaque result list), `/query/plan` returns the full
audit bundle: the typed plan the LLM produced, the exact SQL that ran, and every
result row annotated with the evidence span that explains its match.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from database import get_session
from db_setup import User
from ai.planner import plan_question
from ai.query_pipeline import run_plan
from ingest.services.audit_service import audit_service
from ingest.services.auth_service import require_user
from ingest.services.case_access import authorize_run

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/query", tags=["Query Plan (auditable)"])


class PlanQueryRequest(BaseModel):
    question: str
    run_id: uuid.UUID  # invalid UUIDs are rejected with 422 before any DB work
    context: dict | None = None


@router.post("/plan")
def plan_and_run(
    req: PlanQueryRequest,
    session: Session = Depends(get_session),
    user: User = Depends(require_user),
) -> dict:
    """NL question -> validated plan -> deterministic SQL -> cited results.

    Case-level RBAC: the caller must hold at least 'viewer' on `run_id` (implicit
    owner or an explicit grant). An unauthenticated caller is 401, a nonexistent
    run is 404, and a run the caller is not a member of is 403 — a query must not
    be a back door to evidence the caller may not see."""
    if not req.question.strip():
        raise HTTPException(status_code=422, detail="question must not be empty")

    # 0. Authorize the caller on this case before any planning or DB work.
    authorize_run(session, user, req.run_id)

    # 1. NL -> typed QueryPlan (LLM-validated, or explicit DEMO stub).
    plan, planner = plan_question(req.question, req.context)
    logger.info(
        "Planned question via %s planner: %s", planner, plan.rationale or req.question
    )

    # 2+3. Compile to SQL + execute with citation hydration.
    answer = run_plan(session, plan, req.run_id, question=req.question, planner=planner)

    # 4. Record the query in the tamper-evident audit trail. The payload
    # captures the evidence-bearing artifacts — the typed plan, the compiled
    # SQL, and the result row ids — so the chain can prove what actually ran.
    result = answer.to_dict()
    audit_service.record(
        session,
        "query",
        payload={
            "question": req.question,
            "planner": planner,
            "plan": result["plan"],
            "sql": result["sql"],
            "total": answer.total,
            "row_ids": [r["row_id"] for r in result["rows"]],
        },
        run_id=req.run_id,
        user_id=user.id,  # chain-of-custody: WHO ran the query
    )
    return result


@router.post("/plan/preview")
def plan_preview(
    req: PlanQueryRequest,
    session: Session = Depends(get_session),
    user: User = Depends(require_user),
) -> dict:
    """Return the plan + compiled SQL WITHOUT executing — for the audit panel.

    Gated identically to `/plan`: the preview is part of a specific case's audit
    panel, so the caller must be authenticated and hold 'viewer' on `run_id`."""
    if not req.question.strip():
        raise HTTPException(status_code=422, detail="question must not be empty")
    authorize_run(session, user, req.run_id)
    plan, planner = plan_question(req.question, req.context)
    compiled = plan.compile()
    return {
        "question": req.question,
        "planner": planner,
        "plan": plan.model_dump(mode="json"),
        "sql": compiled.rendered_sql,
        "targets": [tq.target.value for tq in compiled.table_queries],
    }
