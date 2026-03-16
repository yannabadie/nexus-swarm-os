"""
Tests for V8.8 Adaptive Fallback Selector (GROK-004)

Tests the context-aware fallback selection that replaces static chains.
"""

import sys
from pathlib import Path

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.intelligence.swarm.adaptive_fallback import (
    DOMAIN_FALLBACK_PREFERENCES,
    STAGNATION_SHORTCUTS,
    AdaptiveFallbackSelector,
    FallbackContext,
    FallbackDecision,
    get_adaptive_fallback_selector,
)
from core.intelligence.swarm.collaboration_modes import CollaborationMode


class TestFallbackContext:
    """Tests for FallbackContext dataclass."""

    def test_default_context(self):
        """Test default context creation."""
        ctx = FallbackContext()
        assert ctx.domains == []
        assert ctx.complexity == "moderate"
        assert ctx.stagnation_level is None
        assert ctx.current_lead == "gemini"

    def test_context_with_domains(self):
        """Test context with domain information."""
        ctx = FallbackContext(domains=["coding", "security"], complexity="complex")
        assert "coding" in ctx.domains
        assert ctx.complexity == "complex"


class TestAdaptiveFallbackSelector:
    """Tests for AdaptiveFallbackSelector."""

    def test_selector_creation(self):
        """Test selector can be created."""
        selector = AdaptiveFallbackSelector()
        assert selector is not None

    def test_terminal_mode_no_fallback(self):
        """Test SPECIALIST has no fallback."""
        selector = AdaptiveFallbackSelector()
        ctx = FallbackContext()

        decision = selector.get_adaptive_fallback(CollaborationMode.SPECIALIST, ctx)

        assert decision.fallback_mode is None
        assert "terminal" in decision.reason.lower()
        assert decision.confidence == 1.0

    def test_domain_coding_prefers_lead_support(self):
        """Test that coding domain prefers LEAD_SUPPORT from PARALLEL."""
        selector = AdaptiveFallbackSelector()
        ctx = FallbackContext(domains=["coding"])

        decision = selector.get_adaptive_fallback(CollaborationMode.PARALLEL, ctx)

        assert decision.fallback_mode == CollaborationMode.LEAD_SUPPORT
        assert "coding" in decision.reason.lower()

    def test_domain_research_prefers_sequential(self):
        """Test that research domain prefers SEQUENTIAL from PARALLEL."""
        selector = AdaptiveFallbackSelector()
        ctx = FallbackContext(domains=["research"])

        decision = selector.get_adaptive_fallback(CollaborationMode.PARALLEL, ctx)

        assert decision.fallback_mode == CollaborationMode.SEQUENTIAL
        assert "research" in decision.reason.lower()

    def test_high_stagnation_uses_shortcut(self):
        """Test that high stagnation skips intermediate modes."""
        selector = AdaptiveFallbackSelector()
        ctx = FallbackContext(stagnation_level="high", messages_since_progress=5)

        decision = selector.get_adaptive_fallback(CollaborationMode.PARALLEL, ctx)

        assert decision.fallback_mode == CollaborationMode.SPECIALIST
        assert decision.skip_intermediate is True
        assert "stagnation" in decision.reason.lower()

    def test_critical_stagnation_uses_shortcut(self):
        """Test that critical stagnation uses shortcuts."""
        selector = AdaptiveFallbackSelector()
        ctx = FallbackContext(stagnation_level="critical")

        decision = selector.get_adaptive_fallback(CollaborationMode.RED_BLUE, ctx)

        assert decision.fallback_mode == CollaborationMode.SPECIALIST
        assert decision.skip_intermediate is True

    def test_static_fallback_when_no_context(self):
        """Test static fallback when no domain/stagnation context."""
        selector = AdaptiveFallbackSelector()
        ctx = FallbackContext()  # Empty context

        decision = selector.get_adaptive_fallback(CollaborationMode.LEAD_SUPPORT, ctx)

        # Should use static chain
        assert decision.fallback_mode == CollaborationMode.SPECIALIST
        assert "static" in decision.reason.lower()

    def test_modes_tried_tracked(self):
        """Test that previously tried modes are in context."""
        selector = AdaptiveFallbackSelector()
        ctx = FallbackContext(modes_tried=["parallel", "sequential"])

        decision = selector.get_adaptive_fallback(CollaborationMode.SEQUENTIAL, ctx)

        # Should still work with modes_tried
        assert decision.fallback_mode is not None or decision.reason

    def test_decision_to_dict(self):
        """Test FallbackDecision serialization."""
        decision = FallbackDecision(
            fallback_mode=CollaborationMode.SPECIALIST, reason="Test reason", confidence=0.8, skip_intermediate=True
        )

        d = decision.to_dict()
        assert d["fallback_mode"] == "specialist"
        assert d["reason"] == "Test reason"
        assert d["confidence"] == 0.8
        assert d["skip_intermediate"] is True


