"""
Tests for V12.4 Swarm Negotiation Tracker.

Validates:
- NegotiationTurn to_dict
- NegotiationRecord to_dict
- NegotiationStats to_dict / convergence_rate property
- Recording negotiations
- Convergence rate calculation
- Mode proposal/agreement rankings
- Queries (recent, failed, by domain)
- Bounded history
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.intelligence.swarm.negotiation_tracker import (
    MAX_NEGOTIATIONS,
    NegotiationRecord,
    NegotiationStats,
    NegotiationTracker,
    NegotiationTurn,
    get_negotiation_tracker,
    reset_negotiation_tracker,
)

# =============================================================================
# NegotiationTurn Tests
# =============================================================================


class TestNegotiationTurn:
    """Test NegotiationTurn dataclass."""

    def test_basic(self):
        t = NegotiationTurn(
            turn_number=1, agent_id="claude", proposed_mode="PARALLEL", reasoning="Independent subtasks"
        )
        assert t.agent_id == "claude"

    def test_to_dict(self):
        t = NegotiationTurn(turn_number=1, agent_id="claude", proposed_mode="PARALLEL")
        d = t.to_dict()
        assert d["agent_id"] == "claude"
        assert d["proposed_mode"] == "PARALLEL"


# =============================================================================
# NegotiationRecord Tests
# =============================================================================


class TestNegotiationRecord:
    """Test NegotiationRecord dataclass."""

    def test_to_dict(self):
        r = NegotiationRecord(
            negotiation_id="neg_000001",
            task_domain="coding",
            initial_mode="PARALLEL",
            final_mode="LEAD_SUPPORT",
            turn_count=3,
            converged=True,
        )
        d = r.to_dict()
        assert d["negotiation_id"] == "neg_000001"
        assert d["converged"] is True


# =============================================================================
# NegotiationStats Tests
# =============================================================================


class TestNegotiationStats:
    """Test NegotiationStats dataclass."""

    def test_convergence_rate(self):
        s = NegotiationStats(total_negotiations=10, converged_count=8, failed_count=2)
        assert abs(s.convergence_rate - 0.8) < 0.01

    def test_convergence_rate_zero(self):
        s = NegotiationStats()
        assert s.convergence_rate == 0.0

    def test_to_dict(self):
        s = NegotiationStats(total_negotiations=20, converged_count=15)
        d = s.to_dict()
        assert "convergence_rate" in d


# =============================================================================
# Recording Tests
# =============================================================================


class TestRecording:
    """Test negotiation recording."""

    def test_record_basic(self):
        t = NegotiationTracker()
        r = t.record_negotiation(
            task_domain="coding",
            initial_mode="PARALLEL",
            final_mode="LEAD_SUPPORT",
            turn_count=3,
            converged=True,
        )
        assert r.negotiation_id == "neg_000001"
        assert t.negotiation_count == 1

    def test_record_failed(self):
        t = NegotiationTracker()
        r = t.record_negotiation(
            task_domain="security",
            initial_mode="RED_BLUE",
            final_mode="",
            turn_count=4,
            converged=False,
        )
        assert r.converged is False

    def test_auto_incrementing_ids(self):
        t = NegotiationTracker()
        r1 = t.record_negotiation(task_domain="a", initial_mode="PARALLEL", final_mode="PARALLEL")
        r2 = t.record_negotiation(task_domain="b", initial_mode="SEQUENTIAL", final_mode="SEQUENTIAL")
        assert r1.negotiation_id == "neg_000001"
        assert r2.negotiation_id == "neg_000002"

    def test_multiple_negotiations(self):
        t = NegotiationTracker()
        t.record_negotiation(task_domain="a", initial_mode="PARALLEL", final_mode="PARALLEL")
        t.record_negotiation(task_domain="b", initial_mode="SEQUENTIAL", final_mode="SEQUENTIAL")
        t.record_negotiation(task_domain="c", initial_mode="RED_BLUE", final_mode="RED_BLUE")
        assert t.negotiation_count == 3


# =============================================================================
# Convergence Rate Tests
# =============================================================================


class TestConvergenceRate:
    """Test convergence rate calculation."""

    def test_all_converged(self):
        t = NegotiationTracker()
        for _ in range(5):
            t.record_negotiation(initial_mode="P", final_mode="P", converged=True)
        assert abs(t.get_convergence_rate() - 1.0) < 0.01

    def test_mixed(self):
        t = NegotiationTracker()
        for _ in range(3):
            t.record_negotiation(initial_mode="P", final_mode="P", converged=True)
        for _ in range(2):
            t.record_negotiation(initial_mode="P", final_mode="", converged=False)
        assert abs(t.get_convergence_rate() - 0.6) < 0.01

    def test_empty(self):
        t = NegotiationTracker()
        assert t.get_convergence_rate() == 0.0


# =============================================================================
# Ranking Tests
# =============================================================================


class TestRankings:
    """Test mode proposal and agreement rankings."""

    def test_proposal_ranking(self):
        t = NegotiationTracker()
        t.record_negotiation(initial_mode="PARALLEL", final_mode="PARALLEL")
        t.record_negotiation(initial_mode="PARALLEL", final_mode="LEAD_SUPPORT")
        t.record_negotiation(initial_mode="RED_BLUE", final_mode="RED_BLUE")
        ranking = t.get_mode_proposal_ranking()
        assert ranking[0][0] == "PARALLEL"  # 2 proposals
        assert ranking[0][1] == 2

    def test_agreement_ranking(self):
        t = NegotiationTracker()
        t.record_negotiation(initial_mode="P", final_mode="PARALLEL", converged=True)
        t.record_negotiation(initial_mode="P", final_mode="PARALLEL", converged=True)
        t.record_negotiation(initial_mode="P", final_mode="SEQUENTIAL", converged=True)
        t.record_negotiation(initial_mode="P", final_mode="", converged=False)  # not counted
        ranking = t.get_mode_agreement_ranking()
        assert ranking[0][0] == "PARALLEL"  # 2 agreements
        assert ranking[0][1] == 2


# =============================================================================
# Query Tests
# =============================================================================


class TestQueries:
    """Test query methods."""

    def test_recent_negotiations(self):
        t = NegotiationTracker()
        for i in range(5):
            t.record_negotiation(task_domain=f"d_{i}", initial_mode="P", final_mode="P")
        recent = t.get_recent_negotiations(limit=3)
        assert len(recent) == 3

    def test_failed_negotiations(self):
        t = NegotiationTracker()
        t.record_negotiation(initial_mode="P", final_mode="P", converged=True)
        t.record_negotiation(initial_mode="P", final_mode="", converged=False)
        t.record_negotiation(initial_mode="R", final_mode="", converged=False)
        failed = t.get_failed_negotiations()
        assert len(failed) == 2

    def test_by_domain(self):
        t = NegotiationTracker()
        t.record_negotiation(task_domain="coding", initial_mode="P", final_mode="P")
        t.record_negotiation(task_domain="security", initial_mode="R", final_mode="R")
        t.record_negotiation(task_domain="coding", initial_mode="S", final_mode="S")
        results = t.get_negotiations_by_domain("coding")
        assert len(results) == 2


# =============================================================================
# Bounded History Tests
# =============================================================================


class TestBoundedHistory:
    """Test bounded negotiation history."""

    def test_eviction(self):
        t = NegotiationTracker(max_negotiations=5)
        for i in range(10):
            t.record_negotiation(task_domain=f"d_{i}", initial_mode="P", final_mode="P")
        assert t.negotiation_count == 5


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test tracker statistics."""

    def test_initial_stats(self):
        t = NegotiationTracker()
        stats = t.get_stats()
        assert stats.total_negotiations == 0

    def test_stats_after_recording(self):
        t = NegotiationTracker()
        t.record_negotiation(
            initial_mode="PARALLEL", final_mode="PARALLEL", turn_count=2, duration_ms=100, converged=True
        )
        t.record_negotiation(initial_mode="RED_BLUE", final_mode="", turn_count=4, duration_ms=200, converged=False)
        stats = t.get_stats()
        assert stats.total_negotiations == 2
        assert stats.converged_count == 1
        assert stats.failed_count == 1

    def test_stats_to_dict(self):
        t = NegotiationTracker()
        d = t.get_stats().to_dict()
        assert "total_negotiations" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_count(self):
        t = NegotiationTracker()
        t.record_negotiation(initial_mode="P", final_mode="P")
        assert t.negotiation_count == 1

    def test_clear(self):
        t = NegotiationTracker()
        t.record_negotiation(initial_mode="P", final_mode="P")
        t.clear()
        assert t.negotiation_count == 0
        assert t.get_convergence_rate() == 0.0

    def test_to_dict(self):
        t = NegotiationTracker()
        t.record_negotiation(initial_mode="P", final_mode="P")
        d = t.to_dict()
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global negotiation tracker."""

    def test_get(self):
        reset_negotiation_tracker()
        t = get_negotiation_tracker()
        assert isinstance(t, NegotiationTracker)

    def test_singleton(self):
        reset_negotiation_tracker()
        t1 = get_negotiation_tracker()
        t2 = get_negotiation_tracker()
        assert t1 is t2

    def test_reset(self):
        reset_negotiation_tracker()
        t1 = get_negotiation_tracker()
        reset_negotiation_tracker()
        t2 = get_negotiation_tracker()
        assert t1 is not t2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_swarm_package(self):
        from core.intelligence.swarm import (
            NegotiationRecord,
            NegotiationStats,
            NegotiationTracker,
            NegotiationTurn,
            get_negotiation_tracker,
            reset_negotiation_tracker,
        )

        assert all(
            [
                NegotiationTracker,
                NegotiationTurn,
                NegotiationRecord,
                NegotiationStats,
                get_negotiation_tracker,
                reset_negotiation_tracker,
            ]
        )

    def test_constants(self):
        assert MAX_NEGOTIATIONS == 50000
