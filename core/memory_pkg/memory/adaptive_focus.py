"""
NEXUS V12.4 - Adaptive Focus Memory (AFM)

Three-tier fidelity context management based on arxiv:2511.12712.

Instead of binary keep/prune, assigns each context item one of three
fidelity levels based on a composite score:
  - FULL: Verbatim content (highest scoring items)
  - COMPRESSED: Summarized to key points (middle tier)
  - PLACEHOLDER: Short reference stub (lowest scoring items)

Composite score = importance_weight * importance
                + recency_weight * recency_decay
                + length_weight * length_signal

Items are packed chronologically under a fixed token budget, with
higher-scoring items allocated more token space via their fidelity tier.

Usage:
    manager = AdaptiveFocusManager(token_budget=8000)

    manager.add_item("Analysis found 3 bugs in auth module", importance=0.9)
    manager.add_item("ok", importance=0.1)
    manager.add_item("Decision: use JWT over sessions", importance=0.95)

    # Assign fidelity tiers
    assignments = manager.assign_fidelity()
    # assignments[0] = FidelityAssignment(tier=FULL, ...)
    # assignments[1] = FidelityAssignment(tier=PLACEHOLDER, ...)
    # assignments[2] = FidelityAssignment(tier=FULL, ...)

    # Get compressed context string
    context = manager.get_compressed_context()
"""

import logging
import math
import threading
import time
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


# =============================================================================
# Fidelity Tiers
# =============================================================================


class FidelityLevel(str, Enum):
    """Three-tier fidelity for context items."""

    FULL = "full"  # Verbatim content
    COMPRESSED = "compressed"  # Key points summary
    PLACEHOLDER = "placeholder"  # Short reference stub


# Token cost multipliers per tier
TIER_TOKEN_RATIOS = {
    FidelityLevel.FULL: 1.0,  # 100% of original tokens
    FidelityLevel.COMPRESSED: 0.3,  # ~30% of original tokens
    FidelityLevel.PLACEHOLDER: 0.05,  # ~5% of original tokens
}

# Score thresholds for tier assignment (greedy packing adjusts these dynamically)
DEFAULT_FULL_THRESHOLD = 0.7
DEFAULT_COMPRESSED_THRESHOLD = 0.3


# =============================================================================
# Data Types
# =============================================================================


@dataclass
class FocusItem:
    """A context item with scoring metadata."""

    item_id: int
    content: str
    role: str = ""  # "user", "assistant", "system", "tool"
    importance: float = 0.5
    timestamp: float = 0.0
    token_estimate: int = 0
    pinned: bool = False  # Pinned items always get FULL fidelity
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.monotonic()
        if self.token_estimate == 0:
            self.token_estimate = max(1, int(len(self.content.split()) * 1.3))


@dataclass
class FidelityAssignment:
    """Result of fidelity assignment for a single item."""

    item_id: int
    tier: FidelityLevel
    composite_score: float
    allocated_tokens: int
    content: str  # The content at assigned fidelity
    original_tokens: int

    @property
    def compression_ratio(self) -> float:
        if self.original_tokens == 0:
            return 0.0
        return 1.0 - (self.allocated_tokens / self.original_tokens)

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "tier": self.tier.value,
            "composite_score": round(self.composite_score, 3),
            "allocated_tokens": self.allocated_tokens,
            "original_tokens": self.original_tokens,
            "compression_ratio": round(self.compression_ratio, 3),
        }


@dataclass
class FocusResult:
    """Result of an adaptive focus operation."""

    assignments: list[FidelityAssignment]
    total_tokens_before: int
    total_tokens_after: int
    items_full: int
    items_compressed: int
    items_placeholder: int

    @property
    def compression_ratio(self) -> float:
        if self.total_tokens_before == 0:
            return 0.0
        return 1.0 - (self.total_tokens_after / self.total_tokens_before)

    def to_dict(self) -> dict:
        return {
            "total_tokens_before": self.total_tokens_before,
            "total_tokens_after": self.total_tokens_after,
            "compression_ratio": round(self.compression_ratio, 3),
            "items_full": self.items_full,
            "items_compressed": self.items_compressed,
            "items_placeholder": self.items_placeholder,
        }


# =============================================================================
# Adaptive Focus Manager
# =============================================================================


