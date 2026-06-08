"""Auditable NL-query endpoint: question -> QueryPlan IR -> SQL -> cited rows.

This is the route behind the headline feature. Unlike the legacy `/query`
endpoint (which returns an opaque result list), `/query/plan` returns the full
audit bundle: the typed plan the LLM produced, the exact SQL that ran, and every
result row annotated with the evidence span that explains its match.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from database import get_session
from ai.planner import plan_question
from ai.query_pipeline import run_plan
from ingest.services.audit_service import audit_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/query", tags=["Query Plan (auditable)"])


class PlanQueryRequest(BaseModel):
    question: str
    run_id: str
    context: dict | None = None


@router.post("/plan")
def plan_and_run(req: PlanQueryRequest, session: Session = Depends(get_session)) -> dict:
    """NL question -> validated plan -> deterministic SQL -> cited results."""
    if not req.question.strip():
        raise HTTPException(status_code=422, detail="question must not be empty")

    # 1. NL -> typed QueryPlan (LLM-validated, or explicit DEMO stub).
    plan, planner = plan_question(req.question, req.context)
    logger.info("Planned question via %s planner: %s", planner, plan.rationale or req.question)

    # 2+3. Compile to SQL + execute with citation hydration.
    answer = run_plan(session, plan, req.run_id, question=req.question, planner=planner)

    # 4. Record the query in the tamper-evident audit trail.
    audit_service.record(
        session, "query",
        payload={"question": req.question, "planner": planner,
                 "total": answer.total, "targets": [t.value for t in plan.targets]},
        run_id=req.run_id,
    )
    return answer.to_dict()


@router.post("/plan/preview")
def plan_preview(req: PlanQueryRequest) -> dict:
    """Return the plan + compiled SQL WITHOUT executing — for the audit panel."""
    if not req.question.strip():
        raise HTTPException(status_code=422, detail="question must not be empty")
    plan, planner = plan_question(req.question, req.context)
    compiled = plan.compile()
    return {
        "question": req.question,
        "planner": planner,
        "plan": plan.model_dump(mode="json"),
        "sql": compiled.rendered_sql,
        "targets": [tq.target.value for tq in compiled.table_queries],
    }
