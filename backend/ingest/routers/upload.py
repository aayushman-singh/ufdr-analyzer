from fastapi import APIRouter, UploadFile, File, HTTPException, Request
from ingest.services.parser_service import UFDRParser
from ingest.services.ingest_service import IngestService
from ingest.utils.logger import get_logger
import aiofiles
from pathlib import Path
import traceback

logger = get_logger(__name__)

router = APIRouter(prefix="/upload", tags=["Upload"])

ingest_service = IngestService()


@router.post("/")
async def upload_ufdr(file: UploadFile = File(...)):
    """
    Upload a UFDR file, parse it, and ingest into DB + indexes.
    Supports .ufdr, .xml, .json, and .csv files.
    """
    logger.info(f"Starting upload process for file: {file.filename}")
    
    try:
        # Log file details
        logger.info(f"File details - Name: {file.filename}, Content-Type: {file.content_type}, Size: {file.size if hasattr(file, 'size') else 'unknown'}")
        
        # Validate file extension
        file_extension = Path(file.filename).suffix.lower()
        supported_extensions = ['.ufdr', '.xml', '.json', '.csv']
        logger.info(f"File extension: {file_extension}")
        
        if file_extension not in supported_extensions:
            logger.warning(f"Unsupported file type: {file_extension}")
            raise HTTPException(
                status_code=400, 
                detail=f"Unsupported file type: {file_extension}. Supported types: {supported_extensions}"
            )

        logger.info("File extension validation passed")

        # Ensure tmp storage exists
        tmp_dir = Path("storage/tmp")
        tmp_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Temporary directory: {tmp_dir}")

        tmp_path = tmp_dir / file.filename
        logger.info(f"Saving file to: {tmp_path}")

        # Save file with detailed logging
        bytes_written = 0
        async with aiofiles.open(tmp_path, "wb") as f:
            while chunk := await file.read(8192):  # Read in 8KB chunks
                await f.write(chunk)
                bytes_written += len(chunk)
                if bytes_written % (1024 * 1024) == 0:  # Log every MB
                    logger.info(f"Written {bytes_written / (1024 * 1024):.1f} MB")

        logger.info(f"File saved successfully to {tmp_path} ({bytes_written} bytes)")

        # Parse UFDR → dict
        logger.info("Starting file parsing...")
        try:
            parsed_data = UFDRParser.parse_file(str(tmp_path))
            parsed_data["filename"] = file.filename
            logger.info(f"File parsing successful. Parsed {len(parsed_data)} fields")
        except Exception as parse_error:
            logger.error(f"File parsing failed: {parse_error}")
            logger.error(f"Parse error traceback: {traceback.format_exc()}")
            raise HTTPException(
                status_code=400, 
                detail=f"Failed to parse file: {str(parse_error)}"
            )

        # Ingest to Postgres + others
        logger.info("Starting data ingestion...")
        try:
            ingest_result = ingest_service.ingest_to_all(parsed_data)
            logger.info(f"Ingestion successful: {ingest_result}")
        except Exception as ingest_error:
            logger.error(f"Data ingestion failed: {ingest_error}")
            logger.error(f"Ingest error traceback: {traceback.format_exc()}")
            raise HTTPException(
                status_code=500, 
                detail=f"Failed to ingest data: {str(ingest_error)}"
            )

        logger.info("Upload process completed successfully")
        return {
            "status": "success",
            "filename": file.filename,
            "file_type": file_extension,
            "ingest_result": ingest_result,
        }

    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        logger.error(f"Unexpected upload failure: {e}")
        logger.error(f"Error traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"UFDR upload failed: {e}")
