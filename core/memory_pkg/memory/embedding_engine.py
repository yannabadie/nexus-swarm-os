"""
NEXUS V10 MEMORY FORGE - Global Embedding Engine Singleton

Process-wide singleton for text embeddings, shared across all tenants.
Solves RAM explosion problem: 1 model (~500MB) vs N models per tenant.

Architecture:
    GLOBAL (1 instance)
           |
    EmbeddingEngine (500MB shared)
     /      |      \
Tenant A  Tenant B  Tenant C
   |         |         |
DenseBackend DenseBackend DenseBackend
(storage A)  (storage B)  (storage C)

Features:
- Singleton via __new__ + RLock (thread-safe)
- ONNX backend for 2-3x faster CPU inference
- PyTorch fallback if ONNX unavailable
- Lazy loading (model loaded on first use)
- Double-checked locking pattern

Usage:
    engine = get_embedding_engine()
    embeddings = engine.encode(["hello world", "test query"])
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from threading import RLock
from typing import Any

# =============================================================================
# Constants
# =============================================================================

DEFAULT_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384  # all-MiniLM-L6-v2 output dimension
DEFAULT_BATCH_SIZE = 32


# =============================================================================
# EmbeddingEngine Singleton
# =============================================================================


class EmbeddingEngine:
    """
    Process-wide singleton for text embeddings.

    V10 MEMORY FORGE: Shared compute across all tenants.
    Each DenseBackend delegates encoding here instead of loading its own model.

    Thread-safety:
    - __new__ + RLock ensures single instance
    - _ensure_model uses double-checked locking
    - encode() is thread-safe after model is loaded

    ONNX Support:
    - sentence-transformers>=3.2.0 supports backend="onnx"
    - 2-3x faster CPU inference vs PyTorch
    - Automatic fallback to PyTorch if ONNX fails
    """

    _instance: EmbeddingEngine | None = None
    _lock = RLock()
    _initialized = False

    def __new__(cls) -> EmbeddingEngine:
        """Singleton pattern via __new__."""
        if cls._instance is None:
            with cls._lock:
                # Double-check inside lock
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """Initialize the engine (only runs once due to _initialized flag)."""
        # Prevent re-initialization
        if EmbeddingEngine._initialized:
            return

        with EmbeddingEngine._lock:
            if EmbeddingEngine._initialized:
                return

            self._logger = logging.getLogger("nexus.memory.embedding_engine")
            self._model: Any | None = None
            self._model_name = DEFAULT_MODEL
            self._device: str | None = None
            self._backend: str | None = None  # "onnx" or "torch"
            self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="embed_")

            EmbeddingEngine._initialized = True

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def embedding_dim(self) -> int:
        """Embedding dimension (384 for all-MiniLM-L6-v2)."""
        return EMBEDDING_DIM

    @property
    def model_name(self) -> str:
        """Name of the embedding model."""
        return self._model_name

    @property
    def device(self) -> str | None:
        """Device used for inference (cpu/cuda)."""
        return self._device

    @property
    def backend(self) -> str | None:
        """Backend used (onnx/torch)."""
        return self._backend

    @property
    def is_loaded(self) -> bool:
        """Check if model is loaded."""
        return self._model is not None

    # =========================================================================
    # Model Loading
    # =========================================================================

    def _ensure_model(self) -> bool:
        """
        Lazy-load the embedding model with double-checked locking.

        Tries ONNX backend first, falls back to PyTorch.

        Returns:
            True if model is ready, False otherwise
        """
        if self._model is not None:
            return True

        with self._lock:
            # Double-check inside lock
            if self._model is not None:
                return True

            try:
                from sentence_transformers import SentenceTransformer
            except ImportError:
                self._logger.error(
                    "sentence-transformers not installed. Install with: pip install sentence-transformers[onnx]>=3.2.0"
                )
                return False

            # Detect device
            try:
                import torch

                self._device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                self._device = "cpu"

            # Try ONNX backend first (2-3x faster on CPU)
            if self._try_load_onnx(SentenceTransformer):
                return True

            # Fallback to PyTorch
            return self._try_load_pytorch(SentenceTransformer)

    def _try_load_onnx(self, SentenceTransformer: type) -> bool:
        """Try loading model with ONNX backend."""
        try:
            # Check if onnxruntime is available
            import importlib.util

            if importlib.util.find_spec("onnxruntime") is None:
                self._logger.debug("onnxruntime not installed, skipping ONNX backend")
                return False

            self._logger.info(f"Loading {self._model_name} with ONNX backend...")

            # sentence-transformers>=3.2.0 supports backend parameter
            self._model = SentenceTransformer(self._model_name, device=self._device, backend="onnx")
            self._backend = "onnx"
            self._logger.info(
                f"EmbeddingEngine ready: model={self._model_name}, device={self._device}, backend={self._backend}"
            )
            return True

        except TypeError as e:
            # backend parameter not supported (older sentence-transformers)
            if "backend" in str(e):
                self._logger.warning(
                    "ONNX backend not supported. Upgrade to sentence-transformers>=3.2.0 for ONNX support."
                )
            return False
        except Exception as e:
            self._logger.warning(f"ONNX backend failed: {e}, falling back to PyTorch")
            return False

    def _try_load_pytorch(self, SentenceTransformer: type) -> bool:
        """Load model with default PyTorch backend."""
        try:
            self._logger.info(f"Loading {self._model_name} with PyTorch backend...")

            self._model = SentenceTransformer(self._model_name, device=self._device)
            self._backend = "torch"
            self._logger.info(
                f"EmbeddingEngine ready: model={self._model_name}, device={self._device}, backend={self._backend}"
            )
            return True

        except Exception as e:
            self._logger.error(f"Failed to load embedding model: {e}")
            return False

    # =========================================================================
    # Encoding Methods
    # =========================================================================

    def encode(
        self, texts: str | list[str], batch_size: int = DEFAULT_BATCH_SIZE, show_progress: bool = False
    ) -> list[list[float]]:
        """
        Encode texts to embeddings (synchronous).

        Args:
            texts: Single text or list of texts to encode
            batch_size: Batch size for encoding
            show_progress: Show progress bar (useful for large batches)

        Returns:
            List of embeddings (each embedding is a list of floats)
            Returns empty list if model not available

        Raises:
            RuntimeError: If model fails to load
        """
        if not self._ensure_model():
            raise RuntimeError("EmbeddingEngine: Model not available. Check sentence-transformers installation.")

        # Normalize input
        if isinstance(texts, str):
            texts = [texts]

        if not texts:
            return []

        try:
            embeddings = self._model.encode(
                texts, batch_size=batch_size, show_progress_bar=show_progress, convert_to_numpy=True
            )

            # Convert numpy array to list of lists
            return embeddings.tolist()

        except Exception as e:
            self._logger.error(f"Encoding failed: {e}")
            raise RuntimeError(f"EmbeddingEngine encoding failed: {e}") from e

    def encode_single(self, text: str) -> list[float]:
        """
        Encode a single text (convenience method).

        Args:
            text: Text to encode

        Returns:
            Embedding as list of floats
        """
        result = self.encode([text])
        return result[0] if result else []

    async def encode_async(self, texts: str | list[str], batch_size: int = DEFAULT_BATCH_SIZE) -> list[list[float]]:
        """
        Encode texts to embeddings (asynchronous).

        Uses ThreadPoolExecutor to avoid blocking the event loop.

        Args:
            texts: Single text or list of texts to encode
            batch_size: Batch size for encoding

        Returns:
            List of embeddings (each embedding is a list of floats)
        """
        # V11.4 ASYNC: get_running_loop() for Python 3.12+ compatibility
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, lambda: self.encode(texts, batch_size))

    # =========================================================================
    # Diagnostics
    # =========================================================================

    def get_info(self) -> dict:
        """
        Get engine diagnostics.

        Returns:
            Dictionary with engine status and configuration
        """
        return {
            "model_name": self._model_name,
            "embedding_dim": EMBEDDING_DIM,
            "device": self._device,
            "backend": self._backend,
            "is_loaded": self.is_loaded,
            "onnx_available": self._check_onnx_available(),
            "singleton_id": id(self),
        }

    def _check_onnx_available(self) -> bool:
        """Check if ONNX runtime is available."""
        try:
            import importlib.util

            return importlib.util.find_spec("onnxruntime") is not None
        except Exception:
            return False

    def preload(self) -> bool:
        """
        Preload the model (useful for startup).

        Call this during application startup to avoid first-request latency.

        Returns:
            True if model loaded successfully
        """
        return self._ensure_model()

    def __repr__(self) -> str:
        return (
            f"EmbeddingEngine("
            f"model={self._model_name}, "
            f"device={self._device}, "
            f"backend={self._backend}, "
            f"loaded={self.is_loaded})"
        )


# =============================================================================
# Global Access Functions
# =============================================================================


def get_embedding_engine() -> EmbeddingEngine:
    """
    Get the global EmbeddingEngine singleton.

    V10 MEMORY FORGE: This is GLOBAL, NOT tenant-scoped.
    The model is shared across all tenants for RAM efficiency.

    Returns:
        EmbeddingEngine singleton instance
    """
    return EmbeddingEngine()


def reset_embedding_engine() -> None:
    """
    Reset the global EmbeddingEngine (for testing only).

    WARNING: This will unload the model and break any active DenseBackends.
    Only use in test teardown.
    """
    with EmbeddingEngine._lock:
        if EmbeddingEngine._instance is not None:
            # Shutdown executor
            if hasattr(EmbeddingEngine._instance, "_executor"):
                EmbeddingEngine._instance._executor.shutdown(wait=False)

            EmbeddingEngine._instance._model = None
            EmbeddingEngine._instance = None
            EmbeddingEngine._initialized = False
