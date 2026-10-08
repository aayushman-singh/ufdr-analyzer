# DEPLOY — CiteSpan slim demo profile

Runbook for the **slim demo profile**: a public, read-only demo with one
canonical synthetic UFDR pre-loaded.

```
Next.js (Vercel, static export)  →  FastAPI (Fly.io)  →  Postgres + Meilisearch + MinIO (Fly.io)
```

NOT in this profile: Neo4j, Celery, Redis, nginx. Graph reads use a Postgres
recursive CTE; ingest runs inline. Upload is disabled (`DEMO_MODE=1`); the only
mutation a visitor can trigger is the "Reset to sample" button.

The public product name is CiteSpan. Commands and URLs that use `ufdr-analyzer`
below are repository or legacy deployment references. They do not rename the
public product or replace existing legacy links.

Every env var name in this document matches `backend/config.py` exactly.

> **This session produced configs + this runbook only.** No deploy was executed:
> there are no Fly.io / Vercel credentials and no Docker on this host. Every step
> that needs your credentials is marked **[BLOCKED: needs user]**.

---

## (a) Prerequisites — [BLOCKED: needs user]

- **[BLOCKED: needs user]** Fly.io account + `flyctl` installed and authenticated:
  ```sh
  # install: https://fly.io/docs/flyctl/install/
  flyctl auth login
  ```
- **[BLOCKED: needs user]** Vercel account + `vercel` CLI installed and authenticated:
  ```sh
  npm i -g vercel
  vercel login
  ```
- **[BLOCKED: needs user]** A **rotated** OpenRouter (or OpenAI-compatible) API key.
  The key previously committed to git history is compromised — see DECISIONS.md.
  Omit it entirely to run the deterministic **stub planner** (`DEMO_MODE=1` + no
  `OPENAI_API_KEY`); the stub logs loudly on every call.

The backend image is the existing `docker/services/Dockerfile.backend`
(entrypoint `uvicorn main:app`, port 8000). The build context is the **repo root**
because the Dockerfile runs `COPY backend/ .`.

---

## (b) Provision Postgres + Meilisearch + MinIO

Pick managed services or run them as Fly apps. Whichever you choose, the backend
needs the env vars in the table below set (secrets via `fly secrets set`,
non-secrets already in `fly.toml`'s `[env]`).

| Service | Backend env vars (names from `backend/config.py`) | Secret? |
|---|---|---|
| Postgres | `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_DB` | no |
| Postgres | `POSTGRES_PASSWORD` *(or a full `DATABASE_URL`, which wins outright)* | **yes** |
| Meilisearch | `MEILI_URL` | no |
| Meilisearch | `MEILI_MASTER_KEY` | **yes** |
| MinIO | `MINIO_ENDPOINT`, `MINIO_BUCKET` | no |
| MinIO | `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY` | **yes** |

### Postgres on Fly — [BLOCKED: needs user]
```sh
flyctl postgres create --name ufdr-analyzer-db --region iad
# Note the printed superuser creds. Create the app DB + role:
flyctl postgres connect -a ufdr-analyzer-db
#   CREATE ROLE ufdr_user LOGIN PASSWORD '<REAL_PASSWORD>';
#   CREATE DATABASE ufdr_analyzer OWNER ufdr_user;
```
Internal DNS `ufdr-analyzer-db.internal` (already in `fly.toml` `[env]`) resolves
on the Fly private network once the backend app is attached.

### Meilisearch on Fly — [BLOCKED: needs user]
```sh
flyctl launch --image getmeili/meilisearch:v1.10 --name ufdr-analyzer-meili \
  --region iad --internal-port 7700 --no-deploy
flyctl secrets set -a ufdr-analyzer-meili MEILI_MASTER_KEY='<REAL_MASTER_KEY>'
flyctl volumes create meili_data -a ufdr-analyzer-meili --region iad --size 1
flyctl deploy -a ufdr-analyzer-meili
```

### MinIO on Fly — [BLOCKED: needs user]
```sh
flyctl launch --image minio/minio --name ufdr-analyzer-minio \
  --region iad --internal-port 9000 --no-deploy
flyctl secrets set -a ufdr-analyzer-minio \
  MINIO_ROOT_USER='<ACCESS_KEY>' MINIO_ROOT_PASSWORD='<SECRET_KEY>'
flyctl volumes create minio_data -a ufdr-analyzer-minio --region iad --size 5
flyctl deploy -a ufdr-analyzer-minio
# Create the bucket once (mc, or the MinIO console): bucket name = ufdr-files
```

---

## (c) Deploy FastAPI to Fly

`fly.toml` already encodes: internal port 8000, an HTTP service with a health
check on `/health/`, and the non-secret `[env]` block. Review/adjust the
`POSTGRES_HOST` / `MEILI_URL` / `MINIO_ENDPOINT` and `CORS_ALLOWED_ORIGINS`
values to match your actual app names and Vercel origin.

**[BLOCKED: needs user]** Create the app and set secrets (names match `config.py`):
```sh
flyctl apps create ufdr-analyzer-api

# Secrets — NEVER in fly.toml. Placeholder values shown.
flyctl secrets set -a ufdr-analyzer-api \
  POSTGRES_PASSWORD='<REAL_PASSWORD>' \
  MEILI_MASTER_KEY='<REAL_MASTER_KEY>' \
  MINIO_ACCESS_KEY='<ACCESS_KEY>' \
  MINIO_SECRET_KEY='<SECRET_KEY>' \
  SECRET_KEY='<STRONG_RANDOM>' \
  CROSS_CASE_SALT='<STRONG_SHARED_SECRET>'

# SECRET_KEY     — HMAC key that signs evidence + link-graph exports. Required for
#                  any signed export; the export endpoints fail loud without it.
# CROSS_CASE_SALT — HMAC key for cross-case identifier hashing AND link-graph node
#                  identity. Required; a missing/default key makes phone/email
#                  hashes brute-forceable, so the service refuses to start the
#                  cross-case / link-graph paths without it.

# Optional — real LLM planner. Omit to use the DEMO stub planner.
flyctl secrets set -a ufdr-analyzer-api OPENAI_API_KEY='<ROTATED_KEY>'

# Deploy from the REPO ROOT (Dockerfile does `COPY backend/ .`):
flyctl deploy --dockerfile docker/services/Dockerfile.backend .
```

The backend public URL will be `https://ufdr-analyzer-api.fly.dev` (used as
`NEXT_PUBLIC_API_URL` in step (d)).

---

## (d) Deploy Next.js to Vercel

The frontend (`frontend/`) is Next.js 15. Its `next.config.ts` sets
`output: "export"`, so the build emits a **fully static site** (the same build
used for the Electron bundle) — no SSR/route-handler runtime. `frontend/vercel.json`
pins `framework: nextjs`.

`NEXT_PUBLIC_API_URL` is inlined at **build time** (the `NEXT_PUBLIC_` prefix),
so it must be set before the build and a change requires a rebuild.

**[BLOCKED: needs user]**
```sh
cd frontend
vercel link            # select / create the project
vercel env add NEXT_PUBLIC_API_URL production
#   value: https://ufdr-analyzer-api.fly.dev
vercel --prod          # builds the static export and deploys
```

After the first deploy you'll get the Vercel origin (e.g.
`https://ufdr-analyzer.vercel.app`). Put that exact origin into the backend's
`CORS_ALLOWED_ORIGINS` (`fly.toml` `[env]`) and redeploy the backend — credentialed
CORS forbids `*`, so the origin must be listed explicitly.

