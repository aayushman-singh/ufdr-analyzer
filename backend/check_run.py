#!/usr/bin/env python3
"""Check if a run exists in the database"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from sqlmodel import Session, select
from database import engine
from db_setup import Run
import uuid

if len(sys.argv) < 2:
    print("Usage: python check_run.py <run_id>")
    sys.exit(1)

run_id_str = sys.argv[1]

try:
    run_uuid = uuid.UUID(run_id_str)
except ValueError:
    print(f"Invalid UUID: {run_id_str}")
    sys.exit(1)

with Session(engine) as session:
    run = session.get(Run, run_uuid)
    if run:
        print(f"✗ Run STILL EXISTS in database:")
        print(f"  ID: {run.id}")
        print(f"  File: {run.ufdr_file_name}")
        print(f"  Status: {run.status}")
        print(f"  Hash: {run.file_content_hash}")
    else:
        print(f"✓ Run NOT FOUND in database (successfully deleted)")

