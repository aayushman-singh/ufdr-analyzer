Reading additional input from stdin...
OpenAI Codex v0.135.0
--------
workdir: C:\Repo\ufdr-analyzer
model: gpt-5.5
provider: openai
approval: never
sandbox: read-only
reasoning effort: xhigh
reasoning summaries: none
session id: 019ea7a1-c770-7640-8493-e0840aa8e518
--------
user
review this diff as a senior engineer with no patience for excuses. Find architectural problems, security holes, untested edge cases, naming smell, dead code. Be brutal. No praise.

<stdin>
diff --git a/.gitignore b/.gitignore
index 8f6f9d4..4a07698 100644
--- a/.gitignore
+++ b/.gitignore
@@ -65,3 +65,17 @@ ALEAPP/admin/docs/generated/
 
 # Permission marker file
 .permissions_ok.env
+
+# Secrets — never commit real env files (.env held live API keys, see DECISIONS.md)
+.env
+.env.*
+!.env.example
+!env.example
+
+# Committed SQLite DBs are not schema truth (db_setup.py is) — keep them out
+*.db
+backend/ufdr_analyzer.db
+backend/ingest/database.db
+
+# Orchestration scratch
+orchestrator.log
diff --git a/backend/config.py b/backend/config.py
index 2732c7b..9334940 100644
--- a/backend/config.py
+++ b/backend/config.py
@@ -1,5 +1,27 @@
+"""Central configuration — all secrets sourced from the environment.
+
+No credential is hardcoded here. Secrets are loaded from `.env` (gitignored)
+or the process environment. A missing *required* secret fails loudly at import
+rather than silently falling back to a dev default (see project no-fallback rule).
+
+Non-secret connection params (host/port/db name) keep sensible local-dev
+defaults that match `docker-compose.dev.yml`.
+"""
+import os
 from pathlib import Path
 
+from dotenv import load_dotenv
+
+# Load .env from repo root (one level up from backend/) if present.
+_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
+load_dotenv(dotenv_path=_ENV_PATH)
+
+
+def _opt(name: str, default: str) -> str:
+    """Return env var `name` or a non-secret default (host/port/db only)."""
+    return os.getenv(name, default)
+
+
 # ------------------------
 # Storage paths
 # ------------------------
@@ -8,7 +30,6 @@ JSON_STORAGE = BASE_STORAGE / "json"
 REPORT_STORAGE = BASE_STORAGE / "reports"
 TMP_STORAGE = BASE_STORAGE / "tmp"
 
-# Ensure folders exist
 for folder in [JSON_STORAGE, REPORT_STORAGE, TMP_STORAGE]:
     folder.mkdir(parents=True, exist_ok=True)
 
@@ -17,38 +38,67 @@ for folder in [JSON_STORAGE, REPORT_STORAGE, TMP_STORAGE]:
 # ------------------------
 APP_NAME = "UFDR Analyzer"
 APP_VERSION = "0.1.0"
-HOST = "127.0.0.1"
-PORT = 8000
-DEBUG = True
+HOST = _opt("HOST", "127.0.0.1")
+PORT = int(_opt("PORT", "8000"))
+DEBUG = _opt("DEBUG", "false").lower() in ("1", "true", "yes")
+
+# CORS allowed origins (comma-separated). Demo/hosted sets this explicitly.
+CORS_ALLOWED_ORIGINS = [
+    o.strip()
+    for o in _opt("CORS_ALLOWED_ORIGINS", "http://localhost:3000").split(",")
+    if o.strip()
+]
+
+# Deployment profile flags
+DEMO_MODE = _opt("DEMO_MODE", "0").lower() in ("1", "true", "yes")
+GRAPH_BACKEND = _opt("GRAPH_BACKEND", "postgres").lower()  # "postgres" | "neo4j"
 
 # ------------------------
 # Database Configuration
 # ------------------------
