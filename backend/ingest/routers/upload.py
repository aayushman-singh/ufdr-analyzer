from fastapi import APIRouter, HTTPException, Depends
from ingest.services.parser_service import UFDRParser
from ingest.services.ingest_service import IngestService
from ingest.services.cache_service import cache_service
from ingest.utils.logger import get_logger
from pathlib import Path
import traceback
from pydantic import BaseModel
from sqlmodel import Session
from meilisearch import Client as MeiliClient
from database import get_session
from db_setup import Run
import sys
import os
import re
import time
import uuid

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

def get_aleapp_report_path(file_path: str) -> Path:
    """Get the ALEAPP report path for a given file"""
    slug = create_slug_from_path(file_path)
    # Check both new location (ALEAPP/output/slug) and old location (UFDRConvert/slug/aleapp_output)
    # Navigate from backend directory to project root
    current_dir = Path(__file__).parent.parent.parent  # backend
    root_dir = current_dir.parent  # project root
    new_aleapp_path = root_dir / "ALEAPP" / "output" / slug
    old_aleapp_path = get_ufdr_cache_dir(file_path) / "aleapp_output"

    if new_aleapp_path.exists():
        return new_aleapp_path
    elif old_aleapp_path.exists():
        return old_aleapp_path
    else:
        return new_aleapp_path  # Return expected new location

def is_already_processed(file_path: str) -> bool:
    """Check if UFDR file has already been processed"""
    cache_dir = get_ufdr_cache_dir(file_path)
    report_xml = cache_dir / "report.xml"
    aleapp_output = get_aleapp_report_path(file_path)
    return cache_dir.exists() and report_xml.exists() and aleapp_output.exists()

