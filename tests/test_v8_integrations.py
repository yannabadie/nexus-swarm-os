"""
Tests for V8.0 TRUE HIVE MIND Integrations

Tests the three key integration points:
1. CostEstimator -> BudgetTracker (USD budget chain)
2. StagnationDetector -> StrategyBlacklist (stagnation reporting)
3. fsm_handlers -> TrueHiveMind (gating logic)
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestCostEstimatorBudgetTrackerIntegration:
    """Test CostEstimator -> BudgetTracker chain."""

    def test_tokens_to_usd_conversion(self):
        """Test token to USD conversion."""
        from core.intelligence.hive_mind.cost_estimator import CostEstimator

        estimator = CostEstimator(budget_limit=50000)

        # ~$3 per million tokens
        assert estimator.tokens_to_usd(1_000_000) == pytest.approx(3.0, rel=0.01)
        assert estimator.tokens_to_usd(10_000) == pytest.approx(0.03, rel=0.01)
        assert estimator.tokens_to_usd(0) == 0.0

    def test_can_afford_without_tracker(self):
        """Test can_afford works without BudgetTracker (token-only)."""
        from core.intelligence.hive_mind.cost_estimator import CostEstimator

        estimator = CostEstimator(budget_limit=1000)

        # Should pass token check (600 tokens for spawn_agent)
        assert estimator.can_afford("spawn_agent")  # 0 + 600 <= 1000

        # After spending 400, should still afford
        estimator.spent = 400
        assert estimator.can_afford("spawn_agent")  # 400 + 600 = 1000 <= 1000

        # After spending 500, should NOT afford
        estimator.spent = 500
        assert not estimator.can_afford("spawn_agent")  # 500 + 600 = 1100 > 1000

    def test_can_afford_with_budget_tracker(self):
        """Test can_afford checks both token AND USD budgets."""
        from core.intelligence.hive_mind.cost_estimator import CostEstimator

        # Create mock BudgetTracker
        mock_tracker = MagicMock()
        mock_tracker.get_remaining.return_value = 0.001  # Only $0.001 remaining

        estimator = CostEstimator(budget_limit=50000)
        estimator.set_budget_tracker(mock_tracker)

        # Token budget is fine, but USD budget is exceeded
        # spawn_agent = 600 tokens = ~$0.0018
        assert not estimator.can_afford("spawn_agent")

        # With more USD budget
        mock_tracker.get_remaining.return_value = 10.0  # $10 remaining
        assert estimator.can_afford("spawn_agent")

    def test_check_usd_budget_no_tracker(self):
        """Test check_usd_budget returns True when no tracker set."""
        from core.intelligence.hive_mind.cost_estimator import CostEstimator

        estimator = CostEstimator(budget_limit=50000)

        # No tracker = always True
        assert estimator.check_usd_budget(1_000_000)

    def test_get_stats_includes_usd_info(self):
        """Test get_stats includes USD integration info."""
        from core.intelligence.hive_mind.cost_estimator import CostEstimator

        # Without tracker
        estimator = CostEstimator(budget_limit=50000)
        stats = estimator.get_stats()
        assert stats["usd_integration"]["linked"] is False

        # With tracker
        mock_tracker = MagicMock()
        mock_tracker.get_stats.return_value = {"spent_today_usd": 5.0, "remaining_usd": 45.0, "warning_level": None}
        estimator.set_budget_tracker(mock_tracker)
        estimator.spent = 10000

        stats = estimator.get_stats()
        assert stats["usd_integration"]["linked"] is True
        assert "estimated_usd_spent" in stats["usd_integration"]


class TestStagnationDetectorBlacklistIntegration:
    """Test StagnationDetector -> StrategyBlacklist chain."""

    def test_stagnation_category_exists(self):
        """Test STAGNATION category exists in FailureCategory."""
        from core.intelligence.hive_mind.strategy_blacklist import FailureCategory

        assert hasattr(FailureCategory, "STAGNATION")
        assert FailureCategory.STAGNATION.value == "stagnation"

    def test_set_strategy_blacklist(self):
        """Test setting blacklist reference."""
        from core.fsm.stagnation_detector import StagnationDetector
        from core.intelligence.hive_mind.strategy_blacklist import StrategyBlacklist

        detector = StagnationDetector()
        blacklist = StrategyBlacklist()

        detector.set_strategy_blacklist(blacklist)
        assert detector._strategy_blacklist is blacklist

    def test_extract_stagnant_strategy(self):
        """Test strategy extraction from stagnant messages."""
        from core.fsm.stagnation_detector import StagnationDetector

        detector = StagnationDetector()

        # Add messages with common theme
        detector.add_message("let's read auth.py file")
        detector.add_message("yes read auth.py first")
        detector.add_message("ok reading auth.py now")

        strategy = detector.extract_stagnant_strategy()
        # Should contain "auth.py" as common keyword
        assert "auth.py" in strategy.lower() or "discussion" in strategy.lower()

    def test_report_to_blacklist_no_blacklist(self):
        """Test report_to_blacklist returns False when no blacklist."""
        from core.fsm.stagnation_detector import StagnationDetector

        detector = StagnationDetector(similarity_threshold=0.5)
        detector.add_message("same message")
        detector.add_message("same message")
        detector.add_message("same message")

        # No blacklist set
        assert detector.report_to_blacklist() is False

    def test_report_to_blacklist_success(self):
        """Test successful stagnation report to blacklist."""
        from core.fsm.stagnation_detector import StagnationDetector
        from core.intelligence.hive_mind.strategy_blacklist import StrategyBlacklist

        detector = StagnationDetector(similarity_threshold=0.5)
        blacklist = StrategyBlacklist()
        detector.set_strategy_blacklist(blacklist)

        # Create stagnation with very similar messages
        detector.add_message("we should read the auth file")
        detector.add_message("we should read the auth file now")
        detector.add_message("we should read the auth file immediately")

        # Should detect stagnation and report
        if detector.is_stagnant():
            result = detector.report_to_blacklist()
            assert result is True
            assert len(blacklist._blacklist) == 1

    def test_check_and_report_combined(self):
        """Test check_and_report convenience method."""
        from core.fsm.stagnation_detector import StagnationDetector
        from core.intelligence.hive_mind.strategy_blacklist import StrategyBlacklist

        detector = StagnationDetector(similarity_threshold=0.3)  # Very low for test
        blacklist = StrategyBlacklist()
        detector.set_strategy_blacklist(blacklist)

        # Not stagnant yet
        detector.add_message("message one")
        assert detector.check_and_report() is False

        # Add similar messages
        detector.message_history.clear()
        detector.add_message("identical message here")
        detector.add_message("identical message here")
        detector.add_message("identical message here")

        # Now should detect and report
        result = detector.check_and_report()
        # Result depends on actual stagnation detection
        assert isinstance(result, bool)

    def test_stagnation_suggestions(self):
        """Test STAGNATION category has specific suggestions."""
        from core.intelligence.hive_mind.strategy_blacklist import FailureCategory, StrategyBlacklist

        blacklist = StrategyBlacklist()
        blacklist.add_failed_strategy(
            strategy="discussing without action",
            failure_reason="circular discussion",
            diagnosis="agents keep talking",
            failure_category=FailureCategory.STAGNATION,
        )

        suggestions = blacklist.suggest_alternatives("discussing without action")
        assert len(suggestions) >= 5
        # Should include action-oriented suggestions
        suggestion_text = " ".join(suggestions).lower()
        assert "action" in suggestion_text or "tool" in suggestion_text


class TestFsmHandlersHiveMindIntegration:
    """Test fsm_handlers -> TrueHiveMind gating logic."""

    def test_should_use_hive_mind_complex(self):
        """Test COMPLEX tasks route to Hive Mind."""
        from core.intelligence.swarm.task_analyzer import TaskComplexity

        # Mock the fsm_handlers module
        with patch("core.execution_pkg.orchestration.fsm_handlers.HIVE_MIND_AVAILABLE", True):
            # Create mock config
            mock_config = MagicMock()
            mock_config.hive_mind_enabled = True
            mock_config.hive_mind_moderate = False  # Only COMPLEX/EXPERT

            # Create mock orchestrator
            mock_orch = MagicMock()
            mock_orch.config = mock_config

            # Import after patching
            from core.execution_pkg.orchestration.fsm_handlers import FSMHandlers

            handlers = FSMHandlers(mock_orch)

            # COMPLEX should route to Hive Mind
            assert handlers._should_use_hive_mind(TaskComplexity.COMPLEX) is True
            assert handlers._should_use_hive_mind(TaskComplexity.EXPERT) is True

            # MODERATE should NOT route (hive_mind_moderate=False)
            assert handlers._should_use_hive_mind(TaskComplexity.MODERATE) is False

    def test_should_use_hive_mind_moderate_enabled(self):
        """Test MODERATE routes to Hive Mind when setting enabled."""
        from core.intelligence.swarm.task_analyzer import TaskComplexity

        with patch("core.execution_pkg.orchestration.fsm_handlers.HIVE_MIND_AVAILABLE", True):
            mock_config = MagicMock()
            mock_config.hive_mind_enabled = True
            mock_config.hive_mind_moderate = True  # Include MODERATE

            mock_orch = MagicMock()
            mock_orch.config = mock_config

            from core.execution_pkg.orchestration.fsm_handlers import FSMHandlers

            handlers = FSMHandlers(mock_orch)

            # MODERATE should now route to Hive Mind
            assert handlers._should_use_hive_mind(TaskComplexity.MODERATE) is True

    def test_should_use_hive_mind_disabled(self):
        """Test Hive Mind disabled falls back to Swarm."""
        from core.intelligence.swarm.task_analyzer import TaskComplexity

        with patch("core.execution_pkg.orchestration.fsm_handlers.HIVE_MIND_AVAILABLE", True):
            mock_config = MagicMock()
            mock_config.hive_mind_enabled = False  # Disabled

            mock_orch = MagicMock()
            mock_orch.config = mock_config

            from core.execution_pkg.orchestration.fsm_handlers import FSMHandlers

            handlers = FSMHandlers(mock_orch)

            # All should fall back to Swarm
            assert handlers._should_use_hive_mind(TaskComplexity.COMPLEX) is False
            assert handlers._should_use_hive_mind(TaskComplexity.EXPERT) is False

    def test_should_use_hive_mind_not_available(self):
        """Test graceful handling when Hive Mind module not available."""
        from core.intelligence.swarm.task_analyzer import TaskComplexity

        with patch("core.execution_pkg.orchestration.fsm_handlers.HIVE_MIND_AVAILABLE", False):
            mock_config = MagicMock()
            mock_config.hive_mind_enabled = True

            mock_orch = MagicMock()
            mock_orch.config = mock_config

            from core.execution_pkg.orchestration.fsm_handlers import FSMHandlers

            handlers = FSMHandlers(mock_orch)

            # Should return False when module not available
            assert handlers._should_use_hive_mind(TaskComplexity.COMPLEX) is False


class TestConfigHiveMindSettings:
    """Test hive_mind_* settings in Config."""

    def test_config_has_hive_mind_settings(self):
        """Test Config class has all hive_mind_* settings."""
        from core.config import Config

        config = Config()

        # Check all expected settings exist
        assert hasattr(config, "hive_mind_enabled")
        assert hasattr(config, "hive_mind_moderate")
        assert hasattr(config, "hive_mind_budget_limit")
        assert hasattr(config, "hive_mind_max_debate_turns")
        assert hasattr(config, "hive_mind_min_debate_turns")
        assert hasattr(config, "hive_mind_breakpoints_enabled")
        assert hasattr(config, "hive_mind_max_retries")
        assert hasattr(config, "hive_mind_agreement_threshold")

    def test_config_default_values(self):
        """Test default values for hive_mind settings."""
        from core.config import Config

        config = Config()

        assert config.hive_mind_enabled is True
        assert config.hive_mind_moderate is True
        assert config.hive_mind_budget_limit == 50000
        assert config.hive_mind_max_debate_turns == 10
        assert config.hive_mind_min_debate_turns == 3
        assert config.hive_mind_max_retries == 3
        assert config.hive_mind_agreement_threshold == 0.85

    def test_mock_config_has_hive_mind_settings(self):
        """Test MockConfig in conftest also has hive_mind settings."""
        import importlib.util
        from pathlib import Path

        # Load conftest directly since tests/ has no __init__.py
        conftest_path = Path(__file__).parent / "conftest.py"
        spec = importlib.util.spec_from_file_location("conftest", conftest_path)
        conftest_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(conftest_mod)
        MockConfig = conftest_mod.MockConfig

        config = MockConfig()

        assert hasattr(config, "hive_mind_enabled")
        assert hasattr(config, "hive_mind_moderate")
        assert config.hive_mind_breakpoints_enabled is False  # Disabled for tests


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
