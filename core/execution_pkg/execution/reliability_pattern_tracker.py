"""
Reliability Pattern Tracker for NEXUS V12.4.

Tracks combined retry+timeout execution patterns to analyze:
- Which retry policies work best for each tool
- Timeout prediction accuracy
- Reliability patterns per tool
- Overall execution success metrics

This module provides thread-safe tracking of all execution attempts,
recording retry counts, timeouts, durations, and success rates.

Architecture:
    - RetryAttempt: Single execution attempt record
    - ToolReliabilityProfile: Aggregate metrics per tool
    - ReliabilityStats: Overall system statistics
    - ReliabilityPatternTracker: Main singleton tracker

Thread Safety:
    All operations are protected by threading.Lock() for safe concurrent access.

Example:
    >>> tracker = get_reliability_tracker()
    >>> tracker.record_attempt(
    ...     tool_name="bash",
    ...     retry_count=2,
    ...     timeout_ms=5000.0,
    ...     actual_duration_ms=4800.0,
    ...     success=True,
    ...     policy="exponential_backoff"
    ... )
    >>> profile = tracker.get_tool_profile("bash")
    >>> print(f"Success rate: {profile.success_rate:.2%}")

Author: NEXUS Development Team
Version: 12.4.0
"""

from __future__ import annotations

import dataclasses
import threading
from dataclasses import dataclass
from datetime import UTC, datetime

# =============================================================================
# CONSTANTS
# =============================================================================

MAX_ATTEMPTS: int = 50000


# =============================================================================
# DATACLASSES
# =============================================================================


@dataclass
class RetryAttempt:
    """
    Single retry/execution attempt record.

    Captures all relevant metrics for a single tool execution,
    including retry count, timeout information, and outcome.

    Attributes:
        attempt_id: Unique identifier for this attempt (auto-generated)
        tool_name: Name of the tool executed
        retry_count: Number of retries needed (0 = first try success)
        timed_out: Whether this attempt timed out
        timeout_ms: Configured timeout in milliseconds
        actual_duration_ms: Actual execution duration in milliseconds
        success: Final outcome of the attempt
        policy: Name of the retry policy used
        timestamp: ISO timestamp of the attempt (auto-set)
    """

    attempt_id: str = ""
    tool_name: str = ""
    retry_count: int = 0
    timed_out: bool = False
    timeout_ms: float = 0.0
    actual_duration_ms: float = 0.0
    success: bool = True
    policy: str = ""
    timestamp: str = ""

    def to_dict(self) -> dict:
        """
        Convert to dictionary representation.

        Returns:
            Dictionary with all fields.
        """
        return dataclasses.asdict(self)


@dataclass
class ToolReliabilityProfile:
    """
    Aggregate reliability metrics for a specific tool.

    Tracks cumulative statistics to identify reliability patterns
    and performance characteristics per tool.

    Attributes:
        tool_name: Name of the tool
        total_attempts: Total number of execution attempts
        successes: Number of successful executions
        total_retries: Cumulative retry count across all attempts
        timeouts: Number of attempts that timed out
        total_duration_ms: Cumulative execution time in milliseconds

    Computed Properties:
        success_rate: Ratio of successes to total attempts
        avg_retries: Average retries per attempt
        timeout_rate: Ratio of timeouts to total attempts
    """

    tool_name: str = ""
    total_attempts: int = 0
    successes: int = 0
    total_retries: int = 0
    timeouts: int = 0
    total_duration_ms: float = 0.0

    @property
    def success_rate(self) -> float:
        """
        Calculate success rate.

        Returns:
            Ratio of successes to total attempts (0.0 to 1.0).
        """
        if self.total_attempts == 0:
            return 0.0
        return self.successes / self.total_attempts

    @property
    def avg_retries(self) -> float:
        """
        Calculate average retries per attempt.

        Returns:
            Average number of retries needed per attempt.
        """
        if self.total_attempts == 0:
            return 0.0
        return self.total_retries / self.total_attempts

    @property
    def timeout_rate(self) -> float:
        """
        Calculate timeout rate.

        Returns:
            Ratio of timeouts to total attempts (0.0 to 1.0).
        """
        if self.total_attempts == 0:
            return 0.0
        return self.timeouts / self.total_attempts

    def to_dict(self) -> dict:
        """
        Convert to dictionary representation including computed properties.

        Returns:
            Dictionary with all fields and computed properties.
        """
        data = dataclasses.asdict(self)
        data["success_rate"] = self.success_rate
        data["avg_retries"] = self.avg_retries
        data["timeout_rate"] = self.timeout_rate
        return data


