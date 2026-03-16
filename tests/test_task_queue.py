"""
Tests for V12.4 Swarm Task Queue.

Validates:
- TaskStatus enum values
- SwarmTask creation, is_terminal, to_dict
- QueueStats to_dict
- Enqueue (basic, priority, dependencies)
- Acquire (priority ordering, ready only)
- Complete and dependency unblocking
- Fail and cancel
- Query (get, ready, blocked, result, is_all_complete)
- Remove and max size
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.intelligence.swarm.task_queue import (
    SwarmTask,
    SwarmTaskQueue,
    TaskStatus,
    get_task_queue,
    reset_task_queue,
)

# =============================================================================
# TaskStatus Tests
# =============================================================================


class TestTaskStatus:
    """Test TaskStatus enum."""

    def test_values(self):
        assert TaskStatus.PENDING.value == "pending"
        assert TaskStatus.READY.value == "ready"
        assert TaskStatus.ACQUIRED.value == "acquired"
        assert TaskStatus.COMPLETED.value == "completed"
        assert TaskStatus.FAILED.value == "failed"
        assert TaskStatus.CANCELLED.value == "cancelled"

    def test_count(self):
        assert len(TaskStatus) == 6


# =============================================================================
# SwarmTask Tests
# =============================================================================


class TestSwarmTask:
    """Test SwarmTask dataclass."""

    def test_basic(self):
        t = SwarmTask(task_id="t1", description="test")
        assert t.task_id == "t1"
        assert t.status == TaskStatus.PENDING

    def test_is_terminal(self):
        assert SwarmTask(task_id="t", description="", status=TaskStatus.COMPLETED).is_terminal
        assert SwarmTask(task_id="t", description="", status=TaskStatus.FAILED).is_terminal
        assert SwarmTask(task_id="t", description="", status=TaskStatus.CANCELLED).is_terminal
        assert not SwarmTask(task_id="t", description="", status=TaskStatus.READY).is_terminal

    def test_auto_timestamp(self):
        t = SwarmTask(task_id="t", description="test")
        assert t.created_at > 0

    def test_to_dict(self):
        t = SwarmTask(task_id="t1", description="analyze", priority=3)
        d = t.to_dict()
        assert d["task_id"] == "t1"
        assert d["priority"] == 3


# =============================================================================
# Enqueue Tests
# =============================================================================


class TestEnqueue:
    """Test task enqueuing."""

    def test_enqueue(self):
        q = SwarmTaskQueue()
        tid = q.enqueue("Analyze code")
        assert len(tid) == 12
        assert q.size == 1

    def test_enqueue_ready_by_default(self):
        q = SwarmTaskQueue()
        tid = q.enqueue("task")
        task = q.get_task(tid)
        assert task.status == TaskStatus.READY

    def test_enqueue_pending_with_deps(self):
        q = SwarmTaskQueue()
        t1 = q.enqueue("first")
        t2 = q.enqueue("second", depends_on=[t1])
        task = q.get_task(t2)
        assert task.status == TaskStatus.PENDING

    def test_enqueue_with_priority(self):
        q = SwarmTaskQueue()
        tid = q.enqueue("urgent", priority=5)
        task = q.get_task(tid)
        assert task.priority == 5

    def test_enqueue_with_metadata(self):
        q = SwarmTaskQueue()
        tid = q.enqueue("task", metadata={"domain": "security"})
        task = q.get_task(tid)
        assert task.metadata["domain"] == "security"


# =============================================================================
# Acquire Tests
# =============================================================================


class TestAcquire:
    """Test task acquisition."""

    def test_acquire_highest_priority(self):
        q = SwarmTaskQueue()
        q.enqueue("low", priority=1)
        q.enqueue("high", priority=5)
        q.enqueue("mid", priority=3)
        task = q.acquire()
        assert task.priority == 5

    def test_acquire_sets_acquired(self):
        q = SwarmTaskQueue()
        q.enqueue("task")
        task = q.acquire()
        assert task.status == TaskStatus.ACQUIRED

    def test_acquire_assigns_agent(self):
        q = SwarmTaskQueue()
        q.enqueue("task")
        task = q.acquire(agent_id="claude")
        assert task.assigned_agent == "claude"

    def test_acquire_empty(self):
        q = SwarmTaskQueue()
        assert q.acquire() is None

    def test_acquire_skips_pending(self):
        q = SwarmTaskQueue()
        t1 = q.enqueue("first")
        q.enqueue("second", depends_on=[t1])
        task = q.acquire()
        assert task.task_id == t1

    def test_acquire_skips_already_acquired(self):
        q = SwarmTaskQueue()
        q.enqueue("a")
        q.enqueue("b")
        q.acquire()
        task = q.acquire()
        assert task is not None


# =============================================================================
# Complete Tests
# =============================================================================


class TestComplete:
    """Test task completion."""

    def test_complete(self):
        q = SwarmTaskQueue()
        tid = q.enqueue("task")
        q.acquire()
        assert q.complete(tid, result="done") is True
        task = q.get_task(tid)
        assert task.status == TaskStatus.COMPLETED
        assert task.result == "done"

    def test_complete_unblocks_deps(self):
        q = SwarmTaskQueue()
        t1 = q.enqueue("first")
        t2 = q.enqueue("second", depends_on=[t1])
        q.acquire()
        q.complete(t1)
        task2 = q.get_task(t2)
        assert task2.status == TaskStatus.READY

    def test_complete_multi_deps(self):
        q = SwarmTaskQueue()
        t1 = q.enqueue("a")
        t2 = q.enqueue("b")
        t3 = q.enqueue("c", depends_on=[t1, t2])
        q.acquire()
        q.complete(t1)
        # t3 still pending (t2 not done)
        assert q.get_task(t3).status == TaskStatus.PENDING
        q.acquire()
        q.complete(t2)
        # Now t3 is ready
        assert q.get_task(t3).status == TaskStatus.READY

    def test_complete_not_found(self):
        q = SwarmTaskQueue()
        assert q.complete("missing") is False

    def test_complete_already_terminal(self):
        q = SwarmTaskQueue()
        tid = q.enqueue("task")
        q.acquire()
        q.complete(tid)
        assert q.complete(tid) is False  # Already completed


# =============================================================================
# Fail / Cancel Tests
# =============================================================================


class TestFailCancel:
    """Test fail and cancel."""

    def test_fail(self):
        q = SwarmTaskQueue()
        tid = q.enqueue("task")
        q.acquire()
        assert q.fail(tid, error="timeout") is True
        task = q.get_task(tid)
        assert task.status == TaskStatus.FAILED
        assert task.error == "timeout"

    def test_fail_not_found(self):
        q = SwarmTaskQueue()
        assert q.fail("missing") is False

    def test_cancel(self):
        q = SwarmTaskQueue()
        tid = q.enqueue("task")
        assert q.cancel(tid) is True
        assert q.get_task(tid).status == TaskStatus.CANCELLED

    def test_cancel_terminal(self):
        q = SwarmTaskQueue()
        tid = q.enqueue("task")
        q.acquire()
        q.complete(tid)
        assert q.cancel(tid) is False


# =============================================================================
# Query Tests
# =============================================================================


class TestQuery:
    """Test queries."""

    def test_get_task(self):
        q = SwarmTaskQueue()
        tid = q.enqueue("test")
        assert q.get_task(tid) is not None

    def test_get_task_not_found(self):
        q = SwarmTaskQueue()
        assert q.get_task("missing") is None

    def test_get_ready_tasks(self):
        q = SwarmTaskQueue()
        q.enqueue("a", priority=1)
        q.enqueue("b", priority=3)
        ready = q.get_ready_tasks()
        assert len(ready) == 2
        assert ready[0].priority == 3  # Higher priority first

    def test_get_blocked_tasks(self):
        q = SwarmTaskQueue()
        t1 = q.enqueue("first")
        q.enqueue("blocked", depends_on=[t1])
        blocked = q.get_blocked_tasks()
        assert len(blocked) == 1

    def test_get_result(self):
        q = SwarmTaskQueue()
        tid = q.enqueue("task")
        q.acquire()
        q.complete(tid, result={"data": 42})
        assert q.get_result(tid) == {"data": 42}

    def test_get_result_not_complete(self):
        q = SwarmTaskQueue()
        tid = q.enqueue("task")
        assert q.get_result(tid) is None

    def test_is_all_complete(self):
        q = SwarmTaskQueue()
        t1 = q.enqueue("a")
        t2 = q.enqueue("b")
        assert q.is_all_complete() is False
        q.acquire()
        q.complete(t1)
        q.acquire()
        q.complete(t2)
        assert q.is_all_complete() is True

    def test_is_all_complete_empty(self):
        q = SwarmTaskQueue()
        assert q.is_all_complete() is True


# =============================================================================
# Cleanup Tests
# =============================================================================


class TestCleanup:
    """Test cleanup."""

    def test_remove(self):
        q = SwarmTaskQueue()
        tid = q.enqueue("task")
        assert q.remove(tid) is True
        assert q.size == 0

    def test_remove_not_found(self):
        q = SwarmTaskQueue()
        assert q.remove("missing") is False


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test queue statistics."""

    def test_initial_stats(self):
        q = SwarmTaskQueue()
        stats = q.get_stats()
        assert stats.total_tasks == 0

    def test_stats_after_operations(self):
        q = SwarmTaskQueue()
        t1 = q.enqueue("a")
        q.enqueue("b")
        q.acquire()
        q.complete(t1)
        stats = q.get_stats()
        assert stats.total_tasks == 2
        assert stats.completed_count == 1
        assert stats.ready_count == 1

    def test_stats_to_dict(self):
        q = SwarmTaskQueue()
        d = q.get_stats().to_dict()
        assert "total_tasks" in d
        assert "ready_count" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_size(self):
        q = SwarmTaskQueue()
        q.enqueue("a")
        q.enqueue("b")
        assert q.size == 2

    def test_ready_count(self):
        q = SwarmTaskQueue()
        t1 = q.enqueue("a")
        q.enqueue("b", depends_on=[t1])
        assert q.ready_count == 1

    def test_clear(self):
        q = SwarmTaskQueue()
        q.enqueue("a")
        q.clear()
        assert q.size == 0

    def test_to_dict(self):
        q = SwarmTaskQueue()
        q.enqueue("a")
        d = q.to_dict()
        assert d["size"] == 1
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global task queue."""

    def test_get_task_queue(self):
        reset_task_queue()
        q = get_task_queue()
        assert isinstance(q, SwarmTaskQueue)

    def test_singleton(self):
        reset_task_queue()
        q1 = get_task_queue()
        q2 = get_task_queue()
        assert q1 is q2

    def test_reset(self):
        reset_task_queue()
        q1 = get_task_queue()
        reset_task_queue()
        q2 = get_task_queue()
        assert q1 is not q2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_swarm_package(self):
        from core.intelligence.swarm import (
            QueueStats,
            SwarmTask,
            SwarmTaskQueue,
            SwarmTaskStatus,
            get_task_queue,
            reset_task_queue,
        )

        assert all(
            [
                SwarmTaskQueue,
                SwarmTask,
                SwarmTaskStatus,
                QueueStats,
                get_task_queue,
                reset_task_queue,
            ]
        )

    def test_from_module(self):
        from core.intelligence.swarm.task_queue import (
            MAX_QUEUE_SIZE,
        )

        assert MAX_QUEUE_SIZE == 10000
