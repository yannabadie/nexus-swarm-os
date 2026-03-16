"""
SessionEfficiencyScorecard - Per-Session Performance Tracking

NEXUS V12.4 COGNITIVE BOOST - Track session-level efficiency metrics.

This module provides thread-safe tracking of task completion rates, time-to-first-result,
tool usage efficiency, agent utilization, and overall session quality scoring.

Key Metrics:
    - Task Completion Rate: tasks_completed / tasks_attempted
    - Time-to-First-Result: Latency to initial response
    - Tool Success Rate: successful_tool_calls / total_tool_calls
    - Agent Switches: Number of agent handoffs per session

Storage:
    - In-memory with bounded FIFO history (max 50,000 records)
    - Thread-safe with threading.Lock
    - Global singleton via get_session_scorecard()

Usage:
    from core.infrastructure.session.session_efficiency_scorecard import get_session_scorecard

    scorecard = get_session_scorecard()
    record = scorecard.record_session(
        session_id="sess_001",
        tasks_completed=8,
        tasks_attempted=10,
        total_duration_ms=15000.0,
        time_to_first_result_ms=500.0,
        tool_calls_total=25,
        tool_calls_successful=23,
        agent_switches=3
    )

    # Get session profile
    profile = scorecard.get_session_profile("sess_001")
    print(f"Completion rate: {profile.avg_completion_rate:.2%}")

    # Get best session
    best = scorecard.get_best_session()
    print(f"Best session: {best}")

    # Get overall stats
    stats = scorecard.get_stats()
    print(f"Total records: {stats.total_records}")

Author: Claude (NEXUS V12.4)
Date: 2026-02-16
"""

from __future__ import annotations

import dataclasses
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

# Constants
MAX_SESSION_RECORDS: int = 50000


@dataclass
class SessionRecord:
    """
    A single session efficiency record.

    Captures metrics for a single task execution or session snapshot,
    including task completion, timing, tool usage, and agent coordination.
    """

    session_id: str = ""
    record_id: str = ""
    tasks_completed: int = 0
    tasks_attempted: int = 0
    total_duration_ms: float = 0.0
    time_to_first_result_ms: float = 0.0
    tool_calls_total: int = 0
    tool_calls_successful: int = 0
    agent_switches: int = 0
    timestamp: str = ""

    @property
    def completion_rate(self) -> float:
        """
        Task completion rate: tasks_completed / tasks_attempted.

        Returns:
            Completion rate as float (0.0-1.0), or 0.0 if no tasks attempted.
        """
        if self.tasks_attempted == 0:
            return 0.0
        return self.tasks_completed / self.tasks_attempted

    @property
    def tool_success_rate(self) -> float:
        """
        Tool success rate: tool_calls_successful / tool_calls_total.

        Returns:
            Success rate as float (0.0-1.0), or 0.0 if no tool calls.
        """
        if self.tool_calls_total == 0:
            return 0.0
        return self.tool_calls_successful / self.tool_calls_total

    def to_dict(self) -> dict:
        """
        Convert to dictionary, including computed properties.

        Returns:
            Dictionary representation with all fields plus computed rates.
        """
        result = dataclasses.asdict(self)
        result["completion_rate"] = round(self.completion_rate, 4)
        result["tool_success_rate"] = round(self.tool_success_rate, 4)
        return result


@dataclass
class SessionProfile:
    """
    Aggregate metrics per session_id.

    Accumulates metrics across all SessionRecords for a given session,
    enabling longitudinal analysis of session performance.
    """

    session_id: str = ""
    total_records: int = 0
    total_tasks_completed: int = 0
    total_tasks_attempted: int = 0
    total_duration_ms: float = 0.0
    total_tool_calls: int = 0
    total_tool_successes: int = 0
    total_agent_switches: int = 0

    @property
    def avg_completion_rate(self) -> float:
        """
        Average task completion rate across all records.

        Returns:
            Completion rate as float (0.0-1.0), or 0.0 if no tasks attempted.
        """
        if self.total_tasks_attempted == 0:
            return 0.0
        return self.total_tasks_completed / self.total_tasks_attempted

    @property
    def avg_tool_success_rate(self) -> float:
        """
        Average tool success rate across all records.

        Returns:
            Success rate as float (0.0-1.0), or 0.0 if no tool calls.
        """
        if self.total_tool_calls == 0:
            return 0.0
        return self.total_tool_successes / self.total_tool_calls

    @property
    def avg_duration_ms(self) -> float:
        """
        Average duration per record.

        Returns:
            Average duration in milliseconds, or 0.0 if no records.
        """
        if self.total_records == 0:
            return 0.0
        return self.total_duration_ms / self.total_records

    def to_dict(self) -> dict:
        """
        Convert to dictionary, including computed properties.

        Returns:
            Dictionary representation with all fields plus computed rates.
        """
        result = dataclasses.asdict(self)
        result["avg_completion_rate"] = round(self.avg_completion_rate, 4)
        result["avg_tool_success_rate"] = round(self.avg_tool_success_rate, 4)
        result["avg_duration_ms"] = round(self.avg_duration_ms, 2)
        return result


