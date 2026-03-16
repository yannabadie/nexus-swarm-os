"""
NEXUS V12.4 - Pointer-Based Context Memory (arXiv:2511.22729)

Stores large tool outputs externally and replaces them with compact
pointer summaries in the LLM context window. Achieves significant
token reduction for file reads, grep results, and web fetches.

Based on: "Solving Context Window Overflow in AI Agents" (arXiv:2511.22729)

Two operations:
1. store(content) -> pointer_id + summary (compact representation for context)
2. retrieve(pointer_id) -> full content (on demand)

Usage:
    pm = get_pointer_memory()

    # Store large output, get compact pointer
    pointer = pm.store(large_tool_output, source="read:src/auth.py")

    # Use pointer.summary in context instead of full content
    context_entry = pointer.summary  # ~50 tokens vs ~5000 tokens

    # Retrieve full content when needed
    full_content = pm.retrieve(pointer.pointer_id)
"""

import hashlib
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# =============================================================================
# Data Structures
# =============================================================================


@dataclass
class Pointer:
    """Compact reference to externally stored content."""

    pointer_id: str  # Unique hash-based ID
    summary: str  # Compact summary for context injection
    source: str  # Origin (e.g., "read:src/auth.py", "grep:pattern")
    content_length: int  # Original content length (chars)
    token_estimate: int  # Estimated tokens saved
    created_at: float = field(default_factory=time.time)
    access_count: int = 0  # How many times retrieved

    @property
    def context_representation(self) -> str:
        """Format for injection into LLM context."""
        return f"[PTR:{self.pointer_id[:8]}] {self.source} ({self.content_length} chars) — {self.summary}"


@dataclass
class PointerStats:
    """Statistics for pointer memory usage."""

    total_stored: int
    total_retrieved: int
    tokens_saved: int
    active_pointers: int
    evicted_pointers: int
    avg_compression_ratio: float


# =============================================================================
# Summarization Heuristics
# =============================================================================


def _generate_summary(content: str, source: str, max_length: int = 200) -> str:
    """Generate a compact summary of content using heuristics.

    No LLM calls — pure extractive summarization.
    """
    if not content or not content.strip():
        return "(empty content)"

    lines = content.strip().splitlines()
    total_lines = len(lines)

    # File read: first few lines + structure hint
    if source.startswith("read:") or source.startswith("file:"):
        preview_lines = lines[:5]
        preview = "\n".join(ln.strip()[:80] for ln in preview_lines)
        suffix = f" ... ({total_lines} lines total)" if total_lines > 5 else ""
        return f"{preview}{suffix}"

    # Grep results: count matches + sample
    if source.startswith("grep:") or source.startswith("search:"):
        match_count = total_lines
        samples = [ln.strip()[:60] for ln in lines[:3]]
        return f"{match_count} matches. Samples: {'; '.join(samples)}"

    # Web fetch: first sentence + domain
    if source.startswith("web:") or source.startswith("fetch:"):
        first_para = content[:300].split("\n\n")[0]
        return first_para[:max_length]

    # Tool output: first + last line
    if total_lines > 3:
        first = lines[0].strip()[:80]
        last = lines[-1].strip()[:80]
        return f"{first} ... [{total_lines} lines] ... {last}"

    # Short content: just truncate
    return content[:max_length]


