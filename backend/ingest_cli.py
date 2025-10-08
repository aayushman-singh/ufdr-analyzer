#!/usr/bin/env python3
"""
CLI tool for ingesting local UFDR files into the database.
Usage: python ingest_cli.py /path/to/file.ufdr
"""
import sys
import argparse
import os
from pathlib import Path
from sqlmodel import Session
from meilisearch import Client as MeiliClient

# Fix Windows console encoding issues
if sys.platform == "win32":
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.detach())
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.detach())

from ingest.services.parser_service import UFDRParser
from ingest.services.ingest_service import IngestService
from database import engine
from config import MEILI_CONFIG
from ingest.utils.logger import get_logger

logger = get_logger(__name__)


def ingest_file(file_path: str, user_id: int = 1) -> dict:
    """
    Ingest a single UFDR file into the database.

    Args:
        file_path: Path to the UFDR file
        user_id: User ID for the ingestion (default: 1)

    Returns:
        dict: Ingestion result
    """
    file_path = Path(file_path)

    # Validate file exists
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    # Validate file extension
    supported_extensions = ['.ufdr', '.xml', '.json', '.csv']
    if file_path.suffix.lower() not in supported_extensions:
        raise ValueError(f"Unsupported file type: {file_path.suffix}. Supported: {supported_extensions}")

    logger.info(f"Starting ingestion of: {file_path}")

    try:
        # Parse the file
        logger.info("Parsing file...")
        parsed_data = UFDRParser.parse_file(str(file_path))
        parsed_data["filename"] = file_path.name
        parsed_data["user_id"] = user_id

        logger.info(f"Parsed data contains:")
        logger.info(f"  - Messages: {len(parsed_data.get('messages', []))}")
        logger.info(f"  - Contacts: {len(parsed_data.get('contacts', []))}")
        logger.info(f"  - Calls: {len(parsed_data.get('calls', []))}")
        logger.info(f"  - Media: {len(parsed_data.get('media', []))}")

        # Initialize services
        ingest_service = IngestService()

        # Connect to Meilisearch (optional)
        meili_client = None
        try:
            meili_client = MeiliClient(
                MEILI_CONFIG['host'],
                MEILI_CONFIG.get('api_key')
            )
            logger.info("Connected to Meilisearch")
        except Exception as e:
            logger.warning(f"Could not connect to Meilisearch: {e}")
            logger.warning("Proceeding without search indexing")

        # Ingest to database
        logger.info("Ingesting to database...")
        with Session(engine) as session:
            result = ingest_service.ingest_to_all(parsed_data, session, meili_client)

        logger.info(f"Ingestion completed successfully: {result}")
        return result

    except Exception as e:
        # Check if this is a database connection error
        error_msg = str(e)
        if "Connection refused" in error_msg or "connection to server" in error_msg:
            logger.error(f"Database connection failed: {e}")
            logger.error("")
            logger.error("PostgreSQL is not running. To start it:")
            logger.error("  Option 1 (Docker):     ./start-dev-services.bat")
            logger.error("  Option 2 (Local):      ./start-dev-local.bat")
            logger.error("  See DEVELOPMENT.md for detailed setup instructions")
        else:
            logger.error(f"Ingestion failed: {e}")
        raise


def main():
    parser = argparse.ArgumentParser(description="Ingest UFDR files into the database")
    parser.add_argument("file_path", help="Path to the UFDR file")
    parser.add_argument("--user-id", type=int, default=1, help="User ID for the ingestion (default: 1)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")

    args = parser.parse_args()

    if args.verbose:
        import logging
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        result = ingest_file(args.file_path, args.user_id)
        print("[SUCCESS] Ingestion successful!")
        print(f"Run ID: {result.get('run_id')}")
        print(f"Status: {result.get('status')}")

    except FileNotFoundError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)
    except ValueError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)
    except Exception as e:
        error_msg = str(e)
        if "Connection refused" in error_msg or "connection to server" in error_msg:
            print(f"[ERROR] Database connection failed")
            print("")
            print("PostgreSQL is not running. To start it:")
            print("  Option 1 (Docker):     ./start-dev-services.bat")
            print("  Option 2 (Local):      ./start-dev-local.bat")
            print("  See DEVELOPMENT.md for detailed setup instructions")
        else:
            print(f"[ERROR] Ingestion failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()