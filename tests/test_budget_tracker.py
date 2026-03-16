"""
Unit tests for BudgetTracker - Phase 14d

Tests cover:
- Cost calculation per model
- Token estimation
- Budget enforcement (limits, warnings)
- Daily reset logic
- Persistence (JSON state)
- Integration with TelemetryCollector

Author: Claude (NEXUS V7.6)
Date: 2025-12-05
"""

# Add parent to path for imports
import sys
import tempfile
from datetime import date
from pathlib import Path
from unittest import main

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.observability.telemetry.budget_tracker import (
    PRICING,
    BudgetExceededError,
    BudgetState,
    BudgetTracker,
    get_budget_tracker,
    reset_budget_tracker,
)

# =============================================================================
# FIXTURES
# =============================================================================


class MockConfig:
    """Mock config for testing."""

    def __init__(self, budget_limit: float = 50.0):
        self.budget_limit_usd = budget_limit
        self.workspace_path = Path(tempfile.mkdtemp())


@pytest.fixture
def temp_workspace(tmp_path):
    """Create temporary workspace."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    nexus_dir = workspace / ".nexus"
    nexus_dir.mkdir()
    return workspace


@pytest.fixture
def mock_config(temp_workspace):
    """Provide mock config with temp workspace."""
    config = MockConfig()
    config.workspace_path = temp_workspace
    return config


@pytest.fixture
def budget_tracker(temp_workspace):
    """Create BudgetTracker with temp workspace."""
    budget_file = temp_workspace / ".nexus" / "budget.json"
    return BudgetTracker(
        config=None,
        workspace_path=temp_workspace,
        budget_file=budget_file,
    )


# =============================================================================
# TEST: Pricing Constants
# =============================================================================


class TestPricingConstants:
    """Tests for pricing data."""

    def test_claude_opus_pricing_exists(self):
        """Test Claude Opus pricing is defined (Feb 2026 official rates)."""
        assert "claude-opus-4-6-20250116" in PRICING
        pricing = PRICING["claude-opus-4-6-20250116"]
        assert pricing["input"] == 5.00  # CORRECTED from 15.00
        assert pricing["output"] == 25.00  # CORRECTED from 75.00

    def test_claude_sonnet_pricing_exists(self):
        """Test Claude Sonnet pricing is defined (Feb 2026 official rates)."""
        assert "claude-sonnet-4-5-20250929" in PRICING
        pricing = PRICING["claude-sonnet-4-5-20250929"]
        assert pricing["input"] == 3.00  # $3/MTok (platform.claude.com)
        assert pricing["output"] == 15.00  # $15/MTok (platform.claude.com)

    def test_gemini_pro_pricing_exists(self):
        """Test Gemini Pro pricing is defined (Feb 2026 official rates)."""
        assert "gemini-3-pro-preview" in PRICING
        pricing = PRICING["gemini-3-pro-preview"]
        assert pricing["input"] == 2.00  # CORRECTED from 1.25
        assert pricing["output"] == 12.00  # CORRECTED from 5.00

    def test_gemini_flash_pricing_exists(self):
        """Test Gemini Flash pricing is defined (Feb 2026 official rates)."""
        assert "gemini-3-flash" in PRICING
        pricing = PRICING["gemini-3-flash"]
        assert pricing["input"] == 0.50  # CORRECTED from 0.075
        assert pricing["output"] == 3.00  # CORRECTED from 0.30

    def test_default_pricing_exists(self):
        """Test default fallback pricing is defined."""
        assert "default" in PRICING


# =============================================================================
# TEST: Token Estimation
# =============================================================================


class TestTokenEstimation:
    """Tests for token estimation from text."""

    def test_estimate_empty_string(self, budget_tracker):
        """Test empty string returns 0 tokens."""
        assert budget_tracker.estimate_tokens("") == 0

    def test_estimate_short_text(self, budget_tracker):
        """Test short text estimation."""
        # 16 chars -> ~4 tokens
        text = "Hello, world!!!"
        tokens = budget_tracker.estimate_tokens(text)
        assert tokens >= 1
        assert tokens <= 10

    def test_estimate_long_text(self, budget_tracker):
        """Test longer text estimation."""
        # 400 chars -> ~100 tokens
        text = "x" * 400
        tokens = budget_tracker.estimate_tokens(text)
        assert tokens >= 50
        assert tokens <= 150

    def test_estimate_none_input(self, budget_tracker):
        """Test None input handling."""
        # Should not crash
        assert budget_tracker.estimate_tokens(None) == 0


# =============================================================================
# TEST: Cost Calculation
# =============================================================================


class TestCostCalculation:
    """Tests for cost calculation per model."""

    def test_calculate_opus_cost(self, budget_tracker):
        """Test Claude Opus cost calculation (Feb 2026 rates)."""
        # 1M input + 100k output
        cost = budget_tracker.calculate_cost(
            model="claude-opus-4-6-20250116",
            input_tokens=1_000_000,
            output_tokens=100_000,
        )
        # $5 for input + $2.50 for output = $7.50 (CORRECTED from $22.50)
        assert abs(cost - 7.50) < 0.01

    def test_calculate_sonnet_cost(self, budget_tracker):
        """Test Claude Sonnet cost calculation (Feb 2026 rates)."""
        cost = budget_tracker.calculate_cost(
            model="claude-sonnet-4-5-20250929",
            input_tokens=1_000_000,
            output_tokens=100_000,
        )
        # $3 for input + $1.50 for output = $4.50 (platform.claude.com)
        assert abs(cost - 4.50) < 0.01

    def test_calculate_gemini_pro_cost(self, budget_tracker):
        """Test Gemini Pro cost calculation (Feb 2026 rates)."""
        cost = budget_tracker.calculate_cost(
            model="gemini-3-pro-preview",
            input_tokens=1_000_000,
            output_tokens=100_000,
        )
        # $2 for input + $1.20 for output = $3.20 (CORRECTED from $1.75)
        assert abs(cost - 3.20) < 0.01

    def test_calculate_zero_tokens(self, budget_tracker):
        """Test zero tokens returns zero cost."""
        cost = budget_tracker.calculate_cost("claude-opus", 0, 0)
        assert cost == 0.0

    def test_unknown_model_uses_default(self, budget_tracker):
        """Test unknown model falls back to default pricing."""
        cost = budget_tracker.calculate_cost(
            model="unknown-model-xyz",
            input_tokens=1_000_000,
            output_tokens=100_000,
        )
        # Default: $5 input + $2 output = $7
        assert cost > 0


# =============================================================================
# TEST: Cost Tracking
# =============================================================================


class TestCostTracking:
    """Tests for track_cost method."""

    def test_track_cost_updates_state(self, budget_tracker):
        """Test that track_cost updates spent amount."""
        initial_spent = budget_tracker._state.spent_today_usd

        budget_tracker.track_cost(
            model="gemini-3-pro-preview",
            input_tokens=100_000,
            output_tokens=10_000,
        )

        assert budget_tracker._state.spent_today_usd > initial_spent
        assert budget_tracker._state.api_calls_today == 1

    def test_track_cost_returns_cost(self, budget_tracker):
        """Test that track_cost returns the calculated cost (Feb 2026 rates)."""
        cost = budget_tracker.track_cost(
            model="gemini-3-pro-preview",
            input_tokens=1_000_000,
            output_tokens=0,
        )
        # $2.00 for 1M input tokens (CORRECTED from $1.25)
        assert abs(cost - 2.00) < 0.01

    def test_track_cost_with_text_estimation(self, budget_tracker):
        """Test cost tracking with text estimation."""
        cost = budget_tracker.track_cost(
            model="claude-opus",
            input_text="Hello world " * 100,  # ~1200 chars = ~300 tokens
            output_text="Response " * 50,  # ~450 chars = ~112 tokens
        )

        # Should have a non-zero cost
        assert cost > 0

    def test_track_cost_cumulative(self, budget_tracker):
        """Test that costs accumulate correctly."""
        budget_tracker.track_cost("gemini-pro", 100_000, 10_000)
        budget_tracker.track_cost("gemini-pro", 100_000, 10_000)
        budget_tracker.track_cost("gemini-pro", 100_000, 10_000)

        assert budget_tracker._state.api_calls_today == 3
        # Each call: ~$0.175 -> total ~$0.525
        assert budget_tracker._state.spent_today_usd > 0.4


# =============================================================================
# TEST: Budget Enforcement
# =============================================================================


class TestBudgetEnforcement:
    """Tests for budget limit enforcement."""

    def test_check_budget_under_limit(self, budget_tracker):
        """Test check_budget returns True when under limit."""
        budget_tracker.limit_usd = 100.0
        budget_tracker._state.spent_today_usd = 50.0

        assert budget_tracker.check_budget() is True

    def test_check_budget_exceeded(self, budget_tracker):
        """Test check_budget raises exception when exceeded."""
        budget_tracker.limit_usd = 10.0
        budget_tracker._state.spent_today_usd = 15.0

        with pytest.raises(BudgetExceededError) as exc_info:
            budget_tracker.check_budget()

        assert exc_info.value.spent == 15.0
        assert exc_info.value.limit == 10.0

    def test_check_budget_at_exactly_limit(self, budget_tracker):
        """Test check_budget at exactly 100% limit."""
        budget_tracker.limit_usd = 50.0
        budget_tracker._state.spent_today_usd = 50.0

        with pytest.raises(BudgetExceededError):
            budget_tracker.check_budget()

    def test_get_remaining(self, budget_tracker):
        """Test get_remaining calculation."""
        budget_tracker.limit_usd = 100.0
        budget_tracker._state.spent_today_usd = 35.0

        assert budget_tracker.get_remaining() == 65.0

    def test_get_remaining_negative_handled(self, budget_tracker):
        """Test get_remaining doesn't return negative."""
        budget_tracker.limit_usd = 10.0
        budget_tracker._state.spent_today_usd = 20.0

        assert budget_tracker.get_remaining() == 0.0


