"""
Embeddings Service - Vector Embeddings for Semantic Search

Implements semantic search using sentence-transformers and FAISS vector store.
Enables finding similar content even with different wording.

Example:
    Query: "illegal payments"
    Finds: "cash transfer", "money exchange", "wire payment" etc.
"""

from typing import List, Dict, Any, Optional, Tuple
import logging
import os
import pickle
from pathlib import Path
import numpy as np

logger = logging.getLogger(__name__)

# Lazy imports for heavy dependencies
_sentence_transformer = None
_faiss = None


def _get_sentence_transformer():
    """Lazy load sentence-transformers to avoid import overhead."""
    global _sentence_transformer
    if _sentence_transformer is None:
        try:
            from sentence_transformers import SentenceTransformer
            # Use lightweight, fast model (384-dim embeddings, ~80MB)
            _sentence_transformer = SentenceTransformer('all-MiniLM-L6-v2')
            logger.info("Loaded sentence-transformers model: all-MiniLM-L6-v2")
        except ImportError:
            logger.error("sentence-transformers not installed. Run: pip install sentence-transformers")
            raise
    return _sentence_transformer


def _get_faiss():
    """Lazy load FAISS library."""
    global _faiss
    if _faiss is None:
        try:
            import faiss
            _faiss = faiss
            logger.info("FAISS library loaded successfully")
        except ImportError:
            logger.error("FAISS not installed. Run: pip install faiss-cpu")
            raise
    return _faiss


