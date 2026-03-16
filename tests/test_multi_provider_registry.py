"""
Tests for multi-provider round-robin support in UnifiedAgentRegistry.

Validates get_next(), get_active_builtin_ids(), and backward-compatible
get_alternate() behavior with 2, 3, and N registered agents.
"""

import pytest
from unittest.mock import MagicMock

from core.foundation.agents.unified_registry import get_registry, reset_registry


class TestGetNext:
    def setup_method(self):
        reset_registry()
        self.registry = get_registry()
        # Register 2 default agents with mock drivers
        self.registry.register_driver("gemini", MagicMock())
        self.registry.register_driver("claude", MagicMock())

    def test_two_agents_alternates(self):
        assert self.registry.get_next("gemini") == "claude"
        assert self.registry.get_next("claude") == "gemini"

    def test_three_agents_round_robin(self):
        self.registry.register_driver("deepseek", MagicMock())
        assert self.registry.get_next("gemini") == "claude"
        assert self.registry.get_next("claude") == "deepseek"
        assert self.registry.get_next("deepseek") == "gemini"

    def test_four_agents_round_robin(self):
        self.registry.register_driver("deepseek", MagicMock())
        self.registry.register_driver("kimi", MagicMock())
        assert self.registry.get_next("gemini") == "claude"
        assert self.registry.get_next("claude") == "deepseek"
        assert self.registry.get_next("deepseek") == "kimi"
        assert self.registry.get_next("kimi") == "gemini"

    def test_unknown_agent_returns_first(self):
        result = self.registry.get_next("unknown_xyz")
        assert result == "gemini"  # First registered

    def test_single_agent_returns_self(self):
        reset_registry()
        reg = get_registry()
        reg.register_driver("gemini", MagicMock())
        assert reg.get_next("gemini") == "gemini"

    def test_get_alternate_backward_compat(self):
        assert self.registry.get_alternate("gemini") == "claude"
        assert self.registry.get_alternate("claude") == "gemini"

    def test_get_alternate_three_agents(self):
        self.registry.register_driver("deepseek", MagicMock())
        # get_alternate still works (returns next, not None)
        assert self.registry.get_alternate("gemini") == "claude"
        assert self.registry.get_alternate("deepseek") == "gemini"

    def test_get_active_builtin_ids(self):
        agents = self.registry.get_active_builtin_ids()
        assert agents == ["gemini", "claude"]

    def test_get_active_builtin_ids_with_third(self):
        self.registry.register_driver("deepseek", MagicMock())
        agents = self.registry.get_active_builtin_ids()
        assert agents == ["gemini", "claude", "deepseek"]

    def test_registration_order_preserved(self):
        self.registry.register_driver("kimi", MagicMock())
        self.registry.register_driver("openai", MagicMock())
        agents = self.registry.get_active_builtin_ids()
        assert agents == ["gemini", "claude", "kimi", "openai"]
