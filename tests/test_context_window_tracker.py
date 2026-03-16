"""
Tests for V12.4 Context Window Tracker.

Validates:
- ContextUsageRecord to_dict / properties
- CompressionEvent to_dict / properties
- ContextTrackerStats to_dict
- Recording usage and compressions
- Pressure level detection
- Queries (recent usage, high usage, compression history)
- Bounded history
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.memory_pkg.memory.context_window_tracker import (
    CONTEXT_CRITICAL_THRESHOLD,
    CONTEXT_WARNING_THRESHOLD,
    MAX_USAGE_RECORDS,
    CompressionEvent,
    ContextTrackerStats,
    ContextUsageRecord,
    ContextWindowTracker,
    get_context_tracker,
    reset_context_tracker,
)

# =============================================================================
# ContextUsageRecord Tests
# =============================================================================


class TestContextUsageRecord:
    """Test ContextUsageRecord dataclass."""

    def test_utilization(self):
        r = ContextUsageRecord(total_tokens=700, max_tokens=1000)
        assert abs(r.utilization - 0.7) < 0.01

    def test_utilization_zero_max(self):
        r = ContextUsageRecord(total_tokens=100, max_tokens=0)
        assert r.utilization == 0.0

    def test_level_normal(self):
        r = ContextUsageRecord(total_tokens=500, max_tokens=1000)  # 50%
        assert r.level == "normal"

    def test_level_warning(self):
        r = ContextUsageRecord(total_tokens=850, max_tokens=1000)  # 85%
        assert r.level == "warning"

    def test_level_critical(self):
        r = ContextUsageRecord(total_tokens=960, max_tokens=1000)  # 96%
        assert r.level == "critical"

    def test_to_dict(self):
        r = ContextUsageRecord(record_id="ctx_000001", total_tokens=700, max_tokens=1000)
        d = r.to_dict()
        assert d["record_id"] == "ctx_000001"
        assert "utilization" in d
        assert "level" in d


# =============================================================================
# CompressionEvent Tests
# =============================================================================


class TestCompressionEvent:
    """Test CompressionEvent dataclass."""

    def test_compression_ratio(self):
        c = CompressionEvent(original_tokens=1000, compressed_tokens=400)
        # 1.0 - (400/1000) = 0.6 = 60% saved
        assert abs(c.compression_ratio - 0.6) < 0.01

    def test_compression_ratio_zero_original(self):
        c = CompressionEvent(original_tokens=0, compressed_tokens=0)
        assert c.compression_ratio == 0.0

    def test_tokens_saved(self):
        c = CompressionEvent(original_tokens=1000, compressed_tokens=400)
        assert c.tokens_saved == 600

    def test_to_dict(self):
        c = CompressionEvent(original_tokens=1000, compressed_tokens=400)
        d = c.to_dict()
        assert "compression_ratio" in d
        assert "tokens_saved" in d


# =============================================================================
# ContextTrackerStats Tests
# =============================================================================


class TestContextTrackerStats:
    """Test ContextTrackerStats dataclass."""

    def test_to_dict(self):
        s = ContextTrackerStats(total_records=10, total_compressions=3, avg_utilization=0.6, peak_utilization=0.9)
        d = s.to_dict()
        assert d["total_records"] == 10


# =============================================================================
# Usage Recording Tests
# =============================================================================


class TestUsageRecording:
    """Test usage recording."""

    def test_record_basic(self):
        t = ContextWindowTracker()
        r = t.record_usage(session_id="s1", model_id="claude", total_tokens=500, max_tokens=1000)
        assert r.record_id == "ctx_000000"
        assert t.record_count == 1

    def test_auto_compute_total(self):
        t = ContextWindowTracker()
        r = t.record_usage(input_tokens=300, output_tokens=200, max_tokens=1000)
        assert r.total_tokens == 500

    def test_auto_incrementing_ids(self):
        t = ContextWindowTracker()
        r1 = t.record_usage(total_tokens=100)
        r2 = t.record_usage(total_tokens=200)
        assert r1.record_id == "ctx_000000"
        assert r2.record_id == "ctx_000001"

    def test_peak_tracking(self):
        t = ContextWindowTracker()
        t.record_usage(total_tokens=500, max_tokens=1000)  # 0.5
        t.record_usage(total_tokens=900, max_tokens=1000)  # 0.9
        t.record_usage(total_tokens=600, max_tokens=1000)  # 0.6
        stats = t.get_stats()
        assert abs(stats.peak_utilization - 0.9) < 0.01


# =============================================================================
# Compression Recording Tests
# =============================================================================


class TestCompressionRecording:
    """Test compression recording."""

    def test_record_compression(self):
        t = ContextWindowTracker()
        c = t.record_compression(original_tokens=1000, compressed_tokens=400, session_id="s1")
        assert c.original_tokens == 1000
        assert t.compression_count == 1

    def test_multiple_compressions(self):
        t = ContextWindowTracker()
        t.record_compression(original_tokens=1000, compressed_tokens=400)
        t.record_compression(original_tokens=2000, compressed_tokens=800)
        assert t.compression_count == 2


# =============================================================================
# Level Detection Tests
# =============================================================================


class TestLevelDetection:
    """Test current level detection."""

    def test_no_records(self):
        t = ContextWindowTracker()
        assert t.get_current_level() == "normal"

    def test_normal(self):
        t = ContextWindowTracker()
        t.record_usage(total_tokens=500, max_tokens=1000)
        assert t.get_current_level() == "normal"

    def test_warning(self):
        t = ContextWindowTracker()
        t.record_usage(total_tokens=850, max_tokens=1000)
        assert t.get_current_level() == "warning"

    def test_critical(self):
        t = ContextWindowTracker()
        t.record_usage(total_tokens=960, max_tokens=1000)
        assert t.get_current_level() == "critical"


# =============================================================================
# Query Tests
# =============================================================================


class TestQueries:
    """Test query methods."""

    def test_recent_usage(self):
        t = ContextWindowTracker()
        for i in range(5):
            t.record_usage(total_tokens=i * 100)
        recent = t.get_recent_usage(limit=3)
        assert len(recent) == 3

    def test_high_usage_records(self):
        t = ContextWindowTracker()
        t.record_usage(total_tokens=500, max_tokens=1000)  # 50%
        t.record_usage(total_tokens=850, max_tokens=1000)  # 85%
        t.record_usage(total_tokens=950, max_tokens=1000)  # 95%
        high = t.get_high_usage_records()  # default threshold 0.8
        assert len(high) == 2

    def test_compression_history(self):
        t = ContextWindowTracker()
        t.record_compression(original_tokens=1000, compressed_tokens=400)
        t.record_compression(original_tokens=2000, compressed_tokens=800)
        history = t.get_compression_history(limit=1)
        assert len(history) == 1


# =============================================================================
# Bounded History Tests
# =============================================================================


class TestBoundedHistory:
    """Test bounded record history."""

    def test_eviction(self):
        t = ContextWindowTracker(max_records=5)
        for i in range(10):
            t.record_usage(total_tokens=i * 100)
        assert t.record_count == 5


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test tracker statistics."""

    def test_initial_stats(self):
        t = ContextWindowTracker()
        stats = t.get_stats()
        assert stats.total_records == 0

    def test_stats_after_recording(self):
        t = ContextWindowTracker()
        t.record_usage(total_tokens=500, max_tokens=1000)
        t.record_usage(total_tokens=900, max_tokens=1000)
        t.record_compression(original_tokens=1000, compressed_tokens=400)
        stats = t.get_stats()
        assert stats.total_records == 2
        assert stats.total_compressions == 1
        assert stats.total_tokens_saved == 600

    def test_stats_to_dict(self):
        t = ContextWindowTracker()
        d = t.get_stats().to_dict()
        assert "total_records" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_counts(self):
        t = ContextWindowTracker()
        t.record_usage(total_tokens=100)
        t.record_compression(original_tokens=500, compressed_tokens=200)
        assert t.record_count == 1
        assert t.compression_count == 1

    def test_clear(self):
        t = ContextWindowTracker()
        t.record_usage(total_tokens=100)
        t.record_compression(original_tokens=500, compressed_tokens=200)
        t.clear()
        assert t.record_count == 0
        assert t.compression_count == 0

    def test_clear_resets_counter(self):
        t = ContextWindowTracker()
        t.record_usage(total_tokens=100)
        t.clear()
        r = t.record_usage(total_tokens=200)
        assert r.record_id == "ctx_000000"

    def test_to_dict(self):
        t = ContextWindowTracker()
        t.record_usage(total_tokens=100)
        d = t.to_dict()
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global context tracker."""

    def test_get(self):
        reset_context_tracker()
        t = get_context_tracker()
        assert isinstance(t, ContextWindowTracker)

    def test_singleton(self):
        reset_context_tracker()
        t1 = get_context_tracker()
        t2 = get_context_tracker()
        assert t1 is t2

    def test_reset(self):
        reset_context_tracker()
        t1 = get_context_tracker()
        reset_context_tracker()
        t2 = get_context_tracker()
        assert t1 is not t2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_memory_package(self):
        from core.memory_pkg.memory import (
            CompressionEvent,
            ContextTrackerStats,
            ContextUsageRecord,
            ContextWindowTracker,
            get_context_tracker,
            reset_context_tracker,
        )

        assert all(
            [
                ContextWindowTracker,
                ContextUsageRecord,
                CompressionEvent,
                ContextTrackerStats,
                get_context_tracker,
                reset_context_tracker,
            ]
        )

    def test_constants(self):
        assert MAX_USAGE_RECORDS == 50000
        assert CONTEXT_WARNING_THRESHOLD == 0.8
        assert CONTEXT_CRITICAL_THRESHOLD == 0.95
