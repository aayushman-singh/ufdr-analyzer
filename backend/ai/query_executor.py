from typing import Dict, List, Any, Optional
import logging
from sqlmodel import Session, select, or_
from meilisearch import Client as MeiliClient
from datetime import datetime
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from db_setup import Message, Call, Contact, Media, Run, AleappArtifact
from ai.embeddings import EmbeddingsService

logger = logging.getLogger(__name__)

# App name mappings - handles variations and common aliases
APP_NAME_MAPPING = {
    # WhatsApp variations
    "whatsapp": ["WhatsApp", "whatsapp", "WA", "com.whatsapp"],
    "wa": ["WhatsApp", "whatsapp", "WA", "com.whatsapp"],
    # Instagram variations
    "instagram": ["Instagram", "instagram", "IG", "com.instagram"],
    "ig": ["Instagram", "instagram", "IG", "com.instagram"],
    "insta": ["Instagram", "instagram", "IG", "com.instagram"],
    # Facebook Messenger
    "messenger": ["Messenger", "messenger", "facebook messenger", "com.facebook.orca"],
    "facebook messenger": [
        "Messenger",
        "messenger",
        "facebook messenger",
        "com.facebook.orca",
    ],
    # Snapchat
    "snapchat": ["Snapchat", "snapchat", "com.snapchat"],
    "snap": ["Snapchat", "snapchat", "com.snapchat"],
    # Telegram
    "telegram": ["Telegram", "telegram", "org.telegram"],
    # Signal
    "signal": ["Signal", "signal", "org.thoughtcrime.securesms"],
    # Chrome/Browser
    "chrome": ["Chrome", "chrome", "browser", "com.android.chrome"],
    "browser": ["Chrome", "chrome", "browser", "com.android.chrome"],
    # SMS/Messages
    "sms": ["SMS", "sms", "messages", "text messages"],
    "text": ["SMS", "sms", "messages", "text messages"],
    "messages": ["SMS", "sms", "messages", "text messages"],
}


