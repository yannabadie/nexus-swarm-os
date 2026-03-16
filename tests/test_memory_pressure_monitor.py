"""
Tests for V12.4 Memory Pressure Monitor.

Validates:
- MemorySnapshot to_dict / utilization property
- EvictionEvent to_dict
- PressureLevel to_dict
- PressureStats to_dict
- Snapshot recording (auto-incrementing IDs)
- Eviction recording
- Pressure level detection (normal, warning, critical)
- Trend analysis
- Eviction summary
- Queries (recent snapshots, recent evictions, by source)
- Bounded history
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.memory_pkg.memory.memory_pressure_monitor import (
    MAX_SNAPSHOTS,
    PRESSURE_THRESHOLD_WARNING,
    EvictionEvent,
    MemoryPressureMonitor,
    MemorySnapshot,
    PressureLevel,
    PressureStats,
    get_pressure_monitor,
    reset_pressure_monitor,
)

# =============================================================================
# MemorySnapshot Tests
# =============================================================================


class TestMemorySnapshot:
    """Test MemorySnapshot dataclass."""

    def test_basic(self):
        s = MemorySnapshot(cache_items=10, total_bytes=1000, max_bytes=2000)
        assert s.cache_items == 10

    def test_utilization(self):
        s = MemorySnapshot(total_bytes=700, max_bytes=1000)
        assert abs(s.utilization - 0.7) < 0.01

    def test_utilization_zero_max(self):
        s = MemorySnapshot(total_bytes=100, max_bytes=0)
        assert s.utilization == 0.0

    def test_to_dict(self):
        s = MemorySnapshot(snapshot_id="ms_000001", total_bytes=500, max_bytes=1000)
        d = s.to_dict()
        assert d["snapshot_id"] == "ms_000001"
        assert "utilization" in d


# =============================================================================
# EvictionEvent Tests
# =============================================================================


class TestEvictionEvent:
    """Test EvictionEvent dataclass."""

    def test_to_dict(self):
        e = EvictionEvent(reason="lru", items_evicted=5, bytes_freed=1024, source="cache")
        d = e.to_dict()
        assert d["reason"] == "lru"
        assert d["bytes_freed"] == 1024


# =============================================================================
# PressureLevel Tests
# =============================================================================


class TestPressureLevel:
    """Test PressureLevel dataclass."""

    def test_to_dict(self):
        p = PressureLevel(level="warning", utilization=0.75, recommendation="Consider compression")
        d = p.to_dict()
        assert d["level"] == "warning"


# =============================================================================
# PressureStats Tests
# =============================================================================


class TestPressureStats:
    """Test PressureStats dataclass."""

    def test_to_dict(self):
        s = PressureStats(
            total_snapshots=10,
            total_evictions=5,
            total_bytes_freed=5000,
            current_level="normal",
            avg_utilization=0.5,
            peak_utilization=0.8,
        )
        d = s.to_dict()
        assert d["total_snapshots"] == 10


# =============================================================================
# Snapshot Recording Tests
# =============================================================================


class TestSnapshotRecording:
    """Test snapshot recording."""

    def test_record_snapshot(self):
        m = MemoryPressureMonitor()
        s = m.record_snapshot(cache_items=10, total_bytes=500, max_bytes=1000)
        assert s.snapshot_id == "ms_000001"
        assert m.snapshot_count == 1

    def test_auto_incrementing_id(self):
        m = MemoryPressureMonitor()
        s1 = m.record_snapshot(total_bytes=100)
        s2 = m.record_snapshot(total_bytes=200)
        assert s1.snapshot_id == "ms_000001"
        assert s2.snapshot_id == "ms_000002"

    def test_record_multiple(self):
        m = MemoryPressureMonitor()
        m.record_snapshot(total_bytes=100)
        m.record_snapshot(total_bytes=200)
        m.record_snapshot(total_bytes=300)
        assert m.snapshot_count == 3


# =============================================================================
# Eviction Recording Tests
# =============================================================================


class TestEvictionRecording:
    """Test eviction recording."""

    def test_record_eviction(self):
        m = MemoryPressureMonitor()
        e = m.record_eviction(reason="lru", items_evicted=5, bytes_freed=1024, source="cache")
        assert e.reason == "lru"
        assert m.eviction_count == 1

    def test_multiple_evictions(self):
        m = MemoryPressureMonitor()
        m.record_eviction(reason="lru", source="cache")
        m.record_eviction(reason="ttl", source="sessions")
        assert m.eviction_count == 2


# =============================================================================
# Pressure Level Tests
# =============================================================================


class TestPressureLevelDetection:
    """Test pressure level detection."""

    def test_no_snapshots(self):
        m = MemoryPressureMonitor()
        level = m.get_pressure_level()
        assert level.level == "normal"

    def test_normal_pressure(self):
        m = MemoryPressureMonitor()
        m.record_snapshot(total_bytes=500, max_bytes=1000)  # 50%
        level = m.get_pressure_level()
        assert level.level == "normal"

    def test_warning_pressure(self):
        m = MemoryPressureMonitor()
        m.record_snapshot(total_bytes=750, max_bytes=1000)  # 75%
        level = m.get_pressure_level()
        assert level.level == "warning"

    def test_critical_pressure(self):
        m = MemoryPressureMonitor()
        m.record_snapshot(total_bytes=950, max_bytes=1000)  # 95%
        level = m.get_pressure_level()
        assert level.level == "critical"


# =============================================================================
# Trend Analysis Tests
# =============================================================================


class TestTrendAnalysis:
    """Test trend analysis."""

    def test_no_snapshots(self):
        m = MemoryPressureMonitor()
        trend = m.get_trend()
        assert trend["avg_utilization"] == 0.0

    def test_with_snapshots(self):
        m = MemoryPressureMonitor()
        m.record_snapshot(total_bytes=500, max_bytes=1000)
        m.record_snapshot(total_bytes=600, max_bytes=1000)
        trend = m.get_trend(window=2)
        assert trend["avg_utilization"] > 0


# =============================================================================
# Eviction Summary Tests
# =============================================================================


class TestEvictionSummary:
    """Test eviction summary."""

    def test_empty_summary(self):
        m = MemoryPressureMonitor()
        assert m.get_eviction_summary() == {}

    def test_summary_by_reason(self):
        m = MemoryPressureMonitor()
        m.record_eviction(reason="lru")
        m.record_eviction(reason="lru")
        m.record_eviction(reason="ttl")
        summary = m.get_eviction_summary()
        assert summary["lru"] == 2
        assert summary["ttl"] == 1


# =============================================================================
# Query Tests
# =============================================================================


class TestQueries:
    """Test query methods."""

    def test_recent_snapshots(self):
        m = MemoryPressureMonitor()
        for i in range(5):
            m.record_snapshot(total_bytes=i * 100)
        recent = m.get_recent_snapshots(limit=3)
        assert len(recent) == 3

    def test_recent_evictions(self):
        m = MemoryPressureMonitor()
        for _ in range(5):
            m.record_eviction(reason="lru")
        recent = m.get_recent_evictions(limit=3)
        assert len(recent) == 3

    def test_evictions_by_source(self):
        m = MemoryPressureMonitor()
        m.record_eviction(reason="lru", source="cache")
        m.record_eviction(reason="ttl", source="sessions")
        m.record_eviction(reason="lru", source="cache")
        results = m.get_evictions_by_source("cache")
        assert len(results) == 2


# =============================================================================
# Bounded History Tests
# =============================================================================


class TestBoundedHistory:
    """Test bounded history."""

    def test_snapshot_eviction(self):
        m = MemoryPressureMonitor(max_snapshots=5)
        for i in range(10):
            m.record_snapshot(total_bytes=i * 100)
        assert m.snapshot_count == 5

    def test_eviction_eviction(self):
        m = MemoryPressureMonitor(max_evictions=5)
        for _ in range(10):
            m.record_eviction(reason="lru")
        assert m.eviction_count == 5


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test statistics."""

    def test_initial_stats(self):
        m = MemoryPressureMonitor()
        stats = m.get_stats()
        assert stats.total_snapshots == 0

    def test_stats_after_recording(self):
        m = MemoryPressureMonitor()
        m.record_snapshot(total_bytes=500, max_bytes=1000)
        m.record_eviction(reason="lru", bytes_freed=256)
        stats = m.get_stats()
        assert stats.total_snapshots == 1
        assert stats.total_evictions == 1
        assert stats.total_bytes_freed == 256

    def test_stats_to_dict(self):
        m = MemoryPressureMonitor()
        d = m.get_stats().to_dict()
        assert "total_snapshots" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_counts(self):
        m = MemoryPressureMonitor()
        m.record_snapshot(total_bytes=100)
        m.record_eviction(reason="lru")
        assert m.snapshot_count == 1
        assert m.eviction_count == 1

    def test_clear(self):
        m = MemoryPressureMonitor()
        m.record_snapshot(total_bytes=100)
        m.record_eviction(reason="lru")
        m.clear()
        assert m.snapshot_count == 0
        assert m.eviction_count == 0

    def test_clear_resets_counter(self):
        m = MemoryPressureMonitor()
        m.record_snapshot(total_bytes=100)
        m.clear()
        s = m.record_snapshot(total_bytes=200)
        assert s.snapshot_id == "ms_000001"

    def test_to_dict(self):
        m = MemoryPressureMonitor()
        m.record_snapshot(total_bytes=100)
        d = m.to_dict()
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global pressure monitor."""

    def test_get(self):
        reset_pressure_monitor()
        m = get_pressure_monitor()
        assert isinstance(m, MemoryPressureMonitor)

    def test_singleton(self):
        reset_pressure_monitor()
        m1 = get_pressure_monitor()
        m2 = get_pressure_monitor()
        assert m1 is m2

    def test_reset(self):
        reset_pressure_monitor()
        m1 = get_pressure_monitor()
        reset_pressure_monitor()
        m2 = get_pressure_monitor()
        assert m1 is not m2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_memory_package(self):
        from core.memory_pkg.memory import (
            EvictionEvent,
            MemoryPressureMonitor,
            MemorySnapshot,
            PressureLevel,
            PressureStats,
            get_pressure_monitor,
            reset_pressure_monitor,
        )

        assert all(
            [
                MemoryPressureMonitor,
                MemorySnapshot,
                EvictionEvent,
                PressureLevel,
                PressureStats,
                get_pressure_monitor,
                reset_pressure_monitor,
            ]
        )

    def test_constants(self):
        assert MAX_SNAPSHOTS == 10000
        assert PRESSURE_THRESHOLD_WARNING == 0.7
