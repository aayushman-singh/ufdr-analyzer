# HANDOFF — ufdr-analyzer

You are the per-repo orchestrator for `ufdr-analyzer`. You are running in a Claude Code session opened in `c:/Repo/ufdr-analyzer`. Take this repo from current state to portfolio-hire-ready, fully autonomously. User is hands-off.

## Hard rules (do NOT violate)
1. **Never block on the user.** Pick the ambitious path, log calls in `DECISIONS.md`.
2. **Deploy boundary:** the full prod stack (8 containers: Postgres + Redis + Meili + Neo4j + MinIO + nginx + Celery + Next.js + FastAPI) won't run free-tier anywhere. Ship a **slimmed demo profile** — drop Neo4j (Postgres recursive CTE for graph), drop Celery/Redis (inline ingest with SSE progress), keep Postgres + Meili + MinIO managed (Fly.io or Railway), Vercel for Next.js. Bake in **ONE canonical synthetic UFDR**, disable upload in hosted mode, expose "Reset to sample" button.
3. **Codex review:** after each large refactor, `git diff <base>..HEAD | codex exec "review this diff as a senior engineer with no patience for excuses. Find architectural problems, security holes, untested edge cases, naming smell, dead code. Be brutal. No praise."` Save to `codex/<timestamp>.md`.
4. **State persistence:** maintain `STATE.md`.
5. **Backend E2E tests required.**
6. **Use subagents aggressively.**
7. **No fallbacks** — fail loudly. (Especially relevant given current `CORSMiddleware allow_origins=["*"]` + `allow_credentials=True` invalid combo at `backend/main.py:97`.)
8. **`test_comprehensive.ufdr` is 395 MB committed to plain git** (no LFS). DO NOT read it. DO NOT re-extract. Artifacts already at `backend/UFDRConvert/test_comprehensive/` and `ALEAPP/output/test_comprehensive/`.
9. **ALEAPP is vendored** (no `.gitmodules`, ~hundreds of Python files at `ALEAPP/scripts/`). DO NOT grep into ALEAPP. DO NOT `git submodule update`.
10. **Two SQLite DBs are committed** (`backend/ufdr_analyzer.db`, `backend/ingest/database.db`) despite Postgres being canonical. Don't trust them as schema source-of-truth; `db_setup.py` is.
11. **Hardcoded creds in `backend/config.py`** (ufdr_password, neo4j password, meili masterKey). Strip first.
12. **End-of-session:** write `SESSION_SUMMARY.md`.

## Mission
ufdr-analyzer is forensic tooling with a real ML angle (NL → query → cited results). The code shows ambition (3 storage layers, Rust accelerator, vendored ALEAPP, real synthetic forensic fixtures) but doesn't boot end-to-end and leaks credentials. Your job: make the demo path actually run, ship a hosted demo with a deterministic sample case, and turn the LLM call from black-box into an **auditable NL → typed query plan IR → cited results** flow. That IR is the single highest-impact "damn" lever for a forensic-tool reviewer.

## Success criteria (observable)
- `docker-compose.dev.yml` boots cleanly. `docker-compose.yml` (slimmed profile) boots cleanly.
- Hardcoded creds removed; `.env.example` complete; `.env` ignored.
- Compose stack inconsistencies fixed (Dockerfile CMD path mismatch, override file references).
- Hosted demo at a public URL: deterministic synthetic UFDR pre-loaded, NL query box, results with timeline + entity graph + PDF export.
- NL → typed query plan IR → SQL → cited results pipeline visible in UI.
- Audit log (every query, ingest, export) signed + timestamped, exportable.
- Real CI: ingest integration test against synthetic UFDR, frontend type-check, backend pytest.
- README: Mermaid architecture, demo URL, screencast of the NL → cited results flow.
- `codex` review pass committed.

## Repo recon (frozen 2026-06-08)

### What this is
AI-assisted forensic analysis tool for **UFDR** (Universal Forensic Extraction Device Report) zips. Unzips UFDR, runs bundled ALEAPP Android artifact parser, normalises chats/calls/contacts/media into Postgres + Meilisearch + Neo4j, exposes a natural-language query layer. Student/SIH project (SIH25198) framed as a Next.js + Electron desktop investigator workstation.

