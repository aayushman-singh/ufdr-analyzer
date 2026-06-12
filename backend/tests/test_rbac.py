"""E2E tests for case-level RBAC (V5) — owner/viewer authorization.

The headline forensic invariant: a user authorized on case A must be REFUSED
(403) on case B's graph / export / query — never handed an empty-but-revealing
answer. These tests drive the real FastAPI routers through `TestClient` against an
in-memory SQLite DB, exercising the same `require_user` + `authorize_runs` path as
production.

The query route is exercised with the deterministic stub planner (DEMO_MODE=1, no
LLM key) so the test is offline and reproducible.
"""

import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("CROSS_CASE_SALT", "test-cross-case-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
# Drive /query/plan with the deterministic stub planner — offline, reproducible.
os.environ["DEMO_MODE"] = "1"
os.environ.pop("OPENAI_API_KEY", None)

from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import Session, SQLModel, create_engine  # noqa: E402

import db_setup  # noqa: E402,F401
from db_setup import CaseMembership, Message, Run, User  # noqa: E402
from ingest.services.auth_service import create_access_token  # noqa: E402
from ingest.services.case_access import (  # noqa: E402
    OWNER,
    VIEWER,
    authorize_run,
    authorize_runs,
    effective_role,
)

P1 = "+15550100001"
P2 = "+15550100002"


@pytest.fixture(autouse=True)
def _stub_planner_env(monkeypatch):
    """Force the deterministic stub planner for /query/plan.

    `config.load_dotenv` repopulates OPENAI_API_KEY from the repo `.env` at import
    time, so a module-level pop is not enough — delete it (and set DEMO_MODE) per
    test, after imports, since the planner reads these at call time."""
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _user(session, name, email):
    u = User(username=name, email=email, password_hash="x")
    session.add(u)
    session.commit()
    session.refresh(u)
    return u


def _run(session, owner, name="case.ufdr"):
    r = Run(user_id=owner.id, ufdr_file_name=name, status="complete")
    session.add(r)
    session.commit()
    session.refresh(r)
    # A couple of message rows so a query/graph has something to return.
    session.add_all(
        [
            Message(
                run_id=r.id,
                sender=P1,
                receiver=P2,
                timestamp=datetime(2024, 1, 1),
                content="move the bitcoin tonight",
            ),
            Message(
                run_id=r.id,
                sender=P2,
                receiver=P1,
                timestamp=datetime(2024, 1, 2),
                content="ok",
            ),
        ]
    )
    session.commit()
    return r


@pytest.fixture()
def world(session):
    """Two owners, two cases. alice owns A, bob owns B; mallory owns nothing."""
    alice = _user(session, "Alice", "alice@x.gov")
    bob = _user(session, "Bob", "bob@x.gov")
    mallory = _user(session, "Mallory", "m@x.gov")
    a = _run(session, alice, "A.ufdr")
    b = _run(session, bob, "B.ufdr")
    return {"alice": alice, "bob": bob, "mallory": mallory, "A": a, "B": b}


def _client(session):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from database import get_session
    from ingest.routers import (
        case_access_router,
        link_graph_router,
        query_plan_router,
    )

    app = FastAPI()
    app.include_router(link_graph_router.router)
    app.include_router(query_plan_router.router)
    app.include_router(case_access_router.router)
    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app, raise_server_exceptions=False)


def _auth(user):
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


# -- unit: effective role + authorize ---------------------------------------
def test_implicit_owner_is_owner(session, world):
    assert effective_role(session, world["A"], world["alice"].id) == OWNER


def test_non_member_has_no_role(session, world):
    assert effective_role(session, world["A"], world["mallory"].id) is None


def test_granted_viewer_role(session, world):
    session.add(
        CaseMembership(run_id=world["A"].id, user_id=world["bob"].id, role=VIEWER)
    )
    session.commit()
    assert effective_role(session, world["A"], world["bob"].id) == VIEWER


