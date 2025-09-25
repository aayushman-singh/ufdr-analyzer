from fastapi import APIRouter, HTTPException
from ingest.services.parser_service import UFDRParser
from ingest.services.ingest_service import IngestService
from ingest.utils.logger import get_logger
from pathlib import Path
import traceback
from pydantic import BaseModel

logger = get_logger(__name__)

router = APIRouter(prefix="/ingest", tags=["Ingest"])

ingest_service = IngestService()


class IngestRequest(BaseModel):
    file_path: str

@router.post("/")
async def ingest_ufdr(request: IngestRequest):
    """
    Ingest a UFDR file by file path: parse and store in DB + search indexes.
    Supports .ufdr, .xml, .json, and .csv files.
    """
    logger.info(f"Starting ingestion process for file: {request.file_path}")

    try:
        file_path = Path(request.file_path)

        # Validate file exists
        if not file_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"File not found: {request.file_path}"
            )

        # Validate file extension
        file_extension = file_path.suffix.lower()
        supported_extensions = ['.ufdr', '.xml', '.json', '.csv']
        logger.info(f"File extension: {file_extension}")

        if file_extension not in supported_extensions:
            logger.warning(f"Unsupported file type: {file_extension}")
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {file_extension}. Supported types: {supported_extensions}"
            )

        logger.info("File validation passed")

        # Parse UFDR → dict
        logger.info("Starting file parsing...")
        try:
            parsed_data = UFDRParser.parse_file(str(file_path))
            parsed_data["filename"] = file_path.name
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

        logger.info("Ingestion process completed successfully")
        return {
            "status": "success",
            "filename": file_path.name,
            "file_path": str(file_path),
            "file_type": file_extension,
            "ingest_result": ingest_result,
        }

    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        logger.error(f"Unexpected upload failure: {e}")
        logger.error(f"Error traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"UFDR ingestion failed: {e}")
