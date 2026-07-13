#!/usr/bin/env python3
"""Seed a synthetic demo case for UI testing. Run from repo root with venv active."""

from __future__ import annotations

import argparse
import datetime
import sys
import uuid
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from sqlmodel import Session, select  # noqa: E402

import db_setup  # noqa: E402,F401
from database import engine  # noqa: E402
from db_setup import Call, Contact, Message, Run, User  # noqa: E402
from ingest.services.cross_case_service import CrossCaseService  # noqa: E402

P1 = "+15551234567"
P2 = "+15559876543"


def seed(email: str) -> uuid.UUID:
    with Session(engine) as session:
        user = session.exec(select(User).where(User.email == email)).first()
        if not user:
            raise SystemExit(f"No user with email {email!r}. Sign up in the UI first.")

        run = Run(
            user_id=user.id,
            ufdr_file_name="demo_synthetic.ufdr",
            status="complete",
            end_time=datetime.datetime.now(),
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        base = datetime.datetime(2025, 3, 10, 14, 0, 0)
        messages = [
            Message(
                run_id=run.id,
                sender=P1,
                receiver=P2,
                timestamp=base,
                content="Can you send the bitcoin wallet address for the transfer?",
            ),
            Message(
                run_id=run.id,
                sender=P2,
                receiver=P1,
                timestamp=base + datetime.timedelta(hours=2),
                content="Sure — use bc1qdemo123 for the bank transfer tonight.",
            ),
            Message(
                run_id=run.id,
                sender=P1,
                receiver=P2,
                timestamp=base + datetime.timedelta(days=1, hours=23),
                content="Late night ping about Nightingale project docs.",
            ),
        ]
        calls = [
            Call(
                run_id=run.id,
                caller=P1,
                receiver=P2,
                timestamp=base + datetime.timedelta(hours=1),
                duration=420,
            ),
        ]
        contacts = [
            Contact(run_id=run.id, name="Mike Johnson", number=P2),
            Contact(run_id=run.id, name="Alice Demo", number=P1),
        ]
        session.add_all(messages + calls + contacts)
        session.commit()

        CrossCaseService(session).index_run(run.id)
        session.commit()

        print(str(run.id))
        return run.id


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed demo case for a user email")
    parser.add_argument("email", help="User email (must exist from signup)")
    args = parser.parse_args()
    seed(args.email)
