"""
Tests for Model Router - V7 Sprint 8

Tests the intelligent model selection routing for:
- Claude: Opus (complex) vs Sonnet (simple)
- Gemini: 3-Pro (complex) vs Flash (simple)
"""

import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.execution_pkg.routing.model_router import ModelRouter, RoutingDecision, TaskType


class TestTaskType:
    """Test TaskType enum"""

    def test_opus_task_types_exist(self):
        """Verify Opus-routed task types exist"""
        assert TaskType.BRAINSTORM.value == "brainstorm"
        assert TaskType.REDTEAM.value == "redteam"
        assert TaskType.ARCHITECT.value == "architect"
        assert TaskType.EVOLUTION.value == "evolution"

    def test_sonnet_task_types_exist(self):
        """Verify Sonnet-routed task types exist"""
        assert TaskType.TOOL.value == "tool"
        assert TaskType.VALIDATION.value == "validation"
        assert TaskType.SIMPLE.value == "simple"
        assert TaskType.FORMAT.value == "format"

    def test_gemini_task_types_exist(self):
        """Verify Gemini-specific task types exist (V7 Sprint 6)"""
        assert TaskType.REASONING.value == "reasoning"
        assert TaskType.RESEARCH.value == "research"
        assert TaskType.ANALYSIS.value == "analysis"

    def test_default_task_type(self):
        """Test default task type"""
        assert TaskType.DEFAULT.value == "default"


class TestModelRouterInit:
    """Test ModelRouter initialization"""

    def test_default_init_no_config(self):
        """Test router initializes with defaults when no config"""
        router = ModelRouter()

        assert router.opus_model == "claude-opus-4-6"
        assert router.sonnet_model == "claude-sonnet-4-6"
        assert router.gemini_pro_model == "gemini-3.1-pro-preview"
        assert router.gemini_flash_model == "gemini-3-flash-preview"

    def test_default_task_mappings(self):
        """Test default task type mappings"""
        router = ModelRouter()

        # Opus tasks
        assert TaskType.BRAINSTORM in router.opus_tasks
        assert TaskType.REDTEAM in router.opus_tasks
        assert TaskType.ARCHITECT in router.opus_tasks
        assert TaskType.EVOLUTION in router.opus_tasks

        # Sonnet tasks
        assert TaskType.TOOL in router.sonnet_tasks
        assert TaskType.VALIDATION in router.sonnet_tasks
        assert TaskType.SIMPLE in router.sonnet_tasks
        assert TaskType.FORMAT in router.sonnet_tasks

    def test_gemini_task_mappings(self):
        """Test Gemini task type mappings (V7 Sprint 6)"""
        router = ModelRouter()

        # Pro tasks
        assert TaskType.REASONING in router.gemini_pro_tasks
        assert TaskType.RESEARCH in router.gemini_pro_tasks
        assert TaskType.ANALYSIS in router.gemini_pro_tasks
        assert TaskType.BRAINSTORM in router.gemini_pro_tasks

        # Flash tasks
        assert TaskType.SIMPLE in router.gemini_flash_tasks
        assert TaskType.FORMAT in router.gemini_flash_tasks
        assert TaskType.VALIDATION in router.gemini_flash_tasks


class TestClaudeModelSelection:
    """Test Claude model selection (Opus vs Sonnet)"""

    def test_brainstorm_routes_to_opus(self):
        """Brainstorming should use Opus for complex reasoning"""
        router = ModelRouter()
        model = router.select_claude_model(TaskType.BRAINSTORM)
        assert "opus" in model.lower()

    def test_redteam_routes_to_opus(self):
        """Red team testing should use Opus for security"""
        router = ModelRouter()
        model = router.select_claude_model(TaskType.REDTEAM)
        assert "opus" in model.lower()

    def test_evolution_routes_to_opus(self):
        """Evolution brainstorming should use Opus"""
        router = ModelRouter()
        model = router.select_claude_model(TaskType.EVOLUTION)
        assert "opus" in model.lower()

    def test_validation_routes_to_sonnet(self):
        """Validation should use Sonnet for speed"""
        router = ModelRouter()
        model = router.select_claude_model(TaskType.VALIDATION)
        assert "sonnet" in model.lower()

    def test_tool_routes_to_sonnet(self):
        """Tool execution should use Sonnet"""
        router = ModelRouter()
        model = router.select_claude_model(TaskType.TOOL)
        assert "sonnet" in model.lower()

    def test_default_routes_to_sonnet(self):
        """Default/unknown tasks should use Sonnet"""
        router = ModelRouter()
        model = router.select_claude_model(TaskType.DEFAULT)
        assert "sonnet" in model.lower()