class EmbeddingsService:
    """
    Service for generating and managing vector embeddings for semantic search.
    
    Uses sentence-transformers (all-MiniLM-L6-v2) for embedding generation and
    FAISS for fast similarity search. Stores embeddings on disk for persistence.
    
    Architecture:
    - Each run_id has its own FAISS index stored in backend/cache/embeddings/{run_id}/
    - Embeddings are generated during ingestion and cached
    - Queries are embedded at search time and matched against cached embeddings
    """

    def __init__(self, 
                 model_name: str = "all-MiniLM-L6-v2",
                 cache_dir: str = "backend/cache/embeddings"):
        """
        Initialize embedding service.
        
        Args:
            model_name: HuggingFace model for embeddings (default: all-MiniLM-L6-v2)
                       - all-MiniLM-L6-v2: Fast, 384-dim, good quality (~80MB)
                       - all-mpnet-base-v2: Better quality, 768-dim, slower (~420MB)
            cache_dir: Directory to cache FAISS indexes and metadata
        """
        self.model_name = model_name
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger(__name__)
        
        # Lazy-loaded components
        self._model = None
        self._faiss = None
        
        # Runtime cache: {run_id: (index, metadata)}
        self._loaded_indexes: Dict[str, Tuple[Any, List[Dict]]] = {}
        
        self.logger.info(f"EmbeddingsService initialized (model: {model_name})")

    @property
    def model(self):
        """Lazy load the sentence transformer model."""
        if self._model is None:
            self._model = _get_sentence_transformer()
        return self._model

    @property
    def faiss(self):
        """Lazy load FAISS library."""
        if self._faiss is None:
            self._faiss = _get_faiss()
        return self._faiss

    def generate_embeddings(self, texts: List[str], batch_size: int = 32) -> np.ndarray:
        """
        Generate embeddings for a list of texts.
        
        Args:
            texts: List of text strings to embed
            batch_size: Batch size for encoding (default: 32)
            
        Returns:
            numpy array of shape (len(texts), embedding_dim)
            
        Example:
            >>> service = EmbeddingsService()
            >>> texts = ["Hello world", "Bitcoin transaction"]
            >>> embeddings = service.generate_embeddings(texts)
            >>> embeddings.shape
            (2, 384)
        """
        if not texts:
            return np.array([])
        
        # Filter out empty texts
        valid_texts = [t if t and t.strip() else " " for t in texts]
        
        # Encode in batches for efficiency
        embeddings = self.model.encode(
            valid_texts,
            batch_size=batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True  # L2 normalization for cosine similarity
        )
        
        self.logger.info(f"Generated {len(embeddings)} embeddings (dim: {embeddings.shape[1]})")
        return embeddings

    def create_index(self, run_id: str, texts: List[str], metadata: List[Dict[str, Any]]):
        """
        Create and store a FAISS index for a run's data.
        
        Args:
            run_id: UFDR run ID
            texts: List of text content (messages, contacts, etc.)
            metadata: List of dicts with {id, type, timestamp, content_preview, ...}
                     Must be same length as texts
                     
        Example:
            >>> service = EmbeddingsService()
            >>> texts = ["Bitcoin address: 1A1zP1eP...", "Meeting at 5pm"]
            >>> metadata = [
            ...     {"id": "msg_1", "type": "message", "sender": "+91999..."},
            ...     {"id": "msg_2", "type": "message", "sender": "+91888..."}
            ... ]
            >>> service.create_index("run_123", texts, metadata)
        """
        if len(texts) != len(metadata):
            raise ValueError(f"texts and metadata length mismatch: {len(texts)} != {len(metadata)}")
        
        if not texts:
            self.logger.warning(f"No texts to index for run_id={run_id}")
            return
        
        self.logger.info(f"Creating FAISS index for run_id={run_id} with {len(texts)} items...")
        
        # Generate embeddings
        embeddings = self.generate_embeddings(texts)
        
        # Create FAISS index (using Inner Product for normalized vectors = cosine similarity)
        dimension = embeddings.shape[1]
        index = self.faiss.IndexFlatIP(dimension)  # Inner product (cosine sim for normalized)
        index.add(embeddings.astype('float32'))
        
        # Save to disk
        run_cache_dir = self.cache_dir / run_id
        run_cache_dir.mkdir(parents=True, exist_ok=True)
        
        index_path = run_cache_dir / "faiss_index.bin"
        metadata_path = run_cache_dir / "metadata.pkl"
        
        self.faiss.write_index(index, str(index_path))
        with open(metadata_path, 'wb') as f:
            pickle.dump(metadata, f)
        
        # Cache in memory
        self._loaded_indexes[run_id] = (index, metadata)
        
        self.logger.info(f"FAISS index saved to {index_path} ({index.ntotal} vectors)")

    def load_index(self, run_id: str) -> Tuple[Any, List[Dict]]:
        """
        Load a FAISS index and metadata from disk.
        
        Args:
            run_id: UFDR run ID
            
        Returns:
            Tuple of (faiss_index, metadata_list)
            
        Raises:
            FileNotFoundError: If index doesn't exist for this run_id
        """
        # Check memory cache first
        if run_id in self._loaded_indexes:
            return self._loaded_indexes[run_id]
        
        # Load from disk
        run_cache_dir = self.cache_dir / run_id
        index_path = run_cache_dir / "faiss_index.bin"
        metadata_path = run_cache_dir / "metadata.pkl"
        
        if not index_path.exists() or not metadata_path.exists():
            raise FileNotFoundError(f"No embeddings index found for run_id={run_id}")
        
        index = self.faiss.read_index(str(index_path))
        with open(metadata_path, 'rb') as f:
            metadata = pickle.load(f)
        
        # Cache in memory
        self._loaded_indexes[run_id] = (index, metadata)
        
        self.logger.info(f"Loaded FAISS index for run_id={run_id} ({index.ntotal} vectors)")
        return index, metadata

    def semantic_search(self, 
                       query: str, 
                       run_id: str, 
                       top_k: int = 50,
                       similarity_threshold: float = 0.5) -> List[Dict[str, Any]]:
        """
        Perform semantic search using vector similarity.
        
        Args:
            query: Natural language search query
            run_id: UFDR run ID to search within
            top_k: Number of top results to return (default: 50)
            similarity_threshold: Minimum cosine similarity 0.0-1.0 (default: 0.5)
            
        Returns:
            List of result dicts with {metadata, similarity_score}
            
        Example:
            >>> service = EmbeddingsService()
            >>> results = service.semantic_search(
            ...     "illegal money transfer", 
            ...     "run_123", 
            ...     top_k=10
            ... )
            >>> for r in results:
            ...     print(f"Score: {r['similarity_score']:.3f} - {r['content_preview']}")
        """
        try:
            # Load index
            index, metadata = self.load_index(run_id)
        except FileNotFoundError:
            self.logger.warning(f"No embeddings index for run_id={run_id}, returning empty results")
            return []
        
        # Embed query
        query_embedding = self.generate_embeddings([query])[0]
        query_embedding = query_embedding.astype('float32').reshape(1, -1)
        
        # Search FAISS index
        search_k = min(top_k * 2, index.ntotal)  # Search more, then filter
        distances, indices = index.search(query_embedding, search_k)
        
        # Build results with metadata
        results = []
        for distance, idx in zip(distances[0], indices[0]):
            if idx == -1:  # FAISS returns -1 for empty slots
                continue
            
            similarity_score = float(distance)  # Already cosine sim (normalized IP)
            
            if similarity_score < similarity_threshold:
                continue
            
            result = {
                **metadata[idx],  # Unpack metadata (id, type, content, etc.)
                "similarity_score": similarity_score,
                "search_type": "semantic"
            }
            results.append(result)
        
        # Sort by similarity (descending) and limit
        results = sorted(results, key=lambda x: x['similarity_score'], reverse=True)[:top_k]
        
        self.logger.info(f"Semantic search for '{query[:50]}...' returned {len(results)} results")
        return results

    def hybrid_search(self, 
                     query: str, 
                     run_id: str, 
                     keyword_results: List[Dict[str, Any]],
                     top_k: int = 50,
                     semantic_weight: float = 0.6) -> List[Dict[str, Any]]:
        """
        Combine keyword search (MeiliSearch) + semantic search for best results.
        
        Strategy:
        - Run semantic search
        - Merge with keyword_results
        - Re-rank using weighted score: semantic_weight * semantic + (1-weight) * keyword
        - Deduplicate by message_id/content
        
        Args:
            query: Search query
            run_id: UFDR run ID
            keyword_results: Results from MeiliSearch/PostgreSQL keyword search
                            Each should have {id, type, content, keyword_score (0-1)}
            top_k: Final number of results to return
            semantic_weight: Weight for semantic score (default: 0.6)
            
        Returns:
            Ranked and merged results with combined scores
            
        Example:
            >>> keyword_res = [{"id": "msg_1", "content": "BTC wallet", "keyword_score": 0.9}]
            >>> results = service.hybrid_search("crypto", "run_123", keyword_res, top_k=20)
        """
        # Get semantic results
        semantic_results = self.semantic_search(query, run_id, top_k=top_k * 2)
        
        # Merge results by ID
        merged: Dict[str, Dict[str, Any]] = {}
        
        # Add keyword results
        for result in keyword_results:
            result_id = result.get('id') or result.get('message_id') or result.get('call_id')
            if not result_id:
                continue
            
            merged[str(result_id)] = {
                **result,
                'keyword_score': result.get('keyword_score', 1.0),
                'semantic_score': 0.0,
                'combined_score': (1 - semantic_weight) * result.get('keyword_score', 1.0)
            }
        
        # Add/merge semantic results
        for result in semantic_results:
            result_id = result.get('id') or result.get('message_id') or result.get('call_id')
            if not result_id:
                continue
            
            result_id_str = str(result_id)
            if result_id_str in merged:
                # Both keyword and semantic found this - boost score
                merged[result_id_str]['semantic_score'] = result['similarity_score']
                merged[result_id_str]['combined_score'] = (
                    semantic_weight * result['similarity_score'] +
                    (1 - semantic_weight) * merged[result_id_str]['keyword_score']
                )
            else:
                # Only semantic found this
                merged[result_id_str] = {
                    **result,
                    'keyword_score': 0.0,
                    'semantic_score': result['similarity_score'],
                    'combined_score': semantic_weight * result['similarity_score']
                }
        
        # Sort by combined score and return top_k
        final_results = sorted(merged.values(), key=lambda x: x['combined_score'], reverse=True)[:top_k]
        
        self.logger.info(f"Hybrid search returned {len(final_results)} results "
                        f"(keyword: {len(keyword_results)}, semantic: {len(semantic_results)})")
        return final_results

    def index_exists(self, run_id: str) -> bool:
        """Check if an index exists for a given run_id."""
        run_cache_dir = self.cache_dir / run_id
        index_path = run_cache_dir / "faiss_index.bin"
        return index_path.exists()

    def delete_index(self, run_id: str):
        """Delete cached index for a run_id."""
        run_cache_dir = self.cache_dir / run_id
        if run_cache_dir.exists():
            import shutil
            shutil.rmtree(run_cache_dir)
            self.logger.info(f"Deleted embeddings cache for run_id={run_id}")
        
        # Remove from memory cache
        if run_id in self._loaded_indexes:
            del self._loaded_indexes[run_id]
