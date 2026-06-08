# SESSION SUMMARY — ufdr-analyzer orchestration (2026-06-08)

Branch: **`orchestrator/portfolio-ready`** (6 commits, base `6273bc8`). Working tree clean. 21 backend tests passing.

> Environment limits this session: **no Docker** and **no Fly/Vercel credentials** on the host. Code, compose files and deploy configs are written and statically/import-validated; anything requiring a container runtime or cloud login is marked BLOCKED with a runbook. `codex` CLI WAS available — two brutal reviews were run and acted on.

---

## What changed (area-level)

### Phase A — boot blockers & secrets (DONE; boot unverifiable w/o Docker)
- `backend/config.py` rewritten: every secret comes from env via `load_dotenv`; **no hardcoded credentials**. Fails loudly when DB creds are absent; rejects template placeholders (`CHANGE_ME` etc.); rejects `*` / empty CORS origins; requires `NEO4J_PASSWORD` when `GRAPH_BACKEND=neo4j`; percent-encodes credentials; `DATABASE_URL` is authoritative when set.
- `.gitignore`: `.env`/`.env.*` and the two committed SQLite DBs now ignored; both DBs untracked.
- `backend/main.py`: removed the invalid `allow_origins=["*"] + allow_credentials=True` CORS combo (and the redundant manual CORS middleware); origins from `CORS_ALLOWED_ORIGINS`.
- `Dockerfile.backend` CMD `app.main:app → main:app`; `docker-compose.override.yml` fixed and the dead Celery `worker` override removed; the base-compose `worker` (references a nonexistent `app.workers.celery_app`) gated behind a `full` profile so default `up` no longer crash-loops.
- Schema drift fixed (`ingest_service.py` writes `extraction_metadata=`); `Backup` model stray bare-string fixed.

### Phase D — headline: auditable NL → typed IR → SQL → cited results (DONE)
- `backend/ai/query_plan.py` — strict Pydantic **`QueryPlan` IR** (closed vocabulary; the LLM emits *this*, never raw SQL).
- `backend/ai/query_compiler.py` — **deterministic** plan→SQL. Bound parameters only (**injection-proof**); `LOWER(col) LIKE` portable across Postgres + SQLite; quoted reserved-word tables; unsatisfiable predicates skip tables instead of guessing.
- `backend/ai/query_pipeline.py` — executor + **citation hydration**: every result row carries `{source_table, row_id, column, matched_value, char_start/end, snippet}`.
- `backend/ai/planner.py` — NL→IR via OpenAI-compatible JSON mode with validate-and-retry; explicit deterministic **stub planner** (only under `DEMO_MODE=1` with no key; logged loudly).
- Routes: `POST /query/plan`, `POST /query/plan/preview`.
- UI: `frontend/app/query-plan/page.tsx` + `frontend/lib/queryPlanApi.ts` render the plan JSON, compiled SQL, and cited results (matched span highlighted); nav link added.

### Phase E — audit trail + signed evidence export (DONE)
- `db_setup.AuditEvent` — append-only **hash-chained** table (chain-of-custody).
- `audit_service.py` — `record()` links each event to the prior `entry_hash`; `verify_chain()` recomputes and reports the first tamper break; every query/export is recorded (query events store the plan + SQL + row ids).
- `evidence_report.py` — **deterministic, HMAC-signed PDF** (hashes the logical content incl. audit head, not jittery PDF bytes).
- Routes: `GET /audit`, `GET /audit/verify`, `POST /audit/evidence-report`.

### Phase B — slim demo profile (DONE; SSE ingest deferred)
- `docker-compose.demo.yml` — Postgres + Meili + MinIO + FastAPI + Next.js only (no Neo4j/Celery/Redis/nginx); required secrets use `${VAR:?}` fail-loud.
- `entity_service.py` — participant graph from messages+calls; `neighborhood()` uses a **recursive CTE** (portable) to traverse N hops — replaces Neo4j reads behind `GRAPH_BACKEND=postgres`. Routes `GET /entities/graph`, `/entities/neighborhood`.

### Phase C — tests + CI (DONE)
- `.github/workflows/ci.yml` — backend pytest, frontend `tsc --noEmit`, Rust `cargo build`.
- Fixed broken `backend/ingest/tests` imports; `importorskip`-guarded heavy-dep tests; `conftest.py`/`pytest.ini`. New tests: query-plan (10), audit+export (5), entity-graph (4), ingest-artifacts smoke. **21 pass; `ingest/tests` collects cleanly.**

### Phase F — deploy configs + README (DONE; deploy BLOCKED)
- `DEPLOY.md` (Fly + Vercel runbook, user-blocked steps flagged), `fly.toml`, `frontend/vercel.json`, README architecture + NL→IR Mermaid diagrams, headline-feature section, security note.

### Codex reviews (HANDOFF rule 3)
- `codex/phase-a.md` — findings folded into the Phase A hardening commit.
- `codex/phase-bde.md` — headline review; **fixed**: reserved-word SQL bug, audit payload now carries IR+SQL, `echo` PII leak, signing-before-mutation + signed audit head, UUID 422 validation, graph determinism + `degree`/`hops` split. **Accepted limitations documented** (see DECISIONS.md): no authn/authz on routes, HMAC≠PKI, audit `seq` race / no append-only DB enforcement, no Alembic migration, export re-runs query.

---

## Blocked on user (action required)
1. **SECURITY INCIDENT — rotate + purge.** A live **OpenRouter API key** and **Neo4j Aura password** were committed to git **history** (commits `d76f478`, `357bd36`) and were present in the local `.env`. Treat as compromised: **rotate both now**, then purge history (`git filter-repo`/BFG) before any public push. `.env` is now gitignored but history still contains the secrets.
2. **Hosted deploy** needs Fly.io + Vercel login/DNS — runbook in `DEPLOY.md`; every credential step flagged `[BLOCKED: needs user]`.
3. **Decide on `test_comprehensive.ufdr` (395 MB in plain git)** — LFS-migrate or remove from history before publishing.
4. **Before any real (non-demo) deployment:** add authn/authz + run-ownership checks to the new routes, a unique constraint/lock on `AuditEvent.seq`, and Alembic migrations (see DECISIONS.md "Accepted limitations").

## Deploy state
- **Demo profile:** `deployable, runbook ready` (`docker-compose.demo.yml` + `DEPLOY.md` + `fly.toml` + `vercel.json`). Not live — no Docker host / cloud creds this session.
- **Full prod profile:** `docker-compose.yml` fixed (worker gated); Celery task module still unimplemented (documented).

## Codex feedback log
- `codex/phase-a.md`, `codex/phase-bde.md`.

## How to run locally (when a Docker host is available)
```bash
cp env.example .env   # fill real secrets (config rejects CHANGE_ME placeholders)
docker compose --env-file .env -f docker-compose.demo.yml up --build
# backend  :8000   frontend :3000
# headline : POST /query/plan {"question":"...","run_id":"<uuid>"}
# tests    : cd backend && DATABASE_URL=sqlite:// python -m pytest tests/ -q
```
