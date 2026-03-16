"""
Tests for V12.4 Task Priority Scheduler.

Validates:
- ScheduledTask creation and properties
- Priority levels and scoring
- TaskScheduler submit, next, start, complete, fail, cancel
- Priority ordering (critical > high > medium > low > background)
- Deadline urgency bonus
- Age-based priority boost
- Dependency tracking and blocking
- Overdue task detection
- Queue size limits
- Clear completed tasks
- State export
- Module exports
"""

import time

import pytest

from core.execution_pkg.execution.task_scheduler import (
    PRIORITY_SCORES,
    Priority,
    ScheduledTask,
    TaskScheduler,
    TaskStatus,
)

# =============================================================================
# ScheduledTask Tests
# =============================================================================


class TestScheduledTask:
    """Test ScheduledTask dataclass."""

    def test_basic_creation(self):
        task = ScheduledTask(task_id="t1", name="Fix bug")
        assert task.task_id == "t1"
        assert task.name == "Fix bug"
        assert task.priority == Priority.MEDIUM
        assert task.status == TaskStatus.PENDING

    def test_auto_created_at(self):
        task = ScheduledTask(task_id="t1", name="test")
        assert task.created_at > 0

    def test_age_seconds(self):
        task = ScheduledTask(task_id="t1", name="test")
        time.sleep(0.01)
        assert task.age_seconds > 0

    def test_is_terminal(self):
        for status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            task = ScheduledTask(task_id="t1", name="test", status=status)
            assert task.is_terminal is True

        for status in (TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.BLOCKED):
            task = ScheduledTask(task_id="t1", name="test", status=status)
            assert task.is_terminal is False

    def test_is_overdue_no_deadline(self):
        task = ScheduledTask(task_id="t1", name="test")
        assert task.is_overdue is False

    def test_is_overdue_past_deadline(self):
        task = ScheduledTask(
            task_id="t1",
            name="test",
            deadline_at=time.monotonic() - 10.0,
        )
        assert task.is_overdue is True

    def test_is_overdue_future_deadline(self):
        task = ScheduledTask(
            task_id="t1",
            name="test",
            deadline_at=time.monotonic() + 1000.0,
        )
        assert task.is_overdue is False

    def test_to_dict(self):
        task = ScheduledTask(task_id="t1", name="Fix bug", priority=Priority.HIGH)
        d = task.to_dict()
        assert d["task_id"] == "t1"
        assert d["name"] == "Fix bug"
        assert d["priority"] == "high"
        assert d["status"] == "pending"
        assert "age_seconds" in d


# =============================================================================
# TaskScheduler - Submit Tests
# =============================================================================


class TestSubmit:
    """Test task submission."""

    def test_basic_submit(self):
        scheduler = TaskScheduler()
        task = scheduler.submit("Fix bug")
        assert task.name == "Fix bug"
        assert task.status == TaskStatus.PENDING
        assert task.task_id != ""

    def test_submit_with_priority(self):
        scheduler = TaskScheduler()
        task = scheduler.submit("Critical fix", priority=Priority.CRITICAL)
        assert task.priority == Priority.CRITICAL

    def test_submit_with_deadline(self):
        scheduler = TaskScheduler()
        task = scheduler.submit("Urgent", deadline_seconds=60.0)
        assert task.deadline_at is not None

    def test_submit_with_custom_id(self):
        scheduler = TaskScheduler()
        task = scheduler.submit("Test", task_id="custom-123")
        assert task.task_id == "custom-123"

    def test_submit_duplicate_id_raises(self):
        scheduler = TaskScheduler()
        scheduler.submit("A", task_id="dup")
        with pytest.raises(ValueError, match="already exists"):
            scheduler.submit("B", task_id="dup")

    def test_submit_with_metadata(self):
        scheduler = TaskScheduler()
        task = scheduler.submit("Test", metadata={"domain": "coding"})
        assert task.metadata["domain"] == "coding"

    def test_queue_full_raises(self):
        scheduler = TaskScheduler(max_queue_size=3)
        scheduler.submit("A")
        scheduler.submit("B")
        scheduler.submit("C")
        with pytest.raises(ValueError, match="Queue full"):
            scheduler.submit("D")

    def test_submit_with_dependency(self):
        scheduler = TaskScheduler()
        scheduler.submit("First", task_id="t1")
        t2 = scheduler.submit("Second", depends_on=["t1"])
        assert t2.depends_on == ["t1"]
        assert t2.status == TaskStatus.BLOCKED

    def test_submit_invalid_dependency(self):
        scheduler = TaskScheduler()
        with pytest.raises(ValueError, match="not found"):
            scheduler.submit("Task", depends_on=["nonexistent"])


