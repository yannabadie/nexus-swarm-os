# tests/test_base_phase.py
"""Tests for BasePhase — deprecated alias behavior."""
from __future__ import annotations

import warnings
import pytest
from unittest.mock import MagicMock

from core.intelligence.hive_mind.base_phase import BasePhase


class ConcretePhase(BasePhase):
    """Minimal concrete subclass for testing."""
    pass


class TestBasePhase:
    def test_agents_dict_stored(self):
        d = MagicMock()
        phase = ConcretePhase(agents={"primary": d})
        assert phase.agents == {"primary": d}

    def test_empty_init(self):
        phase = ConcretePhase()
        assert phase.agents == {}

    def test_gemini_alias_returns_primary(self):
        d = MagicMock()
        phase = ConcretePhase(agents={"primary": d})
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = phase.gemini
        assert result is d

    def test_gemini_alias_emits_deprecation_warning(self):
        phase = ConcretePhase(agents={"primary": MagicMock()})
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _ = phase.gemini
            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert "primary" in str(w[0].message)

    def test_claude_alias_returns_secondary(self):
        d = MagicMock()
        phase = ConcretePhase(agents={"secondary": d})
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = phase.claude
        assert result is d

    def test_claude_alias_emits_deprecation_warning(self):
        phase = ConcretePhase(agents={"secondary": MagicMock()})
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _ = phase.claude
            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)

    def test_gemini_falls_back_to_gemini_key(self):
        d = MagicMock()
        phase = ConcretePhase(agents={"gemini": d})
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = phase.gemini
        assert result is d

    def test_claude_falls_back_to_claude_key(self):
        d = MagicMock()
        phase = ConcretePhase(agents={"claude": d})
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = phase.claude
        assert result is d

    def test_empty_agents_aliases_return_none(self):
        phase = ConcretePhase(agents={})
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            assert phase.gemini is None
            assert phase.claude is None

    def test_gemini_setter_stores_in_agents(self):
        d = MagicMock()
        phase = ConcretePhase(agents={})
        phase.gemini = d  # uses setter
        assert phase.agents.get("gemini") is d

    def test_claude_setter_stores_in_agents(self):
        d = MagicMock()
        phase = ConcretePhase(agents={})
        phase.claude = d  # uses setter
        assert phase.agents.get("claude") is d