@dataclass
class ReliabilityStats:
    """
    Overall system reliability statistics.

    Provides high-level metrics across all tools and attempts.

    Attributes:
        total_attempts: Total execution attempts across all tools
        unique_tools: Number of distinct tools tracked
        overall_success_rate: System-wide success rate
        overall_timeout_rate: System-wide timeout rate
    """

    total_attempts: int = 0
    unique_tools: int = 0
    overall_success_rate: float = 0.0
    overall_timeout_rate: float = 0.0

    def to_dict(self) -> dict:
        """
        Convert to dictionary representation.

        Returns:
            Dictionary with all fields.
        """
        return dataclasses.asdict(self)


# =============================================================================
# MAIN TRACKER CLASS
# =============================================================================


class ReliabilityPatternTracker:
    """
    Thread-safe tracker for retry and timeout execution patterns.

    Maintains a bounded FIFO history of execution attempts and computes
    aggregate reliability metrics per tool and system-wide.

    Thread Safety:
        All public methods are protected by a threading.Lock().

    Usage:
        Use the singleton via get_reliability_tracker() rather than
        direct instantiation.

    Attributes:
        max_attempts: Maximum number of attempts to retain (FIFO)
    """

    def __init__(self, max_attempts: int = MAX_ATTEMPTS) -> None:
        """
        Initialize the reliability pattern tracker.

        Args:
            max_attempts: Maximum history size (FIFO eviction when exceeded).
        """
        self._max_attempts = max_attempts
        self._attempts: list[RetryAttempt] = []
        self._profiles: dict[str, ToolReliabilityProfile] = {}
        self._counter: int = 0
        self._lock = threading.Lock()

    def record_attempt(
        self,
        tool_name: str,
        retry_count: int = 0,
        timed_out: bool = False,
        timeout_ms: float = 0.0,
        actual_duration_ms: float = 0.0,
        success: bool = True,
        policy: str = "",
    ) -> RetryAttempt:
        """
        Record a single execution attempt.

        Creates a RetryAttempt record, updates the tool's reliability profile,
        and enforces FIFO eviction if at capacity.

        Args:
            tool_name: Name of the tool executed
            retry_count: Number of retries needed (0 = first try success)
            timed_out: Whether the attempt timed out
            timeout_ms: Configured timeout in milliseconds
            actual_duration_ms: Actual execution duration in milliseconds
            success: Final outcome of the attempt
            policy: Name of the retry policy used

        Returns:
            The created RetryAttempt record.

        Thread Safety:
            Protected by lock.
        """
        with self._lock:
            # Generate attempt ID
            attempt_id = f"ra_{self._counter:06d}"
            self._counter += 1

            # Create attempt record
            timestamp = datetime.now(UTC).isoformat()
            attempt = RetryAttempt(
                attempt_id=attempt_id,
                tool_name=tool_name,
                retry_count=retry_count,
                timed_out=timed_out,
                timeout_ms=timeout_ms,
                actual_duration_ms=actual_duration_ms,
                success=success,
                policy=policy,
                timestamp=timestamp,
            )

            # FIFO eviction
            if len(self._attempts) >= self._max_attempts:
                self._attempts.pop(0)
                # Note: We do NOT decrement profile stats on eviction
                # This preserves long-term aggregate metrics

            # Add to history
            self._attempts.append(attempt)

            # Update tool profile
            if tool_name not in self._profiles:
                self._profiles[tool_name] = ToolReliabilityProfile(tool_name=tool_name)

            profile = self._profiles[tool_name]
            profile.total_attempts += 1
            if success:
                profile.successes += 1
            profile.total_retries += retry_count
            if timed_out:
                profile.timeouts += 1
            profile.total_duration_ms += actual_duration_ms

            return attempt

    def get_tool_profile(self, tool_name: str) -> ToolReliabilityProfile | None:
        """
        Get reliability profile for a specific tool.

        Args:
            tool_name: Name of the tool.

        Returns:
            ToolReliabilityProfile if exists, None otherwise.

        Thread Safety:
            Protected by lock.
        """
        with self._lock:
            return self._profiles.get(tool_name)

    def get_all_profiles(self) -> list[ToolReliabilityProfile]:
        """
        Get all tool reliability profiles sorted by total attempts (descending).

        Returns:
            List of ToolReliabilityProfile objects.

        Thread Safety:
            Protected by lock.
        """
        with self._lock:
            profiles = list(self._profiles.values())
            profiles.sort(key=lambda p: p.total_attempts, reverse=True)
            return profiles

    def get_most_reliable(self, min_attempts: int = 3) -> list[ToolReliabilityProfile]:
        """
        Get most reliable tools (success_rate >= 0.9).

        Filters to tools with at least min_attempts and high success rates,
        sorted by success rate descending.

        Args:
            min_attempts: Minimum attempts required for inclusion.

        Returns:
            List of highly reliable ToolReliabilityProfile objects.

        Thread Safety:
            Protected by lock.
        """
        with self._lock:
            reliable = [
                p for p in self._profiles.values() if p.total_attempts >= min_attempts and p.success_rate >= 0.9
            ]
            reliable.sort(key=lambda p: p.success_rate, reverse=True)
            return reliable

    def get_least_reliable(self, min_attempts: int = 3) -> list[ToolReliabilityProfile]:
        """
        Get least reliable tools (success_rate < 0.8).

        Filters to tools with at least min_attempts and low success rates,
        sorted by success rate ascending.

        Args:
            min_attempts: Minimum attempts required for inclusion.

        Returns:
            List of low-reliability ToolReliabilityProfile objects.

        Thread Safety:
            Protected by lock.
        """
        with self._lock:
            unreliable = [
                p for p in self._profiles.values() if p.total_attempts >= min_attempts and p.success_rate < 0.8
            ]
            unreliable.sort(key=lambda p: p.success_rate)
            return unreliable

    def get_recent_attempts(self, limit: int = 10, tool_name: str | None = None) -> list[RetryAttempt]:
        """
        Get recent execution attempts.

        Args:
            limit: Maximum number of attempts to return.
            tool_name: Optional filter by tool name.

        Returns:
            List of RetryAttempt objects (most recent first).

        Thread Safety:
            Protected by lock.
        """
        with self._lock:
            attempts = self._attempts

            # Filter by tool if specified
            if tool_name is not None:
                attempts = [a for a in attempts if a.tool_name == tool_name]

            # Return most recent (reversed) up to limit
            return list(reversed(attempts[-limit:]))

    def list_tools(self) -> list[str]:
        """
        List all tracked tool names alphabetically.

        Returns:
            Sorted list of tool names.

        Thread Safety:
            Protected by lock.
        """
        with self._lock:
            return sorted(self._profiles.keys())

    def get_stats(self) -> ReliabilityStats:
        """
        Get overall system reliability statistics.

        Computes aggregate metrics across all tools and attempts.

        Returns:
            ReliabilityStats object with system-wide metrics.

        Thread Safety:
            Protected by lock.
        """
        with self._lock:
            total_attempts = sum(p.total_attempts for p in self._profiles.values())
            total_successes = sum(p.successes for p in self._profiles.values())
            total_timeouts = sum(p.timeouts for p in self._profiles.values())
            unique_tools = len(self._profiles)

            overall_success_rate = 0.0
            if total_attempts > 0:
                overall_success_rate = total_successes / total_attempts

            overall_timeout_rate = 0.0
            if total_attempts > 0:
                overall_timeout_rate = total_timeouts / total_attempts

            return ReliabilityStats(
                total_attempts=total_attempts,
                unique_tools=unique_tools,
                overall_success_rate=overall_success_rate,
                overall_timeout_rate=overall_timeout_rate,
            )

    @property
    def attempt_count(self) -> int:
        """
        Get current number of attempts in history.

        Returns:
            Number of RetryAttempt records currently stored.

        Thread Safety:
            Protected by lock.
        """
        with self._lock:
            return len(self._attempts)

    def clear(self) -> None:
        """
        Clear all tracked data.

        Resets attempts, profiles, and counter to initial state.

        Thread Safety:
            Protected by lock.
        """
        with self._lock:
            self._attempts.clear()
            self._profiles.clear()
            self._counter = 0

    def to_dict(self) -> dict:
        """
        Convert tracker state to dictionary representation.

        CRITICAL: Calls get_stats() BEFORE acquiring lock to prevent deadlock,
        since get_stats() also acquires the lock.

        Returns:
            Dictionary with stats, profiles, and recent attempts.

        Thread Safety:
            Protected by lock (with deadlock prevention).
        """
        # DEADLOCK PREVENTION: Call all locking methods BEFORE acquiring lock
        stats = self.get_stats()
        all_profiles = self.get_all_profiles()
        recent = self.get_recent_attempts(limit=20)

        with self._lock:
            return {
                "stats": stats.to_dict(),
                "profiles": [p.to_dict() for p in all_profiles],
                "recent_attempts": [a.to_dict() for a in recent],
                "attempt_count": len(self._attempts),
                "max_attempts": self._max_attempts,
            }


# =============================================================================
# SINGLETON PATTERN
# =============================================================================

_instance: ReliabilityPatternTracker | None = None
_lock = threading.Lock()


def get_reliability_tracker() -> ReliabilityPatternTracker:
    """
    Get the global ReliabilityPatternTracker singleton instance.

    Uses double-checked locking for thread-safe lazy initialization.

    Returns:
        The global ReliabilityPatternTracker instance.

    Thread Safety:
        Double-checked locking pattern ensures safe concurrent access.
    """
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = ReliabilityPatternTracker()
    return _instance


def reset_reliability_tracker() -> None:
    """
    Reset the global ReliabilityPatternTracker singleton.

    Creates a new instance, discarding all tracked data.
    Primarily used for testing.

    Thread Safety:
        Protected by lock.
    """
    global _instance
    with _lock:
        _instance = ReliabilityPatternTracker()
