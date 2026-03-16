"""
Tests for V12.4 Phase Coordinator.

Validates:
- PhaseTransition to_dict
- PhaseState properties and to_dict
- TransitionResult to_dict
- CoordinatorStats to_dict
- Session lifecycle (start, end)
- Valid transitions through all phases
- Invalid transition rejection
- Phase skipping
- Queries (current, state, transitions, next, can_transition)
- Completed phase tracking
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.intelligence.hive_mind.phase_coordinator import (
    PHASE_ORDER,
    VALID_TRANSITIONS,
    PhaseCoordinator,
    PhaseState,
    PhaseTransition,
    TransitionResult,
    get_phase_coordinator,
    reset_phase_coordinator,
)

# =============================================================================
# PhaseTransition Tests
# =============================================================================


class TestPhaseTransition:
    """Test PhaseTransition dataclass."""

    def test_basic(self):
        t = PhaseTransition(from_phase="idle", to_phase="analysis", session_id="s1")
        assert t.from_phase == "idle"
        assert t.to_phase == "analysis"

    def test_auto_timestamp(self):
        t = PhaseTransition(from_phase="a", to_phase="b", session_id="s")
        assert t.timestamp > 0

    def test_to_dict(self):
        t = PhaseTransition(from_phase="a", to_phase="b", session_id="s", reason="ready")
        d = t.to_dict()
        assert d["from"] == "a"
        assert d["to"] == "b"
        assert d["reason"] == "ready"


# =============================================================================
# PhaseState Tests
# =============================================================================


class TestPhaseState:
    """Test PhaseState dataclass."""

    def test_defaults(self):
        s = PhaseState(session_id="s1")
        assert s.current_phase == "idle"
        assert s.completed_phases == []

    def test_to_dict(self):
        s = PhaseState(session_id="s1", current_phase="analysis")
        d = s.to_dict()
        assert d["session_id"] == "s1"
        assert d["current_phase"] == "analysis"


# =============================================================================
# TransitionResult Tests
# =============================================================================


class TestTransitionResult:
    """Test TransitionResult dataclass."""

    def test_success(self):
        r = TransitionResult(success=True, from_phase="idle", to_phase="analysis")
        assert r.success is True

    def test_failure(self):
        r = TransitionResult(success=False, error="Invalid")
        assert r.success is False

    def test_to_dict(self):
        r = TransitionResult(success=True, from_phase="a", to_phase="b")
        d = r.to_dict()
        assert d["success"] is True


# =============================================================================
# Session Lifecycle Tests
# =============================================================================


class TestSessionLifecycle:
    """Test session management."""

    def test_start_session(self):
        c = PhaseCoordinator()
        state = c.start_session("s1")
        assert state.current_phase == "idle"
        assert c.session_count == 1

    def test_end_session(self):
        c = PhaseCoordinator()
        c.start_session("s1")
        assert c.end_session("s1") is True
        assert c.session_count == 0

    def test_end_session_not_found(self):
        c = PhaseCoordinator()
        assert c.end_session("missing") is False


# =============================================================================
# Transition Tests
# =============================================================================


class TestTransitions:
    """Test phase transitions."""

    def test_idle_to_analysis(self):
        c = PhaseCoordinator()
        c.start_session("s1")
        result = c.transition("s1", "analysis")
        assert result.success is True
        assert c.current_phase("s1") == "analysis"

    def test_full_happy_path(self):
        c = PhaseCoordinator()
        c.start_session("s1")
        assert c.transition("s1", "analysis").success
        assert c.transition("s1", "debate").success
        assert c.transition("s1", "architecture").success
        assert c.transition("s1", "execution").success
        assert c.transition("s1", "consolidation").success
        assert c.current_phase("s1") == "consolidation"

    def test_skip_debate(self):
        c = PhaseCoordinator()
        c.start_session("s1")
        c.transition("s1", "analysis")
        result = c.transition("s1", "architecture")
        assert result.success is True

    def test_skip_to_execution(self):
        c = PhaseCoordinator()
        c.start_session("s1")
        c.transition("s1", "analysis")
        result = c.transition("s1", "execution")
        assert result.success is True

    def test_error_path(self):
        c = PhaseCoordinator()
        c.start_session("s1")
        c.transition("s1", "analysis")
        c.transition("s1", "execution")
        c.transition("s1", "diagnosis")
        c.transition("s1", "retry")
        result = c.transition("s1", "execution")
        assert result.success is True

    def test_invalid_transition(self):
        c = PhaseCoordinator()
        c.start_session("s1")
        result = c.transition("s1", "execution")
        assert result.success is False
        assert "Invalid transition" in result.error

    def test_session_not_found(self):
        c = PhaseCoordinator()
        result = c.transition("missing", "analysis")
        assert result.success is False
        assert "not found" in result.error

    def test_transition_reason(self):
        c = PhaseCoordinator()
        c.start_session("s1")
        c.transition("s1", "analysis", reason="starting task")
        transitions = c.get_transitions("s1")
        assert transitions[0].reason == "starting task"


# =============================================================================
# Query Tests
# =============================================================================


class TestQueries:
    """Test phase queries."""

    def test_current_phase(self):
        c = PhaseCoordinator()
        c.start_session("s1")
        assert c.current_phase("s1") == "idle"

    def test_current_phase_not_found(self):
        c = PhaseCoordinator()
        assert c.current_phase("missing") is None

    def test_get_state(self):
        c = PhaseCoordinator()
        c.start_session("s1")
        state = c.get_state("s1")
        assert state is not None
        assert state.session_id == "s1"

    def test_get_transitions(self):
        c = PhaseCoordinator()
        c.start_session("s1")
        c.transition("s1", "analysis")
        c.transition("s1", "debate")
        transitions = c.get_transitions("s1")
        assert len(transitions) == 2

    def test_get_transitions_empty(self):
        c = PhaseCoordinator()
        assert c.get_transitions("missing") == []

    def test_next_phases(self):
        c = PhaseCoordinator()
        c.start_session("s1")
        nexts = c.next_phases("s1")
        assert "analysis" in nexts

    def test_next_phases_from_analysis(self):
        c = PhaseCoordinator()
        c.start_session("s1")
        c.transition("s1", "analysis")
        nexts = c.next_phases("s1")
        assert "debate" in nexts
        assert "architecture" in nexts
        assert "execution" in nexts

    def test_can_transition(self):
        c = PhaseCoordinator()
        c.start_session("s1")
        assert c.can_transition("s1", "analysis") is True
        assert c.can_transition("s1", "execution") is False

    def test_can_skip(self):
        c = PhaseCoordinator()
        c.start_session("s1")
        c.transition("s1", "analysis")
        assert c.can_skip("s1", "debate") is True
        assert c.can_skip("s1", "analysis") is False  # Not skippable

    def test_has_completed(self):
        c = PhaseCoordinator()
        c.start_session("s1")
        c.transition("s1", "analysis")
        c.transition("s1", "execution")
        assert c.has_completed("s1", "analysis") is True
        assert c.has_completed("s1", "debate") is False


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test coordinator statistics."""

    def test_initial_stats(self):
        c = PhaseCoordinator()
        stats = c.get_stats()
        assert stats.active_sessions == 0

    def test_stats_after_work(self):
        c = PhaseCoordinator()
        c.start_session("s1")
        c.transition("s1", "analysis")
        c.transition("s1", "execution")
        stats = c.get_stats()
        assert stats.active_sessions == 1
        assert stats.total_transitions == 2
        assert "execution" in stats.phase_distribution

    def test_stats_to_dict(self):
        c = PhaseCoordinator()
        d = c.get_stats().to_dict()
        assert "active_sessions" in d
        assert "phase_distribution" in d