# =============================================================================
# TEST: Warning Levels
# =============================================================================


class TestWarningLevels:
    """Tests for budget warning levels."""

    def test_no_warning_under_80_percent(self, budget_tracker):
        """Test no warning under 80% usage."""
        budget_tracker.limit_usd = 100.0
        budget_tracker._state.spent_today_usd = 70.0

        assert budget_tracker.get_warning_level() is None

    def test_warning_at_80_percent(self, budget_tracker):
        """Test warning level at 80%."""
        budget_tracker.limit_usd = 100.0
        budget_tracker._state.spent_today_usd = 80.0

        assert budget_tracker.get_warning_level() == "warning"

    def test_critical_at_90_percent(self, budget_tracker):
        """Test critical warning at 90%."""
        budget_tracker.limit_usd = 100.0
        budget_tracker._state.spent_today_usd = 90.0

        assert budget_tracker.get_warning_level() == "critical"

    def test_critical_at_95_percent(self, budget_tracker):
        """Test critical warning at 95%."""
        budget_tracker.limit_usd = 100.0
        budget_tracker._state.spent_today_usd = 95.0

        assert budget_tracker.get_warning_level() == "critical"


# =============================================================================
# TEST: Daily Reset
# =============================================================================


class TestDailyReset:
    """Tests for daily reset logic."""

    def test_reset_on_new_day(self, budget_tracker):
        """Test that counters reset on new day."""
        # Set state to yesterday
        budget_tracker._state.spent_today_usd = 100.0
        budget_tracker._state.api_calls_today = 50
        budget_tracker._state.reset_date = "2020-01-01"

        # Check should trigger reset
        budget_tracker._check_daily_reset()

        assert budget_tracker._state.spent_today_usd == 0.0
        assert budget_tracker._state.api_calls_today == 0
        assert budget_tracker._state.reset_date == date.today().isoformat()

    def test_no_reset_same_day(self, budget_tracker):
        """Test no reset on same day."""
        today = date.today().isoformat()
        budget_tracker._state.spent_today_usd = 25.0
        budget_tracker._state.reset_date = today

        budget_tracker._check_daily_reset()

        assert budget_tracker._state.spent_today_usd == 25.0

    def test_manual_reset(self, budget_tracker):
        """Test manual reset_daily method."""
        budget_tracker._state.spent_today_usd = 100.0
        budget_tracker._state.api_calls_today = 50

        budget_tracker.reset_daily()

        assert budget_tracker._state.spent_today_usd == 0.0
        assert budget_tracker._state.api_calls_today == 0


