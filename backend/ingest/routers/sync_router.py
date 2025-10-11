"""
Data Synchronization Router
Handles syncing data between PostgreSQL and Neo4j
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Dict, Any, Optional
from ingest.services.postgres_to_neo4j_sync import PostgresToNeo4jSync
import asyncio

router = APIRouter(prefix="/sync", tags=["DataSync"])

class SyncRequest(BaseModel):
    clear_existing: bool = False
    sync_type: str = "all"  # "all", "users", "messages", "calls", etc.

class SyncStatus(BaseModel):
    status: str
    message: str
    stats: Optional[Dict[str, int]] = None

# Global sync service instance
sync_service = None

def get_sync_service():
    """Get or create sync service instance"""
    global sync_service
    if sync_service is None:
        sync_service = PostgresToNeo4jSync()
    return sync_service

@router.post("/postgres-to-neo4j", response_model=SyncStatus)
async def sync_postgres_to_neo4j(request: SyncRequest):
    """
    Sync data from PostgreSQL to Neo4j
    """
    try:
        service = get_sync_service()
        
        if request.sync_type == "all":
            service.sync_all_data(clear_existing=request.clear_existing)
        else:
            # For specific sync types, we could implement individual sync methods
            raise HTTPException(status_code=400, detail=f"Sync type '{request.sync_type}' not implemented yet")
        
        # Get sync statistics
        stats = service.get_sync_stats()
        
        return SyncStatus(
            status="success",
            message="Data synchronization completed successfully",
            stats=stats
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sync failed: {str(e)}")

@router.post("/postgres-to-neo4j/background", response_model=SyncStatus)
async def sync_postgres_to_neo4j_background(request: SyncRequest, background_tasks: BackgroundTasks):
    """
    Start background sync from PostgreSQL to Neo4j
    """
    try:
        service = get_sync_service()
        
        # Add background task
        background_tasks.add_task(
            background_sync_task,
            service,
            request.clear_existing
        )
        
        return SyncStatus(
            status="started",
            message="Background synchronization started"
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start background sync: {str(e)}")

async def background_sync_task(service: PostgresToNeo4jSync, clear_existing: bool):
    """Background task for data synchronization"""
    try:
        service.sync_all_data(clear_existing=clear_existing)
        print("✅ Background sync completed successfully")
    except Exception as e:
        print(f"❌ Background sync failed: {e}")

@router.get("/stats", response_model=SyncStatus)
async def get_sync_stats():
    """
    Get synchronization statistics
    """
    try:
        service = get_sync_service()
        stats = service.get_sync_stats()
        
        return SyncStatus(
            status="success",
            message="Statistics retrieved successfully",
            stats=stats
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")

@router.delete("/clear-neo4j", response_model=SyncStatus)
async def clear_neo4j_data():
    """
    Clear all data from Neo4j
    """
    try:
        service = get_sync_service()
        service.clear_neo4j_data()
        
        return SyncStatus(
            status="success",
            message="Neo4j data cleared successfully"
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to clear Neo4j data: {str(e)}")

@router.get("/health")
async def sync_health():
    """
    Check sync service health
    """
    try:
        service = get_sync_service()
        
        # Test Neo4j connection
        with service.neo4j_driver.session() as session:
            result = session.run("RETURN 1 as test")
            test_value = result.single()["test"]
        
        return {
            "status": "healthy",
            "message": "Sync service is operational",
            "neo4j_connected": True,
            "test_value": test_value
        }
    
    except Exception as e:
        return {
            "status": "unhealthy",
            "message": f"Sync service error: {str(e)}",
            "neo4j_connected": False
        }
