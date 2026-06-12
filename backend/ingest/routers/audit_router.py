"""Audit-trail + signed evidence-export endpoints.

- GET  /audit          -> full hash-chained log + verification verdict
- GET  /audit/verify   -> just the chain-integrity verdict
- POST /audit/evidence-report -> run a query, record an `export` event, and
  return a signed, deterministic PDF of the cited results.
"""

import logging
import os
import uuid
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session

from database import get_session
from db_setup import User
from ai.planner import plan_question
from ai.query_pipeline import run_plan
from ingest.services.audit_service import audit_service
from ingest.services.auth_service import require_admin, require_user
from ingest.services.case_access import authorize_run
from ingest.services.evidence_report import build_evidence_pdf

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/audit", tags=["Audit & Evidence Export"])


@router.get("")
def get_audit(
    session: Session = Depends(get_session),
    admin: User = Depends(require_admin),
) -> dict:
    """Full audit chain plus a recomputed integrity verdict."""
    return audit_service.export(session)


@router.post("/timestamp")
def timestamp_chain(
    session: Session = Depends(get_session),
    admin: User = Depends(require_admin),
) -> dict:
    """Anchor the current audit-chain head to an RFC 3161 TSA token.

    The custody root (chain head hash) is sent to an external Time-Stamp
    Authority; its token independently attests the head existed at a UTC instant.
    On any TSA failure we record the exact reason in the chain and raise — we
    never return an unstamped result dressed up as stamped.
    """
    from ingest.services.timestamp_service import (
        DEFAULT_TSA_URL,
        TimestampError,
        request_timestamp,
    )

    head_hash = audit_service.export(session)["head_hash"]
    tsa_url = os.getenv("TSA_URL", DEFAULT_TSA_URL)
    try:
        digest = bytes.fromhex(head_hash)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=f"invalid chain head hash: {e}")

    try:
        token = request_timestamp(digest, tsa_url=tsa_url)
    except TimestampError as e:
        # Record the failure (exact reason) in the tamper-evident chain, then fail.
        audit_service.record(
            session,
            "timestamp_failed",
            user_id=admin.id,
            payload={"tsa_url": tsa_url, "head_hash": head_hash, "reason": str(e)},
        )
        raise HTTPException(status_code=502, detail=str(e))

    event = audit_service.record(
        session,
        "timestamp",
        user_id=admin.id,
        payload={
            "tsa_url": token.tsa_url,
            "head_hash": head_hash,
            "gen_time": token.gen_time,
            "serial_number": token.serial_number,
            "policy": token.policy,
            "token_b64": token.token_b64(),
        },
    )
    return {
        "stamped_head_hash": head_hash,
        "tsa_url": token.tsa_url,
        "gen_time": token.gen_time,
        "serial_number": token.serial_number,
        "policy": token.policy,
        "audit_event_seq": event.seq,
    }


@router.get("/verify")
def verify_audit(
    session: Session = Depends(get_session),
    admin: User = Depends(require_admin),
) -> dict:
    status = audit_service.verify_chain(session)
    return {
        "verified": status.ok,
        "length": status.length,
        "broken_at_seq": status.broken_at_seq,
        "detail": status.detail,
    }


class EvidenceReportRequest(BaseModel):
    question: str
    run_id: uuid.UUID  # invalid UUIDs are rejected with 422 before any DB work
    context: dict | None = None


@router.post("/evidence-report")
def evidence_report(
    req: EvidenceReportRequest,
    session: Session = Depends(get_session),
    user: User = Depends(require_user),
):
    """Run the query, record an export audit event, return a signed PDF.

    Case-level RBAC: caller must hold 'viewer' on `run_id` (else 401/403/404) —
    an evidence export must not be a back door to a case the caller may not see."""
    if not req.question.strip():
        raise HTTPException(status_code=422, detail="question must not be empty")

    # Authorize the caller on the case before any planning, query, or signing.
    authorize_run(session, user, req.run_id)

    # Validate signing config BEFORE doing anything that mutates the audit
    # chain — otherwise the chain would claim an export that never produced a
    # valid signed artifact.
    secret_key = os.getenv("SECRET_KEY")
    if not secret_key:
        raise HTTPException(
            status_code=500,
            detail="SECRET_KEY not configured — cannot sign the evidence export.",
        )

    plan, planner = plan_question(req.question, req.context)
    answer = run_plan(
        session, plan, req.run_id, question=req.question, planner=planner
    ).to_dict()

    # Record the export, committing to the content hash, then build the PDF that
    # cites the resulting chain head. The audit head is folded into the signed
    # payload so the chain-of-custody pointer cannot be edited post-hoc.
    from ingest.services.evidence_report import content_hash

    event = audit_service.record(
        session,
        "export",
        payload={
            "question": req.question,
            "content_hash": content_hash(answer),
            "total": answer["total"],
        },
        run_id=req.run_id,
        user_id=user.id,  # chain-of-custody: WHO exported
    )
    pdf = build_evidence_pdf(answer, secret_key, audit_head_hash=event.entry_hash)

    return StreamingResponse(
        BytesIO(pdf),
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="evidence_report.pdf"'},
    )
