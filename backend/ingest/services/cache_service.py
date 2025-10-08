"""
Cache service for UFDR ingestion optimization.
Provides content-based deduplication and result caching.
"""
import hashlib
import json
import os
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime
import uuid
from sqlmodel import Session, select
from db_setup import Run
from ingest.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class CachedResult:
    """Represents a cached processing result."""
    run_id: str
    file_path: str
    cached_at: datetime
    processing_stats: Dict[str, Any]


class CacheService:
    """Service for managing file content hashing and result caching."""

    def __init__(self, cache_root: str = "cache"):
        """Initialize cache service with specified cache directory."""
        self.cache_root = Path(cache_root)
        self.hashes_dir = self.cache_root / "hashes"
        self.parsed_data_dir = self.cache_root / "parsed_data"
        self.results_dir = self.cache_root / "results"

        # Ensure cache directories exist
        for cache_dir in [self.hashes_dir, self.parsed_data_dir, self.results_dir]:
            cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def get_file_content_hash(file_path: str) -> str:
        """
        Generate SHA-256 hash of file content for deduplication.
        Uses stream-based hashing for large files.
        """
        logger.info(f"Computing content hash for: {file_path}")
        sha256_hash = hashlib.sha256()

        try:
            with open(file_path, "rb") as f:
                # Read file in 64KB chunks to handle large files efficiently
                for chunk in iter(lambda: f.read(65536), b""):
                    sha256_hash.update(chunk)

            file_hash = sha256_hash.hexdigest()
            logger.info(f"Content hash computed: {file_hash[:12]}...")
            return file_hash

        except Exception as e:
            logger.error(f"Failed to compute hash for {file_path}: {e}")
            raise

    def get_cached_file_hash(self, file_path: str) -> Optional[str]:
        """Retrieve cached file hash if available."""
        filename = Path(file_path).name
        hash_file = self.hashes_dir / f"{filename}.hash"

        if hash_file.exists():
            try:
                with open(hash_file, 'r') as f:
                    cached_data = json.load(f)

                # Verify file hasn't changed since hash was computed
                file_stat = os.stat(file_path)
                if cached_data.get('mtime') == file_stat.st_mtime and cached_data.get('size') == file_stat.st_size:
                    logger.info(f"Using cached hash for {filename}")
                    return cached_data['hash']
                else:
                    logger.info(f"File {filename} has changed, hash cache invalid")

            except Exception as e:
                logger.warning(f"Failed to read cached hash for {filename}: {e}")

        return None

    def cache_file_hash(self, file_path: str, file_hash: str) -> None:
        """Cache file hash with metadata."""
        filename = Path(file_path).name
        hash_file = self.hashes_dir / f"{filename}.hash"

        try:
            file_stat = os.stat(file_path)
            cache_data = {
                'hash': file_hash,
                'file_path': file_path,
                'mtime': file_stat.st_mtime,
                'size': file_stat.st_size,
                'cached_at': datetime.now().isoformat()
            }

            with open(hash_file, 'w') as f:
                json.dump(cache_data, f, indent=2)

            logger.info(f"Cached hash for {filename}")

        except Exception as e:
            logger.error(f"Failed to cache hash for {filename}: {e}")

    def get_file_hash_with_cache(self, file_path: str) -> str:
        """Get file hash, using cache if available, otherwise compute and cache."""
        # Try to get cached hash first
        cached_hash = self.get_cached_file_hash(file_path)
        if cached_hash:
            return cached_hash

        # Compute hash and cache it
        file_hash = self.get_file_content_hash(file_path)
        self.cache_file_hash(file_path, file_hash)
        return file_hash

    def check_database_for_hash(self, file_hash: str, session: Session) -> Optional[Run]:
        """Check if a file with this hash has already been processed."""
        logger.info(f"Checking database for hash: {file_hash[:12]}...")

        try:
            statement = select(Run).where(Run.file_content_hash == file_hash).order_by(Run.start_time.desc())
            result = session.exec(statement).first()

            if result:
                logger.info(f"Found existing run: {result.id} (status: {result.status})")
                return result
            else:
                logger.info("No existing run found for this hash")
                return None

        except Exception as e:
            logger.error(f"Database lookup failed: {e}")
            return None

    def cache_parsed_data(self, file_hash: str, parsed_data: Dict[str, Any]) -> None:
        """Cache normalized parsed data as JSON."""
        cache_file = self.parsed_data_dir / f"{file_hash}.json"
        metadata_file = self.parsed_data_dir / f"{file_hash}_metadata.json"

        try:
            # Cache the main parsed data
            with open(cache_file, 'w') as f:
                json.dump(parsed_data, f, indent=2, default=str)

            # Cache metadata about the parsing
            metadata = {
                'file_hash': file_hash,
                'cached_at': datetime.now().isoformat(),
                'message_count': len(parsed_data.get('messages', [])),
                'contact_count': len(parsed_data.get('contacts', [])),
                'call_count': len(parsed_data.get('calls', [])),
                'data_size_mb': cache_file.stat().st_size / (1024 * 1024)
            }

            with open(metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2)

            logger.info(f"Cached parsed data for hash {file_hash[:12]}...")

        except Exception as e:
            logger.error(f"Failed to cache parsed data: {e}")

    def get_cached_parsed_data(self, file_hash: str) -> Optional[Dict[str, Any]]:
        """Retrieve cached parsed data if available."""
        cache_file = self.parsed_data_dir / f"{file_hash}.json"

        if cache_file.exists():
            try:
                with open(cache_file, 'r') as f:
                    data = json.load(f)
                    logger.info(f"Retrieved cached parsed data for hash {file_hash[:12]}...")
                    return data
            except Exception as e:
                logger.warning(f"Failed to read cached parsed data: {e}")

        return None

    def cache_ingestion_result(self, file_hash: str, run_id: str, stats: Dict[str, Any]) -> None:
        """Cache database ingestion results."""
        result_file = self.results_dir / f"{file_hash}_result.json"
        stats_file = self.results_dir / f"{file_hash}_stats.json"

        try:
            # Cache ingestion result
            result_data = {
                'file_hash': file_hash,
                'run_id': run_id,
                'cached_at': datetime.now().isoformat(),
                'status': 'completed'
            }

            with open(result_file, 'w') as f:
                json.dump(result_data, f, indent=2)

            # Cache processing statistics
            with open(stats_file, 'w') as f:
                json.dump(stats, f, indent=2, default=str)

            logger.info(f"Cached ingestion result for hash {file_hash[:12]}...")

        except Exception as e:
            logger.error(f"Failed to cache ingestion result: {e}")

    def get_cached_ingestion_result(self, file_hash: str) -> Optional[CachedResult]:
        """Retrieve cached ingestion result if available."""
        result_file = self.results_dir / f"{file_hash}_result.json"
        stats_file = self.results_dir / f"{file_hash}_stats.json"

        if result_file.exists() and stats_file.exists():
            try:
                with open(result_file, 'r') as f:
                    result_data = json.load(f)

                with open(stats_file, 'r') as f:
                    stats_data = json.load(f)

                return CachedResult(
                    run_id=result_data['run_id'],
                    file_path=stats_data.get('file_path', ''),
                    cached_at=datetime.fromisoformat(result_data['cached_at']),
                    processing_stats=stats_data
                )

            except Exception as e:
                logger.warning(f"Failed to read cached result: {e}")

        return None

    def check_existing_processing(self, file_path: str, session: Session) -> Optional[CachedResult]:
        """
        Check multiple cache levels for existing processing.
        Returns CachedResult if found, None otherwise.
        """
        logger.info(f"Checking for existing processing of: {Path(file_path).name}")

        # Level 1: Get file content hash
        file_hash = self.get_file_hash_with_cache(file_path)

        # Level 2: Check database for existing run with this hash
        existing_run = self.check_database_for_hash(file_hash, session)

        if existing_run:
            # Check if this run has any actual data (messages, calls, contacts, media)
            from db_setup import Message, Call, Contact, Media
            has_messages = session.exec(select(Message).where(Message.run_id == existing_run.id).limit(1)).first() is not None
            has_calls = session.exec(select(Call).where(Call.run_id == existing_run.id).limit(1)).first() is not None
            has_contacts = session.exec(select(Contact).where(Contact.run_id == existing_run.id).limit(1)).first() is not None
            has_media = session.exec(select(Media).where(Media.run_id == existing_run.id).limit(1)).first() is not None
            
            has_data = has_messages or has_calls or has_contacts or has_media
            
            # If run has data, return it regardless of status
            if has_data:
                logger.info(f"Found existing run {existing_run.id} with data (status: {existing_run.status})")
                stats = {
                    'file_path': file_path,
                    'run_id': str(existing_run.id),
                    'status': existing_run.status,
                    'start_time': existing_run.start_time.isoformat(),
                    'end_time': existing_run.end_time.isoformat() if existing_run.end_time else None,
                    'processing_time': 'cached',
                    'aleapp_processed': False
                }

                return CachedResult(
                    run_id=str(existing_run.id),
                    file_path=file_path,
                    cached_at=existing_run.start_time,
                    processing_stats=stats
                )
            elif existing_run.status in ['complete', 'completed', 'success']:
                # Run is marked complete but has no data - this is an empty run
                # Don't return it, let the system reprocess or create a proper run
                logger.warning(f"Found completed run {existing_run.id} but it has no data - ignoring")
            else:
                # Run exists but has no data and isn't complete - probably failed or in progress
                logger.info(f"Found run {existing_run.id} with status {existing_run.status} but no data - ignoring")

        # NOTE: We no longer create new runs from cache files alone
        # This was causing empty runs to be created without actual data
        # If no run with data exists, we should fall through to reprocessing
        
        logger.info("No existing processing found with data")
        return None

    def has_comprehensive_cache(self, file_hash: str, file_path: str) -> bool:
        """Check if we have comprehensive cache files that can create a fast response."""
        try:
            # Check if we have XML cache
            xml_path = Path(file_path)
            if xml_path.suffix.lower() == '.ufdr':
                # For UFDR files, check if extraction cache exists
                filename = xml_path.stem.lower().replace(' ', '_')
                cache_dir = Path("UFDRConvert") / filename
                report_xml = cache_dir / "report.xml"

                if not (cache_dir.exists() and report_xml.exists()):
                    return False

                # Check if we have XML parse cache for the report.xml
                file_stat = report_xml.stat()
                cache_key = f"{report_xml.name}_{file_stat.st_mtime}_{file_stat.st_size}"
                xml_cache_file = self.parsed_data_dir / f"xml_{cache_key}.json"

                return xml_cache_file.exists()

            elif xml_path.suffix.lower() == '.xml':
                # For direct XML files, check if we have XML parse cache
                file_stat = xml_path.stat()
                cache_key = f"{xml_path.name}_{file_stat.st_mtime}_{file_stat.st_size}"
                xml_cache_file = self.parsed_data_dir / f"xml_{cache_key}.json"

                return xml_cache_file.exists()

            # For other file types, check if we have parsed data cache
            parsed_cache_file = self.parsed_data_dir / f"{file_hash}.json"
            return parsed_cache_file.exists()

        except Exception as e:
            logger.warning(f"Failed to check comprehensive cache: {e}")
            return False

    def cleanup_stale_cache(self, max_age_days: int = 30) -> None:
        """Remove old cache entries."""
        logger.info(f"Cleaning up cache entries older than {max_age_days} days")

        cutoff_time = datetime.now().timestamp() - (max_age_days * 24 * 3600)

        for cache_dir in [self.hashes_dir, self.parsed_data_dir, self.results_dir]:
            if not cache_dir.exists():
                continue

            for cache_file in cache_dir.iterdir():
                if cache_file.is_file() and cache_file.stat().st_mtime < cutoff_time:
                    try:
                        cache_file.unlink()
                        logger.info(f"Removed stale cache file: {cache_file.name}")
                    except Exception as e:
                        logger.warning(f"Failed to remove {cache_file}: {e}")

    def is_cache_valid(self, file_hash: str) -> bool:
        """Check if cached data is still valid."""
        result_file = self.results_dir / f"{file_hash}_result.json"
        parsed_file = self.parsed_data_dir / f"{file_hash}.json"

        # Check if all required cache files exist
        if not (result_file.exists() and parsed_file.exists()):
            return False

        try:
            # Check file integrity (basic validation)
            with open(result_file, 'r') as f:
                result_data = json.load(f)
                if not result_data.get('run_id'):
                    return False

            with open(parsed_file, 'r') as f:
                parsed_data = json.load(f)
                if not isinstance(parsed_data, dict):
                    return False

            return True

        except Exception as e:
            logger.warning(f"Cache validation failed for {file_hash}: {e}")
            return False

    def get_cached_xml_parse(self, xml_file_path: str) -> Optional[dict]:
        """Get cached XML parsing result if available."""
        try:
            xml_path = Path(xml_file_path)
            if not xml_path.exists():
                return None

            # Create cache key based on file path and modification time
            file_stat = xml_path.stat()
            cache_key = f"{xml_path.name}_{file_stat.st_mtime}_{file_stat.st_size}"
            cache_file = self.parsed_data_dir / f"xml_{cache_key}.json"

            if cache_file.exists():
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cached_data = json.load(f)

                file_size_mb = file_stat.st_size / (1024 * 1024)
                logger.info(f"Using cached XML parse for {xml_path.name} ({file_size_mb:.1f} MB)")
                return cached_data.get('parsed_content')

            return None

        except Exception as e:
            logger.error(f"Failed to retrieve cached XML parse for {xml_file_path}: {e}")
            return None

    def cache_xml_parse(self, xml_file_path: str, parsed_content: dict) -> None:
        """Cache XML parsing result to avoid re-parsing large files."""
        try:
            xml_path = Path(xml_file_path)
            file_stat = xml_path.stat()

            # Create cache key based on file path and modification time
            cache_key = f"{xml_path.name}_{file_stat.st_mtime}_{file_stat.st_size}"
            cache_file = self.parsed_data_dir / f"xml_{cache_key}.json"

            cache_data = {
                'xml_file_path': str(xml_path),
                'file_size_mb': file_stat.st_size / (1024 * 1024),
                'parsed_content': parsed_content,
                'cached_at': datetime.now().isoformat(),
                'mtime': file_stat.st_mtime,
                'size': file_stat.st_size
            }

            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2, default=str)

            file_size_mb = file_stat.st_size / (1024 * 1024)
            logger.info(f"Cached XML parse result for {xml_path.name} ({file_size_mb:.1f} MB)")

        except Exception as e:
            logger.error(f"Failed to cache XML parse for {xml_file_path}: {e}")
            # Don't raise - caching failures shouldn't break the main flow


# Global cache service instance
cache_service = CacheService()