class TestGeminiModelSelection:
    """Test Gemini model selection (V7 Sprint 6)"""

    def test_reasoning_routes_to_pro(self):
        """Complex reasoning should use Gemini 3 Pro"""
        router = ModelRouter()
        model = router.select_gemini_model(TaskType.REASONING)
        assert "pro" in model.lower()

    def test_research_routes_to_pro(self):
        """Research tasks should use Gemini 3 Pro"""
        router = ModelRouter()
        model = router.select_gemini_model(TaskType.RESEARCH)
        assert "pro" in model.lower()

    def test_simple_routes_to_flash(self):
        """Simple tasks should use Gemini Flash (V7.5+: Unified Model uses Pro for all)"""
        router = ModelRouter()
        model = router.select_gemini_model(TaskType.SIMPLE)
        # V7.5+: gemini_flash_model = gemini-3-pro-preview (Unified Model)
        assert "pro" in model.lower() or "flash" in model.lower()

    def test_format_routes_to_flash(self):
        """Formatting tasks should use Gemini Flash (V7.5+: Unified Model uses Pro for all)"""
        router = ModelRouter()
        model = router.select_gemini_model(TaskType.FORMAT)
        # V7.5+: gemini_flash_model = gemini-3-pro-preview (Unified Model)
        assert "pro" in model.lower() or "flash" in model.lower()


class TestRoutingDecision:
    """Test full routing decisions"""

    def test_route_returns_decision_object(self):
        """route() should return RoutingDecision"""
        router = ModelRouter()
        decision = router.route(TaskType.BRAINSTORM)

        assert isinstance(decision, RoutingDecision)
        assert decision.model_id is not None
        assert decision.task_type == TaskType.BRAINSTORM
        assert decision.reason is not None

    def test_opus_decision_is_opus_true(self):
        """Opus routing should have is_opus=True"""
        router = ModelRouter()
        decision = router.route(TaskType.BRAINSTORM)

        assert decision.is_opus is True

    def test_sonnet_decision_is_opus_false(self):
        """Sonnet routing should have is_opus=False"""
        router = ModelRouter()
        decision = router.route(TaskType.VALIDATION)

        assert decision.is_opus is False


class TestStringBasedSelection:
    """Test string-based model selection"""

    def test_claude_string_brainstorm(self):
        """String 'brainstorm' should route to Opus"""
        router = ModelRouter()
        model = router.select_claude_model_str("brainstorm")
        assert "opus" in model.lower()

    def test_claude_string_validation(self):
        """String 'validation' should route to Sonnet"""
        router = ModelRouter()
        model = router.select_claude_model_str("validation")
        assert "sonnet" in model.lower()

    def test_claude_string_invalid(self):
        """Invalid string should default to Sonnet"""
        router = ModelRouter()
        model = router.select_claude_model_str("invalid_task_xyz")
        assert "sonnet" in model.lower()

    def test_gemini_string_reasoning(self):
        """String 'reasoning' should route to Gemini Pro"""
        router = ModelRouter()
        model = router.select_gemini_model_str("reasoning")
        assert "pro" in model.lower()

    def test_gemini_string_simple(self):
        """String 'simple' should route to Gemini Flash (V7.5+: Unified Model uses Pro for all)"""
        router = ModelRouter()
        model = router.select_gemini_model_str("simple")
        # V7.5+: gemini_flash_model = gemini-3-pro-preview (Unified Model)
        assert "pro" in model.lower() or "flash" in model.lower()


class TestHelperMethods:
    """Test helper methods"""

    def test_should_use_opus(self):
        """Test should_use_opus helper"""
        router = ModelRouter()

        assert router.should_use_opus(TaskType.BRAINSTORM) is True
        assert router.should_use_opus(TaskType.EVOLUTION) is True
        assert router.should_use_opus(TaskType.VALIDATION) is False
        assert router.should_use_opus(TaskType.TOOL) is False

    def test_should_use_gemini_pro(self):
        """Test should_use_gemini_pro helper"""
        router = ModelRouter()

        assert router.should_use_gemini_pro(TaskType.REASONING) is True
        assert router.should_use_gemini_pro(TaskType.RESEARCH) is True
        assert router.should_use_gemini_pro(TaskType.SIMPLE) is False
        assert router.should_use_gemini_pro(TaskType.FORMAT) is False

    def test_get_gemini_model(self):
        """Test get_gemini_model returns default"""
        router = ModelRouter()
        model = router.get_gemini_model()
        assert "gemini" in model.lower()


class TestRoutingStats:
    """Test routing statistics"""

    def test_get_routing_stats_no_pool(self):
        """Test stats without agent pool"""
        router = ModelRouter()
        stats = router.get_routing_stats()

        assert "opus_model" in stats
        assert "sonnet_model" in stats
        assert "gemini_model" in stats
        assert "opus_tasks" in stats
        assert "sonnet_tasks" in stats
        assert stats["pool_available"] is False

    def test_stats_contain_task_lists(self):
        """Test stats contain task type lists"""
        router = ModelRouter()
        stats = router.get_routing_stats()

        assert "brainstorm" in stats["opus_tasks"]
        assert "validation" in stats["sonnet_tasks"]


# Pytest entry point
if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
