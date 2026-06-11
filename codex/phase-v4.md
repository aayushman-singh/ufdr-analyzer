# Codex review — V4 cross-case entity link graph

`codex exec` (senior-engineer, brutal) over the staged backend diff:
`link_graph_service.py`, `graph_export.py`, `link_graph_router.py`,
`test_link_graph.py`. Findings verbatim, then resolutions.

## Findings (verbatim)

- **Critical:** `link_graph_service.py` exposes `seed_id` and stable HMAC node
  IDs, while `link_graph_router.py` accepts arbitrary raw `seed`. Server-side HMAC
  oracle + membership oracle: anyone can submit candidate phones/emails, get their
  HMAC, compare against redacted nodes, and read `seed_found`, `cases`,
  `case_count`, neighborhood shape. Defeats the salted-hash privacy story.
- **Critical:** Router has no caller/owner constraint; the service only checks runs
  exist. `Run.user_id` exists but is never used. Any valid run UUID becomes
  graphable evidence.
- **High:** Audit export hash inconsistent. Router records `content_hash(graph)`,
  but `signed_artifact` returned `content_hash(graph, audit_head_hash)`. The audit
  event does not commit to the artifact hash it returns. Folding the head into
  "content" also breaks determinism (identical evidence → different content hash).
- **High:** Router commits the `export` audit event before rendering the PDF; if
  ReportLab fails the chain records an export that never produced an artifact —
  the docstring claims the opposite.
- **High:** DoS — `_load_events` `.all()` loads every message/call, citations
  stored unbounded, cap applied only at output. Large UFDRs OOM before the cap.
- **High:** Citation truncation lies — `citation_count = len(citations)` AFTER the
  cap; `weight` can be 100000 while it claims 50 citations.
- **Medium:** Free-text/handle participants treated as cross-case identity; "Mom",
  "Unknown", un-namespaced handles collapse unrelated people across cases → false
  forensic links.
- **Medium:** Endpoints sorted to undirected but still named `source`/`target` —
  misleading for directional calls/messages.
- **Medium:** POST export bypasses GET's `hops<=6` cap; no `start<=end` validation
  (reversed windows silently return empty).
- **Tests too narrow:** no `TestClient` route tests, no audit/export contract, no
  HMAC-oracle / auth-ownership / citation-cap / large-input / invalid-range tests.

## Resolutions (applied this wave)

- **HMAC oracle (Critical):** node `id` is now `sha256(hmac)` (`_display_id`) — the
  raw HMAC (the cross-case-index key, == `EntityIndex.identifier_hash`) is never
  exposed over the API. `seed_id` is the same wrapped display id (for highlight),
  not the raw HMAC. Test `test_node_id_is_not_the_raw_hmac`. The residual
  membership signal (`seed_found`/`case_count`) is inherently gated behind auth →
  documented (D8) + `owner_id` scoping below; it cannot be closed without a session
  layer (repo-wide pre-deploy blocker).
- **Ownership (Critical):** `build(..., owner_id=...)`. A graph may never span two
  owners (`PermissionError`), and when `owner_id` is given every run must belong to
  it. Router maps `PermissionError → 403`. Tests
  `test_graph_refuses_to_span_two_owners`, `test_owner_id_must_match`,
  `test_route_export_*`. Wiring `owner_id` to an authenticated identity remains the
  deployment step.
- **Audit hash (High):** `content_hash(graph)` is now head-INDEPENDENT and
  reproducible; `sign()` binds `content_hash || audit_head_hash`. The audit event
  and the artifact commit to the *same* `content_hash`. Tests
  `test_content_hash_is_head_independent`, `test_route_export_json_is_signed_and_audited`.
- **Export ordering (High):** artifact/PDF construction wrapped in try; on failure
  an `export_failed` event (with reason) is appended and 500 raised — matches the
  `timestamp_failed` precedent. Docstring corrected.
- **DoS / memory (High):** citations are capped DURING accumulation
  (`len < MAX_EDGE_CITATIONS`), not just at output; `MAX_EVENTS` ceiling fails loud
  rather than building a silently-partial graph. (Row streaming/pagination noted as
  a future scaling step — `.all()` matches the existing analytics service.)
- **Citation honesty (High):** `weight` is the true total; serialized list is
  capped; `citations_shown` + `citations_truncated` make capping explicit. PDF and
  frontend say "showing M of N". Test `test_citation_cap_keeps_true_weight`.
- **False cross-case merge (Medium):** "other" (free-text/handle) participants are
  run-scoped (`other|{run_id}|{value}`) so they never link across cases; only
  canonical phone/email link cross-case.
- **Undirected naming (Medium):** kept `source`/`target` for graph-viz convention
  but documented prominently that edges are undirected endpoints; the cited rows
  preserve original direction.
- **Validation (Medium):** export `hops` bounded via pydantic `Field(ge=0, le=6)`;
  `start<=end` enforced in the service (fail loud). Tests
  `test_route_export_hops_out_of_range_is_422`, `test_reversed_time_window_fails_loud`.
- **Tests (broadened):** added `TestClient` GET/export contract tests, 404/422/403
  paths, audit-commit contract, opaque-id, citation-cap, reversed-window,
  ownership. Suite: 28 link-graph tests, 77 backend tests green.

Codex could not run pytest (sandbox denied); review was static. Tests verified
locally: `77 passed, 3 skipped`.
