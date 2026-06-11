"""End-to-end tests for the NL -> IR -> SQL -> cited-results pipeline.

Runs against an in-memory SQLite DB built from the real SQLModel schema, so the
deterministic compiler and citation logic are exercised exactly as in prod.
"""
import os
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest

# Make `backend/` importable and give config a DB URL so importing it never
# fails on missing secrets.
BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

from sqlmodel import Session, SQLModel, create_engine  # noqa: E402

import db_setup  # noqa: E402,F401  (registers all tables on SQLModel.metadata)
from db_setup import Call, Contact, Message, Run, User  # noqa: E402
from ai.query_plan import (  # noqa: E402
    FieldName, Match, Op, Predicate, QueryPlan, Target,
)
from ai.query_pipeline import run_plan  # noqa: E402
from ai.planner import _stub_plan  # noqa: E402


@pytest.fixture()
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture()
def run_id(session):
    user = User(username="IO Test", email="io@test.gov", password_hash="x")
    session.add(user)
    session.commit()
    session.refresh(user)
    run = Run(user_id=user.id, ufdr_file_name="case.ufdr", status="complete")
    session.add(run)
    session.commit()
    session.refresh(run)

    base = datetime(2024, 1, 1, 12, 0, 0)
    session.add_all([
        Message(run_id=run.id, sender="+15550001", receiver="+15550002",
                timestamp=base, content="Let's move the Bitcoin tonight"),
        Message(run_id=run.id, sender="+15550003", receiver="+15550001",
                timestamp=base + timedelta(hours=1), content="lunch at noon?"),
        Message(run_id=run.id, sender="+447700900111", receiver="+15550001",
                timestamp=base + timedelta(days=2), content="ETH wallet ready"),
        Call(run_id=run.id, caller="+15550001", receiver="+447700900111",
             timestamp=base + timedelta(hours=3), duration=42),
        Contact(run_id=run.id, name="Mr Ghost", number="+447700900111"),
    ])
    session.commit()
    return run.id


# --------------------------------------------------------------------------
# IR + compiler
# --------------------------------------------------------------------------
def test_compile_is_deterministic():
    plan = QueryPlan(
        targets=[Target.messages],
        predicates=[Predicate(field=FieldName.text, op=Op.contains, values=["bitcoin"])],
    )
    a = plan.compile()
    b = plan.compile()
    assert a.rendered_sql == b.rendered_sql
    assert a.table_queries[0].sql == b.table_queries[0].sql


def test_values_are_bound_not_interpolated():
    # An injection attempt stays inside a bound parameter — never SQL syntax.
    evil = "'; DROP TABLE message; --"
    plan = QueryPlan(
        targets=[Target.messages],
        predicates=[Predicate(field=FieldName.text, op=Op.contains, values=[evil])],
    )
    tq = plan.compile().table_queries[0]
    assert evil not in tq.sql            # not baked into SQL text
    assert f"%{evil}%" in tq.params.values()  # carried as a parameter value


def test_unsatisfiable_required_predicate_skips_table():
    # `app` has no column on `messages`; with match=all the table is dropped.
    plan = QueryPlan(
        targets=[Target.messages],
        match=Match.all,
        predicates=[Predicate(field=FieldName.app, op=Op.contains, values=["whatsapp"])],
    )
    assert plan.compile().table_queries == []


# --------------------------------------------------------------------------
# Execution + citations
# --------------------------------------------------------------------------
def test_text_search_returns_cited_rows(session, run_id):
    plan = QueryPlan(
        targets=[Target.messages],
        predicates=[Predicate(field=FieldName.text, op=Op.contains, values=["bitcoin"])],
    )
    ans = run_plan(session, plan, run_id, question="bitcoin messages", planner="stub")
    assert ans.total == 1
    row = ans.rows[0]
    assert "Bitcoin" in row.preview
    assert row.citations, "match must carry a citation"
    cite = row.citations[0]
    assert cite.column == "content"
    assert cite.matched_value == "bitcoin"
    assert row.preview[cite.char_start:cite.char_end].lower() == "bitcoin"


def test_participant_search_across_tables(session, run_id):
    plan = QueryPlan(
        targets=[Target.messages, Target.calls, Target.contacts],
        predicates=[Predicate(field=FieldName.participant, op=Op.contains,
                              values=["+447700900111"])],
    )
    ans = run_plan(session, plan, run_id, planner="stub")
    tables = {r.source_table for r in ans.rows}
    assert tables == {"message", "call", "contact"}
    assert all(r.citations for r in ans.rows)


def test_time_range_filters(session, run_id):
    plan = QueryPlan(
        targets=[Target.messages],
        predicates=[Predicate(field=FieldName.text, op=Op.contains,
                              values=["wallet", "bitcoin", "lunch"])],
        time_range={"start": "2024-01-02T00:00:00"},
    )
    ans = run_plan(session, plan, run_id, planner="stub")
    # Only the Jan-3 "ETH wallet" message is after the lower bound.
    assert ans.total == 1
    assert "wallet" in ans.rows[0].preview.lower()


def test_limit_is_enforced(session, run_id):
    plan = QueryPlan(targets=[Target.messages], limit=2)
    ans = run_plan(session, plan, run_id, planner="stub")
    assert ans.total == 2


def test_answer_serializes_to_dict(session, run_id):
    plan = QueryPlan(targets=[Target.messages],
                     predicates=[Predicate(field=FieldName.text, op=Op.contains,
                                          values=["bitcoin"])])
    d = run_plan(session, plan, run_id, planner="stub").to_dict()
    assert set(d) >= {"question", "plan", "sql", "total", "planner", "rows"}
    assert d["rows"][0]["citations"][0]["column"] == "content"


# --------------------------------------------------------------------------
# Stub planner
# --------------------------------------------------------------------------
def test_stub_plan_detects_app():
    plan = _stub_plan("show me whatsapp messages")
    assert Target.aleapp_artifacts in plan.targets
    assert any(p.field == FieldName.app for p in plan.predicates)


def test_stub_plan_detects_crypto_and_runs(session, run_id):
    plan = _stub_plan("any bitcoin or eth chatter?")
    ans = run_plan(session, plan, run_id, planner="stub")
    assert ans.total >= 1
    assert any("bitcoin" in r.preview.lower() or "eth" in r.preview.lower()
               for r in ans.rows)