+# The Postgres password is the one credential the app cannot run without.
+# It is required UNLESS a full DATABASE_URL is supplied directly (compose,
+# tests pointing at sqlite, hosted DB connection strings), in which case the
+# URL already carries its own auth and POSTGRES_URL below is unused.
+_DATABASE_URL = os.getenv("DATABASE_URL")
+_POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD")
+if not _DATABASE_URL and not _POSTGRES_PASSWORD:
+    raise RuntimeError(
+        "No database credentials found: set DATABASE_URL, or POSTGRES_PASSWORD "
+        f"(plus the POSTGRES_* params). Add them to {_ENV_PATH} or the "
+        "environment. See env.example."
+    )
+
 POSTGRES_CONFIG = {
-    "host": "localhost",
-    "port": 5432,
-    "user": "ufdr_user",
-    "password": "ufdr_password",
-    "database": "ufdr_analyzer"
+    "host": _opt("POSTGRES_HOST", "localhost"),
+    "port": int(_opt("POSTGRES_PORT", "5432")),
+    "user": _opt("POSTGRES_USER", "ufdr_user"),
+    "password": _POSTGRES_PASSWORD or "",
+    "database": _opt("POSTGRES_DB", "ufdr_analyzer"),
 }
 
-# PostgreSQL connection string
-POSTGRES_URL = f"postgresql://{POSTGRES_CONFIG['user']}:{POSTGRES_CONFIG['password']}@{POSTGRES_CONFIG['host']}:{POSTGRES_CONFIG['port']}/{POSTGRES_CONFIG['database']}"
+POSTGRES_URL = (
+    f"postgresql://{POSTGRES_CONFIG['user']}:{POSTGRES_CONFIG['password']}"
+    f"@{POSTGRES_CONFIG['host']}:{POSTGRES_CONFIG['port']}/{POSTGRES_CONFIG['database']}"
+)
 
+# Auxiliary services. Secrets are read from env and may be None when the
+# service is not configured; the respective client construction fails loudly
+# at the point of use (no silent fallback), keeping config decoupled.
 MEILI_CONFIG = {
-    "host": "http://127.0.0.1:7700",
-    "api_key": "masterKey"
+    "host": _opt("MEILI_URL", "http://127.0.0.1:7700"),
+    "api_key": os.getenv("MEILI_MASTER_KEY"),
 }
 
 NEO4J_CONFIG = {
-    "uri": "bolt://localhost:7687",
-    "user": "neo4j",
-    "password": "password"
+    "uri": _opt("NEO4J_URI", "bolt://localhost:7687"),
+    "user": _opt("NEO4J_USERNAME", "neo4j"),
+    "password": os.getenv("NEO4J_PASSWORD"),
 }
 
 MINIO_CONFIG = {
-    "endpoint": "http://127.0.0.1:9000",
-    "access_key": "minio_access",
-    "secret_key": "minio_secret",
-    "bucket": "ufdr-files"
+    "endpoint": _opt("MINIO_ENDPOINT", "127.0.0.1:9000"),
+    "access_key": os.getenv("MINIO_ACCESS_KEY"),
+    "secret_key": os.getenv("MINIO_SECRET_KEY"),
+    "bucket": _opt("MINIO_BUCKET", "ufdr-files"),
 }
diff --git a/backend/db_setup.py b/backend/db_setup.py
index 496723b..17a8982 100644
--- a/backend/db_setup.py
+++ b/backend/db_setup.py
@@ -107,8 +107,7 @@ class Backup(SQLModel, table=True):
     id: Optional[uuid.UUID] = Field(
         default_factory=uuid.uuid4, primary_key=True)
     user_id: uuid.UUID = Field(foreign_key="user.id")
-    event_type: str  # e.g., "database_snapshot", "user_login",
-    "security_event"
+    event_type: str  # e.g. "database_snapshot", "user_login", "security_event"
     timestamp: datetime.datetime = Field(default_factory=datetime.datetime.now)
     description: str
     snapshot_path: Optional[str] = None  # Path to the actual snapshot file
