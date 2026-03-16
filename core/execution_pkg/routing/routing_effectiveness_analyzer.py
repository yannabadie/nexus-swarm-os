"""
Routing Effectiveness Analyzer - Track and analyze routing decision outcomes.

V12.4 COGNITIVE BOOST

Tracks routing decision outcomes to determine whether selected models/routes
were optimal, analyzes policy effectiveness, and monitors cost-quality tradeoffs.

This module provides:
- Per-decision tracking (policy, model, task type, outcome)
- Policy-level metrics (optimality rate, average quality, average latency)
- Cross-policy comparison
- Model-specific decision filtering
- Recent decision history

Usage:
    from core.execution_pkg.routing.routing_effectiveness_analyzer import get_routing_analyzer

    analyzer = get_routing_analyzer()

    # Record a routing decision
    record = analyzer.record_decision(
        policy="COST_OPTIMIZED",
        selected_model="claude-sonnet-4-5",
        task_type="coding:python",
        outcome_quality=0.85,
        cost_tokens=1200,
        latency_ms=850.0,
        was_optimal=True
    )

    # Get policy metrics
    metrics = analyzer.get_policy_metrics("COST_OPTIMIZED")
    print(f"Optimality rate: {metrics.optimality_rate}")

    # Find best policy
    best = analyzer.get_best_policy()
    print(f"Best policy: {best}")

    # Get overall stats
    stats = analyzer.get_stats()

Thread Safety:
    All methods are thread-safe using a single threading.Lock.

Author: Claude (NEXUS V12.4)
Date: 2026-02-16
"""

from __future__ import annotations

import dataclasses
import logging
import threading
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

MAX_DECISIONS: int = 50000


# =============================================================================
# Dataclasses
# =============================================================================


@dataclass
class RoutingDecisionRecord:
    """
    A single routing decision record.

    Captures all metadata about a routing decision and its outcome,
    enabling post-hoc analysis of routing effectiveness.

    Attributes:
        decision_id: Auto-generated unique ID (format: rd_XXXXXX).
        policy: Routing policy used (e.g., "COST_OPTIMIZED", "QUALITY_FIRST").
        selected_model: Model selected by the policy.
        task_type: Type of task being routed.
        outcome_quality: Quality score of the outcome (0.0-1.0).
        cost_tokens: Token cost of the decision.
        latency_ms: Latency in milliseconds.
        was_optimal: Whether this selection was optimal in hindsight.
        timestamp: ISO timestamp of the decision.
    """

    decision_id: str = ""
    policy: str = ""
    selected_model: str = ""
    task_type: str = ""
    outcome_quality: float = 0.0
    cost_tokens: int = 0
    latency_ms: float = 0.0
    was_optimal: bool = True
    timestamp: str = ""

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return dataclasses.asdict(self)


@dataclass
class PolicyMetrics:
    """
    Aggregate metrics for a routing policy.

    Tracks total decisions, optimal decisions, quality, cost, and latency
    for a specific routing policy. Includes computed properties for rates
    and averages.

    Attributes:
        policy: Policy name.
        total_decisions: Total number of decisions made with this policy.
        optimal_decisions: Number of decisions that were optimal.
        total_quality: Sum of quality scores across all decisions.
        total_cost_tokens: Sum of token costs across all decisions.
        total_latency_ms: Sum of latency across all decisions.
    """

    policy: str = ""
    total_decisions: int = 0
    optimal_decisions: int = 0
    total_quality: float = 0.0
    total_cost_tokens: int = 0
    total_latency_ms: float = 0.0

    @property
    def optimality_rate(self) -> float:
        """Compute optimality rate (optimal / total)."""
        if self.total_decisions == 0:
            return 0.0
        return self.optimal_decisions / self.total_decisions

    @property
    def avg_quality(self) -> float:
        """Compute average quality score."""
        if self.total_decisions == 0:
            return 0.0
        return self.total_quality / self.total_decisions

    @property
    def avg_latency_ms(self) -> float:
        """Compute average latency in milliseconds."""
        if self.total_decisions == 0:
            return 0.0
        return self.total_latency_ms / self.total_decisions

    def to_dict(self) -> dict:
        """
        Convert to dictionary, including computed properties.

        Returns:
            Dictionary with all fields plus computed properties.
        """
        data = dataclasses.asdict(self)
        data["optimality_rate"] = round(self.optimality_rate, 4)
        data["avg_quality"] = round(self.avg_quality, 4)
        data["avg_latency_ms"] = round(self.avg_latency_ms, 2)
        return data