### Stack
- **Backend:** FastAPI, SQLModel/SQLAlchemy, Alembic (declared, not used), Celery, psycopg2, Meilisearch, neo4j driver, minio, spaCy, ReportLab, OpenAI/OpenRouter/Anthropic
- **Rust accelerator:** `backend/ufdr2dir-rs/` (built — `target/release/ufdr2dir.exe` present)
- **ALEAPP:** vendored as plain files at `ALEAPP/` (no `.gitmodules`)
- **Frontend:** Next.js 15 + React 19 + Tailwind v4 + Radix + Electron 38 + react-d3-tree/reactflow/vis-network/recharts
- **Infra:** 3 compose files (full prod with nginx; dev with postgres+meili; override referencing `app.main:app` / `celery_app` that don't exist)
- **Windows-incompat:** MSYS2 Postgres in DEVELOPMENT.md, `python-magic` needs libmagic DLL, Dockerfiles linux-only

### Current state
- **Local dev works likely:** `docker-compose.dev.yml` + `python backend/server.py` boots FastAPI on 127.0.0.1:8000; tables auto-create via `database.create_db_and_tables()`. Rust extractor pre-built. Real ingestion has been run.
- **Accepts real UFDR:** `test_comprehensive.ufdr` (395 MB synthesised) → `create_small_ufdr.py` slices from `Android_13_Image.ufdr` (not in repo).
- **Broken:**
  - Full `docker-compose.yml` not runnable — `docker/services/Dockerfile.backend` CMD is `uvicorn app.main:app` but entrypoint is `main:app` at backend root
  - Override references `app.workers.celery_app` (doesn't exist)
  - `CORSMiddleware allow_origins=["*"]` with `allow_credentials=True` — invalid combo (`backend/main.py:97`)
  - Hardcoded creds in `backend/config.py`
  - Schema/code drift: `backend/main.py:84` extraction field is `extraction_metadata` but `ingest_service.py:84` writes `metadata=`
  - `Backup` model in `db_setup.py:111` has stray bare-string line
  - Tests at `backend/ingest/tests/` import `from services.parser_service` (wrong path)
  - Storage dirs (`storage/json`, `storage/reports`) empty
- **Frontend:** pages exist as stubs (login/signup/upload/dashboard/analysis-dashboard/global-search/graph-test). No API client layer. No JWT middleware in backend.

### Maturity score
- Code quality: 4/10
- Test coverage: 1/10 (3 broken test files)
- Docs: 6/10 (verbose, aspirational)
- Deploy-readiness: 2/10 (compose stack doesn't boot, secrets baked in)
- Demo-readiness: 3/10 (local works; no hosted; 395MB sample not in LFS)

### Risks
- ALEAPP vendored — don't grep, don't submodule-update
- `test_comprehensive.ufdr` is 395MB plain git — don't read, don't re-extract
- `Android_13_Image.ufdr` source NOT in repo — `create_small_ufdr.py` won't run
- Two SQLite DBs committed — don't trust as schema truth; `db_setup.py` is
- Windows path traps in `parser_service.py`; libmagic DLL not bundled
- No Alembic migrations despite dep; schema is `SQLModel.metadata.create_all`
- No `.env` in repo (gitignored) — backend will fail on first LLM call without one
- Many imports use `sys.path.append` hacks — refactoring cascades

## Plan

### Phase A — Boot the compose stack (S/M, highest priority)
1. Strip hardcoded creds from `backend/config.py`. Fill `env.example`. Verify `.env` is gitignored.
2. Fix `docker/services/Dockerfile.backend` CMD to match entrypoint (`uvicorn main:app` not `app.main:app`).
3. Remove or fix `docker-compose.override.yml` references to nonexistent `app.workers.celery_app`.
4. Fix `CORSMiddleware` config (`backend/main.py:97`): either drop `allow_credentials=True` or list specific origins.
5. Fix schema drift: align `extraction_metadata` vs `metadata` in `ingest_service.py:84`.
6. Fix `Backup` model bare-string in `db_setup.py:111`.
7. Untrack the two SQLite files; gitignore them; rely on `db_setup.py` as schema truth.
8. Boot the dev profile, verify FastAPI on :8000, verify Meili indexing of a sample.
9. **Codex review.**

### Phase B — Slim production profile (M)
1. Build `docker-compose.demo.yml`: Postgres + Meili + MinIO + FastAPI + Next.js. NO Neo4j, NO Celery/Redis, NO nginx.
2. Replace Neo4j entity-graph reads with Postgres recursive CTE in `services/entity_service.py` (new). Keep Neo4j-backed code path behind a feature flag for the full prod profile.
3. Replace Celery ingest with inline FastAPI background task + SSE progress endpoint.
4. Bake the synthetic UFDR (the small one, ~50MB) into the demo image OR a Fly Volume.
5. **Codex review.**

### Phase C — Tests + CI (M)
1. Fix broken test imports under `backend/ingest/tests/`.
2. Add ingest integration test against `test_comprehensive.ufdr` (uses already-extracted artifacts so it doesn't need the 395MB source).
3. Frontend typecheck.
4. GitHub Actions: pytest + frontend build + Rust extractor build on linux.
5. **Codex review.**

### Phase D — NL → IR → cited-results pipeline (XL, headline feature)
1. Define `QueryPlan` typed schema (Pydantic) — fields: entities, time range, predicates, sort, limit.
2. LLM call → produces `QueryPlan` (not SQL directly). Validate.
3. `QueryPlan.to_sql()` translator (deterministic).
4. Result hydration with cited spans (which message_id / call_id / file_id produced each match).
5. UI: show JSON plan + SQL + result snippets with citations.
6. **Codex review.**

### Phase E — Audit log + signed evidence export (M)
1. Promote `Backup` model to a real audit-trail table: query, ingest, export events with timestamp + signature.
2. ReportLab-generated signed PDF export (deterministic, hash-stamped).
3. UI: "Audit log" tab.
4. **Codex review.**

### Phase F — Hosted demo + polish (L)
1. Deploy to Fly.io (Postgres + Meili + MinIO + FastAPI) + Vercel (Next.js).
2. Disable upload in hosted mode; "Reset to sample" button only.
3. Configure with synthetic UFDR pre-loaded.
4. README: Mermaid architecture, hero screencast of NL→IR→cited results, demo URL.
5. **Final codex review.**
6. Write `SESSION_SUMMARY.md`.

## End-of-session output (REQUIRED)
- **What changed** — area-level summary
- **Blocked on user** — Fly/Vercel account setup, DNS, OpenRouter API key for the demo (or document that demo uses a stub LLM), redact `test_comprehensive.ufdr` from history if user wants public release (LFS migrate or remove)
- **Deploy state** — `live at <URL>` for demo profile; full prod `deployable, runbook ready`
- **Codex feedback log** — link to `codex/`

## Start
Read `STATE.md` if exists, otherwise create it and begin Phase A step 1. Go.