diff --git a/backend/ingest/database.db b/backend/ingest/database.db
deleted file mode 100644
index 0896b8c..0000000
Binary files a/backend/ingest/database.db and /dev/null differ
diff --git a/backend/ingest/services/ingest_service.py b/backend/ingest/services/ingest_service.py
index 4af966b..6e77877 100644
--- a/backend/ingest/services/ingest_service.py
+++ b/backend/ingest/services/ingest_service.py
@@ -81,7 +81,7 @@ class IngestService:
                 status="ingesting",
                 start_time=datetime.utcnow(),
                 user_id=user_id,
-                metadata=json.dumps(metadata) if metadata else None,
+                extraction_metadata=json.dumps(metadata) if metadata else None,
                 file_content_hash=file_content_hash,
                 original_file_path=original_file_path
             )
diff --git a/backend/main.py b/backend/main.py
index 9694f48..aa921f4 100644
--- a/backend/main.py
+++ b/backend/main.py
@@ -94,25 +94,20 @@ def get_meili_client():
 # ------------------------
 
 
+# Credentialed CORS requires an explicit origin allow-list — the wildcard
+# "*" + allow_credentials=True combo is rejected by the Fetch spec and was a
+# real bug here. Origins come from config (CORS_ALLOWED_ORIGINS env var).
+from config import CORS_ALLOWED_ORIGINS  # noqa: E402
+
 app.add_middleware(
     CORSMiddleware,
-    allow_origins=["*"],  # Allow all origins
+    allow_origins=CORS_ALLOWED_ORIGINS,
     allow_credentials=True,
-    allow_methods=["*"],  # Allow all HTTP methods
-    allow_headers=["*"],  # Allow all headers
-    expose_headers=["*"],  # Expose all headers
+    allow_methods=["*"],
+    allow_headers=["*"],
+    expose_headers=["*"],
 )
 
-# Additional CORS headers for maximum compatibility
-@app.middleware("http")
-async def add_cors_headers(request, call_next):
-    response = await call_next(request)
-    response.headers["Access-Control-Allow-Origin"] = "*"
-    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
-    response.headers["Access-Control-Allow-Headers"] = "*"
-    response.headers["Access-Control-Allow-Credentials"] = "true"
-    return response
-
 # ------------------------
 # Request Logging Middleware
 # ------------------------
diff --git a/backend/ufdr_analyzer.db b/backend/ufdr_analyzer.db
deleted file mode 100644
index 3e14589..0000000
Binary files a/backend/ufdr_analyzer.db and /dev/null differ
diff --git a/docker-compose.override.yml b/docker-compose.override.yml
index 248d5df..bb30662 100644
--- a/docker-compose.override.yml
+++ b/docker-compose.override.yml
@@ -10,7 +10,7 @@ services:
     environment:
       - DEBUG=true
       - LOG_LEVEL=debug
-    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
+    command: uvicorn main:app --host 0.0.0.0 --port 8000 --reload
 
   # Frontend development overrides
   frontend:
@@ -22,15 +22,10 @@ services:
       - NODE_ENV=development
     command: npm run dev
 
-  # Worker development overrides
-  worker:
-    volumes:
-      - ./backend:/app
-      - /app/__pycache__
-    environment:
-      - DEBUG=true
-      - LOG_LEVEL=debug
-    command: celery -A app.workers.celery_app worker --loglevel=debug --reload
+  # NOTE: the `worker` override was removed — there is no `app.workers.celery_app`
+  # module in this codebase. Ingestion runs inline in the API process (see the
+  # slim demo profile). If a Celery worker is reintroduced, restore an override
+  # here pointing at the real task module.
 
   # Add development tools
   pgadmin:
diff --git a/docker/services/Dockerfile.backend b/docker/services/Dockerfile.backend
index b681ae5..9c92e50 100644
--- a/docker/services/Dockerfile.backend
+++ b/docker/services/Dockerfile.backend
@@ -65,5 +65,5 @@ EXPOSE 8000
 HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
     CMD curl -f http://localhost:8000/health || exit 1
 
