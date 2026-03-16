"""
Async Adapter for NEXUS V9.0 Hive Mind.

Bridges V9 async drivers with existing Hive Mind phases.
Adds CancellationToken support for graceful shutdown.

This adapter wraps the existing TrueHiveMind orchestrator to:
1. Accept async drivers (AsyncClaudeDriver, AsyncGeminiDriver)
2. Propagate CancellationToken through all phases
3. Track task UUIDs for cancellation
4. Use AsyncBlackboard for shared state

Usage:
    adapter = AsyncHiveMindAdapter(
        hive_mind=true_hive_mind,
        driver_factory=factory,
        blackboard=async_blackboard
    )

    result = await adapter.process_task(
        task="Complex task",
        token=cancellation_token,
        session_uuid="task-123"
    )
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from core.foundation.async_primitives import AsyncBlackboard, CancellationToken
from core.foundation.async_primitives.process_handle import get_process_registry

if TYPE_CHECKING:
    from core.drivers.async_factory import AsyncDriverFactory

    from .orchestrator import HiveMindResult, TrueHiveMind

logger = logging.getLogger(__name__)


class AsyncHiveMindAdapter:
    """
    Adapter that adds V9 async capabilities to existing HiveMind.

    This is a thin wrapper that:
    - Passes CancellationToken to async drivers
    - Tracks task by session_uuid for cancellation
    - Uses AsyncBlackboard for phase communication
    """

    def __init__(
        self,
        hive_mind: TrueHiveMind,
        driver_factory: AsyncDriverFactory | None = None,
        blackboard: AsyncBlackboard | None = None,
    ):
        """
        Initialize adapter.

        Args:
            hive_mind: Existing TrueHiveMind instance
            driver_factory: V9 async driver factory (optional)
            blackboard: V9 async blackboard (optional)
        """
        self.hive_mind = hive_mind
        self.driver_factory = driver_factory
        self.blackboard = blackboard or AsyncBlackboard()

        # Track active tasks
        self._active_tasks: dict[str, CancellationToken] = {}
        self._registry = get_process_registry()

    async def process_task(
        self,
        task: str,
        *,
        token: CancellationToken | None = None,
        session_uuid: str | None = None,
        complexity: Any | None = None,
    ) -> HiveMindResult:
        """
        Process task with V9 async capabilities.

        Args:
            task: Task description
            token: CancellationToken for graceful cancellation
            session_uuid: Unique ID for this task execution
            complexity: Optional TaskComplexity

        Returns:
            HiveMindResult from HiveMind
        """
        token = token or CancellationToken()
        session_uuid = session_uuid or f"hive_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # Track this task
        self._active_tasks[session_uuid] = token

        # Store task info in blackboard
        await self.blackboard.set(
            f"task_{session_uuid}_started", datetime.now().isoformat(), source="hive_mind_adapter"
        )

        try:
            # Check cancellation before starting
            token.check()

            # Call existing process_task
            # Note: The existing HiveMind uses sync drivers internally.
            # This adapter provides the infrastructure for V9 integration
            # without requiring full rewrite of all phases.
            if complexity:
                result = await self.hive_mind.process_task(task, complexity=complexity)
            else:
                result = await self.hive_mind.process_task(task)

            # Store result in blackboard
            await self.blackboard.set(
                f"task_{session_uuid}_result",
                {
                    "success": result.success,
                    "phases": result.phases_completed,
                    "duration": result.total_duration,
                },
                source="hive_mind_adapter",
            )

            return result

        except asyncio.CancelledError:
            logger.info(f"HiveMind task {session_uuid} was cancelled")

            # Cancel any processes associated with this task
            await self._registry.cancel_by_task_id(session_uuid)

            # Re-raise as required by Python docs
            raise

        finally:
            # Cleanup
            self._active_tasks.pop(session_uuid, None)

    async def cancel_task(self, session_uuid: str) -> bool:
        """
        Cancel a specific task by its session UUID.

        Args:
            session_uuid: UUID of the task to cancel

        Returns:
            True if task was found and cancelled
        """
        token = self._active_tasks.get(session_uuid)
        if token:
            token.cancel(reason=f"Task {session_uuid} cancelled by user")

            # Also cancel any driver processes
            cancelled = await self._registry.cancel_by_task_id(session_uuid)
            logger.info(f"Cancelled task {session_uuid}, {cancelled} processes terminated")

            return True
        return False

    async def cancel_all(self) -> int:
        """
        Cancel all active tasks.

        Returns:
            Number of tasks cancelled
        """
        count = 0
        for _session_uuid, token in list(self._active_tasks.items()):
            token.cancel(reason="All tasks cancelled")
            count += 1

        # Cancel all driver processes
        driver_count = await self._registry.cancel_all()
        logger.info(f"Cancelled {count} tasks, {driver_count} processes")

        return count

    @property
    def active_task_count(self) -> int:
        """Get number of active tasks."""
        return len(self._active_tasks)

    async def get_task_status(self, session_uuid: str) -> dict[str, Any] | None:
        """
        Get status of a task from blackboard.

        Args:
            session_uuid: Task UUID

        Returns:
            Status dict or None if not found
        """
        started = await self.blackboard.get(f"task_{session_uuid}_started")
        result = await self.blackboard.get(f"task_{session_uuid}_result")

        if not started:
            return None

        return {
            "session_uuid": session_uuid,
            "started": started,
            "completed": result is not None,
            "result": result,
            "is_active": session_uuid in self._active_tasks,
        }


class DriverBridge:
    """
    Bridge that wraps async drivers to look like sync drivers.

    .. deprecated:: V8.4.4
        Use async drivers directly with `await driver.invoke()` or
        `driver.invoke_sync()` for sync fallback. DriverBridge will
        be removed in V9.0.

    This allows gradual migration - phases can use the bridge
    until they're updated to use async drivers directly.

    Note: This uses asyncio.run_coroutine_threadsafe which is
    NOT ideal for performance. Full V9 should use async drivers
    directly in phases.
    """

    def __init__(self, async_driver, loop: asyncio.AbstractEventLoop | None = None):
        """
        Initialize bridge.

        Args:
            async_driver: AsyncClaudeDriver or AsyncGeminiDriver
            loop: Event loop to use (or get running loop)

        .. deprecated:: V8.4.4
            Use `driver.invoke_sync()` instead of DriverBridge.
        """
        import warnings

        warnings.warn(
            "DriverBridge is deprecated since V8.4.4. "
            "Use async drivers directly with `await driver.invoke()` or "
            "`driver.invoke_sync()` for sync fallback. "
            "DriverBridge will be removed in V9.0.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.async_driver = async_driver
        self._loop = loop

    def invoke(self, context: str, **kwargs) -> dict[str, Any]:
        """
        Synchronous invoke that wraps async driver.

        WARNING: This blocks the calling thread. Only for
        backwards compatibility during migration.

        .. deprecated:: V8.4.4
            Use `driver.invoke_sync()` instead.
        """
        # V11.4 ASYNC: Python 3.12+ compatibility
        # Try get_running_loop() first (in async context), then fallback
        try:
            loop = self._loop or asyncio.get_running_loop()
            # Loop is running - use run_coroutine_threadsafe
            future = asyncio.run_coroutine_threadsafe(self.async_driver.invoke(context, **kwargs), loop)
            return future.result(timeout=300)
        except RuntimeError:
            # No running loop - create one and run
            return asyncio.run(self.async_driver.invoke(context, **kwargs))


# ============================================================================
# V8.4.4 MIGRATION GUIDE - DriverBridge Removal
# ============================================================================
#
# DriverBridge is DEPRECATED since V8.4.4. Migration paths:
#
# 1. ASYNC CODE (Recommended):
#    BEFORE: bridge = DriverBridge(async_driver); result = bridge.invoke(ctx)
#    AFTER:  result = await async_driver.invoke(ctx)
#
# 2. SYNC CODE (Transitional):
#    BEFORE: bridge = DriverBridge(async_driver); result = bridge.invoke(ctx)
#    AFTER:  result = async_driver.invoke_sync(ctx)  # Also deprecated!
#
# 3. HIVEMIND PHASES (Already migrated):
#    All phases use send_message_async() which wraps sync drivers via
#    asyncio.to_thread(). No DriverBridge usage.
#
# Removal Timeline:
# - V8.4.4: DriverBridge deprecated, invoke_sync() deprecated
# - V8.5.x: DriverBridge removed from codebase
# - V9.0:   invoke_sync() removed, all code must be async
#
# See also:
# - core/drivers/async_claude_driver.py:invoke_sync()
# - core/drivers/async_gemini_driver.py:invoke_sync()
# - core/utils/async_utils.py:run_sync() (also deprecated V8.4.4)
# ============================================================================


# V12.4: create_async_hive_mind removed (dead code)
# This function was never called and contained broken references:
# - ClaudeDriverHybrid no longer exists (migrated to AnthropicSDKDriver)
# - BaseAsyncDriver is an ABC and cannot be instantiated directly
#
# If needed, create TrueHiveMind directly with AsyncDriverFactory:
#   factory = AsyncDriverFactory(config)
#   gemini_driver = factory.get_driver("gemini")
#   claude_driver = factory.get_driver("claude")
#   hive_mind = TrueHiveMind(..., gemini_driver, claude_driver)
#   adapter = AsyncHiveMindAdapter(hive_mind, factory)
