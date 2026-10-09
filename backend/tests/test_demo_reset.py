import asyncio
import os
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ["DEMO_MODE"] = "1"

from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import Session, SQLModel, create_engine, select  # noqa: E402

import db_setup  # noqa: E402,F401
from db_setup import AleappArtifact, AleappReport, Message, Run, User  # noqa: E402
import main as backend_main  # noqa: E402
from ingest.routers import query as query_router  # noqa: E402
from main import (  # noqa: E402
    CANONICAL_DEMO_ARTIFACT,
    CANONICAL_DEMO_FILE_NAME,
    CANONICAL_DEMO_MARKER,
    CANONICAL_DEMO_MESSAGES,
    CANONICAL_DEMO_OWNER_EMAIL,
    CANONICAL_DEMO_RUN_ID,
    _validate_canonical_demo_run,
    _demo_data_request_blocked,
    app,
    enforce_demo_data_policy,
    reset_demo_sample,
)
from ingest.services import report_service  # noqa: E402
from ingest.services.report_service import ReportService  # noqa: E402


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as value:
        yield value


def _canonical_run(session):
    owner = User(
        username="CiteSpan demo owner",
        email=CANONICAL_DEMO_OWNER_EMAIL,
        password_hash="release-owner-disabled",
    )
    session.add(owner)
    session.commit()
    session.refresh(owner)
    run = Run(
        id=CANONICAL_DEMO_RUN_ID,
        user_id=owner.id,
        ufdr_file_name=CANONICAL_DEMO_FILE_NAME,
        status="complete",
        end_time=datetime.now(),
        extraction_metadata=(
            '{"citespan_marker": "citespan-synthetic-demo-v1", '
            '"owner_email": "citespan-demo-owner@example.invalid", '
            '"sample_id": "canonical-v1", "synthetic_only": true}'
        ),
    )
    session.add(run)
    session.add_all(
        [
            Message(
                run_id=CANONICAL_DEMO_RUN_ID,
                sender=CANONICAL_DEMO_MESSAGES[0][0],
                receiver=CANONICAL_DEMO_MESSAGES[0][1],
                timestamp=datetime(2025, 3, 10, 14),
                content=CANONICAL_DEMO_MESSAGES[0][2],
            ),
            Message(
                run_id=CANONICAL_DEMO_RUN_ID,
                sender=CANONICAL_DEMO_MESSAGES[1][0],
                receiver=CANONICAL_DEMO_MESSAGES[1][1],
                timestamp=datetime(2025, 3, 10, 16),
                content=CANONICAL_DEMO_MESSAGES[1][2],
            ),
            AleappArtifact(
                run_id=CANONICAL_DEMO_RUN_ID,
                **CANONICAL_DEMO_ARTIFACT,
            ),
        ]
    )
    session.commit()
    session.refresh(run)
    return run


def test_reset_accepts_the_exact_canonical_synthetic_run(session):
    run = _canonical_run(session)

    owner = _validate_canonical_demo_run(session, run)

    assert owner.email == CANONICAL_DEMO_OWNER_EMAIL
    assert CANONICAL_DEMO_MARKER in run.extraction_metadata


def test_demo_reset_returns_the_canonical_synthetic_sample(session, monkeypatch):
    _canonical_run(session)
    owner = session.exec(
        select(User).where(User.email == CANONICAL_DEMO_OWNER_EMAIL)
    ).one()
    monkeypatch.setattr(backend_main, "DEMO_MODE", True)
    monkeypatch.setenv("CITESPAN_DEMO_RUN_ID", str(CANONICAL_DEMO_RUN_ID))

    result = reset_demo_sample(session, owner)

    assert result == {
        "run_id": str(CANONICAL_DEMO_RUN_ID),
        "sample": "canonical synthetic UFDR",
        "reset": True,
    }


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda run: setattr(run, "id", uuid.uuid4()), "identity is not canonical"),
        (
            lambda run: setattr(run, "ufdr_file_name", "real_case.ufdr"),
            "filename is not canonical",
        ),
        (
            lambda run: setattr(run, "extraction_metadata", "{}"),
            "marker or ownership is invalid",
        ),
        (
            lambda run: setattr(run, "user_id", uuid.uuid4()),
            "owner is not the canonical demo owner",
        ),
    ],
)
def test_reset_rejects_incorrect_identity_filename_marker_or_owner(
    session, change, message
):
    run = _canonical_run(session)
    change(run)

    with pytest.raises(RuntimeError, match=message):
        _validate_canonical_demo_run(session, run)


def test_reset_rejects_non_canonical_contents(session):
    run = _canonical_run(session)
    message = session.exec(select(Message).where(Message.run_id == run.id)).first()
    message.content = "real forensic data"
    session.add(message)
    session.commit()

    with pytest.raises(RuntimeError, match="non-canonical message contents"):
        _validate_canonical_demo_run(session, run)


