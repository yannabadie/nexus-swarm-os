"""
NEXUS V12.4 - Native Acceleration Bridge

Tries to import compiled Rust extensions (nexus_core).
Falls back to pure-Python implementations transparently.

Usage:
    from core.native import compute_rrf, sha256_hex, verify_kernel_hash

    # Works regardless of whether Rust is compiled
    scores = compute_rrf(dense_ids, sparse_ids)

Build Rust extensions:
    pip install maturin
    cd rust/nexus_core && maturin develop --release

Enable via feature flag: NEXUS_FF_RUST_ACCELERATION=true
"""

import os

_RUST_AVAILABLE = False
_backend = "python"

# Try importing Rust extension
if os.getenv("NEXUS_FF_RUST_ACCELERATION", "").lower() in ("true", "1"):
    try:
        from nexus_core import (
            batch_tfidf_score,
            compute_rrf,
            sha256_hex,
            verify_kernel_hash,
        )

        _RUST_AVAILABLE = True
        _backend = "rust"
    except ImportError:
        pass

# Fallback to pure Python implementations
if not _RUST_AVAILABLE:
    from ._fallback import (
        batch_tfidf_score,
        compute_rrf,
        sha256_hex,
        verify_kernel_hash,
    )


def get_backend_info() -> dict:
    """Return info about the active native backend."""
    return {
        "backend": _backend,
        "rust_available": _RUST_AVAILABLE,
    }


__all__ = [
    "compute_rrf",
    "sha256_hex",
    "verify_kernel_hash",
    "batch_tfidf_score",
    "get_backend_info",
]
