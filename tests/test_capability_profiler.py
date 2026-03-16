"""
Tests for V12.4 Capability Profiler.

Validates:
- Agent registration with capabilities
- Capability add/remove
- Outcome recording and proficiency learning (EMA)
- Proficiency decay over inactivity
- Task-capability matching and scoring
- Best match / rank all agents
- Preferred capabilities bonus
- Exclude agents from matching
- Queries (list, top agents, agents with capability)
- State management (clear, remove, export)
- Module exports
"""

import time

import pytest

from core.foundation.agents.capability_profiler import (
    DEFAULT_PROFICIENCY,
    KNOWN_CAPABILITIES,
    LEARNING_RATE,
    MIN_OBSERVATIONS,
    AgentProfile,
    CapabilityProfiler,
    CapabilityRecord,
    MatchResult,
    get_capability_profiler,
    reset_capability_profiler,
)

# =============================================================================
# CapabilityRecord Tests
# =============================================================================


class TestCapabilityRecord:
    """Test CapabilityRecord dataclass."""

    def test_defaults(self):
        rec = CapabilityRecord(capability="coding")
        assert rec.capability == "coding"
        assert rec.proficiency == DEFAULT_PROFICIENCY
        assert rec.observations == 0
        assert rec.successes == 0

    def test_success_rate_no_observations(self):
        rec = CapabilityRecord(capability="coding")
        assert rec.success_rate == 0.0

    def test_success_rate(self):
        rec = CapabilityRecord(capability="coding", observations=10, successes=7)
        assert rec.success_rate == 0.7

    def test_average_quality_no_observations(self):
        rec = CapabilityRecord(capability="coding")
        assert rec.average_quality == 0.0

    def test_average_quality(self):
        rec = CapabilityRecord(capability="coding", observations=4, total_quality=3.2)
        assert rec.average_quality == pytest.approx(0.8)

    def test_is_reliable_below_threshold(self):
        rec = CapabilityRecord(capability="coding", observations=2)
        assert rec.is_reliable is False

    def test_is_reliable_above_threshold(self):
        rec = CapabilityRecord(capability="coding", observations=MIN_OBSERVATIONS)
        assert rec.is_reliable is True

    def test_to_dict(self):
        rec = CapabilityRecord(
            capability="coding",
            proficiency=0.8,
            observations=5,
            successes=4,
            total_quality=3.5,
        )
        d = rec.to_dict()
        assert d["capability"] == "coding"
        assert d["proficiency"] == 0.8
        assert d["observations"] == 5
        assert d["is_reliable"] is True


# =============================================================================
# AgentProfile Tests
# =============================================================================


class TestAgentProfile:
    """Test AgentProfile dataclass."""

    def test_basic_creation(self):
        profile = AgentProfile(agent_id="claude")
        assert profile.agent_id == "claude"
        assert profile.total_tasks == 0
        assert profile.capability_names == []

    def test_overall_success_rate_no_tasks(self):
        profile = AgentProfile(agent_id="claude")
        assert profile.overall_success_rate == 0.0

    def test_overall_success_rate(self):
        profile = AgentProfile(agent_id="claude", total_tasks=10, total_successes=8)
        assert profile.overall_success_rate == 0.8

    def test_get_proficiency_missing(self):
        profile = AgentProfile(agent_id="claude")
        assert profile.get_proficiency("coding") == 0.0

    def test_get_proficiency_present(self):
        profile = AgentProfile(agent_id="claude")
        profile.capabilities["coding"] = CapabilityRecord(
            capability="coding",
            proficiency=0.9,
        )
        assert profile.get_proficiency("coding") == 0.9

    def test_capability_names_sorted(self):
        profile = AgentProfile(agent_id="claude")
        profile.capabilities["debugging"] = CapabilityRecord(capability="debugging")
        profile.capabilities["coding"] = CapabilityRecord(capability="coding")
        profile.capabilities["analysis"] = CapabilityRecord(capability="analysis")
        assert profile.capability_names == ["analysis", "coding", "debugging"]

    def test_to_dict(self):
        profile = AgentProfile(agent_id="claude", total_tasks=5, total_successes=4)
        profile.capabilities["coding"] = CapabilityRecord(
            capability="coding",
            proficiency=0.85,
        )
        d = profile.to_dict()
        assert d["agent_id"] == "claude"
        assert d["total_tasks"] == 5
        assert d["overall_success_rate"] == 0.8
        assert "coding" in d["capabilities"]


# =============================================================================
# MatchResult Tests
# =============================================================================


