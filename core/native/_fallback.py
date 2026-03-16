"""
NEXUS V12.4 - Pure Python fallback for Rust native functions.

These implementations mirror the Rust nexus_core crate exactly.
Used when Rust extension is not compiled.
"""

import hashlib
import hmac
from collections import defaultdict


def compute_rrf(
    dense_ids: list[str],
    sparse_ids: list[str],
    k: int = 60,
    dense_weight: float = 0.6,
    sparse_weight: float = 0.4,
) -> list[tuple[str, float]]:
    """
    Compute Reciprocal Rank Fusion scores for two ranked lists.

    Pure Python implementation matching Rust nexus_core::compute_rrf.
    """
    scores: dict[str, float] = defaultdict(float)

    for rank, chunk_id in enumerate(dense_ids, start=1):
        scores[chunk_id] += dense_weight / (k + rank)

    for rank, chunk_id in enumerate(sparse_ids, start=1):
        scores[chunk_id] += sparse_weight / (k + rank)

    results = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return results


def sha256_hex(content: bytes) -> str:
    """Compute SHA-256 hash of content bytes, return hex string."""
    return hashlib.sha256(content).hexdigest()


def verify_kernel_hash(kernel_content: bytes, expected_hash: str) -> bool:
    """
    Verify KERNEL integrity with constant-time comparison.

    Uses hmac.compare_digest for timing-attack resistance.
    """
    actual = sha256_hex(kernel_content)
    return hmac.compare_digest(actual, expected_hash)


def batch_tfidf_score(
    query_terms: list[str],
    chunk_terms_list: list[list[str]],
    idf: dict[str, float],
) -> list[float]:
    """
    Batch compute TF-IDF weighted Jaccard similarity scores.

    Pure Python implementation matching Rust nexus_core::batch_tfidf_score.
    """
    query_set = set(query_terms)
    query_weight = sum(idf.get(t, 0.0) for t in query_terms)

    if query_weight == 0.0:
        return [0.0] * len(chunk_terms_list)

    scores = []
    for chunk_terms in chunk_terms_list:
        intersection_weight = sum(idf.get(t, 0.0) for t in chunk_terms if t in query_set)
        scores.append(intersection_weight / query_weight)

    return scores
