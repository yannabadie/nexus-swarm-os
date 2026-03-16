"""
Tests for BudgetTracker pricing correctness (Feb 2026 official rates).

This test suite verifies:
1. Correct Feb 2026 pricing for all models
2. Prompt caching economics (Anthropic Claude models)
3. Cost calculation accuracy
4. Backwards compatibility (no cache = normal pricing)

References:
- Anthropic Pricing: https://www.anthropic.com/pricing (Feb 2026)
- Google AI Pricing: https://ai.google.dev/pricing (Feb 2026)
- MASTER_ACTION_PLAN.md P0.1
"""

from pathlib import Path

import pytest

from core.observability.telemetry.budget_tracker import BudgetTracker


class TestPricingCorrectness:
    """Test that BudgetTracker uses correct Feb 2026 official pricing."""

    def test_claude_opus_pricing_correct(self, tmp_path: Path):
        """Claude Opus 4.6 should be $5/MTok input, $25/MTok output."""
        tracker = BudgetTracker(workspace_path=tmp_path)

        # 1M input + 1M output
        cost = tracker.calculate_cost(model="claude-opus-4-6", input_tokens=1_000_000, output_tokens=1_000_000)

        # Expected: $5 (input) + $25 (output) = $30
        assert cost == 30.00, f"Expected $30, got ${cost}"

    def test_claude_sonnet_pricing_correct(self, tmp_path: Path):
        """Claude Sonnet 4.5 should be $3/MTok input, $15/MTok output."""
        tracker = BudgetTracker(workspace_path=tmp_path)

        # 1M input + 1M output
        cost = tracker.calculate_cost(
            model="claude-sonnet-4-5-20250929", input_tokens=1_000_000, output_tokens=1_000_000
        )

        # Expected: $3 (input) + $15 (output) = $18
        assert cost == 18.00, f"Expected $18, got ${cost}"

    def test_claude_haiku_pricing_correct(self, tmp_path: Path):
        """Claude Haiku 4.5 should be $1/MTok input, $5/MTok output."""
        tracker = BudgetTracker(workspace_path=tmp_path)

        # 1M input + 1M output
        cost = tracker.calculate_cost(
            model="claude-haiku-4-5-20251001", input_tokens=1_000_000, output_tokens=1_000_000
        )

        # Expected: $1 (input) + $5 (output) = $6
        assert cost == 6.00, f"Expected $6, got ${cost}"

    def test_gemini_3_pro_pricing_correct(self, tmp_path: Path):
        """Gemini 3 Pro should be $2/MTok input, $12/MTok output."""
        tracker = BudgetTracker(workspace_path=tmp_path)

        # 1M input + 1M output
        cost = tracker.calculate_cost(model="gemini-3-pro-preview", input_tokens=1_000_000, output_tokens=1_000_000)

        # Expected: $2 (input) + $12 (output) = $14
        assert cost == 14.00, f"Expected $14, got ${cost}"

    def test_gemini_3_flash_pricing_correct(self, tmp_path: Path):
        """Gemini 3 Flash should be $0.50/MTok input, $3/MTok output."""
        tracker = BudgetTracker(workspace_path=tmp_path)

        # 1M input + 1M output
        cost = tracker.calculate_cost(model="gemini-3-flash", input_tokens=1_000_000, output_tokens=1_000_000)

        # Expected: $0.50 (input) + $3 (output) = $3.50
        assert cost == 3.50, f"Expected $3.50, got ${cost}"