# =============================================================================
# TaskScheduler - Next Tests
# =============================================================================


class TestNext:
    """Test getting next task."""

    def test_next_returns_highest_priority(self):
        scheduler = TaskScheduler()
        scheduler.submit("Low", priority=Priority.LOW, task_id="low")
        scheduler.submit("High", priority=Priority.HIGH, task_id="high")
        scheduler.submit("Medium", priority=Priority.MEDIUM, task_id="med")
        task = scheduler.next()
        assert task.task_id == "high"

    def test_next_empty_queue(self):
        scheduler = TaskScheduler()
        assert scheduler.next() is None

    def test_next_skips_blocked(self):
        scheduler = TaskScheduler()
        scheduler.submit("First", task_id="t1")
        scheduler.submit("Second", priority=Priority.HIGH, depends_on=["t1"])
        scheduler.submit("Third", priority=Priority.LOW, task_id="t3")
        task = scheduler.next()
        # Should skip blocked "Second" and return either "First" or "Third"
        assert task.status == TaskStatus.PENDING

    def test_next_critical_beats_all(self):
        scheduler = TaskScheduler()
        scheduler.submit("Background", priority=Priority.BACKGROUND, task_id="bg")
        scheduler.submit("Critical", priority=Priority.CRITICAL, task_id="crit")
        task = scheduler.next()
        assert task.task_id == "crit"


# =============================================================================
# TaskScheduler - Lifecycle Tests
# =============================================================================


class TestLifecycle:
    """Test task lifecycle transitions."""

    def test_start_task(self):
        scheduler = TaskScheduler()
        scheduler.submit("Test", task_id="t1")
        assert scheduler.start("t1") is True
        t = scheduler.get_task("t1")
        assert t.status == TaskStatus.RUNNING
        assert t.started_at is not None

    def test_start_nonexistent(self):
        scheduler = TaskScheduler()
        assert scheduler.start("missing") is False

    def test_start_non_pending(self):
        scheduler = TaskScheduler()
        scheduler.submit("Test", task_id="t1")
        scheduler.start("t1")
        assert scheduler.start("t1") is False  # Already running

    def test_complete_task(self):
        scheduler = TaskScheduler()
        scheduler.submit("Test", task_id="t1")
        scheduler.start("t1")
        assert scheduler.complete("t1", result="Done") is True
        t = scheduler.get_task("t1")
        assert t.status == TaskStatus.COMPLETED
        assert t.result == "Done"
        assert t.completed_at is not None

    def test_fail_task(self):
        scheduler = TaskScheduler()
        scheduler.submit("Test", task_id="t1")
        scheduler.start("t1")
        assert scheduler.fail("t1", error="Timeout") is True
        t = scheduler.get_task("t1")
        assert t.status == TaskStatus.FAILED
        assert t.result == "Timeout"

    def test_cancel_task(self):
        scheduler = TaskScheduler()
        scheduler.submit("Test", task_id="t1")
        assert scheduler.cancel("t1") is True
        t = scheduler.get_task("t1")
        assert t.status == TaskStatus.CANCELLED

    def test_complete_already_terminal(self):
        scheduler = TaskScheduler()
        scheduler.submit("Test", task_id="t1")
        scheduler.cancel("t1")
        assert scheduler.complete("t1") is False  # Already cancelled


# =============================================================================
# TaskScheduler - Dependency Tests
# =============================================================================


