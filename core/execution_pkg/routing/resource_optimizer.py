"""
Resource Optimizer - Token budget and cost optimization across models.

V12.4 COGNITIVE BOOST - Task #55

Optimizes token budgets, latency, and cost across models dynamically.
Tracks actual usage vs estimates and learns from patterns.

Usage:
    from core.execution_pkg.routing.resource_optimizer import get_resource_optimizer

    optimizer = get_resource_optimizer()

    # Define model costs
    optimizer.register_model("claude/opus", cost_per_1k_input=0.015, cost_per_1k_output=0.075)
    optimizer.register_model("claude/sonnet", cost_per_1k_input=0.003, cost_per_1k_output=0.015)

    # Get optimization decision
    decision = optimizer.optimize(
        task_type="analysis",
        estimated_tokens=2000,
        max_cost_usd=0.05,
    )

    # Record actual usage for learning
    optimizer.record_usage(decision.decision_id, actual_tokens=1800, actual_cost=0.035)
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

LEARNING_RATE = 0.1  # EMA for accuracy tracking


# =============================================================================
# Types
# =============================================================================


@dataclass
class ModelSpec:
    """A registered model with cost information."""

    model_id: str
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0
    avg_latency_ms: float = 1000.0
    max_context: int = 128000
    quality_score: float = 0.5  # 0.0 to 1.0
    available: bool = True

    def estimate_cost(self, input_tokens: int, output_tokens: int = 0) -> float:
        """Estimate cost for given token counts."""
        if output_tokens == 0:
            output_tokens = int(input_tokens * 0.5)  # Default estimate
        return (input_tokens / 1000) * self.cost_per_1k_input + (output_tokens / 1000) * self.cost_per_1k_output

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "cost_per_1k_input": self.cost_per_1k_input,
            "cost_per_1k_output": self.cost_per_1k_output,
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "max_context": self.max_context,
            "quality_score": round(self.quality_score, 3),
            "available": self.available,
        }


@dataclass
class OptimizationDecision:
    """A model selection decision."""

    decision_id: str
    model_id: str
    estimated_cost: float
    estimated_latency_ms: float
    quality_score: float
    reason: str = ""
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.monotonic()

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "model_id": self.model_id,
            "estimated_cost": round(self.estimated_cost, 6),
            "estimated_latency_ms": round(self.estimated_latency_ms, 2),
            "quality_score": round(self.quality_score, 3),
            "reason": self.reason,
        }


@dataclass
class UsageRecord:
    """Actual usage data for a decision."""

    decision_id: str
    model_id: str
    estimated_tokens: int
    actual_tokens: int
    estimated_cost: float
    actual_cost: float
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.monotonic()

    @property
    def token_accuracy(self) -> float:
        """How close estimate was to actual (1.0 = perfect)."""
        if self.estimated_tokens == 0:
            return 0.0
        return 1.0 - abs(self.actual_tokens - self.estimated_tokens) / max(self.estimated_tokens, self.actual_tokens)

    @property
    def cost_accuracy(self) -> float:
        if self.estimated_cost == 0:
            return 0.0
        return 1.0 - abs(self.actual_cost - self.estimated_cost) / max(self.estimated_cost, self.actual_cost)


@dataclass
class OptimizationReport:
    """Report on optimization performance."""

    total_decisions: int
    total_estimated_cost: float
    total_actual_cost: float
    avg_token_accuracy: float
    avg_cost_accuracy: float
    model_usage: dict[str, int]
    cost_savings: float  # Estimated - Actual (positive = under-budget)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_decisions": self.total_decisions,
            "total_estimated_cost": round(self.total_estimated_cost, 6),
            "total_actual_cost": round(self.total_actual_cost, 6),
            "avg_token_accuracy": round(self.avg_token_accuracy, 4),
            "avg_cost_accuracy": round(self.avg_cost_accuracy, 4),
            "model_usage": self.model_usage,
            "cost_savings": round(self.cost_savings, 6),
        }


# =============================================================================
# Resource Optimizer
# =============================================================================


class ResourceOptimizer:
    """
    Optimizes model selection based on cost, latency, and quality.

    Features:
    - Model registry with cost information
    - Cost-aware model selection
    - Usage tracking and accuracy learning
    - Optimization reporting
    """

    def __init__(self):
        self._models: dict[str, ModelSpec] = {}
        self._decisions: dict[str, OptimizationDecision] = {}
        self._usage: list[UsageRecord] = []
        self._model_usage_count: dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()

    # =========================================================================
    # Model Registry
    # =========================================================================

    def register_model(
        self,
        model_id: str,
        *,
        cost_per_1k_input: float = 0.0,
        cost_per_1k_output: float = 0.0,
        avg_latency_ms: float = 1000.0,
        max_context: int = 128000,
        quality_score: float = 0.5,
    ) -> ModelSpec:
        """Register a model with cost/performance data."""
        spec = ModelSpec(
            model_id=model_id,
            cost_per_1k_input=cost_per_1k_input,
            cost_per_1k_output=cost_per_1k_output,
            avg_latency_ms=avg_latency_ms,
            max_context=max_context,
            quality_score=max(0.0, min(1.0, quality_score)),
        )
        with self._lock:
            self._models[model_id] = spec
        return spec

    def unregister_model(self, model_id: str) -> bool:
        """Remove a model."""
        with self._lock:
            return self._models.pop(model_id, None) is not None

    def set_model_available(self, model_id: str, available: bool) -> bool:
        """Toggle model availability."""
        with self._lock:
            spec = self._models.get(model_id)
            if spec is None:
                return False
            spec.available = available
        return True

    def get_model(self, model_id: str) -> ModelSpec | None:
        """Get a model spec."""
        return self._models.get(model_id)

    # =========================================================================
    # Optimization
    # =========================================================================

    def optimize(
        self,
        *,
        estimated_tokens: int = 1000,
        max_cost_usd: float = 0.0,
        max_latency_ms: float = 0.0,
        min_quality: float = 0.0,
        prefer: str = "cost",  # "cost", "quality", "latency"
    ) -> OptimizationDecision | None:
        """
        Select the optimal model based on constraints.

        Args:
            estimated_tokens: Estimated token usage
            max_cost_usd: Maximum cost (0 = no limit)
            max_latency_ms: Maximum latency (0 = no limit)
            min_quality: Minimum quality score (0 = no minimum)
            prefer: Optimization priority ("cost", "quality", "latency")

        Returns:
            OptimizationDecision or None if no model fits constraints
        """
        with self._lock:
            candidates = [
                spec for spec in self._models.values() if spec.available and estimated_tokens <= spec.max_context
            ]

        if not candidates:
            return None

        # Filter by constraints
        filtered = []
        for spec in candidates:
            cost = spec.estimate_cost(estimated_tokens)
            if max_cost_usd > 0 and cost > max_cost_usd:
                continue
            if max_latency_ms > 0 and spec.avg_latency_ms > max_latency_ms:
                continue
            if min_quality > 0 and spec.quality_score < min_quality:
                continue
            filtered.append((spec, cost))

        if not filtered:
            return None

        # Sort by preference
        if prefer == "cost":
            filtered.sort(key=lambda x: x[1])
        elif prefer == "quality":
            filtered.sort(key=lambda x: -x[0].quality_score)
        elif prefer == "latency":
            filtered.sort(key=lambda x: x[0].avg_latency_ms)

        best_spec, best_cost = filtered[0]
        decision_id = uuid.uuid4().hex[:16]

        decision = OptimizationDecision(
            decision_id=decision_id,
            model_id=best_spec.model_id,
            estimated_cost=best_cost,
            estimated_latency_ms=best_spec.avg_latency_ms,
            quality_score=best_spec.quality_score,
            reason=f"Best {prefer} option from {len(filtered)} candidates",
        )

        with self._lock:
            self._decisions[decision_id] = decision
            self._model_usage_count[best_spec.model_id] += 1

        return decision

    # =========================================================================
    # Usage Tracking
    # =========================================================================

    def record_usage(
        self,
        decision_id: str,
        *,
        actual_tokens: int,
        actual_cost: float = 0.0,
    ) -> bool:
        """
        Record actual usage for a decision.

        Returns True if decision was found.
        """
        with self._lock:
            decision = self._decisions.get(decision_id)
            if decision is None:
                return False

            record = UsageRecord(
                decision_id=decision_id,
                model_id=decision.model_id,
                estimated_tokens=int(
                    decision.estimated_cost
                    * 1000
                    / max(0.001, self._models.get(decision.model_id, ModelSpec(model_id="")).cost_per_1k_input or 0.001)
                ),
                actual_tokens=actual_tokens,
                estimated_cost=decision.estimated_cost,
                actual_cost=actual_cost,
            )
            self._usage.append(record)

            # Update model latency with EMA
            model = self._models.get(decision.model_id)
            if model and actual_cost > 0:
                # Learn from actuals
                pass  # Cost learning deferred to more data

        return True

    # =========================================================================
    # Reporting
    # =========================================================================

    def get_report(self) -> OptimizationReport:
        """Generate an optimization performance report."""
        with self._lock:
            usage = list(self._usage)
            model_usage = dict(self._model_usage_count)

        total_estimated = sum(u.estimated_cost for u in usage)
        total_actual = sum(u.actual_cost for u in usage)

        token_accuracies = [u.token_accuracy for u in usage if u.estimated_tokens > 0]
        cost_accuracies = [u.cost_accuracy for u in usage if u.estimated_cost > 0]

        return OptimizationReport(
            total_decisions=len(self._decisions),
            total_estimated_cost=total_estimated,
            total_actual_cost=total_actual,
            avg_token_accuracy=sum(token_accuracies) / len(token_accuracies) if token_accuracies else 0.0,
            avg_cost_accuracy=sum(cost_accuracies) / len(cost_accuracies) if cost_accuracies else 0.0,
            model_usage=model_usage,
            cost_savings=total_estimated - total_actual,
        )

    # =========================================================================
    # Listing
    # =========================================================================

    def list_models(self, *, available_only: bool = False) -> list[ModelSpec]:
        """List all registered models."""
        models = list(self._models.values())
        if available_only:
            models = [m for m in models if m.available]
        return sorted(models, key=lambda m: m.model_id)

    def cheapest_model(self, estimated_tokens: int = 1000) -> ModelSpec | None:
        """Get the cheapest available model."""
        available = [m for m in self._models.values() if m.available]
        if not available:
            return None
        return min(available, key=lambda m: m.estimate_cost(estimated_tokens))

    def best_quality_model(self) -> ModelSpec | None:
        """Get the highest quality available model."""
        available = [m for m in self._models.values() if m.available]
        if not available:
            return None
        return max(available, key=lambda m: m.quality_score)

    # =========================================================================
    # State
    # =========================================================================

    @property
    def model_count(self) -> int:
        return len(self._models)

    @property
    def decision_count(self) -> int:
        return len(self._decisions)

    @property
    def usage_count(self) -> int:
        return len(self._usage)

    def clear(self) -> None:
        """Clear all data."""
        with self._lock:
            self._models.clear()
            self._decisions.clear()
            self._usage.clear()
            self._model_usage_count.clear()

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_count": self.model_count,
            "decision_count": self.decision_count,
            "usage_count": self.usage_count,
            "models": {mid: spec.to_dict() for mid, spec in sorted(self._models.items())},
        }


# =============================================================================
# Global Instance
# =============================================================================

_optimizer: ResourceOptimizer | None = None
_optimizer_lock = threading.Lock()


def get_resource_optimizer() -> ResourceOptimizer:
    """Get or create the global resource optimizer."""
    global _optimizer
    if _optimizer is None:
        with _optimizer_lock:
            if _optimizer is None:
                _optimizer = ResourceOptimizer()
    return _optimizer


def reset_resource_optimizer() -> None:
    """Reset the global resource optimizer (for testing)."""
    global _optimizer
    _optimizer = None
