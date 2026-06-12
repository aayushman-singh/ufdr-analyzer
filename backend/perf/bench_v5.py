"""V5 performance benchmark — measured before/after for the run_id hot-path indexes.

Both V5 perf targets share one root cost: every query and every graph build filters
evidence rows by `run_id`. Before V5 the `message`/`call`/`contact` tables had NO
index on `run_id`, so each per-run read was a full-table scan whose cost grows with
the WHOLE database (every other case's rows), not with the case being queried. V5
adds `(run_id, timestamp)` composite indexes (message, call) and a `run_id` index
(contact), turning those scans into index range lookups.

This script measures the effect honestly: it builds ONE large multi-case SQLite
database, then times the two hot paths

  1. link-graph build   (LinkGraphService.build over one case)
  2. query-plan execute  (compile -> SQL -> cited rows over one case)

first with the indexes DROPPED ("before"), then with them CREATED ("after"), on the
*identical* dataset and engine — so the only variable is the index. It reports the
median of N repetitions for each.

Why SQLite: the test/CI substrate is SQLite, so the benchmark is reproducible with
zero external services. This proves the local planner switches from full scan to
index search on the synthetic dataset. It does NOT claim production Postgres
latency; run this benchmark against a staging Postgres dataset before making that
claim.

Run:
    python perf/bench_v5.py                 # default: 40 cases x 5000 msgs
    python perf/bench_v5.py --runs 60 --msgs 8000 --reps 7
"""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("CROSS_CASE_SALT", "bench-cross-case-key")

from sqlalchemy import text  # noqa: E402
from sqlmodel import Session, SQLModel, create_engine  # noqa: E402

import db_setup  # noqa: E402,F401
from db_setup import Call, Contact, Message, Run, User  # noqa: E402
from ai.query_pipeline import run_plan  # noqa: E402
from ai.query_plan import (  # noqa: E402
    FieldName,
    Op,
    Predicate,
    QueryPlan,
    Target,
)
from ingest.services.link_graph_service import LinkGraphService  # noqa: E402

# The three indexes under test — dropped for "before", created for "after".
# DDL kept identical to what the SQLModel models now declare.
_INDEX_DDL = {
    "ix_message_run_ts": "CREATE INDEX ix_message_run_ts ON message (run_id, timestamp)",
    "ix_call_run_ts": "CREATE INDEX ix_call_run_ts ON call (run_id, timestamp)",
    "ix_contact_run_id": "CREATE INDEX ix_contact_run_id ON contact (run_id)",
}

_POOL = [f"+1555{n:07d}" for n in range(2000)]  # entity pool to interconnect


def seed(session: Session, *, num_runs: int, msgs_per_run: int) -> uuid.UUID:
    """Seed `num_runs` cases; return the id of the target case to benchmark.

    Every case gets `msgs_per_run` messages, msgs_per_run//5 calls, and 200
    contacts, so the tables hold rows for MANY cases — the situation where a
    run_id index matters (a scan would otherwise wade through other cases)."""
    rng = random.Random(42)
    u = User(username="bench", email="bench@x.gov", password_hash="x")
    session.add(u)
    session.commit()
    session.refresh(u)

    base = datetime(2024, 1, 1)
    target: uuid.UUID | None = None
    for ri in range(num_runs):
        run = Run(user_id=u.id, ufdr_file_name=f"case{ri}.ufdr", status="complete")
        session.add(run)
        session.commit()
        session.refresh(run)
        if ri == num_runs // 2:
            target = run.id

        rows: list = []
        for i in range(msgs_per_run):
            a = _POOL[rng.randrange(len(_POOL))]
            b = _POOL[rng.randrange(len(_POOL))]
            # ~1% of messages carry the benchmarked keyword.
            content = "move the bitcoin tonight" if i % 100 == 0 else f"msg {i}"
            rows.append(
                Message(
                    run_id=run.id,
                    sender=a,
                    receiver=b,
                    timestamp=base + timedelta(minutes=i),
                    content=content,
                )
            )
        for i in range(msgs_per_run // 5):
            a = _POOL[rng.randrange(len(_POOL))]
            b = _POOL[rng.randrange(len(_POOL))]
            rows.append(
                Call(
                    run_id=run.id,
                    caller=a,
                    receiver=b,
                    timestamp=base + timedelta(minutes=i),
                    duration=30,
                )
            )
        for i in range(200):
            rows.append(
                Contact(
                    run_id=run.id, name=f"c{i}", number=_POOL[rng.randrange(len(_POOL))]
                )
            )
        session.add_all(rows)
        session.commit()

    assert target is not None
    return target


def drop_indexes(session: Session) -> None:
    for name in _INDEX_DDL:
        session.exec(text(f"DROP INDEX IF EXISTS {name}"))
    session.commit()


def create_indexes(session: Session) -> None:
    for ddl in _INDEX_DDL.values():
        session.exec(text(ddl))
    session.commit()
    session.exec(text("ANALYZE"))  # let the planner see the new indexes
    session.commit()


def _query_plan() -> QueryPlan:
    return QueryPlan(
        targets=[Target.messages],
        predicates=[
            Predicate(field=FieldName.text, op=Op.contains, values=["bitcoin"])
        ],
        limit=100,
    )


def time_op(fn, *, reps: int) -> float:
    """Median wall-clock ms over `reps` runs, after one warmup."""
    fn()  # warm caches/plan
    samples = []
    for _ in range(reps):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000.0)
    return statistics.median(samples)