class TestPromptCachingEconomics:
    """Test Anthropic prompt caching cost calculations."""

    def test_opus_cache_creation_cost(self, tmp_path: Path):
        """Cache creation should cost 25% more than input (6.25 vs 5.00)."""
        tracker = BudgetTracker(workspace_path=tmp_path)

        # 1M tokens written to cache
        cost = tracker.calculate_cost(
            model="claude-opus-4-6", input_tokens=0, output_tokens=0, cache_creation_tokens=1_000_000
        )

        # Expected: $6.25 (cache creation premium)
        assert cost == 6.25, f"Expected $6.25, got ${cost}"

    def test_opus_cache_read_savings(self, tmp_path: Path):
        """Cache read should save 90% vs input ($0.50 vs $5.00)."""
        tracker = BudgetTracker(workspace_path=tmp_path)

        # Scenario 1: Regular input (no cache)
        cost_no_cache = tracker.calculate_cost(model="claude-opus-4-6", input_tokens=1_000_000, output_tokens=0)

        # Scenario 2: Cache read (90% savings)
        cost_with_cache = tracker.calculate_cost(
            model="claude-opus-4-6", input_tokens=0, output_tokens=0, cache_read_tokens=1_000_000
        )

        # Verify costs
        assert cost_no_cache == 5.00, f"No cache should be $5, got ${cost_no_cache}"
        assert cost_with_cache == 0.50, f"Cache read should be $0.50, got ${cost_with_cache}"

        # Verify 90% savings
        savings_pct = (1 - cost_with_cache / cost_no_cache) * 100
        assert savings_pct == 90.0, f"Expected 90% savings, got {savings_pct:.1f}%"

    def test_sonnet_cache_read_savings(self, tmp_path: Path):
        """Sonnet cache read should also save 90% ($0.30 vs $3.00)."""
        tracker = BudgetTracker(workspace_path=tmp_path)

        # Regular input
        cost_no_cache = tracker.calculate_cost(
            model="claude-sonnet-4-5-20250929", input_tokens=1_000_000, output_tokens=0
        )

        # Cache read
        cost_with_cache = tracker.calculate_cost(
            model="claude-sonnet-4-5-20250929", input_tokens=0, output_tokens=0, cache_read_tokens=1_000_000
        )

        assert cost_no_cache == 3.00
        assert cost_with_cache == 0.30

        # Verify 90% savings
        savings_pct = (1 - cost_with_cache / cost_no_cache) * 100
        assert savings_pct == 90.0

    def test_mixed_cache_scenario(self, tmp_path: Path):
        """Test realistic scenario: some cached, some new, plus output."""
        tracker = BudgetTracker(workspace_path=tmp_path)

        # Scenario: 500k cached prompt + 100k new input + 200k output
        cost = tracker.calculate_cost(
            model="claude-opus-4-6",
            input_tokens=100_000,  # New tokens
            output_tokens=200_000,  # Response
            cache_creation_tokens=0,  # Already cached
            cache_read_tokens=500_000,  # Read from cache
        )

        # Expected breakdown:
        # - Cache read: (500k / 1M) * $0.50 = $0.25
        # - New input:  (100k / 1M) * $5.00 = $0.50
        # - Output:     (200k / 1M) * $25.00 = $5.00
        # Total: $5.75
        expected = 0.25 + 0.50 + 5.00
        assert cost == expected, f"Expected ${expected}, got ${cost}"

    def test_gemini_no_cache_support(self, tmp_path: Path):
        """Gemini models don't support caching - cache tokens should be ignored."""
        tracker = BudgetTracker(workspace_path=tmp_path)

        # Try to use cache with Gemini (should be ignored)
        cost = tracker.calculate_cost(
            model="gemini-3-pro-preview",
            input_tokens=1_000_000,
            output_tokens=0,
            cache_creation_tokens=1_000_000,  # Ignored (no cache support)
            cache_read_tokens=1_000_000,  # Ignored (no cache support)
        )

        # Expected: Only regular input cost ($2/MTok)
        assert cost == 2.00, f"Gemini cache should be ignored, expected $2, got ${cost}"


class TestBackwardsCompatibility:
    """Test that existing code without cache params still works."""

    def test_calculate_cost_without_cache_params(self, tmp_path: Path):
        """calculate_cost() should work without cache params (backwards compat)."""
        tracker = BudgetTracker(workspace_path=tmp_path)

        # Call without cache params (old API)
        cost = tracker.calculate_cost(model="claude-opus-4-6", input_tokens=1_000_000, output_tokens=1_000_000)

        # Should work and calculate normal cost
        assert cost == 30.00  # $5 input + $25 output

    def test_track_cost_without_cache_params(self, tmp_path: Path):
        """track_cost() should work without cache params (backwards compat)."""
        tracker = BudgetTracker(workspace_path=tmp_path)

        # Call without cache params (old API)
        cost = tracker.track_cost(model="claude-sonnet-4-5-20250929", input_tokens=1_000_000, output_tokens=1_000_000)

        # Should work and calculate normal cost
        assert cost == 18.00  # $3 input + $15 output

        # Verify state updated
        stats = tracker.get_stats()
        assert stats["spent_today_usd"] == 18.00


