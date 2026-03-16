"""
Tests for V12.4 Interaction Quality Tracker.

Validates:
- InteractionRecord to_dict
- InteractionTypeProfile to_dict / properties
- InteractionQualityStats to_dict
- Recording interactions
- Profile updates
- Queries (all profiles, recent, list types)
- Bounded history
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.security_pkg.interaction.interaction_quality_tracker import (
    MAX_INTERACTIONS,
    InteractionQualityStats,
    InteractionQualityTracker,
    InteractionRecord,
    InteractionTypeProfile,
    get_interaction_tracker,
    reset_interaction_tracker,
)

# =============================================================================
# InteractionRecord Tests
# =============================================================================


class TestInteractionRecord:
    """Test InteractionRecord dataclass."""

    def test_to_dict(self):
        r = InteractionRecord(interaction_id="ix_000001", interaction_type="ask", context="name")
        d = r.to_dict()
        assert d["interaction_type"] == "ask"
        assert d["context"] == "name"


# =============================================================================
# InteractionTypeProfile Tests
# =============================================================================


class TestInteractionTypeProfile:
    """Test InteractionTypeProfile dataclass."""

    def test_satisfaction_rate(self):
        p = InteractionTypeProfile(interaction_type="ask", total_interactions=10, satisfied_count=8)
        assert abs(p.satisfaction_rate - 0.8) < 0.01

    def test_satisfaction_rate_zero(self):
        p = InteractionTypeProfile(interaction_type="ask")
        assert p.satisfaction_rate == 0.0

    def test_avg_response(self):
        p = InteractionTypeProfile(interaction_type="ask", total_interactions=4, total_response_ms=4000.0)
        assert abs(p.avg_response_ms - 1000.0) < 0.01

    def test_avg_response_zero(self):
        p = InteractionTypeProfile(interaction_type="ask")
        assert p.avg_response_ms == 0.0

    def test_to_dict(self):
        p = InteractionTypeProfile(interaction_type="ask", total_interactions=5)
        d = p.to_dict()
        assert "satisfaction_rate" in d
        assert "avg_response_ms" in d


# =============================================================================
# InteractionQualityStats Tests
# =============================================================================


class TestInteractionQualityStats:
    """Test InteractionQualityStats dataclass."""

    def test_to_dict(self):
        s = InteractionQualityStats(total_interactions=20, unique_types=3)
        d = s.to_dict()
        assert d["total_interactions"] == 20


# =============================================================================
# Recording Tests
# =============================================================================


class TestRecording:
    """Test interaction recording."""

    def test_record_basic(self):
        t = InteractionQualityTracker()
        r = t.record_interaction("ask", user_response_ms=500)
        assert r.interaction_id == "ix_000001"
        assert t.interaction_count == 1

    def test_profile_updates(self):
        t = InteractionQualityTracker()
        t.record_interaction("ask", user_response_ms=500, satisfied=True)
        t.record_interaction("ask", user_response_ms=1000, satisfied=True)
        t.record_interaction("ask", satisfied=False)
        p = t.get_type_profile("ask")
        assert p is not None
        assert p.total_interactions == 3
        assert p.satisfied_count == 2

    def test_multiple_types(self):
        t = InteractionQualityTracker()
        t.record_interaction("ask")
        t.record_interaction("confirm")
        t.record_interaction("choose")
        assert len(t.get_all_profiles()) == 3


# =============================================================================
# Query Tests
# =============================================================================


class TestQueries:
    """Test query methods."""

    def test_get_profile_not_found(self):
        t = InteractionQualityTracker()
        assert t.get_type_profile("missing") is None

    def test_get_all_profiles_sorted(self):
        t = InteractionQualityTracker()
        t.record_interaction("once")
        t.record_interaction("twice")
        t.record_interaction("twice")
        profiles = t.get_all_profiles()
        assert profiles[0].interaction_type == "twice"

    def test_recent_interactions(self):
        t = InteractionQualityTracker()
        for _i in range(5):
            t.record_interaction("ask")
        recent = t.get_recent_interactions(limit=3)
        assert len(recent) == 3

    def test_recent_filtered(self):
        t = InteractionQualityTracker()
        t.record_interaction("ask")
        t.record_interaction("confirm")
        t.record_interaction("ask")
        recent = t.get_recent_interactions(interaction_type="ask")
        assert len(recent) == 2

    def test_list_types(self):
        t = InteractionQualityTracker()
        t.record_interaction("confirm")
        t.record_interaction("ask")
        assert t.list_interaction_types() == ["ask", "confirm"]


# =============================================================================
# Bounded History Tests
# =============================================================================


class TestBoundedHistory:
    """Test bounded interaction history."""

    def test_eviction(self):
        t = InteractionQualityTracker(max_interactions=5)
        for _i in range(10):
            t.record_interaction("ask")
        assert t.interaction_count == 5


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test tracker statistics."""

    def test_initial_stats(self):
        t = InteractionQualityTracker()
        stats = t.get_stats()
        assert stats.total_interactions == 0

    def test_stats_after_recording(self):
        t = InteractionQualityTracker()
        t.record_interaction("ask", satisfied=True)
        t.record_interaction("confirm", satisfied=False)
        stats = t.get_stats()
        assert stats.total_interactions == 2
        assert stats.unique_types == 2

    def test_stats_to_dict(self):
        t = InteractionQualityTracker()
        d = t.get_stats().to_dict()
        assert "total_interactions" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_count(self):
        t = InteractionQualityTracker()
        t.record_interaction("ask")
        assert t.interaction_count == 1

    def test_clear(self):
        t = InteractionQualityTracker()
        t.record_interaction("ask")
        t.clear()
        assert t.interaction_count == 0
        assert t.get_type_profile("ask") is None

    def test_to_dict(self):
        t = InteractionQualityTracker()
        t.record_interaction("ask")
        d = t.to_dict()
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global interaction tracker."""

    def test_get(self):
        reset_interaction_tracker()
        t = get_interaction_tracker()
        assert isinstance(t, InteractionQualityTracker)

    def test_singleton(self):
        reset_interaction_tracker()
        t1 = get_interaction_tracker()
        t2 = get_interaction_tracker()
        assert t1 is t2

    def test_reset(self):
        reset_interaction_tracker()
        t1 = get_interaction_tracker()
        reset_interaction_tracker()
        t2 = get_interaction_tracker()
        assert t1 is not t2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_interaction_package(self):
        from core.security_pkg.interaction import (
            InteractionQualityStats,
            InteractionQualityTracker,
            InteractionRecord,
            InteractionTypeProfile,
            get_interaction_tracker,
            reset_interaction_tracker,
        )

        assert all(
            [
                InteractionQualityTracker,
                InteractionRecord,
                InteractionTypeProfile,
                InteractionQualityStats,
                get_interaction_tracker,
                reset_interaction_tracker,
            ]
        )

    def test_constants(self):
        assert MAX_INTERACTIONS == 50000
