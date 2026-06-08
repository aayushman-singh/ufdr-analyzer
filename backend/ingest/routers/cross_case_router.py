"""Cross-case entity-linking endpoints (PII-minimized salted-hash index)."""
import uuid

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from database import get_session
from ingest.services.cross_case_service import CrossCaseService

router = APIRouter(prefix="/cross-case", tags=["Cross-Case Linking"])


@router.post("/index")
def index_run(run_id: uuid.UUID = Query(...), session: Session = Depends(get_session)) -> dict:
    """Build/refresh the cross-case identifier index for a run."""
    count = CrossCaseService(session).index_run(run_id)
    return {"run_id": str(run_id), "indexed_identifiers": count}


@router.get("/links")
def links(run_id: uuid.UUID = Query(...), session: Session = Depends(get_session)) -> dict:
    """Identifiers in this run that also appear in other indexed cases."""
    found = CrossCaseService(session).links_for_run(run_id)
    return {
        "run_id": str(run_id),
        "link_count": len(found),
        "links": [
            {
                "identifier": l.identifier,
                "identifier_type": l.identifier_type,
                "also_in_runs": l.also_in_runs,
                "case_count": l.case_count,
            }
            for l in found
        ],
    }


@router.get("/lookup")
def lookup(identifier: str = Query(..., description="phone number or email"),
           session: Session = Depends(get_session)) -> dict:
    """Which cases contain this identifier (matched by salted hash)?"""
    return CrossCaseService(session).lookup(identifier)