def _estimate_tokens(text: str) -> int:
    """Rough token estimate (4 chars per token average)."""
    return max(1, len(text) // 4)


# =============================================================================
# Pointer Memory
# =============================================================================


class PointerMemory:
    """
    External storage for large tool outputs with compact pointer references.

    Content above the size threshold is stored in an LRU cache and replaced
    with a compact pointer containing a summary. This dramatically reduces
    context window usage while preserving access to full content on demand.
    """

    # Content below this threshold is not worth storing externally
    SIZE_THRESHOLD = 500  # chars (~125 tokens)

    # Maximum number of pointers to keep in memory
    MAX_POINTERS = 200

    # Maximum total content size (chars) before aggressive eviction
    MAX_TOTAL_SIZE = 500_000  # ~500KB

    def __init__(
        self,
        size_threshold: int = 0,
        max_pointers: int = 0,
    ):
        self._size_threshold = size_threshold or self.SIZE_THRESHOLD
        self._max_pointers = max_pointers or self.MAX_POINTERS
        self._store: OrderedDict[str, str] = OrderedDict()  # pointer_id -> content
        self._pointers: dict[str, Pointer] = {}  # pointer_id -> Pointer metadata
        self._total_stored = 0
        self._total_retrieved = 0
        self._tokens_saved = 0
        self._evicted_count = 0
        self._total_content_size = 0
        self._lock = threading.Lock()

    # -------------------------------------------------------------------------
    # Core API
    # -------------------------------------------------------------------------

    def store(self, content: str, source: str = "tool") -> Pointer:
        """
        Store content externally and return a compact pointer.

        If content is below the size threshold, returns a pointer with
        the full content as the summary (no external storage needed).

        Args:
            content: The full content to store
            source: Origin identifier (e.g., "read:src/auth.py")

        Returns:
            Pointer with compact summary for context injection
        """
        if not content:
            return Pointer(
                pointer_id="empty",
                summary="(empty)",
                source=source,
                content_length=0,
                token_estimate=0,
            )

        content_len = len(content)

        # Below threshold: no external storage needed
        if content_len <= self._size_threshold:
            pid = self._hash(content)
            return Pointer(
                pointer_id=pid,
                summary=content,  # Full content fits in context
                source=source,
                content_length=content_len,
                token_estimate=0,  # No savings
            )

        # Generate pointer ID and summary
        pid = self._hash(content)
        summary = _generate_summary(content, source)
        original_tokens = _estimate_tokens(content)
        summary_tokens = _estimate_tokens(summary)
        saved = max(0, original_tokens - summary_tokens)

        pointer = Pointer(
            pointer_id=pid,
            summary=summary,
            source=source,
            content_length=content_len,
            token_estimate=saved,
        )

        with self._lock:
            # Store content externally
            self._store[pid] = content
            self._pointers[pid] = pointer
            self._total_stored += 1
            self._tokens_saved += saved
            self._total_content_size += content_len

            # Move to end (most recent)
            self._store.move_to_end(pid)

            # Evict if over limits
            self._evict_if_needed()

        logger.debug(f"PointerMemory: stored {pid[:8]} ({content_len} chars, ~{saved} tokens saved) from {source}")

        return pointer

    def retrieve(self, pointer_id: str) -> str | None:
        """
        Retrieve full content by pointer ID.

        Args:
            pointer_id: The pointer ID from a previous store() call

        Returns:
            Full content string, or None if evicted/not found
        """
        with self._lock:
            content = self._store.get(pointer_id)
            if content is not None:
                self._total_retrieved += 1
                self._store.move_to_end(pointer_id)  # LRU touch
                if pointer_id in self._pointers:
                    self._pointers[pointer_id].access_count += 1
                return content
        return None

    def should_store(self, content: str) -> bool:
        """Check if content is large enough to benefit from pointer storage."""
        return len(content) > self._size_threshold

    def get_stats(self) -> PointerStats:
        """Get pointer memory statistics."""
        with self._lock:
            active = len(self._store)
            total_original = sum(p.content_length for p in self._pointers.values() if p.pointer_id in self._store)
            total_summary = sum(len(p.summary) for p in self._pointers.values() if p.pointer_id in self._store)
            ratio = total_summary / max(total_original, 1)

        return PointerStats(
            total_stored=self._total_stored,
            total_retrieved=self._total_retrieved,
            tokens_saved=self._tokens_saved,
            active_pointers=active,
            evicted_pointers=self._evicted_count,
            avg_compression_ratio=ratio,
        )

    def clear(self) -> None:
        """Clear all stored content."""
        with self._lock:
            self._store.clear()
            self._pointers.clear()
            self._total_content_size = 0

    # -------------------------------------------------------------------------
    # Internal
    # -------------------------------------------------------------------------

    def _hash(self, content: str) -> str:
        """Generate a stable pointer ID from content."""
        return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()[:16]

    def _evict_if_needed(self) -> None:
        """Evict oldest entries if over limits. Caller must hold lock."""
        # Evict by count
        while len(self._store) > self._max_pointers:
            pid, content = self._store.popitem(last=False)
            self._total_content_size -= len(content)
            self._evicted_count += 1
            self._pointers.pop(pid, None)

        # Evict by total size
        while self._total_content_size > self.MAX_TOTAL_SIZE and self._store:
            pid, content = self._store.popitem(last=False)
            self._total_content_size -= len(content)
            self._evicted_count += 1
            self._pointers.pop(pid, None)


# =============================================================================
# Singleton
# =============================================================================

_instance: PointerMemory | None = None
_instance_lock = threading.Lock()


def get_pointer_memory() -> PointerMemory:
    """Get or create the singleton PointerMemory instance."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = PointerMemory()
    return _instance


def reset_pointer_memory() -> None:
    """Reset the singleton (for testing)."""
    global _instance
    _instance = None
