"""
NEXUS V12.4 - Plan-Aware Context Filter (arXiv:2512.16970, PAACE)

Scores context items by relevance to upcoming execution plan steps.
Preserves plan-relevant information, compresses or deprioritizes
irrelevant context.

Based on: "PAACE: A Plan-Aware Automated Agent Context Engineering
Framework" (arXiv:2512.16970)

Key insight: Instead of compressing context uniformly, model which
upcoming tasks need which context, and preserve only plan-relevant
information.

Uses keyword overlap and plan-graph proximity as heuristics (no LLM).

Usage:
    pfilter = get_plan_context_filter()

    scored = pfilter.score_context_items(
        context_items=["SQL query result: ...", "File structure: ..."],
        upcoming_steps=["Implement auth module", "Write tests for auth"],
    )
    # scored[0] = ("SQL query result: ...", 0.2)  # low relevance
    # scored[1] = ("File structure: ...", 0.8)  # high relevance

    filtered = pfilter.filter(
        context_items=items,
        upcoming_steps=steps,
        budget_ratio=0.6,  # Keep 60% of items
    )
"""

import logging
import re
import threading
from collections import Counter
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# =============================================================================
# Data Structures
# =============================================================================


@dataclass
class ScoredItem:
    """A context item scored for plan relevance."""

    content: str
    relevance_score: float  # 0-1 relevance to upcoming steps
    matched_steps: list[str]  # Steps this item is relevant to
    keyword_overlap: float  # Raw keyword overlap score
    position_score: float  # Proximity to next step (closer = higher)


@dataclass
class FilterResult:
    """Result of plan-aware context filtering."""

    kept_items: list[ScoredItem]
    dropped_items: list[ScoredItem]
    total_items: int
    kept_count: int
    tokens_before: int
    tokens_after: int
    compression_ratio: float


@dataclass
class FilterStats:
    """Statistics for the plan context filter."""

    total_filter_calls: int
    total_items_processed: int
    total_items_dropped: int
    avg_compression_ratio: float
    avg_relevance_score: float


# =============================================================================
# Tokenization Helpers
# =============================================================================


def _extract_keywords(text: str) -> Counter:
    """Extract meaningful keywords from text."""
    # Simple tokenization: alphanumeric words, lowercase
    tokens = re.findall(r"[a-zA-Z_]\w{2,}", text.lower())

    # Filter stop words
    stop_words = {
        "the",
        "and",
        "for",
        "that",
        "this",
        "with",
        "from",
        "are",
        "was",
        "were",
        "been",
        "have",
        "has",
        "had",
        "will",
        "would",
        "could",
        "should",
        "not",
        "but",
        "can",
        "all",
        "each",
        "which",
        "their",
        "said",
        "its",
        "into",
        "than",
        "other",
        "some",
        "them",
        "these",
        "then",
        "her",
        "two",
        "how",
        "our",
        "out",
    }

    return Counter(t for t in tokens if t not in stop_words)


def _keyword_overlap(text_keywords: Counter, plan_keywords: Counter) -> float:
    """Compute keyword overlap score between text and plan."""
    if not text_keywords or not plan_keywords:
        return 0.0

    common = set(text_keywords.keys()) & set(plan_keywords.keys())
    if not common:
        return 0.0

    # Weighted by frequency in plan (more important keywords weighted higher)
    overlap_weight = sum(plan_keywords[k] for k in common)
    plan_weight = sum(plan_keywords.values())

    return overlap_weight / max(plan_weight, 1)


