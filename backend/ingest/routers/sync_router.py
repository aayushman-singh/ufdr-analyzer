"""
Data Synchronization Router
Handles syncing data between PostgreSQL and Neo4j
"""

import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from db_setup import User
from ingest.services.auth_service import require_admin

if TYPE_CHECKING:
    from ingest.services.postgres_to_neo4j_sync import PostgresToNeo4jSync

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sync", tags=["DataSync"])


class SyncRequest(BaseModel):
    clear_existing: bool = False
    sync_type: str = "all"  # "all", "users", "messages", "calls", etc.


class SyncStatus(BaseModel):
    status: str
    message: str
    stats: Optional[Dict[str, int]] = None


# Global sync service instance
sync_service: "PostgresToNeo4jSync | None" = None


def get_sync_service():
    """Get or create sync service instance"""
    global sync_service
    if sync_service is None:
        from ingest.services.postgres_to_neo4j_sync import PostgresToNeo4jSync

        sync_service = PostgresToNeo4jSync()
    return sync_service


def _sync_failure(action: str, exc: Exception, **context: Any) -> HTTPException:
    logger.exception("Neo4j sync action failed", extra={"action": action, **context})
    return HTTPException(status_code=500, detail=f"{action} failed: {exc}")


@router.post("/postgres-to-neo4j", response_model=SyncStatus)
async def sync_postgres_to_neo4j(
    request: SyncRequest, admin: User = Depends(require_admin)
):
    """
    Sync data from PostgreSQL to Neo4j
    """
    try:
        service = get_sync_service()

        if request.sync_type == "all":
            service.sync_all_data(clear_existing=request.clear_existing)
        else:
            # For specific sync types, we could implement individual sync methods
            raise HTTPException(
                status_code=400,
                detail=f"Sync type '{request.sync_type}' not implemented yet",
            )

        # Get sync statistics
        stats = service.get_sync_stats()

        return SyncStatus(
            status="success",
            message="Data synchronization completed successfully",
            stats=stats,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise _sync_failure(
            "sync",
            e,
            clear_existing=request.clear_existing,
            sync_type=request.sync_type,
            admin_id=str(admin.id),
        ) from e


@router.post("/postgres-to-neo4j/background", response_model=SyncStatus)
async def sync_postgres_to_neo4j_background(
    request: SyncRequest,
    background_tasks: BackgroundTasks,
    admin: User = Depends(require_admin),
):
    """
    Start background sync from PostgreSQL to Neo4j
    """
    try:
        service = get_sync_service()

        # Add background task
        background_tasks.add_task(background_sync_task, service, request.clear_existing)

        return SyncStatus(
            status="started", message="Background synchronization started"
        )

    except Exception as e:
        raise _sync_failure(
            "start background sync",
            e,
            clear_existing=request.clear_existing,
            sync_type=request.sync_type,
            admin_id=str(admin.id),
        ) from e


async def background_sync_task(service: "PostgresToNeo4jSync", clear_existing: bool):
    """Background task for data synchronization"""
    try:
        service.sync_all_data(clear_existing=clear_existing)
    except Exception:
        logger.exception("background Neo4j sync failed")
        raise


@router.get("/stats", response_model=SyncStatus)
async def get_sync_stats(admin: User = Depends(require_admin)):
    """
    Get synchronization statistics
    """
    try:
        service = get_sync_service()
        stats = service.get_sync_stats()

        return SyncStatus(
            status="success", message="Statistics retrieved successfully", stats=stats
        )

    except Exception as e:
        raise _sync_failure("get sync stats", e, admin_id=str(admin.id)) from e


@router.delete("/clear-neo4j", response_model=SyncStatus)
async def clear_neo4j_data(admin: User = Depends(require_admin)):
    """
    Clear all data from Neo4j
    """
    try:
        service = get_sync_service()
        service.clear_neo4j_data()

        return SyncStatus(status="success", message="Neo4j data cleared successfully")

    except Exception as e:
        raise _sync_failure("clear Neo4j data", e, admin_id=str(admin.id)) from e


@router.get("/health")
async def sync_health(admin: User = Depends(require_admin)):
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
            "test_value": test_value,
        }

    except Exception as e:
        raise _sync_failure("sync health check", e, admin_id=str(admin.id)) from e
