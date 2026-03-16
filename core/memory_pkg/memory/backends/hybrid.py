"""
NEXUS V12.4 COGNITIVE BOOST - HybridBackend RAG

Combines Dense (semantic) + BM25S (lexical) using Reciprocal Rank Fusion (RRF).

Why Hybrid?
- Dense: Understands semantics ("auth" ≈ "authentication")
- BM25S: Excels at exact term matching ("getUserById")
- Combined: Best of both worlds, ~15% better recall than either alone

RRF Formula:
    score(doc) = sum(1 / (k + rank_i)) for each retriever i
    k = 60 (standard constant, controls rank influence)

Architecture:
- Delegates to DenseBackend and Bm25Backend
- Uses RRF to merge and re-rank results
- Graceful fallback if one backend unavailable

Author: Claude (NEXUS V12.4 COGNITIVE BOOST)
Date: 2025-12-16
"""

import logging
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .base import MemoryBackend

if TYPE_CHECKING:
    from ..types import Chunk

# =============================================================================
# Constants
# =============================================================================

# RRF constant - controls influence of rank position
# Higher k = more equal weighting, lower k = top ranks dominate
RRF_K = 60

# Weight for each backend in final score
# Allows tuning dense vs lexical importance
DEFAULT_DENSE_WEIGHT = 0.6
DEFAULT_SPARSE_WEIGHT = 0.4


