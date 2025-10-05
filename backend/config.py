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
# Database Configuration
# ------------------------
POSTGRES_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "user": "ufdr_user",
    "password": "ufdr_password",
    "database": "ufdr_analyzer"
}

# PostgreSQL connection string
POSTGRES_URL = f"postgresql://{POSTGRES_CONFIG['user']}:{POSTGRES_CONFIG['password']}@{POSTGRES_CONFIG['host']}:{POSTGRES_CONFIG['port']}/{POSTGRES_CONFIG['database']}"

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