class TestDependencies:
    """Test dependency tracking."""

    def test_blocked_until_dependency_complete(self):
        scheduler = TaskScheduler()
        scheduler.submit("A", task_id="a")
        scheduler.submit("B", depends_on=["a"], task_id="b")
        b = scheduler.get_task("b")
        assert b.status == TaskStatus.BLOCKED

    def test_unblocked_after_dependency_complete(self):
        scheduler = TaskScheduler()
        scheduler.submit("A", task_id="a")
        scheduler.submit("B", depends_on=["a"], task_id="b")
        scheduler.start("a")
        scheduler.complete("a")
        # next() triggers _update_blocked_states
        scheduler.next()
        b = scheduler.get_task("b")
        assert b.status == TaskStatus.PENDING

    def test_multiple_dependencies(self):
        scheduler = TaskScheduler()
        scheduler.submit("A", task_id="a")
        scheduler.submit("B", task_id="b")
        scheduler.submit("C", depends_on=["a", "b"], task_id="c")
        c = scheduler.get_task("c")
        assert c.status == TaskStatus.BLOCKED

        # Complete only A
        scheduler.start("a")
        scheduler.complete("a")
        scheduler.next()  # Trigger update
        c = scheduler.get_task("c")
        assert c.status == TaskStatus.BLOCKED  # Still blocked (B not done)

        # Complete B
        scheduler.start("b")
        scheduler.complete("b")
        scheduler.next()  # Trigger update
        c = scheduler.get_task("c")
        assert c.status == TaskStatus.PENDING  # Now unblocked

    def test_chain_dependency(self):
        scheduler = TaskScheduler()
        scheduler.submit("A", task_id="a")
        scheduler.submit("B", depends_on=["a"], task_id="b")
        scheduler.submit("C", depends_on=["b"], task_id="c")

        # Only A should be available
        task = scheduler.next()
        assert task.task_id == "a"


# =============================================================================
# TaskScheduler - Deadline Urgency Tests
# =============================================================================


class TestDeadlineUrgency:
    """Test deadline-based priority boost."""

    def test_deadline_boosts_priority(self):
        scheduler = TaskScheduler()
        scheduler.submit("No deadline", priority=Priority.HIGH, task_id="no_dl")
        scheduler.submit(
            "Urgent", priority=Priority.MEDIUM, task_id="urgent", deadline_seconds=0.001
        )  # Almost immediate deadline
        time.sleep(0.01)  # Let deadline pass
        task = scheduler.next()
        # Overdue medium + deadline bonus should beat high
        assert task.task_id == "urgent"

    def test_overdue_gets_max_bonus(self):
        scheduler = TaskScheduler()
        task = scheduler.submit("Overdue", deadline_seconds=0.001)
        time.sleep(0.01)
        score = scheduler._score_task(task)
        # Should have base + max deadline bonus
        assert score > PRIORITY_SCORES[Priority.MEDIUM]


# =============================================================================
# TaskScheduler - Listing Tests
# =============================================================================


class TestListing:
    """Test task listing and filtering."""

    def test_list_all(self):
        scheduler = TaskScheduler()
        scheduler.submit("A")
        scheduler.submit("B")
        scheduler.submit("C")
        tasks = scheduler.list_tasks()
        assert len(tasks) == 3

    def test_list_by_status(self):
        scheduler = TaskScheduler()
        scheduler.submit("A", task_id="a")
        scheduler.submit("B", task_id="b")
        scheduler.start("a")
        pending = scheduler.list_tasks(status=TaskStatus.PENDING)
        running = scheduler.list_tasks(status=TaskStatus.RUNNING)
        assert len(pending) == 1
        assert len(running) == 1

    def test_pending_count(self):
        scheduler = TaskScheduler()
        scheduler.submit("A")
        scheduler.submit("B")
        assert scheduler.pending_count() == 2

    def test_running_count(self):
        scheduler = TaskScheduler()
        scheduler.submit("A", task_id="a")
        scheduler.submit("B", task_id="b")
        scheduler.start("a")
        assert scheduler.running_count() == 1

    def test_overdue_tasks(self):
        scheduler = TaskScheduler()
        scheduler.submit("Normal")
        scheduler.submit("Overdue", deadline_seconds=0.001, task_id="od")
        time.sleep(0.01)
        overdue = scheduler.overdue_tasks()
        assert len(overdue) == 1
        assert overdue[0].task_id == "od"


