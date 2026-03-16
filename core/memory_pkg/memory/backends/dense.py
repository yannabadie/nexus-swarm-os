"""
NEXUS V10 MEMORY FORGE - Dense Embeddings Backend

Semantic retrieval using LanceDB (vector storage) and shared EmbeddingEngine.
Provides ~10% better recall than BM25S for semantic queries ("auth" ≈ "authentication").

V10 Architecture:
- Delegates encoding to global EmbeddingEngine singleton (shared compute)
- Storage is tenant-isolated (each tenant has own LanceDB path)
- Injection support: pass embedding_engine in __init__ for testing

Optional dependencies: pip install lancedb sentence-transformers[onnx]
Falls back gracefully if not installed.

Model: all-MiniLM-L6-v2 (22MB, 384 dimensions, ~5k sentences/sec on CPU)
Storage: .nexus/lancedb/ (embedded, serverless, per-tenant)
"""

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from .base import MemoryBackend

if TYPE_CHECKING:
    from ..embedding_engine import EmbeddingEngine
    from ..types import Chunk

# =============================================================================
# Optional Dependencies (lazy import for startup performance)
# =============================================================================

LANCEDB_AVAILABLE = False
SENTENCE_TRANSFORMERS_AVAILABLE = False

try:
    import lancedb

    LANCEDB_AVAILABLE = True
except ImportError:
    lancedb = None  # type: ignore

try:
    # Check if sentence_transformers can be imported (don't import yet - slow)
    import importlib.util

    SENTENCE_TRANSFORMERS_AVAILABLE = importlib.util.find_spec("sentence_transformers") is not None
except Exception:
    pass


# =============================================================================
# Constants
# =============================================================================

DEFAULT_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384  # all-MiniLM-L6-v2 dimension
TABLE_NAME = "chunks"
BATCH_SIZE = 32  # Batch size for encoding


