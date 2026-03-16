"""
Mode Effectiveness Evaluator - Evaluate swarm mode effectiveness per task type.

V12.4 COGNITIVE BOOST

Tracks swarm mode execution outcomes across task domains and complexity levels,
computing per-mode summaries (success rate, average quality, average duration)
and domain-specific mode rankings to guide future mode selection.

Usage:
    from core.intelligence.swarm.mode_effectiveness_evaluator import get_mode_evaluator

    evaluator = get_mode_evaluator()

    # Record an evaluation
    ev = evaluator.record_evaluation(
        mode="LEAD_SUPPORT",
        task_domain="coding",
        complexity="MODERATE",
        quality_score=0.92,
        duration_ms=1450.0,
        success=True,
        agent_count=2,
    )

    # Query effectiveness
    best = evaluator.get_best_mode_for_domain("coding")
    ranking = evaluator.get_domain_mode_ranking("coding")
    summaries = evaluator.get_all_summaries()
    stats = evaluator.get_stats()
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
# Helpers
# =============================================================================


def _utc_iso_now() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(UTC).isoformat()


# =============================================================================
# Types
# =============================================================================


@dataclass
class ModeEvaluation:
    """Record of a swarm mode execution outcome."""

    mode: str = ""
    task_domain: str = ""
    complexity: str = ""
    quality_score: float = 0.0
    duration_ms: float = 0.0
    success: bool = True
    agent_count: int = 0
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = _utc_iso_now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "task_domain": self.task_domain,
            "complexity": self.complexity,
            "quality_score": round(self.quality_score, 4),
            "duration_ms": round(self.duration_ms, 2),
            "success": self.success,
            "agent_count": self.agent_count,
            "timestamp": self.timestamp,
        }


@dataclass
class ModeEffectivenessSummary:
    """Aggregated effectiveness per mode."""

    mode: str = ""
    total_evaluations: int = 0
    successes: int = 0
    total_quality: float = 0.0
    total_duration_ms: float = 0.0

    @property
    def success_rate(self) -> float:
        if self.total_evaluations > 0:
            return self.successes / self.total_evaluations
        return 0.0

    @property
    def avg_quality(self) -> float:
        if self.total_evaluations > 0:
            return self.total_quality / self.total_evaluations
        return 0.0

    @property
    def avg_duration_ms(self) -> float:
        if self.total_evaluations > 0:
            return self.total_duration_ms / self.total_evaluations
        return 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "total_evaluations": self.total_evaluations,
            "successes": self.successes,
            "total_quality": round(self.total_quality, 4),
            "total_duration_ms": round(self.total_duration_ms, 2),
            "success_rate": round(self.success_rate, 4),
            "avg_quality": round(self.avg_quality, 4),
            "avg_duration_ms": round(self.avg_duration_ms, 2),
        }


@dataclass
class EvaluatorStats:
    """Overall evaluator statistics."""

    total_evaluations: int = 0
    unique_modes: int = 0
    unique_domains: int = 0
    overall_success_rate: float = 0.0
    overall_avg_quality: float = 0.0
    best_mode: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_evaluations": self.total_evaluations,
            "unique_modes": self.unique_modes,
            "unique_domains": self.unique_domains,
            "overall_success_rate": round(self.overall_success_rate, 4),
            "overall_avg_quality": round(self.overall_avg_quality, 4),
            "best_mode": self.best_mode,
        }


# =============================================================================
# Mode Effectiveness Evaluator
# =============================================================================


class ModeEffectivenessEvaluator:
    """
    Evaluate swarm mode effectiveness per task type.

    Features:
    - Record mode execution outcomes (quality, duration, success)
    - Aggregate per-mode summaries with computed properties
    - Domain-specific mode rankings for intelligent routing
    - Best-mode lookup per domain
    - Bounded history with FIFO eviction
    - Thread-safe operations
    """

    def __init__(self, max_evaluations: int = MAX_EVALUATIONS) -> None:
        self._evaluations: list[ModeEvaluation] = []
        self._mode_summaries: dict[str, ModeEffectivenessSummary] = {}
        self._domain_modes: dict[str, dict[str, list[float]]] = {}
        self._max_evaluations = max_evaluations
        self._lock = threading.Lock()

    # =========================================================================
    # Recording
    # =========================================================================

    def record_evaluation(
        self,
        mode: str,
        task_domain: str = "",
        complexity: str = "",
        quality_score: float = 0.0,
        duration_ms: float = 0.0,
        success: bool = True,
        agent_count: int = 0,
    ) -> ModeEvaluation:
        """
        Record a swarm mode execution outcome.

        Args:
            mode: Swarm mode used (PARALLEL, SEQUENTIAL, etc.)
            task_domain: Domain of the task (coding, security, research, etc.)
            complexity: Task complexity (TRIVIAL, SIMPLE, MODERATE, COMPLEX, EXPERT)
            quality_score: Outcome quality from 0.0 to 1.0
            duration_ms: Execution duration in milliseconds
            success: Whether the execution succeeded
            agent_count: Number of agents involved

        Returns:
            The recorded ModeEvaluation
        """
        q = max(0.0, min(1.0, quality_score))

        evaluation = ModeEvaluation(
            mode=mode,
            task_domain=task_domain,
            complexity=complexity,
            quality_score=q,
            duration_ms=duration_ms,
            success=success,
            agent_count=agent_count,
        )

        with self._lock:
            # Update mode summary
            if mode not in self._mode_summaries:
                self._mode_summaries[mode] = ModeEffectivenessSummary(mode=mode)

            summary = self._mode_summaries[mode]
            summary.total_evaluations += 1
            if success:
                summary.successes += 1
            summary.total_quality += q
            summary.total_duration_ms += duration_ms

            # Track domain -> mode -> quality scores
            if task_domain:
                if task_domain not in self._domain_modes:
                    self._domain_modes[task_domain] = {}
                if mode not in self._domain_modes[task_domain]:
                    self._domain_modes[task_domain][mode] = []
                self._domain_modes[task_domain][mode].append(q)

            # FIFO eviction
            self._evaluations.append(evaluation)
            while len(self._evaluations) > self._max_evaluations:
                self._evaluations.pop(0)

        return evaluation

    # =========================================================================
    # Summaries
    # =========================================================================

    def get_mode_summary(self, mode: str) -> ModeEffectivenessSummary | None:
        """
        Get the effectiveness summary for a specific mode.

        Args:
            mode: Swarm mode name

        Returns:
            ModeEffectivenessSummary or None if no data
        """
        with self._lock:
            summary = self._mode_summaries.get(mode)
            if summary is None:
                return None
            # Return a copy to avoid external mutation
            return ModeEffectivenessSummary(
                mode=summary.mode,
                total_evaluations=summary.total_evaluations,
                successes=summary.successes,
                total_quality=summary.total_quality,
                total_duration_ms=summary.total_duration_ms,
            )

    def get_all_summaries(self) -> list[ModeEffectivenessSummary]:
        """
        Get effectiveness summaries for all modes, sorted by avg_quality descending.

        Returns:
            List of ModeEffectivenessSummary sorted by avg_quality desc
        """
        with self._lock:
            summaries = [
                ModeEffectivenessSummary(
                    mode=s.mode,
                    total_evaluations=s.total_evaluations,
                    successes=s.successes,
                    total_quality=s.total_quality,
                    total_duration_ms=s.total_duration_ms,
                )
                for s in self._mode_summaries.values()
            ]
        summaries.sort(key=lambda s: s.avg_quality, reverse=True)
        return summaries

    # =========================================================================
    # Domain Analysis
    # =========================================================================

    def get_best_mode_for_domain(self, domain: str) -> str | None:
        """
        Find the mode with the highest average quality for a domain.

        Args:
            domain: Task domain to query

        Returns:
            Mode name with highest avg quality, or None if no data
        """
        with self._lock:
            mode_scores = self._domain_modes.get(domain)
            if not mode_scores:
                return None

            best_mode: str | None = None
            best_avg = -1.0

            for mode, scores in mode_scores.items():
                if scores:
                    avg = sum(scores) / len(scores)
                    if avg > best_avg:
                        best_avg = avg
                        best_mode = mode

            return best_mode

    def get_domain_mode_ranking(self, domain: str) -> list[tuple[str, float]]:
        """
        Get modes ranked by average quality for a domain.

        Args:
            domain: Task domain to query

        Returns:
            List of (mode, avg_quality) tuples sorted by avg_quality desc
        """
        with self._lock:
            mode_scores = self._domain_modes.get(domain)
            if not mode_scores:
                return []

            ranking: list[tuple[str, float]] = []
            for mode, scores in mode_scores.items():
                if scores:
                    avg = sum(scores) / len(scores)
                    ranking.append((mode, avg))

        ranking.sort(key=lambda x: x[1], reverse=True)
        return ranking

    # =========================================================================
    # Queries
    # =========================================================================

    def get_recent_evaluations(
        self,
        limit: int = 20,
        mode: str = "",
    ) -> list[ModeEvaluation]:
        """
        Get the most recent evaluations, optionally filtered by mode.

        Args:
            limit: Maximum number of evaluations to return
            mode: If non-empty, filter to this mode only

        Returns:
            List of ModeEvaluation (newest first)
        """
        with self._lock:
            if mode:
                filtered = [e for e in self._evaluations if e.mode == mode]
            else:
                filtered = list(self._evaluations)

        # Newest first
        filtered.reverse()
        return filtered[:limit]

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> EvaluatorStats:
        """Get overall evaluator statistics."""
        with self._lock:
            total = len(self._evaluations)
            if total == 0:
                return EvaluatorStats()

            unique_modes = len(self._mode_summaries)
            unique_domains = len(self._domain_modes)

            total_successes = sum(s.successes for s in self._mode_summaries.values())
            total_quality = sum(s.total_quality for s in self._mode_summaries.values())
            total_evals = sum(s.total_evaluations for s in self._mode_summaries.values())

            overall_success_rate = total_successes / total_evals if total_evals > 0 else 0.0
            overall_avg_quality = total_quality / total_evals if total_evals > 0 else 0.0

            # Best mode by avg_quality
            best_mode = ""
            best_avg = -1.0
            for s in self._mode_summaries.values():
                avg_q = s.avg_quality
                if avg_q > best_avg:
                    best_avg = avg_q
                    best_mode = s.mode

        return EvaluatorStats(
            total_evaluations=total,
            unique_modes=unique_modes,
            unique_domains=unique_domains,
            overall_success_rate=overall_success_rate,
            overall_avg_quality=overall_avg_quality,
            best_mode=best_mode,
        )

    # =========================================================================
    # State
    # =========================================================================

    @property
    def evaluation_count(self) -> int:
        return len(self._evaluations)

    def list_modes(self) -> list[str]:
        """List all recorded mode names, sorted."""
        with self._lock:
            return sorted(self._mode_summaries.keys())

    def list_domains(self) -> list[str]:
        """List all recorded domain names, sorted."""
        with self._lock:
            return sorted(self._domain_modes.keys())

    def clear(self) -> None:
        """Clear all tracked data."""
        with self._lock:
            self._evaluations.clear()
            self._mode_summaries.clear()
            self._domain_modes.clear()

    def to_dict(self) -> dict[str, Any]:
        # CRITICAL: call get_stats() BEFORE acquiring self._lock
        # to avoid deadlock (get_stats also acquires the lock).
        stats = self.get_stats()
        with self._lock:
            return {
                "evaluation_count": len(self._evaluations),
                "max_evaluations": self._max_evaluations,
                "stats": stats.to_dict(),
            }


# =============================================================================
# Global Instance
# =============================================================================

_evaluator: ModeEffectivenessEvaluator | None = None
_evaluator_lock = threading.Lock()


def get_mode_evaluator() -> ModeEffectivenessEvaluator:
    """Get or create the global mode effectiveness evaluator."""
    global _evaluator
    if _evaluator is None:
        with _evaluator_lock:
            if _evaluator is None:
                _evaluator = ModeEffectivenessEvaluator()
    return _evaluator


def reset_mode_evaluator() -> None:
    """Reset the global mode effectiveness evaluator (for testing)."""
    global _evaluator
    _evaluator = None
