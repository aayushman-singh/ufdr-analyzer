"""Entity-graph tests — full graph + recursive-CTE neighborhood on SQLite."""
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
from db_setup import Call, Contact, Message, Run, User  # noqa: E402
from ingest.services.entity_service import EntityService  # noqa: E402


@pytest.fixture()
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture()
def run_id(session):
    user = User(username="IO", email="io@x.gov", password_hash="x")
    session.add(user); session.commit(); session.refresh(user)
    run = Run(user_id=user.id, ufdr_file_name="c.ufdr", status="complete")
    session.add(run); session.commit(); session.refresh(run)
    # Chain: A <-> B (msgs) , B <-> C (call) , C <-> D (msg). A..D 3 hops apart.
    base = datetime(2024, 1, 1)
    session.add_all([
        Message(run_id=run.id, sender="A", receiver="B", timestamp=base, content="hi"),
        Message(run_id=run.id, sender="B", receiver="A", timestamp=base, content="yo"),
        Call(run_id=run.id, caller="B", receiver="C", timestamp=base, duration=10),
        Message(run_id=run.id, sender="C", receiver="D", timestamp=base, content="ok"),
        Contact(run_id=run.id, name="Bob", number="B"),
    ])
    session.commit()
    return run.id


def test_full_graph_nodes_edges_and_labels(session, run_id):
    g = EntityService(session).build_graph(run_id)
    ids = {n.id for n in g.nodes}
    assert ids == {"A", "B", "C", "D"}
    # Contact label resolution: B -> "Bob".
    assert next(n.label for n in g.nodes if n.id == "B") == "Bob"
    # A-B edge has weight 2 (two messages, collapsed undirected).
    ab = next(e for e in g.edges if {e.source, e.target} == {"A", "B"})
    assert ab.weight == 2


def test_neighborhood_one_hop(session, run_id):
    g = EntityService(session).neighborhood(run_id, "B", max_hops=1)
    assert {n.id for n in g.nodes} == {"A", "B", "C"}  # D is 2 hops away


def test_neighborhood_two_hops_reaches_d(session, run_id):
    g = EntityService(session).neighborhood(run_id, "A", max_hops=3)
    assert {n.id for n in g.nodes} == {"A", "B", "C", "D"}


def test_neighborhood_zero_hops_is_seed_only(session, run_id):
    g = EntityService(session).neighborhood(run_id, "A", max_hops=0)
    assert {n.id for n in g.nodes} == {"A"}
