"""
Tests for V12.4 Startup Analytics.

Validates:
- BootStepRecord to_dict
- ComponentProfile to_dict / properties
- StartupStats to_dict
- Recording steps
- Profile updates
- Queries (all profiles, slowest, failing, recent, list components)
- Bounded history
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.infrastructure.bootstrap.startup_analytics import (
    MAX_BOOT_RECORDS,
    BootStepRecord,
    ComponentProfile,
    StartupAnalytics,
    StartupStats,
    get_startup_analytics,
    reset_startup_analytics,
)

# =============================================================================
# BootStepRecord Tests
# =============================================================================


class TestBootStepRecord:
    """Test BootStepRecord dataclass."""

    def test_to_dict(self):
        r = BootStepRecord(step_id="bs_000001", component_name="redis", duration_ms=50.0)
        d = r.to_dict()
        assert d["component_name"] == "redis"
        assert d["duration_ms"] == 50.0


# =============================================================================
# ComponentProfile Tests
# =============================================================================


class TestComponentProfile:
    """Test ComponentProfile dataclass."""

    def test_success_rate(self):
        p = ComponentProfile(component_name="redis", total_boots=10, success_count=8)
        assert abs(p.success_rate - 0.8) < 0.01

    def test_success_rate_zero(self):
        p = ComponentProfile(component_name="redis")
        assert p.success_rate == 0.0

    def test_avg_duration(self):
        p = ComponentProfile(component_name="redis", total_boots=4, total_duration_ms=400.0)
        assert abs(p.avg_duration_ms - 100.0) < 0.01

    def test_avg_duration_zero(self):
        p = ComponentProfile(component_name="redis")
        assert p.avg_duration_ms == 0.0

    def test_to_dict(self):
        p = ComponentProfile(component_name="redis", total_boots=5)
        d = p.to_dict()
        assert "success_rate" in d
        assert "avg_duration_ms" in d


# =============================================================================
# StartupStats Tests
# =============================================================================


class TestStartupStats:
    """Test StartupStats dataclass."""

    def test_to_dict(self):
        s = StartupStats(total_boots=20, unique_components=3)
        d = s.to_dict()
        assert d["total_boots"] == 20


# =============================================================================
# Recording Tests
# =============================================================================


class TestRecording:
    """Test step recording."""

    def test_record_basic(self):
        a = StartupAnalytics()
        r = a.record_step("redis", duration_ms=50.0)
        assert r.step_id == "bs_000001"
        assert a.step_count == 1

    def test_profile_updates(self):
        a = StartupAnalytics()
        a.record_step("redis", duration_ms=50, success=True)
        a.record_step("redis", duration_ms=60, success=True)
        a.record_step("redis", success=False, error_message="connection refused")
        p = a.get_component_profile("redis")
        assert p is not None
        assert p.total_boots == 3
        assert p.success_count == 2

    def test_multiple_components(self):
        a = StartupAnalytics()
        a.record_step("redis")
        a.record_step("postgres")
        a.record_step("kernel")
        assert len(a.get_all_profiles()) == 3


# =============================================================================
# Query Tests
# =============================================================================


class TestQueries:
    """Test query methods."""

    def test_get_profile_not_found(self):
        a = StartupAnalytics()
        assert a.get_component_profile("missing") is None

    def test_get_all_profiles_sorted(self):
        a = StartupAnalytics()
        a.record_step("once")
        a.record_step("twice")
        a.record_step("twice")
        profiles = a.get_all_profiles()
        assert profiles[0].component_name == "twice"

    def test_slowest_components(self):
        a = StartupAnalytics()
        a.record_step("fast", duration_ms=10)
        a.record_step("slow", duration_ms=500)
        a.record_step("medium", duration_ms=100)
        slowest = a.get_slowest_components(limit=2)
        assert len(slowest) == 2
        assert slowest[0].avg_duration_ms >= slowest[1].avg_duration_ms

    def test_failing_components(self):
        a = StartupAnalytics()
        for _ in range(5):
            a.record_step("stable", success=True)
        for _ in range(3):
            a.record_step("flaky", success=False)
        a.record_step("flaky", success=True)
        failing = a.get_failing_components(min_boots=3, threshold=0.8)
        assert len(failing) == 1
        assert failing[0].component_name == "flaky"

    def test_recent_steps(self):
        a = StartupAnalytics()
        for i in range(5):
            a.record_step(f"comp_{i}")
        recent = a.get_recent_steps(limit=3)
        assert len(recent) == 3

    def test_recent_filtered(self):
        a = StartupAnalytics()
        a.record_step("redis")
        a.record_step("postgres")
        a.record_step("redis")
        recent = a.get_recent_steps(component_name="redis")
        assert len(recent) == 2

    def test_list_components(self):
        a = StartupAnalytics()
        a.record_step("zeta")
        a.record_step("alpha")
        assert a.list_components() == ["alpha", "zeta"]


# =============================================================================
# Bounded History Tests
# =============================================================================


class TestBoundedHistory:
    """Test bounded step history."""

    def test_eviction(self):
        a = StartupAnalytics(max_records=5)
        for _i in range(10):
            a.record_step("test")
        assert a.step_count == 5


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test analytics statistics."""

    def test_initial_stats(self):
        a = StartupAnalytics()
        stats = a.get_stats()
        assert stats.total_boots == 0

    def test_stats_after_recording(self):
        a = StartupAnalytics()
        a.record_step("redis", success=True, duration_ms=50)
        a.record_step("postgres", success=False, duration_ms=100)
        stats = a.get_stats()
        assert stats.total_boots == 2
        assert stats.unique_components == 2

    def test_stats_to_dict(self):
        a = StartupAnalytics()
        d = a.get_stats().to_dict()
        assert "total_boots" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_count(self):
        a = StartupAnalytics()
        a.record_step("redis")
        assert a.step_count == 1

    def test_clear(self):
        a = StartupAnalytics()
        a.record_step("redis")
        a.clear()
        assert a.step_count == 0
        assert a.get_component_profile("redis") is None

    def test_to_dict(self):
        a = StartupAnalytics()
        a.record_step("redis")
        d = a.to_dict()
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global startup analytics."""

    def test_get(self):
        reset_startup_analytics()
        a = get_startup_analytics()
        assert isinstance(a, StartupAnalytics)

    def test_singleton(self):
        reset_startup_analytics()
        a1 = get_startup_analytics()
        a2 = get_startup_analytics()
        assert a1 is a2

    def test_reset(self):
        reset_startup_analytics()
        a1 = get_startup_analytics()
        reset_startup_analytics()
        a2 = get_startup_analytics()
        assert a1 is not a2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_bootstrap_package(self):
        from core.infrastructure.bootstrap import (
            BootStepRecord,
            ComponentProfile,
            StartupAnalytics,
            StartupStats,
            get_startup_analytics,
            reset_startup_analytics,
        )

        assert all(
            [
                StartupAnalytics,
                BootStepRecord,
                ComponentProfile,
                StartupStats,
                get_startup_analytics,
                reset_startup_analytics,
            ]
        )

    def test_constants(self):
        assert MAX_BOOT_RECORDS == 50000