class AdaptiveFocusManager:
    """
    Three-tier fidelity context manager (arxiv:2511.12712).

    Scores items using composite of importance, recency, and length,
    then assigns fidelity tiers via greedy packing under token budget.
    """

    def __init__(
        self,
        token_budget: int = 8000,
        importance_weight: float = 0.4,
        recency_weight: float = 0.35,
        length_weight: float = 0.25,
        half_life_seconds: float = 300.0,  # 5 min half-life for recency
    ):
        self._items: list[FocusItem] = []
        self._token_budget = token_budget
        self._importance_weight = importance_weight
        self._recency_weight = recency_weight
        self._length_weight = length_weight
        self._half_life = half_life_seconds
        self._next_id = 0
        self._lock = threading.Lock()

    # =========================================================================
    # Add Items
    # =========================================================================

    def add_item(
        self,
        content: str,
        role: str = "",
        importance: float = 0.5,
        pinned: bool = False,
        metadata: dict | None = None,
    ) -> FocusItem:
        """Add a context item."""
        with self._lock:
            item_id = self._next_id
            self._next_id += 1

        item = FocusItem(
            item_id=item_id,
            content=content,
            role=role,
            importance=max(0.0, min(1.0, importance)),
            pinned=pinned,
            metadata=metadata or {},
        )

        with self._lock:
            self._items.append(item)

        return item

    # =========================================================================
    # Scoring
    # =========================================================================

    def score_item(self, item: FocusItem) -> float:
        """
        Compute composite score for an item.

        composite = w_imp * importance + w_rec * recency + w_len * length_signal
        """
        # Importance component (direct)
        imp = item.importance

        # Recency component (exponential decay)
        age = time.monotonic() - item.timestamp
        recency = math.exp(-0.693 * age / self._half_life) if self._half_life > 0 else 1.0

        # Length signal (longer items carry more information)
        words = len(item.content.split())
        if words >= 100:
            length_sig = 1.0
        elif words >= 50:
            length_sig = 0.7
        elif words >= 20:
            length_sig = 0.5
        elif words >= 5:
            length_sig = 0.3
        else:
            length_sig = 0.1

        composite = self._importance_weight * imp + self._recency_weight * recency + self._length_weight * length_sig
        return max(0.0, min(1.0, composite))

    def score_all(self) -> list[tuple]:
        """Score all items, return (item, score) sorted by score descending."""
        with self._lock:
            items = list(self._items)
        scored = [(item, self.score_item(item)) for item in items]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    # =========================================================================
    # Fidelity Assignment
    # =========================================================================

    def assign_fidelity(self) -> FocusResult:
        """
        Assign fidelity tiers to all items via greedy packing.

        Algorithm:
        1. Score all items
        2. Pinned items always get FULL
        3. Greedily assign FULL to highest-scoring until budget runs low
        4. Assign COMPRESSED to middle tier
        5. Remaining get PLACEHOLDER
        """
        with self._lock:
            items = list(self._items)

        if not items:
            return FocusResult(
                assignments=[],
                total_tokens_before=0,
                total_tokens_after=0,
                items_full=0,
                items_compressed=0,
                items_placeholder=0,
            )

        # Score all items
        scored = [(item, self.score_item(item)) for item in items]

        # Calculate total original tokens
        total_original = sum(item.token_estimate for item in items)

        # Sort by score descending for greedy allocation
        sorted_items = sorted(scored, key=lambda x: x[1], reverse=True)

        # Greedy tier assignment
        assignments_map: dict[int, FidelityAssignment] = {}
        budget_remaining = self._token_budget

        # Pass 1: Pinned items always FULL
        for item, score in sorted_items:
            if item.pinned:
                alloc_tokens = item.token_estimate
                budget_remaining -= alloc_tokens
                assignments_map[item.item_id] = FidelityAssignment(
                    item_id=item.item_id,
                    tier=FidelityLevel.FULL,
                    composite_score=score,
                    allocated_tokens=alloc_tokens,
                    content=item.content,
                    original_tokens=item.token_estimate,
                )

        # Pass 2: Greedy packing for non-pinned items
        for item, score in sorted_items:
            if item.item_id in assignments_map:
                continue

            full_cost = item.token_estimate
            compressed_cost = max(1, int(item.token_estimate * TIER_TOKEN_RATIOS[FidelityLevel.COMPRESSED]))
            placeholder_cost = max(1, int(item.token_estimate * TIER_TOKEN_RATIOS[FidelityLevel.PLACEHOLDER]))

            # Try FULL first
            if budget_remaining >= full_cost and score >= DEFAULT_FULL_THRESHOLD:
                tier = FidelityLevel.FULL
                alloc_tokens = full_cost
                content = item.content
            # Try COMPRESSED
            elif budget_remaining >= compressed_cost and score >= DEFAULT_COMPRESSED_THRESHOLD:
                tier = FidelityLevel.COMPRESSED
                alloc_tokens = compressed_cost
                content = self._compress_content(item.content)
            # PLACEHOLDER
            else:
                tier = FidelityLevel.PLACEHOLDER
                alloc_tokens = placeholder_cost
                content = self._placeholder_content(item.content, item.role)

            budget_remaining -= alloc_tokens
            assignments_map[item.item_id] = FidelityAssignment(
                item_id=item.item_id,
                tier=tier,
                composite_score=score,
                allocated_tokens=alloc_tokens,
                content=content,
                original_tokens=item.token_estimate,
            )

        # Build result in chronological order
        assignments = [assignments_map[item.item_id] for item in items if item.item_id in assignments_map]

        total_after = sum(a.allocated_tokens for a in assignments)
        items_full = sum(1 for a in assignments if a.tier == FidelityLevel.FULL)
        items_compressed = sum(1 for a in assignments if a.tier == FidelityLevel.COMPRESSED)
        items_placeholder = sum(1 for a in assignments if a.tier == FidelityLevel.PLACEHOLDER)

        return FocusResult(
            assignments=assignments,
            total_tokens_before=total_original,
            total_tokens_after=total_after,
            items_full=items_full,
            items_compressed=items_compressed,
            items_placeholder=items_placeholder,
        )

    # =========================================================================
    # Content Compression
    # =========================================================================

    def _compress_content(self, content: str) -> str:
        """Compress content to key points (~30% of original)."""
        sentences = self._split_sentences(content)
        if len(sentences) <= 2:
            return content

        # Keep first sentence (topic), last sentence (conclusion),
        # and any sentence with high-signal keywords
        kept = set()
        kept.add(0)
        kept.add(len(sentences) - 1)

        signal_words = {
            "decision",
            "decided",
            "because",
            "error",
            "fix",
            "conclusion",
            "important",
            "critical",
            "approach",
            "result",
            "finding",
            "recommend",
            "solution",
            "issue",
            "bug",
            "architecture",
        }
        for i, sent in enumerate(sentences):
            words = set(sent.lower().split())
            if words & signal_words:
                kept.add(i)

        # Target ~30% of sentences
        target = max(2, len(sentences) * 3 // 10)
        if len(kept) < target:
            # Add middle sentences for coverage
            mid = len(sentences) // 2
            kept.add(mid)

        compressed = [sentences[i] for i in sorted(kept)]
        return " ".join(compressed)

    def _placeholder_content(self, content: str, role: str) -> str:
        """Create a minimal placeholder reference."""
        words = content.split()
        if len(words) <= 5:
            return f"[{role or 'item'}] {content}"
        preview = " ".join(words[:8])
        return f"[{role or 'item'}, {len(words)} words] {preview}..."

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """Split text into sentences."""
        import re

        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        return [s.strip() for s in sentences if s.strip()]

    # =========================================================================
    # Context Output
    # =========================================================================

    def get_compressed_context(self) -> str:
        """Get the full compressed context as a string."""
        result = self.assign_fidelity()
        parts = []
        for assignment in result.assignments:
            parts.append(assignment.content)
        return "\n".join(parts)

    def needs_compression(self) -> bool:
        """Check if total tokens exceed budget."""
        with self._lock:
            total = sum(item.token_estimate for item in self._items)
        return total > self._token_budget

    # =========================================================================
    # State
    # =========================================================================

    @property
    def item_count(self) -> int:
        return len(self._items)

    @property
    def total_tokens(self) -> int:
        with self._lock:
            return sum(item.token_estimate for item in self._items)

    @property
    def token_budget(self) -> int:
        return self._token_budget

    def get_stats(self) -> dict:
        """Get manager statistics."""
        with self._lock:
            items = list(self._items)
        if not items:
            return {
                "item_count": 0,
                "total_tokens": 0,
                "budget": self._token_budget,
                "utilization": 0.0,
            }
        total = sum(i.token_estimate for i in items)
        scores = [self.score_item(i) for i in items]
        return {
            "item_count": len(items),
            "total_tokens": total,
            "budget": self._token_budget,
            "utilization": round(total / self._token_budget, 3) if self._token_budget > 0 else 0.0,
            "avg_score": round(sum(scores) / len(scores), 3),
            "min_score": round(min(scores), 3),
            "max_score": round(max(scores), 3),
        }

    def clear(self) -> None:
        """Clear all items."""
        with self._lock:
            self._items.clear()
            self._next_id = 0

    def reset(self) -> None:
        """Reset manager state."""
        self.clear()


# =============================================================================
# Singleton
# =============================================================================

_manager: AdaptiveFocusManager | None = None
_manager_lock = threading.Lock()


def get_adaptive_focus(token_budget: int = 8000) -> AdaptiveFocusManager:
    """Get or create the global AdaptiveFocusManager."""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = AdaptiveFocusManager(token_budget=token_budget)
    return _manager


def reset_adaptive_focus() -> None:
    """Reset the global AdaptiveFocusManager."""
    global _manager
    _manager = None
