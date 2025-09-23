from fastapi import APIRouter
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("/")
async def health_check():
    """
    Simple health check endpoint.
    Returns OK if the server is running.
    """
    logger.info("Health check requested")
    return {"status": "OK"}
