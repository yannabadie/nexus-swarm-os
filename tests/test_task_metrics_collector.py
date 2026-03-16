"""
Tests for V12.4 Task Metrics Collector.

Validates:
- TaskRecord to_dict / is_slow property
- TaskTypeMetrics to_dict / properties
- CollectorStats to_dict
- Task lifecycle (start, complete, fail, cancel)
- Metrics updates
- Queries (type metrics, slow tasks, recent tasks, subtasks)
- Bounded history
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.foundation.async_primitives.task_metrics_collector import (
    MAX_TASK_RECORDS,
    SLOW_TASK_THRESHOLD_MS,
    CollectorStats,
    TaskMetricsCollector,
    TaskRecord,
    TaskTypeMetrics,
    get_task_metrics_collector,
    reset_task_metrics_collector,
)

# =============================================================================
# TaskRecord Tests
# =============================================================================


class TestTaskRecord:
    """Test TaskRecord dataclass."""

    def test_defaults(self):
        r = TaskRecord(task_id="t1", task_type="tool_exec")
        assert r.status == "pending"
        assert r.created_at != ""

    def test_is_slow_false(self):
        r = TaskRecord(duration_ms=100.0)
        assert r.is_slow is False

    def test_is_slow_true(self):
        r = TaskRecord(duration_ms=SLOW_TASK_THRESHOLD_MS + 1)
        assert r.is_slow is True

    def test_to_dict(self):
        r = TaskRecord(task_id="t1", task_type="llm_call", status="completed")
        d = r.to_dict()
        assert d["task_id"] == "t1"
        assert "is_slow" in d


# =============================================================================
# TaskTypeMetrics Tests
# =============================================================================


class TestTaskTypeMetrics:
    """Test TaskTypeMetrics dataclass."""

    def test_avg_duration(self):
        m = TaskTypeMetrics(task_type="t", completed_count=4, total_duration_ms=400.0)
        assert abs(m.avg_duration_ms - 100.0) < 0.01

    def test_avg_duration_zero(self):
        m = TaskTypeMetrics(task_type="t")
        assert m.avg_duration_ms == 0.0

    def test_success_rate(self):
        m = TaskTypeMetrics(task_type="t", total_count=10, completed_count=8)
        assert abs(m.success_rate - 0.8) < 0.01

    def test_success_rate_zero(self):
        m = TaskTypeMetrics(task_type="t")
        assert m.success_rate == 0.0

    def test_to_dict(self):
        m = TaskTypeMetrics(task_type="tool_exec", total_count=5, completed_count=4)
        d = m.to_dict()
        assert "success_rate" in d
        assert "avg_duration_ms" in d


# =============================================================================
# CollectorStats Tests
# =============================================================================


class TestCollectorStats:
    """Test CollectorStats dataclass."""

    def test_to_dict(self):
        s = CollectorStats(total_tasks=20, active_tasks=2, completed_tasks=15)
        d = s.to_dict()
        assert d["total_tasks"] == 20


# =============================================================================
# Task Lifecycle Tests
# =============================================================================


class TestTaskLifecycle:
    """Test task start/complete/fail/cancel lifecycle."""

    def test_start_task(self):
        c = TaskMetricsCollector()
        r = c.start_task("tool_execution")
        assert r.task_id == "task_000001"
        assert r.status == "running"
        assert c.active_count == 1

    def test_start_with_custom_id(self):
        c = TaskMetricsCollector()
        r = c.start_task("llm_call", task_id="custom_1")
        assert r.task_id == "custom_1"

    def test_start_with_parent(self):
        c = TaskMetricsCollector()
        r = c.start_task("io_op", parent_task_id="parent_1")
        assert r.parent_task_id == "parent_1"

    def test_complete_task(self):
        c = TaskMetricsCollector()
        r = c.start_task("tool_execution")
        completed = c.complete_task(r.task_id)
        assert completed is not None
        assert completed.status == "completed"
        assert completed.duration_ms >= 0
        assert c.active_count == 0
        assert c.task_count == 1

    def test_complete_not_found(self):
        c = TaskMetricsCollector()
        assert c.complete_task("nonexistent") is None

    def test_fail_task(self):
        c = TaskMetricsCollector()
        r = c.start_task("llm_call")
        failed = c.fail_task(r.task_id, error="Timeout")
        assert failed is not None
        assert failed.status == "failed"
        assert failed.error == "Timeout"
        assert c.active_count == 0
        assert c.task_count == 1

    def test_fail_not_found(self):
        c = TaskMetricsCollector()
        assert c.fail_task("nonexistent") is None

    def test_cancel_task(self):
        c = TaskMetricsCollector()
        r = c.start_task("io_op")
        cancelled = c.cancel_task(r.task_id)
        assert cancelled is not None
        assert cancelled.status == "cancelled"
        assert c.active_count == 0

    def test_cancel_not_found(self):
        c = TaskMetricsCollector()
        assert c.cancel_task("nonexistent") is None

    def test_auto_incrementing_ids(self):
        c = TaskMetricsCollector()
        r1 = c.start_task("a")
        r2 = c.start_task("b")
        assert r1.task_id == "task_000001"
        assert r2.task_id == "task_000002"


# =============================================================================
# Metrics Update Tests
# =============================================================================


class TestMetricsUpdate:
    """Test that metrics are updated on lifecycle events."""

    def test_complete_updates_metrics(self):
        c = TaskMetricsCollector()
        r = c.start_task("tool_exec")
        c.complete_task(r.task_id)
        m = c.get_type_metrics("tool_exec")
        assert m is not None
        assert m.total_count == 1
        assert m.completed_count == 1

    def test_fail_updates_metrics(self):
        c = TaskMetricsCollector()
        r = c.start_task("tool_exec")
        c.fail_task(r.task_id, error="err")
        m = c.get_type_metrics("tool_exec")
        assert m.failed_count == 1

    def test_cancel_updates_metrics(self):
        c = TaskMetricsCollector()
        r = c.start_task("tool_exec")
        c.cancel_task(r.task_id)
        m = c.get_type_metrics("tool_exec")
        assert m.cancelled_count == 1

    def test_multiple_types(self):
        c = TaskMetricsCollector()
        r1 = c.start_task("a")
        r2 = c.start_task("b")
        c.complete_task(r1.task_id)
        c.complete_task(r2.task_id)
        assert len(c.get_all_metrics()) == 2


# =============================================================================
# Query Tests
# =============================================================================


class TestQueries:
    """Test query methods."""

    def test_get_task_active(self):
        c = TaskMetricsCollector()
        r = c.start_task("a")
        found = c.get_task(r.task_id)
        assert found is not None
        assert found.task_id == r.task_id

    def test_get_task_completed(self):
        c = TaskMetricsCollector()
        r = c.start_task("a")
        c.complete_task(r.task_id)
        found = c.get_task(r.task_id)
        assert found is not None
        assert found.status == "completed"

    def test_get_task_not_found(self):
        c = TaskMetricsCollector()
        assert c.get_task("nonexistent") is None

    def test_get_type_metrics_not_found(self):
        c = TaskMetricsCollector()
        assert c.get_type_metrics("missing") is None

    def test_get_all_metrics_sorted(self):
        c = TaskMetricsCollector()
        for _ in range(3):
            r = c.start_task("a")
            c.complete_task(r.task_id)
        r = c.start_task("b")
        c.complete_task(r.task_id)
        metrics = c.get_all_metrics()
        assert metrics[0].task_type == "a"  # 3 > 1

    def test_get_slow_tasks(self):
        c = TaskMetricsCollector()
        # Create a record manually that is slow
        r = c.start_task("slow_op")
        c.complete_task(r.task_id)
        # The duration will be very short, so manually set it
        c._records[-1].duration_ms = SLOW_TASK_THRESHOLD_MS + 100
        slow = c.get_slow_tasks()
        assert len(slow) == 1

    def test_get_recent_tasks(self):
        c = TaskMetricsCollector()
        for _ in range(5):
            r = c.start_task("a")
            c.complete_task(r.task_id)
        recent = c.get_recent_tasks(limit=3)
        assert len(recent) == 3

    def test_get_subtasks(self):
        c = TaskMetricsCollector()
        parent = c.start_task("parent")
        child1 = c.start_task("child", parent_task_id=parent.task_id)
        child2 = c.start_task("child", parent_task_id=parent.task_id)
        other = c.start_task("other")
        c.complete_task(child1.task_id)
        c.complete_task(child2.task_id)
        c.complete_task(other.task_id)
        subtasks = c.get_subtasks(parent.task_id)
        assert len(subtasks) == 2


# =============================================================================
# Bounded History Tests
# =============================================================================


class TestBoundedHistory:
    """Test bounded record history."""

    def test_eviction(self):
        c = TaskMetricsCollector(max_records=5)
        for _ in range(10):
            r = c.start_task("a")
            c.complete_task(r.task_id)
        assert c.task_count == 5


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test collector statistics."""

    def test_initial_stats(self):
        c = TaskMetricsCollector()
        stats = c.get_stats()
        assert stats.total_tasks == 0

    def test_stats_after_recording(self):
        c = TaskMetricsCollector()
        r1 = c.start_task("a")
        c.complete_task(r1.task_id)
        r2 = c.start_task("b")
        c.fail_task(r2.task_id, error="err")
        stats = c.get_stats()
        assert stats.total_tasks == 2
        assert stats.completed_tasks == 1
        assert stats.failed_tasks == 1
        assert stats.unique_task_types == 2

    def test_stats_to_dict(self):
        c = TaskMetricsCollector()
        d = c.get_stats().to_dict()
        assert "total_tasks" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_counts(self):
        c = TaskMetricsCollector()
        r = c.start_task("a")
        assert c.active_count == 1
        c.complete_task(r.task_id)
        assert c.task_count == 1
        assert c.active_count == 0

    def test_clear(self):
        c = TaskMetricsCollector()
        r = c.start_task("a")
        c.complete_task(r.task_id)
        c.clear()
        assert c.task_count == 0
        assert c.active_count == 0
        assert c.get_type_metrics("a") is None

    def test_clear_resets_counter(self):
        c = TaskMetricsCollector()
        c.start_task("a")
        c.clear()
        r = c.start_task("b")
        assert r.task_id == "task_000001"

    def test_to_dict(self):
        c = TaskMetricsCollector()
        r = c.start_task("a")
        c.complete_task(r.task_id)
        d = c.to_dict()
        assert "stats" in d
        assert d["task_count"] == 1


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global task metrics collector."""

    def test_get(self):
        reset_task_metrics_collector()
        c = get_task_metrics_collector()
        assert isinstance(c, TaskMetricsCollector)

    def test_singleton(self):
        reset_task_metrics_collector()
        c1 = get_task_metrics_collector()
        c2 = get_task_metrics_collector()
        assert c1 is c2

    def test_reset(self):
        reset_task_metrics_collector()
        c1 = get_task_metrics_collector()
        reset_task_metrics_collector()
        c2 = get_task_metrics_collector()
        assert c1 is not c2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_async_primitives_package(self):
        from core.foundation.async_primitives import (
            CollectorStats,
            TaskMetricsCollector,
            TaskRecord,
            TaskTypeMetrics,
            get_task_metrics_collector,
            reset_task_metrics_collector,
        )

        assert all(
            [
                TaskMetricsCollector,
                TaskRecord,
                TaskTypeMetrics,
                CollectorStats,
                get_task_metrics_collector,
                reset_task_metrics_collector,
            ]
        )

    def test_constants(self):
        from core.foundation.async_primitives.task_metrics_collector import (
            SLOW_TASK_THRESHOLD_MS,
        )

        assert MAX_TASK_RECORDS == 50000
        assert SLOW_TASK_THRESHOLD_MS == 5000.0
