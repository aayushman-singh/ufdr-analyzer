# DECISIONS — ufdr-analyzer

Autonomous calls made by the orchestrator. Per HANDOFF rule 1, the user is never blocked; ambitious-path choices are logged here instead.

| # | Decision | Rationale | Reversible? |
|---|----------|-----------|-------------|
| 1 | Docker unavailable on this host → fix + statically validate compose, do NOT mark "boots cleanly" as verified. | Cannot install Docker non-interactively; static YAML/CMD correctness is the achievable bar. Runbook documents the boot command. | n/a |
| 2 | `.env` added to `.gitignore` immediately; live secrets left in local `.env` untouched but flagged for rotation. | `.env` held a live OpenRouter key + Neo4j Aura password and was tracked-eligible (`??`, not ignored). Stopping the leak is priority 0. I will NOT rotate keys myself (no creds), but flag loudly. | yes |
| 3 | `config.py` sources all secrets from env via `load_dotenv` + `_require()`; non-secret connection params (host/port/dbname) keep dev defaults. Missing secret → raise loudly (no silent default). | Honors "strip hardcoded creds" + user's no-fallback rule. `database.py` already prefers `DATABASE_URL` env, so this composes. | yes |
| 4 | Demo profile drops Neo4j + Celery/Redis + nginx; full-prod compose retained behind the original `docker-compose.yml`. Graph reads move to Postgres recursive CTE behind a `GRAPH_BACKEND` flag. | HANDOFF rule 2 deploy boundary — full stack won't run free-tier. | yes |
| 5 | LLM demo path uses the NL→IR pipeline; if no LLM key present, a deterministic stub planner is used **only when `DEMO_MODE=1` is explicitly set**, and it logs loudly that it is a stub. | Hosted demo must work without leaking a real key; the stub is explicit opt-in, not a silent fallback. | yes |

## Codex review of headline (codex/phase-bde.md) — triage

**Fixed this session (cheap + high-impact):**
- Reserved-word bug: `call`/`user` are PostgreSQL keywords → quoted all table identifiers in the compiler and entity service (SQLite tests didn't catch this).
- Audit event now records the typed plan + compiled SQL + result row ids (not just counts) — the chain now actually proves the NL→IR→SQL→rows claim.
- `database.py` `echo=True` removed (was leaking phone numbers/message text/params to logs); now `SQL_ECHO=1` opt-in only.
- Evidence export: `SECRET_KEY` check + PDF build moved BEFORE recording the export audit event (chain never claims a failed export); audit head hash folded into the signed content so the custody pointer is authenticated; signed payload widened to planner/total.
- `run_id` request fields typed `uuid.UUID` → invalid input is 422, not 500.
- Entity graph determinism: ORDER BY tie-breakers added; `degree` vs `hops` dual-semantics naming bug split into two fields.
- Honest docstrings: audit `record()` states it commits; HMAC is documented as a keyed integrity signature, not PKI.

**Accepted limitations (documented, out of scope for a portfolio demo — NOT production CJIS-grade):**
- **No authn/authz** on the new routes — anyone reaching the API can query/export. Needs JWT + run-ownership checks before any real deployment. (Backend has no auth layer yet repo-wide.)
- **HMAC ≠ PKI**: the signed PDF proves server-side integrity, not third-party-verifiable X.509 signing. Documented in `evidence_report.build_evidence_pdf`.
- **Audit chain `seq` race + no append-only DB enforcement**: `record()` computes `seq+1` without a unique constraint/lock; a privileged DB writer could rewrite the chain. Needs a unique constraint on `seq`, row-level locking, and ideally DB triggers / external anchoring.
- **No Alembic migration** for `audit_event` (schema is still `SQLModel.metadata.create_all`); repo-wide pre-existing gap.
- **Export re-runs the query** rather than exporting a frozen prior result — fine for the static demo case; a real system should export an immutable stored result snapshot.
- Timestamp round-trip across DB drivers could theoretically affect chain re-hash on Postgres (verified consistent on SQLite). Would store the exact hashed ISO string in prod.

## Blocked-on-user (carried to SESSION_SUMMARY.md)
- **ROTATE the OpenRouter API key and Neo4j Aura password** that were present in `.env` — treat as compromised.
- Fly.io + Vercel account/login, DNS — needed for real deploy (configs + runbook provided).
- Decide whether to scrub `test_comprehensive.ufdr` (395 MB) from git history (LFS migrate or `filter-repo`) before any public push.
