"""Cross-case entity-linking tests (salted-hash index, SQLite)."""
import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

from sqlmodel import Session, SQLModel, create_engine  # noqa: E402

import db_setup  # noqa: E402,F401
from db_setup import Call, Contact, EntityIndex, Message, Run, User  # noqa: E402
from ingest.services.cross_case_service import (  # noqa: E402
    CrossCaseService, hash_identifier, normalize,
)


@pytest.fixture()
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _mk_run(session, user):
    r = Run(user_id=user.id, ufdr_file_name="c.ufdr", status="complete")
    session.add(r); session.commit(); session.refresh(r)
    return r.id


@pytest.fixture()
def user(session):
    u = User(username="IO", email="io@x.gov", password_hash="x")
    session.add(u); session.commit(); session.refresh(u)
    return u


def test_normalize_phone_and_email():
    assert normalize("+1 (555) 010-2030") == ("+15550102030", "phone")
    assert normalize("Foo@Bar.com") == ("foo@bar.com", "email")
    assert normalize("hi") is None  # not an identifier


def test_same_number_different_formatting_same_hash():
    assert hash_identifier("+1 555 010 2030") == hash_identifier("+15550102030")
    assert hash_identifier("a@b.com") != hash_identifier("c@b.com")


def test_index_only_stores_hashes_not_raw(session, user):
    run_id = _mk_run(session, user)
    session.add(Contact(run_id=run_id, name="Bob", number="+15550102030"))
    session.commit()
    CrossCaseService(session).index_run(run_id)
    rows = session.exec(SQLModel.metadata and __import__("sqlmodel").select(EntityIndex)).all()
    assert rows and all(len(r.identifier_hash) == 64 for r in rows)
    # The raw number must NOT appear anywhere in the index rows.
    assert all("+15550102030" not in r.identifier_hash for r in rows)


def test_links_across_two_cases(session, user):
    run_a = _mk_run(session, user)
    run_b = _mk_run(session, user)
    shared = "+15550102030"
    base = datetime(2024, 1, 1)
    session.add(Message(run_id=run_a, sender=shared, receiver="+15550000001",
                        timestamp=base, content="hi"))
    session.add(Call(run_id=run_b, caller=shared, receiver="+15550000002",
                    timestamp=base, duration=10))
    session.commit()

    svc = CrossCaseService(session)
    svc.index_run(run_a)
    svc.index_run(run_b)

    links = svc.links_for_run(run_a)
    shared_link = [l for l in links if l.identifier == shared]
    assert shared_link, "shared number should link across cases"
    assert str(run_b) in shared_link[0].also_in_runs
    assert shared_link[0].case_count == 2


def test_lookup_returns_all_runs(session, user):
    run_a = _mk_run(session, user)
    run_b = _mk_run(session, user)
    num = "+447700900111"
    base = datetime(2024, 1, 1)
    for rid in (run_a, run_b):
        session.add(Contact(run_id=rid, name="X", number=num))
    session.commit()
    svc = CrossCaseService(session)
    svc.index_run(run_a); svc.index_run(run_b)
    out = svc.lookup("+44 7700 900111")
    assert out["count"] == 2
    assert set(out["runs"]) == {str(run_a), str(run_b)}


def test_reindex_is_idempotent(session, user):
    run_id = _mk_run(session, user)
    session.add(Contact(run_id=run_id, name="X", number="+15550102030"))
    session.commit()
    svc = CrossCaseService(session)
    n1 = svc.index_run(run_id)
    n2 = svc.index_run(run_id)
    assert n1 == n2 == 1
    rows = session.exec(__import__("sqlmodel").select(EntityIndex)).all()
    assert len(rows) == 1  # no duplicate accumulation