# =============================================================================
# TEST: Persistence
# =============================================================================


class TestPersistence:
    """Tests for JSON state persistence."""

    def test_save_creates_file(self, budget_tracker):
        """Test that save creates JSON file."""
        budget_tracker.track_cost("gemini-pro", 100_000, 10_000)

        assert budget_tracker.budget_file.exists()

    def test_save_load_roundtrip(self, temp_workspace):
        """Test that state survives save/load cycle."""
        budget_file = temp_workspace / ".nexus" / "budget.json"

        # Create tracker and add costs
        tracker1 = BudgetTracker(
            config=None,
            workspace_path=temp_workspace,
            budget_file=budget_file,
        )
        tracker1.track_cost("gemini-pro", 500_000, 50_000)
        original_spent = tracker1._state.spent_today_usd
        original_calls = tracker1._state.api_calls_today

        # Create new tracker loading same file
        tracker2 = BudgetTracker(
            config=None,
            workspace_path=temp_workspace,
            budget_file=budget_file,
        )

        assert abs(tracker2._state.spent_today_usd - original_spent) < 0.001
        assert tracker2._state.api_calls_today == original_calls

    def test_corrupted_file_handled(self, temp_workspace):
        """Test that corrupted JSON file is handled gracefully."""
        budget_file = temp_workspace / ".nexus" / "budget.json"
        budget_file.write_text("{ invalid json }", encoding="utf-8")

        # Should not raise, should start fresh
        tracker = BudgetTracker(
            config=None,
            workspace_path=temp_workspace,
            budget_file=budget_file,
        )

        assert tracker._state.spent_today_usd == 0.0