-# Run the application
-CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
+# Run the application (entrypoint is backend/main.py -> module `main`)
+CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
diff --git a/env.example b/env.example
index c0b4f04..4e8361d 100644
--- a/env.example
+++ b/env.example
@@ -1,51 +1,52 @@
-# UFDR Analyzer Environment Configuration
-# Copy this file to .env and update the values
+# UFDR Analyzer — environment template
+# Copy to `.env` (gitignored) and fill in real values. NO secrets are committed.
+# `backend/config.py` loads this file; missing DB credentials fail loudly.
 
-# Database Configuration
-POSTGRES_PASSWORD=your_secure_postgres_password
-NEO4J_PASSWORD=your_secure_neo4j_password
-
-# MinIO Object Storage Configuration
-MINIO_ROOT_USER=minioadmin
-MINIO_ROOT_PASSWORD=your_secure_minio_password
-
-# API Security Configuration
-SECRET_KEY=your_very_secure_secret_key_here
+# ----- Deployment profile -----
+DEBUG=false
+LOG_LEVEL=info
+# Comma-separated origins allowed for credentialed CORS. NEVER use "*" here.
+CORS_ALLOWED_ORIGINS=http://localhost:3000
+# DEMO_MODE=1 disables upload and enables the deterministic sample-case reset.
+DEMO_MODE=0
+# Graph backend for entity relationships: "postgres" (recursive CTE) or "neo4j".
+GRAPH_BACKEND=postgres
+
+# ----- PostgreSQL (required) -----
+# Either set DATABASE_URL directly, OR the POSTGRES_* parts below.
+# DATABASE_URL=postgresql://ufdr_user:CHANGE_ME@localhost:5432/ufdr_analyzer
+POSTGRES_HOST=localhost
+POSTGRES_PORT=5432
+POSTGRES_USER=ufdr_user
+POSTGRES_PASSWORD=CHANGE_ME
+POSTGRES_DB=ufdr_analyzer
+
+# ----- Meilisearch -----
+MEILI_URL=http://127.0.0.1:7700
+MEILI_MASTER_KEY=CHANGE_ME
+
+# ----- Neo4j (only when GRAPH_BACKEND=neo4j / full prod profile) -----
+NEO4J_URI=bolt://localhost:7687
+NEO4J_USERNAME=neo4j
+NEO4J_PASSWORD=CHANGE_ME
+
+# ----- MinIO object storage -----
+MINIO_ENDPOINT=127.0.0.1:9000
+MINIO_ACCESS_KEY=CHANGE_ME
+MINIO_SECRET_KEY=CHANGE_ME
+MINIO_BUCKET=ufdr-files
+
+# ----- LLM provider for NL -> QueryPlan IR -----
+# OpenRouter / OpenAI-compatible key. Leave blank in DEMO_MODE to use the
+# deterministic stub planner (logged loudly as a stub).
+OPENAI_API_KEY=
+OPENAI_BASE_URL=https://openrouter.ai/api/v1
+LLM_MODEL=anthropic/claude-3.5-sonnet
+
+# ----- API security -----
+SECRET_KEY=CHANGE_ME
 ALGORITHM=HS256
 ACCESS_TOKEN_EXPIRE_MINUTES=30
 
