# SESSION SUMMARY V2 — ufdr-analyzer "go big"

Branch `orchestrator/portfolio-ready`. Two features shipped + a brutal codex review applied. 35 backend tests passing.

## Shipped
### 1. Temporal patterns & anomaly detection (`ingest/services/analytics_service.py`)
Deterministic detectors over a run's message+call timeline, each finding **citation-backed**, plus a deterministic English narrator (no LLM):
- **spike** — z-score with a **leave-one-out baseline** (a day can't mask itself).
- **dormancy** — longest silence between active days, bracketed by cited events (honestly framed; not mislabeled "cessation").
- **drop** — change-point with a **minimum-baseline guard** + after-window citations (no fake 100% drops from sparse data).
- **late_night**, **burst**, **new_contact** (canonical-identifier grouped).
- Fails loud on a nonexistent run; **surfaces `excluded_events`** for missing-timestamp rows (no silent drops); timestamps normalized to naive-UTC.
- Route: `GET /analytics/patterns`. UI: `/patterns` (recharts series + severity-coded findings + narrative hero).

### 2. Cross-case identifier linking (`ingest/services/cross_case_service.py` + `EntityIndex`)
"Does this number appear in other cases?" via a **keyed-HMAC** index over canonical (digits-only) identifiers — raw PII never stored:
- `CROSS_CASE_SALT` HMAC key is **required** (no brute-forceable default); missing → fail loud.
- **No arbitrary-identifier lookup oracle** — only a run's own identifiers link out; hash never returned.
- Deterministic canonical output; real `occurrence_count`/`first_seen`/`last_seen`; `(run_id, hash)` unique constraint.
- Routes: `POST /cross-case/index`, `GET /cross-case/links`. UI: `/cross-case`.

## Codex review (`codex/phase-v2.md`) — applied
Fixed the criticals/highs: privacy oracle + default salt + hash leak (cross-case); spike self-contamination, sparse-data fake drops, mislabeled cessation, citation-contract violations, silent timestamp drops, nonexistent-run false success (analytics). Remaining lower-severity items (E.164 validation, device-owner heuristics, report-injection hardening — UI already React-escaped) noted for later.

## Discovery rejections (DECISIONS.md)
Voice-note transcription (heavy ML, no runtime) and court-grade x509/RFC-3161 (needs live TSA) were deferred — **both are now the V3 mission.**

## State
- 35 tests pass; routes wired in `main.py`; new env var `CROSS_CASE_SALT` documented in `env.example` + `conftest.py`.
- No new blockers beyond the standing ones in `SESSION_SUMMARY.md` (rotate leaked creds, deploy needs cloud login).
