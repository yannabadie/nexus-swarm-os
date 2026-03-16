"""
Thought Evaluator - Score reasoning quality and detect redundancy.

V12.4 COGNITIVE BOOST

Evaluates individual thoughts and reasoning paths for:
- Quality scoring (0.0-1.0) based on configurable criteria
- Redundancy detection between thoughts
- Path comparison and ranking
- Confidence calibration

Usage:
    from core.intelligence.reasoning.thought_evaluator import get_thought_evaluator

    evaluator = get_thought_evaluator()

    # Score a thought
    score = evaluator.score_thought("analysis_1", content="The auth bug is in token.py line 42",
                                     novelty=0.8, relevance=0.9, confidence=0.7)

    # Check redundancy
    evaluator.score_thought("analysis_2", content="Token validation fails at token.py:42",
                            novelty=0.3, relevance=0.9, confidence=0.7)
    redundant = evaluator.find_redundant(threshold=0.4)
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

DEFAULT_NOVELTY_WEIGHT = 0.3
DEFAULT_RELEVANCE_WEIGHT = 0.4
DEFAULT_CONFIDENCE_WEIGHT = 0.3
MAX_THOUGHTS = 10000
REDUNDANCY_THRESHOLD = 0.4  # Below this novelty = redundant


# =============================================================================
# Types
# =============================================================================


@dataclass
class ThoughtScore:
    """Score for an individual thought."""

    thought_id: str
    content: str = ""
    novelty: float = 0.0  # 0.0 = completely redundant, 1.0 = completely new
    relevance: float = 0.0  # 0.0 = off-topic, 1.0 = directly relevant
    confidence: float = 0.0  # 0.0 = uncertain, 1.0 = certain
    composite_score: float = 0.0
    tags: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.monotonic)

    def to_dict(self) -> dict[str, Any]:
        return {
            "thought_id": self.thought_id,
            "content": self.content[:100] if self.content else "",
            "novelty": round(self.novelty, 4),
            "relevance": round(self.relevance, 4),
            "confidence": round(self.confidence, 4),
            "composite_score": round(self.composite_score, 4),
            "tags": self.tags,
        }


@dataclass
class EvaluationResult:
    """Result of evaluating a set of thoughts."""

    total_thoughts: int
    average_score: float
    best_thought_id: str = ""
    worst_thought_id: str = ""
    redundant_count: int = 0
    redundant_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_thoughts": self.total_thoughts,
            "average_score": round(self.average_score, 4),
            "best_thought_id": self.best_thought_id,
            "worst_thought_id": self.worst_thought_id,
            "redundant_count": self.redundant_count,
            "redundant_ids": self.redundant_ids,
        }


@dataclass
class EvaluatorStats:
    """Evaluator statistics."""

    total_scored: int
    total_pruned: int
    average_novelty: float
    average_relevance: float
    average_confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_scored": self.total_scored,
            "total_pruned": self.total_pruned,
            "average_novelty": round(self.average_novelty, 4),
            "average_relevance": round(self.average_relevance, 4),
            "average_confidence": round(self.average_confidence, 4),
        }


# =============================================================================
# Thought Evaluator
# =============================================================================


class ThoughtEvaluator:
    """
    Evaluates reasoning quality and detects redundancy.

    Features:
    - Weighted composite scoring (novelty, relevance, confidence)
    - Redundancy detection by novelty threshold
    - Path ranking by aggregate score
    - Tag-based grouping
    - Thread-safe
    """

    def __init__(
        self,
        *,
        novelty_weight: float = DEFAULT_NOVELTY_WEIGHT,
        relevance_weight: float = DEFAULT_RELEVANCE_WEIGHT,
        confidence_weight: float = DEFAULT_CONFIDENCE_WEIGHT,
    ):
        total = novelty_weight + relevance_weight + confidence_weight
        self._novelty_weight = novelty_weight / total if total > 0 else 1 / 3
        self._relevance_weight = relevance_weight / total if total > 0 else 1 / 3
        self._confidence_weight = confidence_weight / total if total > 0 else 1 / 3
        self._thoughts: dict[str, ThoughtScore] = {}
        self._total_pruned = 0
        self._lock = threading.Lock()

    # =========================================================================
    # Scoring
    # =========================================================================

    def score_thought(
        self,
        thought_id: str,
        *,
        content: str = "",
        novelty: float = 0.5,
        relevance: float = 0.5,
        confidence: float = 0.5,
        tags: list[str] | None = None,
    ) -> ThoughtScore:
        """
        Score a thought and store it.

        Args:
            thought_id: Unique identifier
            content: Thought content text
            novelty: 0.0-1.0 how new/unique this thought is
            relevance: 0.0-1.0 how relevant to the task
            confidence: 0.0-1.0 how confident in correctness
            tags: Optional tags for grouping

        Returns:
            The scored thought
        """
        n = max(0.0, min(1.0, novelty))
        r = max(0.0, min(1.0, relevance))
        c = max(0.0, min(1.0, confidence))

        composite = self._novelty_weight * n + self._relevance_weight * r + self._confidence_weight * c

        thought = ThoughtScore(
            thought_id=thought_id,
            content=content,
            novelty=n,
            relevance=r,
            confidence=c,
            composite_score=composite,
            tags=tags or [],
        )

        with self._lock:
            # Evict oldest if at capacity
            if thought_id not in self._thoughts and len(self._thoughts) >= MAX_THOUGHTS:
                oldest_id = min(self._thoughts, key=lambda k: self._thoughts[k].timestamp)
                del self._thoughts[oldest_id]
            self._thoughts[thought_id] = thought

        return thought

    def get_score(self, thought_id: str) -> ThoughtScore | None:
        """Get a scored thought."""
        return self._thoughts.get(thought_id)

    def remove_thought(self, thought_id: str) -> bool:
        """Remove a thought."""
        with self._lock:
            if thought_id in self._thoughts:
                del self._thoughts[thought_id]
                return True
            return False

    # =========================================================================
    # Redundancy Detection
    # =========================================================================

    def find_redundant(self, *, threshold: float = REDUNDANCY_THRESHOLD) -> list[str]:
        """Find thought IDs with novelty below threshold."""
        return sorted(tid for tid, t in self._thoughts.items() if t.novelty < threshold)

    def prune_redundant(self, *, threshold: float = REDUNDANCY_THRESHOLD) -> int:
        """Remove thoughts below novelty threshold. Returns count removed."""
        with self._lock:
            to_remove = [tid for tid, t in self._thoughts.items() if t.novelty < threshold]
            for tid in to_remove:
                del self._thoughts[tid]
            self._total_pruned += len(to_remove)
            return len(to_remove)

    # =========================================================================
    # Ranking
    # =========================================================================

    def rank_thoughts(self, *, limit: int = 10) -> list[ThoughtScore]:
        """Get thoughts ranked by composite score (highest first)."""
        ranked = sorted(
            self._thoughts.values(),
            key=lambda t: t.composite_score,
            reverse=True,
        )
        return ranked[:limit]

    def get_by_tag(self, tag: str) -> list[ThoughtScore]:
        """Get thoughts with a specific tag."""
        return [t for t in self._thoughts.values() if tag in t.tags]

    def best_thought(self) -> ThoughtScore | None:
        """Get the highest-scoring thought."""
        if not self._thoughts:
            return None
        return max(self._thoughts.values(), key=lambda t: t.composite_score)

    def worst_thought(self) -> ThoughtScore | None:
        """Get the lowest-scoring thought."""
        if not self._thoughts:
            return None
        return min(self._thoughts.values(), key=lambda t: t.composite_score)

    # =========================================================================
    # Evaluation
    # =========================================================================

    def evaluate(self, *, redundancy_threshold: float = REDUNDANCY_THRESHOLD) -> EvaluationResult:
        """Evaluate all stored thoughts."""
        if not self._thoughts:
            return EvaluationResult(total_thoughts=0, average_score=0.0)

        scores = [t.composite_score for t in self._thoughts.values()]
        avg = sum(scores) / len(scores)
        best = max(self._thoughts.values(), key=lambda t: t.composite_score)
        worst = min(self._thoughts.values(), key=lambda t: t.composite_score)
        redundant = self.find_redundant(threshold=redundancy_threshold)

        return EvaluationResult(
            total_thoughts=len(self._thoughts),
            average_score=avg,
            best_thought_id=best.thought_id,
            worst_thought_id=worst.thought_id,
            redundant_count=len(redundant),
            redundant_ids=redundant,
        )

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> EvaluatorStats:
        thoughts = list(self._thoughts.values())
        if not thoughts:
            return EvaluatorStats(
                total_scored=0,
                total_pruned=self._total_pruned,
                average_novelty=0.0,
                average_relevance=0.0,
                average_confidence=0.0,
            )
        return EvaluatorStats(
            total_scored=len(thoughts),
            total_pruned=self._total_pruned,
            average_novelty=sum(t.novelty for t in thoughts) / len(thoughts),
            average_relevance=sum(t.relevance for t in thoughts) / len(thoughts),
            average_confidence=sum(t.confidence for t in thoughts) / len(thoughts),
        )

    # =========================================================================
    # State
    # =========================================================================

    @property
    def thought_count(self) -> int:
        return len(self._thoughts)

    def clear(self) -> None:
        """Clear all thoughts and reset stats."""
        with self._lock:
            self._thoughts.clear()
            self._total_pruned = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "thought_count": self.thought_count,
            "weights": {
                "novelty": round(self._novelty_weight, 4),
                "relevance": round(self._relevance_weight, 4),
                "confidence": round(self._confidence_weight, 4),
            },
            "stats": self.get_stats().to_dict(),
        }


# =============================================================================
# Global Instance
# =============================================================================

_evaluator: ThoughtEvaluator | None = None
_evaluator_lock = threading.Lock()


def get_thought_evaluator() -> ThoughtEvaluator:
    """Get or create the global thought evaluator."""
    global _evaluator
    if _evaluator is None:
        with _evaluator_lock:
            if _evaluator is None:
                _evaluator = ThoughtEvaluator()
    return _evaluator


def reset_thought_evaluator() -> None:
    """Reset the global thought evaluator (for testing)."""
    global _evaluator
    _evaluator = None