@dataclass
class AnalyzerStats:
    """
    Overall statistics for the analyzer.

    Provides high-level metrics about all routing decisions tracked
    by the analyzer.

    Attributes:
        total_decisions: Total number of decisions recorded.
        unique_policies: Number of distinct policies seen.
        unique_models: Number of distinct models used.
        overall_optimality_rate: Global optimality rate across all policies.
    """

    total_decisions: int = 0
    unique_policies: int = 0
    unique_models: int = 0
    overall_optimality_rate: float = 0.0

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return dataclasses.asdict(self)


# =============================================================================
# Main Analyzer Class
# =============================================================================


class RoutingEffectivenessAnalyzer:
    """
    Thread-safe analyzer for routing decision effectiveness.

    Tracks routing decisions and their outcomes to enable analysis of:
    - Which policies produce the best results
    - Whether model selections were optimal
    - Cost vs. quality tradeoffs
    - Latency characteristics per policy

    Features:
    - Bounded FIFO history (max 50k decisions by default)
    - Thread-safe operations via threading.Lock
    - Per-policy aggregation
    - Model-specific filtering
    - Recent decision queries

    Example:
        >>> analyzer = RoutingEffectivenessAnalyzer()
        >>> record = analyzer.record_decision(
        ...     policy="BALANCED",
        ...     selected_model="claude-opus-4-6",
        ...     task_type="brainstorm",
        ...     outcome_quality=0.92,
        ...     cost_tokens=2500,
        ...     latency_ms=1200.0,
        ...     was_optimal=True
        ... )
        >>> metrics = analyzer.get_policy_metrics("BALANCED")
        >>> print(f"Optimality: {metrics.optimality_rate:.2%}")
    """

    def __init__(self, max_decisions: int = MAX_DECISIONS) -> None:
        """
        Initialize the analyzer.

        Args:
            max_decisions: Maximum number of decisions to retain (FIFO eviction).
        """
        self._max_decisions = max_decisions
        self._lock = threading.Lock()

        # Decision history (FIFO deque)
        self._decisions: deque[RoutingDecisionRecord] = deque(maxlen=max_decisions)

        # Per-policy aggregated metrics
        self._policy_metrics: dict[str, PolicyMetrics] = {}

        # Counter for generating decision IDs
        self._counter = 0

        # Track unique models seen
        self._models_seen: set[str] = set()

        _logger.debug(f"[ROUTING] RoutingEffectivenessAnalyzer initialized (max_decisions={max_decisions})")

    def record_decision(
        self,
        policy: str,
        selected_model: str = "",
        task_type: str = "",
        outcome_quality: float = 0.0,
        cost_tokens: int = 0,
        latency_ms: float = 0.0,
        was_optimal: bool = True,
    ) -> RoutingDecisionRecord:
        """
        Record a routing decision and update policy metrics.

        Thread-safe method that creates a decision record, updates policy
        aggregates, and handles FIFO eviction if at max capacity.

        Args:
            policy: Routing policy used (e.g., "COST_OPTIMIZED").
            selected_model: Model selected by the policy.
            task_type: Type of task being routed.
            outcome_quality: Quality score (0.0-1.0).
            cost_tokens: Token cost.
            latency_ms: Latency in milliseconds.
            was_optimal: Whether the selection was optimal.

        Returns:
            The created RoutingDecisionRecord.
        """
        with self._lock:
            # Generate decision ID
            decision_id = f"rd_{self._counter:06d}"
            self._counter += 1

            # Create record
            record = RoutingDecisionRecord(
                decision_id=decision_id,
                policy=policy,
                selected_model=selected_model,
                task_type=task_type,
                outcome_quality=outcome_quality,
                cost_tokens=cost_tokens,
                latency_ms=latency_ms,
                was_optimal=was_optimal,
                timestamp=datetime.now(UTC).isoformat(),
            )

            # Update policy metrics
            if policy not in self._policy_metrics:
                self._policy_metrics[policy] = PolicyMetrics(policy=policy)

            metrics = self._policy_metrics[policy]
            metrics.total_decisions += 1
            if was_optimal:
                metrics.optimal_decisions += 1
            metrics.total_quality += outcome_quality
            metrics.total_cost_tokens += cost_tokens
            metrics.total_latency_ms += latency_ms

            # Track unique models
            if selected_model:
                self._models_seen.add(selected_model)

            # Append to history (FIFO eviction handled by deque maxlen)
            self._decisions.append(record)

            _logger.debug(
                f"[ROUTING] Recorded decision {decision_id}: "
                f"policy={policy}, model={selected_model}, optimal={was_optimal}"
            )

            return record

    def get_policy_metrics(self, policy: str) -> PolicyMetrics | None:
        """
        Get aggregated metrics for a specific policy.

        Args:
            policy: Policy name to look up.

        Returns:
            PolicyMetrics for the policy, or None if not found.
        """
        with self._lock:
            return self._policy_metrics.get(policy)

    def get_all_metrics(self) -> list[PolicyMetrics]:
        """
        Get metrics for all policies, sorted by total decisions descending.

        Returns:
            List of PolicyMetrics, ordered by most-used policies first.
        """
        with self._lock:
            metrics = list(self._policy_metrics.values())
            metrics.sort(key=lambda m: m.total_decisions, reverse=True)
            return metrics

    def get_best_policy(self) -> str | None:
        """
        Get the policy with the highest optimality rate.

        Returns:
            Policy name with highest optimality rate, or None if no policies.
        """
        with self._lock:
            if not self._policy_metrics:
                return None

            best = max(self._policy_metrics.values(), key=lambda m: m.optimality_rate)
            return best.policy

    def get_decisions_by_model(self, model: str) -> list[RoutingDecisionRecord]:
        """
        Get all decisions that selected a specific model.

        Args:
            model: Model ID to filter by.

        Returns:
            List of RoutingDecisionRecord instances, chronological order.
        """
        with self._lock:
            return [record for record in self._decisions if record.selected_model == model]

    def get_recent_decisions(self, limit: int = 10) -> list[RoutingDecisionRecord]:
        """
        Get the most recent decisions.

        Args:
            limit: Maximum number of decisions to return.

        Returns:
            List of RoutingDecisionRecord instances, most recent first.
        """
        with self._lock:
            # Deque is chronological (oldest to newest)
            # Convert to list and reverse to get newest first
            recent = list(self._decisions)
            recent.reverse()
            return recent[:limit]

    def list_policies(self) -> list[str]:
        """
        List all policies that have been used, alphabetically sorted.

        Returns:
            List of policy names.
        """
        with self._lock:
            policies = list(self._policy_metrics.keys())
            policies.sort()
            return policies

    def get_stats(self) -> AnalyzerStats:
        """
        Get overall analyzer statistics.

        Returns:
            AnalyzerStats with global metrics.
        """
        with self._lock:
            total_decisions = len(self._decisions)
            unique_policies = len(self._policy_metrics)
            unique_models = len(self._models_seen)

            # Calculate overall optimality rate
            if total_decisions == 0:
                overall_optimality = 0.0
            else:
                total_optimal = sum(1 for record in self._decisions if record.was_optimal)
                overall_optimality = total_optimal / total_decisions

            return AnalyzerStats(
                total_decisions=total_decisions,
                unique_policies=unique_policies,
                unique_models=unique_models,
                overall_optimality_rate=overall_optimality,
            )

    @property
    def decision_count(self) -> int:
        """
        Get the current number of decisions stored.

        Returns:
            Number of decisions in history.
        """
        with self._lock:
            return len(self._decisions)

    def clear(self) -> None:
        """
        Clear all decisions and metrics.

        Thread-safe operation that resets the analyzer to initial state.
        """
        with self._lock:
            self._decisions.clear()
            self._policy_metrics.clear()
            self._models_seen.clear()
            self._counter = 0

            _logger.info("[ROUTING] RoutingEffectivenessAnalyzer cleared")

    def to_dict(self) -> dict:
        """
        Convert analyzer state to dictionary.

        CRITICAL: Calls get_stats() BEFORE acquiring lock to prevent deadlock.

        Returns:
            Dictionary with stats and policy metrics.
        """
        # DEADLOCK PREVENTION: Get stats first (which acquires lock internally)
        stats = self.get_stats()

        with self._lock:
            return {
                "stats": stats.to_dict(),
                "policies": {policy: metrics.to_dict() for policy, metrics in self._policy_metrics.items()},
                "max_decisions": self._max_decisions,
                "decision_count": len(self._decisions),
            }


# =============================================================================
# Singleton Pattern (V12.4)
# =============================================================================

_instance: RoutingEffectivenessAnalyzer | None = None
_lock = threading.Lock()


def get_routing_analyzer(max_decisions: int = MAX_DECISIONS) -> RoutingEffectivenessAnalyzer:
    """
    Get the global RoutingEffectivenessAnalyzer singleton.

    Uses double-checked locking pattern for thread-safe lazy initialization.

    Args:
        max_decisions: Maximum decisions to retain (only used on first call).

    Returns:
        The global RoutingEffectivenessAnalyzer instance.
    """
    global _instance

    # First check (no lock)
    if _instance is not None:
        return _instance

    # Second check (with lock)
    with _lock:
        if _instance is None:
            _instance = RoutingEffectivenessAnalyzer(max_decisions=max_decisions)
            _logger.debug("[ROUTING] Global RoutingEffectivenessAnalyzer created")

        return _instance


def reset_routing_analyzer() -> None:
    """
    Reset the global RoutingEffectivenessAnalyzer singleton.

    Used primarily for testing to ensure clean state between tests.
    """
    global _instance

    with _lock:
        _instance = None
        _logger.debug("[ROUTING] Global RoutingEffectivenessAnalyzer reset")