class TestCostAccuracy:
    """Test cost calculation accuracy for realistic token counts."""

    def test_small_request_accuracy(self, tmp_path: Path):
        """Test cost accuracy for typical small request (~2k tokens)."""
        tracker = BudgetTracker(workspace_path=tmp_path)

        # Typical chat: 1500 input, 500 output
        cost = tracker.calculate_cost(model="claude-sonnet-4-5-20250929", input_tokens=1_500, output_tokens=500)

        # Expected:
        # Input:  (1500 / 1M) * $3.00 = $0.0045
        # Output: (500 / 1M) * $15.00 = $0.0075
        # Total: $0.012
        expected = 0.0045 + 0.0075
        assert abs(cost - expected) < 0.00001, f"Expected ${expected}, got ${cost}"

    def test_large_context_with_cache(self, tmp_path: Path):
        """Test cost for large context with caching (realistic HiveMind scenario)."""
        tracker = BudgetTracker(workspace_path=tmp_path)

        # Large system prompt: 50k tokens (cached after first use)
        # New user message: 5k tokens
        # Response: 10k tokens
        cost = tracker.calculate_cost(
            model="claude-opus-4-6",
            input_tokens=5_000,  # New user message
            output_tokens=10_000,  # Response
            cache_creation_tokens=0,  # Already cached
            cache_read_tokens=50_000,  # System prompt cached
        )

        # Expected:
        # Cache read: (50k / 1M) * $0.50 = $0.025
        # Input:      (5k / 1M) * $5.00 = $0.025
        # Output:     (10k / 1M) * $25.00 = $0.25
        # Total: $0.30
        expected = 0.025 + 0.025 + 0.25
        assert abs(cost - expected) < 0.00001, f"Expected ${expected:.4f}, got ${cost:.4f}"

    def test_cache_savings_demonstration(self, tmp_path: Path):
        """Demonstrate massive savings from prompt caching (real-world scenario)."""
        tracker = BudgetTracker(workspace_path=tmp_path)

        # Scenario: 100k token system prompt + 5k user msg + 10k response
        # WITHOUT caching (first call)
        cost_no_cache = tracker.calculate_cost(
            model="claude-opus-4-6",
            input_tokens=105_000,  # System + user
            output_tokens=10_000,
        )

        # WITH caching (subsequent calls - system prompt cached)
        cost_with_cache = tracker.calculate_cost(
            model="claude-opus-4-6",
            input_tokens=5_000,  # Only user message
            output_tokens=10_000,
            cache_read_tokens=100_000,  # System prompt cached
        )

        # Expected costs:
        # No cache:   (105k / 1M) * $5 + (10k / 1M) * $25 = $0.525 + $0.25 = $0.775
        # With cache: (5k / 1M) * $5 + (100k / 1M) * $0.50 + (10k / 1M) * $25
        #           = $0.025 + $0.05 + $0.25 = $0.325

        assert abs(cost_no_cache - 0.775) < 0.001
        assert abs(cost_with_cache - 0.325) < 0.001

        # Savings: ~58% on this realistic scenario
        savings = (cost_no_cache - cost_with_cache) / cost_no_cache * 100
        assert savings > 50, f"Expected >50% savings, got {savings:.1f}%"


class TestModelAliases:
    """Test that all model aliases use correct pricing."""

    @pytest.mark.parametrize(
        "alias",
        [
            "claude-opus-4-6",
            "claude-opus-4-6-20250116",
            "claude-opus-4-5-20251101",
            "claude-opus",
        ],
    )
    def test_opus_aliases_correct(self, tmp_path: Path, alias: str):
        """All Opus aliases should use $5/$25 pricing."""
        tracker = BudgetTracker(workspace_path=tmp_path)
        cost = tracker.calculate_cost(alias, 1_000_000, 1_000_000)
        assert cost == 30.00, f"Alias '{alias}' pricing wrong: ${cost}"

    @pytest.mark.parametrize(
        "alias",
        [
            "claude-sonnet-4-5-20250929",
            "claude-sonnet",
        ],
    )
    def test_sonnet_aliases_correct(self, tmp_path: Path, alias: str):
        """All Sonnet aliases should use $3/$15 pricing."""
        tracker = BudgetTracker(workspace_path=tmp_path)
        cost = tracker.calculate_cost(alias, 1_000_000, 1_000_000)
        assert cost == 18.00, f"Alias '{alias}' pricing wrong: ${cost}"

    @pytest.mark.parametrize(
        "alias",
        [
            "gemini-3-pro-preview",
            "gemini-3-pro",
            "gemini-pro",
        ],
    )
    def test_gemini_pro_aliases_correct(self, tmp_path: Path, alias: str):
        """All Gemini Pro aliases should use $2/$12 pricing."""
        tracker = BudgetTracker(workspace_path=tmp_path)
        cost = tracker.calculate_cost(alias, 1_000_000, 1_000_000)
        assert cost == 14.00, f"Alias '{alias}' pricing wrong: ${cost}"


# =============================================================================
# INTEGRATION TESTS
# =============================================================================


class TestIntegration:
    """Integration tests for BudgetTracker module."""

    def test_budget_tracker_imports_correctly(self):
        """Test that BudgetTracker can be imported."""
        from core.observability.telemetry.budget_tracker import PRICING, BudgetTracker

        assert BudgetTracker is not None
        assert "claude-opus-4-6" in PRICING
        assert "cache_creation" in PRICING["claude-opus-4-6"]

    def test_pricing_dict_structure(self):
        """Test that PRICING dictionary has correct structure."""
        from core.observability.telemetry.budget_tracker import PRICING

        # Claude models should have cache fields
        claude_models = [k for k in PRICING if "claude" in k]
        for model in claude_models:
            if model == "default":
                continue
            assert "input" in PRICING[model], f"{model} missing 'input'"
            assert "output" in PRICING[model], f"{model} missing 'output'"
            assert "cache_creation" in PRICING[model], f"{model} missing 'cache_creation'"
            assert "cache_read" in PRICING[model], f"{model} missing 'cache_read'"

        # Gemini models should NOT have cache fields
        gemini_models = [k for k in PRICING if "gemini" in k]
        for model in gemini_models:
            assert "input" in PRICING[model]
            assert "output" in PRICING[model]
            assert "cache_creation" not in PRICING[model], f"{model} shouldn't have caching"
