"""Case-level RBAC — the authorization boundary for owner/viewer access (V5).

Authentication (`auth_service.require_user`) answers *who is calling*. This module
answers the next question — *which cases may this caller touch, and at what role* —
so the query, link-graph, and export routes can scope a request to exactly the
cases the user is entitled to.

Access model (deny-by-default, fail loud):
- A `Run` has an implicit owner: `Run.user_id`. That user is "owner" with no row.
- A `CaseMembership` row grants an additional user "owner" or "viewer" on a case.
- Roles are ordered viewer < owner. Read paths (query/graph/export) require at
  least "viewer"; management (grant/revoke) requires "owner".

`authorize_runs` is the single enforcement primitive. A missing run is a 404 (it
cannot be authorized because it does not exist); an existing run the caller lacks
the required role on is a 403. It NEVER returns an empty-but-revealing result — a
caller must not be able to distinguish "case has no data" from "you may not see
this case", which would be a membership oracle.
"""

from __future__ import annotations

import logging
import uuid
from typing import Iterable, Optional

from fastapi import HTTPException, status
from sqlmodel import Session, select

from db_setup import CaseMembership, Run, User

logger = logging.getLogger(__name__)

# Role ordering. A caller satisfies a required role iff their effective role rank
# is >= the requirement. New roles slot in here, never as scattered string checks.
VIEWER = "viewer"
OWNER = "owner"
_ROLE_RANK = {VIEWER: 1, OWNER: 2}


def _rank(role: Optional[str]) -> int:
    """Rank of a caller's *effective* role; 0 (no access) for None.

    Only ever called with None or a value already validated against `_ROLE_RANK`
    (effective roles come from `effective_role`, which raises on a corrupt role;
    required roles are validated by `_require_known_role`). The `get(..., 0)` is a
    belt-and-suspenders floor, not a silent-downgrade path.
    """
    if role is None:
        return 0
    return _ROLE_RANK.get(role, 0)


def _require_known_role(min_role: str) -> None:
    """Guard against a caller passing a typo'd `min_role`.

    Without this, a misspelled requirement (e.g. "owenr") would rank 0 and
    authorize EVERY authenticated user on an existing run — a silent auth bypass.
    A bad requirement is a programming error: fail loud, never downgrade.
    """
    if min_role not in _ROLE_RANK:
        raise ValueError(
            f"invalid min_role {min_role!r}; expected one of {tuple(_ROLE_RANK)}"
        )


def effective_role(session: Session, run: Run, user_id: uuid.UUID) -> Optional[str]:
    """The caller's effective role on `run`, or None if they have no access.

    The implicit owner (`run.user_id`) is "owner" without a membership row. No
    membership row means no access (None) — deny-by-default.

    A membership row whose stored `role` is neither 'viewer' nor 'owner' is
    corrupt RBAC state. Per the no-fallback rule it is NOT silently downgraded to
    "no access" (which would hide the corruption as an ordinary 403): it is logged
    with full context and raised, surfacing as a 500 so the integrity problem is
    seen and fixed rather than masked.
    """
    if str(run.user_id) == str(user_id):
        return OWNER
    membership = session.exec(
        select(CaseMembership).where(
            CaseMembership.run_id == run.id,
            CaseMembership.user_id == user_id,
        )
    ).first()
    if membership is None:
        return None
    if membership.role not in _ROLE_RANK:
        logger.error(
            "rbac: corrupt membership role %r (membership=%s run=%s user=%s)",
            membership.role,
            membership.id,
            run.id,
            user_id,
        )
        raise RuntimeError(
            f"corrupt case-membership role {membership.role!r} for run {run.id}"
        )
    return membership.role


def authorize_run(
    session: Session,
    user: User,
    run_id: uuid.UUID,
    *,
    min_role: str = VIEWER,
) -> Run:
    """Authorize `user` on a single run at `min_role`; return the loaded `Run`.

    Raises 404 if the run does not exist, 403 if the caller lacks the role,
    and ValueError (programming error) if `min_role` is not a known role.
    """
    _require_known_role(min_role)
    run = session.get(Run, run_id)
    if run is None:
        # The run does not exist — a 404 here is not an oracle: it is identical
        # whether or not the caller would have been authorized, because there is
        # nothing to be authorized on.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"run {run_id} does not exist"
        )
    role = effective_role(session, run, user.id)
    if _rank(role) < _rank(min_role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(f"not authorized on case {run_id}: requires role '{min_role}'"),
        )
    return run


def can_access(
    session: Session, user: User, run_id: uuid.UUID, *, min_role: str = VIEWER
) -> bool:
    """Boolean form of authorization — True iff `user` holds >= `min_role` on the run.

    For filtering disclosure rather than gating a request: a nonexistent run or a
    run the caller lacks access to both return False, with no exception. Used to
    redact cross-case results down to the caller's authorized cases.
    """
    _require_known_role(min_role)
    run = session.get(Run, run_id)
    if run is None:
        return False
    return _rank(effective_role(session, run, user.id)) >= _rank(min_role)


def authorize_runs(
    session: Session,
    user: User,
    run_ids: Iterable[uuid.UUID],
    *,
    min_role: str = VIEWER,
) -> set[str]:
    """Authorize `user` on EVERY run in `run_ids` at `min_role`.

    Returns the vetted set of run-id strings (for the caller to pass to the graph
    service as an explicit allowlist). Fails loud on the FIRST unmet run — a 404
    for a nonexistent run, a 403 for one the caller may not access — so a
    cross-case request cannot partially succeed and leak which cases exist.
    """
    vetted: set[str] = set()
    for rid in run_ids:
        authorize_run(session, user, rid, min_role=min_role)
        vetted.add(str(rid))
    return vetted
