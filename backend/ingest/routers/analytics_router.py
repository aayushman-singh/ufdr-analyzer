"""Temporal patterns / anomaly endpoints."""
import uuid

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from database import get_session
from ingest.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["Temporal Patterns"])


@router.get("/patterns")
def patterns(run_id: uuid.UUID = Query(...), session: Session = Depends(get_session)) -> dict:
    """Behavioural findings (spikes, late-night, drop-off, bursts, new contacts)
    over a run's message + call timeline, each backed by event citations, plus a
    deterministic English narrative."""
    return AnalyticsService(session).analyze(run_id).to_dict()
