"""
Tests for V12.4 Policy-Driven Model Router with SLM Triage.

Validates:
- RoutingPolicy enum (COST_OPTIMIZED, QUALITY_OPTIMIZED, BALANCED)
- ModelTier classification for all task types
- SLM triage: Haiku for light tasks under COST_OPTIMIZED
- Quality policy: always Opus/Pro
- Balanced policy: original V7 behavior preserved
- Tier-direct model selection
- Policy in RoutingDecision
- Stats include new fields
"""

import pytest

from core.execution_pkg.routing.model_router import (
    ModelRouter,
    ModelTier,
    RoutingPolicy,
    TaskType,
)

# =============================================================================
# RoutingPolicy Tests
# =============================================================================


class TestRoutingPolicy:
    """Test routing policy enum."""

    def test_policy_values(self):
        assert RoutingPolicy.COST_OPTIMIZED.value == "cost_optimized"
        assert RoutingPolicy.QUALITY_OPTIMIZED.value == "quality_optimized"
        assert RoutingPolicy.BALANCED.value == "balanced"

    def test_default_policy_is_balanced(self):
        router = ModelRouter()
        assert router.policy == RoutingPolicy.BALANCED


class TestModelTier:
    """Test model tier classification."""

    def test_tier_values(self):
        assert ModelTier.LIGHT.value == "light"
        assert ModelTier.MEDIUM.value == "medium"
        assert ModelTier.HEAVY.value == "heavy"

    def test_heavy_tasks(self):
        router = ModelRouter()
        assert router.get_task_tier(TaskType.BRAINSTORM) == ModelTier.HEAVY
        assert router.get_task_tier(TaskType.REDTEAM) == ModelTier.HEAVY
        assert router.get_task_tier(TaskType.ARCHITECT) == ModelTier.HEAVY
        assert router.get_task_tier(TaskType.EVOLUTION) == ModelTier.HEAVY

    def test_medium_tasks(self):
        router = ModelRouter()
        assert router.get_task_tier(TaskType.REASONING) == ModelTier.MEDIUM
        assert router.get_task_tier(TaskType.RESEARCH) == ModelTier.MEDIUM
        assert router.get_task_tier(TaskType.ANALYSIS) == ModelTier.MEDIUM
        assert router.get_task_tier(TaskType.DEFAULT) == ModelTier.MEDIUM

    def test_light_tasks(self):
        router = ModelRouter()
        assert router.get_task_tier(TaskType.TOOL) == ModelTier.LIGHT
        assert router.get_task_tier(TaskType.VALIDATION) == ModelTier.LIGHT
        assert router.get_task_tier(TaskType.SIMPLE) == ModelTier.LIGHT
        assert router.get_task_tier(TaskType.FORMAT) == ModelTier.LIGHT


# =============================================================================
# BALANCED Policy (V7 compatibility)
# =============================================================================


class TestBalancedPolicy:
    """Test that BALANCED policy preserves V7 behavior."""

    @pytest.fixture
    def router(self):
        return ModelRouter(policy=RoutingPolicy.BALANCED)

    def test_brainstorm_routes_to_opus(self, router):
        assert router.select_claude_model(TaskType.BRAINSTORM) == router.opus_model

    def test_tool_routes_to_sonnet(self, router):
        """BALANCED: light tasks go to Sonnet (not Haiku)."""
        assert router.select_claude_model(TaskType.TOOL) == router.sonnet_model

    def test_simple_routes_to_sonnet(self, router):
        """BALANCED: simple goes to Sonnet (V7 behavior)."""
        assert router.select_claude_model(TaskType.SIMPLE) == router.sonnet_model

    def test_gemini_complex_to_pro(self, router):
        assert router.select_gemini_model(TaskType.REASONING) == router.gemini_pro_model

    def test_gemini_simple_to_flash(self, router):
        assert router.select_gemini_model(TaskType.SIMPLE) == router.gemini_flash_model


# =============================================================================
# COST_OPTIMIZED Policy (SLM Triage)
# =============================================================================


class TestCostOptimizedPolicy:
    """Test cost-optimized routing with SLM triage."""

    @pytest.fixture
    def router(self):
        return ModelRouter(policy=RoutingPolicy.COST_OPTIMIZED)

    def test_light_tasks_to_haiku(self, router):
        """COST: light tasks should route to Haiku."""
        assert router.select_claude_model(TaskType.SIMPLE) == router.haiku_model
        assert router.select_claude_model(TaskType.FORMAT) == router.haiku_model
        assert router.select_claude_model(TaskType.TOOL) == router.haiku_model
        assert router.select_claude_model(TaskType.VALIDATION) == router.haiku_model

    def test_medium_tasks_to_sonnet(self, router):
        """COST: medium tasks should route to Sonnet."""
        assert router.select_claude_model(TaskType.REASONING) == router.sonnet_model
        assert router.select_claude_model(TaskType.RESEARCH) == router.sonnet_model
        assert router.select_claude_model(TaskType.ANALYSIS) == router.sonnet_model

    def test_heavy_tasks_to_opus(self, router):
        """COST: heavy tasks still route to Opus."""
        assert router.select_claude_model(TaskType.BRAINSTORM) == router.opus_model
        assert router.select_claude_model(TaskType.EVOLUTION) == router.opus_model

    def test_gemini_light_to_flash(self, router):
        """COST: Gemini light tasks to Flash."""
        assert router.select_gemini_model(TaskType.SIMPLE) == router.gemini_flash_model
        assert router.select_gemini_model(TaskType.TOOL) == router.gemini_flash_model

    def test_gemini_medium_to_flash(self, router):
        """COST: Gemini medium tasks also to Flash."""
        assert router.select_gemini_model(TaskType.REASONING) == router.gemini_flash_model

    def test_gemini_heavy_to_pro(self, router):
        """COST: Gemini heavy tasks still route to Pro."""
        assert router.select_gemini_model(TaskType.BRAINSTORM) == router.gemini_pro_model


