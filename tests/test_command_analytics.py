"""
Tests for V12.4 Command Analytics.

Validates:
- CommandInvocation to_dict
- CommandMetrics to_dict / properties
- UsagePattern to_dict
- AnalyticsStats to_dict
- Recording invocations (metric updates)
- Queries (command metrics, most used, error prone, recent)
- Pattern detection
- Bounded history
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.interface_pkg.interface.command_analytics import (
    MAX_INVOCATIONS,
    AnalyticsStats,
    CommandAnalytics,
    CommandInvocation,
    CommandMetrics,
    UsagePattern,
    get_command_analytics,
    reset_command_analytics,
)

# =============================================================================
# CommandInvocation Tests
# =============================================================================


class TestCommandInvocation:
    """Test CommandInvocation dataclass."""

    def test_to_dict(self):
        inv = CommandInvocation(
            command="/evolve", args="--strategy=creative", duration_ms=500.0, success=True, source="repl"
        )
        d = inv.to_dict()
        assert d["command"] == "/evolve"
        assert d["success"] is True


# =============================================================================
# CommandMetrics Tests
# =============================================================================


class TestCommandMetrics:
    """Test CommandMetrics dataclass."""

    def test_success_rate(self):
        m = CommandMetrics(command="/evolve", total_invocations=10, successes=8, failures=2)
        assert abs(m.success_rate - 0.8) < 0.01

    def test_success_rate_zero(self):
        m = CommandMetrics(command="/evolve")
        assert m.success_rate == 0.0

    def test_avg_duration(self):
        m = CommandMetrics(command="/evolve", total_invocations=4, total_duration_ms=400.0)
        assert abs(m.avg_duration_ms - 100.0) < 0.01

    def test_avg_duration_zero(self):
        m = CommandMetrics(command="/evolve")
        assert m.avg_duration_ms == 0.0

    def test_to_dict(self):
        m = CommandMetrics(command="/evolve", total_invocations=5, successes=4)
        d = m.to_dict()
        assert "success_rate" in d
        assert "avg_duration_ms" in d


# =============================================================================
# UsagePattern Tests
# =============================================================================


class TestUsagePattern:
    """Test UsagePattern dataclass."""

    def test_to_dict(self):
        p = UsagePattern(pattern_type="frequent_command", command="/evolve", details="15 invocations", count=15)
        d = p.to_dict()
        assert d["pattern_type"] == "frequent_command"


# =============================================================================
# AnalyticsStats Tests
# =============================================================================


class TestAnalyticsStats:
    """Test AnalyticsStats dataclass."""

    def test_to_dict(self):
        s = AnalyticsStats(
            total_invocations=20, unique_commands=5, overall_success_rate=0.9, most_used_command="/evolve"
        )
        d = s.to_dict()
        assert d["total_invocations"] == 20


# =============================================================================
# Recording Tests
# =============================================================================


class TestRecording:
    """Test invocation recording."""

    def test_record_basic(self):
        a = CommandAnalytics()
        inv = a.record_invocation("/evolve", args="--strategy=creative")
        assert inv.command == "/evolve"
        assert a.invocation_count == 1

    def test_record_failure(self):
        a = CommandAnalytics()
        inv = a.record_invocation("/swarm", success=False, error="No agents")
        assert inv.success is False
        m = a.get_command_metrics("/swarm")
        assert m.failures == 1

    def test_metrics_update(self):
        a = CommandAnalytics()
        a.record_invocation("/evolve", success=True, duration_ms=100)
        a.record_invocation("/evolve", success=True, duration_ms=200)
        a.record_invocation("/evolve", success=False, duration_ms=50)
        m = a.get_command_metrics("/evolve")
        assert m is not None
        assert m.total_invocations == 3
        assert m.successes == 2
        assert m.failures == 1
        assert abs(m.total_duration_ms - 350.0) < 0.01

    def test_multiple_commands(self):
        a = CommandAnalytics()
        a.record_invocation("/evolve")
        a.record_invocation("/swarm")
        assert a.invocation_count == 2


# =============================================================================
# Query Tests
# =============================================================================


class TestQueries:
    """Test query methods."""

    def test_get_command_metrics_not_found(self):
        a = CommandAnalytics()
        assert a.get_command_metrics("missing") is None

    def test_get_all_metrics_sorted(self):
        a = CommandAnalytics()
        a.record_invocation("/evolve")
        a.record_invocation("/evolve")
        a.record_invocation("/swarm")
        metrics = a.get_all_metrics()
        assert len(metrics) == 2
        assert metrics[0].command == "/evolve"  # 2 > 1

    def test_get_most_used(self):
        a = CommandAnalytics()
        for _ in range(5):
            a.record_invocation("/evolve")
        for _ in range(3):
            a.record_invocation("/swarm")
        a.record_invocation("/help")
        most = a.get_most_used(limit=2)
        assert len(most) == 2
        assert most[0].command == "/evolve"

    def test_get_error_prone(self):
        a = CommandAnalytics()
        # 70% success = error prone (< 0.8)
        for _ in range(7):
            a.record_invocation("/buggy", success=True)
        for _ in range(3):
            a.record_invocation("/buggy", success=False)
        # 100% success = not error prone
        for _ in range(5):
            a.record_invocation("/solid", success=True)
        error_prone = a.get_error_prone()
        assert len(error_prone) == 1
        assert error_prone[0].command == "/buggy"

    def test_get_error_prone_min_invocations(self):
        a = CommandAnalytics()
        a.record_invocation("/rare", success=False)
        a.record_invocation("/rare", success=False)
        # Only 2 invocations, default min is 3
        assert len(a.get_error_prone()) == 0

    def test_get_recent_invocations(self):
        a = CommandAnalytics()
        for i in range(10):
            a.record_invocation(f"/cmd_{i}")
        recent = a.get_recent_invocations(limit=3)
        assert len(recent) == 3

    def test_get_recent_filtered_by_command(self):
        a = CommandAnalytics()
        a.record_invocation("/evolve")
        a.record_invocation("/swarm")
        a.record_invocation("/evolve")
        recent = a.get_recent_invocations(command="/evolve")
        assert len(recent) == 2


# =============================================================================
# Pattern Detection Tests
# =============================================================================


class TestPatternDetection:
    """Test pattern detection."""

    def test_no_patterns(self):
        a = CommandAnalytics()
        a.record_invocation("/evolve")
        assert a.detect_patterns() == []

    def test_frequent_command(self):
        a = CommandAnalytics()
        for _ in range(12):
            a.record_invocation("/evolve")
        patterns = a.detect_patterns()
        frequent = [p for p in patterns if p.pattern_type == "frequent_command"]
        assert len(frequent) == 1
        assert frequent[0].command == "/evolve"

    def test_error_prone_pattern(self):
        a = CommandAnalytics()
        for _ in range(4):
            a.record_invocation("/buggy", success=False)
        patterns = a.detect_patterns()
        error_prone = [p for p in patterns if p.pattern_type == "error_prone"]
        assert len(error_prone) == 1
        assert error_prone[0].command == "/buggy"


# =============================================================================
# Bounded History Tests
# =============================================================================


class TestBoundedHistory:
    """Test bounded invocation history."""

    def test_eviction(self):
        a = CommandAnalytics(max_invocations=5)
        for i in range(10):
            a.record_invocation(f"/cmd_{i}")
        assert a.invocation_count == 5


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test analytics statistics."""

    def test_initial_stats(self):
        a = CommandAnalytics()
        stats = a.get_stats()
        assert stats.total_invocations == 0

    def test_stats_after_recording(self):
        a = CommandAnalytics()
        a.record_invocation("/evolve", success=True, duration_ms=100)
        a.record_invocation("/swarm", success=False, duration_ms=200)
        stats = a.get_stats()
        assert stats.total_invocations == 2
        assert stats.unique_commands == 2
        assert abs(stats.overall_success_rate - 0.5) < 0.01
        assert abs(stats.avg_duration_ms - 150.0) < 0.01

    def test_stats_most_used(self):
        a = CommandAnalytics()
        a.record_invocation("/evolve")
        a.record_invocation("/evolve")
        a.record_invocation("/swarm")
        stats = a.get_stats()
        assert stats.most_used_command == "/evolve"

    def test_stats_to_dict(self):
        a = CommandAnalytics()
        d = a.get_stats().to_dict()
        assert "total_invocations" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_invocation_count(self):
        a = CommandAnalytics()
        a.record_invocation("/evolve")
        a.record_invocation("/swarm")
        assert a.invocation_count == 2

    def test_list_commands(self):
        a = CommandAnalytics()
        a.record_invocation("/swarm")
        a.record_invocation("/evolve")
        assert a.list_commands() == ["/evolve", "/swarm"]

    def test_clear(self):
        a = CommandAnalytics()
        a.record_invocation("/evolve")
        a.clear()
        assert a.invocation_count == 0
        assert a.get_command_metrics("/evolve") is None

    def test_to_dict(self):
        a = CommandAnalytics()
        a.record_invocation("/evolve")
        d = a.to_dict()
        assert "stats" in d
        assert d["invocation_count"] == 1


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global command analytics."""

    def test_get(self):
        reset_command_analytics()
        a = get_command_analytics()
        assert isinstance(a, CommandAnalytics)

    def test_singleton(self):
        reset_command_analytics()
        a1 = get_command_analytics()
        a2 = get_command_analytics()
        assert a1 is a2

    def test_reset(self):
        reset_command_analytics()
        a1 = get_command_analytics()
        reset_command_analytics()
        a2 = get_command_analytics()
        assert a1 is not a2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_interface_package(self):
        from core.interface_pkg.interface import (
            AnalyticsStats,
            CommandAnalytics,
            CommandInvocation,
            CommandMetrics,
            UsagePattern,
            get_command_analytics,
            reset_command_analytics,
        )

        assert all(
            [
                CommandAnalytics,
                CommandInvocation,
                CommandMetrics,
                UsagePattern,
                AnalyticsStats,
                get_command_analytics,
                reset_command_analytics,
            ]
        )

    def test_constants(self):
        assert MAX_INVOCATIONS == 50000
