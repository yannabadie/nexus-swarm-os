"""
Result Aggregator - Collect and merge multi-agent results.

V12.4 COGNITIVE BOOST - Task #59

Collects results from multiple agents in swarm modes, detects conflicts,
merges outputs, and validates completeness.

Usage:
    from core.intelligence.swarm.result_aggregator import get_aggregator

    agg = get_aggregator()

    # Submit results from agents
    agg.submit("task_001", "claude", {"analysis": "SQL injection in auth.py"})
    agg.submit("task_001", "gemini", {"analysis": "SQL injection + XSS in auth.py"})

    # Merge results
    merged = agg.merge("task_001")

    # Detect conflicts
    conflicts = agg.detect_conflicts("task_001")
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

MAX_TASKS = 5000


# =============================================================================
# Types
# =============================================================================


class MergeStrategy(Enum):
    """How to merge conflicting values."""

    UNION = "union"  # Combine all unique values
    FIRST = "first"  # Use first submitted
    LATEST = "latest"  # Use last submitted
    LONGEST = "longest"  # Use longest string value
    VOTE = "vote"  # Majority wins


@dataclass
class AgentResult:
    """A result submitted by an agent."""

    task_id: str
    agent_id: str
    data: dict[str, Any]
    confidence: float = 1.0
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.monotonic()


@dataclass
class Conflict:
    """A detected conflict between agent results."""

    key: str
    values: dict[str, Any]  # agent_id -> value
    resolved: bool = False
    resolution: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "values": {k: str(v)[:100] for k, v in self.values.items()},
            "resolved": self.resolved,
        }


@dataclass
class MergeResult:
    """Result of merging agent outputs."""

    task_id: str
    merged_data: dict[str, Any]
    agent_count: int
    conflict_count: int
    keys_merged: int
    strategy: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "merged_keys": list(self.merged_data.keys()),
            "agent_count": self.agent_count,
            "conflict_count": self.conflict_count,
            "keys_merged": self.keys_merged,
            "strategy": self.strategy,
        }


@dataclass
class AggregatorStats:
    """Aggregator statistics."""

    total_tasks: int
    total_submissions: int
    total_merges: int
    total_conflicts: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_tasks": self.total_tasks,
            "total_submissions": self.total_submissions,
            "total_merges": self.total_merges,
            "total_conflicts": self.total_conflicts,
        }


# =============================================================================
# Result Aggregator
# =============================================================================


class ResultAggregator:
    """
    Collects and merges multi-agent results.

    Features:
    - Per-task result collection from multiple agents
    - Conflict detection between agents
    - Configurable merge strategies
    - Completeness validation
    - Statistics tracking
    """

    def __init__(self, *, max_tasks: int = MAX_TASKS):
        self._results: dict[str, dict[str, AgentResult]] = defaultdict(dict)  # task -> agent -> result
        self._max_tasks = max_tasks
        self._total_submissions = 0
        self._total_merges = 0
        self._total_conflicts = 0
        self._lock = threading.Lock()

    # =========================================================================
    # Submit
    # =========================================================================

    def submit(
        self,
        task_id: str,
        agent_id: str,
        data: dict[str, Any],
        *,
        confidence: float = 1.0,
    ) -> AgentResult:
        """
        Submit a result from an agent.

        Args:
            task_id: Task identifier
            agent_id: Agent that produced this result
            data: Result data (key-value pairs)
            confidence: Agent's confidence in this result (0-1)

        Returns:
            The stored AgentResult
        """
        result = AgentResult(
            task_id=task_id,
            agent_id=agent_id,
            data=data,
            confidence=max(0.0, min(1.0, confidence)),
        )
        with self._lock:
            self._results[task_id][agent_id] = result
            self._total_submissions += 1
            self._enforce_max_tasks()
        return result

    # =========================================================================
    # Query
    # =========================================================================

    def get_results(self, task_id: str) -> list[AgentResult]:
        """Get all results for a task."""
        with self._lock:
            agents = self._results.get(task_id, {})
            return list(agents.values())

    def get_result(self, task_id: str, agent_id: str) -> AgentResult | None:
        """Get a specific agent's result for a task."""
        with self._lock:
            agents = self._results.get(task_id, {})
            return agents.get(agent_id)

    def get_agents(self, task_id: str) -> list[str]:
        """Get list of agents that submitted results for a task."""
        with self._lock:
            return sorted(self._results.get(task_id, {}).keys())

    def has_result(self, task_id: str, agent_id: str) -> bool:
        """Check if an agent has submitted a result."""
        with self._lock:
            return agent_id in self._results.get(task_id, {})

    # =========================================================================
    # Conflict Detection
    # =========================================================================

    def detect_conflicts(self, task_id: str) -> list[Conflict]:
        """
        Detect conflicts between agent results for a task.

        A conflict exists when two agents provide different values for the same key.
        """
        with self._lock:
            agents = self._results.get(task_id, {})
            if len(agents) < 2:
                return []

        # Collect all keys and their values per agent
        key_values: dict[str, dict[str, Any]] = defaultdict(dict)
        for agent_id, result in agents.items():
            for key, value in result.data.items():
                key_values[key][agent_id] = value

        conflicts = []
        for key, agent_vals in key_values.items():
            if len(agent_vals) < 2:
                continue
            unique_values = set()
            for v in agent_vals.values():
                unique_values.add(str(v))
            if len(unique_values) > 1:
                conflicts.append(Conflict(key=key, values=dict(agent_vals)))

        return conflicts

    # =========================================================================
    # Merge
    # =========================================================================

    def merge(
        self,
        task_id: str,
        *,
        strategy: MergeStrategy = MergeStrategy.UNION,
    ) -> MergeResult:
        """
        Merge results from all agents for a task.

        Args:
            task_id: Task to merge
            strategy: How to handle conflicts

        Returns:
            MergeResult with merged data
        """
        with self._lock:
            agents = dict(self._results.get(task_id, {}))
            self._total_merges += 1

        if not agents:
            return MergeResult(
                task_id=task_id,
                merged_data={},
                agent_count=0,
                conflict_count=0,
                keys_merged=0,
                strategy=strategy.value,
            )

        # Collect all keys and values
        key_values: dict[str, dict[str, Any]] = defaultdict(dict)
        key_timestamps: dict[str, dict[str, float]] = defaultdict(dict)
        for agent_id, result in agents.items():
            for key, value in result.data.items():
                key_values[key][agent_id] = value
                key_timestamps[key][agent_id] = result.timestamp

        merged: dict[str, Any] = {}
        conflict_count = 0

        for key, agent_vals in key_values.items():
            unique_str_vals = set(str(v) for v in agent_vals.values())

            if len(unique_str_vals) <= 1:
                # No conflict - use the value
                merged[key] = next(iter(agent_vals.values()))
            else:
                # Conflict - apply strategy
                conflict_count += 1
                merged[key] = self._resolve(
                    key,
                    agent_vals,
                    key_timestamps.get(key, {}),
                    strategy,
                    agents,
                )

        with self._lock:
            self._total_conflicts += conflict_count

        return MergeResult(
            task_id=task_id,
            merged_data=merged,
            agent_count=len(agents),
            conflict_count=conflict_count,
            keys_merged=len(merged),
            strategy=strategy.value,
        )

    def _resolve(
        self,
        key: str,
        agent_vals: dict[str, Any],
        timestamps: dict[str, float],
        strategy: MergeStrategy,
        agents: dict[str, AgentResult],
    ) -> Any:
        """Resolve a conflict using the given strategy."""
        if strategy == MergeStrategy.FIRST:
            earliest = min(timestamps, key=timestamps.get)
            return agent_vals[earliest]

        elif strategy == MergeStrategy.LATEST:
            latest = max(timestamps, key=timestamps.get)
            return agent_vals[latest]

        elif strategy == MergeStrategy.LONGEST:
            return max(agent_vals.values(), key=lambda v: len(str(v)))

        elif strategy == MergeStrategy.VOTE:
            # Count how many agents agree on each value
            value_counts: dict[str, int] = defaultdict(int)
            value_map: dict[str, Any] = {}
            for v in agent_vals.values():
                sv = str(v)
                value_counts[sv] += 1
                value_map[sv] = v
            winner = max(value_counts, key=value_counts.get)
            return value_map[winner]

        else:  # UNION
            # For lists: combine unique items; for strings: join; for others: list
            values = list(agent_vals.values())
            if all(isinstance(v, list) for v in values):
                combined = []
                seen: set[str] = set()
                for lst in values:
                    for item in lst:
                        key_str = str(item)
                        if key_str not in seen:
                            seen.add(key_str)
                            combined.append(item)
                return combined
            elif all(isinstance(v, (int, float)) for v in values):
                return max(values)
            else:
                return values

    # =========================================================================
    # Validation
    # =========================================================================

    def is_complete(
        self,
        task_id: str,
        expected_agents: list[str],
    ) -> bool:
        """Check if all expected agents have submitted results."""
        with self._lock:
            submitted = set(self._results.get(task_id, {}).keys())
        return all(a in submitted for a in expected_agents)

    def missing_agents(
        self,
        task_id: str,
        expected_agents: list[str],
    ) -> list[str]:
        """Get list of agents that haven't submitted results yet."""
        with self._lock:
            submitted = set(self._results.get(task_id, {}).keys())
        return [a for a in expected_agents if a not in submitted]

    # =========================================================================
    # Cleanup
    # =========================================================================

    def remove_task(self, task_id: str) -> bool:
        """Remove all results for a task."""
        with self._lock:
            return self._results.pop(task_id, None) is not None

    def _enforce_max_tasks(self) -> None:
        """Evict oldest tasks if over limit (called under lock)."""
        while len(self._results) > self._max_tasks:
            # Remove task with oldest submission
            oldest_task = None
            oldest_time = float("inf")
            for tid, agents in self._results.items():
                for result in agents.values():
                    if result.timestamp < oldest_time:
                        oldest_time = result.timestamp
                        oldest_task = tid
                    break  # Just check first agent per task
            if oldest_task:
                del self._results[oldest_task]
            else:
                break

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> AggregatorStats:
        """Get aggregator statistics."""
        with self._lock:
            return AggregatorStats(
                total_tasks=len(self._results),
                total_submissions=self._total_submissions,
                total_merges=self._total_merges,
                total_conflicts=self._total_conflicts,
            )

    # =========================================================================
    # State
    # =========================================================================

    @property
    def task_count(self) -> int:
        return len(self._results)

    def clear(self) -> None:
        """Clear all data."""
        with self._lock:
            self._results.clear()
            self._total_submissions = 0
            self._total_merges = 0
            self._total_conflicts = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_count": self.task_count,
            "stats": self.get_stats().to_dict(),
        }


# =============================================================================
# Global Instance
# =============================================================================

_aggregator: ResultAggregator | None = None
_aggregator_lock = threading.Lock()


def get_aggregator() -> ResultAggregator:
    """Get or create the global result aggregator."""
    global _aggregator
    if _aggregator is None:
        with _aggregator_lock:
            if _aggregator is None:
                _aggregator = ResultAggregator()
    return _aggregator


def reset_aggregator() -> None:
    """Reset the global aggregator (for testing)."""
    global _aggregator
    _aggregator = None