class QueryExecutor:
    """
    Executes structured queries against PostgreSQL, MeiliSearch, and semantic search.
    Combines results from multiple sources and ranks by relevance.
    """

    def __init__(self, session: Session, meili_client: Optional[MeiliClient] = None):
        """
        Initialize query executor.

        Args:
            session: SQLModel database session
            meili_client: MeiliSearch client (optional)
        """
        self.session = session
        self.meili_client = meili_client
        self.embeddings_service = EmbeddingsService()
        self.logger = logging.getLogger(__name__)

    def _bounded_int(self, value: Any, *, name: str, minimum: int, maximum: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError) as e:
            raise ValueError(f"{name} must be an integer") from e
        if parsed < minimum or parsed > maximum:
            raise ValueError(f"{name} must be between {minimum} and {maximum}")
        return parsed

    def _parse_iso_datetime(self, datetime_str: str) -> datetime:
        """
        Parse ISO datetime string, handling timezone indicators like 'Z'.
        """
        try:
            # Remove 'Z' suffix and replace with '+00:00' for UTC
            if datetime_str.endswith("Z"):
                datetime_str = datetime_str[:-1] + "+00:00"
            return datetime.fromisoformat(datetime_str)
        except ValueError as e:
            logger.error("Failed to parse datetime %r: %s", datetime_str, e)
            raise ValueError(f"invalid ISO datetime {datetime_str!r}") from e

    def execute(self, run_id: str, structured_params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute structured query parameters against data sources.

        Supports three search modes:
        1. keyword: Traditional SQL/MeiliSearch keyword matching
        2. semantic: Vector similarity search using embeddings
        3. hybrid: Combines keyword + semantic for best results (recommended)

        Args:
            run_id: UFDR run ID to query against
            structured_params: LLM-generated structured parameters

        Returns:
            Combined and ranked results
        """
        intent = structured_params.get("intent", "keyword_search")
        if "target_tables" not in structured_params:
            raise ValueError("target_tables is required")
        target_tables = structured_params["target_tables"]
        if not isinstance(target_tables, list) or not target_tables:
            raise ValueError("target_tables must be a non-empty list")
        allowed_tables = {
            "messages",
            "calls",
            "contacts",
            "media",
            "aleapp_artifacts",
            "device_info",
        }
        unknown_tables = sorted(set(target_tables) - allowed_tables)
        if unknown_tables:
            raise ValueError(f"unsupported target_tables: {unknown_tables}")
        filters = structured_params.get("filters", {})
        keywords = structured_params.get("keywords", [])
        if "search_type" not in structured_params:
            raise ValueError("search_type is required")
        search_type = structured_params["search_type"]
        if search_type not in {"keyword", "semantic", "hybrid"}:
            raise ValueError(f"unsupported search_type: {search_type!r}")
        limit = self._bounded_int(
            structured_params.get("limit", 100), name="limit", minimum=1, maximum=500
        )
        offset = self._bounded_int(
            structured_params.get("offset", 0), name="offset", minimum=0, maximum=100000
        )

        results = []

        # Determine if we should use semantic search
        use_semantic = search_type in ["semantic", "hybrid"]
        use_keyword = search_type in ["keyword", "hybrid"]

        # Query construction (what to search for)
        query_text = (
            " ".join(keywords) if keywords else structured_params.get("query", "")
        )

        # Keyword search (traditional SQL + MeiliSearch)
        if use_keyword:
            # Execute against each target table
            for table in target_tables:
                if table == "messages":
                    results.extend(
                        self._search_messages(run_id, keywords, filters, limit, offset)
                    )
                elif table == "calls":
                    results.extend(self._search_calls(run_id, filters, limit, offset))
                elif table == "contacts":
                    results.extend(
                        self._search_contacts(run_id, keywords, filters, limit, offset)
                    )
                elif table == "media":
                    results.extend(self._search_media(run_id, filters, limit, offset))
                elif table == "aleapp_artifacts":
                    results.extend(
                        self._search_aleapp_artifacts(
                            run_id, keywords, filters, limit, offset
                        )
                    )
                elif table == "device_info":
                    results.extend(
                        self._search_device_info(
                            run_id, keywords, filters, limit, offset
                        )
                    )

            # Optionally search MeiliSearch for full-text
            if keywords:
                meili_results = self._search_meilisearch(run_id, keywords, limit)
                results.extend(meili_results)

        # Semantic search (vector similarity)
        if use_semantic and query_text:
            semantic_results = self._search_semantic(run_id, query_text, filters, limit)

            if search_type == "hybrid" and results:
                # Hybrid: merge keyword + semantic results
                self.logger.info(
                    f"Running hybrid search (keyword: {len(results)}, semantic: {len(semantic_results)})"
                )
                results = self._merge_hybrid_results(results, semantic_results)
            else:
                # Pure semantic search
                results.extend(semantic_results)

        # Deduplicate and rank
        results = self._deduplicate_results(results)
        results = self._rank_results(results, structured_params)

        return {
            "total_results": len(results),
            "results": results[:limit],
            "intent": intent,
            "search_type": search_type,
            "query_params": structured_params,
        }

    def _search_messages(
        self,
        run_id: str,
        keywords: List[str],
        filters: Dict[str, Any],
        limit: int,
        offset: int,
    ) -> List[Dict[str, Any]]:
        """Search messages table with filters."""
        query = select(Message).where(Message.run_id == run_id)

        # Apply keyword filters
        if keywords:
            keyword_filters = [Message.content.ilike(f"%{kw}%") for kw in keywords]
            query = query.where(or_(*keyword_filters))

        # Apply phone number filters
        if filters.get("phone_numbers"):
            phone_filters = []
            for phone in filters["phone_numbers"]:
                phone_filters.append(
                    or_(
                        Message.sender.ilike(f"%{phone}%"),
                        Message.receiver.ilike(f"%{phone}%"),
                    )
                )
            query = query.where(or_(*phone_filters))

        # Apply time range filters
        if filters.get("time_range"):
            if filters["time_range"].get("start"):
                start_time = self._parse_iso_datetime(filters["time_range"]["start"])
                query = query.where(Message.timestamp >= start_time)
            if filters["time_range"].get("end"):
                end_time = self._parse_iso_datetime(filters["time_range"]["end"])
                query = query.where(Message.timestamp <= end_time)

        query = (
            query.order_by(Message.timestamp.desc(), Message.id)
            .offset(offset)
            .limit(limit)
        )
        messages = self.session.exec(query).all()

        return [
            {
                "type": "message",
                "id": str(msg.id),
                "sender": msg.sender,
                "receiver": msg.receiver,
                "content": msg.content,
                "timestamp": msg.timestamp.isoformat(),
                "relevance_score": 1.0,  # Will be adjusted by ranking
            }
            for msg in messages
        ]

    def _search_calls(
        self, run_id: str, filters: Dict[str, Any], limit: int, offset: int
    ) -> List[Dict[str, Any]]:
        """Search calls table with filters."""
        query = select(Call).where(Call.run_id == run_id)

        # Apply phone number filters
        if filters.get("phone_numbers"):
            phone_filters = []
            for phone in filters["phone_numbers"]:
                phone_filters.append(
                    or_(
                        Call.caller.ilike(f"%{phone}%"),
                        Call.receiver.ilike(f"%{phone}%"),
                    )
                )
            query = query.where(or_(*phone_filters))

        # Apply time range filters
        if filters.get("time_range"):
            if filters["time_range"].get("start"):
                start_time = self._parse_iso_datetime(filters["time_range"]["start"])
                query = query.where(Call.timestamp >= start_time)
            if filters["time_range"].get("end"):
                end_time = self._parse_iso_datetime(filters["time_range"]["end"])
                query = query.where(Call.timestamp <= end_time)

        query = (
            query.order_by(Call.timestamp.desc(), Call.id).offset(offset).limit(limit)
        )
        calls = self.session.exec(query).all()

        return [
            {
                "type": "call",
                "id": str(call.id),
                "caller": call.caller,
                "receiver": call.receiver,
                "timestamp": call.timestamp.isoformat(),
                "duration": call.duration,
                "relevance_score": 1.0,
            }
            for call in calls
        ]

    def _search_contacts(
        self,
        run_id: str,
        keywords: List[str],
        filters: Dict[str, Any],
        limit: int,
        offset: int,
    ) -> List[Dict[str, Any]]:
        """Search contacts table with filters."""
        query = select(Contact).where(Contact.run_id == run_id)

        # Apply keyword filters (name search)
        if keywords:
            keyword_filters = [Contact.name.ilike(f"%{kw}%") for kw in keywords]
            query = query.where(or_(*keyword_filters))

        # Apply phone number filters
        if filters.get("phone_numbers"):
            phone_filters = [
                Contact.number.ilike(f"%{phone}%") for phone in filters["phone_numbers"]
            ]
            query = query.where(or_(*phone_filters))

        query = query.order_by(Contact.name, Contact.id).offset(offset).limit(limit)
        contacts = self.session.exec(query).all()

        return [
            {
                "type": "contact",
                "id": str(contact.id),
                "name": contact.name,
                "number": contact.number,
                "relevance_score": 1.0,
            }
            for contact in contacts
        ]

    def _search_media(
        self, run_id: str, filters: Dict[str, Any], limit: int, offset: int
    ) -> List[Dict[str, Any]]:
        """Search media table with filters."""
        query = select(Media).where(Media.run_id == run_id)

        # Apply media type filter
        if filters.get("media_type"):
            query = query.where(Media.media_type == filters["media_type"])

        query = (
            query.order_by(Media.original_path, Media.id).offset(offset).limit(limit)
        )
        media_items = self.session.exec(query).all()

        return [
            {
                "type": "media",
                "id": str(media.id),
                "original_path": media.original_path,
                "storage_path": media.storage_path,
                "media_type": media.media_type,
                "relevance_score": 1.0,
            }
            for media in media_items
        ]

    def _search_aleapp_artifacts(
        self,
        run_id: str,
        keywords: List[str],
        filters: Dict[str, Any],
        limit: int,
        offset: int,
    ) -> List[Dict[str, Any]]:
        """
        Search ALEAPP artifacts for app-specific data.
        This is the key to intelligent app queries like "WhatsApp messages".
        """
        query = select(AleappArtifact).where(AleappArtifact.run_id == run_id)

        # App-specific filter (e.g., "WhatsApp", "Instagram")
        if filters.get("app_name"):
            app_name = filters["app_name"].lower()

            # Map app name to all variations (handles "whatsapp", "wa", "WhatsApp", etc.)
            app_variations = APP_NAME_MAPPING.get(app_name, [app_name])
            self.logger.info(
                f"Searching ALEAPP artifacts for app: {app_name} (variations: {app_variations})"
            )

            # Build query for all app variations
            app_filters = []
            for variation in app_variations:
                app_filters.append(AleappArtifact.filename.ilike(f"%{variation}%"))
                app_filters.append(AleappArtifact.category.ilike(f"%{variation}%"))
                app_filters.append(AleappArtifact.file_path.ilike(f"%{variation}%"))

            if app_filters:
                query = query.where(or_(*app_filters))

        # Artifact category filter (e.g., "messages", "calls", "media")
        if filters.get("artifact_category"):
            category = filters["artifact_category"]
            if category != "any":
                self.logger.info(f"Filtering by artifact category: {category}")
                query = query.where(
                    or_(
                        AleappArtifact.category.ilike(f"%{category}%"),
                        AleappArtifact.filename.ilike(f"%{category}%"),
                    )
                )

        # Keyword filter (search in filename, category, and data)
        if keywords:
            keyword_filters = []
            for kw in keywords:
                keyword_filters.append(
                    or_(
                        AleappArtifact.filename.ilike(f"%{kw}%"),
                        AleappArtifact.category.ilike(f"%{kw}%"),
                        AleappArtifact.data.ilike(f"%{kw}%")
                        if AleappArtifact.data
                        else False,
                    )
                )
            if keyword_filters:
                query = query.where(or_(*keyword_filters))

        query = (
            query.order_by(AleappArtifact.created_at.desc(), AleappArtifact.id)
            .offset(offset)
            .limit(limit)
        )
        artifacts = self.session.exec(query).all()
        self.logger.info(f"Found {len(artifacts)} ALEAPP artifacts")

        results = []
        for artifact in artifacts:
            # Parse JSON data if available
            artifact_data = None
            if artifact.data:
                try:
                    import json

                    artifact_data = json.loads(artifact.data)
                except Exception as e:
                    self.logger.exception(
                        "ALEAPP artifact JSON parse failed",
                        extra={
                            "artifact_id": str(artifact.id),
                            "run_id": str(artifact.run_id),
                            "filename": artifact.filename,
                        },
                    )
                    raise ValueError(
                        f"invalid ALEAPP artifact JSON for artifact {artifact.id}"
                    ) from e

            result = {
                "type": "aleapp_artifact",
                "id": str(artifact.id),
                "artifact_type": artifact.artifact_type,
                "filename": artifact.filename,
                "file_path": artifact.file_path,
                "category": artifact.category,
                "row_count": artifact.row_count,
                "relevance_score": 1.5,  # Boost ALEAPP artifacts - they're app-specific!
                "created_at": artifact.created_at.isoformat()
                if artifact.created_at
                else None,
            }

            # Add sample data if available
            if artifact_data:
                if isinstance(artifact_data, list) and len(artifact_data) > 0:
                    result["sample_data"] = artifact_data[:5]  # First 5 rows
                elif isinstance(artifact_data, dict):
                    result["data_summary"] = {
                        k: str(v)[:100] for k, v in list(artifact_data.items())[:5]
                    }

            results.append(result)

        return results

    def _search_device_info(
        self,
        run_id: str,
        keywords: List[str],
        filters: Dict[str, Any],
        limit: int,
        offset: int,
    ) -> List[Dict[str, Any]]:
        """
        Search for device information across available data sources.
        Since we don't have a dedicated device_info table, we search:
        1. ALEAPP artifacts for system information
        2. Media files for system-related files
        3. Run metadata for extraction information
        """
        results = []

        # Search ALEAPP artifacts for system/device info
        aleapp_results = self._search_aleapp_artifacts(
            run_id, keywords, filters, limit, offset
        )
        for result in aleapp_results:
            # Check if this artifact contains device info
            if any(
                keyword in result.get("filename", "").lower()
                for keyword in ["system", "device", "android", "version", "build"]
            ):
                result["type"] = "device_info"
                result["info_type"] = "aleapp_artifact"
                results.append(result)

        # Search media files for system-related files
        media_results = self._search_media(run_id, filters, limit, offset)
        for result in media_results:
            file_path = result.get("original_path", "").lower()
            if any(
                keyword in file_path
                for keyword in ["system", "build", "version", "android", "prop"]
            ):
                result["type"] = "device_info"
                result["info_type"] = "system_file"
                results.append(result)

        # Add run metadata as device info. Any DB failure should abort the query;
        # returning partial device information would misstate the evidence set.
        run = self.session.get(Run, run_id)
        if run:
            device_info = {
                "type": "device_info",
                "info_type": "extraction_metadata",
                "id": str(run.id),
                "file_name": run.ufdr_file_name,
                "status": run.status,
                "start_time": run.start_time.isoformat() if run.start_time else None,
                "end_time": run.end_time.isoformat() if run.end_time else None,
                "extraction_metadata": run.extraction_metadata,
                "relevance_score": 1.0,
            }
            results.append(device_info)

        return results

    def _search_meilisearch(
        self, run_id: str, keywords: List[str], limit: int
    ) -> List[Dict[str, Any]]:
        """Search MeiliSearch for full-text search."""
        if not self.meili_client:
            raise RuntimeError(
                f"MeiliSearch client is unavailable for keyword search on run {run_id}"
            )

        try:
            # Search messages index
            query_string = " ".join(keywords)
            search_results = self.meili_client.index("messages").search(
                query_string, {"filter": f'run_id = "{run_id}"', "limit": limit}
            )

            return [
                {
                    "type": "message",
                    "id": hit.get("id"),
                    "sender": hit.get("sender"),
                    "receiver": hit.get("receiver"),
                    "content": hit.get("content"),
                    "timestamp": hit.get("timestamp"),
                    "relevance_score": hit.get(
                        "_rankingScore", 0.5
                    ),  # MeiliSearch score
                }
                for hit in search_results.get("hits", [])
            ]

        except Exception as e:
            self.logger.exception(
                "MeiliSearch query failed",
                extra={"run_id": str(run_id), "keywords": keywords},
            )
            raise RuntimeError(f"MeiliSearch query failed for run {run_id}") from e

    def _search_semantic(
        self, run_id: str, query_text: str, filters: Dict[str, Any], limit: int
    ) -> List[Dict[str, Any]]:
        """
        Perform semantic search using vector embeddings.

        Args:
            run_id: UFDR run ID
            query_text: Natural language query
            filters: Additional filters (currently not applied to semantic search)

        Returns:
            List of semantically similar results
        """
        try:
            # Check if embeddings exist for this run
            if not self.embeddings_service.index_exists(run_id):
                raise RuntimeError(f"No embeddings index exists for run {run_id}")

            # Perform semantic search
            semantic_results = self.embeddings_service.semantic_search(
                query=query_text,
                run_id=run_id,
                top_k=limit,
                similarity_threshold=0.4,  # Lower threshold for broader recall
            )

            # Convert to standard result format
            standardized_results = []
            for result in semantic_results:
                standardized_results.append(
                    {
                        "type": result.get("type", "message"),
                        "id": result.get("id"),
                        "sender": result.get("sender"),
                        "receiver": result.get("receiver"),
                        "content": result.get("content"),
                        "content_preview": result.get("content_preview"),
                        "timestamp": result.get("timestamp"),
                        "relevance_score": result.get("similarity_score", 0.5),
                        "search_method": "semantic",
                    }
                )

            self.logger.info(
                f"Semantic search returned {len(standardized_results)} results"
            )
            return standardized_results

        except Exception as e:
            self.logger.exception(
                "Semantic search failed",
                extra={"run_id": str(run_id), "query_text": query_text},
            )
            raise RuntimeError(f"Semantic search failed for run {run_id}") from e

    def _merge_hybrid_results(
        self, keyword_results: List[Dict], semantic_results: List[Dict]
    ) -> List[Dict]:
        """
        Merge keyword and semantic search results with weighted scoring.

        Args:
            keyword_results: Results from keyword search
            semantic_results: Results from semantic search

        Returns:
            Merged results with combined scores
        """
        # Weight for combining scores (60% semantic, 40% keyword)
        semantic_weight = 0.6
        keyword_weight = 0.4

        merged = {}

        # Add keyword results
        for result in keyword_results:
            result_id = result.get("id")
            if result_id:
                result["keyword_score"] = result.get("relevance_score", 1.0)
                result["semantic_score"] = 0.0
                result["combined_score"] = keyword_weight * result["keyword_score"]
                result["search_method"] = "keyword"
                merged[result_id] = result

        # Add/merge semantic results
        for result in semantic_results:
            result_id = result.get("id")
            if not result_id:
                continue

            if result_id in merged:
                # Found by both - boost score
                merged[result_id]["semantic_score"] = result.get("relevance_score", 0.5)
                merged[result_id]["combined_score"] = (
                    semantic_weight * merged[result_id]["semantic_score"]
                    + keyword_weight * merged[result_id]["keyword_score"]
                )
                merged[result_id]["search_method"] = "hybrid"
            else:
                # Only found by semantic
                result["keyword_score"] = 0.0
                result["semantic_score"] = result.get("relevance_score", 0.5)
                result["combined_score"] = semantic_weight * result["semantic_score"]
                result["search_method"] = "semantic"
                merged[result_id] = result

        return list(merged.values())

    def _deduplicate_results(
        self, results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Remove duplicate results based on type and ID."""
        seen = set()
        unique_results = []

        for result in results:
            key = (result.get("type"), result.get("id"))
            if key not in seen:
                seen.add(key)
                unique_results.append(result)

        return unique_results

    def _rank_results(
        self, results: List[Dict[str, Any]], params: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Rank results by relevance.
        Factors: keyword matches, entity matches, recency, relevance score.
        """
        keywords = params.get("keywords", [])
        entities = params.get("entities", [])

        for result in results:
            score = result.get("relevance_score", 0.5)

            # Boost for keyword matches in content
            if result.get("content"):
                keyword_count = sum(
                    1 for kw in keywords if kw.lower() in result["content"].lower()
                )
                score += keyword_count * 0.2

            # Boost for entity matches
            for entity in entities:
                entity_value = entity.get("value", "").lower()
                if entity_value in str(result).lower():
                    score += 0.3

            # Boost for recency (if timestamp available)
            if result.get("timestamp"):
                ts = self._parse_iso_datetime(result["timestamp"])
                days_old = (datetime.now() - ts).days
                recency_boost = max(0, 1 - (days_old / 365))  # Decay over 1 year
                score += recency_boost * 0.1

            result["relevance_score"] = score

        # Sort by relevance score descending
        results.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)

        return results
