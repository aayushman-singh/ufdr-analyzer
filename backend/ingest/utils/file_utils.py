# backend/utils/file_utils.py
from pathlib import Path
import uuid


def generate_uuid_filename(filename: str) -> str:
    """
    Generates a unique filename with a UUID prefix.
    """
    return f"{uuid.uuid4()}_{filename}"


def ensure_folder(folder: str) -> Path:
    """
    Ensures the folder exists; creates if not.
    """
    path = Path(folder)
    path.mkdir(parents=True, exist_ok=True)
    return path
