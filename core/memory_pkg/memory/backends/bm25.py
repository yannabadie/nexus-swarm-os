"""
NEXUS V7.9 - BM25S Memory Backend (Phase 10f)

BM25S sparse retrieval with optional Snowball stemming.
~15% better recall than TF-IDF, 500x faster than rank-bm25.

Optional dependency: pip install bm25s PyStemmer
Falls back gracefully if not installed.
"""

import logging
from typing import TYPE_CHECKING, Any

from .base import MemoryBackend

if TYPE_CHECKING:
    from ..types import Chunk

# =============================================================================
# Optional Dependencies (graceful fallback)
# =============================================================================

BM25S_AVAILABLE = False
STEMMER_AVAILABLE = False

try:
    # Suppress bm25s benchmark.py warning about 'resource' module on Windows
    import io
    import sys

    _stderr_backup = sys.stderr
    sys.stderr = io.StringIO()
    _stdout_backup = sys.stdout
    sys.stdout = io.StringIO()
    try:
        import bm25s

        BM25S_AVAILABLE = True
    finally:
        sys.stdout = _stdout_backup
        sys.stderr = _stderr_backup
except ImportError:
    bm25s = None  # type: ignore

try:
    import Stemmer  # PyStemmer

    STEMMER_AVAILABLE = True
except ImportError:
    Stemmer = None  # type: ignore


class Bm25Backend(MemoryBackend):
    """
    BM25S sparse retrieval backend.

    Features:
    - Okapi BM25 scoring (better than TF-IDF for information retrieval)
    - Optional Snowball stemming for improved term matching
    - ~500x faster indexing than rank-bm25
    - Graceful degradation if dependencies unavailable

    Dependencies:
    - bm25s>=0.2.0 (required)
    - PyStemmer>=2.2.0 (optional, +5% recall)
    """

    def __init__(self):
        """Initialize the BM25S backend."""
        self._logger = logging.getLogger("nexus.memory.bm25")
        self._index: Any | None = None  # bm25s.BM25 instance
        self._stemmer: Any | None = None  # Stemmer.Stemmer instance
        self._corpus_tokens: list[list[str]] | None = None
        self._index_built = False

        # Initialize stemmer if available
        self._init_stemmer()

    @property
    def name(self) -> str:
        return "bm25s"

    @property
    def is_ready(self) -> bool:
        return BM25S_AVAILABLE and self._index_built and self._index is not None

    @classmethod
    def is_available(cls) -> bool:
        """Check if BM25S backend can be used."""
        return BM25S_AVAILABLE

    def _init_stemmer(self) -> None:
        """Initialize the Snowball stemmer (if available)."""
        if STEMMER_AVAILABLE and self._stemmer is None:
            try:
                self._stemmer = Stemmer.Stemmer("english")
                self._logger.debug("Snowball stemmer initialized")
            except Exception as e:
                self._logger.warning(f"Failed to init stemmer: {e}")
                self._stemmer = None

    def _stem_tokens(self, tokens: list[str]) -> list[str]:
        """Apply stemming to tokens (if stemmer available)."""
        if self._stemmer is None:
            return tokens
        try:
            return self._stemmer.stemWords(tokens)
        except Exception:
            return tokens

    def build_index(self, chunks: list["Chunk"]) -> None:
        """
        Build the BM25S index from chunks.

        Args:
            chunks: List of Chunk objects to index
        """
        if not BM25S_AVAILABLE:
            self._logger.warning("BM25S not available, cannot build index")
            self._index_built = False
            return

        if not chunks:
            self._index = None
            self._corpus_tokens = None
            self._index_built = False
            return

        try:
            # Tokenize all chunks (use terms + apply stemming)
            corpus_tokens = []
            for chunk in chunks:
                tokens = list(chunk.terms)
                tokens = self._stem_tokens(tokens)
                corpus_tokens.append(tokens)

            self._corpus_tokens = corpus_tokens

            # Build BM25S index
            self._index = bm25s.BM25()
            self._index.index(corpus_tokens)

            self._index_built = True
            self._logger.debug(f"BM25S index built: {len(corpus_tokens)} chunks")

        except Exception as e:
            self._logger.warning(f"BM25S index build failed: {e}")
            self._index = None
            self._corpus_tokens = None
            self._index_built = False

    def retrieve(
        self,
        query_terms: list[str],
        chunks: list["Chunk"],
        limit: int,
        min_score: float,
        raw_query: str | None = None,  # V7.9 Phase 10g: Ignored by sparse backends
    ) -> list["Chunk"]:
        """
        Retrieve chunks using BM25S.

        Args:
            query_terms: Pre-processed query terms
            chunks: Full list of chunks (for corpus reference)
            limit: Maximum chunks to return
            min_score: Minimum BM25 score threshold
            raw_query: Ignored (used by dense backends only)

        Returns:
            List of relevant chunks, sorted by score descending
        """
        # Note: raw_query ignored - BM25S uses tokenized query_terms
        if not BM25S_AVAILABLE or self._index is None:
            return []

        if not query_terms or not chunks:
            return []

        try:
            # Apply stemming to query tokens
            query_tokens = self._stem_tokens(list(query_terms))

            # Search with BM25S
            results, scores = self._index.retrieve([query_tokens], corpus=chunks, k=limit)

            # Filter by min_score and return
            filtered_chunks = []
            for chunk, score in zip(results[0], scores[0], strict=False):
                if score >= min_score:
                    filtered_chunks.append(chunk)

            return filtered_chunks

        except Exception as e:
            self._logger.warning(f"BM25S retrieve failed: {e}")
            return []

    def clear(self) -> None:
        """Clear the BM25S index."""
        self._index = None
        self._corpus_tokens = None
        self._index_built = False

    def get_info(self) -> dict[str, Any]:
        """Get BM25S backend information."""
        return {
            "backend": self.name,
            "bm25s_available": BM25S_AVAILABLE,
            "stemmer_available": STEMMER_AVAILABLE,
            "stemmer_active": self._stemmer is not None,
            "index_built": self._index_built,
            "corpus_size": len(self._corpus_tokens) if self._corpus_tokens else 0,
            "dependencies": "bm25s>=0.2.0, PyStemmer>=2.2.0 (optional)",
        }
