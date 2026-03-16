"""
Tests for V12.4 Resource Optimizer.

Validates:
- Model registration and specs
- Cost estimation
- Optimization decisions (cost, quality, latency)
- Constraint filtering (max cost, max latency, min quality)
- Usage tracking
- Optimization report
- Model listing (cheapest, best quality)
- State management
- Global singleton
- Module exports
"""

from core.execution_pkg.routing.resource_optimizer import (
    ModelSpec,
    OptimizationDecision,
    ResourceOptimizer,
    UsageRecord,
    get_resource_optimizer,
    reset_resource_optimizer,
)

# =============================================================================
# ModelSpec Tests
# =============================================================================


class TestModelSpec:
    """Test ModelSpec dataclass."""

    def test_basic_creation(self):
        spec = ModelSpec(model_id="claude/opus", cost_per_1k_input=0.015)
        assert spec.model_id == "claude/opus"
        assert spec.available is True

    def test_estimate_cost(self):
        spec = ModelSpec(
            model_id="test",
            cost_per_1k_input=0.01,
            cost_per_1k_output=0.03,
        )
        cost = spec.estimate_cost(1000, 500)
        assert abs(cost - 0.025) < 0.001  # 0.01 + 0.015

    def test_estimate_cost_default_output(self):
        spec = ModelSpec(
            model_id="test",
            cost_per_1k_input=0.01,
            cost_per_1k_output=0.03,
        )
        cost = spec.estimate_cost(2000)
        # 2000 input + 1000 output (50% default)
        assert cost > 0

    def test_to_dict(self):
        spec = ModelSpec(model_id="claude/opus", quality_score=0.95)
        d = spec.to_dict()
        assert d["model_id"] == "claude/opus"
        assert d["quality_score"] == 0.95


# =============================================================================
# Register Tests
# =============================================================================


class TestRegister:
    """Test model registration."""

    def test_register(self):
        opt = ResourceOptimizer()
        spec = opt.register_model("claude/opus", cost_per_1k_input=0.015)
        assert spec.model_id == "claude/opus"
        assert opt.model_count == 1

    def test_register_multiple(self):
        opt = ResourceOptimizer()
        opt.register_model("claude/opus")
        opt.register_model("claude/sonnet")
        opt.register_model("gemini/pro")
        assert opt.model_count == 3

    def test_register_with_quality(self):
        opt = ResourceOptimizer()
        spec = opt.register_model("claude/opus", quality_score=0.95)
        assert spec.quality_score == 0.95

    def test_quality_clamped(self):
        opt = ResourceOptimizer()
        spec = opt.register_model("test", quality_score=1.5)
        assert spec.quality_score == 1.0

    def test_unregister(self):
        opt = ResourceOptimizer()
        opt.register_model("test")
        assert opt.unregister_model("test") is True
        assert opt.model_count == 0

    def test_unregister_not_found(self):
        opt = ResourceOptimizer()
        assert opt.unregister_model("missing") is False

    def test_set_available(self):
        opt = ResourceOptimizer()
        opt.register_model("test")
        assert opt.set_model_available("test", False) is True
        assert opt.get_model("test").available is False

    def test_set_available_not_found(self):
        opt = ResourceOptimizer()
        assert opt.set_model_available("missing", True) is False

    def test_get_model(self):
        opt = ResourceOptimizer()
        opt.register_model("test", cost_per_1k_input=0.01)
        spec = opt.get_model("test")
        assert spec is not None
        assert spec.cost_per_1k_input == 0.01

    def test_get_model_not_found(self):
        opt = ResourceOptimizer()
        assert opt.get_model("missing") is None


# =============================================================================
# Optimization Tests
# =============================================================================


