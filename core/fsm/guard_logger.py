"""
FSM Guard Logger - Track guard evaluation outcomes and effectiveness.

V12.4 COGNITIVE BOOST

Logs which FSM transition guards evaluate to true/false, their latency,
and provides metrics for guard effectiveness analysis.

Usage:
    from core.fsm.guard_logger import get_guard_logger

    logger = get_guard_logger()

    # Record a guard evaluation
    logger.record_evaluation(
        "can_brainstorm", "idle", "brainstorming", True, latency_ms=0.3
    )

    # Query blocked transitions
    blocked = logger.get_blocked_transitions(guard_name="auth_guard")

    # Get most blocking guards
    worst = logger.get_most_blocking_guards(limit=3)
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

MAX_EVALUATIONS = 50000


# =============================================================================
# Types
# =============================================================================


@dataclass
class GuardEvaluation:
    """A single guard evaluation record."""

    guard_name: str
    from_state: str
    to_state: str
    result: bool  # True = allowed, False = blocked
    latency_ms: float = 0.0
    session_id: str = ""
    timestamp: float = field(default_factory=time.monotonic)
    reason: str = ""  # why guard blocked (only when result=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "guard_name": self.guard_name,
            "from_state": self.from_state,
            "to_state": self.to_state,
            "result": self.result,
            "latency_ms": round(self.latency_ms, 3),
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "reason": self.reason,
        }


@dataclass
class GuardMetrics:
    """Aggregated metrics for a single guard."""

    guard_name: str
    total_evaluations: int = 0
    allowed_count: int = 0
    blocked_count: int = 0
    avg_latency_ms: float = 0.0

    @property
    def allow_rate(self) -> float:
        if self.total_evaluations == 0:
            return 0.0
        return self.allowed_count / self.total_evaluations

    @property
    def block_rate(self) -> float:
        if self.total_evaluations == 0:
            return 0.0
        return self.blocked_count / self.total_evaluations

    def to_dict(self) -> dict[str, Any]:
        return {
            "guard_name": self.guard_name,
            "total_evaluations": self.total_evaluations,
            "allowed_count": self.allowed_count,
            "blocked_count": self.blocked_count,
            "avg_latency_ms": round(self.avg_latency_ms, 3),
            "allow_rate": round(self.allow_rate, 4),
            "block_rate": round(self.block_rate, 4),
        }


@dataclass
class BlockedTransition:
    """Record of a guard blocking a transition."""

    from_state: str
    to_state: str
    guard_name: str
    reason: str = ""
    session_id: str = ""
    timestamp: float = field(default_factory=time.monotonic)

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_state": self.from_state,
            "to_state": self.to_state,
            "guard_name": self.guard_name,
            "reason": self.reason,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
        }


@dataclass
class GuardLoggerStats:
    """Overall guard logger statistics."""

    total_evaluations: int
    total_blocked: int
    total_allowed: int
    unique_guards: int
    unique_transitions: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_evaluations": self.total_evaluations,
            "total_blocked": self.total_blocked,
            "total_allowed": self.total_allowed,
            "unique_guards": self.unique_guards,
            "unique_transitions": self.unique_transitions,
        }


# =============================================================================
# Guard Logger
# =============================================================================


class GuardLogger:
    """
    FSM guard evaluation logger.

    Features:
    - Record guard evaluation outcomes (allowed/blocked)
    - Track per-guard metrics with running average latency
    - Query blocked transitions by guard or state
    - Identify most-blocking guards
    - Bounded history (auto-eviction)
    - Thread-safe
    """

    def __init__(self, *, max_evaluations: int = MAX_EVALUATIONS):
        self._evaluations: list[GuardEvaluation] = []
        self._metrics: dict[str, GuardMetrics] = {}
        self._blocked: list[BlockedTransition] = []
        self._max_evaluations = max_evaluations
        self._lock = threading.Lock()

    # =========================================================================
    # Recording
    # =========================================================================

    def record_evaluation(
        self,
        guard_name: str,
        from_state: str,
        to_state: str,
        result: bool,
        *,
        latency_ms: float = 0.0,
        session_id: str = "",
        reason: str = "",
    ) -> GuardEvaluation:
        """
        Record a guard evaluation.

        Args:
            guard_name: Name of the guard that was evaluated.
            from_state: FSM state before the transition attempt.
            to_state: FSM state the transition targets.
            result: True if the guard allowed the transition, False if blocked.
            latency_ms: Time taken by the guard evaluation.
            session_id: Session identifier.
            reason: Why the guard blocked (only meaningful when result=False).

        Returns:
            The recorded GuardEvaluation.
        """
        evaluation = GuardEvaluation(
            guard_name=guard_name,
            from_state=from_state,
            to_state=to_state,
            result=result,
            latency_ms=latency_ms,
            session_id=session_id,
            reason=reason,
        )
        with self._lock:
            self._evaluations.append(evaluation)
            # Evict oldest if over limit
            if len(self._evaluations) > self._max_evaluations:
                self._evaluations = self._evaluations[-self._max_evaluations :]

            # Update aggregated metrics
            metrics = self._metrics.get(guard_name)
            if metrics is None:
                metrics = GuardMetrics(guard_name=guard_name)
                self._metrics[guard_name] = metrics
            prev_total = metrics.total_evaluations
            metrics.total_evaluations += 1
            if result:
                metrics.allowed_count += 1
            else:
                metrics.blocked_count += 1
                # Record blocked transition
                self._blocked.append(
                    BlockedTransition(
                        from_state=from_state,
                        to_state=to_state,
                        guard_name=guard_name,
                        reason=reason,
                        session_id=session_id,
                    )
                )
            # Running average latency
            metrics.avg_latency_ms = (metrics.avg_latency_ms * prev_total + latency_ms) / metrics.total_evaluations
        return evaluation

    # =========================================================================
    # Queries
    # =========================================================================

    def get_guard_metrics(self, guard_name: str) -> GuardMetrics | None:
        """Get aggregated metrics for a specific guard."""
        with self._lock:
            metrics = self._metrics.get(guard_name)
            if metrics is None:
                return None
            # Return a copy to avoid external mutation
            return GuardMetrics(
                guard_name=metrics.guard_name,
                total_evaluations=metrics.total_evaluations,
                allowed_count=metrics.allowed_count,
                blocked_count=metrics.blocked_count,
                avg_latency_ms=metrics.avg_latency_ms,
            )

    def get_all_metrics(self) -> list[GuardMetrics]:
        """Get metrics for all guards, sorted by total_evaluations descending."""
        with self._lock:
            result = [
                GuardMetrics(
                    guard_name=m.guard_name,
                    total_evaluations=m.total_evaluations,
                    allowed_count=m.allowed_count,
                    blocked_count=m.blocked_count,
                    avg_latency_ms=m.avg_latency_ms,
                )
                for m in self._metrics.values()
            ]
        result.sort(key=lambda m: m.total_evaluations, reverse=True)
        return result

    def get_blocked_transitions(
        self,
        *,
        guard_name: str | None = None,
        from_state: str | None = None,
        limit: int = 50,
    ) -> list[BlockedTransition]:
        """
        Get blocked transitions, most recent first.

        Args:
            guard_name: Filter by guard name.
            from_state: Filter by originating state.
            limit: Maximum number of results.

        Returns:
            List of BlockedTransition, most recent first.
        """
        with self._lock:
            items = list(reversed(self._blocked))
        filtered = items
        if guard_name is not None:
            filtered = [b for b in filtered if b.guard_name == guard_name]
        if from_state is not None:
            filtered = [b for b in filtered if b.from_state == from_state]
        return filtered[:limit]

    def get_evaluations(
        self,
        *,
        guard_name: str | None = None,
        from_state: str | None = None,
        to_state: str | None = None,
        result: bool | None = None,
        limit: int = 100,
    ) -> list[GuardEvaluation]:
        """
        Get evaluations with optional filters, most recent first.

        Args:
            guard_name: Filter by guard name.
            from_state: Filter by originating state.
            to_state: Filter by target state.
            result: Filter by outcome (True=allowed, False=blocked).
            limit: Maximum number of results.

        Returns:
            List of GuardEvaluation, most recent first.
        """
        with self._lock:
            items = list(reversed(self._evaluations))
        filtered = items
        if guard_name is not None:
            filtered = [e for e in filtered if e.guard_name == guard_name]
        if from_state is not None:
            filtered = [e for e in filtered if e.from_state == from_state]
        if to_state is not None:
            filtered = [e for e in filtered if e.to_state == to_state]
        if result is not None:
            filtered = [e for e in filtered if e.result == result]
        return filtered[:limit]

    def get_most_blocking_guards(self, *, limit: int = 5) -> list[GuardMetrics]:
        """
        Get guards sorted by blocked_count descending.

        Args:
            limit: Maximum number of results.

        Returns:
            List of GuardMetrics for the most-blocking guards.
        """
        with self._lock:
            result = [
                GuardMetrics(
                    guard_name=m.guard_name,
                    total_evaluations=m.total_evaluations,
                    allowed_count=m.allowed_count,
                    blocked_count=m.blocked_count,
                    avg_latency_ms=m.avg_latency_ms,
                )
                for m in self._metrics.values()
            ]
        result.sort(key=lambda m: m.blocked_count, reverse=True)
        return result[:limit]

    # =========================================================================
    # State
    # =========================================================================

    def get_stats(self) -> GuardLoggerStats:
        """Get overall logger statistics."""
        with self._lock:
            transitions: set = set()
            for e in self._evaluations:
                transitions.add((e.from_state, e.to_state))
            return GuardLoggerStats(
                total_evaluations=len(self._evaluations),
                total_blocked=len(self._blocked),
                total_allowed=len(self._evaluations) - len(self._blocked),
                unique_guards=len(self._metrics),
                unique_transitions=len(transitions),
            )

    @property
    def evaluation_count(self) -> int:
        return len(self._evaluations)

    @property
    def blocked_count(self) -> int:
        return len(self._blocked)

    def clear(self) -> None:
        """Clear all evaluations, metrics, and blocked records."""
        with self._lock:
            self._evaluations.clear()
            self._metrics.clear()
            self._blocked.clear()

    def to_dict(self) -> dict[str, Any]:
        # Call get_stats() which acquires the lock internally;
        # do NOT acquire self._lock here to avoid re-entrant locking.
        stats = self.get_stats()
        return {
            "evaluation_count": self.evaluation_count,
            "blocked_count": self.blocked_count,
            "stats": stats.to_dict(),
        }


# =============================================================================
# Global Instance
# =============================================================================

_guard_logger: GuardLogger | None = None
_guard_logger_lock = threading.Lock()


def get_guard_logger() -> GuardLogger:
    """Get or create the global guard logger."""
    global _guard_logger
    if _guard_logger is None:
        with _guard_logger_lock:
            if _guard_logger is None:
                _guard_logger = GuardLogger()
    return _guard_logger


def reset_guard_logger() -> None:
    """Reset the global guard logger (for testing)."""
    global _guard_logger
    _guard_logger = None
