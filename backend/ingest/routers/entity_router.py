"""Entity-graph endpoints backed by Postgres recursive CTE (slim demo profile)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from database import get_session
from db_setup import User
from ingest.services.auth_service import require_user
from ingest.services.case_access import authorize_run
from ingest.services.entity_service import EntityService

router = APIRouter(prefix="/entities", tags=["Entity Graph"])


@router.get("/graph")
def entity_graph(
    run_id: uuid.UUID = Query(...),
    session: Session = Depends(get_session),
    user: User = Depends(require_user),
) -> dict:
    """Full participant graph (who contacted whom) for a run.

    Case-level RBAC: caller must hold 'viewer' on the run (else 401/403/404)."""
    authorize_run(session, user, run_id)
    return EntityService(session).build_graph(run_id).to_dict()


@router.get("/neighborhood")
def entity_neighborhood(
    run_id: uuid.UUID = Query(...),
    seed: str = Query(..., description="participant identifier (phone/handle)"),
    hops: int = Query(2, ge=0, le=6),
    session: Session = Depends(get_session),
    user: User = Depends(require_user),
) -> dict:
    """Entities within `hops` of `seed`, via recursive CTE traversal."""
    authorize_run(session, user, run_id)
    try:
        return EntityService(session).neighborhood(run_id, seed, hops).to_dict()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
