"""
Error Pattern Analyzer - Detect recurring error patterns across NEXUS subsystems.

V12.4 COGNITIVE BOOST

Tracks error occurrences, aggregates metrics per category, and detects
patterns such as recurring failures, cascading errors, and agent-specific
issues. Designed to feed into HiveMind DIAGNOSIS phase and CEREBRO dashboards.

Usage:
    from core.observability.telemetry.error_pattern_analyzer import get_error_analyzer

    analyzer = get_error_analyzer()
    analyzer.record_error(
        category="timeout",
        message="Gemini driver timed out after 30s",
        source="llm_invoke",
        agent_id="gemini",
        phase="EXECUTION",
    )

    patterns = analyzer.detect_patterns(min_count=3)
    stats = analyzer.get_stats()
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

MAX_ERRORS = 50_000

ERROR_CATEGORIES = {
    "timeout",
    "budget",
    "validation",
    "dependency",
    "auth",
    "internal",
    "external",
    "unknown",
}


# =============================================================================
# Dataclasses
# =============================================================================


@dataclass
class ErrorRecord:
    """A single error occurrence."""

    error_id: str = ""
    category: str = "unknown"
    message: str = ""
    source: str = ""
    agent_id: str = ""
    phase: str = ""
    recovered: bool = False
    recovery_ms: float = 0.0
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_id": self.error_id,
            "category": self.category,
            "message": self.message,
            "source": self.source,
            "agent_id": self.agent_id,
            "phase": self.phase,
            "recovered": self.recovered,
            "recovery_ms": self.recovery_ms,
            "timestamp": self.timestamp,
        }


@dataclass
class ErrorCategoryMetrics:
    """Aggregated metrics for a single error category."""

    category: str = ""
    total_count: int = 0
    recovered_count: int = 0
    total_recovery_ms: float = 0.0

    @property
    def recovery_rate(self) -> float:
        """Fraction of errors that were recovered from."""
        if self.total_count > 0:
            return self.recovered_count / self.total_count
        return 0.0

    @property
    def avg_recovery_ms(self) -> float:
        """Average recovery time in milliseconds."""
        if self.recovered_count > 0:
            return self.total_recovery_ms / self.recovered_count
        return 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "total_count": self.total_count,
            "recovered_count": self.recovered_count,
            "total_recovery_ms": round(self.total_recovery_ms, 2),
            "recovery_rate": round(self.recovery_rate, 4),
            "avg_recovery_ms": round(self.avg_recovery_ms, 2),
        }


@dataclass
class ErrorPattern:
    """A detected error pattern."""

    pattern_type: str = ""
    category: str = ""
    details: str = ""
    count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern_type": self.pattern_type,
            "category": self.category,
            "details": self.details,
            "count": self.count,
        }


@dataclass
class AnalyzerStats:
    """Overall error analyzer statistics."""

    total_errors: int = 0
    unique_categories: int = 0
    overall_recovery_rate: float = 0.0
    most_common_category: str = ""
    most_error_prone_agent: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_errors": self.total_errors,
            "unique_categories": self.unique_categories,
            "overall_recovery_rate": round(self.overall_recovery_rate, 4),
            "most_common_category": self.most_common_category,
            "most_error_prone_agent": self.most_error_prone_agent,
        }


# =============================================================================
# Error Pattern Analyzer
# =============================================================================


class ErrorPatternAnalyzer:
    """
    Analyzes error patterns across NEXUS subsystems.

    Tracks error occurrences with bounded FIFO history, aggregates metrics
    per category and agent, and detects recurring or agent-specific patterns.

    Thread-safe via threading.Lock().
    """

    def __init__(self, max_errors: int = MAX_ERRORS) -> None:
        self._errors: list[ErrorRecord] = []
        self._category_metrics: dict[str, ErrorCategoryMetrics] = {}
        self._agent_errors: dict[str, int] = {}
        self._max_errors = max_errors
        self._lock = threading.Lock()
        self._counter = 0

    # =========================================================================
    # Record
    # =========================================================================

    def record_error(
        self,
        category: str = "unknown",
        message: str = "",
        source: str = "",
        agent_id: str = "",
        phase: str = "",
        recovered: bool = False,
        recovery_ms: float = 0.0,
    ) -> ErrorRecord:
        """
        Record a new error occurrence.

        Args:
            category: Error category (one of ERROR_CATEGORIES).
            message: Human-readable error description.
            source: Where the error originated (e.g. "phase_execution").
            agent_id: Which agent caused the error.
            phase: Which HiveMind phase was active.
            recovered: Whether the error was recovered from.
            recovery_ms: Time to recover in milliseconds.

        Returns:
            The recorded ErrorRecord.
        """
        with self._lock:
            error_id = f"err_{self._counter:06d}"
            self._counter += 1

            record = ErrorRecord(
                error_id=error_id,
                category=category,
                message=message,
                source=source,
                agent_id=agent_id,
                phase=phase,
                recovered=recovered,
                recovery_ms=recovery_ms,
            )

            # Update category metrics
            if category not in self._category_metrics:
                self._category_metrics[category] = ErrorCategoryMetrics(
                    category=category,
                )
            metrics = self._category_metrics[category]
            metrics.total_count += 1
            if recovered:
                metrics.recovered_count += 1
                metrics.total_recovery_ms += recovery_ms

            # Update agent errors
            if agent_id:
                self._agent_errors[agent_id] = self._agent_errors.get(agent_id, 0) + 1

            # FIFO eviction
            if len(self._errors) >= self._max_errors:
                self._errors.pop(0)

            self._errors.append(record)

        return record

    # =========================================================================
    # Query: Category Metrics
    # =========================================================================

    def get_category_metrics(self, category: str) -> ErrorCategoryMetrics | None:
        """
        Get aggregated metrics for a specific error category.

        Args:
            category: The error category to look up.

        Returns:
            ErrorCategoryMetrics or None if category has no recorded errors.
        """
        with self._lock:
            return self._category_metrics.get(category)

    def get_all_metrics(self) -> list[ErrorCategoryMetrics]:
        """
        Get metrics for all categories, sorted by total_count descending.

        Returns:
            List of ErrorCategoryMetrics.
        """
        with self._lock:
            metrics = list(self._category_metrics.values())
        metrics.sort(key=lambda m: m.total_count, reverse=True)
        return metrics

    # =========================================================================
    # Query: By Agent / Category
    # =========================================================================

    def get_errors_by_agent(self, agent_id: str) -> list[ErrorRecord]:
        """
        Get all error records for a specific agent.

        Args:
            agent_id: The agent identifier.

        Returns:
            List of ErrorRecord for that agent.
        """
        with self._lock:
            return [e for e in self._errors if e.agent_id == agent_id]

    def get_errors_by_category(self, category: str) -> list[ErrorRecord]:
        """
        Get all error records for a specific category.

        Args:
            category: The error category.

        Returns:
            List of ErrorRecord for that category.
        """
        with self._lock:
            return [e for e in self._errors if e.category == category]

    # =========================================================================
    # Pattern Detection
    # =========================================================================

    def detect_patterns(self, min_count: int = 3) -> list[ErrorPattern]:
        """
        Detect recurring and agent-specific error patterns.

        Args:
            min_count: Minimum occurrences to qualify as a pattern.

        Returns:
            List of detected ErrorPattern instances.
        """
        patterns: list[ErrorPattern] = []

        with self._lock:
            # Recurring: categories with >= min_count errors
            for cat, metrics in self._category_metrics.items():
                if metrics.total_count >= min_count:
                    patterns.append(
                        ErrorPattern(
                            pattern_type="recurring",
                            category=cat,
                            details=(
                                f"Category '{cat}' has {metrics.total_count} errors "
                                f"(recovery rate: {metrics.recovery_rate:.1%})"
                            ),
                            count=metrics.total_count,
                        )
                    )

            # Agent-specific: agents with >= min_count errors
            for agent_id, count in self._agent_errors.items():
                if count >= min_count:
                    patterns.append(
                        ErrorPattern(
                            pattern_type="agent_specific",
                            category="",
                            details=(f"Agent '{agent_id}' has {count} errors"),
                            count=count,
                        )
                    )

        return patterns

    # =========================================================================
    # Recent / Top Agents
    # =========================================================================

    def get_recent_errors(self, limit: int = 20) -> list[ErrorRecord]:
        """
        Get the most recent error records.

        Args:
            limit: Maximum number of records to return.

        Returns:
            List of ErrorRecord, most recent last.
        """
        with self._lock:
            return list(self._errors[-limit:])

    def get_most_error_prone_agents(
        self,
        limit: int = 5,
    ) -> list[tuple[str, int]]:
        """
        Get agents ranked by error count, descending.

        Args:
            limit: Maximum number of agents to return.

        Returns:
            List of (agent_id, error_count) tuples.
        """
        with self._lock:
            items = list(self._agent_errors.items())
        items.sort(key=lambda x: x[1], reverse=True)
        return items[:limit]

    # =========================================================================
    # Stats
    # =========================================================================

    def get_stats(self) -> AnalyzerStats:
        """
        Compute overall analyzer statistics.

        Returns:
            AnalyzerStats with aggregated data.
        """
        with self._lock:
            total = len(self._errors)
            unique = len(self._category_metrics)

            # Overall recovery rate
            total_recovered = sum(m.recovered_count for m in self._category_metrics.values())
            total_all = sum(m.total_count for m in self._category_metrics.values())
            recovery_rate = total_recovered / total_all if total_all > 0 else 0.0

            # Most common category
            most_common = ""
            if self._category_metrics:
                most_common = max(
                    self._category_metrics.values(),
                    key=lambda m: m.total_count,
                ).category

            # Most error-prone agent
            most_error_prone = ""
            if self._agent_errors:
                most_error_prone = max(
                    self._agent_errors,
                    key=self._agent_errors.get,
                )

        return AnalyzerStats(
            total_errors=total,
            unique_categories=unique,
            overall_recovery_rate=recovery_rate,
            most_common_category=most_common,
            most_error_prone_agent=most_error_prone,
        )

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def error_count(self) -> int:
        """Total number of errors currently in the buffer."""
        with self._lock:
            return len(self._errors)

    # =========================================================================
    # Clear / Export
    # =========================================================================

    def clear(self) -> None:
        """Clear all recorded errors and metrics."""
        with self._lock:
            self._errors.clear()
            self._category_metrics.clear()
            self._agent_errors.clear()
            self._counter = 0

    def to_dict(self) -> dict[str, Any]:
        """
        Export analyzer state for diagnostics.

        NOTE: get_stats() is called BEFORE acquiring self._lock to
        avoid reentrant locking (threading.Lock is non-reentrant).
        """
        stats = self.get_stats()
        with self._lock:
            return {
                "stats": stats.to_dict(),
                "error_count": len(self._errors),
                "max_errors": self._max_errors,
                "categories": [
                    m.to_dict()
                    for m in sorted(
                        self._category_metrics.values(),
                        key=lambda m: m.total_count,
                        reverse=True,
                    )
                ],
                "agent_errors": dict(self._agent_errors),
            }


# =============================================================================
# Global Singleton
# =============================================================================

_analyzer: ErrorPatternAnalyzer | None = None
_analyzer_lock = threading.Lock()


def get_error_analyzer() -> ErrorPatternAnalyzer:
    """Get or create the global error pattern analyzer (double-checked locking)."""
    global _analyzer
    if _analyzer is None:
        with _analyzer_lock:
            if _analyzer is None:
                _analyzer = ErrorPatternAnalyzer()
    return _analyzer


def reset_error_analyzer() -> None:
    """Reset the global error pattern analyzer (for testing)."""
    global _analyzer
    _analyzer = None
