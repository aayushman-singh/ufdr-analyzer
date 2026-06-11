"""E2E tests for the cross-case entity link graph (SQLite).

Forensic invariants under test:
- Provenance integrity: every edge cites >=1 real source row in the named run.
- Determinism: same evidence + params -> identical graph and identical content hash.
- Cross-case PII: an identifier in 2+ cases is redacted to its salted hash, unless
  it is the user-supplied seed.
- Time filtering, seed neighborhood, signed-export verification + tamper detection.
- Fail-loud on bad input / missing config (no silent fallbacks).
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

from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import Session, SQLModel, create_engine  # noqa: E402

import db_setup  # noqa: E402,F401
from db_setup import Call, Contact, Message, Run, User  # noqa: E402
from ingest.services.graph_export import (  # noqa: E402
    content_hash,
    sign,
    signed_artifact,
    build_graph_pdf,
)
from ingest.services.link_graph_service import (  # noqa: E402
    LinkGraphService,
    entity_key,
)

# Identifiers used across the fixture.
P1 = "+1 (555) 010-0001"  # appears in BOTH runs -> cross-case
P2 = "+15550100002"  # run A only
P3 = "+15550100003"  # run A only
P9 = "+15550100009"  # run B only


@pytest.fixture()
def session():
    # StaticPool shares one in-memory DB across connections/threads — required so
    # the TestClient route tests (endpoint runs in a worker thread) see the tables.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture()
def runs(session):
    """Two cases owned by one IO; P1 is shared across them."""
    u = User(username="IO", email="io@x.gov", password_hash="x")
    session.add(u)
    session.commit()
    session.refresh(u)

    a = Run(user_id=u.id, ufdr_file_name="a.ufdr", status="complete")
    b = Run(user_id=u.id, ufdr_file_name="b.ufdr", status="complete")
    session.add_all([a, b])
    session.commit()
    session.refresh(a)
    session.refresh(b)

    session.add_all(
        [
            # Run A: P1<->P2 twice (Jan), P2<->P3 call (Mar), Alice = P1
            Message(
                run_id=a.id,
                sender=P1,
                receiver=P2,
                timestamp=datetime(2024, 1, 1),
                content="hi",
            ),
            Message(
                run_id=a.id,
                sender=P2,
                receiver=P1,
                timestamp=datetime(2024, 1, 2),
                content="yo",
            ),
            Call(
                run_id=a.id,
                caller=P2,
                receiver=P3,
                timestamp=datetime(2024, 3, 1),
                duration=30,
            ),
            Contact(run_id=a.id, name="Alice", number=P1),
            # Run B: P1<->P9 call (Jan)
            Call(
                run_id=b.id,
                caller=P1,
                receiver=P9,
                timestamp=datetime(2024, 1, 5),
                duration=12,
            ),
        ]
    )
    session.commit()
    return a.id, b.id


# -- provenance --------------------------------------------------------------
def test_every_edge_has_real_citations(session, runs):
    a, _ = runs
    g = LinkGraphService(session).build([a])
    assert g.edges, "expected edges in run A"
    valid_msg = {
        str(m.id) for m in session.exec(__import__("sqlmodel").select(Message)).all()
    }
    valid_call = {
        str(c.id) for c in session.exec(__import__("sqlmodel").select(Call)).all()
    }
    for e in g.edges:
        assert e.citations, "every edge MUST cite at least one source row"
        assert e.weight == len(e.citations)
        for c in e.citations:
            assert c.run_id == str(a)
            pool = valid_msg if c.source_table == "message" else valid_call
            assert c.row_id in pool, "citation must point to a real row"


def test_edge_weight_collapses_repeated_interactions(session, runs):
    a, _ = runs
    g = LinkGraphService(session).build([a])
    k1 = entity_key(P1)[0]
    k2 = entity_key(P2)[0]
    lo, hi = sorted([k1, k2])
    edge = next(e for e in g.edges if e.source == lo and e.target == hi)
    assert edge.weight == 2  # two messages P1<->P2


def test_contact_label_resolves(session, runs):
    a, _ = runs
    g = LinkGraphService(session).build([a])
    k1 = entity_key(P1)[0]
    n1 = next(n for n in g.nodes if n.id == k1)
    assert n1.label == "Alice"  # P1 disclosed (single case in this scope)


# -- cross-case redaction ----------------------------------------------------
def test_shared_identifier_redacted_across_cases(session, runs):
    a, b = runs
    g = LinkGraphService(session).build([a, b])
    k1 = entity_key(P1)[0]
    n1 = next(n for n in g.nodes if n.id == k1)
    assert n1.redacted is True
    assert n1.value is None and n1.label is None
    assert n1.case_count == 2 and n1.cases == sorted([str(a), str(b)])
    # single-case node still discloses its value
    k9 = entity_key(P9)[0]
    n9 = next(n for n in g.nodes if n.id == k9)
    assert n9.redacted is False and n9.value == "15550100009"


def test_seed_is_disclosed_even_when_cross_case(session, runs):
    a, b = runs
    g = LinkGraphService(session).build([a, b], seed=P1, max_hops=2)
    k1 = entity_key(P1)[0]
    n1 = next(n for n in g.nodes if n.id == k1)
    assert n1.redacted is False  # seed supplied by querier -> disclosed
    assert n1.value == "15550100001"
    assert g.seed_found is True and g.seed_id == k1


def test_citations_carry_no_pii(session, runs):
    a, b = runs
    g = LinkGraphService(session).build([a, b])
    for e in g.edges:
        for c in e.citations:
            # only internal ids + timestamp, never a raw identifier
            assert set(c.__dict__) == {"run_id", "source_table", "row_id", "timestamp"}


# -- seed neighborhood -------------------------------------------------------
def test_seed_zero_hops_is_seed_only(session, runs):
    a, b = runs
    g = LinkGraphService(session).build([a, b], seed=P1, max_hops=0)
    assert {n.id for n in g.nodes} == {entity_key(P1)[0]}
    assert g.edges == []


def test_seed_one_hop_reaches_cross_case_neighbors(session, runs):
    a, b = runs
    g = LinkGraphService(session).build([a, b], seed=P1, max_hops=1)
    ids = {n.id for n in g.nodes}
    assert ids == {entity_key(P1)[0], entity_key(P2)[0], entity_key(P9)[0]}
    # P3 is 2 hops from P1 (via P2) -> excluded at hops=1
    assert entity_key(P3)[0] not in ids


def test_seed_not_found(session, runs):
    a, _ = runs
    g = LinkGraphService(session).build([a], seed="+19999999999", max_hops=2)
    assert g.seed_found is False
    assert g.nodes == [] and g.edges == []


# -- time filter -------------------------------------------------------------
def test_time_window_excludes_out_of_range(session, runs):
    a, _ = runs
    # Only the Mar call survives a Feb-onward window.
    g = LinkGraphService(session).build([a], start=datetime(2024, 2, 1))
    pairs = {(e.source, e.target) for e in g.edges}
    k2, k3 = entity_key(P2)[0], entity_key(P3)[0]
    assert pairs == {tuple(sorted([k2, k3]))}


# -- determinism -------------------------------------------------------------
def test_graph_is_deterministic(session, runs):
    a, b = runs
    svc = LinkGraphService(session)
    g1 = svc.build([a, b], seed=P1, max_hops=2).to_dict()
    g2 = svc.build([b, a], seed=P1, max_hops=2).to_dict()  # run order swapped
    assert g1 == g2
    assert content_hash(g1) == content_hash(g2)


def test_content_hash_changes_on_tamper(session, runs):
    a, b = runs
    g = LinkGraphService(session).build([a, b]).to_dict()
    h0 = content_hash(g)
    g["edges"][0]["weight"] += 1  # tamper
    assert content_hash(g) != h0


# -- signed export -----------------------------------------------------------
def test_signed_artifact_verifies(session, runs):
    a, b = runs
    g = LinkGraphService(session).build([a, b], seed=P1).to_dict()
    art = signed_artifact(g, "k", audit_head_hash="deadbeef")
    # content_hash is head-INDEPENDENT (reproducible); signature binds the head.
    assert art["content_hash"] == content_hash(g)
    assert art["signature"] == sign(g, "k", audit_head_hash="deadbeef")
    # different key, different head, or tampered graph all break verification
    assert art["signature"] != sign(g, "other-key", audit_head_hash="deadbeef")
    assert art["signature"] != sign(g, "k", audit_head_hash="cafe")


def test_content_hash_is_head_independent(session, runs):
    a, b = runs
    g = LinkGraphService(session).build([a, b], seed=P1).to_dict()
    # Two exports of the same evidence -> same content hash, different signatures.
    assert content_hash(g) == content_hash(g)
    assert sign(g, "k", "head1") != sign(g, "k", "head2")


def test_graph_pdf_is_nonempty_pdf(session, runs):
    a, b = runs
    g = LinkGraphService(session).build([a, b], seed=P1).to_dict()
    pdf = build_graph_pdf(g, "k", audit_head_hash="deadbeef")
    assert pdf[:5] == b"%PDF-" and len(pdf) > 800


# -- fail loud ---------------------------------------------------------------
def test_empty_run_set_fails_loud(session):
    with pytest.raises(ValueError, match="run_ids must not be empty"):
        LinkGraphService(session).build([])


def test_nonexistent_run_fails_loud(session):
    with pytest.raises(ValueError, match="does not exist"):
        LinkGraphService(session).build([uuid.uuid4()])


def test_negative_hops_fails_loud(session, runs):
    a, _ = runs
    with pytest.raises(ValueError, match="max_hops"):
        LinkGraphService(session).build([a], seed=P1, max_hops=-1)


def test_missing_salt_fails_loud(monkeypatch):
    monkeypatch.delenv("CROSS_CASE_SALT", raising=False)
    with pytest.raises(RuntimeError, match="CROSS_CASE_SALT"):
        entity_key("+15550100001")


def test_reversed_time_window_fails_loud(session, runs):
    a, _ = runs
    with pytest.raises(ValueError, match="start must be <= end"):
        LinkGraphService(session).build(
            [a], start=datetime(2024, 3, 1), end=datetime(2024, 1, 1)
        )


# -- ownership / tenancy -----------------------------------------------------
def test_graph_refuses_to_span_two_owners(session):
    u1 = User(username="IO1", email="io1@x.gov", password_hash="x")
    u2 = User(username="IO2", email="io2@x.gov", password_hash="x")
    session.add_all([u1, u2])
    session.commit()
    session.refresh(u1)
    session.refresh(u2)
    r1 = Run(user_id=u1.id, ufdr_file_name="1.ufdr", status="complete")
    r2 = Run(user_id=u2.id, ufdr_file_name="2.ufdr", status="complete")
    session.add_all([r1, r2])
    session.commit()
    session.refresh(r1)
    session.refresh(r2)
    with pytest.raises(PermissionError, match="same owner"):
        LinkGraphService(session).build([r1.id, r2.id])


def test_owner_id_must_match(session, runs):
    a, _ = runs
    with pytest.raises(PermissionError, match="does not belong"):
        LinkGraphService(session).build([a], owner_id=uuid.uuid4())


# -- opaque ids (no raw HMAC / EntityIndex key leak) -------------------------
def test_node_id_is_not_the_raw_hmac(session, runs):
    """Node id is sha256(HMAC), never the cross-case index key itself."""
    import hashlib
    import hmac as _hmac

    a, _ = runs
    g = LinkGraphService(session).build([a])
    key = os.environ["CROSS_CASE_SALT"].encode()
    raw_hmac = _hmac.new(key, b"15550100002", hashlib.sha256).hexdigest()
    ids = {n.id for n in g.nodes}
    assert raw_hmac not in ids  # raw index key never exposed
    assert hashlib.sha256(raw_hmac.encode()).hexdigest() in ids  # wrapped id is


# -- citation cap honesty ----------------------------------------------------
def test_citation_cap_keeps_true_weight(session, monkeypatch):
    import ingest.services.link_graph_service as svc_mod

    monkeypatch.setattr(svc_mod, "MAX_EDGE_CITATIONS", 3)
    u = User(username="IO", email="io@x.gov", password_hash="x")
    session.add(u)
    session.commit()
    session.refresh(u)
    r = Run(user_id=u.id, ufdr_file_name="c.ufdr", status="complete")
    session.add(r)
    session.commit()
    session.refresh(r)
    for i in range(10):  # 10 interactions on one edge
        session.add(
            Message(
                run_id=r.id,
                sender=P1,
                receiver=P2,
                timestamp=datetime(2024, 1, 1),
                content=str(i),
            )
        )
    session.commit()
    g = LinkGraphService(session).build([r.id]).to_dict()
    edge = g["edges"][0]
    assert edge["weight"] == 10  # honest total preserved
    assert edge["citations_shown"] == 3  # only the cap is serialized
    assert edge["citations_truncated"] is True


# -- HTTP route contract (TestClient) ----------------------------------------
def _client(session, *, token: str | None = None):
    """Test client for the link-graph router.

    `require_user` (a dependency of both endpoints) itself depends on
    `get_session`, so overriding it routes auth lookups at the same in-memory DB.
    Pass `token` to authenticate every request with a Bearer header.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from database import get_session
    from ingest.routers import link_graph_router

    app = FastAPI()
    app.include_router(link_graph_router.router)
    app.dependency_overrides[get_session] = lambda: session
    headers = {"Authorization": f"Bearer {token}"} if token else None
    return TestClient(app, raise_server_exceptions=False, headers=headers)


