"""Entity-relationship graph from Postgres — no Neo4j required.

The slim demo profile drops Neo4j. The entity graph an investigator cares about
(who talked to whom) is derivable directly from the normalized tables: each
message/call is an edge between two participants. This service builds that graph
with plain SQL, and answers "who is within N hops of this number?" with a
recursive CTE — the same query runs on PostgreSQL (demo/prod) and SQLite (tests).

`GRAPH_BACKEND=neo4j` keeps the legacy Neo4j path; `postgres` (default) uses this.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Uuid, bindparam, text
from sqlmodel import Session

# Undirected participant edges from both messages and calls, aggregated with a
# weight = interaction count. Built once and reused by both queries below.
_EDGES_CTE = """
WITH pair AS (
    SELECT sender AS a, receiver AS b FROM message
        WHERE run_id = :run_id AND sender IS NOT NULL AND receiver IS NOT NULL
    UNION ALL
    SELECT caller AS a, receiver AS b FROM call
        WHERE run_id = :run_id AND caller IS NOT NULL AND receiver IS NOT NULL
),
norm AS (  -- canonicalize direction so a-b and b-a collapse
    SELECT CASE WHEN a <= b THEN a ELSE b END AS lo,
           CASE WHEN a <= b THEN b ELSE a END AS hi
    FROM pair
)
SELECT lo, hi, COUNT(*) AS weight FROM norm GROUP BY lo, hi
"""


@dataclass
class GraphNode:
    id: str
    label: str  # contact name if known, else the raw identifier
    degree: int


@dataclass
class GraphEdge:
    source: str
    target: str
    weight: int


@dataclass
class EntityGraph:
    nodes: list[GraphNode]
    edges: list[GraphEdge]

    def to_dict(self) -> dict:
        return {
            "nodes": [n.__dict__ for n in self.nodes],
            "edges": [e.__dict__ for e in self.edges],
        }


class EntityService:
    """Postgres/SQLite entity graph over participants in a run."""

    def __init__(self, session: Session):
        self.session = session

    def _bind(self, sql: str, **params):
        stmt = text(sql).bindparams(bindparam("run_id", type_=Uuid(as_uuid=True)))
        return self.session.execute(stmt, params)

    def _contact_labels(self, run_id) -> dict[str, str]:
        rows = self._bind(
            "SELECT number, name FROM contact WHERE run_id = :run_id",
            run_id=run_id,
        ).mappings()
        return {r["number"]: r["name"] for r in rows if r["number"]}

    def build_graph(self, run_id) -> EntityGraph:
        """Full participant graph for a run (nodes + weighted edges)."""
        labels = self._contact_labels(run_id)
        edges: list[GraphEdge] = []
        degree: dict[str, int] = {}
        for r in self._bind(_EDGES_CTE, run_id=run_id).mappings():
            lo, hi, w = r["lo"], r["hi"], int(r["weight"])
            edges.append(GraphEdge(source=lo, target=hi, weight=w))
            degree[lo] = degree.get(lo, 0) + w
            degree[hi] = degree.get(hi, 0) + w
        nodes = [
            GraphNode(id=ident, label=labels.get(ident, ident), degree=deg)
            for ident, deg in sorted(degree.items(), key=lambda kv: -kv[1])
        ]
        return EntityGraph(nodes=nodes, edges=edges)

    def neighborhood(self, run_id, seed: str, max_hops: int = 2) -> EntityGraph:
        """Entities within `max_hops` of `seed`, via a recursive CTE."""
        if max_hops < 0:
            raise ValueError("max_hops must be >= 0")
        sql = """
        WITH RECURSIVE adj(a, b) AS (
            SELECT sender, receiver FROM message
                WHERE run_id = :run_id AND sender IS NOT NULL AND receiver IS NOT NULL
            UNION ALL
            SELECT receiver, sender FROM message
                WHERE run_id = :run_id AND sender IS NOT NULL AND receiver IS NOT NULL
            UNION ALL
            SELECT caller, receiver FROM call
                WHERE run_id = :run_id AND caller IS NOT NULL AND receiver IS NOT NULL
            UNION ALL
            SELECT receiver, caller FROM call
                WHERE run_id = :run_id AND caller IS NOT NULL AND receiver IS NOT NULL
        ),
        reach(node, hops) AS (
            SELECT CAST(:seed AS VARCHAR), 0
            UNION
            SELECT adj.b, reach.hops + 1
            FROM adj JOIN reach ON adj.a = reach.node
            WHERE reach.hops < :max_hops
        )
        SELECT node, MIN(hops) AS hops FROM reach GROUP BY node
        """
        stmt = text(sql).bindparams(bindparam("run_id", type_=Uuid(as_uuid=True)))
        reached = {
            r["node"]: int(r["hops"])
            for r in self.session.execute(
                stmt, {"run_id": run_id, "seed": seed, "max_hops": max_hops}
            ).mappings()
        }
        if not reached:
            return EntityGraph(nodes=[], edges=[])

        # Restrict the full graph to the reached node set.
        full = self.build_graph(run_id)
        labels = {n.id: n.label for n in full.nodes}
        nodes = [
            GraphNode(id=ident, label=labels.get(ident, ident), degree=hops)
            for ident, hops in sorted(reached.items(), key=lambda kv: kv[1])
        ]
        edges = [
            e for e in full.edges
            if e.source in reached and e.target in reached
        ]
        return EntityGraph(nodes=nodes, edges=edges)