@dataclass
class ScorecardStats:
    """
    Overall statistics across all sessions.

    Provides high-level metrics for system-wide efficiency analysis.
    """

    total_records: int = 0
    unique_sessions: int = 0
    avg_completion_rate: float = 0.0
    avg_tool_success_rate: float = 0.0
    avg_duration_ms: float = 0.0
    total_agent_switches: int = 0

    def to_dict(self) -> dict:
        """
        Convert to dictionary.

        Returns:
            Dictionary representation via dataclasses.asdict.
        """
        return dataclasses.asdict(self)


class SessionEfficiencyScorecard:
    """
    Thread-safe in-memory session efficiency tracker.

    Maintains bounded FIFO history of session records with per-session
    aggregation and system-wide statistics.

    Thread Safety:
        All public methods use threading.Lock for synchronization.

    Bounded Storage:
        FIFO eviction when max_records reached (default 50,000).

    Singleton Pattern:
        Use get_session_scorecard() for global instance.
    """

    def __init__(self, max_records: int = MAX_SESSION_RECORDS):
        """
        Initialize the scorecard.

        Args:
            max_records: Maximum number of records to retain (FIFO eviction).
        """
        self._lock = threading.Lock()
        self._max_records = max_records
        self._counter = 0  # Auto-incrementing counter for record IDs
        self._records: list[SessionRecord] = []
        self._profiles: dict[str, SessionProfile] = {}
        logger.info(f"SessionEfficiencyScorecard initialized (max_records={max_records})")

    def record_session(
        self,
        session_id: str,
        tasks_completed: int = 0,
        tasks_attempted: int = 0,
        total_duration_ms: float = 0.0,
        time_to_first_result_ms: float = 0.0,
        tool_calls_total: int = 0,
        tool_calls_successful: int = 0,
        agent_switches: int = 0,
    ) -> SessionRecord:
        """
        Record a session efficiency snapshot.

        Auto-generates record_id and timestamp. Updates SessionProfile for
        the given session_id. Evicts oldest record if at max capacity.

        Args:
            session_id: Session identifier
            tasks_completed: Number of tasks successfully completed
            tasks_attempted: Number of tasks attempted
            total_duration_ms: Total duration in milliseconds
            time_to_first_result_ms: Time to first result in milliseconds
            tool_calls_total: Total number of tool calls
            tool_calls_successful: Number of successful tool calls
            agent_switches: Number of agent handoffs

        Returns:
            The created SessionRecord instance.

        Thread Safety:
            Method is thread-safe via self._lock.
        """
        with self._lock:
            # Generate record ID
            record_id = f"sr_{self._counter:06d}"
            self._counter += 1

            # Create record
            timestamp = datetime.now(UTC).isoformat()
            record = SessionRecord(
                session_id=session_id,
                record_id=record_id,
                tasks_completed=tasks_completed,
                tasks_attempted=tasks_attempted,
                total_duration_ms=total_duration_ms,
                time_to_first_result_ms=time_to_first_result_ms,
                tool_calls_total=tool_calls_total,
                tool_calls_successful=tool_calls_successful,
                agent_switches=agent_switches,
                timestamp=timestamp,
            )

            # Update profile
            self._update_profile(record)

            # Add to records (FIFO eviction)
            self._records.append(record)
            if len(self._records) > self._max_records:
                evicted = self._records.pop(0)
                logger.debug(f"Evicted record {evicted.record_id} (FIFO)")

            logger.debug(
                f"Recorded session snapshot: {session_id} "
                f"(completion={record.completion_rate:.2%}, "
                f"tool_success={record.tool_success_rate:.2%})"
            )

            return record

    def _update_profile(self, record: SessionRecord) -> None:
        """
        Update SessionProfile for the given record.

        Args:
            record: SessionRecord to aggregate into profile.

        Note:
            Must be called with self._lock held.
        """
        session_id = record.session_id
        if session_id not in self._profiles:
            self._profiles[session_id] = SessionProfile(session_id=session_id)

        profile = self._profiles[session_id]
        profile.total_records += 1
        profile.total_tasks_completed += record.tasks_completed
        profile.total_tasks_attempted += record.tasks_attempted
        profile.total_duration_ms += record.total_duration_ms
        profile.total_tool_calls += record.tool_calls_total
        profile.total_tool_successes += record.tool_calls_successful
        profile.total_agent_switches += record.agent_switches

    def get_session_profile(self, session_id: str) -> SessionProfile | None:
        """
        Get aggregate profile for a session.

        Args:
            session_id: Session identifier to query.

        Returns:
            SessionProfile if session exists, None otherwise.

        Thread Safety:
            Method is thread-safe via self._lock.
        """
        with self._lock:
            return self._profiles.get(session_id)

    def get_all_profiles(self) -> list[SessionProfile]:
        """
        Get all session profiles, sorted by total_records descending.

        Returns:
            List of SessionProfile instances, sorted by activity.

        Thread Safety:
            Method is thread-safe via self._lock.
        """
        with self._lock:
            profiles = list(self._profiles.values())
            profiles.sort(key=lambda p: p.total_records, reverse=True)
            return profiles

    def get_best_session(self) -> str | None:
        """
        Get session_id with highest average completion rate.

        Returns:
            session_id with best completion rate, or None if no sessions.

        Thread Safety:
            Method is thread-safe via self._lock.
        """
        with self._lock:
            if not self._profiles:
                return None

            best_profile = max(self._profiles.values(), key=lambda p: p.avg_completion_rate)
            return best_profile.session_id

    def get_recent_records(self, limit: int = 10, session_id: str | None = None) -> list[SessionRecord]:
        """
        Get most recent records, optionally filtered by session_id.

        Args:
            limit: Maximum number of records to return.
            session_id: If provided, filter to this session only.

        Returns:
            List of SessionRecord instances (most recent first).

        Thread Safety:
            Method is thread-safe via self._lock.
        """
        with self._lock:
            if session_id is None:
                # All records, most recent first
                return list(reversed(self._records[-limit:]))
            else:
                # Filter by session_id
                filtered = [r for r in self._records if r.session_id == session_id]
                return list(reversed(filtered[-limit:]))

    def list_sessions(self) -> list[str]:
        """
        List all session IDs, sorted alphabetically.

        Returns:
            Sorted list of session_id strings.

        Thread Safety:
            Method is thread-safe via self._lock.
        """
        with self._lock:
            return sorted(self._profiles.keys())

    def get_stats(self) -> ScorecardStats:
        """
        Get overall statistics across all sessions.

        Returns:
            ScorecardStats instance with system-wide metrics.

        Thread Safety:
            Method is thread-safe via self._lock.
        """
        with self._lock:
            if not self._records:
                return ScorecardStats()

            total_records = len(self._records)
            unique_sessions = len(self._profiles)

            # Calculate averages
            total_completed = sum(r.tasks_completed for r in self._records)
            total_attempted = sum(r.tasks_attempted for r in self._records)
            avg_completion = total_completed / total_attempted if total_attempted > 0 else 0.0

            total_tool_success = sum(r.tool_calls_successful for r in self._records)
            total_tool_calls = sum(r.tool_calls_total for r in self._records)
            avg_tool_success = total_tool_success / total_tool_calls if total_tool_calls > 0 else 0.0

            total_duration = sum(r.total_duration_ms for r in self._records)
            avg_duration = total_duration / total_records if total_records > 0 else 0.0

            total_switches = sum(r.agent_switches for r in self._records)

            return ScorecardStats(
                total_records=total_records,
                unique_sessions=unique_sessions,
                avg_completion_rate=round(avg_completion, 4),
                avg_tool_success_rate=round(avg_tool_success, 4),
                avg_duration_ms=round(avg_duration, 2),
                total_agent_switches=total_switches,
            )

    @property
    def record_count(self) -> int:
        """
        Get current number of records.

        Returns:
            Current record count.

        Thread Safety:
            Property is thread-safe via self._lock.
        """
        with self._lock:
            return len(self._records)

    def clear(self) -> None:
        """
        Clear all records and profiles.

        Thread Safety:
            Method is thread-safe via self._lock.
        """
        with self._lock:
            self._records.clear()
            self._profiles.clear()
            self._counter = 0
            logger.info("SessionEfficiencyScorecard cleared")

    def to_dict(self) -> dict:
        """
        Convert entire scorecard to dictionary.

        CRITICAL: Calls get_stats() BEFORE acquiring lock to prevent deadlock,
        since get_stats() also acquires the lock.

        Returns:
            Dictionary with stats, profiles, and recent records.

        Thread Safety:
            Method is thread-safe with deadlock prevention.
        """
        # DEADLOCK PREVENTION: Call get_stats() before acquiring lock
        stats = self.get_stats()

        with self._lock:
            return {
                "stats": stats.to_dict(),
                "profiles": {session_id: profile.to_dict() for session_id, profile in self._profiles.items()},
                "recent_records": [r.to_dict() for r in self._records[-10:]],
                "total_records": len(self._records),
                "max_records": self._max_records,
            }


# Singleton management
_instance: SessionEfficiencyScorecard | None = None
_lock = threading.Lock()


def get_session_scorecard(max_records: int = MAX_SESSION_RECORDS) -> SessionEfficiencyScorecard:
    """
    Get or create the global SessionEfficiencyScorecard singleton.

    Uses double-checked locking for thread-safe lazy initialization.

    Args:
        max_records: Maximum records (only used on first initialization).

    Returns:
        The global SessionEfficiencyScorecard instance.

    Thread Safety:
        Function is thread-safe via double-checked locking pattern.
    """
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = SessionEfficiencyScorecard(max_records=max_records)
                logger.info("Global SessionEfficiencyScorecard singleton created")
    return _instance


def reset_session_scorecard() -> None:
    """
    Reset the global singleton (primarily for testing).

    Creates a fresh instance, discarding all previous data.

    Thread Safety:
        Function is thread-safe via _lock.
    """
    global _instance
    with _lock:
        _instance = None
        logger.info("Global SessionEfficiencyScorecard singleton reset")
