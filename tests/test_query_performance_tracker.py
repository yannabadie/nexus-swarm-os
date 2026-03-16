"""
Tests for V12.4 Query Performance Tracker.

Validates:
- QueryRecord to_dict
- TableProfile to_dict / properties
- QueryPerformanceStats to_dict
- Recording queries
- Profile updates
- Queries (all profiles, slowest, recent, list tables)
- Bounded history
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.infrastructure.db.query_performance_tracker import (
    MAX_QUERIES,
    QueryPerformanceStats,
    QueryPerformanceTracker,
    QueryRecord,
    TableProfile,
    get_query_tracker,
    reset_query_tracker,
)

# =============================================================================
# QueryRecord Tests
# =============================================================================


class TestQueryRecord:
    """Test QueryRecord dataclass."""

    def test_to_dict(self):
        r = QueryRecord(query_id="qr_000001", query_type="select", table_name="tenants", duration_ms=5.0)
        d = r.to_dict()
        assert d["query_type"] == "select"
        assert d["table_name"] == "tenants"


# =============================================================================
# TableProfile Tests
# =============================================================================


class TestTableProfile:
    """Test TableProfile dataclass."""

    def test_success_rate(self):
        p = TableProfile(table_name="tenants", total_queries=10, success_count=8)
        assert abs(p.success_rate - 0.8) < 0.01

    def test_success_rate_zero(self):
        p = TableProfile(table_name="tenants")
        assert p.success_rate == 0.0

    def test_avg_duration(self):
        p = TableProfile(table_name="tenants", total_queries=4, total_duration_ms=400.0)
        assert abs(p.avg_duration_ms - 100.0) < 0.01

    def test_avg_duration_zero(self):
        p = TableProfile(table_name="tenants")
        assert p.avg_duration_ms == 0.0

    def test_avg_rows(self):
        p = TableProfile(table_name="tenants", total_queries=4, total_rows=40)
        assert abs(p.avg_rows - 10.0) < 0.01

    def test_avg_rows_zero(self):
        p = TableProfile(table_name="tenants")
        assert p.avg_rows == 0.0

    def test_to_dict(self):
        p = TableProfile(table_name="tenants", total_queries=5)
        d = p.to_dict()
        assert "success_rate" in d
        assert "avg_duration_ms" in d
        assert "avg_rows" in d


# =============================================================================
# QueryPerformanceStats Tests
# =============================================================================


class TestQueryPerformanceStats:
    """Test QueryPerformanceStats dataclass."""

    def test_to_dict(self):
        s = QueryPerformanceStats(total_queries=20, unique_tables=3)
        d = s.to_dict()
        assert d["total_queries"] == 20


# =============================================================================
# Recording Tests
# =============================================================================


class TestRecording:
    """Test query recording."""

    def test_record_basic(self):
        t = QueryPerformanceTracker()
        r = t.record_query("select", "tenants", duration_ms=5.0)
        assert r.query_id == "qr_000001"
        assert t.query_count == 1

    def test_profile_updates(self):
        t = QueryPerformanceTracker()
        t.record_query("select", "tenants", duration_ms=5, rows_affected=10)
        t.record_query("select", "tenants", duration_ms=10, rows_affected=20)
        t.record_query("insert", "tenants", success=False)
        p = t.get_table_profile("tenants")
        assert p is not None
        assert p.total_queries == 3
        assert p.success_count == 2

    def test_multiple_tables(self):
        t = QueryPerformanceTracker()
        t.record_query("select", "tenants")
        t.record_query("select", "users")
        t.record_query("select", "workspaces")
        assert len(t.get_all_profiles()) == 3


# =============================================================================
# Query Tests
# =============================================================================


class TestQueries:
    """Test query methods."""

    def test_get_profile_not_found(self):
        t = QueryPerformanceTracker()
        assert t.get_table_profile("missing") is None

    def test_get_all_profiles_sorted(self):
        t = QueryPerformanceTracker()
        t.record_query("select", "once")
        t.record_query("select", "twice")
        t.record_query("select", "twice")
        profiles = t.get_all_profiles()
        assert profiles[0].table_name == "twice"

    def test_slowest_tables(self):
        t = QueryPerformanceTracker()
        t.record_query("select", "fast", duration_ms=1)
        t.record_query("select", "slow", duration_ms=500)
        t.record_query("select", "medium", duration_ms=50)
        slowest = t.get_slowest_tables(limit=2)
        assert len(slowest) == 2
        assert slowest[0].avg_duration_ms >= slowest[1].avg_duration_ms

    def test_recent_queries(self):
        t = QueryPerformanceTracker()
        for _i in range(5):
            t.record_query("select", "tenants")
        recent = t.get_recent_queries(limit=3)
        assert len(recent) == 3

    def test_recent_filtered(self):
        t = QueryPerformanceTracker()
        t.record_query("select", "tenants")
        t.record_query("select", "users")
        t.record_query("select", "tenants")
        recent = t.get_recent_queries(table_name="tenants")
        assert len(recent) == 2

    def test_list_tables(self):
        t = QueryPerformanceTracker()
        t.record_query("select", "zeta")
        t.record_query("select", "alpha")
        assert t.list_tables() == ["alpha", "zeta"]


# =============================================================================
# Bounded History Tests
# =============================================================================


class TestBoundedHistory:
    """Test bounded query history."""

    def test_eviction(self):
        t = QueryPerformanceTracker(max_queries=5)
        for _i in range(10):
            t.record_query("select", "tenants")
        assert t.query_count == 5


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test tracker statistics."""

    def test_initial_stats(self):
        t = QueryPerformanceTracker()
        stats = t.get_stats()
        assert stats.total_queries == 0

    def test_stats_after_recording(self):
        t = QueryPerformanceTracker()
        t.record_query("select", "tenants", success=True)
        t.record_query("insert", "users", success=False)
        stats = t.get_stats()
        assert stats.total_queries == 2
        assert stats.unique_tables == 2

    def test_stats_to_dict(self):
        t = QueryPerformanceTracker()
        d = t.get_stats().to_dict()
        assert "total_queries" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_count(self):
        t = QueryPerformanceTracker()
        t.record_query("select", "tenants")
        assert t.query_count == 1

    def test_clear(self):
        t = QueryPerformanceTracker()
        t.record_query("select", "tenants")
        t.clear()
        assert t.query_count == 0
        assert t.get_table_profile("tenants") is None

    def test_to_dict(self):
        t = QueryPerformanceTracker()
        t.record_query("select", "tenants")
        d = t.to_dict()
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global query tracker."""

    def test_get(self):
        reset_query_tracker()
        t = get_query_tracker()
        assert isinstance(t, QueryPerformanceTracker)

    def test_singleton(self):
        reset_query_tracker()
        t1 = get_query_tracker()
        t2 = get_query_tracker()
        assert t1 is t2

    def test_reset(self):
        reset_query_tracker()
        t1 = get_query_tracker()
        reset_query_tracker()
        t2 = get_query_tracker()
        assert t1 is not t2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_db_package(self):
        from core.infrastructure.db import (
            QueryPerformanceStats,
            QueryPerformanceTracker,
            QueryRecord,
            TableProfile,
            get_query_tracker,
            reset_query_tracker,
        )

        assert all(
            [
                QueryPerformanceTracker,
                QueryRecord,
                TableProfile,
                QueryPerformanceStats,
                get_query_tracker,
                reset_query_tracker,
            ]
        )

    def test_constants(self):
        assert MAX_QUERIES == 50000
