"""Cross-case entity-graph link analysis — provenance-cited, deterministic.

The cross-case salted-hash index answers *"does this identifier appear elsewhere?"*
This service answers the next question: *"show me the network of how entities
relate, within and across my cases, and prove every link."*

Nodes are entities (phone numbers, emails, accounts, handles) deterministically
extracted from the parsed evidence. Edges are **observed** relations — a message
or call between two parties — and every edge carries the source rows that prove
it (`run_id`, table, row id, timestamp). There are no inferred edges: a relation
exists in the graph iff a record exists for it.

Cross-case identity and privacy reuse the existing salted-hash design:
- A node's identity is derived from a **keyed HMAC** of its canonical identifier,
  so the same person across two cases collapses to a single node, never by raw
  value. The HMAC itself (the cross-case-index key) is never exposed: the node
  `id` is `sha256(hmac)`, so the API/export can be correlated within one response
  without leaking the index key space.
- "PII stays salted-hash where cross-case": a node that appears in 2+ runs is
  **redacted** (surfaced by opaque id + type + which cases), unless it is the
  user-supplied seed (already known to the querier). Single-case nodes — the
  owner's own case data — keep their raw value. Edge citations carry only internal
  ids, never PII, so provenance survives redaction.
- Free-text / handle participants (type "other") are **run-scoped**: their key
  folds in the run id, so a display name like "Mom" or "Unknown" in case A is
  never linked to the same string in case B. Only canonical phone/email
  identifiers, which are low-ambiguity, link across cases.

Edges are **undirected** co-occurrence relations: `source`/`target` are the two
endpoints (ordered by id for determinism), NOT a from→to direction. The cited
source rows preserve the original direction for anyone who needs it.

Deterministic and LLM-free: same evidence + same parameters → byte-identical graph
and content hash. This is what makes the signed export reproducible in court.

See DECISIONS_V4.md (D1–D8) for the rationale behind each rule.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid as _uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

from db_setup import Call, Contact, Message, Run

# Reuse the cross-case primitives so node identity composes with the existing
# salted-hash index and never re-implements identifier handling.
from ingest.services.analytics_service import _to_utc_naive
from ingest.services.cross_case_service import _require_key, normalize

# Cap citations serialized per edge so a million-message thread doesn't produce a
# multi-MB payload OR exhaust memory while building. The true interaction count is
# always kept as `weight`, and `citations_truncated` makes any capping explicit —
# never a silent truncation.
MAX_EDGE_CITATIONS = 50

# Hard ceiling on rows pulled into one graph. Beyond this we fail loud rather than
# silently building a partial graph or OOMing — a forensic surface must not lie by
# omission. Tune per deployment; large cases should be windowed or seeded.
MAX_EVENTS = 500_000


def _display_id(hmac_hex: str) -> str:
    """Public node id = sha256 of the HMAC, so the cross-case index key (the raw
    HMAC) is never exposed over the API while ids stay stable and deterministic."""
    return hashlib.sha256(hmac_hex.encode("utf-8")).hexdigest()


def entity_key(raw: str) -> tuple[str, str, str] | None:
    """Map a raw participant to (display_id, canonical_value, type), run-agnostic.

    Used for seeds and tests. Phone/email are canonicalized via
    `cross_case_service.normalize`; any other string is keyed by its stripped form
    with type "other". For run-scoped "other" identity inside the graph, see
    `_key_for`. Returns None for empty input.
    """
    if not raw or not raw.strip():
        return None
    norm = normalize(raw)
    if norm is not None:
        value, vtype = norm
        material = value
    else:
        value, vtype = raw.strip(), "other"
        material = value
    h = hmac.new(_require_key(), material.encode("utf-8"), hashlib.sha256).hexdigest()
    return _display_id(h), value, vtype


def _key_for(raw: str, run_id: str) -> tuple[str, str, str] | None:
    """Graph-internal keying. Phone/email link across cases (global key); "other"
    participants are namespaced by run so unrelated free-text never merges."""
    if not raw or not raw.strip():
        return None
    norm = normalize(raw)
    if norm is not None:
        value, vtype = norm
        material = value
    else:
        value, vtype = raw.strip(), "other"
        material = f"other|{run_id}|{value}"
    h = hmac.new(_require_key(), material.encode("utf-8"), hashlib.sha256).hexdigest()
    return _display_id(h), value, vtype


@dataclass
class EdgeCitation:
    run_id: str
    source_table: str  # "message" | "call"
    row_id: str
    timestamp: Optional[str]  # ISO-8601, naive-UTC; None only if the row had none

    def as_tuple(self):
        return (self.run_id, self.source_table, self.row_id, self.timestamp or "")


@dataclass
class LinkNode:
    id: str  # sha256(HMAC) of the canonical identifier
    type: str  # "phone" | "email" | "other"
    redacted: bool  # True => cross-case node, raw value withheld
    degree: int = 0  # weighted incident-edge count in the returned graph
    cases: list[str] = field(default_factory=list)  # run ids the entity appears in
    case_count: int = 0
    value: Optional[str] = None  # canonical identifier, only when disclosed
    label: Optional[str] = None  # contact name if known, only when disclosed
    hops: Optional[int] = None  # distance from seed, set only in neighborhood mode

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "redacted": self.redacted,
            "degree": self.degree,
            "cases": self.cases,
            "case_count": self.case_count,
            "value": self.value,
            "label": self.label,
            "hops": self.hops,
        }


@dataclass
class LinkEdge:
    source: str  # endpoint id (lo) — undirected, not a from-direction
    target: str  # endpoint id (hi)
    weight: int  # true total interaction count (== total citations)
    citations: list[EdgeCitation]  # up to MAX_EDGE_CITATIONS of them

    @property
    def citations_shown(self) -> int:
        return len(self.citations)

    @property
    def citations_truncated(self) -> bool:
        return self.weight > len(self.citations)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "target": self.target,
            "weight": self.weight,
            # weight is the honest total; the list may be capped for size.
            "citations_shown": self.citations_shown,
            "citations_truncated": self.citations_truncated,
            "citations": [c.__dict__ for c in self.citations],
        }


@dataclass
class LinkGraph:
    run_ids: list[str]
    seed: Optional[str]
    seed_id: Optional[str]  # display id of the seed entity, for highlighting
    seed_found: bool
    max_hops: Optional[int]
    window_start: Optional[str]
    window_end: Optional[str]
    nodes: list[LinkNode]
    edges: list[LinkEdge]
    excluded_events: int  # rows skipped for missing timestamps (surfaced)

    def to_dict(self) -> dict:
        return {
            "run_ids": self.run_ids,
            "seed": self.seed,
            "seed_id": self.seed_id,
            "seed_found": self.seed_found,
            "max_hops": self.max_hops,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "excluded_events": self.excluded_events,
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
        }


@dataclass
class _Event:
    run_id: str
    table: str  # "message" | "call"
    row_id: str
    ts: Optional[datetime]
    a: str
    b: str


class LinkGraphService:
    """Builds the provenance-cited cross-case entity graph."""

    def __init__(self, session: Session):
        self.session = session

    # -- public API --------------------------------------------------------
    def build(
        self,
        run_ids: list[_uuid.UUID],
        *,
        seed: Optional[str] = None,
        max_hops: Optional[int] = 2,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        owner_id: Optional[_uuid.UUID] = None,
    ) -> LinkGraph:
        """Build the link graph over `run_ids`.

        - `seed`: restrict to the seed entity's `max_hops` neighborhood. Matched by
          id, so it works whether the seed is local or recurs across cases.
        - `start`/`end`: inclusive time window over event timestamps (`start<=end`).
        - `owner_id`: if given, every run must belong to this user (tenant guard).
          Regardless, all runs in one graph must share a single owner — merging two
          users' cases into one graph is refused, not silently allowed.
        Fails loud on an empty run set, a nonexistent run, a cross-owner set, or a
        reversed window — an empty graph and a bad request must not look the same.
        """
        if not run_ids:
            raise ValueError("run_ids must not be empty")
        if max_hops is not None and max_hops < 0:
            raise ValueError("max_hops must be >= 0")
        if (
            start is not None
            and end is not None
            and _to_utc_naive(start) > _to_utc_naive(end)
        ):
            raise ValueError("start must be <= end")

        # Dedupe (sorted, deterministic) and validate existence + single ownership.
        uniq = sorted({str(r) for r in run_ids})
        owners: set[str] = set()
        for rid in uniq:
            run = self.session.get(Run, _uuid.UUID(rid))
            if run is None:
                raise ValueError(f"run {rid} does not exist")
            owners.add(str(run.user_id))
            if owner_id is not None and str(run.user_id) != str(owner_id):
                raise PermissionError(
                    f"run {rid} does not belong to the requesting user"
                )
        if len(owners) > 1:
            raise PermissionError(
                "all runs in one graph must belong to the same owner "
                f"(found {len(owners)} distinct owners)"
            )

        start_n, end_n = _to_utc_naive(start), _to_utc_naive(end)
        events, excluded = self._load_events(uniq, start_n, end_n)

        # Accumulate nodes and edges from the raw event stream. Citations are capped
        # DURING accumulation so a huge thread bounds memory, not just payload.
        node_runs: dict[str, set[str]] = {}
        node_meta: dict[str, tuple[str, str]] = {}  # id -> (canonical_value, type)
        edge_acc: dict[tuple[str, str], LinkEdge] = {}
        for ev in events:
            ka, kb = _key_for(ev.a, ev.run_id), _key_for(ev.b, ev.run_id)
            if ka is None or kb is None:
                continue
            (ia, va, ta), (ib, vb, tb) = ka, kb
            if ia == ib:
                continue  # self-loop (a contacting itself) carries no relation
            node_runs.setdefault(ia, set()).add(ev.run_id)
            node_runs.setdefault(ib, set()).add(ev.run_id)
            node_meta.setdefault(ia, (va, ta))
            node_meta.setdefault(ib, (vb, tb))
            lo, hi = (ia, ib) if ia <= ib else (ib, ia)
            edge = edge_acc.get((lo, hi))
            if edge is None:
                edge = LinkEdge(source=lo, target=hi, weight=0, citations=[])
                edge_acc[(lo, hi)] = edge
            edge.weight += 1
            if len(edge.citations) < MAX_EDGE_CITATIONS:
                edge.citations.append(
                    EdgeCitation(
                        run_id=ev.run_id,
                        source_table=ev.table,
                        row_id=ev.row_id,
                        timestamp=ev.ts.isoformat() if ev.ts else None,
                    )
                )

        labels = self._contact_labels(uniq)

        seed_meta = entity_key(seed) if seed else None
        seed_id = seed_meta[0] if seed_meta else None
        keep = self._neighborhood_ids(edge_acc, seed_id, max_hops) if seed_id else None
        seed_found = bool(seed_id and seed_id in node_runs)

        # Filter to the seed neighborhood if requested.
        if keep is not None:
            edge_acc = {
                k: e
                for k, e in edge_acc.items()
                if e.source in keep and e.target in keep
            }
            node_ids = set(keep) & set(node_runs)
        else:
            node_ids = set(node_runs)

        # Degree is computed over the FINAL edge set so it matches what's returned.
        degree: dict[str, int] = {nid: 0 for nid in node_ids}
        for e in edge_acc.values():
            degree[e.source] = degree.get(e.source, 0) + e.weight
            degree[e.target] = degree.get(e.target, 0) + e.weight

        hops_map = keep if keep is not None else {}
        nodes = [
            self._make_node(
                nid,
                node_runs[nid],
                node_meta[nid],
                labels,
                degree.get(nid, 0),
                seed_id,
                hops_map.get(nid),
            )
            for nid in node_ids
        ]
        nodes.sort(key=lambda n: (-n.degree, n.id))

        edges = []
        for e in edge_acc.values():
            e.citations.sort(key=lambda c: c.as_tuple())
            edges.append(e)
        edges.sort(key=lambda e: (e.source, e.target))

        return LinkGraph(
            run_ids=uniq,
            seed=seed,
            seed_id=seed_id,
            seed_found=seed_found,
            max_hops=max_hops if seed_id else None,
            window_start=start_n.isoformat() if start_n else None,
            window_end=end_n.isoformat() if end_n else None,
            nodes=nodes,
            edges=edges,
            excluded_events=excluded,
        )

    # -- internals ---------------------------------------------------------
    def _load_events(
        self, run_ids: list[str], start: Optional[datetime], end: Optional[datetime]
    ) -> tuple[list[_Event], int]:
        """Stream messages + calls across runs into a deterministic event list.

        Rows with no timestamp are excluded and counted (never silently dropped);
        a time window, if set, is applied inclusively after tz-normalization. Fails
        loud past MAX_EVENTS rather than building a silently-partial graph.
        """
        events: list[_Event] = []
        excluded = 0

        def in_window(ts: Optional[datetime]) -> bool:
            if ts is None:
                return False
            if start is not None and ts < start:
                return False
            if end is not None and ts > end:
                return False
            return True

        for rid in run_ids:
            ru = _uuid.UUID(rid)
            for m in self.session.exec(
                select(Message).where(Message.run_id == ru)
            ).all():
                ts = _to_utc_naive(m.timestamp)
                if ts is None:
                    excluded += 1
                    continue
                if not in_window(ts):
                    continue
                events.append(
                    _Event(rid, "message", str(m.id), ts, m.sender, m.receiver)
                )
            for c in self.session.exec(select(Call).where(Call.run_id == ru)).all():
                ts = _to_utc_naive(c.timestamp)
                if ts is None:
                    excluded += 1
                    continue
                if not in_window(ts):
                    continue
                events.append(_Event(rid, "call", str(c.id), ts, c.caller, c.receiver))
            if len(events) > MAX_EVENTS:
                raise ValueError(
                    f"graph exceeds MAX_EVENTS ({MAX_EVENTS}); narrow the time "
                    "window or seed the query rather than building it whole"
                )

        # Deterministic order so citation lists are reproducible regardless of the
        # DB's row return order.
        events.sort(key=lambda e: (e.ts, e.table, e.run_id, e.row_id))
        return events, excluded

    def _contact_labels(self, run_ids: list[str]) -> dict[str, str]:
        """display id -> contact name, across all runs in scope.

        Keyed by the same id as nodes so a label attaches to the right entity.
        Sorted iteration makes resolution deterministic when a number has multiple
        contact rows (last write wins, in a fixed order). Only phone/email contacts
        resolve (run-agnostic key); free-text contacts are not cross-case anyway.
        """
        out: dict[str, str] = {}
        for rid in run_ids:
            ru = _uuid.UUID(rid)
            rows = self.session.exec(
                select(Contact).where(Contact.run_id == ru).order_by(Contact.name)
            ).all()
            for c in rows:
                if not c.number or not c.name:
                    continue
                k = entity_key(c.number)
                if k is not None:
                    out[k[0]] = c.name
        return out

    @staticmethod
    def _neighborhood_ids(
        edge_acc, seed_id: str, max_hops: Optional[int]
    ) -> dict[str, int]:
        """BFS from `seed_id` over the undirected edge set; returns id -> hops.

        Run in memory because the graph is already materialized (and time-filtered);
        a recursive SQL CTE would re-traverse the unfiltered tables.
        """
        adj: dict[str, set[str]] = {}
        for lo, hi in edge_acc:
            adj.setdefault(lo, set()).add(hi)
            adj.setdefault(hi, set()).add(lo)
        reached = {seed_id: 0}
        if max_hops is None:
            max_hops = 10**9
        frontier = [seed_id]
        d = 0
        while frontier and d < max_hops:
            d += 1
            nxt = []
            for node in frontier:
                for nb in sorted(adj.get(node, ())):
                    if nb not in reached:
                        reached[nb] = d
                        nxt.append(nb)
            frontier = sorted(nxt)
        return reached

    @staticmethod
    def _make_node(
        nid: str,
        runs: set[str],
        meta: tuple[str, str],
        labels: dict[str, str],
        degree: int,
        seed_id: Optional[str],
        hops: Optional[int],
    ) -> LinkNode:
        value, vtype = meta
        cases = sorted(runs)
        is_seed = nid == seed_id
        # Disclosure rule (D3): redact identifiers seen in 2+ cases unless they are
        # the user-supplied seed. Single-case identifiers keep their raw value.
        redacted = (len(cases) >= 2) and not is_seed
        return LinkNode(
            id=nid,
            type=vtype,
            redacted=redacted,
            degree=degree,
            cases=cases,
            case_count=len(cases),
            value=None if redacted else value,
            label=None if redacted else labels.get(nid, value),
            hops=hops,
        )
