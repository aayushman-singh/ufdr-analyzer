"""Cross-case entity-graph link-analysis endpoints.

- GET  /link-graph          -> provenance-cited graph over one or more cases
- POST /link-graph/export   -> court-defensible signed artifact (JSON or PDF),
                               recorded as an `export` event in the audit chain

Every edge in the response cites the source rows that prove it. Identifiers seen
across 2+ cases are returned salted-hash (redacted) unless they are the seed.

Auth: both endpoints REQUIRE an authenticated user (Bearer token, see
`auth_service.require_user`) AND case-level RBAC authorization (see
`case_access.authorize_runs`). The caller must hold at least 'viewer' on every
requested case — as the case's implicit owner (`Run.user_id`) or via an explicit
`CaseMembership` grant. The run set is never trusted from the client beyond this
check. This closes the prior membership/PII oracle: an unauthenticated caller is
401, and a caller asking for a case they are not a member of is 403 — they cannot
learn whether an entity appears across someone else's cases.
"""

import logging
import os
import uuid
from datetime import datetime
from io import BytesIO
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import Session

from database import get_session
from db_setup import User
from ingest.services.audit_service import audit_service
from ingest.services.auth_service import require_user
from ingest.services.case_access import authorize_runs
from ingest.services.graph_export import (
    build_graph_pdf,
    content_hash,
    signed_artifact,
)
from ingest.services.link_graph_service import (
    DEFAULT_EDGE_LIMIT,
    DEFAULT_NODE_LIMIT,
    MAX_EDGE_LIMIT,
    MAX_NODE_LIMIT,
    LinkGraphService,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/link-graph", tags=["Entity Link Graph"])


def _build(
    session: Session,
    *,
    run_ids,
    seed,
    hops,
    start,
    end,
    authorized_run_ids=None,
    node_limit=DEFAULT_NODE_LIMIT,
    edge_limit=DEFAULT_EDGE_LIMIT,
):
    """Shared build path; maps service errors to 4xx (fail loud, never silent)."""
    try:
        return LinkGraphService(session).build(
            run_ids,
            seed=seed,
            max_hops=hops,
            start=start,
            end=end,
            authorized_run_ids=authorized_run_ids,
            node_limit=node_limit,
            edge_limit=edge_limit,
        )
    except PermissionError as e:
        # Cross-owner set / run not owned by requester — refuse, don't leak.
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        msg = str(e)
        # Nonexistent run -> 404; bad params (empty set, hops, window, too big) -> 422.
        raise HTTPException(
            status_code=404 if "does not exist" in msg else 422, detail=msg
        )
    except RuntimeError as e:
        # Missing CROSS_CASE_SALT — config error, must not be silently degraded.
        raise HTTPException(status_code=500, detail=str(e))


@router.get("")
def get_link_graph(
    run_ids: list[uuid.UUID] = Query(..., description="one or more case run ids"),
    seed: Optional[str] = Query(None, description="entity to center the graph on"),
    hops: int = Query(2, ge=0, le=6, description="neighborhood radius around seed"),
    start: Optional[datetime] = Query(
        None, description="inclusive ISO start of time window"
    ),
    end: Optional[datetime] = Query(
        None, description="inclusive ISO end of time window"
    ),
    node_limit: int = Query(
        DEFAULT_NODE_LIMIT,
        ge=1,
        le=MAX_NODE_LIMIT,
        description="maximum nodes to serialize before marking the graph truncated",
    ),
    edge_limit: int = Query(
        DEFAULT_EDGE_LIMIT,
        ge=1,
        le=MAX_EDGE_LIMIT,
        description="maximum edges to serialize before marking the graph truncated",
    ),
    session: Session = Depends(get_session),
    user: User = Depends(require_user),
) -> dict:
    """The entity link graph over the given cases, optionally centered on a seed
    and/or time-filtered. Every edge carries its source-row citations.

    Scoped by case-level RBAC: the caller must hold at least 'viewer' on every
    requested case (implicit owner or an explicit membership grant). A nonexistent
    case is 404; one the caller may not access is 403 — never an empty-but-revealing
    graph, so the cross-case membership signal is not an oracle."""
    authorized = authorize_runs(session, user, run_ids)
    graph = _build(
        session,
        run_ids=run_ids,
        seed=seed,
        hops=hops,
        start=start,
        end=end,
        authorized_run_ids=authorized,
        node_limit=node_limit,
        edge_limit=edge_limit,
    )
    return graph.to_dict()


class GraphExportRequest(BaseModel):
    run_ids: list[uuid.UUID]
    seed: Optional[str] = None
    hops: int = Field(2, ge=0, le=6)  # same bound as GET — no validation bypass
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    node_limit: int = Field(DEFAULT_NODE_LIMIT, ge=1, le=MAX_NODE_LIMIT)
    edge_limit: int = Field(DEFAULT_EDGE_LIMIT, ge=1, le=MAX_EDGE_LIMIT)
    # No owner_id here: scope is bound to the authenticated caller, not the client.
    format: str = "json"  # "json" (signed artifact) | "pdf" (signed summary)


@router.post("/export")
def export_link_graph(
    req: GraphExportRequest,
    session: Session = Depends(get_session),
    user: User = Depends(require_user),
):
    """Build the graph, record an `export` audit event, and return a signed,
    court-defensible artifact (JSON by default, or a PDF summary).

    Ordering and honesty: signing config is validated before mutating the chain;
    the `export` event commits to the reproducible `content_hash`; the returned
    artifact binds that hash to the resulting chain head. If artifact construction
    fails after the event is recorded, an `export_failed` event is appended (with
    the reason) and the request fails — the chain reflects the true outcome rather
    than claiming an artifact that never existed.
    """
    if req.format not in ("json", "pdf"):
        raise HTTPException(status_code=422, detail="format must be 'json' or 'pdf'")
    secret_key = os.getenv("SECRET_KEY")
    if not secret_key:
        raise HTTPException(
            status_code=500,
            detail="SECRET_KEY not configured — cannot sign the graph export.",
        )

    authorized = authorize_runs(session, user, req.run_ids)
    graph = _build(
        session,
        run_ids=req.run_ids,
        seed=req.seed,
        hops=req.hops,
        start=req.start,
        end=req.end,
        authorized_run_ids=authorized,
        node_limit=req.node_limit,
        edge_limit=req.edge_limit,
    ).to_dict()
    chash = content_hash(graph)

    event = audit_service.record(
        session,
        "export",
        user_id=user.id,  # record WHO exported — chain-of-custody actor
        payload={
            "artifact": "link-graph",
            "content_hash": chash,
            "run_ids": graph["run_ids"],
            "seed": graph["seed"],
            "node_count": graph["node_count"],
            "edge_count": graph["edge_count"],
        },
    )

    try:
        if req.format == "pdf":
            pdf = build_graph_pdf(graph, secret_key, audit_head_hash=event.entry_hash)
            return StreamingResponse(
                BytesIO(pdf),
                media_type="application/pdf",
                headers={
                    "Content-Disposition": 'attachment; filename="link_graph.pdf"'
                },
            )
        return signed_artifact(graph, secret_key, audit_head_hash=event.entry_hash)
    except Exception as e:  # artifact construction failed AFTER the export was logged
        logger.exception("link-graph export artifact construction failed")
        audit_service.record(
            session,
            "export_failed",
            user_id=user.id,
            payload={"artifact": "link-graph", "content_hash": chash, "reason": str(e)},
        )
        raise HTTPException(status_code=500, detail=f"export artifact failed: {e}")
