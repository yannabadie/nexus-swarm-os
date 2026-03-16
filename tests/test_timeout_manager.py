"""
Tests for V12.4 Execution Timeout Manager.

Validates:
- TimeoutConfig to_dict
- Deadline properties and to_dict
- TimeoutEvent to_dict
- TimeoutStats to_dict
- Tool timeout configuration (configure, unconfigure, get, list)
- Deadline tracking (set, get, remaining, expired, cancel, cleanup)
- Timeout events (record, filter)
- Statistics
- State management
- Global singleton
- Module exports
"""

import time

from core.execution_pkg.execution.timeout_manager import (
    DEFAULT_TIMEOUT,
    MAX_TIMEOUT,
    Deadline,
    TimeoutConfig,
    TimeoutEvent,
    TimeoutManager,
    TimeoutStats,
    get_timeout_manager,
    reset_timeout_manager,
)

# =============================================================================
# TimeoutConfig Tests
# =============================================================================


class TestTimeoutConfig:
    """Test TimeoutConfig dataclass."""

    def test_defaults(self):
        c = TimeoutConfig(name="tool")
        assert c.timeout_seconds == DEFAULT_TIMEOUT

    def test_custom(self):
        c = TimeoutConfig(name="ai", timeout_seconds=60.0)
        assert c.timeout_seconds == 60.0

    def test_to_dict(self):
        c = TimeoutConfig(name="ai", timeout_seconds=60.0, description="AI calls")
        d = c.to_dict()
        assert d["name"] == "ai"
        assert d["timeout_seconds"] == 60.0


# =============================================================================
# Deadline Tests
# =============================================================================


class TestDeadline:
    """Test Deadline dataclass."""

    def test_auto_created_at(self):
        d = Deadline(task_id="t1", deadline_at=time.monotonic() + 100)
        assert d.created_at > 0

    def test_remaining(self):
        d = Deadline(task_id="t1", deadline_at=time.monotonic() + 100)
        assert d.remaining > 99

    def test_remaining_expired(self):
        d = Deadline(task_id="t1", deadline_at=time.monotonic() - 1)
        assert d.remaining == 0.0

    def test_is_expired(self):
        d = Deadline(task_id="t1", deadline_at=time.monotonic() - 1)
        assert d.is_expired is True

    def test_not_expired(self):
        d = Deadline(task_id="t1", deadline_at=time.monotonic() + 100)
        assert d.is_expired is False

    def test_to_dict(self):
        d = Deadline(task_id="t1", deadline_at=time.monotonic() + 100, label="urgent")
        dd = d.to_dict()
        assert dd["task_id"] == "t1"
        assert dd["is_expired"] is False
        assert dd["label"] == "urgent"


# =============================================================================
# TimeoutEvent Tests
# =============================================================================


class TestTimeoutEvent:
    """Test TimeoutEvent dataclass."""

    def test_basic(self):
        e = TimeoutEvent(tool_name="bash", timeout_seconds=30.0)
        assert e.timestamp > 0

    def test_to_dict(self):
        e = TimeoutEvent(tool_name="bash", timeout_seconds=30.0)
        d = e.to_dict()
        assert d["tool_name"] == "bash"
        assert d["timeout_seconds"] == 30.0


# =============================================================================
# TimeoutStats Tests
# =============================================================================


class TestTimeoutStats:
    """Test TimeoutStats dataclass."""

    def test_to_dict(self):
        s = TimeoutStats(configured_tools=3, active_deadlines=2, expired_deadlines=1, total_timeouts_recorded=5)
        d = s.to_dict()
        assert d["configured_tools"] == 3
        assert d["total_timeouts_recorded"] == 5


# =============================================================================
# Tool Configuration Tests
# =============================================================================


