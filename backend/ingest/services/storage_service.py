# backend/services/storage_services.py
from minio import Minio
import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# MinIO Client Initialization
# You need to get these from environment variables or a config file
MINIO_URL = os.getenv("MINIO_URL", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minio_access_key")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minio_secret_key")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "ufdr-media")

# Create a MinIO client instance
minio_client = Minio(
    MINIO_URL,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False  # Use True if you're using https
)


def save_media(local_file_path: str, run_id: str) -> str:
    """
    Uploads a local media file to MinIO.

    Args:
        local_file_path: The local path to the file.
        run_id: The ID of the ingestion run to categorize the file.

    Returns:
        The MinIO object name (path) of the saved file.
    """
    local_path = Path(local_file_path)
    if not local_path.exists() or not local_path.is_file():
        logger.error(f"Local file not found: {local_file_path}")
        return ""

    # Ensure the bucket exists
    try:
        if not minio_client.bucket_exists(MINIO_BUCKET):
            minio_client.make_bucket(MINIO_BUCKET)
            logger.info(f"Created MinIO bucket: {MINIO_BUCKET}")
    except Exception as e:
        logger.error(f"Error checking/creating bucket: {e}")
        return ""

    # Define the object name in the bucket
    # e.g., 'run_id/media/image_123.jpg'
    file_name = local_path.name
    minio_path = f"{run_id}/media/{file_name}"

    try:
        minio_client.fput_object(
            bucket_name=MINIO_BUCKET,
            object_name=minio_path,
            file_path=str(local_path)
        )
        logger.info(f"Successfully uploaded {local_path} to {minio_path}")
        return minio_path
    except Exception as e:
        logger.error(f"Error uploading file to MinIO: {e}")
        return ""