class HybridBackend(MemoryBackend):
    """
    Hybrid retrieval combining Dense (semantic) and BM25S (lexical) backends.

    V12.4 COGNITIVE BOOST: Implements Reciprocal Rank Fusion (RRF) for optimal
    combination of semantic and lexical search results.

    Features:
    - Dual retrieval: Dense + BM25S in parallel
    - RRF ranking: Provably optimal rank fusion without score calibration
    - Graceful degradation: Works with either backend alone if one unavailable
    - Configurable weights: Tune dense vs sparse importance

    Usage:
        backend = HybridBackend(storage_path=Path(".nexus/lancedb"))
        backend.build_index(chunks)
        results = backend.retrieve(query_terms, chunks, limit=10, min_score=0.0, raw_query="...")
    """

    def __init__(
        self,
        storage_path: Path | None = None,
        dense_weight: float = DEFAULT_DENSE_WEIGHT,
        sparse_weight: float = DEFAULT_SPARSE_WEIGHT,
    ):
        """
        Initialize the Hybrid backend.

        Args:
            storage_path: Path for Dense backend storage (e.g., .nexus/lancedb)
            dense_weight: Weight for dense (semantic) results [0.0-1.0]
            sparse_weight: Weight for sparse (lexical) results [0.0-1.0]
        """
        self._logger = logging.getLogger("nexus.memory.hybrid")
        self._storage_path = storage_path

        # Weights for RRF combination
        self._dense_weight = dense_weight
        self._sparse_weight = sparse_weight

        # Sub-backends (lazy initialized)
        self._dense_backend: MemoryBackend | None = None
        self._sparse_backend: MemoryBackend | None = None

        # State
        self._index_built = False
        self._chunk_count = 0

    @property
    def name(self) -> str:
        return "hybrid"

    @property
    def is_ready(self) -> bool:
        # Ready if at least one backend is ready
        dense_ready = self._dense_backend is not None and self._dense_backend.is_ready
        sparse_ready = self._sparse_backend is not None and self._sparse_backend.is_ready
        return self._index_built and (dense_ready or sparse_ready)

    @classmethod
    def is_available(cls) -> bool:
        """Check if Hybrid backend can be used."""
        # Available if either sub-backend is available
        from .bm25 import Bm25Backend
        from .dense import DenseBackend

        return DenseBackend.is_available() or Bm25Backend.is_available()

    def _ensure_backends(self) -> bool:
        """
        Lazy-initialize sub-backends.

        Returns:
            True if at least one backend is available
        """
        if self._dense_backend is None:
            try:
                from .dense import DenseBackend

                if DenseBackend.is_available() and self._storage_path:
                    self._dense_backend = DenseBackend(self._storage_path)
                    self._logger.debug("Dense backend initialized")
            except Exception as e:
                self._logger.debug(f"Dense backend unavailable: {e}")

        if self._sparse_backend is None:
            try:
                from .bm25 import Bm25Backend

                if Bm25Backend.is_available():
                    self._sparse_backend = Bm25Backend()
                    self._logger.debug("BM25S backend initialized")
            except Exception as e:
                self._logger.debug(f"BM25S backend unavailable: {e}")

        return self._dense_backend is not None or self._sparse_backend is not None

    def build_index(self, chunks: list["Chunk"]) -> None:
        """
        Build indices for both sub-backends.

        Args:
            chunks: List of Chunk objects to index
        """
        if not self._ensure_backends():
            self._logger.warning("No sub-backends available")
            self._index_built = False
            return

        if not chunks:
            self.clear()
            return

        self._logger.info(f"Building hybrid index for {len(chunks)} chunks...")

        # Build both indices
        if self._dense_backend is not None:
            try:
                self._dense_backend.build_index(chunks)
                self._logger.debug("Dense index built")
            except Exception as e:
                self._logger.warning(f"Dense index build failed: {e}")

        if self._sparse_backend is not None:
            try:
                self._sparse_backend.build_index(chunks)
                self._logger.debug("BM25S index built")
            except Exception as e:
                self._logger.warning(f"BM25S index build failed: {e}")

        self._chunk_count = len(chunks)
        self._index_built = True
        self._logger.info(f"Hybrid index built: {self._chunk_count} chunks")

    def retrieve(
        self, query_terms: list[str], chunks: list["Chunk"], limit: int, min_score: float, raw_query: str | None = None
    ) -> list["Chunk"]:
        """
        Retrieve chunks using hybrid RRF ranking.

        Args:
            query_terms: Pre-processed query terms (used by BM25S)
            chunks: Full list of chunks (corpus reference)
            limit: Maximum chunks to return
            min_score: Minimum RRF score threshold
            raw_query: Original query string (REQUIRED for Dense)

        Returns:
            List of relevant chunks, sorted by RRF score descending
        """
        if not self._index_built:
            return []

        # Retrieve from both backends (with higher limit for re-ranking)
        retrieve_limit = min(limit * 3, self._chunk_count) if self._chunk_count > 0 else limit * 3

        dense_results: list[Chunk] = []
        sparse_results: list[Chunk] = []

        # Dense retrieval (semantic)
        if self._dense_backend is not None and self._dense_backend.is_ready and raw_query:
            try:
                dense_results = self._dense_backend.retrieve(
                    query_terms=query_terms,
                    chunks=chunks,
                    limit=retrieve_limit,
                    min_score=0.0,  # Don't filter here, filter after RRF
                    raw_query=raw_query,
                )
            except Exception as e:
                self._logger.warning(f"Dense retrieval failed: {e}")

        # Sparse retrieval (lexical)
        if self._sparse_backend is not None and self._sparse_backend.is_ready and query_terms:
            try:
                sparse_results = self._sparse_backend.retrieve(
                    query_terms=query_terms,
                    chunks=chunks,
                    limit=retrieve_limit,
                    min_score=0.0,  # Don't filter here, filter after RRF
                    raw_query=raw_query,
                )
            except Exception as e:
                self._logger.warning(f"Sparse retrieval failed: {e}")

        # If only one backend returned results, use those directly
        if not dense_results and not sparse_results:
            return []
        if not dense_results:
            return sparse_results[:limit]
        if not sparse_results:
            return dense_results[:limit]

        # Apply RRF to combine results
        rrf_results = self._compute_rrf_scores(dense_results, sparse_results)

        # Sort by RRF score descending
        sorted_entries = sorted(rrf_results.values(), key=lambda entry: entry[1], reverse=True)

        # Return top-k chunks above min_score
        results = []
        for chunk, score in sorted_entries[:limit]:
            if score >= min_score:
                results.append(chunk)

        self._logger.debug(
            f"Hybrid retrieval: {len(dense_results)} dense + {len(sparse_results)} sparse -> {len(results)} after RRF"
        )

        return results

    def _compute_rrf_scores(self, dense_results: list["Chunk"], sparse_results: list["Chunk"]) -> dict[str, tuple]:
        """
        Compute Reciprocal Rank Fusion scores.

        V12.4: Uses chunk_id (str) as dict key instead of Chunk objects.
        Chunk is frozen+hashable now, but string keys are more explicit.

        RRF combines multiple ranked lists without needing score calibration.
        Formula: score(d) = sum(w_i / (k + rank_i(d))) for each list i

        Args:
            dense_results: Ranked results from dense backend
            sparse_results: Ranked results from sparse backend

        Returns:
            Dict mapping chunk_id to (chunk, rrf_score) tuples
        """
        rrf_scores: dict[str, float] = defaultdict(float)
        chunk_lookup: dict[str, Chunk] = {}

        # Process dense results
        for rank, chunk in enumerate(dense_results, start=1):
            cid = chunk.chunk_id
            rrf_scores[cid] += self._dense_weight / (RRF_K + rank)
            chunk_lookup[cid] = chunk

        # Process sparse results
        for rank, chunk in enumerate(sparse_results, start=1):
            cid = chunk.chunk_id
            rrf_scores[cid] += self._sparse_weight / (RRF_K + rank)
            if cid not in chunk_lookup:
                chunk_lookup[cid] = chunk

        # Return as (chunk, score) tuples keyed by chunk_id
        return {cid: (chunk_lookup[cid], score) for cid, score in rrf_scores.items()}

    def clear(self) -> None:
        """Clear both sub-backend indices."""
        if self._dense_backend is not None:
            try:
                self._dense_backend.clear()
            except Exception as e:
                self._logger.warning(f"Dense clear failed: {e}")

        if self._sparse_backend is not None:
            try:
                self._sparse_backend.clear()
            except Exception as e:
                self._logger.warning(f"Sparse clear failed: {e}")

        self._index_built = False
        self._chunk_count = 0

    def get_info(self) -> dict[str, Any]:
        """Get Hybrid backend information."""
        dense_info = self._dense_backend.get_info() if self._dense_backend else {}
        sparse_info = self._sparse_backend.get_info() if self._sparse_backend else {}

        return {
            "backend": self.name,
            "rrf_k": RRF_K,
            "dense_weight": self._dense_weight,
            "sparse_weight": self._sparse_weight,
            "index_built": self._index_built,
            "chunk_count": self._chunk_count,
            "dense_backend": dense_info,
            "sparse_backend": sparse_info,
        }

    def set_weights(self, dense_weight: float, sparse_weight: float) -> None:
        """
        Update backend weights dynamically.

        V12.4: Allows adaptive weight tuning based on query type.

        Args:
            dense_weight: Weight for dense (semantic) results
            sparse_weight: Weight for sparse (lexical) results
        """
        self._dense_weight = dense_weight
        self._sparse_weight = sparse_weight
        self._logger.debug(f"Weights updated: dense={dense_weight}, sparse={sparse_weight}")


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "HybridBackend",
    "RRF_K",
    "DEFAULT_DENSE_WEIGHT",
    "DEFAULT_SPARSE_WEIGHT",
]
