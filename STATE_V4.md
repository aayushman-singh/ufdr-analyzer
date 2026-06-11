# STATE_V4 — orchestrator persistence

Branch: `feat/v4-entity-graph`. Resume by reading this file first.

## Mission
Cross-case **entity-graph link-analysis** surface: nodes = entities, edges = observed
relations with provenance citations. Every node/edge traces to a source record.
Deterministic (no LLM). Court-defensible signed + audit-logged export.

## Inventory of reusable prior-wave parts (do NOT redo)
- `cross_case_service.py` — `normalize()`, salted-HMAC `hash_identifier()`, `CROSS_CASE_SALT` required. Salted-hash cross-case index (`EntityIndex`).
- `entity_service.py` — single-run participant graph (no provenance, no cross-case). Kept as the quick single-run view; V4 adds the richer surface alongside it.
- `analytics_service.py` — temporal layer; `_to_utc_naive()`, `Citation` shape, fixed thresholds.
- `audit_service.py` — hash-chain audit (`record`, `verify_chain`, `export`).
- `evidence_report.py` — signed deterministic PDF: `content_hash` + HMAC `sign` over canonical content, `SECRET_KEY` required.
- Frontend: Next 15 / React 19, `vis-network` + `reactflow` already deps. API base `NEXT_PUBLIC_API_URL`.

## Plan / progress — COMPLETE
- [x] A. `LinkGraphService` — provenance-cited edge extraction over N runs, salted-hash node keying, cross-case redaction, time filter, seed neighborhood. Deterministic. + codex.
- [x] B. `/link-graph` API (graph + signed export) + register router. Frontend force-directed time-filterable page + nav.
- [x] C. Backend E2E (28 tests; provenance, determinism, redaction, time filter, signed export, ownership, route contracts) + codex (`codex/phase-v4.md`, all findings applied) + docs (DEPLOY) + SESSION_SUMMARY_V4.

Status: 77 backend tests pass; frontend type+lint clean. PR opened, not merged.

## Key decisions — see DECISIONS_V4.md (D1–D8) and codex/phase-v4.md