class TestMatchResult:
    """Test MatchResult dataclass."""

    def test_full_match(self):
        m = MatchResult(
            agent_id="claude",
            score=0.9,
            matched_capabilities=["coding", "debugging"],
            missing_capabilities=[],
            proficiency_details={"coding": 0.9, "debugging": 0.85},
        )
        assert m.is_full_match is True

    def test_partial_match(self):
        m = MatchResult(
            agent_id="gemini",
            score=0.5,
            matched_capabilities=["research"],
            missing_capabilities=["coding"],
            proficiency_details={"research": 0.8, "coding": 0.0},
        )
        assert m.is_full_match is False

    def test_to_dict(self):
        m = MatchResult(
            agent_id="claude",
            score=0.85,
            matched_capabilities=["coding"],
            missing_capabilities=["research"],
            proficiency_details={"coding": 0.9, "research": 0.0},
        )
        d = m.to_dict()
        assert d["agent_id"] == "claude"
        assert d["score"] == 0.85
        assert d["is_full_match"] is False


# =============================================================================
# Registration Tests
# =============================================================================


class TestRegistration:
    """Test agent registration."""

    def test_register_agent(self):
        p = CapabilityProfiler()
        profile = p.register_agent("claude", capabilities=["coding", "debugging"])
        assert profile.agent_id == "claude"
        assert "coding" in profile.capabilities
        assert "debugging" in profile.capabilities

    def test_register_with_initial_proficiency(self):
        p = CapabilityProfiler()
        profile = p.register_agent(
            "claude",
            capabilities=["coding", "research"],
            initial_proficiency={"coding": 0.9, "research": 0.3},
        )
        assert profile.get_proficiency("coding") == 0.9
        assert profile.get_proficiency("research") == 0.3

    def test_register_default_proficiency(self):
        p = CapabilityProfiler()
        profile = p.register_agent("claude", capabilities=["coding"])
        assert profile.get_proficiency("coding") == DEFAULT_PROFICIENCY

    def test_register_no_capabilities(self):
        p = CapabilityProfiler()
        profile = p.register_agent("claude")
        assert len(profile.capabilities) == 0

    def test_add_capability(self):
        p = CapabilityProfiler()
        p.register_agent("claude", capabilities=["coding"])
        assert p.add_capability("claude", "debugging", 0.7) is True
        assert p.get_proficiency("claude", "debugging") == 0.7

    def test_add_capability_unknown_agent(self):
        p = CapabilityProfiler()
        assert p.add_capability("unknown", "coding") is False

    def test_add_capability_clamps(self):
        p = CapabilityProfiler()
        p.register_agent("claude")
        p.add_capability("claude", "coding", 1.5)
        assert p.get_proficiency("claude", "coding") == 1.0
        p.add_capability("claude", "debugging", -0.5)
        assert p.get_proficiency("claude", "debugging") == 0.0

    def test_remove_capability(self):
        p = CapabilityProfiler()
        p.register_agent("claude", capabilities=["coding", "debugging"])
        assert p.remove_capability("claude", "coding") is True
        assert "coding" not in p.list_capabilities("claude")

    def test_remove_capability_nonexistent(self):
        p = CapabilityProfiler()
        p.register_agent("claude")
        assert p.remove_capability("claude", "missing") is False

    def test_remove_capability_unknown_agent(self):
        p = CapabilityProfiler()
        assert p.remove_capability("unknown", "coding") is False


# =============================================================================
# Outcome Recording & Learning Tests
# =============================================================================


