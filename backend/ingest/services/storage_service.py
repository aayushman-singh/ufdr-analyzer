# backend/services/storage_services.py
import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Configuration - prefer local storage for efficiency (no file duplication)
USE_LOCAL_STORAGE = os.getenv("USE_LOCAL_STORAGE", "true").lower() == "true"
LOCAL_STORAGE_PATH = os.getenv(
    "LOCAL_STORAGE_PATH", "storage/media"
)  # Legacy path, not used when optimized

# MinIO Configuration (only if local storage is disabled)
MINIO_URL = os.getenv("MINIO_URL", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minio_access_key")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minio_secret_key")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "ufdr-media")

# Initialize MinIO client only if needed
minio_client = None
if not USE_LOCAL_STORAGE:
    try:
        from minio import Minio

        minio_client = Minio(
            MINIO_URL,
            access_key=MINIO_ACCESS_KEY,
            secret_key=MINIO_SECRET_KEY,
            secure=False,
        )
        logger.info("MinIO client initialized")
    except ImportError as e:
        raise RuntimeError("USE_LOCAL_STORAGE=false but MinIO is not installed") from e
    except Exception as e:
        raise RuntimeError(f"MinIO client initialization failed: {e}") from e


def save_media_local(local_file_path: str, run_id: str) -> str:
    """
    References media file without duplication (optimized for local storage).

    Args:
        local_file_path: The local path to the file.
        run_id: The ID of the ingestion run to categorize the file.

    Returns:
        The original file path (no copying needed for local storage).
    """
    local_path = Path(local_file_path)
    if not local_path.exists() or not local_path.is_file():
        raise FileNotFoundError(f"Local media file not found: {local_file_path}")

    # Optimization: Return original path instead of copying
    # Files are already organized in UFDRConvert/ and ALEAPP/output/
    # No need to duplicate them in storage/media/
    return str(local_path)


def save_media_minio(local_file_path: str, run_id: str) -> str:
    """
    Uploads a local media file to MinIO.

    Args:
        local_file_path: The local path to the file.
        run_id: The ID of the ingestion run to categorize the file.

    Returns:
        The MinIO object name (path) of the saved file.
    """
    if not minio_client:
        raise RuntimeError("MinIO client not available")

    local_path = Path(local_file_path)
    if not local_path.exists() or not local_path.is_file():
        raise FileNotFoundError(f"Local media file not found: {local_file_path}")

    # Ensure the bucket exists
    try:
        if not minio_client.bucket_exists(MINIO_BUCKET):
            minio_client.make_bucket(MINIO_BUCKET)
            logger.info(f"Created MinIO bucket: {MINIO_BUCKET}")
    except Exception as e:
        raise RuntimeError(f"Error checking/creating bucket {MINIO_BUCKET}: {e}") from e

    # Define the object name in the bucket
    file_name = local_path.name
    minio_path = f"{run_id}/media/{file_name}"

    try:
        minio_client.fput_object(
            bucket_name=MINIO_BUCKET, object_name=minio_path, file_path=str(local_path)
        )
        logger.info(f"Successfully uploaded {local_path} to MinIO: {minio_path}")
        return minio_path
    except Exception as e:
        raise RuntimeError(f"Error uploading file to MinIO: {e}") from e


def save_media(local_file_path: str, run_id: str) -> str:
    """
    Saves media file using the configured storage method (local or MinIO).

    Args:
        local_file_path: The local path to the file.
        run_id: The ID of the ingestion run to categorize the file.

    Returns:
        The storage path of the saved file.
    """
    if USE_LOCAL_STORAGE:
        return save_media_local(local_file_path, run_id)
    return save_media_minio(local_file_path, run_id)