class TestOptimization:
    """Test optimization decisions."""

    def _setup_models(self) -> ResourceOptimizer:
        opt = ResourceOptimizer()
        opt.register_model(
            "cheap", cost_per_1k_input=0.001, cost_per_1k_output=0.002, quality_score=0.3, avg_latency_ms=200
        )
        opt.register_model(
            "mid", cost_per_1k_input=0.005, cost_per_1k_output=0.015, quality_score=0.7, avg_latency_ms=500
        )
        opt.register_model(
            "expensive", cost_per_1k_input=0.015, cost_per_1k_output=0.075, quality_score=0.95, avg_latency_ms=2000
        )
        return opt

    def test_optimize_cost(self):
        opt = self._setup_models()
        decision = opt.optimize(estimated_tokens=1000, prefer="cost")
        assert decision is not None
        assert decision.model_id == "cheap"

    def test_optimize_quality(self):
        opt = self._setup_models()
        decision = opt.optimize(estimated_tokens=1000, prefer="quality")
        assert decision is not None
        assert decision.model_id == "expensive"

    def test_optimize_latency(self):
        opt = self._setup_models()
        decision = opt.optimize(estimated_tokens=1000, prefer="latency")
        assert decision is not None
        assert decision.model_id == "cheap"

    def test_optimize_max_cost_filter(self):
        opt = self._setup_models()
        decision = opt.optimize(estimated_tokens=1000, max_cost_usd=0.005, prefer="quality")
        assert decision is not None
        assert decision.model_id != "expensive"

    def test_optimize_max_latency_filter(self):
        opt = self._setup_models()
        decision = opt.optimize(estimated_tokens=1000, max_latency_ms=300, prefer="quality")
        assert decision is not None
        assert decision.model_id == "cheap"

    def test_optimize_min_quality_filter(self):
        opt = self._setup_models()
        decision = opt.optimize(estimated_tokens=1000, min_quality=0.9, prefer="cost")
        assert decision is not None
        assert decision.model_id == "expensive"

    def test_optimize_no_candidates(self):
        opt = ResourceOptimizer()
        decision = opt.optimize(estimated_tokens=1000)
        assert decision is None

    def test_optimize_all_filtered(self):
        opt = self._setup_models()
        decision = opt.optimize(estimated_tokens=1000, max_cost_usd=0.0001)
        assert decision is None

    def test_optimize_unavailable_excluded(self):
        opt = self._setup_models()
        opt.set_model_available("cheap", False)
        decision = opt.optimize(estimated_tokens=1000, prefer="cost")
        assert decision.model_id == "mid"

    def test_decision_has_id(self):
        opt = self._setup_models()
        decision = opt.optimize(estimated_tokens=1000)
        assert decision.decision_id
        assert len(decision.decision_id) == 16

    def test_decision_to_dict(self):
        opt = self._setup_models()
        decision = opt.optimize(estimated_tokens=1000)
        d = decision.to_dict()
        assert "decision_id" in d
        assert "model_id" in d
        assert "estimated_cost" in d
        assert "reason" in d

    def test_decision_count_increments(self):
        opt = self._setup_models()
        opt.optimize(estimated_tokens=1000)
        opt.optimize(estimated_tokens=2000)
        assert opt.decision_count == 2


# =============================================================================
# Usage Tracking Tests
# =============================================================================


class TestUsageTracking:
    """Test usage recording."""

    def test_record_usage(self):
        opt = ResourceOptimizer()
        opt.register_model("test", cost_per_1k_input=0.01)
        decision = opt.optimize(estimated_tokens=1000)
        assert opt.record_usage(decision.decision_id, actual_tokens=950, actual_cost=0.01) is True
        assert opt.usage_count == 1

    def test_record_usage_not_found(self):
        opt = ResourceOptimizer()
        assert opt.record_usage("missing", actual_tokens=1000) is False

    def test_usage_record_accuracy(self):
        record = UsageRecord(
            decision_id="d1",
            model_id="test",
            estimated_tokens=1000,
            actual_tokens=900,
            estimated_cost=0.01,
            actual_cost=0.009,
        )
        assert record.token_accuracy > 0.8
        assert record.cost_accuracy > 0.8

    def test_usage_record_zero_estimate(self):
        record = UsageRecord(
            decision_id="d1",
            model_id="test",
            estimated_tokens=0,
            actual_tokens=100,
            estimated_cost=0,
            actual_cost=0.01,
        )
        assert record.token_accuracy == 0.0
        assert record.cost_accuracy == 0.0


# =============================================================================
# Report Tests
# =============================================================================


