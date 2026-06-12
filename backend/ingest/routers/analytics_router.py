"""Temporal patterns / anomaly endpoints."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from database import get_session
from db_setup import User
from ingest.services.analytics_service import AnalyticsService
from ingest.services.auth_service import require_user
from ingest.services.case_access import authorize_run

router = APIRouter(prefix="/analytics", tags=["Temporal Patterns"])


@router.get("/patterns")
def patterns(
    run_id: uuid.UUID = Query(...),
    session: Session = Depends(get_session),
    user: User = Depends(require_user),
) -> dict:
    """Behavioural findings (spikes, late-night, drop-off, bursts, new contacts)
    over a run's message + call timeline, each backed by event citations, plus a
    deterministic English narrative.

    Case-level RBAC: caller must hold 'viewer' on the run (else 401/403/404)."""
    authorize_run(session, user, run_id)
    return AnalyticsService(session).analyze(run_id).to_dict()
