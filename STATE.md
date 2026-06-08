# STATE — ufdr-analyzer orchestration

_Single source of truth for orchestration progress. Updated continuously._

## Environment constraints (frozen this session)
- **Docker NOT available** on this host (`docker: command not found`). Compose files are fixed + statically validated (YAML parse), but **boot is unverifiable here** — logged in DECISIONS.md, runbook provided.
- **`codex` CLI available** (codex-cli 0.135.0) → reviews run per HANDOFF rule 3.
- **Python 3.11.9** available. No venv assumed.
- No Fly.io / Vercel credentials → actual deploy blocked; configs + runbook produced instead.
- `test_comprehensive.ufdr` (395 MB) — NOT read, NOT re-extracted. Artifacts reused.
- ALEAPP vendored — NOT grepped, NOT submodule-updated.

## Phase status
| Phase | Title | Status |
|-------|-------|--------|
| A | Boot compose stack (creds, CORS, Dockerfile, schema drift, gitignore) | IN PROGRESS |
| B | Slim demo profile (drop Neo4j/Celery, CTE graph, SSE ingest) | pending |
| C | Tests + CI | pending |
| D | NL → IR → cited-results pipeline (headline) | pending |
| E | Audit log + signed PDF export | pending |
| F | Hosted demo configs + README polish | pending |

## Phase A checklist
- [ ] A1 Strip hardcoded creds from `backend/config.py`; fill `env.example`; `.env` gitignored
- [ ] A2 Fix `Dockerfile.backend` CMD `app.main:app` → `main:app`
- [ ] A3 Fix `docker-compose.override.yml` (`app.main:app`, `app.workers.celery_app`)
- [ ] A4 Fix CORS invalid combo at `backend/main.py:97`
- [ ] A5 Fix schema drift `ingest_service.py` `metadata=` → `extraction_metadata=`
- [ ] A6 Fix `Backup` model bare-string `db_setup.py:111`
- [ ] A7 Untrack two SQLite DBs; gitignore them
- [ ] A8 Boot dev profile + verify (BLOCKED: no docker — static validation only)
- [ ] A9 Codex review

## Security flags raised
- `.env` contained a **live OpenRouter API key** (`sk-or-v1-...`) and **live Neo4j Aura password**, and was NOT gitignored. → gitignore fixed; **key/password MUST be rotated by user** (see DECISIONS.md + SESSION_SUMMARY.md).