class TestReport:
    """Test optimization reporting."""

    def test_empty_report(self):
        opt = ResourceOptimizer()
        report = opt.get_report()
        assert report.total_decisions == 0
        assert report.total_estimated_cost == 0.0

    def test_report_with_data(self):
        opt = ResourceOptimizer()
        opt.register_model("test", cost_per_1k_input=0.01, cost_per_1k_output=0.03)
        decision = opt.optimize(estimated_tokens=1000)
        opt.record_usage(decision.decision_id, actual_tokens=950, actual_cost=0.02)
        report = opt.get_report()
        assert report.total_decisions == 1
        assert report.total_actual_cost == 0.02

    def test_report_to_dict(self):
        opt = ResourceOptimizer()
        report = opt.get_report()
        d = report.to_dict()
        assert "total_decisions" in d
        assert "model_usage" in d
        assert "cost_savings" in d


# =============================================================================
# Listing Tests
# =============================================================================


class TestListing:
    """Test model listing."""

    def test_list_models(self):
        opt = ResourceOptimizer()
        opt.register_model("b_model")
        opt.register_model("a_model")
        models = opt.list_models()
        assert [m.model_id for m in models] == ["a_model", "b_model"]

    def test_list_available_only(self):
        opt = ResourceOptimizer()
        opt.register_model("available")
        opt.register_model("unavailable")
        opt.set_model_available("unavailable", False)
        models = opt.list_models(available_only=True)
        assert len(models) == 1

    def test_cheapest_model(self):
        opt = ResourceOptimizer()
        opt.register_model("expensive", cost_per_1k_input=0.015)
        opt.register_model("cheap", cost_per_1k_input=0.001)
        assert opt.cheapest_model().model_id == "cheap"

    def test_cheapest_model_empty(self):
        opt = ResourceOptimizer()
        assert opt.cheapest_model() is None

    def test_best_quality_model(self):
        opt = ResourceOptimizer()
        opt.register_model("low", quality_score=0.3)
        opt.register_model("high", quality_score=0.95)
        assert opt.best_quality_model().model_id == "high"

    def test_best_quality_empty(self):
        opt = ResourceOptimizer()
        assert opt.best_quality_model() is None


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_counts(self):
        opt = ResourceOptimizer()
        assert opt.model_count == 0
        assert opt.decision_count == 0
        assert opt.usage_count == 0

    def test_clear(self):
        opt = ResourceOptimizer()
        opt.register_model("test")
        opt.optimize(estimated_tokens=100)
        opt.clear()
        assert opt.model_count == 0
        assert opt.decision_count == 0

    def test_to_dict(self):
        opt = ResourceOptimizer()
        opt.register_model("test", cost_per_1k_input=0.01)
        d = opt.to_dict()
        assert d["model_count"] == 1
        assert "test" in d["models"]


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global optimizer."""

    def test_get_resource_optimizer(self):
        reset_resource_optimizer()
        opt = get_resource_optimizer()
        assert isinstance(opt, ResourceOptimizer)

    def test_singleton(self):
        reset_resource_optimizer()
        o1 = get_resource_optimizer()
        o2 = get_resource_optimizer()
        assert o1 is o2

    def test_reset(self):
        reset_resource_optimizer()
        o1 = get_resource_optimizer()
        reset_resource_optimizer()
        o2 = get_resource_optimizer()
        assert o1 is not o2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_routing_package(self):
        from core.execution_pkg.routing import (
            ModelSpec,
            OptimizationDecision,
            OptimizationReport,
            ResourceOptimizer,
            UsageRecord,
            get_resource_optimizer,
            reset_resource_optimizer,
        )

        assert all(
            [
                ResourceOptimizer,
                ModelSpec,
                OptimizationDecision,
                OptimizationReport,
                UsageRecord,
                get_resource_optimizer,
                reset_resource_optimizer,
            ]
        )

    def test_from_module(self):
        from core.execution_pkg.routing.resource_optimizer import (
            ModelSpec,
            ResourceOptimizer,
        )

        assert all([ResourceOptimizer, ModelSpec, OptimizationDecision])
