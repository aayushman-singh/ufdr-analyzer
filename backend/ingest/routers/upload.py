from fastapi import APIRouter, HTTPException, Depends
from ingest.services.parser_service import UFDRParser
from ingest.services.ingest_service import IngestService
from ingest.utils.logger import get_logger
from pathlib import Path
import traceback
from pydantic import BaseModel
from sqlmodel import Session
from meilisearch import Client as MeiliClient
from database import get_session
import sys
import os
import re

# Avoid circular import by getting meili_client directly
def get_meili_client():
    """Get the Meilisearch client instance"""
    from meilisearch import Client as MeiliClient
    MEILI_URL = os.getenv("MEILI_URL", "http://localhost:7700")
    MEILI_KEY = os.getenv("MEILI_KEY", None)
    return MeiliClient(MEILI_URL, MEILI_KEY)

logger = get_logger(__name__)

router = APIRouter(prefix="/ingest", tags=["Ingest"])

ingest_service = IngestService()


class IngestRequest(BaseModel):
    file_path: str

def create_slug_from_path(file_path: str) -> str:
    """Create a slug from file path for folder naming"""
    filename = Path(file_path).stem  # Get filename without extension
    # Replace spaces and special chars with underscores, convert to lowercase
    slug = re.sub(r'[^\w\-_.]', '_', filename).lower()
    slug = re.sub(r'_+', '_', slug).strip('_')  # Remove multiple underscores
    return slug

def get_ufdr_cache_dir(file_path: str) -> Path:
    """Get the cache directory for a specific UFDR file"""
    slug = create_slug_from_path(file_path)
    return Path("UFDRConvert") / slug

def is_already_processed(file_path: str) -> bool:
    """Check if UFDR file has already been processed"""
    cache_dir = get_ufdr_cache_dir(file_path)
    report_xml = cache_dir / "report.xml"
    aleapp_output = cache_dir / "aleapp_output"
    return cache_dir.exists() and report_xml.exists() and aleapp_output.exists()

@router.post("/")
async def ingest_ufdr(
    request: IngestRequest,
    session: Session = Depends(get_session),
    meili_client: MeiliClient = Depends(get_meili_client)
):
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

        # Check if already processed
        if is_already_processed(str(file_path)):
            cache_dir = get_ufdr_cache_dir(str(file_path))
            logger.info(f"File already processed, using cached data from: {cache_dir}")

            # Parse from cached report.xml
            report_xml_path = cache_dir / "report.xml"
            try:
                parsed_data = UFDRParser._parse_xml(report_xml_path)
                # Add extraction info from cache
                parsed_data["_extraction_info"] = {
                    "extracted_dir": str(cache_dir),
                    "files_info": UFDRParser._get_files_info_from_cache(str(cache_dir))
                }
                parsed_data = UFDRParser._normalize(parsed_data, file_path.name)

                # Check for cached ALEAPP data
                aleapp_output_dir = cache_dir / "aleapp_output"
                if aleapp_output_dir.exists():
                    aleapp_output = UFDRParser._parse_aleapp_output(str(aleapp_output_dir))
                    if aleapp_output:
                        parsed_data["aleapp_data"] = aleapp_output
                        logger.info("Using cached ALEAPP data")
                logger.info(f"Using cached data, parsed {len(parsed_data)} fields")
            except Exception as cache_error:
                logger.warning(f"Cache read failed, will reprocess: {cache_error}")
                # Fall through to normal processing
                parsed_data = None
        else:
            parsed_data = None

        # If not cached or cache failed, process normally
        if parsed_data is None:
            logger.info("Starting file parsing...")
            try:
                # Modify the parser to use organized folders
                parsed_data = UFDRParser.parse_file(str(file_path), output_dir=str(get_ufdr_cache_dir(str(file_path))))
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
            ingest_result = ingest_service.ingest_to_all(parsed_data, session, meili_client)
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
            "aleapp_processed": "aleapp_data" in parsed_data,
        }

    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        logger.error(f"Unexpected upload failure: {e}")
        logger.error(f"Error traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"UFDR ingestion failed: {e}")
