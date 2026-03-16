"""
Tests for V12.4 Error Pattern Analyzer.

Validates:
- ErrorRecord to_dict
- ErrorCategoryMetrics to_dict / properties
- ErrorPattern to_dict
- AnalyzerStats to_dict
- Recording errors
- Category metrics updates
- Pattern detection
- Queries (by agent, by category, recent, error-prone agents)
- Bounded history
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.observability.telemetry.error_pattern_analyzer import (
    ERROR_CATEGORIES,
    MAX_ERRORS,
    AnalyzerStats,
    ErrorCategoryMetrics,
    ErrorPattern,
    ErrorPatternAnalyzer,
    ErrorRecord,
    get_error_analyzer,
    reset_error_analyzer,
)

# =============================================================================
# ErrorRecord Tests
# =============================================================================


class TestErrorRecord:
    """Test ErrorRecord dataclass."""

    def test_to_dict(self):
        r = ErrorRecord(error_id="err_000001", category="timeout", message="Request timed out", source="llm_invoke")
        d = r.to_dict()
        assert d["category"] == "timeout"
        assert d["error_id"] == "err_000001"


# =============================================================================
# ErrorCategoryMetrics Tests
# =============================================================================


class TestErrorCategoryMetrics:
    """Test ErrorCategoryMetrics dataclass."""

    def test_recovery_rate(self):
        m = ErrorCategoryMetrics(category="timeout", total_count=10, recovered_count=8)
        assert abs(m.recovery_rate - 0.8) < 0.01

    def test_recovery_rate_zero(self):
        m = ErrorCategoryMetrics(category="timeout")
        assert m.recovery_rate == 0.0

    def test_avg_recovery_ms(self):
        m = ErrorCategoryMetrics(category="timeout", recovered_count=4, total_recovery_ms=400.0)
        assert abs(m.avg_recovery_ms - 100.0) < 0.01

    def test_avg_recovery_zero(self):
        m = ErrorCategoryMetrics(category="timeout")
        assert m.avg_recovery_ms == 0.0

    def test_to_dict(self):
        m = ErrorCategoryMetrics(category="timeout", total_count=5)
        d = m.to_dict()
        assert "recovery_rate" in d
        assert "avg_recovery_ms" in d


# =============================================================================
# ErrorPattern Tests
# =============================================================================


class TestErrorPattern:
    """Test ErrorPattern dataclass."""

    def test_to_dict(self):
        p = ErrorPattern(pattern_type="recurring", category="timeout", details="5 occurrences", count=5)
        d = p.to_dict()
        assert d["pattern_type"] == "recurring"


# =============================================================================
# AnalyzerStats Tests
# =============================================================================


class TestAnalyzerStats:
    """Test AnalyzerStats dataclass."""

    def test_to_dict(self):
        s = AnalyzerStats(total_errors=20, unique_categories=3)
        d = s.to_dict()
        assert d["total_errors"] == 20


# =============================================================================
# Recording Tests
# =============================================================================


class TestRecording:
    """Test error recording."""

    def test_record_basic(self):
        a = ErrorPatternAnalyzer()
        r = a.record_error(category="timeout", message="Timed out")
        assert r.error_id == "err_000000"
        assert a.error_count == 1

    def test_record_with_recovery(self):
        a = ErrorPatternAnalyzer()
        r = a.record_error(category="timeout", recovered=True, recovery_ms=500.0)
        assert r.recovered is True
        m = a.get_category_metrics("timeout")
        assert m.recovered_count == 1

    def test_category_metrics_update(self):
        a = ErrorPatternAnalyzer()
        a.record_error(category="timeout", recovered=True, recovery_ms=100)
        a.record_error(category="timeout", recovered=False)
        a.record_error(category="timeout", recovered=True, recovery_ms=200)
        m = a.get_category_metrics("timeout")
        assert m is not None
        assert m.total_count == 3
        assert m.recovered_count == 2

    def test_multiple_categories(self):
        a = ErrorPatternAnalyzer()
        a.record_error(category="timeout")
        a.record_error(category="budget")
        a.record_error(category="validation")
        assert len(a.get_all_metrics()) == 3


# =============================================================================
# Query Tests
# =============================================================================


class TestQueries:
    """Test query methods."""

    def test_get_category_not_found(self):
        a = ErrorPatternAnalyzer()
        assert a.get_category_metrics("missing") is None

    def test_get_all_metrics_sorted(self):
        a = ErrorPatternAnalyzer()
        a.record_error(category="timeout")
        a.record_error(category="timeout")
        a.record_error(category="budget")
        metrics = a.get_all_metrics()
        assert metrics[0].category == "timeout"  # 2 > 1

    def test_errors_by_agent(self):
        a = ErrorPatternAnalyzer()
        a.record_error(agent_id="claude", category="timeout")
        a.record_error(agent_id="gemini", category="budget")
        a.record_error(agent_id="claude", category="validation")
        results = a.get_errors_by_agent("claude")
        assert len(results) == 2

    def test_errors_by_category(self):
        a = ErrorPatternAnalyzer()
        a.record_error(category="timeout")
        a.record_error(category="budget")
        a.record_error(category="timeout")
        results = a.get_errors_by_category("timeout")
        assert len(results) == 2

    def test_recent_errors(self):
        a = ErrorPatternAnalyzer()
        for _i in range(5):
            a.record_error(category="timeout")
        recent = a.get_recent_errors(limit=3)
        assert len(recent) == 3

    def test_most_error_prone_agents(self):
        a = ErrorPatternAnalyzer()
        for _ in range(5):
            a.record_error(agent_id="claude")
        for _ in range(2):
            a.record_error(agent_id="gemini")
        agents = a.get_most_error_prone_agents(limit=2)
        assert len(agents) == 2
        assert agents[0][0] == "claude"  # 5 > 2


# =============================================================================
# Pattern Detection Tests
# =============================================================================


class TestPatternDetection:
    """Test pattern detection."""

    def test_no_patterns(self):
        a = ErrorPatternAnalyzer()
        a.record_error(category="timeout")
        assert a.detect_patterns() == []

    def test_recurring_pattern(self):
        a = ErrorPatternAnalyzer()
        for _ in range(5):
            a.record_error(category="timeout")
        patterns = a.detect_patterns()
        recurring = [p for p in patterns if p.pattern_type == "recurring"]
        assert len(recurring) == 1
        assert recurring[0].category == "timeout"

    def test_agent_specific_pattern(self):
        a = ErrorPatternAnalyzer()
        for _ in range(4):
            a.record_error(agent_id="claude")
        patterns = a.detect_patterns()
        agent = [p for p in patterns if p.pattern_type == "agent_specific"]
        assert len(agent) == 1


# =============================================================================
# Bounded History Tests
# =============================================================================


class TestBoundedHistory:
    """Test bounded error history."""

    def test_eviction(self):
        a = ErrorPatternAnalyzer(max_errors=5)
        for _i in range(10):
            a.record_error(category="timeout")
        assert a.error_count == 5


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test analyzer statistics."""

    def test_initial_stats(self):
        a = ErrorPatternAnalyzer()
        stats = a.get_stats()
        assert stats.total_errors == 0

    def test_stats_after_recording(self):
        a = ErrorPatternAnalyzer()
        a.record_error(category="timeout", recovered=True, agent_id="claude")
        a.record_error(category="budget", recovered=False, agent_id="gemini")
        stats = a.get_stats()
        assert stats.total_errors == 2
        assert stats.unique_categories == 2

    def test_stats_to_dict(self):
        a = ErrorPatternAnalyzer()
        d = a.get_stats().to_dict()
        assert "total_errors" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_count(self):
        a = ErrorPatternAnalyzer()
        a.record_error(category="timeout")
        assert a.error_count == 1

    def test_clear(self):
        a = ErrorPatternAnalyzer()
        a.record_error(category="timeout")
        a.clear()
        assert a.error_count == 0
        assert a.get_category_metrics("timeout") is None

    def test_to_dict(self):
        a = ErrorPatternAnalyzer()
        a.record_error(category="timeout")
        d = a.to_dict()
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global error analyzer."""

    def test_get(self):
        reset_error_analyzer()
        a = get_error_analyzer()
        assert isinstance(a, ErrorPatternAnalyzer)

    def test_singleton(self):
        reset_error_analyzer()
        a1 = get_error_analyzer()
        a2 = get_error_analyzer()
        assert a1 is a2

    def test_reset(self):
        reset_error_analyzer()
        a1 = get_error_analyzer()
        reset_error_analyzer()
        a2 = get_error_analyzer()
        assert a1 is not a2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_telemetry_package(self):
        from core.observability.telemetry import (
            ErrorAnalyzerStats,
            ErrorCategoryMetrics,
            ErrorPattern,
            ErrorPatternAnalyzer,
            ErrorRecord,
            get_error_analyzer,
            reset_error_analyzer,
        )

        assert all(
            [
                ErrorPatternAnalyzer,
                ErrorRecord,
                ErrorCategoryMetrics,
                ErrorPattern,
                ErrorAnalyzerStats,
                get_error_analyzer,
                reset_error_analyzer,
            ]
        )

    def test_constants(self):
        assert MAX_ERRORS == 50000
        assert "timeout" in ERROR_CATEGORIES
