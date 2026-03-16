"""
Command Analytics - Track command usage analytics for NEXUS REPL.

V12.4 COGNITIVE BOOST

Tracks command invocation patterns:
- Per-command metrics (invocation count, success rate, duration)
- Recent invocation history with FIFO eviction
- Usage pattern detection (frequent, error-prone)
- Overall analytics statistics

Usage:
    from core.interface_pkg.interface.command_analytics import get_command_analytics

    analytics = get_command_analytics()
    analytics.record_invocation("/evolve", args="--strategy=creative", duration_ms=1200.0)
    metrics = analytics.get_command_metrics("/evolve")
    stats = analytics.get_stats()
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

MAX_INVOCATIONS = 50000


# =============================================================================
# Types
# =============================================================================


@dataclass
class CommandInvocation:
    """Record of a single command invocation."""

    command: str = ""
    args: str = ""
    timestamp: str = ""
    duration_ms: float = 0.0
    success: bool = True
    error: str = ""
    source: str = "repl"

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "args": self.args,
            "timestamp": self.timestamp,
            "duration_ms": self.duration_ms,
            "success": self.success,
            "error": self.error,
            "source": self.source,
        }


@dataclass
class CommandMetrics:
    """Aggregated metrics per command."""

    command: str = ""
    total_invocations: int = 0
    successes: int = 0
    failures: int = 0
    total_duration_ms: float = 0.0

    @property
    def success_rate(self) -> float:
        if self.total_invocations > 0:
            return self.successes / self.total_invocations
        return 0.0

    @property
    def avg_duration_ms(self) -> float:
        if self.total_invocations > 0:
            return self.total_duration_ms / self.total_invocations
        return 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "total_invocations": self.total_invocations,
            "successes": self.successes,
            "failures": self.failures,
            "total_duration_ms": round(self.total_duration_ms, 2),
            "success_rate": round(self.success_rate, 4),
            "avg_duration_ms": round(self.avg_duration_ms, 2),
        }


@dataclass
class UsagePattern:
    """Detected usage pattern."""

    pattern_type: str = ""
    command: str = ""
    details: str = ""
    count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern_type": self.pattern_type,
            "command": self.command,
            "details": self.details,
            "count": self.count,
        }


@dataclass
class AnalyticsStats:
    """Overall analytics statistics."""

    total_invocations: int = 0
    unique_commands: int = 0
    overall_success_rate: float = 0.0
    most_used_command: str = ""
    avg_duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_invocations": self.total_invocations,
            "unique_commands": self.unique_commands,
            "overall_success_rate": round(self.overall_success_rate, 4),
            "most_used_command": self.most_used_command,
            "avg_duration_ms": round(self.avg_duration_ms, 2),
        }


# =============================================================================
# Command Analytics
# =============================================================================


class CommandAnalytics:
    """
    Track command usage analytics with bounded history.

    Features:
    - Record invocations with timestamp and duration
    - Per-command aggregated metrics (success rate, avg duration)
    - FIFO eviction when invocation history exceeds max
    - Usage pattern detection (frequent commands, error-prone commands)
    - Thread-safe via threading.Lock()
    """

    def __init__(self, max_invocations: int = MAX_INVOCATIONS) -> None:
        self._invocations: list[CommandInvocation] = []
        self._metrics: dict[str, CommandMetrics] = {}
        self._max_invocations = max_invocations
        self._lock = threading.Lock()

    # =========================================================================
    # Recording
    # =========================================================================

    def record_invocation(
        self,
        command: str,
        args: str = "",
        duration_ms: float = 0.0,
        success: bool = True,
        error: str = "",
        source: str = "repl",
    ) -> CommandInvocation:
        """Record a command invocation and update aggregated metrics."""
        invocation = CommandInvocation(
            command=command,
            args=args,
            timestamp=datetime.now(UTC).isoformat(),
            duration_ms=duration_ms,
            success=success,
            error=error,
            source=source,
        )
        with self._lock:
            # Update metrics for this command
            if command not in self._metrics:
                self._metrics[command] = CommandMetrics(command=command)
            m = self._metrics[command]
            m.total_invocations += 1
            if success:
                m.successes += 1
            else:
                m.failures += 1
            m.total_duration_ms += duration_ms

            # Add to history with FIFO eviction
            if len(self._invocations) >= self._max_invocations:
                self._invocations.pop(0)
            self._invocations.append(invocation)

        return invocation

    # =========================================================================
    # Metrics Queries
    # =========================================================================

    def get_command_metrics(self, command: str) -> CommandMetrics | None:
        """Get aggregated metrics for a specific command."""
        with self._lock:
            return self._metrics.get(command)

    def get_all_metrics(self) -> list[CommandMetrics]:
        """Return all command metrics sorted by total_invocations descending."""
        with self._lock:
            return sorted(
                self._metrics.values(),
                key=lambda m: m.total_invocations,
                reverse=True,
            )

    def get_most_used(self, limit: int = 10) -> list[CommandMetrics]:
        """Return top N commands by total_invocations."""
        with self._lock:
            return sorted(
                self._metrics.values(),
                key=lambda m: m.total_invocations,
                reverse=True,
            )[:limit]

    def get_error_prone(self, min_invocations: int = 3) -> list[CommandMetrics]:
        """Return commands with success_rate < 0.8 and at least min_invocations.

        Sorted by success_rate ascending (worst first).
        """
        with self._lock:
            return sorted(
                [m for m in self._metrics.values() if m.total_invocations >= min_invocations and m.success_rate < 0.8],
                key=lambda m: m.success_rate,
            )

    # =========================================================================
    # Invocation Queries
    # =========================================================================

    def get_recent_invocations(self, limit: int = 20, command: str = "") -> list[CommandInvocation]:
        """Return last N invocations, optionally filtered by command name."""
        with self._lock:
            if command:
                filtered = [inv for inv in self._invocations if inv.command == command]
            else:
                filtered = list(self._invocations)
            return filtered[-limit:]

    # =========================================================================
    # Pattern Detection
    # =========================================================================

    def detect_patterns(self) -> list[UsagePattern]:
        """Detect usage patterns from recorded metrics.

        Patterns detected:
        - frequent_command: commands with >= 10 invocations
        - error_prone: commands with success_rate < 0.5 and >= 3 invocations
        """
        patterns: list[UsagePattern] = []
        with self._lock:
            for m in self._metrics.values():
                if m.total_invocations >= 10:
                    patterns.append(
                        UsagePattern(
                            pattern_type="frequent_command",
                            command=m.command,
                            details=f"{m.total_invocations} invocations",
                            count=m.total_invocations,
                        )
                    )
                if m.total_invocations >= 3 and m.success_rate < 0.5:
                    patterns.append(
                        UsagePattern(
                            pattern_type="error_prone",
                            command=m.command,
                            details=(f"success_rate={m.success_rate:.2%} over {m.total_invocations} invocations"),
                            count=m.failures,
                        )
                    )
        return patterns

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> AnalyticsStats:
        """Compute overall analytics statistics."""
        with self._lock:
            total = sum(m.total_invocations for m in self._metrics.values())
            successes = sum(m.successes for m in self._metrics.values())
            total_duration = sum(m.total_duration_ms for m in self._metrics.values())
            unique = len(self._metrics)

            most_used = ""
            if self._metrics:
                most_used = max(
                    self._metrics.values(),
                    key=lambda m: m.total_invocations,
                ).command

            return AnalyticsStats(
                total_invocations=total,
                unique_commands=unique,
                overall_success_rate=(successes / total if total > 0 else 0.0),
                most_used_command=most_used,
                avg_duration_ms=(total_duration / total if total > 0 else 0.0),
            )

    # =========================================================================
    # State
    # =========================================================================

    @property
    def invocation_count(self) -> int:
        """Number of invocation records currently stored."""
        return len(self._invocations)

    def list_commands(self) -> list[str]:
        """Return sorted list of all tracked command names."""
        with self._lock:
            return sorted(self._metrics.keys())

    def clear(self) -> None:
        """Reset all analytics state."""
        with self._lock:
            self._invocations.clear()
            self._metrics.clear()

    def to_dict(self) -> dict[str, Any]:
        """Serialize analytics state to dict.

        Note: get_stats() is called BEFORE acquiring self._lock
        to avoid deadlock (threading.Lock is not reentrant).
        """
        stats = self.get_stats()
        with self._lock:
            return {
                "max_invocations": self._max_invocations,
                "invocation_count": len(self._invocations),
                "stats": stats.to_dict(),
            }


# =============================================================================
# Global Instance
# =============================================================================

_global_analytics: CommandAnalytics | None = None
_global_lock = threading.Lock()


def get_command_analytics() -> CommandAnalytics:
    """Get or create the global command analytics singleton."""
    global _global_analytics
    if _global_analytics is None:
        with _global_lock:
            if _global_analytics is None:
                _global_analytics = CommandAnalytics()
    return _global_analytics


def reset_command_analytics() -> None:
    """Reset the global command analytics singleton (for testing)."""
    global _global_analytics
    with _global_lock:
        _global_analytics = None