-# Monitoring Configuration
-GRAFANA_PASSWORD=your_secure_grafana_password
-
-# External Services (Optional)
-# OPENAI_API_KEY=your_openai_api_key
-# HUGGINGFACE_API_KEY=your_huggingface_api_key
-
-# Email Configuration (Optional)
-# SMTP_HOST=smtp.gmail.com
-# SMTP_PORT=587
-# SMTP_USERNAME=your_email@gmail.com
-# SMTP_PASSWORD=your_app_password
-
-# Logging Configuration
-LOG_LEVEL=info
-DEBUG=false
-
-# File Upload Configuration
-MAX_UPLOAD_SIZE=10737418240  # 10GB in bytes
-ALLOWED_EXTENSIONS=.xml,.json,.csv,.zip,.tar,.7z
-
-# Redis Configuration
-REDIS_URL=redis://redis:6379
-
-# Neo4j Configuration
-NEO4J_URL=bolt://neo4j:7687
-NEO4J_USER=neo4j
-
-# MinIO Configuration
-MINIO_ENDPOINT=minio:9000
-MINIO_ACCESS_KEY=minioadmin
-MINIO_SECRET_KEY=your_secure_minio_password
-
-# Frontend Configuration
-NEXT_PUBLIC_API_URL=http://localhost/api
+# ----- Frontend -----
+NEXT_PUBLIC_API_URL=http://localhost:8000
</stdin>
hook: SessionStart
hook: SessionStart Failed
codex
Using `superpowers:using-superpowers` for the session-level skill rule, then I’ll inspect the touched files so the review is grounded in the actual code instead of just the patch text.
exec
"C:\\Users\\Aayushman\\AppData\\Local\\Microsoft\\WindowsApps\\pwsh.exe" -Command 'Get-Content -Raw C:/Users/Aayushman/.codex/plugins/cache/claude-plugins-official/superpowers/5.1.0/skills/using-superpowers/SKILL.md' in C:\Repo\ufdr-analyzer
2026-06-08T14:27:58.868375Z ERROR codex_core::exec: exec error: windows sandbox: spawn setup refresh
 exited -1 in 0ms:
execution error: Io(Custom { kind: Other, error: "windows sandbox: spawn setup refresh" })
2026-06-08T14:27:58.870987Z ERROR codex_core::tools::router: error=execution error: Io(Custom { kind: Other, error: "windows sandbox: spawn setup refresh" })
codex
The local shell is failing before PowerShell starts (`windows sandbox: spawn setup refresh`), so I can’t read the skill file or repository files in this turn. I’ll keep this review scoped to the provided diff and call out where that limits certainty.
codex
**Findings**

- **Critical: `DATABASE_URL` is accepted but never used.** [backend/config.py](<C:/Repo/ufdr-analyzer/backend/config.py:45>) lets startup pass when `DATABASE_URL` exists, then [backend/config.py](<C:/Repo/ufdr-analyzer/backend/config.py:55>) builds `POSTGRES_URL` from `POSTGRES_*` with an empty password. Hosted DB URLs and sqlite test URLs will silently route to the wrong config until connection fails.

- **Critical: this does not remediate leaked secrets.** [.gitignore](<C:/Repo/ufdr-analyzer/.gitignore:68>) says `.env` held live API keys. Ignoring `.env` now does not remove it from Git history and does not rotate anything. Treat this as an incident: rotate keys, purge history with `git filter-repo`/BFG, audit DB dumps, then document the rotation.

- **High: placeholder secrets pass validation.** [env.example](<C:/Repo/ufdr-analyzer/env.example:18>) uses `CHANGE_ME`, while [backend/config.py](<C:/Repo/ufdr-analyzer/backend/config.py:47>) only checks presence. A copied env file can boot with known credentials or a known JWT `SECRET_KEY`. Reject blank, `CHANGE_ME`, `your_*`, and other sentinel values at startup.

- **High: CORS is still one env var away from being broken/insecure.** [backend/main.py](<C:/Repo/ufdr-analyzer/backend/main.py:100>) uses credentialed CORS, but [backend/config.py](<C:/Repo/ufdr-analyzer/backend/config.py:41>) does not reject `*`, invalid schemes, trailing slashes, or empty lists. Comments are not controls. Also `expose_headers=["*"]` is sloppy and not reliable with credentials. Validate exact origins and expose only needed headers.