# =============================================================================
# QUALITY_OPTIMIZED Policy
# =============================================================================


class TestQualityOptimizedPolicy:
    """Test quality-optimized routing (always heaviest model)."""

    @pytest.fixture
    def router(self):
        return ModelRouter(policy=RoutingPolicy.QUALITY_OPTIMIZED)

    def test_all_claude_to_opus(self, router):
        """QUALITY: every task type should route to Opus."""
        for task_type in TaskType:
            model = router.select_claude_model(task_type)
            assert model == router.opus_model, f"{task_type} should route to Opus"

    def test_all_gemini_to_pro(self, router):
        """QUALITY: every task type should route to Pro."""
        for task_type in TaskType:
            model = router.select_gemini_model(task_type)
            assert model == router.gemini_pro_model, f"{task_type} should route to Pro"


# =============================================================================
# Direct Tier Selection
# =============================================================================


class TestTierSelection:
    """Test direct tier-based model selection."""

    @pytest.fixture
    def router(self):
        return ModelRouter()

    def test_claude_light_tier(self, router):
        assert router.select_claude_by_tier(ModelTier.LIGHT) == router.haiku_model

    def test_claude_medium_tier(self, router):
        assert router.select_claude_by_tier(ModelTier.MEDIUM) == router.sonnet_model

    def test_claude_heavy_tier(self, router):
        assert router.select_claude_by_tier(ModelTier.HEAVY) == router.opus_model

    def test_gemini_light_tier(self, router):
        assert router.select_gemini_by_tier(ModelTier.LIGHT) == router.gemini_flash_model

    def test_gemini_medium_tier(self, router):
        assert router.select_gemini_by_tier(ModelTier.MEDIUM) == router.gemini_pro_model

    def test_gemini_heavy_tier(self, router):
        assert router.select_gemini_by_tier(ModelTier.HEAVY) == router.gemini_pro_model


# =============================================================================
# RoutingDecision Enrichment
# =============================================================================


class TestRoutingDecision:
    """Test enriched routing decisions."""

    def test_decision_includes_tier(self):
        router = ModelRouter(policy=RoutingPolicy.COST_OPTIMIZED)
        decision = router.route(TaskType.SIMPLE)
        assert decision.tier == ModelTier.LIGHT

    def test_decision_includes_policy(self):
        router = ModelRouter(policy=RoutingPolicy.QUALITY_OPTIMIZED)
        decision = router.route(TaskType.SIMPLE)
        assert decision.policy == RoutingPolicy.QUALITY_OPTIMIZED

    def test_decision_reason_includes_policy(self):
        router = ModelRouter(policy=RoutingPolicy.COST_OPTIMIZED)
        decision = router.route(TaskType.FORMAT)
        assert "cost_optimized" in decision.reason

    def test_cost_decision_for_light_task(self):
        router = ModelRouter(policy=RoutingPolicy.COST_OPTIMIZED)
        decision = router.route(TaskType.SIMPLE)
        assert decision.model_id == router.haiku_model
        assert "light" in decision.reason

    def test_quality_decision_for_light_task(self):
        router = ModelRouter(policy=RoutingPolicy.QUALITY_OPTIMIZED)
        decision = router.route(TaskType.SIMPLE)
        assert decision.model_id == router.opus_model
        assert decision.is_opus is True


# =============================================================================
# Stats
# =============================================================================


class TestRoutingStats:
    """Test routing statistics output."""

    def test_stats_include_policy(self):
        router = ModelRouter(policy=RoutingPolicy.COST_OPTIMIZED)
        stats = router.get_routing_stats()
        assert stats["policy"] == "cost_optimized"

    def test_stats_include_haiku(self):
        router = ModelRouter()
        stats = router.get_routing_stats()
        assert "haiku_model" in stats

    def test_stats_include_task_tiers(self):
        router = ModelRouter()
        stats = router.get_routing_stats()
        assert "task_tiers" in stats
        assert stats["task_tiers"]["simple"] == "light"
        assert stats["task_tiers"]["brainstorm"] == "heavy"

    def test_stats_include_flash_model(self):
        router = ModelRouter()
        stats = router.get_routing_stats()
        assert "gemini_flash_model" in stats


# =============================================================================
# Module Exports
# =============================================================================


class TestModuleExports:
    """Test that new types are exported from routing module."""

    def test_routing_policy_importable(self):
        from core.execution_pkg.routing import RoutingPolicy

        assert RoutingPolicy.BALANCED is not None

    def test_model_tier_importable(self):
        from core.execution_pkg.routing import ModelTier

        assert ModelTier.LIGHT is not None

    def test_routing_decision_importable(self):
        from core.execution_pkg.routing import RoutingDecision

        assert RoutingDecision is not None
