# HANDOFF_V4 — ufdr-analyzer

You are the per-repo orchestrator for `ufdr-analyzer` (forensic UFDR analysis; FastAPI backend + Next.js frontend + docker-compose). Prior waves shipped: typed `QueryPlan` IR → deterministic SQL compiler, hash-chained audit + RFC 3161 timestamping, salted-hash cross-case linking, temporal anomaly detection, faster-whisper transcription. Execute this wave fully autonomously.

## Hard rules
1. Never block on the user — decide + `DECISIONS_V4.md`, bias ambitious.
2. Deploy boundary: stop at one-command deployable + templated secrets + RUNBOOK (needs DB/meili/minio). Do NOT touch leaked-credential history — that is a separate user-only rotation task.
3. Codex after each large refactor: `codex exec "review this diff as a senior engineer with no patience for excuses. Find architectural problems, security holes, untested edge cases, naming smell, dead code. Be brutal. No praise."` Apply + save under `codex/`.
4. `STATE_V4.md` persistence; read first on resume.
5. Backend E2E tests REQUIRED. No fallbacks — for a forensic tool an LLM that hallucinates or a silent skip is unusable; fail loud + log context.
6. Branch `feat/v4-entity-graph`. PR at end, no merge.

## Mission
The cross-case salted-hash index answers "does this number appear elsewhere?" but there is no **graph view of how entities relate within and across cases**. Build a **cross-case entity graph link-analysis** surface: nodes = entities (numbers, accounts, devices, people) deterministically extracted from the evidence; edges = observed relations (co-occurrence in a message thread, call, shared device) with provenance citations. Every node/edge must trace to a source record — no inferred edges without a citation.

## Success criteria (observable)
- A query like "show the network around +91XXXX across all my cases" returns a graph whose every edge cites the source row(s); PII stays salted-hash where cross-case.
- Deterministic: same evidence → same graph. No LLM in the graph-construction path.
- Export the graph as a court-defensible artifact (signed, audit-logged like the existing PDF export).

## Plan
A. Schema + deterministic edge-extraction over existing parsed evidence; provenance hydration. Codex.
B. API endpoint + frontend graph viz (force-directed, time-filterable to reuse the temporal layer).
C. Backend E2E tests (provenance integrity, determinism) + signed export + docs. Codex. `SESSION_SUMMARY_V4.md`.

## Start
Read `STATE_V4.md` else create it; begin Phase A. Go.
</content>
