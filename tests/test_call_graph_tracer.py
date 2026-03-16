"""
Tests for V12.4 Call Graph Tracer.

Validates:
- CallRecord to_dict
- EdgeMetrics to_dict / properties
- TracerStats to_dict
- Recording calls
- Edge metrics updates
- Graph queries (fan-out, fan-in, hottest, failing)
- Listing callers/callees
- Bounded history
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.execution_pkg.orchestration.call_graph_tracer import (
    MAX_CALLS,
    CallGraphTracer,
    CallRecord,
    EdgeMetrics,
    TracerStats,
    get_call_tracer,
    reset_call_tracer,
)

# =============================================================================
# CallRecord Tests
# =============================================================================


class TestCallRecord:
    """Test CallRecord dataclass."""

    def test_to_dict(self):
        r = CallRecord(caller="claude", callee="bash_tool", call_type="agent_to_tool", duration_ms=150.0)
        d = r.to_dict()
        assert d["caller"] == "claude"
        assert d["callee"] == "bash_tool"


# =============================================================================
# EdgeMetrics Tests
# =============================================================================


class TestEdgeMetrics:
    """Test EdgeMetrics dataclass."""

    def test_avg_duration(self):
        m = EdgeMetrics(caller="a", callee="b", call_count=4, total_duration_ms=400.0)
        assert abs(m.avg_duration_ms - 100.0) < 0.01

    def test_avg_duration_zero(self):
        m = EdgeMetrics(caller="a", callee="b")
        assert m.avg_duration_ms == 0.0

    def test_failure_rate(self):
        m = EdgeMetrics(caller="a", callee="b", call_count=10, failures=3)
        assert abs(m.failure_rate - 0.3) < 0.01

    def test_failure_rate_zero(self):
        m = EdgeMetrics(caller="a", callee="b")
        assert m.failure_rate == 0.0

    def test_to_dict(self):
        m = EdgeMetrics(caller="claude", callee="bash", call_count=5)
        d = m.to_dict()
        assert "avg_duration_ms" in d
        assert "failure_rate" in d


# =============================================================================
# TracerStats Tests
# =============================================================================


class TestTracerStats:
    """Test TracerStats dataclass."""

    def test_to_dict(self):
        s = TracerStats(total_calls=20, unique_callers=3, unique_callees=5)
        d = s.to_dict()
        assert d["total_calls"] == 20


# =============================================================================
# Recording Tests
# =============================================================================


class TestRecording:
    """Test call recording."""

    def test_record_basic(self):
        t = CallGraphTracer()
        r = t.record_call("claude", "bash_tool", duration_ms=100.0)
        assert r.caller == "claude"
        assert t.call_count == 1

    def test_edge_updates(self):
        t = CallGraphTracer()
        t.record_call("claude", "bash", duration_ms=100)
        t.record_call("claude", "bash", duration_ms=200)
        t.record_call("claude", "bash", duration_ms=300, success=False)
        e = t.get_edge_metrics("claude", "bash")
        assert e is not None
        assert e.call_count == 3
        assert e.failures == 1

    def test_multiple_edges(self):
        t = CallGraphTracer()
        t.record_call("claude", "bash")
        t.record_call("claude", "read")
        t.record_call("gemini", "bash")
        assert len(t.get_all_edges()) == 3


# =============================================================================
# Graph Query Tests
# =============================================================================


class TestGraphQueries:
    """Test graph query methods."""

    def test_get_edge_not_found(self):
        t = CallGraphTracer()
        assert t.get_edge_metrics("a", "b") is None

    def test_hottest_edges(self):
        t = CallGraphTracer()
        for _ in range(5):
            t.record_call("claude", "bash")
        for _ in range(2):
            t.record_call("gemini", "bash")
        hot = t.get_hottest_edges(limit=1)
        assert len(hot) == 1
        assert hot[0].caller == "claude"

    def test_failing_edges(self):
        t = CallGraphTracer()
        for _ in range(5):
            t.record_call("claude", "bash", success=True)
        for _ in range(3):
            t.record_call("claude", "risky_tool", success=False)
        t.record_call("claude", "risky_tool", success=True)
        failing = t.get_failing_edges(min_calls=3)
        assert len(failing) >= 1

    def test_caller_fan_out(self):
        t = CallGraphTracer()
        t.record_call("claude", "bash")
        t.record_call("claude", "read")
        t.record_call("claude", "write")
        t.record_call("gemini", "bash")
        fan_out = t.get_caller_fan_out("claude")
        assert len(fan_out) == 3

    def test_callee_fan_in(self):
        t = CallGraphTracer()
        t.record_call("claude", "bash")
        t.record_call("gemini", "bash")
        t.record_call("user", "bash")
        fan_in = t.get_callee_fan_in("bash")
        assert len(fan_in) == 3

    def test_recent_calls(self):
        t = CallGraphTracer()
        for i in range(5):
            t.record_call(f"agent_{i}", "tool")
        recent = t.get_recent_calls(limit=3)
        assert len(recent) == 3


# =============================================================================
# Listing Tests
# =============================================================================


class TestListing:
    """Test listing methods."""

    def test_list_callers(self):
        t = CallGraphTracer()
        t.record_call("gemini", "tool")
        t.record_call("claude", "tool")
        assert t.list_callers() == ["claude", "gemini"]

    def test_list_callees(self):
        t = CallGraphTracer()
        t.record_call("agent", "write")
        t.record_call("agent", "bash")
        assert t.list_callees() == ["bash", "write"]


# =============================================================================
# Bounded History Tests
# =============================================================================


class TestBoundedHistory:
    """Test bounded call history."""

    def test_eviction(self):
        t = CallGraphTracer(max_calls=5)
        for i in range(10):
            t.record_call(f"agent_{i}", "tool")
        assert t.call_count == 5


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test tracer statistics."""

    def test_initial_stats(self):
        t = CallGraphTracer()
        stats = t.get_stats()
        assert stats.total_calls == 0

    def test_stats_after_recording(self):
        t = CallGraphTracer()
        t.record_call("claude", "bash", success=True)
        t.record_call("gemini", "read", success=False)
        stats = t.get_stats()
        assert stats.total_calls == 2
        assert stats.unique_callers == 2
        assert stats.unique_callees == 2
        assert stats.unique_edges == 2

    def test_stats_to_dict(self):
        t = CallGraphTracer()
        d = t.get_stats().to_dict()
        assert "total_calls" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_count(self):
        t = CallGraphTracer()
        t.record_call("a", "b")
        assert t.call_count == 1

    def test_clear(self):
        t = CallGraphTracer()
        t.record_call("a", "b")
        t.clear()
        assert t.call_count == 0
        assert t.get_edge_metrics("a", "b") is None

    def test_to_dict(self):
        t = CallGraphTracer()
        t.record_call("a", "b")
        d = t.to_dict()
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global call tracer."""

    def test_get(self):
        reset_call_tracer()
        t = get_call_tracer()
        assert isinstance(t, CallGraphTracer)

    def test_singleton(self):
        reset_call_tracer()
        t1 = get_call_tracer()
        t2 = get_call_tracer()
        assert t1 is t2

    def test_reset(self):
        reset_call_tracer()
        t1 = get_call_tracer()
        reset_call_tracer()
        t2 = get_call_tracer()
        assert t1 is not t2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_orchestration_package(self):
        from core.execution_pkg.orchestration import (
            CallGraphTracer,
            CallRecord,
            EdgeMetrics,
            TracerStats,
            get_call_tracer,
            reset_call_tracer,
        )

        assert all(
            [
                CallGraphTracer,
                CallRecord,
                EdgeMetrics,
                TracerStats,
                get_call_tracer,
                reset_call_tracer,
            ]
        )

    def test_constants(self):
        assert MAX_CALLS == 50000