def _owner_token(session, run_id):
    """Mint a bearer token for the user who owns `run_id`."""
    from db_setup import Run
    from ingest.services.auth_service import create_access_token

    owner_id = session.get(Run, run_id).user_id
    return create_access_token(owner_id)


def test_route_get_returns_cited_graph(session, runs):
    a, _ = runs
    c = _client(session, token=_owner_token(session, a))
    res = c.get("/link-graph", params={"run_ids": [str(a)]})
    assert res.status_code == 200
    body = res.json()
    assert body["edge_count"] >= 1
    for e in body["edges"]:
        assert e["weight"] >= 1
        assert e["citations"], "edge must carry provenance over the wire"


def test_route_get_nonexistent_run_is_404(session):
    # An authenticated user is required even to get a 404 — auth precedes scoping.
    from db_setup import User
    from ingest.services.auth_service import create_access_token

    u = User(username="IO", email="io@x.gov", password_hash="x")
    session.add(u)
    session.commit()
    session.refresh(u)
    c = _client(session, token=create_access_token(u.id))
    res = c.get("/link-graph", params={"run_ids": [str(uuid.uuid4())]})
    assert res.status_code == 404


def test_route_export_json_is_signed_and_audited(session, runs):
    a, b = runs
    c = _client(session, token=_owner_token(session, a))
    res = c.post(
        "/link-graph/export",
        json={"run_ids": [str(a), str(b)], "seed": P1, "format": "json"},
    )
    assert res.status_code == 200
    art = res.json()
    assert art["kind"] == "ufdr-link-graph"
    assert art["content_hash"] == content_hash(art["graph"])
    assert art["signature"] == sign(
        art["graph"], "test-secret-key", audit_head_hash=art["audit_head_hash"]
    )
    # the export was recorded in the audit chain committing to the same content hash
    from ingest.services.audit_service import audit_service

    export_events = [
        e
        for e in audit_service.export(session)["events"]
        if e["event_type"] == "export"
    ]
    assert (
        export_events
        and export_events[-1]["payload"]["content_hash"] == art["content_hash"]
    )
    # the export event records WHO exported (chain-of-custody actor)
    assert export_events[-1]["user_id"] == str(session.get(Run, a).user_id)


