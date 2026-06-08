"""Tests for temporal pattern / anomaly detection (deterministic, SQLite)."""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

from sqlmodel import Session, SQLModel, create_engine  # noqa: E402

import db_setup  # noqa: E402,F401
from db_setup import Call, Message, Run, User  # noqa: E402
from ingest.services.analytics_service import AnalyticsService  # noqa: E402


@pytest.fixture()
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _mk_run(session):
    u = User(username="IO", email="io@x.gov", password_hash="x")
    session.add(u); session.commit(); session.refresh(u)
    r = Run(user_id=u.id, ufdr_file_name="c.ufdr", status="complete")
    session.add(r); session.commit(); session.refresh(r)
    return r.id


def test_empty_run_has_no_findings(session):
    rep = AnalyticsService(session).analyze(_mk_run(session))
    assert rep.total_events == 0
    assert rep.findings == []
    assert "No communication activity" in rep.narrative


def test_detects_volume_spike_with_citations(session):
    run_id = _mk_run(session)
    base = datetime(2024, 1, 1, 12, 0)
    # 20 quiet days with 1 msg each, then a spike day with 30.
    for d in range(20):
        session.add(Message(run_id=run_id, sender="A", receiver="B",
                            timestamp=base + timedelta(days=d), content="hi"))
    spike_day = base + timedelta(days=21)
    for i in range(30):
        session.add(Message(run_id=run_id, sender="A", receiver="B",
                            timestamp=spike_day + timedelta(minutes=i), content=f"m{i}"))
    session.commit()

    rep = AnalyticsService(session).analyze(run_id)
    spikes = [f for f in rep.findings if f.type == "spike"]
    assert spikes, "should detect the 30-event day as a spike"
    s = spikes[0]
    assert s.dates == ["2024-01-22"]
    assert s.stats["volume"] == 30
    assert len(s.citations) > 0


def test_detects_late_night_activity(session):
    run_id = _mk_run(session)
    base = datetime(2024, 2, 1, 2, 30)  # 02:30 — late night
    for i in range(10):
        session.add(Call(run_id=run_id, caller="A", receiver="B",
                        timestamp=base + timedelta(hours=24 * i), duration=5))
    session.commit()
    rep = AnalyticsService(session).analyze(run_id)
    assert any(f.type == "late_night" for f in rep.findings)


def test_detects_dropoff(session):
    run_id = _mk_run(session)
    base = datetime(2024, 3, 1, 9, 0)
    # 10 busy days (10/day) then 10 near-silent days (0/day after change point).
    for d in range(10):
        for i in range(10):
            session.add(Message(run_id=run_id, sender="A", receiver="B",
                                timestamp=base + timedelta(days=d, minutes=i), content="x"))
    # add a single late event 12 days later to extend the span
    session.add(Message(run_id=run_id, sender="A", receiver="B",
                        timestamp=base + timedelta(days=22), content="last"))
    session.commit()
    rep = AnalyticsService(session).analyze(run_id)
    assert any(f.type == "drop" for f in rep.findings), \
        f"expected a drop finding, got {[f.type for f in rep.findings]}"


def test_detects_new_contact_emergence(session):
    run_id = _mk_run(session)
    base = datetime(2024, 4, 1, 10, 0)
    for d in range(5):  # established contact B from day 0
        session.add(Message(run_id=run_id, sender="A", receiver="B",
                            timestamp=base + timedelta(days=d), content="hi"))
    # New contact Z appears on day 10 with high volume.
    for i in range(10):
        session.add(Message(run_id=run_id, sender="A", receiver="Z",
                            timestamp=base + timedelta(days=10, minutes=i), content="new"))
    session.commit()
    rep = AnalyticsService(session).analyze(run_id)
    nc = [f for f in rep.findings if f.type == "new_contact"]
    assert any("Z" in f.title for f in nc)


def test_report_is_deterministic(session):
    run_id = _mk_run(session)
    base = datetime(2024, 5, 1, 12, 0)
    for d in range(15):
        for i in range(d % 4):
            session.add(Message(run_id=run_id, sender="A", receiver="B",
                                timestamp=base + timedelta(days=d, minutes=i), content="x"))
    session.commit()
    a = AnalyticsService(session).analyze(run_id).to_dict()
    b = AnalyticsService(session).analyze(run_id).to_dict()
    assert a == b