def explain(session: Session, target: uuid.UUID) -> str:
    """SQLite query plan for the run-scoped message read — proves index usage.

    Returns the joined EXPLAIN QUERY PLAN detail lines. Without the index they
    read 'SCAN message'; with it, 'SEARCH message USING INDEX ix_message_run_ts'.
    This is the honesty check: the timing win is only meaningful if the planner
    actually switched from a full scan to an index search."""
    rows = session.exec(
        text(
            "EXPLAIN QUERY PLAN SELECT id FROM message "
            "WHERE run_id = :rid ORDER BY timestamp"
        ),
        params={"rid": str(target)},
    ).all()
    return " | ".join(r[-1] for r in rows)


def measure(session: Session, target: uuid.UUID, *, reps: int) -> dict:
    plan = _query_plan()
    graph_ms = time_op(
        lambda: LinkGraphService(session).build(
            [target], authorized_run_ids={str(target)}
        ),
        reps=reps,
    )
    query_ms = time_op(
        lambda: run_plan(session, plan, target, question="bitcoin", planner="stub"),
        reps=reps,
    )
    return {"graph_build_ms": round(graph_ms, 2), "query_exec_ms": round(query_ms, 2)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=40, help="number of cases")
    ap.add_argument("--msgs", type=int, default=5000, help="messages per case")
    ap.add_argument("--reps", type=int, default=5, help="timed repetitions")
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="ufdr_bench_"))
    db = tmp / "bench.sqlite"
    engine = create_engine(f"sqlite:///{db}")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        print(f"seeding {args.runs} cases x {args.msgs} msgs ...", flush=True)
        target = seed(session, num_runs=args.runs, msgs_per_run=args.msgs)
        total_msgs = session.exec(text("SELECT COUNT(*) FROM message")).one()[0]
        print(f"  message rows total: {total_msgs}", flush=True)

        # before -> after -> before2. The third pass re-drops the index and
        # re-measures: if "before2" tracks "before" while "after" stays fast, the
        # win is more likely the index than pass ordering. Report all three; do
        # not hide the control value inside the speedup headline.
        drop_indexes(session)
        explain_before = explain(session, target)
        before = measure(session, target, reps=args.reps)
        create_indexes(session)
        explain_after = explain(session, target)
        after = measure(session, target, reps=args.reps)
        drop_indexes(session)
        before2 = measure(session, target, reps=args.reps)

    def speedup(b: float, a: float) -> str:
        return f"{b / a:.1f}x" if a > 0 else "inf"

    report = {
        "config": {
            "runs": args.runs,
            "msgs_per_run": args.msgs,
            "reps": args.reps,
            "total_messages": total_msgs,
        },
        "explain_query_plan": {
            "before_no_index": explain_before,
            "after_with_index": explain_after,
        },
        "before_no_index": before,
        "after_with_index": after,
        "before_no_index_recheck": before2,
        "speedup": {
            "graph_build": speedup(before["graph_build_ms"], after["graph_build_ms"]),
            "query_exec": speedup(before["query_exec_ms"], after["query_exec_ms"]),
        },
    }
    print("\n=== V5 perf: run_id index, before vs after (median ms) ===")
    print(f"  dataset: {total_msgs} messages across {args.runs} cases\n")
    print(f"  EXPLAIN before: {explain_before}")
    print(f"  EXPLAIN after : {explain_after}\n")
    print(f"  {'op':<16}{'before':>12}{'after':>12}{'speedup':>10}")
    print(f"  {'-' * 48}")
    for op, blabel in (
        ("graph_build", "graph_build_ms"),
        ("query_exec", "query_exec_ms"),
    ):
        print(
            f"  {op:<16}{before[blabel]:>10.2f}ms{after[blabel]:>10.2f}ms"
            f"{report['speedup'][op]:>10}"
        )
    print("\nJSON:")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