# =============================================================================
# TEST: Stats
# =============================================================================


class TestStats:
    """Tests for get_stats method."""

    def test_get_stats_returns_dict(self, budget_tracker):
        """Test that get_stats returns comprehensive dict."""
        budget_tracker.limit_usd = 50.0
        budget_tracker.track_cost("gemini-pro", 100_000, 10_000)

        stats = budget_tracker.get_stats()

        assert "spent_today_usd" in stats
        assert "limit_usd" in stats
        assert "remaining_usd" in stats
        assert "percentage_used" in stats
        assert "api_calls_today" in stats
        assert "warning_level" in stats

    def test_get_stats_percentage_calculation(self, budget_tracker):
        """Test percentage calculation in stats."""
        budget_tracker.limit_usd = 100.0
        budget_tracker._state.spent_today_usd = 25.0

        stats = budget_tracker.get_stats()

        assert stats["percentage_used"] == 25.0


# =============================================================================
# TEST: Add Credit
# =============================================================================


class TestAddCredit:
    """Tests for emergency credit addition."""

    def test_add_credit_increases_limit(self, budget_tracker):
        """Test that add_credit increases the limit."""
        original_limit = budget_tracker.limit_usd

        budget_tracker.add_credit(10.0)

        assert budget_tracker.limit_usd == original_limit + 10.0


# =============================================================================
# TEST: Model Pricing Resolution
# =============================================================================


class TestModelPricingResolution:
    """Tests for get_model_pricing method."""

    def test_exact_match(self, budget_tracker):
        """Test exact model name match (Feb 2026 rates)."""
        pricing = budget_tracker.get_model_pricing("claude-opus-4-6-20250116")
        assert pricing["input"] == 5.00  # CORRECTED from 15.00

    def test_alias_match(self, budget_tracker):
        """Test alias model name match (Feb 2026 rates)."""
        pricing = budget_tracker.get_model_pricing("claude-opus")
        assert pricing["input"] == 5.00  # CORRECTED from 15.00

    def test_partial_match(self, budget_tracker):
        """Test partial model name match (Feb 2026 rates)."""
        pricing = budget_tracker.get_model_pricing("gemini-3-pro")
        assert pricing["input"] == 2.00  # CORRECTED from 1.25

    def test_fallback_to_default(self, budget_tracker):
        """Test fallback to default pricing."""
        pricing = budget_tracker.get_model_pricing("totally-unknown-model")
        assert pricing == PRICING["default"]


# =============================================================================
# TEST: BudgetState Dataclass
# =============================================================================


class TestBudgetState:
    """Tests for BudgetState dataclass."""

    def test_to_dict(self):
        """Test BudgetState.to_dict()."""
        state = BudgetState(
            spent_today_usd=10.0,
            reset_date="2025-12-05",
            total_lifetime_usd=100.0,
            api_calls_today=5,
        )

        d = state.to_dict()

        assert d["spent_today_usd"] == 10.0
        assert d["reset_date"] == "2025-12-05"
        assert d["total_lifetime_usd"] == 100.0
        assert d["api_calls_today"] == 5

    def test_from_dict(self):
        """Test BudgetState.from_dict()."""
        d = {
            "spent_today_usd": 25.0,
            "reset_date": "2025-12-05",
            "total_lifetime_usd": 500.0,
            "api_calls_today": 10,
        }

        state = BudgetState.from_dict(d)

        assert state.spent_today_usd == 25.0
        assert state.api_calls_today == 10


# =============================================================================
# TEST: Exception
# =============================================================================


class TestBudgetExceededError:
    """Tests for BudgetExceededError exception."""

    def test_exception_attributes(self):
        """Test exception has correct attributes."""
        exc = BudgetExceededError(spent=75.0, limit=50.0)

        assert exc.spent == 75.0
        assert exc.limit == 50.0
        assert "$75.00" in exc.message
        assert "$50.00" in exc.message

    def test_custom_message(self):
        """Test custom message."""
        exc = BudgetExceededError(spent=10.0, limit=5.0, message="Custom error")

        assert exc.message == "Custom error"


# =============================================================================
# TEST: Singleton
# =============================================================================


class TestSingleton:
    """Tests for get_budget_tracker singleton."""

    def test_get_returns_same_instance(self, mock_config):
        """Test singleton returns same instance."""
        reset_budget_tracker()

        t1 = get_budget_tracker(mock_config)
        t2 = get_budget_tracker(mock_config)

        assert t1 is t2

    def test_reset_clears_singleton(self, mock_config):
        """Test reset_budget_tracker clears singleton."""
        t1 = get_budget_tracker(mock_config)
        reset_budget_tracker()
        t2 = get_budget_tracker(mock_config)

        assert t1 is not t2


# Run tests if executed directly
if __name__ == "__main__":
    main()
