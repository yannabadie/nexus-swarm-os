"""
AsyncProcessHandle - Track Async Subprocess with Session Context.

NEXUS V9.0 Async-First Architecture

Critical component for:
- UUID-based process tracking (each process has a session_uuid)
- Graceful termination with timeout fallback to kill
- Orphan process prevention on cancellation
- Integration with SwarmSessionManager

This solves the "orphan process" problem where Ctrl+C might leave
CLI processes (claude, gemini) running in the background.

Usage:
    proc = await asyncio.create_subprocess_exec(...)
    handle = AsyncProcessHandle(proc=proc, session_uuid="abc123")

    # Later, to cancel:
    await handle.terminate_gracefully(timeout=2.0)

References:
- https://docs.python.org/3/library/asyncio-subprocess.html
- https://superfastpython.com/asyncio-subprocess/
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ProcessState(str, Enum):
    """State of an async process."""

    RUNNING = "running"
    TERMINATED = "terminated"
    KILLED = "killed"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class AsyncProcessHandle:
    """
    Track an async subprocess with its session context.

    Attributes:
        proc: The asyncio subprocess object
        session_uuid: Unique identifier for session isolation
        task_id: Optional task ID from SwarmSessionManager
        agent_id: Which agent owns this process (gemini/claude)
        created_at: When the process was started
        terminated_at: When the process was terminated (if applicable)
        state: Current process state
        metadata: Additional tracking metadata
    """

    proc: asyncio.subprocess.Process
    session_uuid: str
    task_id: str | None = None
    agent_id: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    terminated_at: datetime | None = None
    state: ProcessState = ProcessState.RUNNING
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_running(self) -> bool:
        """Check if the process is still running."""
        return self.proc.returncode is None

    @property
    def returncode(self) -> int | None:
        """Get the process return code (None if still running)."""
        return self.proc.returncode

    @property
    def pid(self) -> int | None:
        """Get the process ID."""
        return self.proc.pid

    @property
    def runtime_seconds(self) -> float:
        """Get how long the process has been running."""
        end_time = self.terminated_at or datetime.now()
        return (end_time - self.created_at).total_seconds()

    async def terminate_gracefully(self, timeout: float = 2.0) -> bool:
        """
        Terminate the process gracefully with timeout fallback to kill.

        1. First tries SIGTERM (terminate)
        2. Waits up to `timeout` seconds
        3. If still running, sends SIGKILL (kill)

        Args:
            timeout: Seconds to wait after terminate before killing

        Returns:
            True if process was terminated/killed, False if already dead
        """
        if not self.is_running:
            self.state = ProcessState.COMPLETED
            return False

        # Try graceful termination first
        try:
            self.proc.terminate()
            self.state = ProcessState.TERMINATED
        except ProcessLookupError:
            # Process already gone
            self.state = ProcessState.COMPLETED
            self.terminated_at = datetime.now()
            return False

        try:
            await asyncio.wait_for(self.proc.wait(), timeout=timeout)
            self.terminated_at = datetime.now()
            self.state = ProcessState.TERMINATED
            return True
        except TimeoutError:
            # Terminate didn't work, force kill
            try:
                self.proc.kill()
                await self.proc.wait()
                self.state = ProcessState.KILLED
            except ProcessLookupError:
                # Already gone
                self.state = ProcessState.COMPLETED

            self.terminated_at = datetime.now()
            return True

    async def wait(self, timeout: float | None = None) -> int:
        """
        Wait for the process to complete.

        Args:
            timeout: Optional timeout in seconds

        Returns:
            Process exit code

        Raises:
            asyncio.TimeoutError: If timeout is exceeded
        """
        if timeout is not None:
            return await asyncio.wait_for(self.proc.wait(), timeout=timeout)
        return await self.proc.wait()

    async def read_stdout(self) -> bytes:
        """Read all stdout (only if pipe was set up)."""
        if self.proc.stdout:
            return await self.proc.stdout.read()
        return b""

    async def read_stderr(self) -> bytes:
        """Read all stderr (only if pipe was set up)."""
        if self.proc.stderr:
            return await self.proc.stderr.read()
        return b""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/debugging."""
        return {
            "session_uuid": self.session_uuid,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "pid": self.pid,
            "state": self.state.value,
            "is_running": self.is_running,
            "returncode": self.returncode,
            "created_at": self.created_at.isoformat(),
            "terminated_at": self.terminated_at.isoformat() if self.terminated_at else None,
            "runtime_seconds": self.runtime_seconds,
        }

    def __repr__(self) -> str:
        return f"AsyncProcessHandle(uuid={self.session_uuid[:8]}..., pid={self.pid}, state={self.state.value})"


