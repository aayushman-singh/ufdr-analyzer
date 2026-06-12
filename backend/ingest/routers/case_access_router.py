"""Case membership management — grant / list / revoke per-case roles (V5 RBAC).

This is the control plane for case-level access: a case owner shares a case with
another investigating officer at a named role, so that officer can then query,
graph, and export it. Without this, RBAC grants would be unreachable — the
enforcement points (`case_access.authorize_runs`) would only ever see implicit
owners.

Authorization (fail loud, deny-by-default):
- Only a caller who holds 'owner' on the case (implicit owner or an owner grant)
  may grant, list, or revoke memberships. A viewer or non-member is refused 403.
- The implicit owner (`Run.user_id`) cannot be demoted or revoked here — their
  ownership is intrinsic to the run, not a membership row.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session, select

from database import get_session
from db_setup import CaseMembership, User
from ingest.services.auth_service import require_user
from ingest.services.case_access import OWNER, VIEWER, authorize_run

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/cases", tags=["Case Access (RBAC)"])

_VALID_ROLES = (VIEWER, OWNER)


class GrantRequest(BaseModel):
    user_id: uuid.UUID
    role: str  # "viewer" | "owner"


class MemberView(BaseModel):
    user_id: str
    role: str
    implicit: bool  # True for the run's intrinsic owner (no membership row)


@router.get("/{run_id}/members", response_model=list[MemberView])
def list_members(
    run_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: User = Depends(require_user),
) -> list[MemberView]:
    """List everyone with access to the case. Owner-only."""
    run = authorize_run(session, user, run_id, min_role=OWNER)
    members = [MemberView(user_id=str(run.user_id), role=OWNER, implicit=True)]
    rows = session.exec(
        select(CaseMembership).where(CaseMembership.run_id == run_id)
    ).all()
    for m in rows:
        members.append(MemberView(user_id=str(m.user_id), role=m.role, implicit=False))
    return members


@router.post("/{run_id}/members", status_code=status.HTTP_201_CREATED)
def grant_member(
    run_id: uuid.UUID,
    req: GrantRequest,
    session: Session = Depends(get_session),
    user: User = Depends(require_user),
) -> dict:
    """Grant (or update) another user's role on the case. Owner-only.

    Fails loud: an unknown role is 422, an unknown target user is 404, and trying
    to grant a membership to the case's implicit owner is 409 (their ownership is
    intrinsic, not a grant)."""
    if req.role not in _VALID_ROLES:
        raise HTTPException(
            status_code=422,
            detail=f"role must be one of {_VALID_ROLES}, got {req.role!r}",
        )
    run = authorize_run(session, user, run_id, min_role=OWNER)
    if session.get(User, req.user_id) is None:
        raise HTTPException(
            status_code=404, detail=f"user {req.user_id} does not exist"
        )
    if str(req.user_id) == str(run.user_id):
        raise HTTPException(
            status_code=409,
            detail="user is the case's implicit owner; ownership is intrinsic",
        )

    existing = session.exec(
        select(CaseMembership).where(
            CaseMembership.run_id == run_id,
            CaseMembership.user_id == req.user_id,
        )
    ).first()
    if existing is None:
        membership = CaseMembership(
            run_id=run_id, user_id=req.user_id, role=req.role, granted_by=user.id
        )
        session.add(membership)
    else:
        existing.role = req.role
        existing.granted_by = user.id
        session.add(existing)
    session.commit()
    logger.info(
        "rbac: %s granted %s '%s' on case %s", user.id, req.user_id, req.role, run_id
    )
    return {"run_id": str(run_id), "user_id": str(req.user_id), "role": req.role}


@router.delete("/{run_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_member(
    run_id: uuid.UUID,
    member_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: User = Depends(require_user),
) -> None:
    """Revoke a user's membership on the case. Owner-only.

    The implicit owner cannot be revoked (409). Revoking a user who has no
    membership row is a 404 — the caller is told their assumption was wrong rather
    than getting a silent no-op."""
    run = authorize_run(session, user, run_id, min_role=OWNER)
    if str(member_id) == str(run.user_id):
        raise HTTPException(
            status_code=409,
            detail="cannot revoke the case's implicit owner",
        )
    membership = session.exec(
        select(CaseMembership).where(
            CaseMembership.run_id == run_id,
            CaseMembership.user_id == member_id,
        )
    ).first()
    if membership is None:
        raise HTTPException(
            status_code=404, detail=f"user {member_id} has no membership on this case"
        )
    session.delete(membership)
    session.commit()
    logger.info("rbac: %s revoked %s on case %s", user.id, member_id, run_id)
