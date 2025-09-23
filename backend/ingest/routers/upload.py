from fastapi import APIRouter, UploadFile, File, HTTPException
from ingest.services.parser_service import UFDRParser
from ingest.services.ingest_service import IngestService
import logging
import aiofiles
from pathlib import Path

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

router = APIRouter(prefix="/upload", tags=["Upload"])

ingest_service = IngestService()


@router.post("/")
async def upload_ufdr(file: UploadFile = File(...)):
    """
    Upload a UFDR file, parse it, and ingest into DB + indexes.
    Supports .ufdr, .xml, .json, and .csv files.
    """
    try:
        # Validate file extension
        file_extension = Path(file.filename).suffix.lower()
        supported_extensions = ['.ufdr', '.xml', '.json', '.csv']
        if file_extension not in supported_extensions:
            raise HTTPException(
                status_code=400, 
                detail=f"Unsupported file type: {file_extension}. Supported types: {supported_extensions}"
            )

        # Ensure tmp storage exists
        tmp_dir = Path("storage/tmp")
        tmp_dir.mkdir(parents=True, exist_ok=True)

        tmp_path = tmp_dir / file.filename

        async with aiofiles.open(tmp_path, "wb") as f:
            while chunk := await file.read(8192):  # Read in 8KB chunks
                await f.write(chunk)

        logger.info(f"File saved to {tmp_path}")

        # Parse UFDR → dict
        parsed_data = UFDRParser.parse_file(str(tmp_path))
        parsed_data["filename"] = file.filename

        # Ingest to Postgres + others
        ingest_result = ingest_service.ingest_to_all(parsed_data)

        return {
            "status": "success",
            "filename": file.filename,
            "file_type": file_extension,
            "ingest_result": ingest_result,
        }

    except Exception as e:
        logger.error(f"Upload failed: {e}")
        raise HTTPException(status_code=500, detail=f"UFDR upload failed: {e}")
