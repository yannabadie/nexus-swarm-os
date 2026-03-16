"""
Tests for V12.4 Agent Lifecycle Manager.

Validates:
- RetirementPolicy to_dict
- AgentHealthSnapshot properties and to_dict
- LifecycleEvent to_dict
- LifecycleStats to_dict
- Registration (register, unregister, list)
- Outcome recording and degradation detection
- Retirement (auto, manual, criteria)
- Reinstatement
- Replacement finding
- Event history
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.foundation.agents.agent_lifecycle import (
    DEFAULT_MAX_CONSECUTIVE_FAILURES,
    DEFAULT_MIN_QUALITY,
    MAX_AGENTS,
    AgentHealthSnapshot,
    AgentLifecycleManager,
    LifecycleEvent,
    LifecycleStats,
    RetirementPolicy,
    get_lifecycle_manager,
    reset_lifecycle_manager,
)

# =============================================================================
# RetirementPolicy Tests
# =============================================================================


class TestRetirementPolicy:
    """Test RetirementPolicy dataclass."""

    def test_defaults(self):
        p = RetirementPolicy()
        assert p.min_quality == DEFAULT_MIN_QUALITY
        assert p.max_consecutive_failures == DEFAULT_MAX_CONSECUTIVE_FAILURES

    def test_to_dict(self):
        p = RetirementPolicy(min_quality=0.5)
        d = p.to_dict()
        assert d["min_quality"] == 0.5
        assert "max_consecutive_failures" in d


# =============================================================================
# AgentHealthSnapshot Tests
# =============================================================================


class TestAgentHealthSnapshot:
    """Test AgentHealthSnapshot dataclass."""

    def test_success_rate_zero(self):
        s = AgentHealthSnapshot(agent_id="a")
        assert s.success_rate == 0.0

    def test_success_rate(self):
        s = AgentHealthSnapshot(agent_id="a", total_tasks=10, successes=7, failures=3)
        assert s.success_rate == 0.7

    def test_to_dict(self):
        s = AgentHealthSnapshot(agent_id="claude", total_tasks=5, successes=4)
        d = s.to_dict()
        assert d["agent_id"] == "claude"
        assert d["success_rate"] == 0.8


# =============================================================================
# LifecycleEvent Tests
# =============================================================================


class TestLifecycleEvent:
    """Test LifecycleEvent dataclass."""

    def test_basic(self):
        e = LifecycleEvent(agent_id="claude", event_type="registered")
        assert e.agent_id == "claude"
        assert e.timestamp > 0

    def test_to_dict(self):
        e = LifecycleEvent(agent_id="a", event_type="retired", details="Low quality")
        d = e.to_dict()
        assert d["event_type"] == "retired"
        assert d["details"] == "Low quality"


# =============================================================================
# LifecycleStats Tests
# =============================================================================


class TestLifecycleStats:
    """Test LifecycleStats dataclass."""

    def test_to_dict(self):
        s = LifecycleStats(
            total_agents=5,
            active_agents=3,
            degraded_agents=1,
            retired_agents=1,
            total_events=10,
            total_retirements=1,
        )
        d = s.to_dict()
        assert d["active_agents"] == 3


# =============================================================================
# Registration Tests
# =============================================================================


class TestRegistration:
    """Test agent registration."""

    def test_register(self):
        m = AgentLifecycleManager()
        assert m.register("claude") is True
        assert m.agent_count == 1

    def test_register_duplicate(self):
        m = AgentLifecycleManager()
        m.register("claude")
        assert m.register("claude") is False

    def test_register_with_capabilities(self):
        m = AgentLifecycleManager()
        m.register("claude", capabilities=["coding", "debugging"])
        snap = m.get_health("claude")
        assert snap.capabilities == ["coding", "debugging"]

    def test_unregister(self):
        m = AgentLifecycleManager()
        m.register("claude")
        assert m.unregister("claude") is True
        assert m.agent_count == 0

    def test_unregister_not_found(self):
        m = AgentLifecycleManager()
        assert m.unregister("missing") is False

    def test_is_registered(self):
        m = AgentLifecycleManager()
        m.register("claude")
        assert m.is_registered("claude") is True
        assert m.is_registered("missing") is False

    def test_list_agents(self):
        m = AgentLifecycleManager()
        m.register("gemini")
        m.register("claude")
        assert m.list_agents() == ["claude", "gemini"]

    def test_register_creates_event(self):
        m = AgentLifecycleManager()
        m.register("claude")
        events = m.get_events(event_type="registered")
        assert len(events) == 1
        assert events[0].agent_id == "claude"


# =============================================================================
# Outcome Recording Tests
# =============================================================================


class TestOutcomeRecording:
    """Test outcome recording and quality tracking."""

    def test_record_success(self):
        m = AgentLifecycleManager()
        m.register("claude")
        assert m.record_outcome("claude", success=True, quality=0.9) is True
        snap = m.get_health("claude")
        assert snap.total_tasks == 1
        assert snap.successes == 1
        assert snap.consecutive_failures == 0

    def test_record_failure(self):
        m = AgentLifecycleManager()
        m.register("claude")
        m.record_outcome("claude", success=False)
        snap = m.get_health("claude")
        assert snap.failures == 1
        assert snap.consecutive_failures == 1

    def test_record_not_found(self):
        m = AgentLifecycleManager()
        assert m.record_outcome("missing", success=True) is False

    def test_consecutive_failures_reset_on_success(self):
        m = AgentLifecycleManager()
        m.register("claude")
        m.record_outcome("claude", success=False)
        m.record_outcome("claude", success=False)
        m.record_outcome("claude", success=True, quality=0.8)
        snap = m.get_health("claude")
        assert snap.consecutive_failures == 0

    def test_average_quality(self):
        m = AgentLifecycleManager()
        m.register("claude")
        m.record_outcome("claude", success=True, quality=0.8)
        m.record_outcome("claude", success=True, quality=0.6)
        snap = m.get_health("claude")
        assert abs(snap.average_quality - 0.7) < 0.01

    def test_quality_window_bounded(self):
        policy = RetirementPolicy(observation_window=3)
        m = AgentLifecycleManager(policy=policy)
        m.register("claude")
        m.record_outcome("claude", success=True, quality=0.2)
        m.record_outcome("claude", success=True, quality=0.2)
        m.record_outcome("claude", success=True, quality=0.2)
        # Now push old values out
        m.record_outcome("claude", success=True, quality=0.9)
        m.record_outcome("claude", success=True, quality=0.9)
        m.record_outcome("claude", success=True, quality=0.9)
        snap = m.get_health("claude")
        assert snap.average_quality == 0.9


# =============================================================================
# Degradation Tests
# =============================================================================


class TestDegradation:
    """Test degradation detection."""

    def test_degraded_on_consecutive_failures(self):
        policy = RetirementPolicy(max_consecutive_failures=4)
        m = AgentLifecycleManager(policy=policy)
        m.register("claude")
        m.record_outcome("claude", success=False)
        m.record_outcome("claude", success=False)
        snap = m.get_health("claude")
        assert snap.is_degraded is True

    def test_recovery_from_degradation(self):
        policy = RetirementPolicy(max_consecutive_failures=4, min_observations=1)
        m = AgentLifecycleManager(policy=policy)
        m.register("claude")
        # Degrade
        m.record_outcome("claude", success=False)
        m.record_outcome("claude", success=False)
        assert m.get_health("claude").is_degraded is True
        # Recover with good outcomes
        for _ in range(5):
            m.record_outcome("claude", success=True, quality=0.95)
        snap = m.get_health("claude")
        assert snap.is_degraded is False

    def test_degradation_event_emitted(self):
        policy = RetirementPolicy(max_consecutive_failures=4)
        m = AgentLifecycleManager(policy=policy)
        m.register("claude")
        m.record_outcome("claude", success=False)
        m.record_outcome("claude", success=False)
        events = m.get_events(event_type="degraded")
        assert len(events) == 1

    def test_recovery_event_emitted(self):
        policy = RetirementPolicy(max_consecutive_failures=6, min_observations=1)
        m = AgentLifecycleManager(policy=policy)
        m.register("claude")
        m.record_outcome("claude", success=False)
        m.record_outcome("claude", success=False)
        m.record_outcome("claude", success=False)
        # Now recover
        for _ in range(10):
            m.record_outcome("claude", success=True, quality=0.95)
        events = m.get_events(event_type="recovered")
        assert len(events) >= 1


# =============================================================================
# Retirement Tests
# =============================================================================


class TestRetirement:
    """Test retirement logic."""

    def test_should_retire_consecutive_failures(self):
        policy = RetirementPolicy(max_consecutive_failures=3, min_observations=3)
        m = AgentLifecycleManager(policy=policy)
        m.register("claude")
        m.record_outcome("claude", success=False)
        m.record_outcome("claude", success=False)
        m.record_outcome("claude", success=False)
        assert m.should_retire("claude") is True

    def test_should_retire_low_quality(self):
        policy = RetirementPolicy(min_quality=0.3, min_observations=5)
        m = AgentLifecycleManager(policy=policy)
        m.register("claude")
        for _ in range(5):
            m.record_outcome("claude", success=True, quality=0.1)
        assert m.should_retire("claude") is True

    def test_should_not_retire_insufficient_observations(self):
        policy = RetirementPolicy(min_quality=0.3, min_observations=10)
        m = AgentLifecycleManager(policy=policy)
        m.register("claude")
        for _ in range(3):
            m.record_outcome("claude", success=True, quality=0.1)
        assert m.should_retire("claude") is False

    def test_manual_retire(self):
        m = AgentLifecycleManager()
        m.register("claude")
        assert m.retire("claude", reason="Replaced by v2") is True
        snap = m.get_health("claude")
        assert snap.is_retired is True
        assert snap.retirement_reason == "Replaced by v2"

    def test_manual_retire_not_found(self):
        m = AgentLifecycleManager()
        assert m.retire("missing") is False

    def test_manual_retire_already_retired(self):
        m = AgentLifecycleManager()
        m.register("claude")
        m.retire("claude")
        assert m.retire("claude") is False

    def test_apply_retirements(self):
        policy = RetirementPolicy(max_consecutive_failures=3, min_observations=3)
        m = AgentLifecycleManager(policy=policy)
        m.register("claude")
        m.register("gemini")
        # Claude fails enough to retire
        for _ in range(3):
            m.record_outcome("claude", success=False)
        # Gemini is fine
        for _ in range(3):
            m.record_outcome("gemini", success=True, quality=0.9)
        retired = m.apply_retirements()
        assert "claude" in retired
        assert "gemini" not in retired

    def test_apply_retirements_sets_reason(self):
        policy = RetirementPolicy(max_consecutive_failures=3, min_observations=3)
        m = AgentLifecycleManager(policy=policy)
        m.register("claude")
        for _ in range(3):
            m.record_outcome("claude", success=False)
        m.apply_retirements()
        snap = m.get_health("claude")
        assert "Consecutive failures" in snap.retirement_reason

    def test_retirement_event(self):
        m = AgentLifecycleManager()
        m.register("claude")
        m.retire("claude", reason="test")
        events = m.get_events(event_type="retired")
        assert len(events) == 1


# =============================================================================
# Reinstatement Tests
# =============================================================================


class TestReinstatement:
    """Test agent reinstatement."""

    def test_reinstate(self):
        m = AgentLifecycleManager()
        m.register("claude")
        m.retire("claude")
        assert m.reinstate("claude") is True
        snap = m.get_health("claude")
        assert snap.is_retired is False
        assert snap.consecutive_failures == 0

    def test_reinstate_not_retired(self):
        m = AgentLifecycleManager()
        m.register("claude")
        assert m.reinstate("claude") is False

    def test_reinstate_not_found(self):
        m = AgentLifecycleManager()
        assert m.reinstate("missing") is False

    def test_reinstate_event(self):
        m = AgentLifecycleManager()
        m.register("claude")
        m.retire("claude")
        m.reinstate("claude")
        events = m.get_events(event_type="reinstated")
        assert len(events) == 1


# =============================================================================
# Replacement Tests
# =============================================================================


class TestReplacement:
    """Test replacement finding."""

    def test_find_replacement(self):
        m = AgentLifecycleManager()
        m.register("claude", capabilities=["coding", "debugging"])
        m.register("gemini", capabilities=["coding", "research"])
        m.record_outcome("gemini", success=True, quality=0.9)
        replacement = m.find_replacement("claude")
        assert replacement == "gemini"

    def test_no_replacement_no_overlap(self):
        m = AgentLifecycleManager()
        m.register("claude", capabilities=["coding"])
        m.register("gemini", capabilities=["research"])
        replacement = m.find_replacement("claude")
        assert replacement is None

    def test_no_replacement_for_unknown(self):
        m = AgentLifecycleManager()
        assert m.find_replacement("missing") is None

    def test_skip_retired_as_replacement(self):
        m = AgentLifecycleManager()
        m.register("claude", capabilities=["coding"])
        m.register("gemini", capabilities=["coding"])
        m.register("agent3", capabilities=["coding"])
        m.retire("gemini")
        m.record_outcome("agent3", success=True, quality=0.8)
        replacement = m.find_replacement("claude")
        assert replacement == "agent3"

    def test_best_quality_replacement(self):
        m = AgentLifecycleManager()
        m.register("claude", capabilities=["coding", "debugging"])
        m.register("agent1", capabilities=["coding"])
        m.register("agent2", capabilities=["coding", "debugging"])
        m.record_outcome("agent1", success=True, quality=0.5)
        m.record_outcome("agent2", success=True, quality=0.9)
        replacement = m.find_replacement("claude")
        assert replacement == "agent2"


# =============================================================================
# Query Tests
# =============================================================================


class TestQueries:
    """Test query methods."""

    def test_get_health(self):
        m = AgentLifecycleManager()
        m.register("claude")
        snap = m.get_health("claude")
        assert snap is not None
        assert snap.agent_id == "claude"

    def test_get_health_not_found(self):
        m = AgentLifecycleManager()
        assert m.get_health("missing") is None

    def test_get_active_agents(self):
        m = AgentLifecycleManager()
        m.register("claude")
        m.register("gemini")
        m.retire("gemini")
        assert m.get_active_agents() == ["claude"]

    def test_get_degraded_agents(self):
        policy = RetirementPolicy(max_consecutive_failures=6)
        m = AgentLifecycleManager(policy=policy)
        m.register("claude")
        m.register("gemini")
        m.record_outcome("claude", success=False)
        m.record_outcome("claude", success=False)
        m.record_outcome("claude", success=False)
        assert "claude" in m.get_degraded_agents()
        assert "gemini" not in m.get_degraded_agents()

    def test_get_retired_agents(self):
        m = AgentLifecycleManager()
        m.register("claude")
        m.register("gemini")
        m.retire("claude")
        assert m.get_retired_agents() == ["claude"]

    def test_get_events_with_filters(self):
        m = AgentLifecycleManager()
        m.register("claude")
        m.register("gemini")
        events = m.get_events(agent_id="claude")
        assert all(e.agent_id == "claude" for e in events)

    def test_get_events_with_limit(self):
        m = AgentLifecycleManager()
        for i in range(10):
            m.register(f"agent{i}")
        events = m.get_events(limit=3)
        assert len(events) == 3


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test lifecycle statistics."""

    def test_initial_stats(self):
        m = AgentLifecycleManager()
        stats = m.get_stats()
        assert stats.total_agents == 0
        assert stats.total_retirements == 0

    def test_stats_after_work(self):
        m = AgentLifecycleManager()
        m.register("claude")
        m.register("gemini")
        m.retire("claude")
        stats = m.get_stats()
        assert stats.total_agents == 2
        assert stats.active_agents == 1
        assert stats.retired_agents == 1
        assert stats.total_retirements == 1

    def test_stats_to_dict(self):
        m = AgentLifecycleManager()
        d = m.get_stats().to_dict()
        assert "total_agents" in d
        assert "total_retirements" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_agent_count(self):
        m = AgentLifecycleManager()
        m.register("a")
        m.register("b")
        assert m.agent_count == 2

    def test_clear(self):
        m = AgentLifecycleManager()
        m.register("claude")
        m.record_outcome("claude", success=True)
        m.clear()
        assert m.agent_count == 0
        assert m.get_stats().total_events == 0

    def test_set_policy(self):
        m = AgentLifecycleManager()
        new_policy = RetirementPolicy(min_quality=0.5)
        m.set_policy(new_policy)
        assert m.policy.min_quality == 0.5

    def test_to_dict(self):
        m = AgentLifecycleManager()
        m.register("claude")
        d = m.to_dict()
        assert d["agent_count"] == 1
        assert "policy" in d
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global lifecycle manager."""

    def test_get(self):
        reset_lifecycle_manager()
        mgr = get_lifecycle_manager()
        assert isinstance(mgr, AgentLifecycleManager)

    def test_singleton(self):
        reset_lifecycle_manager()
        m1 = get_lifecycle_manager()
        m2 = get_lifecycle_manager()
        assert m1 is m2

    def test_reset(self):
        reset_lifecycle_manager()
        m1 = get_lifecycle_manager()
        reset_lifecycle_manager()
        m2 = get_lifecycle_manager()
        assert m1 is not m2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_agents_package(self):
        from core.foundation.agents import (
            AgentHealthSnapshot,
            AgentLifecycleManager,
            LifecycleEvent,
            LifecycleStats,
            RetirementPolicy,
            get_lifecycle_manager,
            reset_lifecycle_manager,
        )

        assert all(
            [
                AgentLifecycleManager,
                RetirementPolicy,
                AgentHealthSnapshot,
                LifecycleEvent,
                LifecycleStats,
                get_lifecycle_manager,
                reset_lifecycle_manager,
            ]
        )

    def test_constants(self):
        from core.foundation.agents.agent_lifecycle import (
            DEFAULT_MIN_QUALITY,
        )

        assert DEFAULT_MIN_QUALITY == 0.3
        assert MAX_AGENTS == 5000
