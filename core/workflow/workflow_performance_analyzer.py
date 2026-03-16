"""
Workflow Performance Analyzer - Runtime workflow execution analytics.

V12.4 COGNITIVE BOOST - Task #76

Tracks actual workflow execution metrics: execution times, step completion rates,
bottleneck detection, workflow throughput, and parallel efficiency.

Provides per-workflow profiles and aggregate statistics for performance tuning
and workflow optimization.

Usage:
    from core.workflow.workflow_performance_analyzer import get_workflow_analyzer

    analyzer = get_workflow_analyzer()

    # Record workflow execution
    record = analyzer.record_run(
        workflow_name="data_pipeline",
        steps_total=10,
        steps_completed=10,
        steps_failed=0,
        total_duration_ms=1500.0,
        bottleneck_step="transform_data",
        parallel_efficiency=0.85
    )

    # Query analytics
    profile = analyzer.get_workflow_profile("data_pipeline")
    best = analyzer.get_best_workflow()
    stats = analyzer.get_stats()

Author: Claude (NEXUS V12.4)
Date: 2026-02-16
"""

from __future__ import annotations

import dataclasses
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

MAX_WORKFLOW_RECORDS: int = 50000


# =============================================================================
# Dataclasses
# =============================================================================


@dataclass
class WorkflowRunRecord:
    """
    A single workflow execution record.

    Contains detailed metrics about one workflow run including completion rate,
    duration, bottlenecks, and parallel efficiency.
    """

    run_id: str = ""
    workflow_name: str = ""
    steps_total: int = 0
    steps_completed: int = 0
    steps_failed: int = 0
    total_duration_ms: float = 0.0
    bottleneck_step: str = ""
    parallel_efficiency: float = 0.0  # 0.0-1.0
    timestamp: str = ""

    @property
    def completion_rate(self) -> float:
        """
        Fraction of steps completed successfully.

        Returns:
            0.0-1.0 completion rate (0.0 if no steps total)
        """
        if self.steps_total == 0:
            return 0.0
        return self.steps_completed / self.steps_total

    def to_dict(self) -> dict[str, Any]:
        """
        Convert to dictionary with computed properties.

        Returns:
            Dictionary representation including completion_rate
        """
        result = dataclasses.asdict(self)
        result["completion_rate"] = round(self.completion_rate, 4)
        return result


@dataclass
class WorkflowProfile:
    """
    Aggregate statistics for a single workflow type.

    Tracks cumulative metrics across all runs of a workflow, enabling
    performance trend analysis and bottleneck identification.
    """

    workflow_name: str = ""
    total_runs: int = 0
    total_steps_completed: int = 0
    total_steps_attempted: int = 0
    total_duration_ms: float = 0.0
    total_parallel_efficiency: float = 0.0

    @property
    def avg_completion_rate(self) -> float:
        """
        Average completion rate across all runs.

        Returns:
            0.0-1.0 average completion rate (0.0 if no steps attempted)
        """
        if self.total_steps_attempted == 0:
            return 0.0
        return self.total_steps_completed / self.total_steps_attempted

    @property
    def avg_duration_ms(self) -> float:
        """
        Average execution time per run.

        Returns:
            Average duration in milliseconds (0.0 if no runs)
        """
        if self.total_runs == 0:
            return 0.0
        return self.total_duration_ms / self.total_runs

    @property
    def avg_parallel_efficiency(self) -> float:
        """
        Average parallel efficiency across all runs.

        Returns:
            0.0-1.0 average efficiency (0.0 if no runs)
        """
        if self.total_runs == 0:
            return 0.0
        return self.total_parallel_efficiency / self.total_runs

    def to_dict(self) -> dict[str, Any]:
        """
        Convert to dictionary with computed properties.

        Returns:
            Dictionary representation including averages
        """
        result = dataclasses.asdict(self)
        result["avg_completion_rate"] = round(self.avg_completion_rate, 4)
        result["avg_duration_ms"] = round(self.avg_duration_ms, 2)
        result["avg_parallel_efficiency"] = round(self.avg_parallel_efficiency, 4)
        return result


@dataclass
class PerformanceStats:
    """
    Overall performance statistics across all workflows.

    Provides high-level metrics for system-wide workflow performance.
    """

    total_runs: int = 0
    unique_workflows: int = 0
    avg_completion_rate: float = 0.0
    avg_duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return dataclasses.asdict(self)