class ProcessHandleRegistry:
    """
    Registry for tracking all active AsyncProcessHandles.

    Provides methods to:
    - Track processes by session_uuid
    - Cancel specific processes by UUID
    - Cancel all processes (for Ctrl+C handler)
    - Query active processes

    Thread-safe via asyncio.Lock.
    """

    def __init__(self):
        self._handles: dict[str, AsyncProcessHandle] = {}
        self._lock = asyncio.Lock()

    async def register(self, handle: AsyncProcessHandle) -> None:
        """Register a process handle."""
        async with self._lock:
            self._handles[handle.session_uuid] = handle

    async def unregister(self, session_uuid: str) -> AsyncProcessHandle | None:
        """Unregister and return a process handle."""
        async with self._lock:
            return self._handles.pop(session_uuid, None)

    async def get(self, session_uuid: str) -> AsyncProcessHandle | None:
        """Get a process handle by UUID."""
        async with self._lock:
            return self._handles.get(session_uuid)

    async def cancel_by_uuid(self, session_uuid: str, timeout: float = 2.0) -> bool:
        """
        Cancel a specific process by its session UUID.

        Args:
            session_uuid: The UUID of the process to cancel
            timeout: Timeout for graceful termination

        Returns:
            True if process was found and terminated
        """
        handle = await self.get(session_uuid)
        if handle:
            result = await handle.terminate_gracefully(timeout)
            await self.unregister(session_uuid)
            return result
        return False

    async def cancel_by_task_id(self, task_id: str, timeout: float = 2.0) -> int:
        """
        Cancel all processes associated with a task ID.

        Args:
            task_id: The task ID to cancel
            timeout: Timeout for each termination

        Returns:
            Number of processes terminated
        """
        count = 0
        async with self._lock:
            handles_to_cancel = [h for h in self._handles.values() if h.task_id == task_id]

        for handle in handles_to_cancel:
            await handle.terminate_gracefully(timeout)
            await self.unregister(handle.session_uuid)
            count += 1

        return count

    async def cancel_all(self, timeout: float = 2.0) -> int:
        """
        Cancel all active processes.

        Used by Ctrl+C handler to clean up all processes.

        Args:
            timeout: Timeout for each termination

        Returns:
            Number of processes terminated
        """
        count = 0
        async with self._lock:
            handles = list(self._handles.values())
            self._handles.clear()

        for handle in handles:
            if handle.is_running:
                await handle.terminate_gracefully(timeout)
                count += 1

        return count

    async def list_active(self) -> list[dict[str, Any]]:
        """List all active process handles as dictionaries."""
        async with self._lock:
            return [h.to_dict() for h in self._handles.values() if h.is_running]

    @property
    def active_count(self) -> int:
        """Get count of active processes (non-async for quick checks)."""
        return sum(1 for h in self._handles.values() if h.is_running)

    def __len__(self) -> int:
        return len(self._handles)


# =============================================================================
# V10 PRISM: Multi-Tenant Process Registry Access
# =============================================================================
import threading  # noqa: E402  # singleton setup after class definition

_global_registry: ProcessHandleRegistry | None = None
_registry_lock = threading.Lock()


def get_process_registry() -> ProcessHandleRegistry:
    """
    Get the process handle registry for the current tenant context.

    V10 PRISM: Returns tenant-scoped registry via ServiceFactory.
    Falls back to global singleton if no context is active.

    V9: Thread-safe singleton with double-checked locking to prevent
    race conditions during initialization.
    """
    # V10: Try ServiceFactory first (tenant-scoped)
    try:
        from ..context import has_active_session

        if has_active_session():
            from ..factory import ServiceFactory

            return ServiceFactory.get_process_registry()
    except ImportError:
        pass  # context module not available, use legacy

    # Legacy fallback: global singleton
    global _global_registry
    if _global_registry is None:
        with _registry_lock:
            # Double-check inside lock
            if _global_registry is None:
                _global_registry = ProcessHandleRegistry()
    return _global_registry


def reset_process_registry() -> None:
    """
    Reset the global process registry (for testing).

    Note: In V10, also clears ServiceFactory cache for current tenant.
    """
    global _global_registry
    with _registry_lock:
        _global_registry = None

    # V10: Also clear factory cache
    try:
        from ..context import get_current_session_or_none
        from ..factory import ServiceFactory

        ctx = get_current_session_or_none()
        if ctx:
            ServiceFactory.clear_tenant_cache(ctx.tenant_id)
    except ImportError:
        pass