def _estimate_tokens(text: str) -> int:
    """Rough token estimate."""
    return max(1, len(text) // 4)


# =============================================================================
# Plan-Aware Context Filter
# =============================================================================


class PlanContextFilter:
    """
    Scores and filters context items based on relevance to upcoming
    execution plan steps.

    Uses keyword overlap as a lightweight relevance proxy. Items with
    higher overlap to upcoming steps are prioritized for retention.

    No LLM calls — pure heuristic scoring.
    """

    # Position decay: closer upcoming steps have more weight
    POSITION_DECAY = 0.8  # Each step further reduces weight

    # Minimum relevance to keep (items below this are candidates for dropping)
    MIN_RELEVANCE = 0.1

    # Default budget ratio (keep this fraction of context)
    DEFAULT_BUDGET = 0.7

    def __init__(self):
        self._total_calls = 0
        self._total_processed = 0
        self._total_dropped = 0
        self._compression_sum = 0.0
        self._relevance_sum = 0.0
        self._relevance_count = 0
        self._lock = threading.Lock()

    # -------------------------------------------------------------------------
    # Core API
    # -------------------------------------------------------------------------

    def score_context_items(
        self,
        context_items: list[str],
        upcoming_steps: list[str],
    ) -> list[ScoredItem]:
        """
        Score context items by relevance to upcoming steps.

        Args:
            context_items: List of context content strings
            upcoming_steps: List of upcoming step descriptions (ordered)

        Returns:
            List of ScoredItem with relevance scores
        """
        if not context_items:
            return []

        if not upcoming_steps:
            # No plan info: all items get neutral score
            return [
                ScoredItem(
                    content=item,
                    relevance_score=0.5,
                    matched_steps=[],
                    keyword_overlap=0.0,
                    position_score=0.5,
                )
                for item in context_items
            ]

        # Extract keywords from upcoming steps with position weighting
        step_keywords: list[tuple[Counter, float]] = []
        for i, step in enumerate(upcoming_steps):
            kw = _extract_keywords(step)
            weight = self.POSITION_DECAY**i  # Closer steps weighted higher
            step_keywords.append((kw, weight))

        # Merge all step keywords with position weighting
        combined_plan_kw = Counter()
        for kw, weight in step_keywords:
            for term, count in kw.items():
                combined_plan_kw[term] += count * weight

        # Score each context item
        scored = []
        for item in context_items:
            item_kw = _extract_keywords(item)
            overlap = _keyword_overlap(item_kw, combined_plan_kw)

            # Find which steps match
            matched = []
            best_position = len(upcoming_steps)
            for i, (step_kw, _) in enumerate(step_keywords):
                step_overlap = _keyword_overlap(item_kw, step_kw)
                if step_overlap > 0.1:
                    matched.append(upcoming_steps[i][:50])
                    best_position = min(best_position, i)

            # Position score: items relevant to closer steps score higher
            position_score = self.POSITION_DECAY**best_position if matched else 0.0

            # Combined relevance
            relevance = overlap * 0.6 + position_score * 0.4

            scored.append(
                ScoredItem(
                    content=item,
                    relevance_score=relevance,
                    matched_steps=matched,
                    keyword_overlap=overlap,
                    position_score=position_score,
                )
            )

        # Track stats
        with self._lock:
            for s in scored:
                self._relevance_sum += s.relevance_score
                self._relevance_count += 1

        return scored

    def filter(
        self,
        context_items: list[str],
        upcoming_steps: list[str],
        budget_ratio: float = 0.0,
    ) -> FilterResult:
        """
        Filter context items based on plan relevance.

        Args:
            context_items: List of context content strings
            upcoming_steps: List of upcoming step descriptions
            budget_ratio: Fraction of items to keep (0 = use default)

        Returns:
            FilterResult with kept and dropped items
        """
        budget = budget_ratio or self.DEFAULT_BUDGET

        scored = self.score_context_items(context_items, upcoming_steps)

        if not scored:
            return FilterResult(
                kept_items=[],
                dropped_items=[],
                total_items=0,
                kept_count=0,
                tokens_before=0,
                tokens_after=0,
                compression_ratio=1.0,
            )

        # Sort by relevance (highest first)
        scored.sort(key=lambda x: x.relevance_score, reverse=True)

        # Keep top budget_ratio fraction
        keep_count = max(1, int(len(scored) * budget))
        kept = scored[:keep_count]
        dropped = scored[keep_count:]

        tokens_before = sum(_estimate_tokens(s.content) for s in scored)
        tokens_after = sum(_estimate_tokens(s.content) for s in kept)
        ratio = tokens_after / max(tokens_before, 1)

        with self._lock:
            self._total_calls += 1
            self._total_processed += len(scored)
            self._total_dropped += len(dropped)
            self._compression_sum += ratio

        return FilterResult(
            kept_items=kept,
            dropped_items=dropped,
            total_items=len(scored),
            kept_count=len(kept),
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            compression_ratio=ratio,
        )

    def get_stats(self) -> FilterStats:
        """Get filter statistics."""
        avg_compression = self._compression_sum / max(self._total_calls, 1)
        avg_relevance = self._relevance_sum / max(self._relevance_count, 1)

        return FilterStats(
            total_filter_calls=self._total_calls,
            total_items_processed=self._total_processed,
            total_items_dropped=self._total_dropped,
            avg_compression_ratio=avg_compression,
            avg_relevance_score=avg_relevance,
        )


# =============================================================================
# Singleton
# =============================================================================

_instance: PlanContextFilter | None = None
_instance_lock = threading.Lock()


def get_plan_context_filter() -> PlanContextFilter:
    """Get or create the singleton PlanContextFilter instance."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = PlanContextFilter()
    return _instance


def reset_plan_context_filter() -> None:
    """Reset the singleton (for testing)."""
    global _instance
    _instance = None
