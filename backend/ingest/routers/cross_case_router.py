"""Cross-case entity-linking endpoints (PII-minimized salted-hash index).

Both endpoints are run-scoped and gated by case-level RBAC: the caller must be
authenticated and hold at least 'viewer' on the run. `/links` in particular is a
cross-case membership signal, so an unauthorized caller is refused (401/403) — it
must never become an oracle for whether an entity recurs across someone's cases.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from database import get_session
from db_setup import User
from ingest.services.auth_service import require_user
from ingest.services.case_access import authorize_run, can_access
from ingest.services.cross_case_service import CrossCaseService

router = APIRouter(prefix="/cross-case", tags=["Cross-Case Linking"])


@router.post("/index")
def index_run(
    run_id: uuid.UUID = Query(...),
    session: Session = Depends(get_session),
    user: User = Depends(require_user),
) -> dict:
    """Build/refresh the cross-case identifier index for a run."""
    authorize_run(session, user, run_id)
    try:
        count = CrossCaseService(session).index_run(run_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"run_id": str(run_id), "indexed_identifiers": count}


@router.get("/links")
def links(
    run_id: uuid.UUID = Query(...),
    session: Session = Depends(get_session),
    user: User = Depends(require_user),
) -> dict:
    """Identifiers in this run that also appear in other indexed cases.

    Only a run's OWN identifiers can be linked — there is deliberately no
    arbitrary-identifier lookup, which would be a cross-case membership oracle.
    The salted hash is never returned.
    """
    authorize_run(session, user, run_id)
    try:
        found = CrossCaseService(session).links_for_run(run_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    visible_links = []
    for link in found:
        visible_runs = [
            rid
            for rid in link.also_in_runs
            if can_access(session, user, uuid.UUID(str(rid)))
        ]
        if visible_runs:
            visible_links.append(
                {
                    "identifier": link.identifier,
                    "identifier_type": link.identifier_type,
                    "also_in_runs": sorted(visible_runs),
                    "case_count": 1 + len(visible_runs),
                }
            )

    return {
        "run_id": str(run_id),
        "link_count": len(visible_links),
        "links": visible_links,
    }
