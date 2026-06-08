"""Tamper-evident audit trail — forensic chain-of-custody.

Every consequential action (query, ingest, export) is appended to the
`AuditEvent` table as a link in a hash chain:

    entry_hash = sha256( prev_hash || canonical_json(event_core) )

Because each link commits to the previous one, you cannot alter or remove a
past event without invalidating every `entry_hash` that follows. `verify_chain`
recomputes the whole chain and reports the first break, if any. This is the
property a court cares about: the log can be *shown* to be intact.

No fallbacks: a verification failure is returned explicitly (not swallowed), and
recording is transactional with the caller's session.
"""
from __future__ import annotations

import hashlib
import json
import sys
import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from db_setup import AuditEvent  # noqa: E402

GENESIS_HASH = "0" * 64


def _canonical(event_type: str, seq: int, timestamp: str, run_id: Optional[str],
               user_id: Optional[str], payload: Optional[str], prev_hash: str) -> str:
    """Deterministic serialization of the fields the hash commits to."""
    return json.dumps(
        {
            "seq": seq,
            "event_type": event_type,
            "timestamp": timestamp,
            "run_id": run_id,
            "user_id": user_id,
            "payload": payload,
            "prev_hash": prev_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def _hash_event(event_type: str, seq: int, timestamp: str, run_id: Optional[str],
                user_id: Optional[str], payload: Optional[str], prev_hash: str) -> str:
    canon = _canonical(event_type, seq, timestamp, run_id, user_id, payload, prev_hash)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


@dataclass
class ChainStatus:
    ok: bool
    length: int
    broken_at_seq: Optional[int] = None
    detail: str = ""


class AuditService:
    """Append-only, verifiable audit log over the `AuditEvent` table."""

    def record(
        self,
        session: Session,
        event_type: str,
        payload: Optional[dict] = None,
        run_id: Optional[uuid.UUID | str] = None,
        user_id: Optional[uuid.UUID | str] = None,
    ) -> AuditEvent:
        """Append an event, linking it to the current chain head."""
        head = session.exec(
            select(AuditEvent).order_by(AuditEvent.seq.desc())
        ).first()
        seq = (head.seq + 1) if head and head.seq is not None else 0
        prev_hash = head.entry_hash if head else GENESIS_HASH

        ts = datetime.utcnow()
        ts_iso = ts.isoformat()
        run_s = str(run_id) if run_id is not None else None
        user_s = str(user_id) if user_id is not None else None
        payload_s = (
            json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
            if payload is not None else None
        )

        entry_hash = _hash_event(event_type, seq, ts_iso, run_s, user_s, payload_s, prev_hash)

        event = AuditEvent(
            seq=seq,
            event_type=event_type,
            run_id=uuid.UUID(run_s) if run_s else None,
            user_id=uuid.UUID(user_s) if user_s else None,
            timestamp=ts,
            payload=payload_s,
            prev_hash=prev_hash,
            entry_hash=entry_hash,
        )
        session.add(event)
        session.commit()
        session.refresh(event)
        return event

    def verify_chain(self, session: Session) -> ChainStatus:
        """Recompute the whole chain; report the first break if any."""
        events = session.exec(select(AuditEvent).order_by(AuditEvent.seq.asc())).all()
        prev_hash = GENESIS_HASH
        for ev in events:
            if ev.prev_hash != prev_hash:
                return ChainStatus(False, len(events), ev.seq,
                                   f"prev_hash mismatch at seq {ev.seq}")
            recomputed = _hash_event(
                ev.event_type, ev.seq, ev.timestamp.isoformat(),
                str(ev.run_id) if ev.run_id else None,
                str(ev.user_id) if ev.user_id else None,
                ev.payload, ev.prev_hash,
            )
            if recomputed != ev.entry_hash:
                return ChainStatus(False, len(events), ev.seq,
                                   f"entry_hash mismatch at seq {ev.seq}")
            prev_hash = ev.entry_hash
        return ChainStatus(True, len(events), None, "chain intact")

    def export(self, session: Session) -> dict:
        """Full chain + verification verdict + head hash, for export."""
        events = session.exec(select(AuditEvent).order_by(AuditEvent.seq.asc())).all()
        status = self.verify_chain(session)
        return {
            "verified": status.ok,
            "length": status.length,
            "head_hash": events[-1].entry_hash if events else GENESIS_HASH,
            "broken_at_seq": status.broken_at_seq,
            "events": [
                {
                    "seq": ev.seq,
                    "event_type": ev.event_type,
                    "timestamp": ev.timestamp.isoformat(),
                    "run_id": str(ev.run_id) if ev.run_id else None,
                    "user_id": str(ev.user_id) if ev.user_id else None,
                    "payload": json.loads(ev.payload) if ev.payload else None,
                    "prev_hash": ev.prev_hash,
                    "entry_hash": ev.entry_hash,
                }
                for ev in events
            ],
        }


audit_service = AuditService()