@router.get("/validate-path")
async def validate_file_path(file_path: str):
    """
    Validate if a file path exists and is accessible.
    """
    try:
        path = Path(file_path)
        
        if not path.exists():
            return {
                "valid": False,
                "error": "File does not exist",
                "file_path": file_path
            }
        
        if not path.is_file():
            return {
                "valid": False,
                "error": "Path is not a file",
                "file_path": file_path
            }
        
        # Check file extension
        file_extension = path.suffix.lower()
        supported_extensions = ['.ufdr', '.xml', '.json', '.csv']
        
        if file_extension not in supported_extensions:
            return {
                "valid": False,
                "error": f"Unsupported file type: {file_extension}",
                "file_path": file_path
            }
        
        # Get file size
        file_size_bytes = path.stat().st_size
        file_size_gb = round(file_size_bytes / (1024**3), 2)
        
        return {
            "valid": True,
            "file_path": file_path,
            "file_size_bytes": file_size_bytes,
            "file_size_gb": file_size_gb,
            "readable": True,
            "file_extension": file_extension
        }
        
    except Exception as e:
        logger.error(f"File validation error: {e}")
        return {
            "valid": False,
            "error": f"Validation error: {str(e)}",
            "file_path": file_path
        }

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

        # OPTIMIZATION: Check for content-based deduplication first
        start_time = time.time()
        cached_result = cache_service.check_existing_processing(str(file_path), session)
        
        # The cache service now validates that runs have actual data before returning them
        # So we can trust cached_result if it exists

        if cached_result:
            processing_time = time.time() - start_time
            logger.info(f"Found cached result for file, returning in {processing_time:.2f}s")

            # Generate ALEAPP URLs for cached results
            aleapp_report_path = None
            aleapp_web_url = None
            slug = create_slug_from_path(str(file_path))

            # Check if ALEAPP was processed by looking for ALEAPP output directory
            aleapp_output_dir = get_aleapp_report_path(str(file_path))
            if aleapp_output_dir.exists():
                aleapp_reports = list(aleapp_output_dir.glob("ALEAPP_Reports_*"))
                if aleapp_reports:
                    # Use the first (and usually only) report directory
                    report_dir = aleapp_reports[0]
                    aleapp_report_path = str(report_dir.absolute())
                    # Provide web URL if accessible
                    aleapp_web_url = f"http://localhost:8080/ALEAPP/output/{slug}/{report_dir.name}/_HTML/index.html"

                    # Update the processing stats to reflect ALEAPP was processed
                    cached_result.processing_stats['aleapp_processed'] = True

            return {
                "status": "success",
                "cached": True,
                "filename": file_path.name,
                "file_path": str(file_path),
                "file_type": file_extension,
                "run_id": cached_result.run_id,
                "processing_time": f"{processing_time:.2f}s",
                "message": "Using cached results - file already processed",
                "ingest_result": cached_result.processing_stats,
                "aleapp_processed": cached_result.processing_stats.get('aleapp_processed', False),
                "aleapp_report_path": aleapp_report_path,
                "aleapp_web_url": aleapp_web_url,
                "slug": slug
            }

        # Check if already processed (legacy cache check)
        if is_already_processed(str(file_path)):
            cache_dir = get_ufdr_cache_dir(str(file_path))
            logger.info(f"File already processed, using cached data from: {cache_dir}")

            # Parse from cached report.xml
            report_xml_path = cache_dir / "report.xml"
            try:
                logger.info(f"Reading cached report.xml ({report_xml_path.stat().st_size / (1024*1024):.1f} MB)")
                parsed_data = UFDRParser._parse_xml(report_xml_path)
                logger.info("Cached XML parsing completed")

                # Add extraction info from cache
                logger.info("Getting cached files info...")
                parsed_data["_extraction_info"] = {
                    "extracted_dir": str(cache_dir),
                    "files_info": UFDRParser._get_files_info_from_cache(str(cache_dir))
                }
                logger.info("Normalizing cached data...")
                parsed_data = UFDRParser._normalize(parsed_data, file_path.name)
                
                # Add file path for hash calculation and deduplication
                parsed_data["file_path"] = str(file_path)
                parsed_data["filename"] = file_path.name

                # Check for cached ALEAPP data
                aleapp_output_dir = get_aleapp_report_path(str(file_path))
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
                parsed_data["file_path"] = str(file_path)
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
        logger.info(f"Data summary: {len(parsed_data.get('messages', []))} messages, {len(parsed_data.get('contacts', []))} contacts, {len(parsed_data.get('calls', []))} calls")

        # Get file hash for caching
        file_hash = cache_service.get_file_hash_with_cache(str(file_path))
        logger.info(f"File content hash: {file_hash[:12]}...")

        try:
            ingest_result = ingest_service.ingest_to_all(parsed_data, session, meili_client)
            logger.info(f"Ingestion successful: {ingest_result}")

            # Update the run record with file hash and original path
            if ingest_result and 'run_id' in ingest_result:
                try:
                    run = session.get(Run, ingest_result['run_id'])
                    if run:
                        run.file_content_hash = file_hash
                        run.original_file_path = str(file_path)
                        session.add(run)
                        session.commit()
                        logger.info(f"Updated run {run.id} with content hash")

                        # Cache the processing results
                        processing_stats = {
                            'file_path': str(file_path),
                            'run_id': str(run.id),
                            'message_count': len(parsed_data.get('messages', [])),
                            'contact_count': len(parsed_data.get('contacts', [])),
                            'call_count': len(parsed_data.get('calls', [])),
                            'aleapp_processed': "aleapp_data" in parsed_data,
                            'processing_time': time.time() - start_time,
                            'status': 'completed'
                        }

                        cache_service.cache_ingestion_result(file_hash, str(run.id), processing_stats)
                        logger.info("Cached ingestion results for future lookups")

                except Exception as cache_error:
                    logger.warning(f"Failed to update run with hash or cache results: {cache_error}")

        except Exception as ingest_error:
            logger.error(f"Data ingestion failed: {ingest_error}")
            logger.error(f"Ingest error traceback: {traceback.format_exc()}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to ingest data: {str(ingest_error)}"
            )

        # Get ALEAPP report path for response
        aleapp_report_path = None
        aleapp_web_url = None
        if "aleapp_data" in parsed_data:
            aleapp_output_dir = get_aleapp_report_path(str(file_path))
            if aleapp_output_dir.exists():
                aleapp_report_path = str(aleapp_output_dir.absolute())
                # Check for the actual ALEAPP report directory structure
                aleapp_reports = list(aleapp_output_dir.glob("ALEAPP_Reports_*"))
                if aleapp_reports:
                    # Use the first (and usually only) report directory
                    report_dir = aleapp_reports[0]
                    aleapp_report_path = str(report_dir.absolute())
                    # Provide web URL if accessible
                    slug = create_slug_from_path(str(file_path))
                    aleapp_web_url = f"http://localhost:8080/ALEAPP/output/{slug}/{report_dir.name}/_HTML/index.html"

        total_processing_time = time.time() - start_time
        logger.info(f"Ingestion process completed successfully in {total_processing_time:.2f}s")

        return {
            "status": "success",
            "cached": False,
            "filename": file_path.name,
            "file_path": str(file_path),
            "file_type": file_extension,
            "processing_time": f"{total_processing_time:.2f}s",
            "ingest_result": ingest_result,
            "aleapp_processed": "aleapp_data" in parsed_data,
            "aleapp_report_path": aleapp_report_path,
            "aleapp_web_url": aleapp_web_url,
            "slug": create_slug_from_path(str(file_path))
        }

    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        logger.error(f"Unexpected upload failure: {e}")
        logger.error(f"Error traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"UFDR ingestion failed: {e}")
