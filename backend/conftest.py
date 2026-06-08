"""Root test configuration for the backend test suite.

Ensures `backend/` is importable (so `db_setup`, `ai`, `ingest`, `config`,
`main` resolve as top-level modules) and gives `config` a DB URL up front so
importing it never fails on a missing secret.
"""
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

os.environ.setdefault("DATABASE_URL", "sqlite://")
