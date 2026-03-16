"""
NEXUS V12.4 COGNITIVE BOOST - Memory Backends

Pluggable retrieval backends for ProjectMemory.

Available backends:
- TfidfBackend: Zero-dependency fallback (stdlib only)
- Bm25Backend: Better recall (~15%), requires bm25s
- DenseBackend: Semantic retrieval (~+10% recall), requires lancedb + sentence-transformers
- HybridBackend: V12.4 RRF fusion of Dense + BM25S

Usage:
    from core.memory_pkg.memory.backends import MemoryBackend, HybridBackend, DenseBackend, Bm25Backend

    # V12.4: Prefer Hybrid for best results
    if HybridBackend.is_available():
        backend = HybridBackend(storage_path)  # RRF fusion
    elif DenseBackend.is_available():
        backend = DenseBackend(storage_path)  # Semantic search
    elif Bm25Backend.is_available():
        backend = Bm25Backend()  # Sparse lexical
    else:
        backend = TfidfBackend()  # Fallback

    backend.build_index(chunks)
    results = backend.retrieve(query_terms, chunks, limit=5, min_score=0.05, raw_query="...")
"""

from .base import MemoryBackend
from .bm25 import BM25S_AVAILABLE, STEMMER_AVAILABLE, Bm25Backend
from .dense import LANCEDB_AVAILABLE, SENTENCE_TRANSFORMERS_AVAILABLE, DenseBackend
from .hybrid import DEFAULT_DENSE_WEIGHT, DEFAULT_SPARSE_WEIGHT, RRF_K, HybridBackend
from .tfidf import TfidfBackend

__all__ = [
    "MemoryBackend",
    "TfidfBackend",
    "Bm25Backend",
    "BM25S_AVAILABLE",
    "STEMMER_AVAILABLE",
    "DenseBackend",
    "LANCEDB_AVAILABLE",
    "SENTENCE_TRANSFORMERS_AVAILABLE",
    # V12.4 COGNITIVE BOOST
    "HybridBackend",
    "RRF_K",
    "DEFAULT_DENSE_WEIGHT",
    "DEFAULT_SPARSE_WEIGHT",
]
