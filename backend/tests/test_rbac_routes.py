"""Per-route RBAC deny tests for the run-scoped endpoints gated in V5.

Codex flagged that V5's first cut only gated /query/plan and /link-graph, leaving
other run-scoped routers open. This proves the closure: every gated endpoint
rejects an unauthenticated caller (401) and an authenticated non-member (403),
including the legacy /query/execute, /query/history, and /report/generate routes.

The test harness stubs import-only optional packages for the legacy query router;
the deny checks return before MeiliSearch, embeddings, or LLM work can run.
"""

import os
import sys
import types
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
from db_setup import Message, Run, User  # noqa: E402
from ingest.services.auth_service import create_access_token  # noqa: E402


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


@pytest.fixture()
def world(session):
    owner = User(username="Owner", email="o@x.gov", password_hash="x")
    mallory = User(username="Mallory", email="m@x.gov", password_hash="x")
    session.add_all([owner, mallory])
    session.commit()
    session.refresh(owner)
    session.refresh(mallory)
    run = Run(user_id=owner.id, ufdr_file_name="A.ufdr", status="complete")
    session.add(run)
    session.commit()
    session.refresh(run)
    session.add(
        Message(
            run_id=run.id,
            sender="+1",
            receiver="+2",
            timestamp=datetime(2024, 1, 1),
            content="hi",
        )
    )
    session.commit()
    return {"owner": owner, "mallory": mallory, "run": run}


def _client(session):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from database import get_session

    if "meilisearch" not in sys.modules:
        meili = types.ModuleType("meilisearch")

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

        meili.Client = FakeClient
        sys.modules["meilisearch"] = meili
    if "ai.embeddings" not in sys.modules:
        embeddings = types.ModuleType("ai.embeddings")

        class FakeEmbeddingsService:
            def index_exists(self, run_id):
                return False

            def semantic_search(self, *args, **kwargs):
                raise AssertionError("semantic search must not run in RBAC deny tests")

        embeddings.EmbeddingsService = FakeEmbeddingsService
        sys.modules["ai.embeddings"] = embeddings

    from ingest.routers import (
        aleapp_structure,
        analytics_router,
        audit_router,
        cross_case_router,
        entity_router,
        sync_router,
        query,
        report,
        transcription_router,
        upload,
    )

    app = FastAPI()
    for r in (
        entity_router,
        analytics_router,
        transcription_router,
        cross_case_router,
        audit_router,
        aleapp_structure,
        query,
        report,
        sync_router,
        upload,
    ):
        app.include_router(r.router)
    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app, raise_server_exceptions=False)


def _auth(user):
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def _requests(run_id):
    """(method, path, params, json) for every gated run-scoped endpoint here."""
    rid = str(run_id)
    return [
        ("GET", "/entities/graph", {"run_id": rid}, None),
        ("GET", "/entities/neighborhood", {"run_id": rid, "seed": "+1"}, None),
        ("GET", "/analytics/patterns", {"run_id": rid}, None),
        ("POST", "/query/execute", None, {"query": "bitcoin", "run_id": rid}),
        ("GET", "/query/history/PLACEHOLDER", {"run_id": rid}, None),
        ("POST", "/report/generate", {"run_id": rid}, None),
        ("POST", "/cross-case/index", {"run_id": rid}, None),
        ("GET", "/cross-case/links", {"run_id": rid}, None),
        ("GET", "/transcription/run", {"run_id": rid}, None),
        ("POST", "/audit/evidence-report", None, {"question": "hi", "run_id": rid}),
    ]


def _call(c, method, path, params, json, headers):
    if "PLACEHOLDER" in path:
        path = path.replace(
            "PLACEHOLDER", params["run_id"] if params else json["run_id"]
        )
    return c.request(method, path, params=params, json=json, headers=headers)


@pytest.mark.parametrize("method,path,params,json", _requests("PLACEHOLDER"))
def test_unauthenticated_is_401(session, world, method, path, params, json):
    c = _client(session)
    rid = str(world["run"].id)
    params = {
        k: (rid if v == "PLACEHOLDER" else v) for k, v in (params or {}).items()
    } or None
    json = {**json, "run_id": rid} if json else None
    res = _call(c, method, path, params, json, headers=None)
    assert res.status_code == 401, f"{method} {path} must reject anonymous caller"


@pytest.mark.parametrize("method,path,params,json", _requests("PLACEHOLDER"))
def test_non_member_is_403(session, world, method, path, params, json):
    c = _client(session)
    rid = str(world["run"].id)
    params = {
        k: (rid if v == "PLACEHOLDER" else v) for k, v in (params or {}).items()
    } or None
    json = {**json, "run_id": rid} if json else None
    res = _call(c, method, path, params, json, headers=_auth(world["mallory"]))
    assert res.status_code == 403, f"{method} {path} must reject a non-member"


def test_owner_passes_authz_layer(session, world):
    """Sanity: the owner clears the authz gate (status is not 401/403) — proving
    the deny results above are the RBAC layer, not a blanket failure."""
    c = _client(session)
    rid = str(world["run"].id)
    res = c.get(
        "/analytics/patterns", params={"run_id": rid}, headers=_auth(world["owner"])
    )
    assert res.status_code not in (401, 403)


def test_sync_routes_require_admin(session, world):
    c = _client(session)
    assert c.get("/sync/stats").status_code == 401
    assert c.get("/sync/stats", headers=_auth(world["owner"])).status_code == 403


