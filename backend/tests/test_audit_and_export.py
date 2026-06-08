"""Tests for the tamper-evident audit chain and the signed evidence PDF."""
import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

from sqlmodel import Session, SQLModel, create_engine  # noqa: E402

import db_setup  # noqa: E402,F401
from db_setup import AuditEvent  # noqa: E402
from ingest.services.audit_service import AuditService, GENESIS_HASH  # noqa: E402
from ingest.services.evidence_report import (  # noqa: E402
    build_evidence_pdf, content_hash, sign,
)


@pytest.fixture()
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_chain_links_and_verifies(session):
    svc = AuditService()
    e0 = svc.record(session, "query", payload={"q": "first"})
    e1 = svc.record(session, "export", payload={"q": "second"})
    assert e0.prev_hash == GENESIS_HASH
    assert e1.prev_hash == e0.entry_hash
    status = svc.verify_chain(session)
    assert status.ok and status.length == 2 and status.broken_at_seq is None


def test_tampering_breaks_chain(session):
    svc = AuditService()
    svc.record(session, "query", payload={"q": "a"})
    svc.record(session, "query", payload={"q": "b"})
    svc.record(session, "query", payload={"q": "c"})

    # Forge a past event's payload without recomputing downstream hashes.
    victim = session.exec(SQLModel.metadata and __import__("sqlmodel").select(AuditEvent)
                          ).all()[1]
    victim.payload = '{"q":"TAMPERED"}'
    session.add(victim)
    session.commit()

    status = svc.verify_chain(session)
    assert not status.ok
    assert status.broken_at_seq == 1


def test_export_reports_head_and_verdict(session):
    svc = AuditService()
    svc.record(session, "query", payload={"q": "x"})
    out = svc.export(session)
    assert out["verified"] is True
    assert out["length"] == 1
    assert out["head_hash"] == out["events"][0]["entry_hash"]


def test_signature_is_deterministic_and_keyed():
    answer = {
        "question": "bitcoin?", "planner": "stub",
        "plan": {"targets": ["messages"]}, "sql": "SELECT 1",
        "total": 1,
        "rows": [{"source_table": "message", "row_id": "1", "event_time": None,
                  "preview": "Bitcoin", "citations": []}],
    }
    h1 = content_hash(answer)
    h2 = content_hash(dict(answer))  # same content
    assert h1 == h2                  # deterministic over content
    assert sign(answer, "key-a") == sign(answer, "key-a")
    assert sign(answer, "key-a") != sign(answer, "key-b")  # keyed


def test_pdf_builds_and_is_nonempty():
    answer = {
        "question": "any eth wallet talk?", "planner": "stub",
        "plan": {"targets": ["messages"], "predicates": []},
        "sql": "SELECT id FROM message WHERE run_id = :run_id",
        "total": 1,
        "rows": [{
            "source_table": "message", "row_id": "abc", "event_time": "2024-01-03T12:00:00",
            "preview": "ETH wallet ready",
            "citations": [{"source_table": "message", "row_id": "abc", "column": "content",
                           "matched_value": "wallet", "snippet": "ETH wallet ready",
                           "char_start": 4, "char_end": 10}],
        }],
    }
    pdf = build_evidence_pdf(answer, "secret", audit_head_hash="deadbeef")
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 800
