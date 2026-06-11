# SESSION_SUMMARY_V4 — cross-case entity-graph link analysis

Branch: `feat/v4-entity-graph`. PR opened, **not merged** (per handoff). All
backend tests green (`77 passed, 3 skipped`); frontend additions type-clean + lint-clean.

## What shipped

A **provenance-cited cross-case entity-graph link-analysis** surface. The prior
cross-case index could say "this number appears elsewhere"; this wave answers
"show me the network of how entities relate, within and across my cases — and
prove every link".

### Backend
- **`ingest/services/link_graph_service.py`** — `LinkGraphService.build(run_ids, *, seed, max_hops, start, end, owner_id)`.
  - Nodes = entities; edges = **observed** message/call co-occurrences. No inferred
    edges — a relation exists iff a source row exists.
  - **Every edge carries `citations`** — `(run_id, source_table, row_id, timestamp)`
    — so each link traces to the rows that prove it.
  - **Deterministic, no LLM**: same evidence + params → byte-identical graph and
    content hash. Sorted everywhere; tz-normalized via the temporal layer's
    `_to_utc_naive`.
  - **Cross-case PII**: node identity is `sha256(HMAC(salt, identifier))` — the raw
    HMAC (cross-case index key) is never exposed. Identifiers in 2+ cases are
    **redacted** (value withheld, surfaced by opaque id + type + case set) unless
    they are the user-supplied seed. Free-text/handle ("other") participants are
    run-scoped so unrelated strings ("Mom", "Unknown") never falsely merge.
  - **Time filter** (`start`/`end`, inclusive, `start<=end` enforced) and
    **seed neighborhood** (deterministic in-memory BFS to `max_hops`).
  - **Tenancy guard**: a graph may never span two owners; `owner_id` scopes to one.
- **`ingest/services/graph_export.py`** — court-defensible signed export. Reusable
  `content_hash` (head-independent → reproducible), `sign` (binds
  `content_hash || audit_head_hash`), `signed_artifact` (primary JSON artifact),
  `build_graph_pdf` (human-readable signed summary, same content hash).
- **`ingest/routers/link_graph_router.py`** — `GET /link-graph`,
  `POST /link-graph/export` (json|pdf). Export records an `export` audit event
  committing to the same `content_hash`; on artifact failure appends
  `export_failed` and 500s (chain reflects the true outcome). Registered in `main.py`.

### Frontend (Next 15 / React 19)
- **`app/link-graph/page.tsx`** — force-directed graph (vis-network barnesHut),
  controls for run ids / seed / hops / time window; click a node for entity detail
  (redaction-aware), click an edge for **source-row provenance**; signed JSON / PDF
  export download. Redacted cross-case nodes render distinctly (🔒).
- **`lib/linkGraphApi.ts`** — typed client. Nav link added in `components/header.tsx`.

### Tests — `backend/tests/test_link_graph.py` (28 tests)
Provenance integrity (every edge cites real rows), determinism + head-independent
content hash + tamper detection, cross-case redaction + seed disclosure, citations
carry no PII, seed neighborhood (0/1/2-hop, cross-case, not-found), time window,
citation-cap honesty, ownership/tenancy (403), opaque-id (no raw HMAC leak),
reversed-window/empty/nonexistent/hops fail-loud, and `TestClient` route contracts
(GET cited graph, 404, signed+audited export, 422 hops bound).

## Success criteria — met
- "network around +91XXXX across all my cases" → `GET /link-graph?run_ids=…&seed=…`
  returns a graph whose **every edge cites source row(s)**; cross-case identifiers
  stay salted-hash (redacted). ✔
- Deterministic, no LLM in the construction path. ✔
- Signed, audit-logged, court-defensible export (JSON + PDF), mirroring the
  existing evidence PDF. ✔

## Codex review
Run after the build (`codex/phase-v4.md`). Flagged 2 critical (HMAC/membership
oracle; no owner constraint), 4 high (audit-hash inconsistency, export-before-render,
DoS, lying citation count), 3 medium (false cross-case merge, undirected naming,
validation bypass), narrow tests. **All applied** this wave — see resolutions in
`codex/phase-v4.md`. Decisions in `DECISIONS_V4.md` (D1–D8).

## Deploy boundary (unchanged scope, hard rule 2)
One-command deployable + templated secrets + runbook already existed (`DEPLOY.md`,
`env.example`). Added to the runbook: `SECRET_KEY` + `CROSS_CASE_SALT` in the Fly
secrets step (both **required** for signed export / cross-case identity) and
smoke-test curls for `/link-graph` + `/link-graph/export`. No deploy executed.

## Known limitations / next
- **Auth**: repo-wide, no session layer. `owner_id` plumbing exists but is
  caller-supplied; the cross-case membership signal is an oracle until `owner_id`
  is bound to an authenticated identity + run-ownership enforced. Pre-deploy blocker
  (shared with all other routes — see `DECISIONS.md`).
- **Scale**: `_load_events` uses `.all()` (matches analytics service); `MAX_EVENTS`
  fails loud past 500k rows. Row streaming/pagination is the next scaling step.
- **HMAC ≠ PKI**: signed exports prove server-side integrity, not third-party X.509
  verifiability (documented in `graph_export.build_graph_pdf`).
- Pre-existing, untouched: legacy Neo4j `graph_router.py` (hardcoded `S:/` path,
  module-level raise) and a frontend `/cross-case/lookup` call with no backend
  endpoint — both out of V4 scope.