def test_corrupt_stored_role_fails_loud(session, world):
    """A corrupt/unknown role is data-integrity failure -> raise (no-fallback),
    never a silent downgrade to 'no access' that hides the corruption."""
    session.add(
        CaseMembership(run_id=world["A"].id, user_id=world["bob"].id, role="superuser")
    )
    session.commit()
    with pytest.raises(RuntimeError, match="corrupt case-membership role"):
        effective_role(session, world["A"], world["bob"].id)


def test_authorize_runs_missing_run_is_404(session, world):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as ei:
        authorize_run(session, world["alice"], uuid.uuid4())
    assert ei.value.status_code == 404


def test_authorize_runs_non_member_is_403(session, world):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as ei:
        authorize_runs(session, world["mallory"], [world["A"].id])
    assert ei.value.status_code == 403


def test_unknown_required_role_fails_loud(session, world):
    with pytest.raises(ValueError, match="invalid min_role"):
        authorize_run(session, world["alice"], world["A"].id, min_role="owenr")


# -- link-graph route: the headline cross-case refusal ----------------------
def test_owner_can_graph_own_case(session, world):
    c = _client(session)
    res = c.get(
        "/link-graph",
        params={"run_ids": [str(world["A"].id)]},
        headers=_auth(world["alice"]),
    )
    assert res.status_code == 200
    assert res.json()["edge_count"] >= 1


def test_user_authorized_on_A_is_403_on_B(session, world):
    """Alice owns A but has NO role on B -> B's graph is refused, not emptied."""
    c = _client(session)
    res = c.get(
        "/link-graph",
        params={"run_ids": [str(world["B"].id)]},
        headers=_auth(world["alice"]),
    )
    assert res.status_code == 403


def test_user_authorized_on_A_is_403_on_B_export(session, world):
    c = _client(session)
    res = c.post(
        "/link-graph/export",
        json={"run_ids": [str(world["B"].id)], "format": "json"},
        headers=_auth(world["alice"]),
    )
    assert res.status_code == 403


def test_non_member_cannot_query_case(session, world):
    c = _client(session)
    res = c.post(
        "/query/plan",
        json={"question": "any bitcoin chatter?", "run_id": str(world["A"].id)},
        headers=_auth(world["mallory"]),
    )
    assert res.status_code == 403


def test_query_without_token_is_401(session, world):
    c = _client(session)
    res = c.post(
        "/query/plan", json={"question": "bitcoin", "run_id": str(world["A"].id)}
    )
    assert res.status_code == 401


# -- grant -> viewer can now read; revoke -> access removed -----------------
def test_grant_then_viewer_can_graph_query_export(session, world):
    c = _client(session)
    # Alice (owner of A) grants Bob viewer on A.
    g = c.post(
        f"/cases/{world['A'].id}/members",
        json={"user_id": str(world["bob"].id), "role": "viewer"},
        headers=_auth(world["alice"]),
    )
    assert g.status_code == 201

    # Bob can now graph, query, and export case A.
    assert (
        c.get(
            "/link-graph",
            params={"run_ids": [str(world["A"].id)]},
            headers=_auth(world["bob"]),
        ).status_code
        == 200
    )
    assert (
        c.post(
            "/query/plan",
            json={"question": "bitcoin", "run_id": str(world["A"].id)},
            headers=_auth(world["bob"]),
        ).status_code
        == 200
    )
    assert (
        c.post(
            "/link-graph/export",
            json={"run_ids": [str(world["A"].id)], "format": "json"},
            headers=_auth(world["bob"]),
        ).status_code
        == 200
    )


def test_revoke_removes_access(session, world):
    c = _client(session)
    c.post(
        f"/cases/{world['A'].id}/members",
        json={"user_id": str(world["bob"].id), "role": "viewer"},
        headers=_auth(world["alice"]),
    )
    assert (
        c.get(
            "/link-graph",
            params={"run_ids": [str(world["A"].id)]},
            headers=_auth(world["bob"]),
        ).status_code
        == 200
    )
    d = c.request(
        "DELETE",
        f"/cases/{world['A'].id}/members/{world['bob'].id}",
        headers=_auth(world["alice"]),
    )
    assert d.status_code == 204
    assert (
        c.get(
            "/link-graph",
            params={"run_ids": [str(world["A"].id)]},
            headers=_auth(world["bob"]),
        ).status_code
        == 403
    )


