"""
NEXUS V12.4 - Memory Types

Shared type definitions for the memory subsystem.

V12.4 COGNITIVE BOOST:
- Chunk is now frozen (immutable, hashable) for safe use as dict keys in RRF
- Set[str] replaced with frozenset[str] for hashability
- New ScoredChunk wraps Chunk with retrieval metadata (score, backend, etc.)
- chunk_id provides stable identity for deduplication across backends
"""

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Chunk:
    """
    A single indexed chunk of code or documentation.

    IMMUTABLE: This dataclass is frozen so it can be used as a dict key
    (required by HybridBackend RRF scoring). All fields are hashable.

    V12.4.1 Epic 1.4: Added optional metadata field for storing arbitrary
    key-value pairs (e.g., task_id, quality_score for SuccessMemoryV2).
    Metadata is stored as JSON string to maintain immutability.
    """

    file_path: str
    start_line: int
    end_line: int
    content: str
    terms: frozenset[str] = frozenset()
    chunk_type: str = "lines"  # "function", "class", "section", "lines"
    name: str | None = None  # Function/class/section name if applicable
    metadata: dict[str, Any] | None = None  # V12.4.1: Arbitrary metadata

    def __post_init__(self):
        # Coerce mutable set to frozenset for hashability safety
        if isinstance(self.terms, set):
            object.__setattr__(self, "terms", frozenset(self.terms))

        # V12.4.1: Metadata is allowed to be mutable for convenience
        # (Chunk is still hashable via chunk_id, not by metadata)

    @property
    def chunk_id(self) -> str:
        """Stable unique identifier based on file path and line range."""
        return f"{self.file_path}:{self.start_line}-{self.end_line}"

    @property
    def content_hash(self) -> str:
        """SHA-256 hash of the content (first 16 chars)."""
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        result = {
            "file_path": self.file_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "content": self.content,
            "terms": sorted(self.terms),
            "chunk_type": self.chunk_type,
            "name": self.name,
        }
        # V12.4.1: Include metadata if present
        if self.metadata is not None:
            result["metadata"] = self.metadata
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "Chunk":
        """Create from JSON dict."""
        return cls(
            file_path=data["file_path"],
            start_line=data["start_line"],
            end_line=data["end_line"],
            content=data["content"],
            terms=frozenset(data.get("terms", [])),
            chunk_type=data.get("chunk_type", "lines"),
            name=data.get("name"),
            metadata=data.get("metadata"),  # V12.4.1: Load metadata if present
        )


@dataclass
class ScoredChunk:
    """
    A retrieval result wrapping a Chunk with scoring metadata.

    Used by backends to return ranked results. NOT frozen because
    scores and metadata can be adjusted during post-processing (e.g., RRF).

    The underlying Chunk remains immutable.
    """

    chunk: Chunk
    score: float = 0.0
    backend: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def chunk_id(self) -> str:
        """Delegate to underlying chunk."""
        return self.chunk.chunk_id

    @property
    def file_path(self) -> str:
        return self.chunk.file_path

    @property
    def start_line(self) -> int:
        return self.chunk.start_line

    @property
    def end_line(self) -> int:
        return self.chunk.end_line

    @property
    def content(self) -> str:
        return self.chunk.content

    @property
    def terms(self) -> frozenset[str]:
        return self.chunk.terms

    @property
    def chunk_type(self) -> str:
        return self.chunk.chunk_type

    @property
    def name(self) -> str | None:
        return self.chunk.name


@dataclass
class IndexStats:
    """Statistics about the indexed project."""

    total_files: int = 0
    total_chunks: int = 0
    total_terms: int = 0
    indexed_at: str = ""
    storage_path: str = ""

    def to_dict(self) -> dict:
        return asdict(self)