class DenseBackend(MemoryBackend):
    """
    Dense embeddings retrieval backend using LanceDB + shared EmbeddingEngine.

    V10 MEMORY FORGE Architecture:
    - Encoding delegated to global EmbeddingEngine (shared across tenants)
    - Storage isolated per tenant (each has own LanceDB path)
    - Supports dependency injection for testing

    Features:
    - Semantic similarity (understands "auth" ≈ "authentication")
    - ~10% better recall than BM25S for conceptual queries
    - Persistent vector storage in .nexus/lancedb/
    - Lazy loading for zero startup impact
    - ONNX acceleration when available (2-3x faster CPU)

    Dependencies:
    - lancedb>=0.4.0 (required)
    - sentence-transformers>=3.2.0 (required)
    - onnxruntime>=1.19.0 (optional, for ONNX acceleration)

    Storage Schema:
    - id: Unique chunk identifier (file_path:start-end)
    - vector: 384-dim embedding (all-MiniLM-L6-v2)
    - metadata: JSON-serialized Chunk data
    """

    def __init__(self, storage_path: Path, embedding_engine: Optional["EmbeddingEngine"] = None):
        """
        Initialize the Dense backend.

        Args:
            storage_path: Directory for LanceDB storage (e.g., .nexus/lancedb)
            embedding_engine: Optional EmbeddingEngine instance (for DI/testing).
                             If None, uses global singleton.
        """
        self._logger = logging.getLogger("nexus.memory.dense")
        self._storage_path = Path(storage_path)

        # V10 MEMORY FORGE: Use injected engine or get global singleton
        self._engine: EmbeddingEngine | None = embedding_engine

        # Lazy-loaded components (storage only - model is in engine)
        self._db: Any | None = None
        self._table: Any | None = None

        self._index_built = False
        self._chunk_count = 0

    @property
    def name(self) -> str:
        return "dense"

    @property
    def is_ready(self) -> bool:
        return self._index_built and self._table is not None

    @classmethod
    def is_available(cls) -> bool:
        """Check if Dense backend can be used."""
        return LANCEDB_AVAILABLE and SENTENCE_TRANSFORMERS_AVAILABLE

    def _ensure_engine(self) -> bool:
        """
        Ensure the EmbeddingEngine is ready.

        V10 MEMORY FORGE: Delegates to global singleton or injected engine.

        Returns:
            True if engine is ready, False otherwise
        """
        # Already have an engine
        if self._engine is not None and self._engine.is_loaded:
            return True

        # Get global singleton if not injected
        if self._engine is None:
            if not SENTENCE_TRANSFORMERS_AVAILABLE:
                self._logger.warning("sentence-transformers not installed")
                return False

            try:
                from ..embedding_engine import get_embedding_engine

                self._engine = get_embedding_engine()
            except ImportError as e:
                self._logger.error(f"Failed to import EmbeddingEngine: {e}")
                return False

        # Ensure model is loaded (lazy loading in engine)
        try:
            return self._engine.preload()
        except Exception as e:
            self._logger.error(f"Failed to load embedding model: {e}")
            return False

    def _get_table_names(self) -> list:
        """Get table names from LanceDB, handling API changes."""
        # lancedb >= 0.5 uses table_names(), older versions used list_tables()
        if hasattr(self._db, "table_names"):
            result = self._db.table_names()
        elif hasattr(self._db, "list_tables"):
            result = self._db.list_tables()
        else:
            return []
        if isinstance(result, list):
            return result
        return getattr(result, "tables", [])

    def _ensure_db(self) -> bool:
        """
        Lazy-connect to LanceDB.

        Returns:
            True if DB is ready, False otherwise
        """
        if self._db is not None:
            return True

        if not LANCEDB_AVAILABLE:
            self._logger.warning("lancedb not installed")
            return False

        try:
            # Ensure storage directory exists
            self._storage_path.mkdir(parents=True, exist_ok=True)

            # Connect to embedded LanceDB
            self._db = lancedb.connect(str(self._storage_path))
            self._logger.debug(f"LanceDB connected: {self._storage_path}")

            # Check for existing table
            if TABLE_NAME in self._get_table_names():
                self._table = self._db.open_table(TABLE_NAME)
                self._chunk_count = self._table.count_rows()
                self._index_built = self._chunk_count > 0
                self._logger.debug(f"Existing table loaded: {self._chunk_count} chunks")

            return True

        except Exception as e:
            self._logger.error(f"Failed to connect to LanceDB: {e}")
            return False

    def _chunk_to_id(self, chunk: "Chunk") -> str:
        """Generate unique ID for a chunk."""
        return f"{chunk.file_path}:{chunk.start_line}-{chunk.end_line}"

    def _chunk_to_metadata(self, chunk: "Chunk") -> str:
        """Serialize chunk to JSON metadata."""
        return json.dumps(chunk.to_dict())

    def _metadata_to_chunk(self, metadata: str) -> "Chunk":
        """Deserialize chunk from JSON metadata."""
        from ..types import Chunk

        data = json.loads(metadata)
        return Chunk.from_dict(data)

    def build_index(self, chunks: list["Chunk"]) -> None:
        """
        Build the dense index from chunks.

        Uses batch encoding for efficiency via shared EmbeddingEngine.

        Args:
            chunks: List of Chunk objects to index
        """
        if not self._ensure_db() or not self._ensure_engine():
            self._logger.warning("Dense backend not available, cannot build index")
            self._index_built = False
            return

        if not chunks:
            # Clear existing table
            if TABLE_NAME in self._get_table_names():
                self._db.drop_table(TABLE_NAME)
            self._table = None
            self._index_built = False
            self._chunk_count = 0
            return

        try:
            self._logger.info(f"Building dense index for {len(chunks)} chunks...")

            # Extract texts for embedding
            texts = [chunk.content for chunk in chunks]

            # V10 MEMORY FORGE: Delegate encoding to shared engine
            self._logger.debug(f"Encoding {len(texts)} chunks (batch_size={BATCH_SIZE})...")
            embeddings = self._engine.encode(texts, batch_size=BATCH_SIZE, show_progress=False)

            # Prepare data for LanceDB
            # V11.2 MEMORIA FIX: encode() returns List[List[float]], not numpy array
            # embeddings[i] is already a list, no need for .tolist()
            data = []
            for i, chunk in enumerate(chunks):
                # Handle both list (from EmbeddingEngine) and numpy array (legacy)
                vector = embeddings[i] if isinstance(embeddings[i], list) else embeddings[i].tolist()
                data.append(
                    {"id": self._chunk_to_id(chunk), "vector": vector, "metadata": self._chunk_to_metadata(chunk)}
                )

            # Drop existing table and create new
            if TABLE_NAME in self._get_table_names():
                self._db.drop_table(TABLE_NAME)

            self._table = self._db.create_table(TABLE_NAME, data)
            self._chunk_count = len(chunks)
            self._index_built = True

            self._logger.info(f"Dense index built: {self._chunk_count} chunks indexed")

        except Exception as e:
            self._logger.error(f"Dense index build failed: {e}")
            self._table = None
            self._index_built = False
            self._chunk_count = 0

    def retrieve(
        self, query_terms: list[str], chunks: list["Chunk"], limit: int, min_score: float, raw_query: str | None = None
    ) -> list["Chunk"]:
        """
        Retrieve chunks using dense embeddings.

        Args:
            query_terms: Ignored (used by sparse backends)
            chunks: Ignored (LanceDB stores chunks internally)
            limit: Maximum chunks to return
            min_score: Minimum cosine similarity threshold (0.0-1.0)
            raw_query: The original query string (REQUIRED for dense retrieval)

        Returns:
            List of relevant chunks, sorted by semantic similarity descending
        """
        if not raw_query:
            self._logger.warning("raw_query required for dense retrieval")
            return []

        if not self._ensure_db() or not self._ensure_engine():
            return []

        if self._table is None or self._chunk_count == 0:
            return []

        try:
            # V10 MEMORY FORGE: Delegate query encoding to shared engine
            query_embedding = self._engine.encode_single(raw_query)

            # Search LanceDB
            # LanceDB uses L2 distance by default, but we can use cosine via metric
            # Note: query_embedding is already a list from engine.encode_single()
            results = self._table.search(query_embedding).limit(limit).to_list()

            # Convert results to Chunk objects
            retrieved_chunks = []
            for result in results:
                # LanceDB returns _distance (L2) - convert to similarity
                # For cosine, similarity = 1 - distance/2 (approximate)
                distance = result.get("_distance", 0)
                similarity = max(0, 1 - distance / 2)  # Approximate cosine from L2

                if similarity >= min_score:
                    try:
                        chunk = self._metadata_to_chunk(result["metadata"])
                        retrieved_chunks.append(chunk)
                    except Exception as e:
                        self._logger.warning(f"Failed to deserialize chunk: {e}")

            return retrieved_chunks

        except Exception as e:
            self._logger.warning(f"Dense retrieve failed: {e}")
            return []

    def clear(self) -> None:
        """Clear the dense index."""
        if self._db is not None and TABLE_NAME in self._get_table_names():
            try:
                self._db.drop_table(TABLE_NAME)
            except Exception as e:
                self._logger.warning(f"Failed to drop table: {e}")

        self._table = None
        self._index_built = False
        self._chunk_count = 0

    def get_info(self) -> dict[str, Any]:
        """Get Dense backend information."""
        # Ensure storage is loaded so on-disk indexes are reflected in info.
        self._ensure_db()
        engine_info = {}
        if self._engine is not None:
            engine_info = self._engine.get_info()

        return {
            "backend": self.name,
            "lancedb_available": LANCEDB_AVAILABLE,
            "sentence_transformers_available": SENTENCE_TRANSFORMERS_AVAILABLE,
            "model": DEFAULT_MODEL,
            "embedding_dim": EMBEDDING_DIM,
            "index_built": self._index_built,
            "chunk_count": self._chunk_count,
            "storage_path": str(self._storage_path),
            "dependencies": "lancedb>=0.4.0, sentence-transformers>=3.2.0",
            # V10 MEMORY FORGE: Include shared engine info
            "engine": engine_info,
        }