# -- cross-owner viewer: combined graph allowed when authorized on both ------
def test_viewer_on_both_owners_cases_can_combine(session, world):
    c = _client(session)
    # Bob owns B; Alice grants Bob viewer on A. Bob is now authorized on A AND B.
    c.post(
        f"/cases/{world['A'].id}/members",
        json={"user_id": str(world["bob"].id), "role": "viewer"},
        headers=_auth(world["alice"]),
    )
    res = c.get(
        "/link-graph",
        params={"run_ids": [str(world["A"].id), str(world["B"].id)]},
        headers=_auth(world["bob"]),
    )
    assert res.status_code == 200  # cross-owner allowed under RBAC


def test_combined_graph_refused_without_both_grants(session, world):
    """Bob owns B only; combining [A, B] without a grant on A is 403."""
    c = _client(session)
    res = c.get(
        "/link-graph",
        params={"run_ids": [str(world["A"].id), str(world["B"].id)]},
        headers=_auth(world["bob"]),
    )
    assert res.status_code == 403


# -- management authorization ------------------------------------------------
def test_non_owner_cannot_grant(session, world):
    c = _client(session)
    res = c.post(
        f"/cases/{world['A'].id}/members",
        json={"user_id": str(world["mallory"].id), "role": "viewer"},
        headers=_auth(world["bob"]),
    )  # Bob is not owner of A
    assert res.status_code == 403


def test_viewer_cannot_grant(session, world):
    c = _client(session)
    c.post(
        f"/cases/{world['A'].id}/members",
        json={"user_id": str(world["bob"].id), "role": "viewer"},
        headers=_auth(world["alice"]),
    )
    # Bob is now a viewer on A — viewers may not grant.
    res = c.post(
        f"/cases/{world['A'].id}/members",
        json={"user_id": str(world["mallory"].id), "role": "viewer"},
        headers=_auth(world["bob"]),
    )
    assert res.status_code == 403


def test_owner_grant_can_then_manage(session, world):
    """A granted 'owner' can manage members too."""
    c = _client(session)
    c.post(
        f"/cases/{world['A'].id}/members",
        json={"user_id": str(world["bob"].id), "role": "owner"},
        headers=_auth(world["alice"]),
    )
    res = c.post(
        f"/cases/{world['A'].id}/members",
        json={"user_id": str(world["mallory"].id), "role": "viewer"},
        headers=_auth(world["bob"]),
    )
    assert res.status_code == 201


def test_grant_validation(session, world):
    c = _client(session)
    a = world["A"].id
    h = _auth(world["alice"])
    # bad role -> 422
    assert (
        c.post(
            f"/cases/{a}/members",
            json={"user_id": str(world["bob"].id), "role": "root"},
            headers=h,
        ).status_code
        == 422
    )
    # unknown target user -> 404
    assert (
        c.post(
            f"/cases/{a}/members",
            json={"user_id": str(uuid.uuid4()), "role": "viewer"},
            headers=h,
        ).status_code
        == 404
    )
    # granting the implicit owner -> 409
    assert (
        c.post(
            f"/cases/{a}/members",
            json={"user_id": str(world["alice"].id), "role": "viewer"},
            headers=h,
        ).status_code
        == 409
    )


def test_list_members_owner_only(session, world):
    c = _client(session)
    a = world["A"].id
    c.post(
        f"/cases/{a}/members",
        json={"user_id": str(world["bob"].id), "role": "viewer"},
        headers=_auth(world["alice"]),
    )
    # owner sees the implicit owner + the viewer
    res = c.get(f"/cases/{a}/members", headers=_auth(world["alice"]))
    assert res.status_code == 200
    body = res.json()
    assert {m["user_id"] for m in body} == {
        str(world["alice"].id),
        str(world["bob"].id),
    }
    assert any(m["implicit"] and m["role"] == "owner" for m in body)
    # the viewer themselves may not list (owner-only)
    assert c.get(f"/cases/{a}/members", headers=_auth(world["bob"])).status_code == 403