def test_route_export_hops_out_of_range_is_422(session, runs):
    a, _ = runs
    c = _client(session, token=_owner_token(session, a))
    res = c.post(
        "/link-graph/export", json={"run_ids": [str(a)], "hops": 99, "format": "json"}
    )
    assert res.status_code == 422  # pydantic bound matches the GET cap


# -- auth / owner-scoping (the membership-oracle fix) ------------------------
def test_route_get_without_token_is_401(session, runs):
    a, _ = runs
    c = _client(session)  # no Authorization header
    res = c.get("/link-graph", params={"run_ids": [str(a)]})
    assert res.status_code == 401, "unauthenticated caller must be rejected"


def test_route_export_without_token_is_401(session, runs):
    a, _ = runs
    c = _client(session)
    res = c.post(
        "/link-graph/export", json={"run_ids": [str(a)], "format": "json"}
    )
    assert res.status_code == 401


def test_route_get_with_garbage_token_is_401(session, runs):
    a, _ = runs
    c = _client(session, token="not-a-real-jwt")
    res = c.get("/link-graph", params={"run_ids": [str(a)]})
    assert res.status_code == 401


def test_route_get_token_for_unknown_user_is_401(session, runs):
    """A well-signed token whose subject is no longer a user is rejected — a
    deleted user's token must not keep working."""
    from ingest.services.auth_service import create_access_token

    a, _ = runs
    c = _client(session, token=create_access_token(uuid.uuid4()))
    res = c.get("/link-graph", params={"run_ids": [str(a)]})
    assert res.status_code == 401


def test_route_non_owner_is_403_not_empty(session, runs):
    """A different authenticated user asking for someone else's run is REFUSED
    (403), not handed an empty-but-revealing graph — no membership oracle."""
    from db_setup import User
    from ingest.services.auth_service import create_access_token

    a, _ = runs
    attacker = User(username="Mallory", email="m@x.gov", password_hash="x")
    session.add(attacker)
    session.commit()
    session.refresh(attacker)
    c = _client(session, token=create_access_token(attacker.id))
    res = c.get("/link-graph", params={"run_ids": [str(a)]})
    assert res.status_code == 403, "non-owner must be refused, not given a result"


def test_route_export_non_owner_is_403(session, runs):
    from db_setup import User
    from ingest.services.auth_service import create_access_token

    a, b = runs
    attacker = User(username="Mallory", email="m@x.gov", password_hash="x")
    session.add(attacker)
    session.commit()
    session.refresh(attacker)
    c = _client(session, token=create_access_token(attacker.id))
    res = c.post(
        "/link-graph/export",
        json={"run_ids": [str(a), str(b)], "format": "json"},
    )
    assert res.status_code == 403