class TestToolConfiguration:
    """Test tool timeout configuration."""

    def test_configure(self):
        mgr = TimeoutManager()
        c = mgr.configure("bash", timeout_seconds=10.0)
        assert c.name == "bash"
        assert mgr.config_count == 1

    def test_configure_caps_at_max(self):
        mgr = TimeoutManager()
        c = mgr.configure("long_task", timeout_seconds=9999.0)
        assert c.timeout_seconds == MAX_TIMEOUT

    def test_unconfigure(self):
        mgr = TimeoutManager()
        mgr.configure("bash")
        assert mgr.unconfigure("bash") is True
        assert mgr.config_count == 0

    def test_unconfigure_not_found(self):
        mgr = TimeoutManager()
        assert mgr.unconfigure("missing") is False

    def test_get_timeout(self):
        mgr = TimeoutManager()
        mgr.configure("bash", timeout_seconds=10.0)
        assert mgr.get_timeout("bash") == 10.0

    def test_get_timeout_default(self):
        mgr = TimeoutManager()
        assert mgr.get_timeout("unknown") == DEFAULT_TIMEOUT

    def test_get_config(self):
        mgr = TimeoutManager()
        mgr.configure("bash", timeout_seconds=10.0)
        c = mgr.get_config("bash")
        assert c is not None
        assert c.timeout_seconds == 10.0

    def test_get_config_not_found(self):
        mgr = TimeoutManager()
        assert mgr.get_config("missing") is None

    def test_list_configs(self):
        mgr = TimeoutManager()
        mgr.configure("a")
        mgr.configure("b")
        assert len(mgr.list_configs()) == 2


# =============================================================================
# Deadline Tests
# =============================================================================


class TestDeadlineTracking:
    """Test deadline management."""

    def test_set_deadline(self):
        mgr = TimeoutManager()
        d = mgr.set_deadline("task-1", seconds=60.0)
        assert d.task_id == "task-1"
        assert mgr.deadline_count == 1

    def test_set_deadline_with_label(self):
        mgr = TimeoutManager()
        d = mgr.set_deadline("task-1", seconds=60.0, label="urgent")
        assert d.label == "urgent"

    def test_get_deadline(self):
        mgr = TimeoutManager()
        mgr.set_deadline("task-1", seconds=60.0)
        d = mgr.get_deadline("task-1")
        assert d is not None
        assert d.task_id == "task-1"

    def test_get_deadline_not_found(self):
        mgr = TimeoutManager()
        assert mgr.get_deadline("missing") is None

    def test_remaining(self):
        mgr = TimeoutManager()
        mgr.set_deadline("task-1", seconds=100.0)
        assert mgr.remaining("task-1") > 99

    def test_remaining_not_found(self):
        mgr = TimeoutManager()
        assert mgr.remaining("missing") == 0.0

    def test_is_expired_false(self):
        mgr = TimeoutManager()
        mgr.set_deadline("task-1", seconds=100.0)
        assert mgr.is_expired("task-1") is False

    def test_is_expired_true(self):
        mgr = TimeoutManager()
        mgr.set_deadline("task-1", seconds=0.0)
        assert mgr.is_expired("task-1") is True

    def test_is_expired_not_found(self):
        mgr = TimeoutManager()
        assert mgr.is_expired("missing") is True

    def test_cancel_deadline(self):
        mgr = TimeoutManager()
        mgr.set_deadline("task-1", seconds=60.0)
        assert mgr.cancel_deadline("task-1") is True
        assert mgr.deadline_count == 0

    def test_cancel_deadline_not_found(self):
        mgr = TimeoutManager()
        assert mgr.cancel_deadline("missing") is False

    def test_get_active_deadlines(self):
        mgr = TimeoutManager()
        mgr.set_deadline("active", seconds=100.0)
        mgr.set_deadline("expired", seconds=0.0)
        active = mgr.get_active_deadlines()
        assert len(active) == 1
        assert active[0].task_id == "active"

    def test_get_expired_deadlines(self):
        mgr = TimeoutManager()
        mgr.set_deadline("active", seconds=100.0)
        mgr.set_deadline("expired", seconds=0.0)
        expired = mgr.get_expired_deadlines()
        assert len(expired) == 1
        assert expired[0].task_id == "expired"

    def test_cleanup_expired(self):
        mgr = TimeoutManager()
        mgr.set_deadline("active", seconds=100.0)
        mgr.set_deadline("expired", seconds=0.0)
        count = mgr.cleanup_expired()
        assert count == 1
        assert mgr.deadline_count == 1


