"""Central configuration — all secrets sourced from the environment.

No credential is hardcoded here. Secrets are loaded from `.env` (gitignored)
or the process environment. A missing *required* secret fails loudly at import
rather than silently falling back to a dev default (see project no-fallback rule).

Non-secret connection params (host/port/db name) keep sensible local-dev
defaults that match `docker-compose.dev.yml`.
"""
import os
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv

# Load .env from repo root (one level up from backend/) if present.
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_ENV_PATH)

# Sentinel values that mean "you forgot to fill this in" — never accepted.
_PLACEHOLDERS = {"change_me", "changeme", "your_secure_postgres_password",
                 "your_very_secure_secret_key_here", "password", "masterkey"}


def _opt(name: str, default: str) -> str:
    """Return env var `name` or a non-secret default (host/port/db only)."""
    return os.getenv(name, default)


def _reject_placeholder(name: str, value: str) -> str:
    """Fail loudly if a real secret was left at its template sentinel."""
    if value.strip().lower() in _PLACEHOLDERS:
        raise RuntimeError(
            f"Environment variable '{name}' is still set to a template "
            f"placeholder ('{value}'). Set a real value in {_ENV_PATH}."
        )
    return value


# ------------------------
# Storage paths
# ------------------------
BASE_STORAGE = Path("storage")
JSON_STORAGE = BASE_STORAGE / "json"
REPORT_STORAGE = BASE_STORAGE / "reports"
TMP_STORAGE = BASE_STORAGE / "tmp"

for folder in [JSON_STORAGE, REPORT_STORAGE, TMP_STORAGE]:
    folder.mkdir(parents=True, exist_ok=True)

# ------------------------
# API / App Settings
# ------------------------
APP_NAME = "UFDR Analyzer"
APP_VERSION = "0.1.0"
HOST = _opt("HOST", "127.0.0.1")
PORT = int(_opt("PORT", "8000"))
DEBUG = _opt("DEBUG", "false").lower() in ("1", "true", "yes")

# CORS allowed origins (comma-separated). Demo/hosted sets this explicitly.
# Credentialed CORS forbids the "*" wildcard — reject it loudly rather than
# ship a config the browser will silently refuse.
CORS_ALLOWED_ORIGINS = [
    o.strip()
    for o in _opt("CORS_ALLOWED_ORIGINS", "http://localhost:3000").split(",")
    if o.strip()
]
if not CORS_ALLOWED_ORIGINS:
    raise RuntimeError("CORS_ALLOWED_ORIGINS is empty — set at least one origin.")
if "*" in CORS_ALLOWED_ORIGINS:
    raise RuntimeError(
        "CORS_ALLOWED_ORIGINS contains '*', which is invalid with credentialed "
        "CORS. List explicit origins (e.g. http://localhost:3000)."
    )

# Deployment profile flags
DEMO_MODE = _opt("DEMO_MODE", "0").lower() in ("1", "true", "yes")
GRAPH_BACKEND = _opt("GRAPH_BACKEND", "postgres").lower()  # "postgres" | "neo4j"
if GRAPH_BACKEND not in ("postgres", "neo4j"):
    raise RuntimeError(
        f"GRAPH_BACKEND must be 'postgres' or 'neo4j', got {GRAPH_BACKEND!r}."
    )

# ------------------------
# Database Configuration
# ------------------------
# The Postgres password is the one credential the app cannot run without.
# It is required UNLESS a full DATABASE_URL is supplied directly (compose,
# tests pointing at sqlite, hosted DB connection strings), in which case the
# URL already carries its own auth and POSTGRES_URL below is unused.
# A full DATABASE_URL (compose, hosted DB, sqlite tests) wins outright and
# already carries its own auth. Otherwise POSTGRES_* parts are required and the
# password must be a real (non-placeholder) value.
_DATABASE_URL = os.getenv("DATABASE_URL")
_POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD")
if not _DATABASE_URL and not _POSTGRES_PASSWORD:
    raise RuntimeError(
        "No database credentials found: set DATABASE_URL, or POSTGRES_PASSWORD "
        f"(plus the POSTGRES_* params). Add them to {_ENV_PATH} or the "
        "environment. See env.example."
    )
if _POSTGRES_PASSWORD:
    _reject_placeholder("POSTGRES_PASSWORD", _POSTGRES_PASSWORD)

POSTGRES_CONFIG = {
    "host": _opt("POSTGRES_HOST", "localhost"),
    "port": int(_opt("POSTGRES_PORT", "5432")),
    "user": _opt("POSTGRES_USER", "ufdr_user"),
    "password": _POSTGRES_PASSWORD or "",
    "database": _opt("POSTGRES_DB", "ufdr_analyzer"),
}

# When DATABASE_URL is given it is authoritative; otherwise build a URL with
# percent-encoded credentials so passwords containing @ : / # % parse correctly.
if _DATABASE_URL:
    POSTGRES_URL = _DATABASE_URL
else:
    POSTGRES_URL = (
        f"postgresql://{quote_plus(POSTGRES_CONFIG['user'])}:"
        f"{quote_plus(POSTGRES_CONFIG['password'])}"
        f"@{POSTGRES_CONFIG['host']}:{POSTGRES_CONFIG['port']}/{POSTGRES_CONFIG['database']}"
    )

# Auxiliary services. Secrets are read from env and may be None when the
# service is not configured; the respective client construction fails loudly
# at the point of use (no silent fallback), keeping config decoupled.
MEILI_CONFIG = {
    "host": _opt("MEILI_URL", "http://127.0.0.1:7700"),
    "api_key": os.getenv("MEILI_MASTER_KEY"),
}

NEO4J_CONFIG = {
    "uri": _opt("NEO4J_URI", "bolt://localhost:7687"),
    "user": _opt("NEO4J_USERNAME", "neo4j"),
    "password": os.getenv("NEO4J_PASSWORD"),
}

# If the graph backend is explicitly Neo4j, its password is no longer optional.
if GRAPH_BACKEND == "neo4j" and not NEO4J_CONFIG["password"]:
    raise RuntimeError(
        "GRAPH_BACKEND=neo4j but NEO4J_PASSWORD is not set. Set it, or use "
        "GRAPH_BACKEND=postgres."
    )

MINIO_CONFIG = {
    "endpoint": _opt("MINIO_ENDPOINT", "127.0.0.1:9000"),
    "access_key": os.getenv("MINIO_ACCESS_KEY"),
    "secret_key": os.getenv("MINIO_SECRET_KEY"),
    "bucket": _opt("MINIO_BUCKET", "ufdr-files"),
}
