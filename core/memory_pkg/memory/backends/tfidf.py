"""
NEXUS V7.9 - TF-IDF Memory Backend (Phase 10f)

TF-IDF weighted Jaccard similarity retrieval.
Zero external dependencies - uses only standard library.

This is the fallback backend when BM25S is not installed.
"""

import logging
import math
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from .base import MemoryBackend

if TYPE_CHECKING:
    from ..types import Chunk


class TfidfBackend(MemoryBackend):
    """
    TF-IDF weighted Jaccard similarity retrieval backend.

    Scoring formula:
        Score = sum(idf[term] for term in intersection) / sum(idf[term] for term in query)

    Where:
        IDF(term) = log(N / (1 + df(term)))
        N = total chunks
        df = chunks containing term
    """

    def __init__(self):
        """Initialize the TF-IDF backend."""
        self._logger = logging.getLogger("nexus.memory.tfidf")
        self._idf: dict[str, float] = {}
        self._index_built = False

    @property
    def name(self) -> str:
        return "tfidf"

    @property
    def is_ready(self) -> bool:
        return self._index_built

    def build_index(self, chunks: list["Chunk"]) -> None:
        """
        Build IDF scores from chunks.

        Args:
            chunks: List of Chunk objects to index
        """
        if not chunks:
            self._idf = {}
            self._index_built = False
            return

        # Count document frequency for each term
        df: dict[str, int] = defaultdict(int)
        for chunk in chunks:
            for term in chunk.terms:
                df[term] += 1

        # Calculate IDF using the smooth formula: log(1 + N / df)
        # This guarantees a non-negative IDF even when N == 1 (single-document
        # index), unlike log(N/(1+df)) which goes negative when df >= N.
        n = len(chunks)
        self._idf = {term: math.log(1 + n / count) for term, count in df.items()}

        self._index_built = True
        self._logger.debug(f"TF-IDF index built: {len(self._idf)} terms from {n} chunks")

    def retrieve(
        self,
        query_terms: list[str],
        chunks: list["Chunk"],
        limit: int,
        min_score: float,
        raw_query: str | None = None,  # V7.9 Phase 10g: Ignored by sparse backends
    ) -> list["Chunk"]:
        """
        Retrieve chunks using TF-IDF weighted Jaccard similarity.

        Args:
            query_terms: Pre-processed query terms
            chunks: Full list of chunks to search
            limit: Maximum chunks to return
            min_score: Minimum similarity score threshold
            raw_query: Ignored (used by dense backends only)

        Returns:
            List of relevant chunks, sorted by score descending
        """
        # Note: raw_query ignored - TF-IDF uses tokenized query_terms
        if not query_terms or not chunks:
            return []

        # Ensure index is built
        if not self._index_built:
            self.build_index(chunks)

        query_set = set(query_terms)

        # Score each chunk
        scored_chunks = []
        for chunk in chunks:
            score = self._score_chunk(query_set, chunk.terms)
            if score >= min_score:
                scored_chunks.append((score, chunk))

        # Sort by score descending
        scored_chunks.sort(key=lambda x: x[0], reverse=True)

        # Return top chunks
        return [chunk for _, chunk in scored_chunks[:limit]]

    def _score_chunk(self, query_terms: set[str], chunk_terms: set[str]) -> float:
        """
        Calculate TF-IDF weighted Jaccard similarity.

        Score = sum(idf[term] for term in intersection) / sum(idf[term] for term in query)
        """
        intersection = query_terms & chunk_terms
        if not intersection:
            return 0.0

        # TF-IDF weighted score
        intersection_weight = sum(self._idf.get(term, 1.0) for term in intersection)
        query_weight = sum(self._idf.get(term, 1.0) for term in query_terms)

        if query_weight == 0:
            return 0.0

        return intersection_weight / query_weight

    def clear(self) -> None:
        """Clear the TF-IDF index."""
        self._idf = {}
        self._index_built = False

    def get_info(self) -> dict[str, Any]:
        """Get TF-IDF backend information."""
        return {
            "backend": self.name,
            "terms_indexed": len(self._idf),
            "index_built": self._index_built,
            "dependencies": "none (stdlib only)",
        }
