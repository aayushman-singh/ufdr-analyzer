"""Cross-case entity linking — "this number appears in N other cases".

Single-case forensic tools can't answer the question investigators most want:
*have I seen this person before?* This service builds a privacy-preserving index
of identifiers (phone numbers, emails) across every ingested run, storing only a
**salted hash** of each normalized identifier — never the raw value. Matching is
then a hash join across runs, so a hit reveals only *that another case contains
the same identifier you already hold*, not any other PII from that case.

Deterministic given the salt; testable on SQLite. Normalization is explicit so
"+1 (555) 010" and "+1555010" collapse to the same hash.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass

from sqlmodel import Session, delete, select

from db_setup import Call, Contact, EntityIndex, Message

# A salt prevents trivial rainbow-tabling of a small phone-number space. It is
# config, not a credential; set CROSS_CASE_SALT to a shared secret for real
# cross-organization linking. Default is documented and deterministic.
_SALT = os.getenv("CROSS_CASE_SALT", "ufdr-cross-case-v1")

_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_DIGITS_RE = re.compile(r"\d")


def normalize(identifier: str) -> tuple[str, str] | None:
    """Return (normalized_value, type) or None if not a usable identifier."""
    if not identifier:
        return None
    s = identifier.strip()
    if _EMAIL_RE.fullmatch(s):
        return s.lower(), "email"
    # Phone: keep a leading '+' and the digits; require >= 6 digits.
    digits = "".join(_DIGITS_RE.findall(s))
    if len(digits) >= 6:
        plus = "+" if s.lstrip().startswith("+") else ""
        return plus + digits, "phone"
    return None


def hash_identifier(identifier: str) -> str | None:
    norm = normalize(identifier)
    if norm is None:
        return None
    value, _type = norm
    return hashlib.sha256((_SALT + "|" + value).encode("utf-8")).hexdigest()


@dataclass
class RunLink:
    identifier: str            # the querying run's OWN raw identifier (already held)
    identifier_type: str
    identifier_hash: str
    also_in_runs: list[str]    # other run ids sharing this identifier
    case_count: int            # number of distinct runs (incl. this one)


class CrossCaseService:
    def __init__(self, session: Session):
        self.session = session

    def _identifiers_for_run(self, run_id) -> dict[str, tuple[str, str]]:
        """hash -> (raw_example, type) for every identifier appearing in a run."""
        out: dict[str, tuple[str, str]] = {}
        sources: list[str] = []
        for c in self.session.exec(select(Contact).where(Contact.run_id == run_id)).all():
            sources.append(c.number)
        for m in self.session.exec(select(Message).where(Message.run_id == run_id)).all():
            sources += [m.sender, m.receiver]
        for c in self.session.exec(select(Call).where(Call.run_id == run_id)).all():
            sources += [c.caller, c.receiver]
        for raw in sources:
            if not raw:
                continue
            norm = normalize(raw)
            if norm is None:
                continue
            value, vtype = norm
            h = hashlib.sha256((_SALT + "|" + value).encode("utf-8")).hexdigest()
            out.setdefault(h, (raw, vtype))
        return out

    def index_run(self, run_id) -> int:
        """(Re)build the cross-case index rows for a run. Returns row count."""
        self.session.exec(delete(EntityIndex).where(EntityIndex.run_id == run_id))
        idents = self._identifiers_for_run(run_id)
        rows = [
            EntityIndex(run_id=run_id, identifier_hash=h, identifier_type=vtype,
                        occurrence_count=1)
            for h, (_raw, vtype) in idents.items()
        ]
        self.session.add_all(rows)
        self.session.commit()
        return len(rows)

    def links_for_run(self, run_id) -> list[RunLink]:
        """Identifiers in this run that also appear in other indexed runs."""
        idents = self._identifiers_for_run(run_id)
        if not idents:
            return []
        hashes = list(idents)
        rows = self.session.exec(
            select(EntityIndex).where(EntityIndex.identifier_hash.in_(hashes))
        ).all()
        by_hash: dict[str, set] = {}
        for r in rows:
            by_hash.setdefault(r.identifier_hash, set()).add(str(r.run_id))

        links: list[RunLink] = []
        for h, (raw, vtype) in sorted(idents.items(), key=lambda kv: kv[1][0]):
            run_set = by_hash.get(h, set())
            others = sorted(run_set - {str(run_id)})
            if others:  # only surface genuine cross-case hits
                links.append(RunLink(
                    identifier=raw, identifier_type=vtype, identifier_hash=h,
                    also_in_runs=others, case_count=len(run_set | {str(run_id)}),
                ))
        return links

    def lookup(self, identifier: str) -> dict:
        """Which runs contain this identifier (by salted hash)?"""
        h = hash_identifier(identifier)
        if h is None:
            return {"identifier": identifier, "normalized": None, "runs": [], "count": 0}
        rows = self.session.exec(
            select(EntityIndex).where(EntityIndex.identifier_hash == h)
        ).all()
        runs = sorted({str(r.run_id) for r in rows})
        return {
            "identifier": identifier,
            "identifier_hash": h,
            "runs": runs,
            "count": len(runs),
        }
