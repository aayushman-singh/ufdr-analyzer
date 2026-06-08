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
| A | Boot compose stack (creds, CORS, Dockerfile, schema drift, gitignore) | DONE (boot unverifiable — no docker) |
| B | Slim demo profile (drop Neo4j/Celery, CTE graph, SSE ingest) | pending |
| C | Tests + CI | in progress (Phase D suite green: 10/10) |
| D | NL → IR → cited-results pipeline (headline) | core DONE (IR+compiler+executor+planner+tests); route/UI pending |
| E | Audit log + signed PDF export | pending |
| F | Hosted demo configs + README polish | pending |

## Phase A checklist
- [x] A1 Strip hardcoded creds from `backend/config.py`; fill `env.example`; `.env` gitignored
- [x] A2 Fix `Dockerfile.backend` CMD `app.main:app` → `main:app`
- [x] A3 Fix `docker-compose.override.yml` (`app.main:app`, `app.workers.celery_app`)
- [x] A4 Fix CORS invalid combo at `backend/main.py:97`
- [x] A5 Fix schema drift `ingest_service.py` `metadata=` → `extraction_metadata=`
- [x] A6 Fix `Backup` model bare-string `db_setup.py:111`
- [x] A7 Untrack two SQLite DBs; gitignore them
- [~] A8 Boot dev profile — BLOCKED (no docker); config + compose statically validated, import-tested
- [x] A9 Codex review → `codex/phase-a.md`; hardening applied (DATABASE_URL authoritative, placeholder rejection, CORS `*` reject, neo4j-pw-required-when-selected, pw url-encoding, worker gated behind `full` profile)

## Phase D (headline) — modules
- `backend/ai/query_plan.py` — typed Pydantic IR (`QueryPlan`, predicates, enums)
- `backend/ai/query_compiler.py` — deterministic plan→parameter-bound SQL (injection-proof, portable)
- `backend/ai/query_pipeline.py` — executor + citation hydration (`run_plan` → `QueryAnswer`)
- `backend/ai/planner.py` — NL→IR (LLM w/ validation+retry; explicit DEMO stub)
- `backend/tests/test_query_plan.py` — 10 tests, SQLite, all green

## Security flags raised
- `.env` contained a **live OpenRouter API key** (`sk-or-v1-...`) and **live Neo4j Aura password**, and was NOT gitignored. → gitignore fixed; **key/password MUST be rotated by user** (see DECISIONS.md + SESSION_SUMMARY.md).
