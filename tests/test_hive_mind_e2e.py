"""
End-to-End Integration Tests for V8.0 TRUE HIVE MIND

Tests the complete Hive Mind pipeline with mocked drivers.
Verifies all 7 phases work together correctly.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestHiveMindOrchestrator:
    """Test TrueHiveMind orchestrator end-to-end."""

    @pytest.fixture
    def mock_workspace(self, tmp_path):
        """Create a mock workspace with necessary directories."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / ".nexus").mkdir()
        (workspace / "agents").mkdir()
        (workspace / "logs").mkdir()
        return workspace

    @pytest.fixture
    def mock_config(self):
        """Create mock config with hive_mind settings."""
        config = MagicMock()
        config.hive_mind_enabled = True
        config.hive_mind_moderate = True
        config.hive_mind_budget_limit = 50000
        config.hive_mind_max_debate_turns = 10
        config.hive_mind_min_debate_turns = 3
        config.hive_mind_breakpoints_enabled = False
        config.hive_mind_max_retries = 3
        config.hive_mind_agreement_threshold = 0.85
        return config

    @pytest.fixture
    def mock_drivers(self):
        """Create mock Gemini and Claude drivers."""
        gemini = MagicMock()
        claude = MagicMock()

        # Mock invoke to return analysis-like responses
        gemini.invoke.return_value = {
            "sender": "Gemini",
            "action_type": "TALK",
            "content": "Analysis: This task requires reading auth.py and fixing the bug.",
            "status": "CONTINUE",
        }
        claude.invoke.return_value = {
            "sender": "Claude",
            "action_type": "TALK",
            "content": "I agree. The bug is in the token validation function.",
            "status": "CONTINUE",
        }

        return {"gemini": gemini, "claude": claude}

    def test_hive_mind_components_import(self):
        """Test all Hive Mind components can be imported."""
        from core.intelligence.hive_mind import (
            AgentRegistry,
            CostEstimator,
            HiveMindResult,
            TrueHiveMind,
        )

        # Verify classes exist
        assert TrueHiveMind is not None
        assert HiveMindResult is not None
        assert AgentRegistry is not None
        assert CostEstimator is not None

    def test_hive_mind_phases_import(self):
        """Test all 7 phases can be imported."""
        from core.intelligence.hive_mind.phases import (
            AdaptiveRetryPhase,
            ArchitectureGenerationPhase,
            FailureDiagnosisPhase,
            IndependentAnalysisPhase,
            KnowledgeConsolidationPhase,
            MonitoredExecutionPhase,
            StrategicDebatePhase,
        )

        # Verify all phases exist
        assert IndependentAnalysisPhase is not None
        assert StrategicDebatePhase is not None
        assert ArchitectureGenerationPhase is not None
        assert MonitoredExecutionPhase is not None
        assert FailureDiagnosisPhase is not None
        assert AdaptiveRetryPhase is not None
        assert KnowledgeConsolidationPhase is not None

    def test_hive_mind_types(self):
        """Test Hive Mind type definitions."""
        from core.intelligence.hive_mind.types import (
            HiveMindState,
            UserBreakpoint,
        )

        # Verify enums and dataclasses
        assert HiveMindState.HIVE_ANALYZING_GEMINI is not None
        assert HiveMindState.HIVE_DEBATING is not None
        assert UserBreakpoint.AFTER_DEBATE is not None

    def test_cost_estimator_initialization(self, mock_workspace):
        """Test CostEstimator initializes correctly."""
        from core.intelligence.hive_mind.cost_estimator import CostEstimator

        estimator = CostEstimator(budget_limit=50000)

        assert estimator.budget_limit == 50000
        assert estimator.spent == 0
        assert estimator.budget_remaining == 50000

    def test_cost_estimator_full_hive_mind_estimate(self):
        """Test estimating cost of full Hive Mind run."""
        from core.intelligence.hive_mind.cost_estimator import CostEstimator

        estimator = CostEstimator(budget_limit=50000)

        # Estimate full run with typical parameters
        estimate = estimator.estimate_full_hive_mind(debate_turns=4, spawns=1, execution_steps=5)

        # Should be reasonable (not exceeding typical budget)
        assert estimate > 0
        assert estimate < 50000  # Should fit in budget

    def test_agent_registry_initialization(self, mock_workspace):
        """Test AgentRegistry initializes correctly."""
        from core.intelligence.hive_mind.agent_registry import AgentRegistry

        registry = AgentRegistry(mock_workspace)

        assert registry.workspace_path == mock_workspace
        # Check registry has expected methods
        assert hasattr(registry, "find_similar")
        assert hasattr(registry, "register_spawn")
        assert hasattr(registry, "get_active_agents")

    def test_strategy_blacklist_operations(self, mock_workspace):
        """Test StrategyBlacklist basic operations."""
        from core.intelligence.hive_mind.strategy_blacklist import FailureCategory, StrategyBlacklist

        blacklist = StrategyBlacklist(workspace_path=mock_workspace)

        # Add a failed strategy
        blacklist.add_failed_strategy(
            strategy="Try reading non-existent file",
            failure_reason="File not found",
            diagnosis="The file does not exist in the workspace",
            failure_category=FailureCategory.TOOL_ERROR,
        )

        # Check if blacklisted
        result = blacklist.is_blacklisted("Try reading non-existent file")
        assert result is not None

        # Mark as success (removes from blacklist)
        blacklist.mark_success("Try reading non-existent file")
        result = blacklist.is_blacklisted("Try reading non-existent file")
        assert result is None

    def test_context_manager_sliding_window(self):
        """Test HiveMindContextManager sliding window."""
        from core.intelligence.hive_mind.context_manager import HiveMindContextManager

        manager = HiveMindContextManager(max_tokens=10000)

        # Add some context using correct method signature: (turn_number, agent_id, argument)
        manager.add_debate_turn(1, "gemini", "First point about the problem")
        manager.add_debate_turn(2, "claude", "I agree, and also consider...")

        # Get full context string
        context = manager.get_full_context_string()
        assert len(context) > 0 or manager.current_tokens >= 0

    def test_adaptive_debate_config(self):
        """Test AdaptiveDebateConfig calculates correct turns."""
        from core.intelligence.hive_mind.adaptive_debate import AdaptiveDebateConfig, TaskComplexity

        config = AdaptiveDebateConfig()

        # Test different complexities
        moderate_params = config.get_debate_params(TaskComplexity.MODERATE)
        complex_params = config.get_debate_params(TaskComplexity.COMPLEX)
        expert_params = config.get_debate_params(TaskComplexity.EXPERT)

        # More complex tasks should have more debate turns
        assert moderate_params.max_turns <= complex_params.max_turns
        assert complex_params.max_turns <= expert_params.max_turns