# =============================================================================
# Constants Tests
# =============================================================================


class TestConstants:
    """Test constants."""

    def test_phase_order(self):
        assert len(PHASE_ORDER) == 7
        assert PHASE_ORDER[0] == "analysis"
        assert PHASE_ORDER[-1] == "consolidation"

    def test_valid_transitions_complete(self):
        assert "idle" in VALID_TRANSITIONS
        assert "consolidation" in VALID_TRANSITIONS


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_session_count(self):
        c = PhaseCoordinator()
        c.start_session("s1")
        c.start_session("s2")
        assert c.session_count == 2

    def test_clear(self):
        c = PhaseCoordinator()
        c.start_session("s1")
        c.clear()
        assert c.session_count == 0

    def test_to_dict(self):
        c = PhaseCoordinator()
        c.start_session("s1")
        d = c.to_dict()
        assert d["session_count"] == 1
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global phase coordinator."""

    def test_get(self):
        reset_phase_coordinator()
        coord = get_phase_coordinator()
        assert isinstance(coord, PhaseCoordinator)

    def test_singleton(self):
        reset_phase_coordinator()
        c1 = get_phase_coordinator()
        c2 = get_phase_coordinator()
        assert c1 is c2

    def test_reset(self):
        reset_phase_coordinator()
        c1 = get_phase_coordinator()
        reset_phase_coordinator()
        c2 = get_phase_coordinator()
        assert c1 is not c2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_hive_mind_package(self):
        from core.intelligence.hive_mind import (
            PhaseCoordinator,
            PhaseState,
            PhaseTransition,
            TransitionResult,
            get_phase_coordinator,
            reset_phase_coordinator,
        )

        assert all(
            [
                PhaseCoordinator,
                PhaseState,
                PhaseTransition,
                TransitionResult,
                get_phase_coordinator,
                reset_phase_coordinator,
            ]
        )

    def test_from_module(self):
        from core.intelligence.hive_mind.phase_coordinator import (
            PHASE_ORDER,
        )

        assert len(PHASE_ORDER) == 7
