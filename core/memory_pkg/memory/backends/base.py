"""
NEXUS V7.9 - Memory Backend ABC (Phase 10f + 10g)

Abstract base class for memory retrieval backends.
Enables swappable backends (TF-IDF, BM25S, Dense/LanceDB, Hybrid)

Phase 10f: Initial abstraction (TF-IDF, BM25S)
Phase 10g: Dense embeddings support (raw_query parameter)
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..types import Chunk


class MemoryBackend(ABC):
    """
    Abstract base class for memory retrieval backends.

    Each backend is responsible for:
    - Building an index from chunks
    - Retrieving relevant chunks for a query
    - Managing its own internal state

    The ProjectMemory facade handles:
    - Chunk storage and persistence
    - Term extraction
    - Backend selection and fallback
    """

    @abstractmethod
    def build_index(self, chunks: list["Chunk"]) -> None:
        """
        Build the retrieval index from chunks.

        Called when chunks are added/modified and index needs rebuild.

        Args:
            chunks: List of Chunk objects to index
        """
        pass

    @abstractmethod
    def retrieve(
        self, query_terms: list[str], chunks: list["Chunk"], limit: int, min_score: float, raw_query: str | None = None
    ) -> list["Chunk"]:
        """
        Retrieve relevant chunks for a query.

        Args:
            query_terms: Pre-processed query terms (extracted by facade)
            chunks: Full list of chunks to search within
            limit: Maximum number of chunks to return
            min_score: Minimum relevance score threshold
            raw_query: Original query string (used by dense backends for embeddings)
                      Sparse backends (TF-IDF, BM25S) ignore this parameter.

        Returns:
            List of relevant Chunk objects, sorted by relevance descending
        """
        pass

    @abstractmethod
    def clear(self) -> None:
        """
        Clear the backend's internal index.

        Called when chunks are cleared or forgotten.
        """
        pass

    @abstractmethod
    def get_info(self) -> dict[str, Any]:
        """
        Get information about the backend.

        Returns:
            Dict with backend name, status, and capabilities
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Backend identifier string (e.g., 'tfidf', 'bm25s')."""
        pass

    @property
    def is_ready(self) -> bool:
        """Whether the backend is ready to perform retrieval."""
        return True