- **High: removing a service override does not remove the service.** [docker-compose.override.yml](<C:/Repo/ufdr-analyzer/docker-compose.override.yml:25>) says the worker override was removed, but if the base compose file still defines `worker`, Compose will still start it with the base command. This comment may be dead code masking a still-broken Celery service. Disable/remove it in the base file or put it behind a profile.

- **High: selected services are not validated by selected behavior.** [backend/config.py](<C:/Repo/ufdr-analyzer/backend/config.py:44>) allows `GRAPH_BACKEND=neo4j`, but [backend/config.py](<C:/Repo/ufdr-analyzer/backend/config.py:73>) allows `NEO4J_PASSWORD=None`. Same pattern exists for Meili and MinIO. “Fail at point of use” is late failure, not all-or-nothing startup validation.

- **Medium: `POSTGRES_URL` construction is unsafe.** [backend/config.py](<C:/Repo/ufdr-analyzer/backend/config.py:58>) interpolates credentials into a URL without encoding. Any serious generated password containing `@`, `:`, `/`, `#`, or `%` can corrupt parsing. Use structured connection params or SQLAlchemy URL construction.

- **Medium: new dependency is not shown.** [backend/config.py](<C:/Repo/ufdr-analyzer/backend/config.py:13>) imports `python-dotenv`; the diff does not add it to requirements/lock files. If it is not already present, every backend import dies before the app starts.

- **Medium: config is doing too much at import time.** [backend/config.py](<C:/Repo/ufdr-analyzer/backend/config.py:16>) mutates environment loading, [backend/config.py](<C:/Repo/ufdr-analyzer/backend/config.py:33>) creates directories, and [backend/config.py](<C:/Repo/ufdr-analyzer/backend/config.py:47>) validates DB credentials. That makes a “settings” import perform runtime setup. Split parse/validate from filesystem setup.

- **Medium: env var contract changed without proving callers changed.** [env.example](<C:/Repo/ufdr-analyzer/env.example:31>) uses `NEO4J_URI`/`NEO4J_USERNAME`; old template used `NEO4J_URL`/`NEO4J_USER`. If compose, docs, CI, or deployment still use old names, config silently falls back to localhost/default user and `None` password.

- **Medium: ingest field rename needs schema/test proof.** [backend/ingest/services/ingest_service.py](<C:/Repo/ufdr-analyzer/backend/ingest/services/ingest_service.py:84>) changes `metadata` to `extraction_metadata`. If the model/schema was not migrated consistently, this becomes either an unexpected constructor arg or a missing persisted column. Needs an ingest job creation test covering metadata persistence.

- **Low: global `*.db` ignore is too broad.** [.gitignore](<C:/Repo/ufdr-analyzer/.gitignore:75>) can hide intentional SQLite fixtures or sample forensic datasets. Ignore the known generated DB paths unless the repo policy explicitly bans every DB artifact.

I could not inspect the repository because the local shell failed before PowerShell started, so this review is limited to the supplied diff. The biggest blockers are the unused `DATABASE_URL`, unresolved secret-history incident, placeholder-secret validation, and the Compose worker misconception.
tokens used
40,812
**Findings**

- **Critical: `DATABASE_URL` is accepted but never used.** [backend/config.py](<C:/Repo/ufdr-analyzer/backend/config.py:45>) lets startup pass when `DATABASE_URL` exists, then [backend/config.py](<C:/Repo/ufdr-analyzer/backend/config.py:55>) builds `POSTGRES_URL` from `POSTGRES_*` with an empty password. Hosted DB URLs and sqlite test URLs will silently route to the wrong config until connection fails.

- **Critical: this does not remediate leaked secrets.** [.gitignore](<C:/Repo/ufdr-analyzer/.gitignore:68>) says `.env` held live API keys. Ignoring `.env` now does not remove it from Git history and does not rotate anything. Treat this as an incident: rotate keys, purge history with `git filter-repo`/BFG, audit DB dumps, then document the rotation.