class TestOutcomeRecording:
    """Test outcome recording and proficiency learning."""

    def test_record_success(self):
        p = CapabilityProfiler()
        p.register_agent("claude", capabilities=["coding"])
        result = p.record_outcome("claude", "coding", success=True, quality=0.9)
        assert result is True
        profile = p.get_profile("claude")
        assert profile.total_tasks == 1
        assert profile.total_successes == 1

    def test_record_failure(self):
        p = CapabilityProfiler()
        p.register_agent("claude", capabilities=["coding"])
        p.record_outcome("claude", "coding", success=False)
        profile = p.get_profile("claude")
        assert profile.total_tasks == 1
        assert profile.total_successes == 0

    def test_record_unknown_agent(self):
        p = CapabilityProfiler()
        assert p.record_outcome("unknown", "coding", success=True) is False

    def test_record_auto_creates_capability(self):
        p = CapabilityProfiler()
        p.register_agent("claude")
        p.record_outcome("claude", "new_cap", success=True, quality=0.8)
        assert "new_cap" in p.list_capabilities("claude")

    def test_proficiency_increases_on_success(self):
        p = CapabilityProfiler()
        p.register_agent("claude", capabilities=["coding"])
        initial = p.get_proficiency("claude", "coding")
        p.record_outcome("claude", "coding", success=True, quality=1.0)
        assert p.get_proficiency("claude", "coding") > initial

    def test_proficiency_decreases_on_failure(self):
        p = CapabilityProfiler()
        p.register_agent(
            "claude",
            capabilities=["coding"],
            initial_proficiency={"coding": 0.8},
        )
        p.record_outcome("claude", "coding", success=False)
        assert p.get_proficiency("claude", "coding") < 0.8

    def test_ema_convergence(self):
        """Multiple successes should push proficiency toward 1.0."""
        p = CapabilityProfiler()
        p.register_agent("claude", capabilities=["coding"], initial_proficiency={"coding": 0.5})
        for _ in range(20):
            p.record_outcome("claude", "coding", success=True, quality=1.0)
        assert p.get_proficiency("claude", "coding") > 0.9

    def test_observations_count(self):
        p = CapabilityProfiler()
        p.register_agent("claude", capabilities=["coding"])
        for _ in range(5):
            p.record_outcome("claude", "coding", success=True, quality=0.8)
        rec = p.get_profile("claude").capabilities["coding"]
        assert rec.observations == 5
        assert rec.successes == 5

    def test_proficiency_stays_bounded(self):
        p = CapabilityProfiler()
        p.register_agent("claude", capabilities=["coding"], initial_proficiency={"coding": 0.99})
        p.record_outcome("claude", "coding", success=True, quality=1.0)
        assert 0.0 <= p.get_proficiency("claude", "coding") <= 1.0

    def test_success_without_quality(self):
        """Success without explicit quality should use default 0.7."""
        p = CapabilityProfiler()
        p.register_agent("claude", capabilities=["coding"], initial_proficiency={"coding": 0.5})
        p.record_outcome("claude", "coding", success=True)
        # EMA: 0.5 * 0.8 + 0.7 * 0.2 = 0.4 + 0.14 = 0.54
        expected = (1 - LEARNING_RATE) * 0.5 + LEARNING_RATE * 0.7
        assert p.get_proficiency("claude", "coding") == pytest.approx(expected, abs=0.01)


# =============================================================================
# Decay Tests
# =============================================================================


class TestDecay:
    """Test proficiency decay."""

    def test_no_decay_recent(self):
        p = CapabilityProfiler()
        p.register_agent("claude", capabilities=["coding"], initial_proficiency={"coding": 0.9})
        decayed = p.apply_decay("claude")
        assert decayed == 0

    def test_decay_applied(self):
        p = CapabilityProfiler(decay_rate_per_hour=0.1)
        profile = p.register_agent(
            "claude",
            capabilities=["coding"],
            initial_proficiency={"coding": 0.9},
        )
        # Simulate 2 hours ago
        rec = profile.capabilities["coding"]
        rec.last_updated = time.monotonic() - 7200
        decayed = p.apply_decay("claude")
        assert decayed == 1
        assert p.get_proficiency("claude", "coding") < 0.9

    def test_decay_toward_default(self):
        """Proficiency should decay toward DEFAULT_PROFICIENCY."""
        p = CapabilityProfiler(decay_rate_per_hour=1.0)
        profile = p.register_agent(
            "claude",
            capabilities=["coding"],
            initial_proficiency={"coding": 0.9},
        )
        rec = profile.capabilities["coding"]
        rec.last_updated = time.monotonic() - 7200  # 2 hours
        p.apply_decay("claude")
        # Should move toward 0.5 but not below it
        assert p.get_proficiency("claude", "coding") >= DEFAULT_PROFICIENCY

    def test_decay_low_proficiency_increases(self):
        """Low proficiency should decay upward toward default."""
        p = CapabilityProfiler(decay_rate_per_hour=0.1)
        profile = p.register_agent(
            "claude",
            capabilities=["coding"],
            initial_proficiency={"coding": 0.1},
        )
        rec = profile.capabilities["coding"]
        rec.last_updated = time.monotonic() - 7200
        p.apply_decay("claude")
        assert p.get_proficiency("claude", "coding") > 0.1

    def test_decay_all_agents(self):
        p = CapabilityProfiler(decay_rate_per_hour=0.1)
        for name in ["claude", "gemini"]:
            profile = p.register_agent(
                name,
                capabilities=["coding"],
                initial_proficiency={"coding": 0.9},
            )
            profile.capabilities["coding"].last_updated = time.monotonic() - 7200
        decayed = p.apply_decay()
        assert decayed == 2


