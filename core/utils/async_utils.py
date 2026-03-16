"""
NEXUS V8.4.4a - Async Utilities

Provides helpers for async/sync interoperability.

TD-001: Extracted from duplicated patterns in tool_manager.py and repl.py.
V8.4.4a: Added timeout + deprecation warning to run_sync().
"""

import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")


def run_sync(coro: Coroutine[Any, Any, T], *, timeout: float | None = 300.0, warn: bool = True) -> T:
    """
    Execute an async coroutine from a synchronous context.

    .. deprecated:: V8.4.4
        Prefer async patterns using `await` directly. This function
        will be removed in V9.0. Use `asyncio.run()` if not in an
        event loop, or refactor to async.

    Handles the case where an event loop may or may not be running.

    Args:
        coro: The coroutine to execute
        timeout: Timeout in seconds (default 300s). None for no timeout.
        warn: Whether to emit deprecation warning (default True)

    Returns:
        The result of the coroutine

    Raises:
        concurrent.futures.TimeoutError: If timeout exceeded

    Example:
        >>> async def fetch_data():
        ...     return {"status": "ok"}
        >>> result = run_sync(fetch_data(), timeout=60.0, warn=False)
        >>> print(result)
        {'status': 'ok'}
    """
    if warn:
        import warnings

        warnings.warn(
            "run_sync() is deprecated since V8.4.4. "
            "Prefer async patterns with `await` or `asyncio.run()`. "
            "run_sync() will be removed in V9.0.",
            DeprecationWarning,
            stacklevel=2,
        )

    # V11.4 ASYNC: Detect if we're in an async context
    # WARNING: run_sync() does NOT preserve async context (CancellationToken, etc.)
    # This is why it's deprecated - use proper async patterns instead.
    try:
        asyncio.get_running_loop()
        # Event loop exists - use ThreadPoolExecutor to avoid deadlock
        # Note: This creates a NEW event loop in the thread, losing context
        # For context-preserving async, use run_coroutine_threadsafe() directly
        # (only safe when called from a DIFFERENT thread than the event loop)
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, coro)
            return future.result(timeout=timeout)
    except RuntimeError:
        # No running event loop - safe to create one
        return asyncio.run(coro)


def get_or_create_event_loop() -> asyncio.AbstractEventLoop:
    """
    Get the current event loop or create a new one if none exists.

    Returns:
        The current or newly created event loop
    """
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop


async def run_in_thread(func, *args, **kwargs):
    """
    Run a synchronous function in a thread pool.

    Useful for wrapping blocking I/O operations in async code.

    Args:
        func: The synchronous function to run
        *args: Positional arguments for the function
        **kwargs: Keyword arguments for the function

    Returns:
        The result of the function
    """
    import functools

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, functools.partial(func, *args, **kwargs))
