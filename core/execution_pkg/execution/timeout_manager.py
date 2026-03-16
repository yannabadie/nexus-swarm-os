"""
Timeout Manager - Per-tool timeout configuration and deadline tracking.

V12.4 COGNITIVE BOOST - Task #70

Provides configurable timeouts for tool execution with deadline tracking,
timeout history, and statistics.

Usage:
    from core.execution_pkg.execution.timeout_manager import get_timeout_manager

    mgr = get_timeout_manager()

    # Configure tool timeouts
    mgr.configure("file_read", timeout_seconds=5.0)
    mgr.configure("ai_call", timeout_seconds=60.0)

    # Check timeout for a tool
    timeout = mgr.get_timeout("file_read")  # 5.0

    # Track deadlines
    mgr.set_deadline("task-1", seconds=300)
    remaining = mgr.remaining("task-1")
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

DEFAULT_TIMEOUT = 30.0  # seconds
MAX_TIMEOUT = 600.0  # 10 minutes
MAX_CONFIGS = 500
MAX_DEADLINES = 10000


# =============================================================================
# Types
# =============================================================================


@dataclass
class TimeoutConfig:
    """Timeout configuration for a tool."""

    name: str
    timeout_seconds: float = DEFAULT_TIMEOUT
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "timeout_seconds": self.timeout_seconds,
            "description": self.description,
        }


@dataclass
class Deadline:
    """A tracked deadline."""

    task_id: str
    deadline_at: float  # monotonic time
    created_at: float = 0.0
    label: str = ""

    def __post_init__(self):
        if self.created_at == 0.0:
            self.created_at = time.monotonic()

    @property
    def remaining(self) -> float:
        r = self.deadline_at - time.monotonic()
        return max(0.0, r)

    @property
    def is_expired(self) -> bool:
        return time.monotonic() >= self.deadline_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "remaining_seconds": round(self.remaining, 2),
            "is_expired": self.is_expired,
            "label": self.label,
        }


@dataclass
class TimeoutEvent:
    """Record of a timeout occurrence."""

    tool_name: str
    timeout_seconds: float
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.monotonic()

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass
class TimeoutStats:
    """Timeout manager statistics."""

    configured_tools: int
    active_deadlines: int
    expired_deadlines: int
    total_timeouts_recorded: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "configured_tools": self.configured_tools,
            "active_deadlines": self.active_deadlines,
            "expired_deadlines": self.expired_deadlines,
            "total_timeouts_recorded": self.total_timeouts_recorded,
        }


# =============================================================================
# Timeout Manager
# =============================================================================


class TimeoutManager:
    """
    Manages tool timeouts and task deadlines.

    Features:
    - Per-tool timeout configuration
    - Task deadline tracking
    - Timeout event history
    - Deadline expiration checking
    - Statistics
    - Thread-safe
    """

    def __init__(self):
        self._configs: dict[str, TimeoutConfig] = {}
        self._deadlines: dict[str, Deadline] = {}
        self._timeout_events: list[TimeoutEvent] = []
        self._lock = threading.Lock()

    # =========================================================================
    # Tool Timeout Configuration
    # =========================================================================

    def configure(
        self,
        tool_name: str,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT,
        description: str = "",
    ) -> TimeoutConfig:
        """Configure timeout for a tool."""
        timeout_seconds = min(timeout_seconds, MAX_TIMEOUT)
        config = TimeoutConfig(
            name=tool_name,
            timeout_seconds=timeout_seconds,
            description=description,
        )
        with self._lock:
            if len(self._configs) >= MAX_CONFIGS and tool_name not in self._configs:
                raise ValueError(f"Maximum configs ({MAX_CONFIGS}) reached")
            self._configs[tool_name] = config
        return config

    def unconfigure(self, tool_name: str) -> bool:
        """Remove a tool timeout configuration."""
        with self._lock:
            return self._configs.pop(tool_name, None) is not None

    def get_timeout(self, tool_name: str) -> float:
        """Get timeout for a tool (returns default if not configured)."""
        config = self._configs.get(tool_name)
        return config.timeout_seconds if config else DEFAULT_TIMEOUT

    def get_config(self, tool_name: str) -> TimeoutConfig | None:
        """Get timeout configuration for a tool."""
        return self._configs.get(tool_name)

    def list_configs(self) -> list[TimeoutConfig]:
        """List all configured tool timeouts."""
        return list(self._configs.values())

    # =========================================================================
    # Deadline Tracking
    # =========================================================================

    def set_deadline(
        self,
        task_id: str,
        *,
        seconds: float,
        label: str = "",
    ) -> Deadline:
        """Set a deadline for a task."""
        now = time.monotonic()
        deadline = Deadline(
            task_id=task_id,
            deadline_at=now + seconds,
            created_at=now,
            label=label,
        )
        with self._lock:
            if len(self._deadlines) >= MAX_DEADLINES and task_id not in self._deadlines:
                raise ValueError(f"Maximum deadlines ({MAX_DEADLINES}) reached")
            self._deadlines[task_id] = deadline
        return deadline

    def get_deadline(self, task_id: str) -> Deadline | None:
        """Get a deadline by task ID."""
        return self._deadlines.get(task_id)

    def remaining(self, task_id: str) -> float:
        """Get remaining seconds for a deadline."""
        deadline = self._deadlines.get(task_id)
        if deadline is None:
            return 0.0
        return deadline.remaining

    def is_expired(self, task_id: str) -> bool:
        """Check if a deadline has expired."""
        deadline = self._deadlines.get(task_id)
        if deadline is None:
            return True
        return deadline.is_expired

    def cancel_deadline(self, task_id: str) -> bool:
        """Cancel a deadline."""
        with self._lock:
            return self._deadlines.pop(task_id, None) is not None

    def get_active_deadlines(self) -> list[Deadline]:
        """Get all non-expired deadlines."""
        return [d for d in self._deadlines.values() if not d.is_expired]

    def get_expired_deadlines(self) -> list[Deadline]:
        """Get all expired deadlines."""
        return [d for d in self._deadlines.values() if d.is_expired]

    def cleanup_expired(self) -> int:
        """Remove expired deadlines. Returns count removed."""
        with self._lock:
            expired = [tid for tid, d in self._deadlines.items() if d.is_expired]
            for tid in expired:
                del self._deadlines[tid]
            return len(expired)

    # =========================================================================
    # Timeout Events
    # =========================================================================

    def record_timeout(self, tool_name: str, timeout_seconds: float) -> TimeoutEvent:
        """Record a timeout event."""
        event = TimeoutEvent(tool_name=tool_name, timeout_seconds=timeout_seconds)
        with self._lock:
            self._timeout_events.append(event)
        return event

    def get_timeout_events(self, *, tool_name: str | None = None) -> list[TimeoutEvent]:
        """Get timeout events, optionally filtered by tool."""
        if tool_name is None:
            return list(self._timeout_events)
        return [e for e in self._timeout_events if e.tool_name == tool_name]

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> TimeoutStats:
        """Get timeout manager statistics."""
        active = sum(1 for d in self._deadlines.values() if not d.is_expired)
        expired = sum(1 for d in self._deadlines.values() if d.is_expired)
        return TimeoutStats(
            configured_tools=len(self._configs),
            active_deadlines=active,
            expired_deadlines=expired,
            total_timeouts_recorded=len(self._timeout_events),
        )

    # =========================================================================
    # State
    # =========================================================================

    @property
    def config_count(self) -> int:
        return len(self._configs)

    @property
    def deadline_count(self) -> int:
        return len(self._deadlines)

    def clear(self) -> None:
        """Clear all configurations, deadlines, and events."""
        with self._lock:
            self._configs.clear()
            self._deadlines.clear()
            self._timeout_events.clear()

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_count": self.config_count,
            "deadline_count": self.deadline_count,
            "stats": self.get_stats().to_dict(),
        }


# =============================================================================
# Global Instance
# =============================================================================

_manager: TimeoutManager | None = None
_manager_lock = threading.Lock()


def get_timeout_manager() -> TimeoutManager:
    """Get or create the global timeout manager."""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = TimeoutManager()
    return _manager


def reset_timeout_manager() -> None:
    """Reset the global timeout manager (for testing)."""
    global _manager
    _manager = None
