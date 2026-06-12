# HANDOFF_REVIEW — ufdr-analyzer (adversarial review + fix, push to main)

You are the per-repo fix orchestrator for `ufdr-analyzer` (forensic UFDR analysis; FastAPI + Next.js). Current `origin/main` carries: the V4 cross-case entity-graph feature (PR #6) AND the "Evidence Terminal" dark restyle — both merged. Run fully autonomously.

## Mission
1. **Fix the V4 security bug codex flagged** (read `codex/v4-merge-gate.txt`): *"unauthenticated link-graph/export endpoint is a PII and membership oracle."* The cross-case graph + signed-export endpoints must enforce owner/case authorization — an unauthenticated (or non-owner) caller must NOT be able to query the graph or learn whether an entity appears across cases (membership oracle) or pull a signed export. For a forensic tool this is critical. Add auth/owner-scoping (consistent with how the rest of the API authenticates) + tests proving an unauthorized caller is rejected (not given an empty-but-revealing answer — reject with 401/403, fail loud).
2. **Adversarially review the Evidence Terminal restyle** (commit f6ab379): broken routes, lost states/handlers, a11y, regressions. Fix real issues only.

## Rules
- `codex exec --skip-git-repo-check "brutal senior review — correctness, security, no-fallback violations, overclaiming. Terse."` on your fix diff; apply; save under `codex/`.
- No fallbacks — fail loud. Backend E2E tests REQUIRED for the auth fix. Verify before push.
- Do NOT touch git history (secrets already scrubbed). **Push to main** (owner authorized).
- Write `REVIEW_SUMMARY.md`. Decide, don't block. Go.
</content>