# =============================================================================
# Timeout Event Tests
# =============================================================================


class TestTimeoutEvents:
    """Test timeout event recording."""

    def test_record_timeout(self):
        mgr = TimeoutManager()
        e = mgr.record_timeout("bash", 30.0)
        assert e.tool_name == "bash"

    def test_get_all_events(self):
        mgr = TimeoutManager()
        mgr.record_timeout("bash", 30.0)
        mgr.record_timeout("ai", 60.0)
        events = mgr.get_timeout_events()
        assert len(events) == 2

    def test_get_events_filtered(self):
        mgr = TimeoutManager()
        mgr.record_timeout("bash", 30.0)
        mgr.record_timeout("ai", 60.0)
        mgr.record_timeout("bash", 30.0)
        events = mgr.get_timeout_events(tool_name="bash")
        assert len(events) == 2


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test timeout manager statistics."""

    def test_initial_stats(self):
        mgr = TimeoutManager()
        stats = mgr.get_stats()
        assert stats.configured_tools == 0
        assert stats.total_timeouts_recorded == 0

    def test_stats_after_work(self):
        mgr = TimeoutManager()
        mgr.configure("bash", timeout_seconds=10.0)
        mgr.set_deadline("task-1", seconds=100.0)
        mgr.set_deadline("task-2", seconds=0.0)
        mgr.record_timeout("bash", 10.0)
        stats = mgr.get_stats()
        assert stats.configured_tools == 1
        assert stats.active_deadlines == 1
        assert stats.expired_deadlines == 1
        assert stats.total_timeouts_recorded == 1

    def test_stats_to_dict(self):
        mgr = TimeoutManager()
        d = mgr.get_stats().to_dict()
        assert "configured_tools" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_config_count(self):
        mgr = TimeoutManager()
        mgr.configure("a")
        mgr.configure("b")
        assert mgr.config_count == 2

    def test_deadline_count(self):
        mgr = TimeoutManager()
        mgr.set_deadline("t1", seconds=60.0)
        assert mgr.deadline_count == 1

    def test_clear(self):
        mgr = TimeoutManager()
        mgr.configure("bash")
        mgr.set_deadline("t1", seconds=60.0)
        mgr.record_timeout("bash", 10.0)
        mgr.clear()
        assert mgr.config_count == 0
        assert mgr.deadline_count == 0
        assert len(mgr.get_timeout_events()) == 0

    def test_to_dict(self):
        mgr = TimeoutManager()
        mgr.configure("bash")
        d = mgr.to_dict()
        assert d["config_count"] == 1
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global timeout manager."""

    def test_get(self):
        reset_timeout_manager()
        mgr = get_timeout_manager()
        assert isinstance(mgr, TimeoutManager)

    def test_singleton(self):
        reset_timeout_manager()
        m1 = get_timeout_manager()
        m2 = get_timeout_manager()
        assert m1 is m2

    def test_reset(self):
        reset_timeout_manager()
        m1 = get_timeout_manager()
        reset_timeout_manager()
        m2 = get_timeout_manager()
        assert m1 is not m2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_execution_package(self):
        from core.execution_pkg.execution import (
            Deadline,
            TimeoutConfig,
            TimeoutEvent,
            TimeoutManager,
            TimeoutStats,
            get_timeout_manager,
            reset_timeout_manager,
        )

        assert all(
            [
                TimeoutManager,
                TimeoutConfig,
                Deadline,
                TimeoutEvent,
                TimeoutStats,
                get_timeout_manager,
                reset_timeout_manager,
            ]
        )

    def test_from_module(self):
        from core.execution_pkg.execution.timeout_manager import (
            DEFAULT_TIMEOUT,
            MAX_TIMEOUT,
        )

        assert DEFAULT_TIMEOUT == 30.0
        assert MAX_TIMEOUT == 600.0