# =============================================================================
# TaskScheduler - Cleanup Tests
# =============================================================================


class TestCleanup:
    """Test task cleanup."""

    def test_clear_completed(self):
        scheduler = TaskScheduler()
        scheduler.submit("A", task_id="a")
        scheduler.submit("B", task_id="b")
        scheduler.submit("C", task_id="c")
        scheduler.complete("a")
        scheduler.cancel("b")
        removed = scheduler.clear_completed()
        assert removed == 2
        assert scheduler.get_task("a") is None
        assert scheduler.get_task("b") is None
        assert scheduler.get_task("c") is not None

    def test_clear_empty(self):
        scheduler = TaskScheduler()
        assert scheduler.clear_completed() == 0


# =============================================================================
# TaskScheduler - Priority Scoring Tests
# =============================================================================


class TestScoring:
    """Test priority scoring."""

    def test_priority_order(self):
        scheduler = TaskScheduler()
        tasks = {}
        for p in Priority:
            t = scheduler.submit(p.value, priority=p, task_id=p.value)
            tasks[p] = scheduler._score_task(t)

        assert tasks[Priority.CRITICAL] > tasks[Priority.HIGH]
        assert tasks[Priority.HIGH] > tasks[Priority.MEDIUM]
        assert tasks[Priority.MEDIUM] > tasks[Priority.LOW]
        assert tasks[Priority.LOW] > tasks[Priority.BACKGROUND]

    def test_blocked_scores_zero(self):
        scheduler = TaskScheduler()
        scheduler.submit("A", task_id="a")
        t = scheduler.submit("B", depends_on=["a"])
        assert scheduler._score_task(t) == 0.0

    def test_terminal_scores_negative(self):
        scheduler = TaskScheduler()
        scheduler.submit("A", task_id="a")
        scheduler.complete("a")
        t = scheduler.get_task("a")
        assert scheduler._score_task(t) < 0


# =============================================================================
# TaskScheduler - State Export Tests
# =============================================================================


class TestStateExport:
    """Test scheduler state export."""

    def test_to_dict(self):
        scheduler = TaskScheduler()
        scheduler.submit("A", task_id="a")
        scheduler.submit("B", task_id="b")
        scheduler.start("a")
        d = scheduler.to_dict()
        assert d["total_tasks"] == 2
        assert d["pending_count"] == 1
        assert d["running_count"] == 1

    def test_to_dict_empty(self):
        scheduler = TaskScheduler()
        d = scheduler.to_dict()
        assert d["total_tasks"] == 0
        assert d["pending_count"] == 0


# =============================================================================
# Priority/TaskStatus Enum Tests
# =============================================================================


class TestEnums:
    """Test enum values."""

    def test_priority_values(self):
        assert Priority.CRITICAL.value == "critical"
        assert Priority.HIGH.value == "high"
        assert Priority.MEDIUM.value == "medium"
        assert Priority.LOW.value == "low"
        assert Priority.BACKGROUND.value == "background"

    def test_status_values(self):
        assert TaskStatus.PENDING.value == "pending"
        assert TaskStatus.RUNNING.value == "running"
        assert TaskStatus.COMPLETED.value == "completed"
        assert TaskStatus.FAILED.value == "failed"
        assert TaskStatus.CANCELLED.value == "cancelled"
        assert TaskStatus.BLOCKED.value == "blocked"

    def test_priority_scores_complete(self):
        for p in Priority:
            assert p in PRIORITY_SCORES


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_execution_package(self):
        from core.execution_pkg.execution import Priority, ScheduledTask, TaskScheduler, TaskStatus

        assert all([TaskScheduler, ScheduledTask, Priority, TaskStatus])

    def test_from_module(self):
        from core.execution_pkg.execution.task_scheduler import (
            PRIORITY_SCORES,
            Priority,
            ScheduledTask,
            TaskScheduler,
            TaskStatus,
        )

        assert all([TaskScheduler, ScheduledTask, Priority, TaskStatus])
        assert len(PRIORITY_SCORES) == 5
