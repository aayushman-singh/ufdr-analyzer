#!/usr/bin/env python3
"""
CLI script to sync PostgreSQL data to Neo4j
"""

import sys
import os
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).parent / "backend"
sys.path.insert(0, str(backend_path))

from ingest.services.postgres_to_neo4j_sync import PostgresToNeo4jSync

def main():
    print("🔄 PostgreSQL to Neo4j Data Synchronization")
    print("=" * 50)
    
    try:
        # Create sync service
        sync_service = PostgresToNeo4jSync()
        
        # Ask user for options
        clear_existing = input("Clear existing Neo4j data? (y/N): ").lower().strip() == 'y'
        
        if clear_existing:
            print("⚠️  This will delete ALL existing data in Neo4j!")
            confirm = input("Are you sure? (yes/no): ").lower().strip()
            if confirm != 'yes':
                print("❌ Sync cancelled")
                return
        
        # Start synchronization
        sync_service.sync_all_data(clear_existing=clear_existing)
        
        # Show statistics
        print("\n📊 Synchronization Statistics:")
        stats = sync_service.get_sync_stats()
        for node_type, count in stats.items():
            print(f"  {node_type}: {count}")
        
        print("\n✅ Data synchronization completed successfully!")
        
    except Exception as e:
        print(f"❌ Synchronization failed: {e}")
        sys.exit(1)
    
    finally:
        # Close connections
        if 'sync_service' in locals():
            sync_service.close()

if __name__ == "__main__":
    main()
