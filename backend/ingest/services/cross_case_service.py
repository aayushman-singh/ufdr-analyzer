"""Cross-case identifier linking — "this number appears in N other cases".

Single-case forensic tools can't answer the question investigators most want:
*have I seen this identifier before?* This service builds an occurrence index of
identifiers (phone numbers, emails) across every ingested run, keyed by an
**HMAC of the canonicalized identifier** — never the raw value. Linking is a
keyed-hash equality join across runs, so a hit reveals only *that another run
contains an identifier the querying run already holds*.

Design constraints (hardened after review):
- The HMAC key (`CROSS_CASE_SALT`) is **required** — a public/default salt over a
  small phone-number space is brute-forceable, so a missing key fails loudly.
- There is intentionally **no arbitrary-identifier lookup endpoint**: that would
  be a cross-case membership oracle. Only a run's own identifiers can be linked.
- Output is deterministic: identifiers are surfaced in their canonical normalized
  form (not whichever raw formatting happened to be read first), and lists sorted.
- The hash is never returned over the API.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from dataclasses import dataclass
from datetime import datetime

from sqlmodel import Session, delete, select

from db_setup import Call, Contact, EntityIndex, Message

_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_DIGITS_RE = re.compile(r"\d")
_MIN_PHONE_DIGITS = 7  # below this, digit strings are not treated as phone numbers


def _require_key() -> bytes:
    """The HMAC key for identifier hashing. Required — no default (brute-force)."""
    salt = os.getenv("CROSS_CASE_SALT")
    if not salt:
        raise RuntimeError(
            "CROSS_CASE_SALT is not set. Cross-case linking hashes identifiers with "
            "a keyed HMAC; a missing or default key makes phone/email hashes "
            "brute-forceable. Set CROSS_CASE_SALT to a strong shared secret."
        )
    if salt.strip().lower() in {"change_me", "changeme"} or "change_me" in salt.lower():
        raise RuntimeError("CROSS_CASE_SALT is still a template placeholder.")
    return salt.encode("utf-8")


def normalize(identifier: str) -> tuple[str, str] | None:
    """Return (canonical_value, type) or None. Canonical phone = digits only.

    Canonicalizing to digits-only collapses '+1 (555) 010-2030' and '15550102030'
    to the same value, so they hash identically and link.
    """
    if not identifier:
        return None
    s = identifier.strip()
    if _EMAIL_RE.fullmatch(s):
        return s.lower(), "email"
    digits = "".join(_DIGITS_RE.findall(s))
    if len(digits) >= _MIN_PHONE_DIGITS:
        return digits, "phone"
    return None


def hash_identifier(identifier: str) -> str | None:
    norm = normalize(identifier)
    if norm is None:
        return None
    value, _type = norm
    return hmac.new(_require_key(), value.encode("utf-8"), hashlib.sha256).hexdigest()


@dataclass
class RunLink:
    identifier: str  # the querying run's own identifier, canonical form
    identifier_type: str
    also_in_runs: list[str]  # other run ids sharing this identifier
    case_count: int  # number of distinct runs (incl. this one)


class CrossCaseService:
    def __init__(self, session: Session):
        self.session = session

    def _run_exists(self, run_id) -> bool:
        from db_setup import Run

        return self.session.get(Run, run_id) is not None

    def _occurrences(self, run_id) -> dict[str, dict]:
        """hash -> {value, type, count, first, last} for identifiers in a run.

        Deterministic: the surfaced `value` is the canonical normalized form, not
        a raw formatting variant, so row order cannot change the output.
        """
        key = _require_key()
        acc: dict[str, dict] = {}

        def add(raw: str | None, ts: datetime | None):
            if not raw:
                return
            norm = normalize(raw)
            if norm is None:
                return
            value, vtype = norm
            h = hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()
            slot = acc.setdefault(
                h,
                {
                    "value": value,
                    "type": vtype,
                    "count": 0,
                    "first": None,
                    "last": None,
                },
            )
            slot["count"] += 1
            if ts is not None:
                slot["first"] = ts if slot["first"] is None else min(slot["first"], ts)
                slot["last"] = ts if slot["last"] is None else max(slot["last"], ts)

        for c in self.session.exec(
            select(Contact).where(Contact.run_id == run_id)
        ).all():
            add(c.number, None)
        for m in self.session.exec(
            select(Message).where(Message.run_id == run_id)
        ).all():
            add(m.sender, m.timestamp)
            add(m.receiver, m.timestamp)
        for c in self.session.exec(select(Call).where(Call.run_id == run_id)).all():
            add(c.caller, c.timestamp)
            add(c.receiver, c.timestamp)
        return acc

    def index_run(self, run_id) -> int:
        """(Re)build the index rows for a run. Returns row count. Fails loud on
        a nonexistent run rather than silently indexing nothing."""
        if not self._run_exists(run_id):
            raise ValueError(f"run {run_id} does not exist")
        self.session.exec(delete(EntityIndex).where(EntityIndex.run_id == run_id))
        occ = self._occurrences(run_id)
        rows = [
            EntityIndex(
                run_id=run_id,
                identifier_hash=h,
                identifier_type=d["type"],
                first_seen=d["first"],
                last_seen=d["last"],
                occurrence_count=d["count"],
            )
            for h, d in occ.items()
        ]
        self.session.add_all(rows)
        self.session.commit()
        return len(rows)

    def links_for_run(self, run_id) -> list[RunLink]:
        """Identifiers in this run that also appear in other indexed runs."""
        if not self._run_exists(run_id):
            raise ValueError(f"run {run_id} does not exist")
        occ = self._occurrences(run_id)
        if not occ:
            return []
        rows = self.session.exec(
            select(EntityIndex).where(EntityIndex.identifier_hash.in_(list(occ)))
        ).all()
        by_hash: dict[str, set] = {}
        for r in rows:
            by_hash.setdefault(r.identifier_hash, set()).add(str(r.run_id))

        links: list[RunLink] = []
        for h, d in sorted(occ.items(), key=lambda kv: kv[1]["value"]):
            run_set = by_hash.get(h, set())
            others = sorted(run_set - {str(run_id)})
            if others:  # only surface genuine cross-case hits
                links.append(
                    RunLink(
                        identifier=d["value"],
                        identifier_type=d["type"],
                        also_in_runs=others,
                        case_count=len(run_set | {str(run_id)}),
                    )
                )
        return links
