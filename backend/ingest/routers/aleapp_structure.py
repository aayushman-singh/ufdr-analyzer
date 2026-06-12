import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from database import get_session
from db_setup import User
from ingest.services.auth_service import require_user
from ingest.services.case_access import authorize_run
from ingest.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/ingest", tags=["ALEAPP"])


def create_slug_from_path(file_path: str) -> str:
    filename = Path(file_path).stem
    slug = re.sub(r"[^\w\-_.]", "_", filename).lower()
    return re.sub(r"_+", "_", slug).strip("_")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def resolve_case_aleapp_report_dir(report_path: str, run) -> Path:
    source_path = run.original_file_path or run.ufdr_file_name
    if not source_path:
        raise HTTPException(
            status_code=409,
            detail=f"run {run.id} has no source path for ALEAPP report binding",
        )
    slug = create_slug_from_path(source_path)
    root = _repo_root()
    allowed_roots = [
        (root / "ALEAPP" / "output" / slug).resolve(strict=False),
        (root / "UFDRConvert" / slug / "aleapp_output").resolve(strict=False),
    ]
    requested = Path(report_path).expanduser().resolve(strict=False)
    if not any(
        requested == allowed or _is_relative_to(requested, allowed)
        for allowed in allowed_roots
    ):
        raise HTTPException(
            status_code=403,
            detail="ALEAPP report path is not bound to the authorized case",
        )
    if not requested.exists():
        raise HTTPException(
            status_code=404, detail=f"ALEAPP report directory not found: {report_path}"
        )
    if not requested.is_dir():
        raise HTTPException(
            status_code=400, detail="ALEAPP report path is not a directory"
        )
    return requested


def get_aleapp_file_structure(report_dir: Path) -> Dict[str, Any]:
    """
    Extract file structure from ALEAPP report directory
    """
    try:
        structure = {
            "root": str(report_dir.name),
            "directories": [],
            "files": [],
            "total_files": 0,
            "total_dirs": 0,
        }

        # Walk through the directory structure
        for root, dirs, files in os.walk(report_dir):
            root_path = Path(root)

            # Add directories
            for dir_name in dirs:
                dir_path = root_path / dir_name
                relative_dir_path = dir_path.relative_to(report_dir)
                structure["directories"].append(
                    {
                        "name": dir_name,
                        "path": str(relative_dir_path),
                        "size": get_directory_size(dir_path),
                    }
                )
                structure["total_dirs"] += 1

            # Add files
            for file_name in files:
                file_path = root_path / file_name
                relative_file_path = file_path.relative_to(report_dir)
                file_size = file_path.stat().st_size

                structure["files"].append(
                    {
                        "name": file_name,
                        "path": str(relative_file_path),
                        "size": file_size,
                        "size_formatted": format_file_size(file_size),
                        "extension": file_path.suffix.lower(),
                    }
                )
                structure["total_files"] += 1

        # Organize by categories based on ALEAPP structure
        structure["categories"] = organize_aleapp_categories(
            structure["files"], structure["directories"]
        )

        return structure

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error extracting ALEAPP structure: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to extract ALEAPP structure: {str(e)}"
        )


def get_directory_size(directory: Path) -> int:
    """Calculate total size of directory"""
    total_size = 0
    for file_path in directory.rglob("*"):
        if file_path.is_file():
            total_size += file_path.stat().st_size
    return total_size


def format_file_size(size_bytes: int) -> str:
    """Format file size in human readable format"""
    if size_bytes == 0:
        return "0 B"

    size_names = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1

    return f"{size_bytes:.1f} {size_names[i]}"


def organize_aleapp_categories(
    files: List[Dict], directories: List[Dict]
) -> Dict[str, Any]:
    """Organize ALEAPP files into logical categories"""
    categories = {
        "html_reports": [],
        "tsv_exports": [],
        "databases": [],
        "timeline": [],
        "data_extraction": [],
        "scripts": [],
        "other": [],
    }

    for file_info in files:
        file_path = file_info["path"].lower()
        file_name = file_info["name"].lower()

        if file_path.startswith("_html") or file_name.endswith(".html"):
            categories["html_reports"].append(file_info)
        elif file_path.startswith("_tsv exports") or file_name.endswith(".tsv"):
            categories["tsv_exports"].append(file_info)
        elif file_name.endswith(".db"):
            categories["databases"].append(file_info)
        elif file_path.startswith("_timeline"):
            categories["timeline"].append(file_info)
        elif file_path.startswith("data"):
            categories["data_extraction"].append(file_info)
        elif file_path.startswith("script logs"):
            categories["scripts"].append(file_info)
        else:
            categories["other"].append(file_info)

    return categories


@router.get("/aleapp-structure")
async def get_aleapp_structure(
    report_path: str,
    run_id: uuid.UUID,
    session: Session = Depends(get_session),
    auth_user: User = Depends(require_user),
):
    """
    Get ALEAPP report file structure
    """
    try:
        run = authorize_run(session, auth_user, run_id)
        report_dir = resolve_case_aleapp_report_dir(report_path, run)
        structure = get_aleapp_file_structure(report_dir)
        return structure
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get ALEAPP structure: {e}")
        raise HTTPException(status_code=500, detail=str(e))
