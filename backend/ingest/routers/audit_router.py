"""Audit-trail + signed evidence-export endpoints.

- GET  /audit          -> full hash-chained log + verification verdict
- GET  /audit/verify   -> just the chain-integrity verdict
- POST /audit/evidence-report -> run a query, record an `export` event, and
  return a signed, deterministic PDF of the cited results.
"""
import logging
import os
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session

from database import get_session
from ai.planner import plan_question
from ai.query_pipeline import run_plan
from ingest.services.audit_service import audit_service
from ingest.services.evidence_report import build_evidence_pdf

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/audit", tags=["Audit & Evidence Export"])


@router.get("")
def get_audit(session: Session = Depends(get_session)) -> dict:
    """Full audit chain plus a recomputed integrity verdict."""
    return audit_service.export(session)


@router.get("/verify")
def verify_audit(session: Session = Depends(get_session)) -> dict:
    status = audit_service.verify_chain(session)
    return {
        "verified": status.ok,
        "length": status.length,
        "broken_at_seq": status.broken_at_seq,
        "detail": status.detail,
    }


class EvidenceReportRequest(BaseModel):
    question: str
    run_id: str
    context: dict | None = None


@router.post("/evidence-report")
def evidence_report(req: EvidenceReportRequest, session: Session = Depends(get_session)):
    """Run the query, record an export audit event, return a signed PDF."""
    if not req.question.strip():
        raise HTTPException(status_code=422, detail="question must not be empty")

    plan, planner = plan_question(req.question, req.context)
    answer = run_plan(session, plan, req.run_id, question=req.question, planner=planner).to_dict()

    # Record the export in the tamper-evident chain BEFORE signing so the PDF can
    # cite the resulting chain head.
    from ingest.services.evidence_report import content_hash
    event = audit_service.record(
        session, "export",
        payload={"question": req.question, "content_hash": content_hash(answer),
                 "total": answer["total"]},
        run_id=req.run_id,
    )

    secret_key = os.getenv("SECRET_KEY")
    if not secret_key:
        raise HTTPException(
            status_code=500,
            detail="SECRET_KEY not configured — cannot sign the evidence export.",
        )
    pdf = build_evidence_pdf(answer, secret_key, audit_head_hash=event.entry_hash)

    return StreamingResponse(
        BytesIO(pdf),
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="evidence_report.pdf"'},
    )
