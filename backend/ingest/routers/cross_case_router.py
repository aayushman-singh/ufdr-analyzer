"""Cross-case entity-linking endpoints (PII-minimized salted-hash index)."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from database import get_session
from ingest.services.cross_case_service import CrossCaseService

router = APIRouter(prefix="/cross-case", tags=["Cross-Case Linking"])


@router.post("/index")
def index_run(run_id: uuid.UUID = Query(...), session: Session = Depends(get_session)) -> dict:
    """Build/refresh the cross-case identifier index for a run."""
    try:
        count = CrossCaseService(session).index_run(run_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"run_id": str(run_id), "indexed_identifiers": count}


@router.get("/links")
def links(run_id: uuid.UUID = Query(...), session: Session = Depends(get_session)) -> dict:
    """Identifiers in this run that also appear in other indexed cases.

    Only a run's OWN identifiers can be linked — there is deliberately no
    arbitrary-identifier lookup, which would be a cross-case membership oracle.
    The salted hash is never returned.
    """
    try:
        found = CrossCaseService(session).links_for_run(run_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
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