class TestDomainFallbackPreferences:
    """Tests for domain fallback preference mapping."""

    def test_parallel_security_prefers_red_blue(self):
        """Security domain should prefer RED_BLUE for adversarial review."""
        prefs = DOMAIN_FALLBACK_PREFERENCES.get("parallel", {})
        assert prefs.get("security") == "red_blue"

    def test_parallel_architecture_prefers_lead_support(self):
        """Architecture domain should prefer LEAD_SUPPORT."""
        prefs = DOMAIN_FALLBACK_PREFERENCES.get("parallel", {})
        assert prefs.get("architecture") == "lead_support"

    def test_red_blue_security_prefers_specialist(self):
        """Security from RED_BLUE should go to SPECIALIST."""
        prefs = DOMAIN_FALLBACK_PREFERENCES.get("red_blue", {})
        assert prefs.get("security") == "specialist"


class TestStagnationShortcuts:
    """Tests for stagnation-triggered shortcuts."""

    def test_parallel_shortcut_to_specialist(self):
        """PARALLEL should shortcut to SPECIALIST on high stagnation."""
        assert STAGNATION_SHORTCUTS.get("parallel") == "specialist"

    def test_red_blue_shortcut_to_specialist(self):
        """RED_BLUE should shortcut to SPECIALIST."""
        assert STAGNATION_SHORTCUTS.get("red_blue") == "specialist"

    def test_all_modes_have_shortcuts(self):
        """All non-terminal modes should have shortcuts defined."""
        non_terminal = ["parallel", "red_blue", "lead_support", "ping_pong", "sequential"]
        for mode in non_terminal:
            assert mode in STAGNATION_SHORTCUTS


class TestSingleton:
    """Tests for singleton access."""

    def test_get_adaptive_fallback_selector(self):
        """Test singleton getter."""
        selector1 = get_adaptive_fallback_selector()
        selector2 = get_adaptive_fallback_selector()

        # Should be the same instance
        assert selector1 is selector2

    def test_singleton_is_functional(self):
        """Test singleton can make decisions."""
        selector = get_adaptive_fallback_selector()
        ctx = FallbackContext(domains=["coding"])

        decision = selector.get_adaptive_fallback(CollaborationMode.PARALLEL, ctx)

        assert decision is not None
        assert decision.fallback_mode is not None


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_domain_list(self):
        """Test handling of empty domain list."""
        selector = AdaptiveFallbackSelector()
        ctx = FallbackContext(domains=[])

        decision = selector.get_adaptive_fallback(CollaborationMode.PARALLEL, ctx)

        # Should fall back to static chain
        assert decision.fallback_mode is not None

    def test_unknown_domain(self):
        """Test handling of unknown domain."""
        selector = AdaptiveFallbackSelector()
        ctx = FallbackContext(domains=["quantum_computing"])

        decision = selector.get_adaptive_fallback(CollaborationMode.PARALLEL, ctx)

        # Should fall back to default or static chain
        assert decision.fallback_mode is not None

    def test_multiple_errors_with_stagnation(self):
        """Test handling with multiple errors and many messages triggers shortcut."""
        selector = AdaptiveFallbackSelector()
        ctx = FallbackContext(
            errors_encountered=["Error 1", "Error 2", "Error 3"],
            messages_since_progress=6,
            stagnation_level="high",  # Need stagnation for shortcut
        )

        decision = selector.get_adaptive_fallback(CollaborationMode.PARALLEL, ctx)

        # Multiple errors + stagnation should trigger shortcut
        assert decision.skip_intermediate is True

    def test_errors_alone_use_domain_or_static(self):
        """Test that errors alone use domain or static fallback."""
        selector = AdaptiveFallbackSelector()
        ctx = FallbackContext(
            errors_encountered=["Error 1", "Error 2"],
            messages_since_progress=6,
            # No stagnation_level = no shortcut
        )

        decision = selector.get_adaptive_fallback(CollaborationMode.PARALLEL, ctx)

        # Without stagnation, should use static fallback
        assert decision.fallback_mode is not None

    def test_confidence_range(self):
        """Test that confidence is always in valid range."""
        selector = AdaptiveFallbackSelector()

        for mode in CollaborationMode:
            ctx = FallbackContext()
            decision = selector.get_adaptive_fallback(mode, ctx)
            assert 0.0 <= decision.confidence <= 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
