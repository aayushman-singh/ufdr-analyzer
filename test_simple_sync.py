#!/usr/bin/env python3
"""
Simple test for PostgreSQL to Neo4j sync
"""

import sys
import os
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).parent / "backend"
sys.path.insert(0, str(backend_path))

from ingest.services.postgres_to_neo4j_sync import PostgresToNeo4jSync
from database import get_session
from db_setup import User, Run, Message, Call, Contact
from sqlmodel import select

def test_simple_sync():
    print("🔄 Simple PostgreSQL to Neo4j Sync Test")
    print("=" * 50)
    
    try:
        # Create sync service
        sync_service = PostgresToNeo4jSync()
        
        # Get database session
        with next(get_session()) as db_session:
            # Check what data we have
            print("\n📊 Checking PostgreSQL data...")
            
            users = db_session.exec(select(User)).all()
            runs = db_session.exec(select(Run)).all()
            messages = db_session.exec(select(Message)).all()
            calls = db_session.exec(select(Call)).all()
            contacts = db_session.exec(select(Contact)).all()
            
            print(f"  Users: {len(users)}")
            print(f"  Runs: {len(runs)}")
            print(f"  Messages: {len(messages)}")
            print(f"  Calls: {len(calls)}")
            print(f"  Contacts: {len(contacts)}")
            
            if len(users) == 0:
                print("❌ No users found in PostgreSQL. Please add some data first.")
                return False
            
            # Test syncing just users first
            print("\n📤 Testing user sync...")
            sync_service.sync_users(db_session)
            
            # Test syncing runs
            if len(runs) > 0:
                print("\n📤 Testing run sync...")
                sync_service.sync_runs(db_session)
            
            # Get stats
            print("\n📊 Neo4j statistics after sync:")
            stats = sync_service.get_sync_stats()
            for node_type, count in stats.items():
                print(f"  {node_type}: {count}")
            
            print("\n✅ Simple sync test completed!")
            return True
            
    except Exception as e:
        print(f"❌ Sync test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    finally:
        # Close connections
        if 'sync_service' in locals():
            sync_service.close()

if __name__ == "__main__":
    success = test_simple_sync()
    sys.exit(0 if success else 1)
