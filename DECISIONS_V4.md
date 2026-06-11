# DECISIONS_V4 — cross-case entity-graph link analysis

Autonomous decisions for the V4 wave. Bias: ambitious, forensic-defensible, no fallbacks.

## D1 — New `LinkGraphService`, not an extension of `EntityService`
`EntityService` builds a single-run participant graph with aggregate SQL and **no
provenance** (edges carry only a weight). V4 requires per-edge source citations,
cross-case node identity, time filtering, and seed neighborhoods — different
external behaviour. Rather than overload `EntityService` (and risk its existing
tests/endpoints), V4 adds `LinkGraphService` as the provenance + cross-case
surface. `EntityService` stays as the lightweight single-run view.
*Reduction note:* the two overlap on "edges from message/call participants". If a
later wave wants one node, fold `EntityService.build_graph` into
`LinkGraphService.build(run_ids=[r])` and drop the citations for the quick view.

## D2 — Node identity = salted HMAC of the canonical identifier
Cross-case linkage reuses `cross_case_service.hash_identifier` semantics: the same
person across two cases collapses to one node by HMAC, never by raw value. This
composes with the existing `EntityIndex` and keeps raw PII out of any cross-case
key. `CROSS_CASE_SALT` is therefore **required** (already true repo-wide).
Non-phone/email participants (handles, names) are also keyed by a keyed HMAC of
the raw string (type `other`) so no raw PII is ever used as a cross-case key.

## D3 — "PII stays salted-hash where cross-case" → disclosure rule
A node's raw `value`/`label` is disclosed **only when it appears in exactly one of
the runs in scope** (single-case → the owner's own case data) **or it is the
user-supplied seed** (already known to the querier). A node appearing in **2+ runs
is redacted**: `value=null`, `redacted=true`, surfaced by HMAC `id` + `type` +
`case_count` + `also_in_runs`. This is the literal success-criterion wording and
the same posture as the existing salted-hash index. Edge citations carry only
internal ids (`run_id`, `source_table`, `row_id`, `timestamp`) — not PII — so full
provenance survives redaction.

## D4 — Provenance is mandatory; citations capped but never silently
Every edge carries ≥1 `EdgeCitation`. `weight` = the true total interaction count;
`citations` is capped at `MAX_EDGE_CITATIONS` (50) for payload size, and
`citation_count` vs `weight` makes any truncation explicit (no silent caps — house
rule). An edge with zero citations is impossible by construction and asserted in
tests.

## D5 — Time filter reuses the temporal layer's normalization
Optional `start`/`end` (inclusive ISO instants) filter the underlying events
before edges are built, using `analytics_service._to_utc_naive` so tz handling is
consistent with the patterns surface. Rows with no timestamp are **excluded and
counted** (`excluded_events`), never silently dropped.

## D6 — Seed neighborhood = deterministic in-memory BFS
After edges are built, an optional `seed` + `max_hops` restricts the graph to the
seed's k-hop neighborhood via BFS over the undirected edge set (no recursive SQL —
the data is already in memory and must be filtered post-time-window). Seed is
matched by its HMAC id, so it works whether the seed is local or cross-case.

## D7 — Signed export = deterministic JSON artifact + signed PDF, audit-logged
Court-defensible export mirrors `evidence_report`: a canonical JSON serialization
of the graph is SHA-256 hashed and HMAC-signed with `SECRET_KEY`, folded together
with the audit-chain head (recorded as an `export` event first). Primary artifact
is the **signed JSON** (a graph's layout in a PDF is non-deterministic; its logical
content is what must be reproducible). A human-readable signed **PDF summary**
(integrity block + node/edge/citation listing) is also produced for the same
content hash. `SECRET_KEY` required — fail loud if missing, before mutating the
chain.

## D8 — Auth enforced on the link-graph surface (resolved post-review)
*Superseded:* D8 originally shipped with no auth (repo had no session layer) and
a caller-supplied `owner_id`, which made the cross-case graph/export a PII +
membership oracle — flagged at merge review (`codex/v4-merge-gate.txt`).

Now enforced. `ingest/services/auth_service.py` adds a real identity layer:
PBKDF2-HMAC-SHA256 password hashing, HS256 JWTs signed with `SECRET_KEY`, and a
`require_user` dependency. `POST /auth/signup` + `POST /auth/login` issue tokens.
Both `GET /link-graph` and `POST /link-graph/export` now **require** a bearer
token and bind `owner_id` to the *authenticated* identity — it is no longer
accepted from the client. An unauthenticated caller gets **401**; a caller asking
for runs they do not own gets **403** (never an empty-but-revealing graph). Proven
by E2E tests in `backend/tests/test_link_graph.py` + `test_auth.py`.

The rest of the repo's routes remain unauthenticated — adopting `require_user`
across them is the next step, but the oracle on the cross-case surface is closed.