- **High: placeholder secrets pass validation.** [env.example](<C:/Repo/ufdr-analyzer/env.example:18>) uses `CHANGE_ME`, while [backend/config.py](<C:/Repo/ufdr-analyzer/backend/config.py:47>) only checks presence. A copied env file can boot with known credentials or a known JWT `SECRET_KEY`. Reject blank, `CHANGE_ME`, `your_*`, and other sentinel values at startup.

- **High: CORS is still one env var away from being broken/insecure.** [backend/main.py](<C:/Repo/ufdr-analyzer/backend/main.py:100>) uses credentialed CORS, but [backend/config.py](<C:/Repo/ufdr-analyzer/backend/config.py:41>) does not reject `*`, invalid schemes, trailing slashes, or empty lists. Comments are not controls. Also `expose_headers=["*"]` is sloppy and not reliable with credentials. Validate exact origins and expose only needed headers.

- **High: removing a service override does not remove the service.** [docker-compose.override.yml](<C:/Repo/ufdr-analyzer/docker-compose.override.yml:25>) says the worker override was removed, but if the base compose file still defines `worker`, Compose will still start it with the base command. This comment may be dead code masking a still-broken Celery service. Disable/remove it in the base file or put it behind a profile.

- **High: selected services are not validated by selected behavior.** [backend/config.py](<C:/Repo/ufdr-analyzer/backend/config.py:44>) allows `GRAPH_BACKEND=neo4j`, but [backend/config.py](<C:/Repo/ufdr-analyzer/backend/config.py:73>) allows `NEO4J_PASSWORD=None`. Same pattern exists for Meili and MinIO. “Fail at point of use” is late failure, not all-or-nothing startup validation.

- **Medium: `POSTGRES_URL` construction is unsafe.** [backend/config.py](<C:/Repo/ufdr-analyzer/backend/config.py:58>) interpolates credentials into a URL without encoding. Any serious generated password containing `@`, `:`, `/`, `#`, or `%` can corrupt parsing. Use structured connection params or SQLAlchemy URL construction.

- **Medium: new dependency is not shown.** [backend/config.py](<C:/Repo/ufdr-analyzer/backend/config.py:13>) imports `python-dotenv`; the diff does not add it to requirements/lock files. If it is not already present, every backend import dies before the app starts.

- **Medium: config is doing too much at import time.** [backend/config.py](<C:/Repo/ufdr-analyzer/backend/config.py:16>) mutates environment loading, [backend/config.py](<C:/Repo/ufdr-analyzer/backend/config.py:33>) creates directories, and [backend/config.py](<C:/Repo/ufdr-analyzer/backend/config.py:47>) validates DB credentials. That makes a “settings” import perform runtime setup. Split parse/validate from filesystem setup.

- **Medium: env var contract changed without proving callers changed.** [env.example](<C:/Repo/ufdr-analyzer/env.example:31>) uses `NEO4J_URI`/`NEO4J_USERNAME`; old template used `NEO4J_URL`/`NEO4J_USER`. If compose, docs, CI, or deployment still use old names, config silently falls back to localhost/default user and `None` password.

- **Medium: ingest field rename needs schema/test proof.** [backend/ingest/services/ingest_service.py](<C:/Repo/ufdr-analyzer/backend/ingest/services/ingest_service.py:84>) changes `metadata` to `extraction_metadata`. If the model/schema was not migrated consistently, this becomes either an unexpected constructor arg or a missing persisted column. Needs an ingest job creation test covering metadata persistence.

- **Low: global `*.db` ignore is too broad.** [.gitignore](<C:/Repo/ufdr-analyzer/.gitignore:75>) can hide intentional SQLite fixtures or sample forensic datasets. Ignore the known generated DB paths unless the repo policy explicitly bans every DB artifact.

I could not inspect the repository because the local shell failed before PowerShell started, so this review is limited to the supplied diff. The biggest blockers are the unused `DATABASE_URL`, unresolved secret-history incident, placeholder-secret validation, and the Compose worker misconception.
