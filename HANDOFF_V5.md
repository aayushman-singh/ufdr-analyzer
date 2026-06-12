# HANDOFF_V5 — ufdr-analyzer (security + performance)

Per-repo orchestrator for `ufdr-analyzer` (forensic; FastAPI + Next.js). V5 theme: **security + performance only — no new features.** Auth was just added (JWT). Run autonomously. Do NOT touch git history (secrets scrubbed).

## Targets (both, real + measured)
1. **SECURITY — case-level RBAC.** The new JWT auth gates access but every authenticated user can reach every case. Add per-case roles (owner / viewer) so a user can only query/graph/export cases they're authorized on. Enforce server-side on the link-graph, query, and export routes. Tests: a user authorized on case A is rejected (403) on case B's graph/export.
2. **PERFORMANCE — large-case query + graph performance.** Profile the hot paths (QueryPlan→SQL execution, entity-graph build, citation hydration) on a large synthetic case. Add DB indexes on the actual hot columns, paginate/stream large result sets, and cap + lazy-expand the graph (don't build the whole N-node graph eagerly). **Measure** query + graph build latency before/after on a large case; numbers in the summary.

## Rules
- No fallbacks — fail loud (forensic tool). Backend E2E tests REQUIRED for RBAC. Determinism of the graph must be preserved.
- `codex exec --skip-git-repo-check "brutal senior security + perf review — authz bypass, injection, no-fallback, perf-claim honesty"` on your diff; apply; save under `codex/`.
- **Branch `feat/v5-rbac-graphperf`. Open a PR. DO NOT merge** — maintainer gates first.
- Write `SESSION_SUMMARY_V5.md` (RBAC model, before/after perf numbers, proof). Decide, don't block. Go.
</content>
