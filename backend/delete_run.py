#!/usr/bin/env python3
"""
Quick utility to delete a run from the database by run_id
"""
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from sqlmodel import Session, select, delete
from database import engine
from db_setup import Run, Message, Call, Contact, Media, AleappArtifact, AleappReport
import uuid

def delete_run(run_id_str: str):
    """Delete a run and all related data from the database"""
    try:
        run_uuid = uuid.UUID(run_id_str)
    except ValueError:
        print(f"Error: Invalid UUID format: {run_id_str}")
        return False
    
    with Session(engine) as session:
        # Check if run exists
        run = session.get(Run, run_uuid)
        if not run:
            print(f"Run not found: {run_id_str}")
            return False
        
        print(f"Found run: {run.id}")
        print(f"  File: {run.ufdr_file_name}")
        print(f"  Status: {run.status}")
        print(f"  Started: {run.start_time}")
        print()
        
        # Delete related data
        print("Deleting related data...")
        
        # Delete messages
        stmt = delete(Message).where(Message.run_id == run_uuid)
        result = session.exec(stmt)
        print(f"  Deleted {result.rowcount} messages")
        
        # Delete calls
        stmt = delete(Call).where(Call.run_id == run_uuid)
        result = session.exec(stmt)
        print(f"  Deleted {result.rowcount} calls")
        
        # Delete contacts
        stmt = delete(Contact).where(Contact.run_id == run_uuid)
        result = session.exec(stmt)
        print(f"  Deleted {result.rowcount} contacts")
        
        # Delete media
        stmt = delete(Media).where(Media.run_id == run_uuid)
        result = session.exec(stmt)
        print(f"  Deleted {result.rowcount} media")
        
        # Delete ALEAPP artifacts
        stmt = delete(AleappArtifact).where(AleappArtifact.run_id == run_uuid)
        result = session.exec(stmt)
        print(f"  Deleted {result.rowcount} ALEAPP artifacts")
        
        # Delete ALEAPP reports
        stmt = delete(AleappReport).where(AleappReport.run_id == run_uuid)
        result = session.exec(stmt)
        print(f"  Deleted {result.rowcount} ALEAPP reports")
        
        # Delete queries (need to import Query first)
        from db_setup import Query
        stmt = delete(Query).where(Query.run_id == run_uuid)
        result = session.exec(stmt)
        print(f"  Deleted {result.rowcount} queries")
        
        # Finally delete the run itself
        session.delete(run)
        session.commit()
        
        print()
        print(f"✓ Successfully deleted run: {run_id_str}")
        return True

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python delete_run.py <run_id>")
        print()
        print("Example:")
        print("  python delete_run.py 77d26da0-03e2-400b-b089-0a9f45603b2d")
        sys.exit(1)
    
    run_id = sys.argv[1]
    success = delete_run(run_id)
    sys.exit(0 if success else 1)

