#!/usr/bin/env python3
"""
Test PostgreSQL to Neo4j data synchronization
"""

import requests
import json
import sys

def test_sync_endpoints():
    """Test the sync API endpoints"""
    base_url = "http://localhost:8000"
    
    print("🔄 Testing PostgreSQL to Neo4j Data Sync")
    print("=" * 50)
    
    # Test sync health
    print("\n1. Testing sync service health...")
    try:
        response = requests.get(f"{base_url}/sync/health", timeout=10)
        if response.status_code == 200:
            health_data = response.json()
            print(f"✅ Sync service health: {health_data['status']}")
            print(f"   Neo4j connected: {health_data.get('neo4j_connected', False)}")
        else:
            print(f"❌ Sync health check failed: {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"❌ Sync health check failed: {e}")
        return False
    
    # Test getting current stats
    print("\n2. Getting current Neo4j statistics...")
    try:
        response = requests.get(f"{base_url}/sync/stats", timeout=10)
        if response.status_code == 200:
            stats_data = response.json()
            print("✅ Current Neo4j statistics:")
            if stats_data.get('stats'):
                for node_type, count in stats_data['stats'].items():
                    print(f"   {node_type}: {count}")
            else:
                print("   No data in Neo4j yet")
        else:
            print(f"❌ Failed to get stats: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"❌ Failed to get stats: {e}")
    
    # Test data synchronization
    print("\n3. Testing data synchronization...")
    sync_data = {
        "clear_existing": False,
        "sync_type": "all"
    }
    
    try:
        print("   Starting sync (this may take a while)...")
        response = requests.post(f"{base_url}/sync/postgres-to-neo4j", json=sync_data, timeout=60)
        if response.status_code == 200:
            sync_result = response.json()
            print(f"✅ Sync completed: {sync_result['message']}")
            
            if sync_result.get('stats'):
                print("   New statistics:")
                for node_type, count in sync_result['stats'].items():
                    print(f"     {node_type}: {count}")
        else:
            print(f"❌ Sync failed: {response.status_code}")
            print(f"   Error: {response.text}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"❌ Sync request failed: {e}")
        return False
    
    # Test graph endpoints with synced data
    print("\n4. Testing graph endpoints with synced data...")
    try:
        response = requests.get(f"{base_url}/graph/full_graph", timeout=10)
        if response.status_code == 200:
            graph_data = response.json()
            node_count = len(graph_data.get('nodes', []))
            edge_count = len(graph_data.get('edges', []))
            print(f"✅ Graph data available: {node_count} nodes, {edge_count} edges")
        else:
            print(f"❌ Graph endpoint failed: {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"❌ Graph endpoint failed: {e}")
        return False
    
    print("\n🎉 All sync tests passed!")
    print("\nNext steps:")
    print("1. Visit http://localhost:3000/graph-test to see the data")
    print("2. Or go to Dashboard → Graph Analysis for full visualization")
    
    return True

if __name__ == "__main__":
    success = test_sync_endpoints()
    sys.exit(0 if success else 1)