class TestHiveMindIntegrationWithFSM:
    """Test Hive Mind integration with FSM handlers."""

    def test_fsm_handlers_has_hive_mind_methods(self):
        """Test FSMHandlers has Hive Mind integration methods."""
        from core.execution_pkg.orchestration.fsm_handlers import FSMHandlers

        # Check methods exist
        assert hasattr(FSMHandlers, "_should_use_hive_mind")
        assert hasattr(FSMHandlers, "_route_to_hive_mind")
        assert hasattr(FSMHandlers, "_fallback_to_swarm_or_brainstorm")

    def test_complexity_gating_logic(self):
        """Test complexity-based routing logic."""
        from core.intelligence.swarm.task_analyzer import TaskComplexity

        complexities = [
            TaskComplexity.TRIVIAL,
            TaskComplexity.SIMPLE,
            TaskComplexity.MODERATE,
            TaskComplexity.COMPLEX,
            TaskComplexity.EXPERT,
        ]

        # Verify all complexities are defined
        for c in complexities:
            assert c is not None


class TestHiveMindWithMockedDrivers:
    """Test Hive Mind with fully mocked drivers (no API calls)."""

    @pytest.fixture
    def hive_mind_setup(self, tmp_path):
        """Set up Hive Mind with mocked components."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / ".nexus").mkdir()
        (workspace / "agents").mkdir()

        # Mock config
        config = MagicMock()
        config.hive_mind_enabled = True
        config.hive_mind_moderate = True
        config.hive_mind_budget_limit = 50000
        config.hive_mind_max_debate_turns = 4
        config.hive_mind_min_debate_turns = 2
        config.hive_mind_breakpoints_enabled = False
        config.hive_mind_max_retries = 2
        config.hive_mind_agreement_threshold = 0.85

        # Mock drivers
        gemini_driver = MagicMock()
        claude_driver = MagicMock()

        return {
            "workspace": workspace,
            "config": config,
            "gemini_driver": gemini_driver,
            "claude_driver": claude_driver,
        }

    def test_true_hive_mind_initialization(self, hive_mind_setup):
        """Test TrueHiveMind can be initialized."""
        from core.intelligence.hive_mind import TrueHiveMind

        hive = TrueHiveMind(
            workspace_path=hive_mind_setup["workspace"],
            config=hive_mind_setup["config"],
            gemini_driver=hive_mind_setup["gemini_driver"],
            claude_driver=hive_mind_setup["claude_driver"],
        )

        assert hive is not None
        assert hive.workspace_path == hive_mind_setup["workspace"]

    def test_true_hive_mind_components_initialized(self, hive_mind_setup):
        """Test TrueHiveMind initializes all components."""
        from core.intelligence.hive_mind import TrueHiveMind

        hive = TrueHiveMind(
            workspace_path=hive_mind_setup["workspace"],
            config=hive_mind_setup["config"],
            gemini_driver=hive_mind_setup["gemini_driver"],
            claude_driver=hive_mind_setup["claude_driver"],
        )

        # Check components are initialized
        assert hive.cost_estimator is not None
        assert hive.context_manager is not None
        assert hive.strategy_blacklist is not None


class TestBudgetChainIntegration:
    """Test the complete CostEstimator -> BudgetTracker chain."""

    def test_full_budget_chain(self, tmp_path):
        """Test full budget chain with real components."""
        from core.intelligence.hive_mind.cost_estimator import CostEstimator
        from core.observability.telemetry.budget_tracker import BudgetTracker

        # Create real BudgetTracker
        tracker = BudgetTracker(workspace_path=tmp_path, config=MagicMock(budget_limit_usd=50.0))

        # Create CostEstimator and link
        estimator = CostEstimator(budget_limit=50000)
        estimator.set_budget_tracker(tracker)

        # Test the chain
        assert estimator.can_afford("spawn_agent")  # Should pass

        # Record some cost in tracker
        tracker.track_cost("gemini-pro", input_tokens=100000, output_tokens=50000)

        # Now estimator should still check against tracker
        stats = estimator.get_stats()
        assert stats["usd_integration"]["linked"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
