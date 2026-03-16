"""
Async adapter for synchronous LLM drivers.

V8.1.6: Enables true parallel execution via asyncio.gather()

This module provides an async wrapper around synchronous drivers,
allowing them to be used with asyncio.gather() without blocking
the event loop.

Usage:
    from core.drivers.async_adapter import AsyncDriverAdapter

    # Wrap existing sync drivers
    async_gemini = AsyncDriverAdapter(gemini_driver)
    async_claude = AsyncDriverAdapter(claude_driver)

    # Run truly in parallel
    results = await asyncio.gather(
        async_gemini.invoke_async(context1, session_uuid="uuid1"),
        async_claude.invoke_async(context2, session_uuid="uuid2")
    )
"""

import asyncio
from collections.abc import Callable
from typing import Any


class AsyncDriverAdapter:
    """
    Wraps synchronous LLM drivers for async execution.

    Uses asyncio.to_thread (Python 3.9+) to run blocking
    driver.invoke() calls in a thread pool without blocking
    the event loop.

    This enables true parallel execution when used with
    asyncio.gather(), unlike ThreadPoolExecutor which still
    blocks due to the GIL during I/O operations.

    Attributes:
        driver: The synchronous driver instance to wrap
    """

    def __init__(self, sync_driver: Any):
        """
        Initialize the async adapter.

        Args:
            sync_driver: A synchronous driver with invoke() method.
                        Expected to have invoke(context, session_uuid=None)
                        signature.
        """
        self.driver = sync_driver

    async def invoke_async(self, context: str, session_uuid: str | None = None) -> dict:
        """
        Async wrapper for driver.invoke().

        Runs the synchronous invoke() method in a thread pool
        to avoid blocking the event loop.

        Args:
            context: Context string to send to the LLM
            session_uuid: Optional unique ID for file isolation

        Returns:
            Dict response from the driver
        """
        return await asyncio.to_thread(self.driver.invoke, context, session_uuid=session_uuid)

    async def invoke_stream_async(
        self, context: str, on_token: Callable[[str], None], session_uuid: str | None = None
    ) -> dict:
        """
        Async wrapper for driver.invoke_stream().

        Runs the synchronous invoke_stream() method in a thread pool.
        Note: on_token callbacks will be called from the thread pool.

        Args:
            context: Context string to send to the LLM
            on_token: Callback for each token/chunk
            session_uuid: Optional unique ID for file isolation

        Returns:
            Dict response from the driver
        """
        return await asyncio.to_thread(self.driver.invoke_stream, context, on_token, session_uuid=session_uuid)


async def invoke_parallel(drivers: list, contexts: list, session_uuids: list | None = None) -> list:
    """
    Convenience function to invoke multiple drivers in parallel.

    Args:
        drivers: List of driver instances (sync or AsyncDriverAdapter)
        contexts: List of context strings (same length as drivers)
        session_uuids: Optional list of session UUIDs (same length)

    Returns:
        List of responses in the same order as inputs

    Example:
        results = await invoke_parallel(
            [gemini, claude],
            [context1, context2],
            [uuid1, uuid2]
        )
    """
    if session_uuids is None:
        session_uuids = [None] * len(drivers)

    if len(drivers) != len(contexts) or len(drivers) != len(session_uuids):
        raise ValueError("drivers, contexts, and session_uuids must have same length")

    tasks = []
    for driver, context, uuid in zip(drivers, contexts, session_uuids, strict=False):
        if isinstance(driver, AsyncDriverAdapter):
            tasks.append(driver.invoke_async(context, session_uuid=uuid))
        else:
            # Wrap sync driver on the fly
            adapter = AsyncDriverAdapter(driver)
            tasks.append(adapter.invoke_async(context, session_uuid=uuid))

    return await asyncio.gather(*tasks)
