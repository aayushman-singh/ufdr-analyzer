from pathlib import Path

# ------------------------
# Storage paths
# ------------------------
BASE_STORAGE = Path("storage")
JSON_STORAGE = BASE_STORAGE / "json"
REPORT_STORAGE = BASE_STORAGE / "reports"
TMP_STORAGE = BASE_STORAGE / "tmp"

# Ensure folders exist
for folder in [JSON_STORAGE, REPORT_STORAGE, TMP_STORAGE]:
    folder.mkdir(parents=True, exist_ok=True)

# ------------------------
# API / App Settings
# ------------------------
APP_NAME = "UFDR Analyzer"
APP_VERSION = "0.1.0"
HOST = "127.0.0.1"
PORT = 8000
DEBUG = True

# ------------------------
# Database placeholders (to be updated after schema is ready)
# ------------------------
POSTGRES_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "user": "username",
    "password": "password",
    "database": "ufdr_db"
}

MEILI_CONFIG = {
    "host": "http://127.0.0.1:7700",
    "api_key": "masterKey"
}

NEO4J_CONFIG = {
    "uri": "bolt://localhost:7687",
    "user": "neo4j",
    "password": "password"
}

MINIO_CONFIG = {
    "endpoint": "http://127.0.0.1:9000",
    "access_key": "minio_access",
    "secret_key": "minio_secret",
    "bucket": "ufdr-files"
}
