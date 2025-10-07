from typing import Dict, List, Any, Optional
import logging
from sqlmodel import Session, select, or_, and_, func
from meilisearch import Client as MeiliClient
from datetime import datetime
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from db_setup import Message, Call, Contact, Media, Run
from ai.embeddings import EmbeddingsService

logger = logging.getLogger(__name__)


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
        target_tables = structured_params.get("target_tables", ["messages"])
        filters = structured_params.get("filters", {})
        keywords = structured_params.get("keywords", [])
        search_type = structured_params.get("search_type", "hybrid")  # "keyword", "semantic", or "hybrid"

        results = []

        # Determine if we should use semantic search
        use_semantic = search_type in ["semantic", "hybrid"]
        use_keyword = search_type in ["keyword", "hybrid"]
        
        # Query construction (what to search for)
        query_text = " ".join(keywords) if keywords else structured_params.get("query", "")

        # Keyword search (traditional SQL + MeiliSearch)
        if use_keyword:
            # Execute against each target table
            for table in target_tables:
                if table == "messages":
                    results.extend(self._search_messages(run_id, keywords, filters))
                elif table == "calls":
                    results.extend(self._search_calls(run_id, filters))
                elif table == "contacts":
                    results.extend(self._search_contacts(run_id, keywords, filters))
                elif table == "media":
                    results.extend(self._search_media(run_id, filters))

            # Optionally search MeiliSearch for full-text
            if self.meili_client and keywords:
                meili_results = self._search_meilisearch(run_id, keywords)
                results.extend(meili_results)
        
        # Semantic search (vector similarity)
        if use_semantic and query_text:
            semantic_results = self._search_semantic(run_id, query_text, filters)
            
            if search_type == "hybrid" and results:
                # Hybrid: merge keyword + semantic results
                self.logger.info(f"Running hybrid search (keyword: {len(results)}, semantic: {len(semantic_results)})")
                results = self._merge_hybrid_results(results, semantic_results)
            else:
                # Pure semantic search
                results.extend(semantic_results)

        # Deduplicate and rank
        results = self._deduplicate_results(results)
        results = self._rank_results(results, structured_params)

        return {
            "total_results": len(results),
            "results": results[:100],  # Limit to top 100
            "intent": intent,
            "search_type": search_type,
            "query_params": structured_params
        }

    def _search_messages(self, run_id: str, keywords: List[str], filters: Dict[str, Any]) -> List[Dict[str, Any]]:
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
                phone_filters.append(or_(
                    Message.sender.ilike(f"%{phone}%"),
                    Message.receiver.ilike(f"%{phone}%")
                ))
            query = query.where(or_(*phone_filters))

        # Apply time range filters
        if filters.get("time_range"):
            if filters["time_range"].get("start"):
                query = query.where(Message.timestamp >= datetime.fromisoformat(filters["time_range"]["start"]))
            if filters["time_range"].get("end"):
                query = query.where(Message.timestamp <= datetime.fromisoformat(filters["time_range"]["end"]))

        messages = self.session.exec(query).all()

        return [{
            "type": "message",
            "id": str(msg.id),
            "sender": msg.sender,
            "receiver": msg.receiver,
            "content": msg.content,
            "timestamp": msg.timestamp.isoformat(),
            "relevance_score": 1.0  # Will be adjusted by ranking
        } for msg in messages]

    def _search_calls(self, run_id: str, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Search calls table with filters."""
        query = select(Call).where(Call.run_id == run_id)

        # Apply phone number filters
        if filters.get("phone_numbers"):
            phone_filters = []
            for phone in filters["phone_numbers"]:
                phone_filters.append(or_(
                    Call.caller.ilike(f"%{phone}%"),
                    Call.receiver.ilike(f"%{phone}%")
                ))
            query = query.where(or_(*phone_filters))

        # Apply time range filters
        if filters.get("time_range"):
            if filters["time_range"].get("start"):
                query = query.where(Call.timestamp >= datetime.fromisoformat(filters["time_range"]["start"]))
            if filters["time_range"].get("end"):
                query = query.where(Call.timestamp <= datetime.fromisoformat(filters["time_range"]["end"]))

        calls = self.session.exec(query).all()

        return [{
            "type": "call",
            "id": str(call.id),
            "caller": call.caller,
            "receiver": call.receiver,
            "timestamp": call.timestamp.isoformat(),
            "duration": call.duration,
            "relevance_score": 1.0
        } for call in calls]

    def _search_contacts(self, run_id: str, keywords: List[str], filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Search contacts table with filters."""
        query = select(Contact).where(Contact.run_id == run_id)

        # Apply keyword filters (name search)
        if keywords:
            keyword_filters = [Contact.name.ilike(f"%{kw}%") for kw in keywords]
            query = query.where(or_(*keyword_filters))

        # Apply phone number filters
        if filters.get("phone_numbers"):
            phone_filters = [Contact.number.ilike(f"%{phone}%") for phone in filters["phone_numbers"]]
            query = query.where(or_(*phone_filters))

        contacts = self.session.exec(query).all()

        return [{
            "type": "contact",
            "id": str(contact.id),
            "name": contact.name,
            "number": contact.number,
            "relevance_score": 1.0
        } for contact in contacts]

    def _search_media(self, run_id: str, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Search media table with filters."""
        query = select(Media).where(Media.run_id == run_id)

        # Apply media type filter
        if filters.get("media_type"):
            query = query.where(Media.media_type == filters["media_type"])

        media_items = self.session.exec(query).all()

        return [{
            "type": "media",
            "id": str(media.id),
            "original_path": media.original_path,
            "storage_path": media.storage_path,
            "media_type": media.media_type,
            "relevance_score": 1.0
        } for media in media_items]

    def _search_meilisearch(self, run_id: str, keywords: List[str]) -> List[Dict[str, Any]]:
        """Search MeiliSearch for full-text search."""
        if not self.meili_client:
            return []

        try:
            # Search messages index
            query_string = " ".join(keywords)
            search_results = self.meili_client.index("messages").search(
                query_string,
                {
                    "filter": f"run_id = {run_id}",
                    "limit": 50
                }
            )

            return [{
                "type": "message",
                "id": hit.get("id"),
                "sender": hit.get("sender"),
                "receiver": hit.get("receiver"),
                "content": hit.get("content"),
                "timestamp": hit.get("timestamp"),
                "relevance_score": hit.get("_rankingScore", 0.5)  # MeiliSearch score
            } for hit in search_results.get("hits", [])]

        except Exception as e:
            self.logger.warning(f"MeiliSearch query failed: {e}")
            return []

    def _search_semantic(self, run_id: str, query_text: str, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
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
                self.logger.info(f"No embeddings index for run {run_id}, skipping semantic search")
                return []
            
            # Perform semantic search
            semantic_results = self.embeddings_service.semantic_search(
                query=query_text,
                run_id=run_id,
                top_k=50,
                similarity_threshold=0.4  # Lower threshold for broader recall
            )
            
            # Convert to standard result format
            standardized_results = []
            for result in semantic_results:
                standardized_results.append({
                    "type": result.get("type", "message"),
                    "id": result.get("id"),
                    "sender": result.get("sender"),
                    "receiver": result.get("receiver"),
                    "content": result.get("content"),
                    "content_preview": result.get("content_preview"),
                    "timestamp": result.get("timestamp"),
                    "relevance_score": result.get("similarity_score", 0.5),
                    "search_method": "semantic"
                })
            
            self.logger.info(f"Semantic search returned {len(standardized_results)} results")
            return standardized_results
            
        except Exception as e:
            self.logger.error(f"Semantic search failed: {e}")
            return []

    def _merge_hybrid_results(self, keyword_results: List[Dict], semantic_results: List[Dict]) -> List[Dict]:
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
                    semantic_weight * merged[result_id]["semantic_score"] +
                    keyword_weight * merged[result_id]["keyword_score"]
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

    def _deduplicate_results(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove duplicate results based on type and ID."""
        seen = set()
        unique_results = []

        for result in results:
            key = (result.get("type"), result.get("id"))
            if key not in seen:
                seen.add(key)
                unique_results.append(result)

        return unique_results

    def _rank_results(self, results: List[Dict[str, Any]], params: Dict[str, Any]) -> List[Dict[str, Any]]:
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
                keyword_count = sum(1 for kw in keywords if kw.lower() in result["content"].lower())
                score += keyword_count * 0.2

            # Boost for entity matches
            for entity in entities:
                entity_value = entity.get("value", "").lower()
                if entity_value in str(result).lower():
                    score += 0.3

            # Boost for recency (if timestamp available)
            if result.get("timestamp"):
                try:
                    ts = datetime.fromisoformat(result["timestamp"])
                    days_old = (datetime.now() - ts).days
                    recency_boost = max(0, 1 - (days_old / 365))  # Decay over 1 year
                    score += recency_boost * 0.1
                except:
                    pass

            result["relevance_score"] = score

        # Sort by relevance score descending
        results.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)

        return results