def test_audit_routes_require_admin(session, world):
    admin = User(
        username="Admin", email="admin@x.gov", password_hash="x", is_admin=True
    )
    session.add(admin)
    session.commit()
    session.refresh(admin)

    c = _client(session)
    assert c.get("/audit").status_code == 401
    assert c.get("/audit", headers=_auth(world["owner"])).status_code == 403
    assert c.get("/audit", headers=_auth(admin)).status_code == 200
    assert c.get("/audit/verify", headers=_auth(world["owner"])).status_code == 403


def test_ingest_routes_require_auth(session):
    c = _client(session)
    assert (
        c.get("/ingest/validate-path", params={"file_path": "x.ufdr"}).status_code
        == 401
    )
    assert c.post("/ingest/", json={"file_path": "x.ufdr"}).status_code == 401


def test_ingest_validate_rejects_paths_outside_input_root(
    session, world, tmp_path, monkeypatch
):
    root = tmp_path / "inputs"
    root.mkdir()
    outside = tmp_path / "outside.ufdr"
    outside.write_text("not a real ufdr", encoding="utf-8")
    monkeypatch.setenv("UFDR_INPUT_ROOT", str(root))

    c = _client(session)
    assert (
        c.get(
            "/ingest/validate-path",
            params={"file_path": str(outside)},
            headers=_auth(world["owner"]),
        ).status_code
        == 403
    )


def test_aleapp_structure_requires_case_bound_path(
    session, world, tmp_path, monkeypatch
):
    from ingest.routers import aleapp_structure

    monkeypatch.setattr(aleapp_structure, "_repo_root", lambda: tmp_path)
    world["run"].original_file_path = "A.ufdr"
    session.add(world["run"])
    session.commit()

    report_dir = tmp_path / "ALEAPP" / "output" / "a" / "ALEAPP_Reports_1"
    report_dir.mkdir(parents=True)
    (report_dir / "index.html").write_text("<html></html>", encoding="utf-8")
    outside = tmp_path / "ALEAPP" / "output" / "other"
    outside.mkdir(parents=True)

    c = _client(session)
    params = {"run_id": str(world["run"].id), "report_path": str(report_dir)}
    assert c.get("/ingest/aleapp-structure", params=params).status_code == 401
    assert (
        c.get(
            "/ingest/aleapp-structure", params=params, headers=_auth(world["mallory"])
        ).status_code
        == 403
    )
    assert (
        c.get(
            "/ingest/aleapp-structure", params=params, headers=_auth(world["owner"])
        ).status_code
        == 200
    )
    assert (
        c.get(
            "/ingest/aleapp-structure",
            params={"run_id": str(world["run"].id), "report_path": str(outside)},
            headers=_auth(world["owner"]),
        ).status_code
        == 403
    )


def test_cross_case_links_redact_unauthorized_runs(session, world):
    from db_setup import CaseMembership
    from ingest.services.cross_case_service import CrossCaseService

    other_owner = User(username="Other", email="other@x.gov", password_hash="x")
    shared_number = "+1 (555) 010-0001"
    session.add(
        Message(
            run_id=world["run"].id,
            sender=shared_number,
            receiver="+1 (555) 010-0002",
            timestamp=datetime(2024, 1, 1, 1),
            content="source shared",
        )
    )
    session.add(other_owner)
    session.commit()
    session.refresh(other_owner)
    other_run = Run(user_id=other_owner.id, ufdr_file_name="B.ufdr", status="complete")
    session.add(other_run)
    session.commit()
    session.refresh(other_run)
    session.add(
        Message(
            run_id=other_run.id,
            sender=shared_number,
            receiver="+9",
            timestamp=datetime(2024, 1, 2),
            content="shared",
        )
    )
    session.commit()

    service = CrossCaseService(session)
    service.index_run(world["run"].id)
    service.index_run(other_run.id)

    c = _client(session)
    res = c.get(
        "/cross-case/links",
        params={"run_id": str(world["run"].id)},
        headers=_auth(world["owner"]),
    )
    assert res.status_code == 200
    assert res.json()["links"] == []

    session.add(
        CaseMembership(
            run_id=other_run.id,
            user_id=world["owner"].id,
            role="viewer",
            granted_by=other_owner.id,
        )
    )
    session.commit()
    res = c.get(
        "/cross-case/links",
        params={"run_id": str(world["run"].id)},
        headers=_auth(world["owner"]),
    )
    assert res.status_code == 200
    assert res.json()["links"][0]["also_in_runs"] == [str(other_run.id)]


def test_report_download_requires_case_access(session, world, tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir()
    filename = f"{world['run'].id}_dummy.pdf"
    (reports / filename).write_bytes(b"%PDF-1.4\n")

    from ingest.routers import report

    monkeypatch.setattr(report.report_service, "output_dir", reports)
    c = _client(session)
    path = f"/report/download/{filename}"

    assert c.get(path, params={"run_id": str(world["run"].id)}).status_code == 401
    assert (
        c.get(
            path,
            params={"run_id": str(world["run"].id)},
            headers=_auth(world["mallory"]),
        ).status_code
        == 403
    )
    assert (
        c.get(
            path,
            params={"run_id": str(world["run"].id)},
            headers=_auth(world["owner"]),
        ).status_code
        == 200
    )

    other_filename = f"{world['mallory'].id}_dummy.pdf"
    (reports / other_filename).write_bytes(b"%PDF-1.4\n")
    assert (
        c.get(
            f"/report/download/{other_filename}",
            params={"run_id": str(world["run"].id)},
            headers=_auth(world["owner"]),
        ).status_code
        == 403
    )
