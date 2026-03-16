"""
Tests for V12.4 Endpoint Analytics.

Validates:
- EndpointRequestRecord to_dict
- EndpointProfile to_dict / properties
- EndpointAnalyticsStats to_dict
- Recording requests
- Profile updates
- Queries (all profiles, slowest, error-prone, recent, list endpoints)
- Bounded history
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.api.cerebro.endpoint_analytics import (
    MAX_REQUESTS,
    EndpointAnalytics,
    EndpointAnalyticsStats,
    EndpointProfile,
    EndpointRequestRecord,
    get_endpoint_analytics,
    reset_endpoint_analytics,
)

# =============================================================================
# EndpointRequestRecord Tests
# =============================================================================


class TestEndpointRequestRecord:
    """Test EndpointRequestRecord dataclass."""

    def test_to_dict(self):
        r = EndpointRequestRecord(request_id="req_000001", endpoint="/api/health", method="GET")
        d = r.to_dict()
        assert d["endpoint"] == "/api/health"
        assert d["method"] == "GET"


# =============================================================================
# EndpointProfile Tests
# =============================================================================


class TestEndpointProfile:
    """Test EndpointProfile dataclass."""

    def test_error_rate(self):
        p = EndpointProfile(endpoint="/api/test", total_requests=10, error_count=3)
        assert abs(p.error_rate - 0.3) < 0.01

    def test_error_rate_zero(self):
        p = EndpointProfile(endpoint="/api/test")
        assert p.error_rate == 0.0

    def test_avg_latency(self):
        p = EndpointProfile(endpoint="/api/test", total_requests=4, total_latency_ms=400.0)
        assert abs(p.avg_latency_ms - 100.0) < 0.01

    def test_avg_latency_zero(self):
        p = EndpointProfile(endpoint="/api/test")
        assert p.avg_latency_ms == 0.0

    def test_to_dict(self):
        p = EndpointProfile(endpoint="/api/test", total_requests=5)
        d = p.to_dict()
        assert "error_rate" in d
        assert "avg_latency_ms" in d


# =============================================================================
# EndpointAnalyticsStats Tests
# =============================================================================


class TestEndpointAnalyticsStats:
    """Test EndpointAnalyticsStats dataclass."""

    def test_to_dict(self):
        s = EndpointAnalyticsStats(total_requests=20, unique_endpoints=3)
        d = s.to_dict()
        assert d["total_requests"] == 20


# =============================================================================
# Recording Tests
# =============================================================================


class TestRecording:
    """Test request recording."""

    def test_record_basic(self):
        a = EndpointAnalytics()
        r = a.record_request("/api/health")
        assert r.request_id == "req_000001"
        assert a.request_count == 1

    def test_profile_updates(self):
        a = EndpointAnalytics()
        a.record_request("/api/data", latency_ms=100)
        a.record_request("/api/data", latency_ms=200)
        a.record_request("/api/data", error=True, latency_ms=50)
        p = a.get_endpoint_profile("/api/data")
        assert p is not None
        assert p.total_requests == 3
        assert p.error_count == 1

    def test_multiple_endpoints(self):
        a = EndpointAnalytics()
        a.record_request("/api/a")
        a.record_request("/api/b")
        a.record_request("/api/c", method="POST")
        assert len(a.get_all_profiles()) == 3


# =============================================================================
# Query Tests
# =============================================================================


class TestQueries:
    """Test query methods."""

    def test_get_profile_not_found(self):
        a = EndpointAnalytics()
        assert a.get_endpoint_profile("/missing") is None

    def test_get_all_profiles_sorted(self):
        a = EndpointAnalytics()
        a.record_request("/api/once")
        a.record_request("/api/twice")
        a.record_request("/api/twice")
        profiles = a.get_all_profiles()
        assert profiles[0].endpoint == "/api/twice"

    def test_slowest_endpoints(self):
        a = EndpointAnalytics()
        a.record_request("/fast", latency_ms=10)
        a.record_request("/slow", latency_ms=500)
        a.record_request("/medium", latency_ms=100)
        slowest = a.get_slowest_endpoints(limit=2)
        assert len(slowest) == 2
        assert slowest[0].avg_latency_ms >= slowest[1].avg_latency_ms

    def test_error_prone_endpoints(self):
        a = EndpointAnalytics()
        for _ in range(5):
            a.record_request("/stable")
        for _ in range(3):
            a.record_request("/broken", error=True)
        prone = a.get_error_prone_endpoints(min_requests=3, threshold=0.1)
        assert len(prone) == 1
        assert prone[0].endpoint == "/broken"

    def test_recent_requests(self):
        a = EndpointAnalytics()
        for i in range(5):
            a.record_request(f"/api/{i}")
        recent = a.get_recent_requests(limit=3)
        assert len(recent) == 3

    def test_list_endpoints(self):
        a = EndpointAnalytics()
        a.record_request("/api/b")
        a.record_request("/api/a")
        endpoints = a.list_endpoints()
        assert len(endpoints) == 2


# =============================================================================
# Bounded History Tests
# =============================================================================


class TestBoundedHistory:
    """Test bounded request history."""

    def test_eviction(self):
        a = EndpointAnalytics(max_requests=5)
        for _i in range(10):
            a.record_request("/api/test")
        assert a.request_count == 5


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test analytics statistics."""

    def test_initial_stats(self):
        a = EndpointAnalytics()
        stats = a.get_stats()
        assert stats.total_requests == 0

    def test_stats_after_recording(self):
        a = EndpointAnalytics()
        a.record_request("/api/a", latency_ms=100)
        a.record_request("/api/b", error=True)
        stats = a.get_stats()
        assert stats.total_requests == 2
        assert stats.unique_endpoints == 2

    def test_stats_to_dict(self):
        a = EndpointAnalytics()
        d = a.get_stats().to_dict()
        assert "total_requests" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_count(self):
        a = EndpointAnalytics()
        a.record_request("/api/test")
        assert a.request_count == 1

    def test_clear(self):
        a = EndpointAnalytics()
        a.record_request("/api/test")
        a.clear()
        assert a.request_count == 0
        assert a.get_endpoint_profile("/api/test") is None

    def test_to_dict(self):
        a = EndpointAnalytics()
        a.record_request("/api/test")
        d = a.to_dict()
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global endpoint analytics."""

    def test_get(self):
        reset_endpoint_analytics()
        a = get_endpoint_analytics()
        assert isinstance(a, EndpointAnalytics)

    def test_singleton(self):
        reset_endpoint_analytics()
        a1 = get_endpoint_analytics()
        a2 = get_endpoint_analytics()
        assert a1 is a2

    def test_reset(self):
        reset_endpoint_analytics()
        a1 = get_endpoint_analytics()
        reset_endpoint_analytics()
        a2 = get_endpoint_analytics()
        assert a1 is not a2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_cerebro_package(self):
        from core.api.cerebro import (
            EndpointAnalytics,
            EndpointAnalyticsStats,
            EndpointProfile,
            EndpointRequestRecord,
            get_endpoint_analytics,
            reset_endpoint_analytics,
        )

        assert all(
            [
                EndpointAnalytics,
                EndpointRequestRecord,
                EndpointProfile,
                EndpointAnalyticsStats,
                get_endpoint_analytics,
                reset_endpoint_analytics,
            ]
        )

    def test_constants(self):
        assert MAX_REQUESTS == 50000