# =============================================================================
# Main Analyzer
# =============================================================================


class WorkflowPerformanceAnalyzer:
    """
    Thread-safe workflow execution performance analyzer.

    Tracks workflow execution metrics with FIFO eviction, provides per-workflow
    profiles, identifies best-performing workflows, and detects bottlenecks.

    Features:
    - Thread-safe recording and querying
    - FIFO eviction at max_records
    - Per-workflow aggregate profiles
    - Bottleneck and efficiency tracking
    - Recent run history
    - Best workflow identification

    Thread Safety:
        All public methods are thread-safe using a single lock.
    """

    def __init__(self, max_records: int = MAX_WORKFLOW_RECORDS):
        """
        Initialize the workflow performance analyzer.

        Args:
            max_records: Maximum number of workflow run records to keep (FIFO eviction)
        """
        self._max_records = max_records
        self._runs: list[WorkflowRunRecord] = []
        self._profiles: dict[str, WorkflowProfile] = {}
        self._counter = 1
        self._lock = threading.Lock()

    # =========================================================================
    # Recording
    # =========================================================================

    def record_run(
        self,
        workflow_name: str,
        steps_total: int = 0,
        steps_completed: int = 0,
        steps_failed: int = 0,
        total_duration_ms: float = 0.0,
        bottleneck_step: str = "",
        parallel_efficiency: float = 0.0,
    ) -> WorkflowRunRecord:
        """
        Record a workflow execution.

        Creates a run record, updates the workflow profile, and enforces FIFO
        eviction if at max capacity.

        Args:
            workflow_name: Name of the workflow
            steps_total: Total steps in workflow
            steps_completed: Steps successfully completed
            steps_failed: Steps that failed
            total_duration_ms: Total execution time in milliseconds
            bottleneck_step: Name of slowest step
            parallel_efficiency: 0.0-1.0 how well parallelism was utilized

        Returns:
            The created WorkflowRunRecord
        """
        with self._lock:
            # Auto-generate run ID
            run_id = f"wr_{self._counter:06d}"
            self._counter += 1

            # Create record
            record = WorkflowRunRecord(
                run_id=run_id,
                workflow_name=workflow_name,
                steps_total=steps_total,
                steps_completed=steps_completed,
                steps_failed=steps_failed,
                total_duration_ms=total_duration_ms,
                bottleneck_step=bottleneck_step,
                parallel_efficiency=parallel_efficiency,
                timestamp=datetime.now(UTC).isoformat(),
            )

            # FIFO eviction if needed
            if len(self._runs) >= self._max_records:
                evicted = self._runs.pop(0)
                _logger.debug(f"Evicted workflow run {evicted.run_id} (FIFO at {self._max_records})")

            # Add to runs
            self._runs.append(record)

            # Update profile
            self._update_profile(record)

            return record

    def _update_profile(self, record: WorkflowRunRecord) -> None:
        """
        Update the workflow profile with data from a new record.

        Args:
            record: The workflow run record to incorporate

        Note:
            Must be called with lock held.
        """
        workflow_name = record.workflow_name

        if workflow_name not in self._profiles:
            self._profiles[workflow_name] = WorkflowProfile(workflow_name=workflow_name)

        profile = self._profiles[workflow_name]
        profile.total_runs += 1
        profile.total_steps_completed += record.steps_completed
        profile.total_steps_attempted += record.steps_total
        profile.total_duration_ms += record.total_duration_ms
        profile.total_parallel_efficiency += record.parallel_efficiency

    # =========================================================================
    # Querying - Profiles
    # =========================================================================

    def get_workflow_profile(self, workflow_name: str) -> WorkflowProfile | None:
        """
        Get aggregate profile for a specific workflow.

        Args:
            workflow_name: Name of the workflow

        Returns:
            WorkflowProfile if workflow exists, None otherwise
        """
        with self._lock:
            return self._profiles.get(workflow_name)

    def get_all_profiles(self) -> list[WorkflowProfile]:
        """
        Get all workflow profiles sorted by total runs descending.

        Returns:
            List of WorkflowProfile sorted by popularity
        """
        with self._lock:
            profiles = list(self._profiles.values())
            profiles.sort(key=lambda p: p.total_runs, reverse=True)
            return profiles

    def get_best_workflow(self) -> str | None:
        """
        Identify the best-performing workflow by completion rate.

        Returns:
            Workflow name with highest avg_completion_rate, or None if no workflows
        """
        with self._lock:
            if not self._profiles:
                return None

            best_profile = max(self._profiles.values(), key=lambda p: p.avg_completion_rate)
            return best_profile.workflow_name

    # =========================================================================
    # Querying - Runs
    # =========================================================================

    def get_recent_runs(self, limit: int = 10, workflow_name: str | None = None) -> list[WorkflowRunRecord]:
        """
        Get most recent workflow runs.

        Args:
            limit: Maximum number of runs to return
            workflow_name: Optional filter by workflow name

        Returns:
            List of recent WorkflowRunRecord (newest first)
        """
        with self._lock:
            runs = self._runs

            # Filter by workflow if specified
            if workflow_name:
                runs = [r for r in runs if r.workflow_name == workflow_name]

            # Return most recent
            return list(reversed(runs[-limit:]))

    def list_workflows(self) -> list[str]:
        """
        Get sorted list of all tracked workflow names.

        Returns:
            Sorted list of workflow names
        """
        with self._lock:
            return sorted(self._profiles.keys())

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> PerformanceStats:
        """
        Get overall performance statistics across all workflows.

        Returns:
            PerformanceStats with system-wide metrics
        """
        with self._lock:
            total_runs = len(self._runs)
            unique_workflows = len(self._profiles)

            if total_runs == 0:
                return PerformanceStats(
                    total_runs=0,
                    unique_workflows=unique_workflows,
                    avg_completion_rate=0.0,
                    avg_duration_ms=0.0,
                )

            # Calculate averages across all runs
            total_completion = sum(r.completion_rate for r in self._runs)
            total_duration = sum(r.total_duration_ms for r in self._runs)

            avg_completion_rate = total_completion / total_runs
            avg_duration_ms = total_duration / total_runs

            return PerformanceStats(
                total_runs=total_runs,
                unique_workflows=unique_workflows,
                avg_completion_rate=avg_completion_rate,
                avg_duration_ms=avg_duration_ms,
            )

    @property
    def run_count(self) -> int:
        """
        Total number of workflow runs recorded.

        Returns:
            Count of workflow runs
        """
        with self._lock:
            return len(self._runs)

    # =========================================================================
    # Management
    # =========================================================================

    def clear(self) -> None:
        """Clear all workflow run records and profiles."""
        with self._lock:
            self._runs.clear()
            self._profiles.clear()
            self._counter = 1
            _logger.info("Cleared all workflow performance data")

    def to_dict(self) -> dict[str, Any]:
        """
        Export analyzer state to dictionary.

        Returns:
            Dictionary with stats, profiles, and recent runs

        Note:
            Calls get_stats() BEFORE acquiring lock to prevent deadlock.
        """
        # DEADLOCK PREVENTION: Call all locking methods BEFORE acquiring lock
        stats = self.get_stats()
        all_profiles = self.get_all_profiles()
        recent = self.get_recent_runs(limit=20)

        with self._lock:
            return {
                "stats": stats.to_dict(),
                "profiles": [p.to_dict() for p in all_profiles],
                "recent_runs": [r.to_dict() for r in recent],
                "run_count": len(self._runs),
                "max_records": self._max_records,
            }


# =============================================================================
# Singleton Pattern
# =============================================================================

_instance: WorkflowPerformanceAnalyzer | None = None
_lock = threading.Lock()


def get_workflow_analyzer() -> WorkflowPerformanceAnalyzer:
    """
    Get the global WorkflowPerformanceAnalyzer singleton.

    Uses double-checked locking for thread-safe lazy initialization.

    Returns:
        The global WorkflowPerformanceAnalyzer instance
    """
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = WorkflowPerformanceAnalyzer()
                _logger.debug("Initialized global WorkflowPerformanceAnalyzer")
    return _instance


def reset_workflow_analyzer() -> None:
    """
    Reset the global WorkflowPerformanceAnalyzer singleton.

    Creates a fresh instance with default configuration.
    Primarily for testing and session resets.
    """
    global _instance
    with _lock:
        _instance = WorkflowPerformanceAnalyzer()
        _logger.info("Reset global WorkflowPerformanceAnalyzer")
