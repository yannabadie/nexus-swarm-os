"""
Reasoning Quality Scorer - Score and track agent reasoning quality over time.

V12.4 COGNITIVE BOOST

Evaluates reasoning quality across multiple dimensions:
- Depth: How deeply the agent explored the problem
- Coherence: Logical consistency of the reasoning chain
- Completeness: How many options/angles were explored
- Confidence calibration: How well self-reported confidence matches outcomes

Tracks per-agent profiles for intelligent routing and evolution decisions.

Usage:
    from core.intelligence.reasoning.reasoning_quality_scorer import get_quality_scorer

    scorer = get_quality_scorer()

    # Record an evaluation
    ev = scorer.record_evaluation(
        agent_id="claude",
        task_domain="coding",
        depth_score=0.85,
        coherence_score=0.92,
        completeness_score=0.78,
        confidence=0.80,
        actual_outcome_quality=0.88,
    )

    # Get agent profile
    profile = scorer.get_agent_profile("claude")
    print(profile.avg_composite)

    # Find best reasoner
    best = scorer.get_best_reasoner()
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

MAX_EVALUATIONS = 50000


# =============================================================================
# Types
# =============================================================================


@dataclass
class ReasoningEvaluation:
    """A single reasoning quality assessment."""

    evaluation_id: str = ""
    agent_id: str = ""
    task_domain: str = ""
    depth_score: float = 0.0
    coherence_score: float = 0.0
    completeness_score: float = 0.0
    confidence: float = 0.0
    actual_outcome_quality: float = 0.0
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(UTC).isoformat()

    @property
    def composite_score(self) -> float:
        """Average of depth, coherence, and completeness."""
        return (self.depth_score + self.coherence_score + self.completeness_score) / 3

    @property
    def confidence_calibration(self) -> float:
        """How well calibrated the confidence is (1.0 = perfect)."""
        return 1.0 - abs(self.confidence - self.actual_outcome_quality)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation_id": self.evaluation_id,
            "agent_id": self.agent_id,
            "task_domain": self.task_domain,
            "depth_score": round(self.depth_score, 4),
            "coherence_score": round(self.coherence_score, 4),
            "completeness_score": round(self.completeness_score, 4),
            "confidence": round(self.confidence, 4),
            "actual_outcome_quality": round(self.actual_outcome_quality, 4),
            "composite_score": round(self.composite_score, 4),
            "confidence_calibration": round(self.confidence_calibration, 4),
            "timestamp": self.timestamp,
        }


@dataclass
class AgentReasoningProfile:
    """Aggregated per-agent reasoning metrics."""

    agent_id: str = ""
    total_evaluations: int = 0
    total_depth: float = 0.0
    total_coherence: float = 0.0
    total_completeness: float = 0.0
    total_calibration: float = 0.0

    @property
    def avg_depth(self) -> float:
        if self.total_evaluations == 0:
            return 0.0
        return self.total_depth / self.total_evaluations

    @property
    def avg_coherence(self) -> float:
        if self.total_evaluations == 0:
            return 0.0
        return self.total_coherence / self.total_evaluations

    @property
    def avg_completeness(self) -> float:
        if self.total_evaluations == 0:
            return 0.0
        return self.total_completeness / self.total_evaluations

    @property
    def avg_calibration(self) -> float:
        if self.total_evaluations == 0:
            return 0.0
        return self.total_calibration / self.total_evaluations

    @property
    def avg_composite(self) -> float:
        """Average composite across all evaluations."""
        return (self.avg_depth + self.avg_coherence + self.avg_completeness) / 3

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "total_evaluations": self.total_evaluations,
            "avg_depth": round(self.avg_depth, 4),
            "avg_coherence": round(self.avg_coherence, 4),
            "avg_completeness": round(self.avg_completeness, 4),
            "avg_calibration": round(self.avg_calibration, 4),
            "avg_composite": round(self.avg_composite, 4),
        }


@dataclass
class ScorerStats:
    """Overall scorer statistics."""

    total_evaluations: int = 0
    unique_agents: int = 0
    overall_avg_composite: float = 0.0
    overall_avg_calibration: float = 0.0
    best_reasoner: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_evaluations": self.total_evaluations,
            "unique_agents": self.unique_agents,
            "overall_avg_composite": round(self.overall_avg_composite, 4),
            "overall_avg_calibration": round(self.overall_avg_calibration, 4),
            "best_reasoner": self.best_reasoner,
        }


# =============================================================================
# Reasoning Quality Scorer
# =============================================================================


class ReasoningQualityScorer:
    """
    Scores and tracks agent reasoning quality over time.

    Features:
    - Multi-dimensional reasoning evaluation (depth, coherence, completeness)
    - Confidence calibration tracking
    - Per-agent reasoning profiles with running averages
    - Bounded history with FIFO eviction
    - Thread-safe with non-reentrant locking
    """

    def __init__(self, max_evaluations: int = MAX_EVALUATIONS) -> None:
        self._evaluations: list[ReasoningEvaluation] = []
        self._profiles: dict[str, AgentReasoningProfile] = {}
        self._max_evaluations = max_evaluations
        self._lock = threading.Lock()
        self._counter = 0

    # =========================================================================
    # Recording
    # =========================================================================

    def record_evaluation(
        self,
        agent_id: str,
        task_domain: str = "",
        depth_score: float = 0.0,
        coherence_score: float = 0.0,
        completeness_score: float = 0.0,
        confidence: float = 0.0,
        actual_outcome_quality: float = 0.0,
    ) -> ReasoningEvaluation:
        """
        Record a reasoning quality evaluation.

        Args:
            agent_id: Which agent's reasoning is being evaluated.
            task_domain: Domain of the task (coding, research, security, etc.).
            depth_score: 0.0-1.0 reasoning depth.
            coherence_score: 0.0-1.0 logical coherence.
            completeness_score: 0.0-1.0 option exploration completeness.
            confidence: Agent's self-reported confidence.
            actual_outcome_quality: Actual result quality.

        Returns:
            The recorded ReasoningEvaluation.
        """
        with self._lock:
            eval_id = f"re_{self._counter:06d}"
            self._counter += 1

            evaluation = ReasoningEvaluation(
                evaluation_id=eval_id,
                agent_id=agent_id,
                task_domain=task_domain,
                depth_score=depth_score,
                coherence_score=coherence_score,
                completeness_score=completeness_score,
                confidence=confidence,
                actual_outcome_quality=actual_outcome_quality,
            )

            # Update agent profile
            if agent_id not in self._profiles:
                self._profiles[agent_id] = AgentReasoningProfile(
                    agent_id=agent_id,
                )
            profile = self._profiles[agent_id]
            profile.total_evaluations += 1
            profile.total_depth += depth_score
            profile.total_coherence += coherence_score
            profile.total_completeness += completeness_score
            profile.total_calibration += evaluation.confidence_calibration

            # FIFO eviction
            if len(self._evaluations) >= self._max_evaluations:
                self._evaluations.pop(0)

            self._evaluations.append(evaluation)

        return evaluation

    # =========================================================================
    # Queries
    # =========================================================================

    def get_agent_profile(self, agent_id: str) -> AgentReasoningProfile | None:
        """Get the reasoning profile for a specific agent."""
        with self._lock:
            return self._profiles.get(agent_id)

    def get_all_profiles(self) -> list[AgentReasoningProfile]:
        """Get all agent profiles sorted by avg_composite descending."""
        with self._lock:
            profiles = list(self._profiles.values())
        profiles.sort(key=lambda p: p.avg_composite, reverse=True)
        return profiles

    def get_best_reasoner(self) -> str | None:
        """Get the agent_id with the highest avg_composite score."""
        with self._lock:
            if not self._profiles:
                return None
            best = max(
                self._profiles.values(),
                key=lambda p: p.avg_composite,
            )
            return best.agent_id

    def get_recent_evaluations(
        self,
        limit: int = 20,
        agent_id: str = "",
    ) -> list[ReasoningEvaluation]:
        """
        Get recent evaluations, optionally filtered by agent.

        Args:
            limit: Maximum number of evaluations to return.
            agent_id: If non-empty, filter to this agent only.

        Returns:
            List of evaluations, most recent first.
        """
        with self._lock:
            if agent_id:
                filtered = [e for e in self._evaluations if e.agent_id == agent_id]
            else:
                filtered = list(self._evaluations)
        return list(reversed(filtered[-limit:]))

    def get_evaluations_by_domain(self, domain: str) -> list[ReasoningEvaluation]:
        """Get all evaluations for a specific task domain."""
        with self._lock:
            return [e for e in self._evaluations if e.task_domain == domain]

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> ScorerStats:
        """Compute overall scorer statistics."""
        with self._lock:
            total = len(self._evaluations)
            unique = len(self._profiles)

            if not self._profiles:
                return ScorerStats(
                    total_evaluations=total,
                    unique_agents=unique,
                )

            profiles = list(self._profiles.values())
            avg_composite = sum(p.avg_composite for p in profiles) / len(profiles)
            avg_calibration = sum(p.avg_calibration for p in profiles) / len(profiles)
            best = max(profiles, key=lambda p: p.avg_composite)

            return ScorerStats(
                total_evaluations=total,
                unique_agents=unique,
                overall_avg_composite=avg_composite,
                overall_avg_calibration=avg_calibration,
                best_reasoner=best.agent_id,
            )

    # =========================================================================
    # State
    # =========================================================================

    @property
    def evaluation_count(self) -> int:
        """Total number of stored evaluations."""
        return len(self._evaluations)

    def list_agents(self) -> list[str]:
        """List all tracked agent IDs, sorted alphabetically."""
        with self._lock:
            return sorted(self._profiles.keys())

    def clear(self) -> None:
        """Clear all evaluations, profiles, and reset counter."""
        with self._lock:
            self._evaluations.clear()
            self._profiles.clear()
            self._counter = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialise scorer state as a dict.

        Computes stats before acquiring the lock to avoid re-entrant
        locking (get_stats acquires self._lock internally).
        """
        stats = self.get_stats()
        with self._lock:
            return {
                "max_evaluations": self._max_evaluations,
                "evaluation_count": len(self._evaluations),
                "agent_count": len(self._profiles),
                "stats": stats.to_dict(),
            }


# =============================================================================
# Global Singleton
# =============================================================================

_scorer: ReasoningQualityScorer | None = None
_scorer_lock = threading.Lock()


def get_quality_scorer() -> ReasoningQualityScorer:
    """Get or create the global reasoning quality scorer."""
    global _scorer
    if _scorer is None:
        with _scorer_lock:
            if _scorer is None:
                _scorer = ReasoningQualityScorer()
    return _scorer


def reset_quality_scorer() -> None:
    """Reset the global reasoning quality scorer (for testing)."""
    global _scorer
    _scorer = None