# =============================================================================
# Matching Tests
# =============================================================================


class TestMatching:
    """Test task-capability matching."""

    def _setup_profiler(self):
        p = CapabilityProfiler()
        p.register_agent(
            "claude",
            capabilities=["coding", "debugging", "architecture"],
            initial_proficiency={"coding": 0.9, "debugging": 0.85, "architecture": 0.8},
        )
        p.register_agent(
            "gemini",
            capabilities=["research", "web_search", "summarization"],
            initial_proficiency={"research": 0.95, "web_search": 0.9, "summarization": 0.85},
        )
        p.register_agent(
            "ollama",
            capabilities=["coding", "general"],
            initial_proficiency={"coding": 0.6, "general": 0.5},
        )
        return p

    def test_best_match_coding(self):
        p = self._setup_profiler()
        match = p.best_match(required=["coding"])
        assert match is not None
        assert match.agent_id == "claude"
        assert match.score > 0.8

    def test_best_match_research(self):
        p = self._setup_profiler()
        match = p.best_match(required=["research"])
        assert match is not None
        assert match.agent_id == "gemini"

    def test_best_match_multiple_required(self):
        p = self._setup_profiler()
        match = p.best_match(required=["coding", "debugging"])
        assert match is not None
        assert match.agent_id == "claude"
        assert match.is_full_match is True

    def test_best_match_no_full_match(self):
        p = self._setup_profiler()
        match = p.best_match(required=["coding", "web_search"])
        assert match is not None
        # No agent has both coding + web_search
        assert match.is_full_match is False

    def test_match_with_preferred(self):
        p = self._setup_profiler()
        match = p.best_match(
            required=["coding"],
            preferred=["debugging"],
        )
        assert match is not None
        assert match.agent_id == "claude"

    def test_match_exclude(self):
        p = self._setup_profiler()
        match = p.best_match(required=["coding"], exclude=["claude"])
        assert match is not None
        assert match.agent_id == "ollama"

    def test_match_all_ranked(self):
        p = self._setup_profiler()
        results = p.match_all(required=["coding"])
        assert len(results) == 3  # claude, ollama, gemini (0 proficiency)
        assert results[0].agent_id == "claude"
        assert results[0].score >= results[1].score

    def test_match_no_agents(self):
        p = CapabilityProfiler()
        match = p.best_match(required=["coding"])
        assert match is None

    def test_match_empty_required(self):
        p = self._setup_profiler()
        match = p.best_match(required=[])
        assert match is not None
        # With no requirements, score is based on preferred only
        assert match.score == 0.0

    def test_missing_capabilities_listed(self):
        p = self._setup_profiler()
        results = p.match_all(required=["coding", "web_search"])
        # Claude has coding but not web_search
        claude_result = next(r for r in results if r.agent_id == "claude")
        assert "coding" in claude_result.matched_capabilities
        assert "web_search" in claude_result.missing_capabilities

    def test_proficiency_details_in_result(self):
        p = self._setup_profiler()
        match = p.best_match(required=["coding"])
        assert "coding" in match.proficiency_details
        assert match.proficiency_details["coding"] == 0.9


# =============================================================================
# Query Tests
# =============================================================================


