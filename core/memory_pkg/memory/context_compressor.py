"""
Context Compressor - Smart conversation pruning and summarization.

V12.4 COGNITIVE BOOST - Task #53

Compresses conversation history by detecting low-importance turns,
applying sliding window with importance weighting, and archiving
pruned content. Preserves decision rationale while removing filler.

Usage:
    from core.memory_pkg.memory.context_compressor import ContextCompressor

    compressor = ContextCompressor(max_tokens=8000)

    # Add turns
    compressor.add_turn("user", "Analyze the auth module")
    compressor.add_turn("assistant", "The auth module has 3 issues...")
    compressor.add_turn("user", "ok")
    compressor.add_turn("assistant", "Let me fix issue #1...")

    # Compress (prune low-importance turns)
    result = compressor.compress()

    # Get compressed context
    turns = compressor.get_active_turns()

    # Check if compression is needed
    if compressor.should_compress():
        compressor.compress()
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

DEFAULT_MAX_TOKENS = 8000
DEFAULT_COMPRESS_THRESHOLD = 0.8  # Compress when 80% of budget used
TOKENS_PER_WORD = 1.3  # Rough estimate

# Importance signals
LOW_IMPORTANCE_PATTERNS = [
    r"^(ok|okay|yes|no|sure|thanks|thank you|got it|understood|alright)[\.\!\?]?$",
    r"^(hmm|hm|ah|oh|uh)[\.\!\?]?$",
]

HIGH_IMPORTANCE_PATTERNS = [
    r"\b(decision|decided|choosing|chose|approach|architecture)\b",
    r"\b(error|bug|fix|issue|problem|critical)\b",
    r"\b(because|reason|rationale|trade-?off)\b",
    r"\b(conclusion|summary|result|finding)\b",
]


# =============================================================================
# Types
# =============================================================================


@dataclass
class CompressTurn:
    """A turn in the conversation with importance scoring."""

    turn_id: int
    role: str  # "user", "assistant", "system"
    content: str
    token_estimate: int = 0
    importance: float = 0.5  # 0.0 = least important, 1.0 = most important
    timestamp: float = 0.0
    pinned: bool = False  # If True, never pruned
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.monotonic()
        if self.token_estimate == 0:
            self.token_estimate = int(len(self.content.split()) * TOKENS_PER_WORD)

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "role": self.role,
            "content_length": len(self.content),
            "token_estimate": self.token_estimate,
            "importance": round(self.importance, 3),
            "pinned": self.pinned,
        }


@dataclass
class CompressionResult:
    """Result of a compression operation."""

    turns_before: int
    turns_after: int
    tokens_before: int
    tokens_after: int
    turns_pruned: int
    turns_archived: int

    @property
    def compression_ratio(self) -> float:
        if self.tokens_before == 0:
            return 0.0
        return 1 - (self.tokens_after / self.tokens_before)

    def to_dict(self) -> dict[str, Any]:
        return {
            "turns_before": self.turns_before,
            "turns_after": self.turns_after,
            "tokens_before": self.tokens_before,
            "tokens_after": self.tokens_after,
            "turns_pruned": self.turns_pruned,
            "turns_archived": self.turns_archived,
            "compression_ratio": round(self.compression_ratio, 4),
        }


@dataclass
class ContextShift:
    """A detected shift in conversation context."""

    turn_id: int
    old_topic: str
    new_topic: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "old_topic": self.old_topic,
            "new_topic": self.new_topic,
            "confidence": round(self.confidence, 3),
        }


# =============================================================================
# Context Compressor
# =============================================================================


class ContextCompressor:
    """
    Smart conversation context compression.

    Strategies:
    - Importance scoring: Score each turn for information content
    - Low-importance pruning: Remove filler turns (ok, thanks, etc.)
    - Recency bias: More recent turns get higher importance
    - Pin protection: Critical turns can be pinned (never pruned)
    - Archive: Pruned turns archived (never deleted)
    """

    def __init__(
        self,
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        compress_threshold: float = DEFAULT_COMPRESS_THRESHOLD,
    ):
        self._turns: list[CompressTurn] = []
        self._archive: list[CompressTurn] = []
        self._max_tokens = max_tokens
        self._compress_threshold = compress_threshold
        self._next_id = 0
        self._lock = threading.Lock()
        self._compressions = 0

    # =========================================================================
    # Add Turns
    # =========================================================================

    def add_turn(
        self,
        role: str,
        content: str,
        *,
        pinned: bool = False,
        importance: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CompressTurn:
        """
        Add a conversation turn.

        Args:
            role: Turn role ("user", "assistant", "system")
            content: Turn content
            pinned: If True, never pruned
            importance: Override importance (auto-scored if None)
            metadata: Optional metadata
        """
        with self._lock:
            turn_id = self._next_id
            self._next_id += 1

        turn = CompressTurn(
            turn_id=turn_id,
            role=role,
            content=content,
            pinned=pinned,
            metadata=metadata or {},
        )

        if importance is not None:
            turn.importance = max(0.0, min(1.0, importance))
        else:
            turn.importance = self._score_importance(turn)

        with self._lock:
            self._turns.append(turn)

        return turn

    # =========================================================================
    # Importance Scoring
    # =========================================================================

    def _score_importance(self, turn: CompressTurn) -> float:
        """Score the importance of a turn (0.0 to 1.0)."""
        score = 0.5  # Base score

        content_lower = turn.content.strip().lower()

        # Low importance patterns
        for pattern in LOW_IMPORTANCE_PATTERNS:
            if re.match(pattern, content_lower, re.IGNORECASE):
                score = 0.1
                return score

        # High importance patterns
        for pattern in HIGH_IMPORTANCE_PATTERNS:
            if re.search(pattern, content_lower, re.IGNORECASE):
                score += 0.1

        # Content length bonus (longer = more information)
        word_count = len(turn.content.split())
        if word_count > 100:
            score += 0.15
        elif word_count > 50:
            score += 0.1
        elif word_count < 5:
            score -= 0.1

        # System messages get high importance
        if turn.role == "system":
            score += 0.2

        # Clamp
        return max(0.0, min(1.0, score))

    # =========================================================================
    # Compression
    # =========================================================================

    def compress(self, *, target_tokens: int | None = None) -> CompressionResult:
        """
        Compress the conversation by removing low-importance turns.

        Args:
            target_tokens: Target token budget (default: max_tokens * 0.6)

        Returns:
            CompressionResult with statistics
        """
        target = target_tokens or int(self._max_tokens * 0.6)

        with self._lock:
            turns_before = len(self._turns)
            tokens_before = self._total_tokens()

            if tokens_before <= target:
                return CompressionResult(
                    turns_before=turns_before,
                    turns_after=turns_before,
                    tokens_before=tokens_before,
                    tokens_after=tokens_before,
                    turns_pruned=0,
                    turns_archived=0,
                )

            # Sort prunable turns by importance (lowest first)
            prunable = [(i, t) for i, t in enumerate(self._turns) if not t.pinned]
            prunable.sort(key=lambda x: (x[1].importance, -x[0]))  # Low importance first, older first

            pruned_indices = set()
            current_tokens = tokens_before

            for idx, turn in prunable:
                if current_tokens <= target:
                    break
                pruned_indices.add(idx)
                current_tokens -= turn.token_estimate

            # Archive pruned turns
            archived = []
            remaining = []
            for i, turn in enumerate(self._turns):
                if i in pruned_indices:
                    archived.append(turn)
                else:
                    remaining.append(turn)

            self._archive.extend(archived)
            self._turns = remaining
            self._compressions += 1

            turns_after = len(self._turns)
            tokens_after = self._total_tokens()

        return CompressionResult(
            turns_before=turns_before,
            turns_after=turns_after,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            turns_pruned=len(archived),
            turns_archived=len(archived),
        )

    # =========================================================================
    # Query
    # =========================================================================

    def should_compress(self) -> bool:
        """Check if compression is recommended."""
        current = self._total_tokens()
        return current > self._max_tokens * self._compress_threshold

    def get_active_turns(self) -> list[CompressTurn]:
        """Get current (non-pruned) turns."""
        with self._lock:
            return list(self._turns)

    def get_archived_turns(self) -> list[CompressTurn]:
        """Get archived (pruned) turns."""
        with self._lock:
            return list(self._archive)

    def get_turn(self, turn_id: int) -> CompressTurn | None:
        """Get a turn by ID (searches active and archived)."""
        with self._lock:
            for turn in self._turns:
                if turn.turn_id == turn_id:
                    return turn
            for turn in self._archive:
                if turn.turn_id == turn_id:
                    return turn
        return None

    def pin_turn(self, turn_id: int) -> bool:
        """Pin a turn (prevent it from being pruned)."""
        with self._lock:
            for turn in self._turns:
                if turn.turn_id == turn_id:
                    turn.pinned = True
                    return True
        return False

    def unpin_turn(self, turn_id: int) -> bool:
        """Unpin a turn."""
        with self._lock:
            for turn in self._turns:
                if turn.turn_id == turn_id:
                    turn.pinned = False
                    return True
        return False

    # =========================================================================
    # Context Shift Detection
    # =========================================================================

    def detect_context_shift(self) -> ContextShift | None:
        """
        Detect if the conversation topic has shifted.

        Uses keyword overlap between first half and second half.
        """
        with self._lock:
            turns = list(self._turns)

        if len(turns) < 4:
            return None

        mid = len(turns) // 2
        first_half = " ".join(t.content for t in turns[:mid])
        second_half = " ".join(t.content for t in turns[mid:])

        first_keywords = self._extract_keywords(first_half)
        second_keywords = self._extract_keywords(second_half)

        if not first_keywords or not second_keywords:
            return None

        overlap = first_keywords & second_keywords
        total = first_keywords | second_keywords

        if not total:
            return None

        similarity = len(overlap) / len(total)

        # Low similarity suggests a context shift
        if similarity < 0.2:
            return ContextShift(
                turn_id=turns[mid].turn_id,
                old_topic=", ".join(sorted(first_keywords - second_keywords)[:5]),
                new_topic=", ".join(sorted(second_keywords - first_keywords)[:5]),
                confidence=1.0 - similarity,
            )

        return None

    @staticmethod
    def _extract_keywords(text: str) -> set:
        """Extract meaningful keywords from text."""
        words = re.findall(r"\b[a-zA-Z]{4,}\b", text.lower())
        # Filter common stop words
        stop_words = {
            "this",
            "that",
            "with",
            "from",
            "have",
            "will",
            "been",
            "were",
            "they",
            "them",
            "their",
            "some",
            "what",
            "when",
            "where",
            "which",
            "would",
            "could",
            "should",
            "about",
            "into",
            "your",
            "also",
            "than",
            "then",
            "just",
            "more",
            "most",
            "very",
            "much",
        }
        return set(w for w in words if w not in stop_words)

    # =========================================================================
    # State
    # =========================================================================

    @property
    def active_count(self) -> int:
        return len(self._turns)

    @property
    def archived_count(self) -> int:
        return len(self._archive)

    @property
    def compression_count(self) -> int:
        return self._compressions

    @property
    def total_tokens(self) -> int:
        return self._total_tokens()

    @property
    def max_tokens(self) -> int:
        return self._max_tokens

    @property
    def utilization(self) -> float:
        """Current token budget utilization (0.0 to 1.0+)."""
        if self._max_tokens == 0:
            return 0.0
        return self._total_tokens() / self._max_tokens

    def _total_tokens(self) -> int:
        return sum(t.token_estimate for t in self._turns)

    def clear(self) -> None:
        """Clear all turns (active and archived)."""
        with self._lock:
            self._turns.clear()
            self._archive.clear()
            self._compressions = 0
            self._next_id = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_count": self.active_count,
            "archived_count": self.archived_count,
            "total_tokens": self.total_tokens,
            "max_tokens": self._max_tokens,
            "utilization": round(self.utilization, 4),
            "compression_count": self._compressions,
            "should_compress": self.should_compress(),
        }


# =============================================================================
# Global Instance
# =============================================================================

_compressor: ContextCompressor | None = None
_compressor_lock = threading.Lock()


def get_compressor(*, max_tokens: int = DEFAULT_MAX_TOKENS) -> ContextCompressor:
    """Get or create the global context compressor."""
    global _compressor
    if _compressor is None:
        with _compressor_lock:
            if _compressor is None:
                _compressor = ContextCompressor(max_tokens=max_tokens)
    return _compressor


def reset_compressor() -> None:
    """Reset the global compressor (for testing)."""
    global _compressor
    _compressor = None
