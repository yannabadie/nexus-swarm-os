"""
Strategy Performance Tracker - Track mutation strategy effectiveness per domain.

V12.4 COGNITIVE BOOST

Tracks which mutation strategies (e.g. "code_specialist", "reasoning_enhancer")
produce the best fitness improvements for each domain (e.g. "python", "security"),
enabling smarter future mutation decisions.

Usage:
    from core.intelligence.evolution.strategy_performance_tracker import get_strategy_tracker

    tracker = get_strategy_tracker()

    # Record a strategy application
    tracker.record_application(
        "code_specialist",
        "python",
        parent_id="agent_v1",
        child_id="agent_v1a",
        fitness_before=0.6,
        fitness_after=0.85,
    )

    # Get recommendation for a domain
    rec = tracker.recommend_strategy("python")
    # StrategyRecommendation(strategy="code_specialist", confidence=0.5, ...)

    # Get domain ranking
    ranking = tracker.get_domain_ranking("python")
    # [("code_specialist", 0.25), ("reasoning_enhancer", 0.10)]
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

MAX_APPLICATIONS = 50000
MIN_TRIALS_FOR_RECOMMENDATION = 3


# =============================================================================
# Types
# =============================================================================


@dataclass
class StrategyApplication:
    """A single recorded application of a mutation strategy."""

    strategy: str
    domain: str
    parent_id: str = ""
    child_id: str = ""
    fitness_before: float = 0.0
    fitness_after: float = 0.0
    success: bool = True
    timestamp: float = field(default_factory=time.monotonic)

    @property
    def fitness_delta(self) -> float:
        return self.fitness_after - self.fitness_before

    @property
    def improvement(self) -> float:
        if self.fitness_before > 0:
            return self.fitness_delta / self.fitness_before
        return 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "domain": self.domain,
            "parent_id": self.parent_id,
            "child_id": self.child_id,
            "fitness_before": round(self.fitness_before, 4),
            "fitness_after": round(self.fitness_after, 4),
            "fitness_delta": round(self.fitness_delta, 4),
            "improvement": round(self.improvement, 4),
            "success": self.success,
        }


@dataclass
class StrategyMetrics:
    """Aggregated metrics for a mutation strategy across all domains."""

    strategy: str
    total_applications: int = 0
    successes: int = 0
    avg_fitness_delta: float = 0.0
    best_domain: str = ""
    worst_domain: str = ""

    @property
    def success_rate(self) -> float:
        if self.total_applications == 0:
            return 0.0
        return self.successes / self.total_applications

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "total_applications": self.total_applications,
            "successes": self.successes,
            "success_rate": round(self.success_rate, 4),
            "avg_fitness_delta": round(self.avg_fitness_delta, 4),
            "best_domain": self.best_domain,
            "worst_domain": self.worst_domain,
        }


@dataclass
class StrategyRecommendation:
    """A recommendation for which strategy to use in a given domain."""

    strategy: str
    confidence: float
    expected_improvement: float
    based_on_trials: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "confidence": round(self.confidence, 4),
            "expected_improvement": round(self.expected_improvement, 4),
            "based_on_trials": self.based_on_trials,
        }


@dataclass
class TrackerStats:
    """Summary statistics for the strategy performance tracker."""

    total_applications: int
    unique_strategies: int
    unique_domains: int
    overall_success_rate: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_applications": self.total_applications,
            "unique_strategies": self.unique_strategies,
            "unique_domains": self.unique_domains,
            "overall_success_rate": round(self.overall_success_rate, 4),
        }


# =============================================================================
# Strategy Performance Tracker
# =============================================================================


class StrategyPerformanceTracker:
    """
    Tracks mutation strategy performance per domain.

    Features:
    - Record strategy applications with fitness outcomes
    - Per-strategy aggregated metrics (success rate, avg fitness delta)
    - Per-domain strategy ranking
    - Strategy recommendations based on historical performance
    - Bounded history with configurable max
    - Thread-safe operations
    """

    def __init__(self, *, max_applications: int = MAX_APPLICATIONS):
        self._applications: list[StrategyApplication] = []
        self._metrics: dict[str, StrategyMetrics] = {}
        self._domain_strategies: dict[str, dict[str, list[float]]] = {}
        self._max_applications = max_applications
        self._lock = threading.Lock()

    # =========================================================================
    # Recording
    # =========================================================================

    def record_application(
        self,
        strategy: str,
        domain: str,
        *,
        parent_id: str = "",
        child_id: str = "",
        fitness_before: float = 0.0,
        fitness_after: float = 0.0,
        success: bool = True,
    ) -> StrategyApplication:
        """
        Record a strategy application and update aggregated metrics.

        Args:
            strategy: Mutation strategy name (e.g. "code_specialist")
            domain: Target domain (e.g. "python", "security")
            parent_id: Parent agent identifier
            child_id: Child agent identifier
            fitness_before: Fitness score before mutation
            fitness_after: Fitness score after mutation
            success: Whether the mutation was successful

        Returns:
            The recorded StrategyApplication
        """
        app = StrategyApplication(
            strategy=strategy,
            domain=domain,
            parent_id=parent_id,
            child_id=child_id,
            fitness_before=fitness_before,
            fitness_after=fitness_after,
            success=success,
        )

        with self._lock:
            self._applications.append(app)

            # Evict oldest if at capacity
            while len(self._applications) > self._max_applications:
                self._applications.pop(0)

            # Update strategy metrics
            metrics = self._metrics.get(strategy)
            if metrics is None:
                metrics = StrategyMetrics(strategy=strategy)
                self._metrics[strategy] = metrics

            metrics.total_applications += 1
            if success:
                metrics.successes += 1

            # Running average for fitness delta
            n = metrics.total_applications
            metrics.avg_fitness_delta = (metrics.avg_fitness_delta * (n - 1) + app.fitness_delta) / n

            # Update domain strategies
            if domain not in self._domain_strategies:
                self._domain_strategies[domain] = {}
            dom_strats = self._domain_strategies[domain]
            if strategy not in dom_strats:
                dom_strats[strategy] = []
            dom_strats[strategy].append(app.fitness_delta)

            # Recompute best/worst domain for this strategy
            self._update_best_worst_domain(strategy)

        return app

    def _update_best_worst_domain(self, strategy: str) -> None:
        """
        Recompute best and worst domains for a strategy.

        Must be called while self._lock is held.
        """
        metrics = self._metrics.get(strategy)
        if metrics is None:
            return

        domain_avgs: dict[str, float] = {}
        for domain, strats in self._domain_strategies.items():
            deltas = strats.get(strategy)
            if deltas:
                domain_avgs[domain] = sum(deltas) / len(deltas)

        if domain_avgs:
            metrics.best_domain = max(domain_avgs, key=domain_avgs.get)  # type: ignore[arg-type]
            metrics.worst_domain = min(domain_avgs, key=domain_avgs.get)  # type: ignore[arg-type]

    # =========================================================================
    # Analysis
    # =========================================================================

    def get_strategy_metrics(self, strategy: str) -> StrategyMetrics | None:
        """Get aggregated metrics for a specific strategy."""
        with self._lock:
            metrics = self._metrics.get(strategy)
            if metrics is None:
                return None
            # Return a copy to avoid external mutation
            return StrategyMetrics(
                strategy=metrics.strategy,
                total_applications=metrics.total_applications,
                successes=metrics.successes,
                avg_fitness_delta=metrics.avg_fitness_delta,
                best_domain=metrics.best_domain,
                worst_domain=metrics.worst_domain,
            )

    def get_all_metrics(self) -> list[StrategyMetrics]:
        """
        Get metrics for all strategies, sorted by success rate descending.

        Returns:
            List of StrategyMetrics sorted by success_rate (highest first)
        """
        with self._lock:
            result = [
                StrategyMetrics(
                    strategy=m.strategy,
                    total_applications=m.total_applications,
                    successes=m.successes,
                    avg_fitness_delta=m.avg_fitness_delta,
                    best_domain=m.best_domain,
                    worst_domain=m.worst_domain,
                )
                for m in self._metrics.values()
            ]
        result.sort(key=lambda m: m.success_rate, reverse=True)
        return result

    def recommend_strategy(
        self,
        domain: str,
        *,
        min_trials: int = MIN_TRIALS_FOR_RECOMMENDATION,
    ) -> StrategyRecommendation | None:
        """
        Recommend the best strategy for a given domain.

        Finds the strategy with the highest average fitness delta
        that has at least min_trials recorded trials in the domain.

        Args:
            domain: Target domain
            min_trials: Minimum number of trials required

        Returns:
            StrategyRecommendation or None if insufficient data
        """
        with self._lock:
            dom_strats = self._domain_strategies.get(domain)
            if not dom_strats:
                return None

            best_strategy: str | None = None
            best_avg: float = float("-inf")
            best_trials: int = 0

            for strategy, deltas in dom_strats.items():
                if len(deltas) < min_trials:
                    continue
                avg = sum(deltas) / len(deltas)
                if avg > best_avg:
                    best_avg = avg
                    best_strategy = strategy
                    best_trials = len(deltas)

        if best_strategy is None:
            return None

        confidence = min(1.0, best_trials / (best_trials + min_trials))

        return StrategyRecommendation(
            strategy=best_strategy,
            confidence=confidence,
            expected_improvement=best_avg,
            based_on_trials=best_trials,
        )

    def get_domain_ranking(self, domain: str) -> list[tuple[str, float]]:
        """
        Rank strategies by average fitness delta for a domain.

        Args:
            domain: Target domain

        Returns:
            List of (strategy, avg_fitness_delta) sorted descending
        """
        with self._lock:
            dom_strats = self._domain_strategies.get(domain)
            if not dom_strats:
                return []

            ranking = [(strategy, sum(deltas) / len(deltas)) for strategy, deltas in dom_strats.items() if deltas]

        ranking.sort(key=lambda x: x[1], reverse=True)
        return ranking

    def list_strategies(self) -> list[str]:
        """List all recorded strategy names."""
        with self._lock:
            return sorted(self._metrics.keys())

    def list_domains(self) -> list[str]:
        """List all recorded domain names."""
        with self._lock:
            return sorted(self._domain_strategies.keys())

    # =========================================================================
    # State
    # =========================================================================

    def get_stats(self) -> TrackerStats:
        """Get summary statistics."""
        with self._lock:
            total = len(self._applications)
            strategies = len(self._metrics)
            domains = len(self._domain_strategies)
            successes = sum(m.successes for m in self._metrics.values())
            total_apps = sum(m.total_applications for m in self._metrics.values())

        overall_rate = successes / total_apps if total_apps > 0 else 0.0

        return TrackerStats(
            total_applications=total,
            unique_strategies=strategies,
            unique_domains=domains,
            overall_success_rate=overall_rate,
        )

    @property
    def application_count(self) -> int:
        return len(self._applications)

    def clear(self) -> None:
        """Clear all tracked data."""
        with self._lock:
            self._applications.clear()
            self._metrics.clear()
            self._domain_strategies.clear()

    def to_dict(self) -> dict[str, Any]:
        stats = self.get_stats()
        return {
            "application_count": self.application_count,
            "stats": stats.to_dict(),
        }


# =============================================================================
# Global Instance
# =============================================================================

_tracker: StrategyPerformanceTracker | None = None
_tracker_lock = threading.Lock()


def get_strategy_tracker() -> StrategyPerformanceTracker:
    """Get or create the global strategy performance tracker."""
    global _tracker
    if _tracker is None:
        with _tracker_lock:
            if _tracker is None:
                _tracker = StrategyPerformanceTracker()
    return _tracker


def reset_strategy_tracker() -> None:
    """Reset the global strategy performance tracker (for testing)."""
    global _tracker
    _tracker = None
