# tests/test_capability_router.py
"""Tests for CapabilityRouter — model-agnostic slot assignment."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from core.intelligence.swarm.capability_router import (
    CapabilityRouter,
    SlotAssignment,
    SLOT_PRIMARY,
    SLOT_SECONDARY,
    SLOT_CRITIC,
    SLOT_EXECUTOR,
    ALL_SLOTS,
)
from core.intelligence.swarm.task_analyzer import TaskAnalysis, TaskDomain, TaskComplexity


def _make_registry(provider_ids: list[str]):
    """Build a minimal mock registry."""
    registry = MagicMock()
    registry.get_active_builtin_ids.return_value = provider_ids
    # get_driver returns a distinguishable mock per provider
    drivers = {pid: MagicMock(name=f"driver_{pid}") for pid in provider_ids}
    registry.get_driver.side_effect = lambda pid: drivers.get(pid, MagicMock())
    return registry


def _make_analysis(domains: list[TaskDomain] | None = None) -> TaskAnalysis:
    resolved_domains = domains or [TaskDomain.CODING]
    return TaskAnalysis(
        raw_input="test",
        complexity=TaskComplexity.MODERATE,
        domains=resolved_domains,
        primary_domain=resolved_domains[0],
        gemini_fit_score=0.5,
        claude_fit_score=0.5,
    )


class TestCapabilityRouterTwoProviders:
    def test_returns_four_slots(self):
        router = CapabilityRouter(_make_registry(["claude", "gemini"]))
        result = router.route(_make_analysis())
        assert set(result.keys()) == set(ALL_SLOTS)

    def test_all_slots_have_drivers(self):
        router = CapabilityRouter(_make_registry(["claude", "gemini"]))
        result = router.route(_make_analysis())
        for slot in ALL_SLOTS:
            assert result[slot] is not None

    def test_primary_and_secondary_are_different_with_two_providers(self):
        router = CapabilityRouter(_make_registry(["claude", "gemini"]))
        result = router.route(_make_analysis())
        # With 2 providers, primary and secondary should use different drivers
        assert result[SLOT_PRIMARY] is not result[SLOT_SECONDARY]

    def test_research_domain_prefers_gemini(self):
        """Gemini has highest research score (0.95) in AGENT_DOMAIN_STRENGTHS."""
        registry = _make_registry(["gemini", "claude", "openai"])
        router = CapabilityRouter(registry)
        router.route(_make_analysis([TaskDomain.RESEARCH]))
        # First get_driver call should be for primary slot = gemini
        first_provider = registry.get_driver.call_args_list[0][0][0]
        assert first_provider == "gemini"

    def test_coding_domain_prefers_claude_over_gemini(self):
        """Claude has highest coding score (0.95) vs Gemini (0.80) for CODING."""
        registry = _make_registry(["gemini", "claude"])
        router = CapabilityRouter(registry)
        router.route(_make_analysis([TaskDomain.CODING]))
        first_provider = registry.get_driver.call_args_list[0][0][0]
        assert first_provider == "claude"


class TestCapabilityRouterSingleProvider:
    def test_single_provider_returns_four_slots(self):
        router = CapabilityRouter(_make_registry(["claude"]))
        result = router.route(_make_analysis())
        assert set(result.keys()) == set(ALL_SLOTS)

    def test_single_provider_all_slots_same_driver(self):
        registry = _make_registry(["claude"])
        router = CapabilityRouter(registry)
        result = router.route(_make_analysis())
        drivers = list(result.values())
        # All slots should use the same driver instance
        assert all(d is drivers[0] for d in drivers)

    def test_single_provider_no_error(self):
        router = CapabilityRouter(_make_registry(["deepseek"]))
        result = router.route(_make_analysis([TaskDomain.RESEARCH]))
        assert len(result) == 4


class TestCapabilityRouterEmptyRegistry:
    def test_empty_registry_raises_runtime_error(self):
        router = CapabilityRouter(_make_registry([]))
        with pytest.raises(RuntimeError, match="No providers registered"):
            router.route(_make_analysis())


class TestSlotAssignment:
    def test_slot_assignment_dataclass(self):
        sa = SlotAssignment(slot=SLOT_PRIMARY, provider_id="claude", score=0.85)
        assert sa.slot == SLOT_PRIMARY
        assert sa.provider_id == "claude"
        assert sa.score == 0.85

    def test_slot_assignment_frozen(self):
        sa = SlotAssignment(slot=SLOT_PRIMARY, provider_id="claude", score=0.85)
        with pytest.raises(Exception):  # frozen dataclass
            sa.slot = "secondary"  # type: ignore


class TestCapabilityRouterSevenProviders:
    def test_seven_providers_no_error(self):
        providers = ["claude", "gemini", "openai", "deepseek", "kimi", "minimax", "ollama"]
        router = CapabilityRouter(_make_registry(providers))
        result = router.route(_make_analysis([TaskDomain.CODING, TaskDomain.RESEARCH]))
        assert set(result.keys()) == set(ALL_SLOTS)

    def test_security_domain_uses_critic_slot(self):
        """Critic slot should map to best security provider."""
        providers = ["claude", "gemini", "openai"]
        router = CapabilityRouter(_make_registry(providers))
        result = router.route(_make_analysis([TaskDomain.SECURITY]))
        assert result[SLOT_CRITIC] is not None
