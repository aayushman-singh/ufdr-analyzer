# Codex senior security + perf review — V5 (feat/v5-rbac-graphperf)

Prompt: "Brutal senior security + perf review … RBAC authz-bypass, SQL/auth injection, no-fallback violations, perf-claim honesty."

## Findings (verbatim) + disposition

### Critical — RBAC incomplete: other run-scoped routers still unauthenticated
`/query/plan` and `/link-graph` are gated, but `/query/execute`, `/query/history/{run_id}`,
the audit evidence-report, cross-case, analytics, entity, transcription, report routes accept
`run_id` with no auth. A non-member can hit those with another `run_id`.
**Disposition: FIXED (extended beyond handoff scope).** Added `require_user + authorize_run`
to every run-scoped endpoint. Deny tests added.

### High — allowlist `set[str]` vs `uuid.UUID` rejects all valid requests
**Disposition: FALSE POSITIVE.** `LinkGraphService.build()` first does
`uniq = sorted({str(r) for r in run_ids})`, so the membership test `rid not in authorized_run_ids`
compares `str` against `set[str]`. Proven by `test_owner_can_graph_own_case` / `test_viewer_on_both_owners_cases_can_combine`
returning 200 through the allowlist path. No change.

### Medium — case-existence oracle (404 missing vs 403 unauthorized)
**Disposition: BY DESIGN, documented.** The handoff + V4 route contract require 403 for an
authorized-but-forbidden case (`test_route_non_owner_is_403_not_empty`) and 404 for a
nonexistent run (`test_route_get_nonexistent_run_is_404`). Only an *authenticated* caller can
observe the distinction, and run ids are unguessable UUIDv4. Kept; noted in SESSION_SUMMARY_V5.

### Medium — invalid stored role silently degraded to no-access
**Disposition: FIXED.** Per the project no-fallback rule, a corrupt `role` is now a loud failure:
`effective_role` raises (→ 500 with context logged) on a non-null role outside {viewer,owner},
instead of treating corruption as an ordinary 403.

### Medium — perf benchmark overclaims isolation
**Disposition: FIXED.** Benchmark now captures `EXPLAIN QUERY PLAN` before/after (proves SCAN→SEARCH
via index) and reports a `before_no_index_recheck` inside the same synthetic run. This is a SQLite
synthetic hot-path measurement, not a fresh-connection or production Postgres claim.

### Medium — index deployment gap (`create_all` won't add indexes to existing tables)
**Disposition: FIXED.** Added idempotent migration `backend/migrations/v5_indexes.sql`
(`CREATE INDEX IF NOT EXISTS …`) and documented it.

### Injection
No SQL/auth injection found in V5 additions — query paths are parameter-bound; benchmark DDL is hardcoded.