class TestQueries:
    """Test query methods."""

    def test_list_agents(self):
        p = CapabilityProfiler()
        p.register_agent("claude")
        p.register_agent("gemini")
        agents = p.list_agents()
        assert agents == ["claude", "gemini"]

    def test_list_capabilities(self):
        p = CapabilityProfiler()
        p.register_agent("claude", capabilities=["coding", "debugging"])
        caps = p.list_capabilities("claude")
        assert caps == ["coding", "debugging"]

    def test_list_capabilities_unknown(self):
        p = CapabilityProfiler()
        assert p.list_capabilities("unknown") == []

    def test_agents_with_capability(self):
        p = CapabilityProfiler()
        p.register_agent("claude", capabilities=["coding", "debugging"])
        p.register_agent("gemini", capabilities=["research"])
        p.register_agent("ollama", capabilities=["coding"])
        agents = p.agents_with_capability("coding")
        assert agents == ["claude", "ollama"]

    def test_agents_with_capability_none(self):
        p = CapabilityProfiler()
        p.register_agent("claude", capabilities=["coding"])
        assert p.agents_with_capability("missing") == []

    def test_top_agents(self):
        p = CapabilityProfiler()
        p.register_agent("claude", capabilities=["coding"], initial_proficiency={"coding": 0.9})
        p.register_agent("gemini", capabilities=["coding"], initial_proficiency={"coding": 0.7})
        p.register_agent("ollama", capabilities=["coding"], initial_proficiency={"coding": 0.5})
        top = p.top_agents("coding", limit=2)
        assert len(top) == 2
        assert top[0] == ("claude", 0.9)
        assert top[1] == ("gemini", 0.7)

    def test_top_agents_no_capability(self):
        p = CapabilityProfiler()
        p.register_agent("claude", capabilities=["coding"])
        top = p.top_agents("missing")
        assert top == []

    def test_get_proficiency(self):
        p = CapabilityProfiler()
        p.register_agent("claude", capabilities=["coding"], initial_proficiency={"coding": 0.85})
        assert p.get_proficiency("claude", "coding") == 0.85

    def test_get_proficiency_unknown_agent(self):
        p = CapabilityProfiler()
        assert p.get_proficiency("unknown", "coding") == 0.0

    def test_get_proficiency_unknown_capability(self):
        p = CapabilityProfiler()
        p.register_agent("claude")
        assert p.get_proficiency("claude", "missing") == 0.0


# =============================================================================
# State Management Tests
# =============================================================================


class TestStateManagement:
    """Test state management."""

    def test_clear(self):
        p = CapabilityProfiler()
        p.register_agent("claude", capabilities=["coding"])
        p.register_agent("gemini", capabilities=["research"])
        p.clear()
        assert p.agent_count == 0

    def test_remove_agent(self):
        p = CapabilityProfiler()
        p.register_agent("claude")
        p.register_agent("gemini")
        assert p.remove_agent("claude") is True
        assert p.agent_count == 1

    def test_remove_agent_nonexistent(self):
        p = CapabilityProfiler()
        assert p.remove_agent("missing") is False

    def test_agent_count(self):
        p = CapabilityProfiler()
        assert p.agent_count == 0
        p.register_agent("claude")
        assert p.agent_count == 1
        p.register_agent("gemini")
        assert p.agent_count == 2

    def test_to_dict(self):
        p = CapabilityProfiler()
        p.register_agent("claude", capabilities=["coding"])
        d = p.to_dict()
        assert d["agent_count"] == 1
        assert d["learning_rate"] == LEARNING_RATE
        assert "claude" in d["profiles"]

    def test_to_dict_empty(self):
        p = CapabilityProfiler()
        d = p.to_dict()
        assert d["agent_count"] == 0
        assert d["profiles"] == {}


# =============================================================================
# Constants Tests
# =============================================================================


class TestConstants:
    """Test module constants."""

    def test_known_capabilities_populated(self):
        assert len(KNOWN_CAPABILITIES) >= 20

    def test_known_capabilities_has_coding(self):
        assert "coding" in KNOWN_CAPABILITIES

    def test_known_capabilities_has_research(self):
        assert "research" in KNOWN_CAPABILITIES

    def test_default_proficiency(self):
        assert DEFAULT_PROFICIENCY == 0.5

    def test_learning_rate(self):
        assert 0.0 < LEARNING_RATE < 1.0


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_agents_package(self):
        from core.foundation.agents import (
            KNOWN_CAPABILITIES,
            AgentProfile,
            CapabilityProfiler,
            CapabilityRecord,
            MatchResult,
        )

        assert all([CapabilityProfiler, AgentProfile, CapabilityRecord, MatchResult, KNOWN_CAPABILITIES])

    def test_from_module(self):
        from core.foundation.agents.capability_profiler import (
            KNOWN_CAPABILITIES,
            AgentProfile,
            CapabilityProfiler,
            CapabilityRecord,
            MatchResult,
        )

        assert all([CapabilityProfiler, AgentProfile, CapabilityRecord, MatchResult])
        assert len(KNOWN_CAPABILITIES) >= 20


# =============================================================================
# Singleton Tests
# =============================================================================


class TestSingleton:
    """Test singleton pattern."""

    def test_get_returns_same(self):
        reset_capability_profiler()
        p1 = get_capability_profiler()
        p2 = get_capability_profiler()
        assert p1 is p2

    def test_reset_creates_new(self):
        reset_capability_profiler()
        p1 = get_capability_profiler()
        reset_capability_profiler()
        p2 = get_capability_profiler()
        assert p1 is not p2