def test_reset_rejects_non_canonical_artifact_contents(session):
    run = _canonical_run(session)
    artifact = session.exec(
        select(AleappArtifact).where(AleappArtifact.run_id == run.id)
    ).first()
    artifact.data = '{"message": "real forensic data"}'
    session.add(artifact)
    session.commit()

    with pytest.raises(RuntimeError, match="non-canonical artifacts"):
        _validate_canonical_demo_run(session, run)


def test_reset_rejects_forbidden_rows(session):
    run = _canonical_run(session)
    session.add(
        AleappReport(
            run_id=run.id,
            report_type="html",
            filename="real-case.html",
            file_path="/real-case.html",
        )
    )
    session.commit()

    with pytest.raises(RuntimeError, match="forbidden AleappReport row"):
        _validate_canonical_demo_run(session, run)


def test_demo_mode_blocks_every_registered_ingest_route_before_handler_access(
    monkeypatch,
):
    monkeypatch.setattr(backend_main, "DEMO_MODE", True)
    ingest_paths = sorted(
        {
            route.path.rstrip("/")
            for route in app.routes
            if route.path.rstrip("/") == "/ingest" or route.path.startswith("/ingest/")
        }
    )
    assert ingest_paths == [
        "/ingest",
        "/ingest/aleapp-structure",
        "/ingest/validate-path",
    ]

    class Request:
        def __init__(self, path):
            self.url = type("URL", (), {"path": path})()
            self.method = "POST"

    async def handler_must_not_run(_request):
        raise AssertionError("demo ingestion handler accessed supplied data")

    async def check(path):
        response = await enforce_demo_data_policy(Request(path), handler_must_not_run)
        assert response.status_code == 403
        assert response.body == (
            b'{"detail":"File upload and path ingestion are disabled in demo mode."}'
        )

    for path in ingest_paths:
        asyncio.run(check(path))
        assert _demo_data_request_blocked(path)


def test_demo_mode_keeps_canonical_reset_outside_ingestion_boundary():
    assert not _demo_data_request_blocked("/demo/reset")
    assert _demo_data_request_blocked("/api/ingest/aleapp-structure")


def test_demo_mode_blocks_legacy_query_before_llm_client_construction(monkeypatch):
    class MustNotConstruct:
        def __init__(self, *args, **kwargs):
            raise AssertionError("legacy LLM client was constructed in demo mode")

    monkeypatch.setattr(query_router, "DEMO_MODE", True)
    monkeypatch.setattr(query_router, "LLMClient", MustNotConstruct)

    with pytest.raises(Exception) as error:
        asyncio.run(
            query_router.execute_query(
                query_router.ExecuteQueryRequest(
                    query="show messages",
                    run_id=str(CANONICAL_DEMO_RUN_ID),
                ),
                session=None,
                auth_user=None,
                meili_client=None,
            )
        )

    assert getattr(error.value, "status_code", None) == 403
    assert "external-AI" in str(error.value.detail)


def test_hosted_dashboard_uses_honest_query_plan_redirect():
    dashboard = (
        BACKEND.parent / "frontend/components/dashboard/DashboardLayout.tsx"
    ).read_text(encoding="utf-8")
    assistant = (
        BACKEND.parent / "frontend/components/dashboard/views/AiAssistantView.tsx"
    ).read_text(encoding="utf-8")

    assert 'const hostedDemo = process.env.NEXT_PUBLIC_DEMO_MODE === "1"' in dashboard
    assert "if (hostedDemo)" in dashboard
    assert 'window.location.assign("/query-plan")' in dashboard
    assert "/query/execute" in dashboard
    assert "query: trimmedInput" in dashboard
    assert "Query Plan" in assistant
    assert "external llm behavior is disabled" in assistant.lower()
    assert "disabled={isSending || hostedDemo}" in assistant


def test_generate_pdf_uses_citespan_title_and_preserves_report_content(
    tmp_path, monkeypatch
):
    original_canvas = report_service.canvas.Canvas
    monkeypatch.setattr(
        report_service.canvas,
        "Canvas",
        lambda path, pagesize: original_canvas(
            path, pagesize=pagesize, pageCompression=0
        ),
    )
    service = ReportService(tmp_path)
    report_path = service.generate_pdf(
        {
            "run_id": "synthetic-run",
            "ufdr_file_name": "demo_synthetic.ufdr",
            "status": "completed",
            "start_time": "2026-10-08T10:00:00Z",
            "end_time": "2026-10-08T10:01:00Z",
            "user": {"username": "Demo User", "email": "demo@example.invalid"},
            "results": [
                {
                    "result_type": "contact",
                    "confidence_score": 0.95,
                    "rule": "synthetic-contact-rule",
                    "evidence_data": '{"source": "demo"}',
                }
            ],
        }
    )

    rendered_text = re.sub(rb"\s+", b" ", Path(report_path).read_bytes())

    assert b"CiteSpan Report" in rendered_text
    assert b"UFDR Report" not in rendered_text
    assert b"demo_synthetic.ufdr" in rendered_text
    assert b"synthetic-contact-rule" in rendered_text