---

## (e) One-time seed of the canonical synthetic UFDR + DEMO_MODE

`DEMO_MODE=1` (already in `fly.toml`) disables upload and makes "Reset to sample"
the only mutation. The demo must boot with one synthetic UFDR already ingested.

**[BLOCKED: needs user]** Run the seed once against the deployed backend. Use the
pre-extracted artifacts already in the repo (`backend/UFDRConvert/test_comprehensive/`)
— do **not** re-extract the 395 MB source.

```sh
# Open a one-off shell on the backend machine:
flyctl ssh console -a ufdr-analyzer-api

# Inside the container, run the project's seed/ingest entrypoint against the
# bundled synthetic case so the sample run_id exists. Confirm the exact script
# name in backend/ before running; the demo's "Reset to sample" button re-points
# the UI at this canonical run_id rather than re-uploading.
```

> The exact seed command depends on the demo-seed entrypoint added in Phase B/F.
> The contract this runbook relies on: after seeding, a known `run_id` exists and
> `POST /query/plan` returns cited rows for it. Verify with step (f).

---

## (f) Post-deploy smoke test

**Health** (expect `{"status":"OK"}`):
```sh
curl -fsS https://ufdr-analyzer-api.fly.dev/health/
```

**Auditable NL query** — `POST /query/plan` (expect a JSON bundle with `plan`,
`sql`, and `rows[].citations`):
```sh
curl -fsS -X POST https://ufdr-analyzer-api.fly.dev/query/plan \
  -H 'Content-Type: application/json' \
  -d '{
        "question": "show me chats mentioning bitcoin",
        "run_id": "<SEEDED_RUN_ID>"
      }'
```

**Plan preview without execution** — `POST /query/plan/preview` (shows the typed
plan + compiled SQL, runs nothing):
```sh
curl -fsS -X POST https://ufdr-analyzer-api.fly.dev/query/plan/preview \
  -H 'Content-Type: application/json' \
  -d '{"question": "whatsapp calls to +15551234567", "run_id": "x"}'
```

**Authenticate first** — the link-graph endpoints are owner-scoped and require a
bearer token. Register (or log in) to obtain one; the graph only ever covers the
authenticated user's own cases:
```sh
TOKEN=$(curl -fsS -X POST https://ufdr-analyzer-api.fly.dev/auth/signup \
  -H 'Content-Type: application/json' \
  -d '{"username":"IO","email":"io@example.gov","password":"<STRONG_PW>"}' \
  | python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
```

**Cross-case link graph** — `GET /link-graph` (expect `nodes`/`edges`, every edge
carrying `citations`; identifiers in 2+ cases come back `redacted:true`). Without
the token this returns **401**; a `<RUN_ID>` you do not own returns **403** — by
design, so it is not a membership oracle:
```sh
curl -fsS -H "Authorization: Bearer $TOKEN" \
  "https://ufdr-analyzer-api.fly.dev/link-graph?run_ids=<RUN_ID>&seed=%2B15551234567&hops=2"
```

**Signed graph export** — `POST /link-graph/export` (expect a signed artifact with
`content_hash` + `signature`; requires `SECRET_KEY` + `CROSS_CASE_SALT`; same
bearer token; the `export` event records the exporting user):
```sh
curl -fsS -X POST https://ufdr-analyzer-api.fly.dev/link-graph/export \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"run_ids": ["<RUN_ID>"], "seed": "+15551234567", "format": "json"}'
```

**Frontend**: open the Vercel URL, confirm the NL query box returns results with
visible citations, that the **Link Graph** page renders a force-directed network
whose edges expose source-row provenance on click, and that the upload control is
hidden / disabled while "Reset to sample" is present (because `DEMO_MODE=1`).

If `/query/plan` 500s with a planner error, you either set no `OPENAI_API_KEY`
without `DEMO_MODE=1`, or the key is invalid — both fail loudly by design.
