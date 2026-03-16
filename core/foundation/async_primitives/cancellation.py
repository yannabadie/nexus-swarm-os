"""
CancellationToken - Hierarchical Cancellation for Async Operations.

NEXUS V9.0 Async-First Architecture

This implements a cancellation pattern similar to .NET's CancellationToken,
allowing graceful cancellation of async operations with hierarchical propagation.

Key Features:
- Parent cancellation propagates to all children
- Callbacks executed on cancellation
- check() method raises asyncio.CancelledError
- Thread-safe via simple boolean flag (atomic in Python)

Usage:
    token = CancellationToken()
    child = token.create_child()

    async def long_operation(token: CancellationToken):
        while not token.is_cancelled:
            await do_work()
            token.check()  # Raises CancelledError if cancelled

    # Cancel from another task
    token.cancel()  # Propagates to child tokens

References:
- https://superfastpython.com/asyncio-task-cancellation-best-practices/
- https://docs.python.org/3/library/asyncio-task.html
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class CancellationToken:
    """
    Hierarchical cancellation token for async operations.

    Attributes:
        _cancelled: Whether this token has been cancelled
        _parent: Parent token (cancellation propagates down)
        _children: Child tokens that inherit cancellation
        _callbacks: Functions to call on cancellation
        _cancel_reason: Optional reason for cancellation
        _cancelled_at: Timestamp when cancelled
    """

    _cancelled: bool = False
    _parent: CancellationToken | None = field(default=None, repr=False)
    _children: list[CancellationToken] = field(default_factory=list, repr=False)
    _callbacks: list[Callable] = field(default_factory=list, repr=False)
    _cancel_reason: str | None = None
    _cancelled_at: datetime | None = None

    @property
    def is_cancelled(self) -> bool:
        """
        Check if this token or any parent is cancelled.

        Returns:
            True if cancelled, False otherwise
        """
        if self._cancelled:
            return True
        if self._parent is not None:
            return self._parent.is_cancelled
        return False

    @property
    def cancel_reason(self) -> str | None:
        """Get the cancellation reason, checking parent if needed."""
        if self._cancel_reason:
            return self._cancel_reason
        if self._parent is not None:
            return self._parent.cancel_reason
        return None

    def cancel(self, reason: str | None = None) -> None:
        """
        Cancel this token and all children.

        Args:
            reason: Optional human-readable reason for cancellation
        """
        if self._cancelled:
            return  # Already cancelled

        self._cancelled = True
        self._cancel_reason = reason
        self._cancelled_at = datetime.now()

        # Propagate to children
        for child in self._children:
            child.cancel(reason=reason or "Parent cancelled")

        # Execute callbacks (don't let one failure stop others)
        for callback in self._callbacks:
            try:
                result = callback()
                # If callback returns a coroutine, schedule it
                if asyncio.iscoroutine(result):
                    try:
                        asyncio.get_running_loop()
                        # V9.5: Use SafeTaskManager for error tracking
                        from .safe_task_manager import SafeTaskManager

                        SafeTaskManager.create_task(result, name="cancellation_callback")
                    except RuntimeError:
                        # No running loop, try to run synchronously
                        pass
            except Exception as e:
                # V9.5: Log callback failures
                logger.warning(f"CancellationToken: Callback failed: {e}")

    def check(self) -> None:
        """
        Raise asyncio.CancelledError if this token is cancelled.

        Use this in loops to allow cancellation between iterations.

        Raises:
            asyncio.CancelledError: If token is cancelled

        Example:
            async for item in stream:
                token.check()  # Allow cancellation here
                process(item)
        """
        if self.is_cancelled:
            reason = self.cancel_reason or "Operation was cancelled"
            raise asyncio.CancelledError(reason)

    def create_child(self) -> CancellationToken:
        """
        Create a child token that inherits cancellation from this token.

        Child tokens are automatically cancelled when the parent is cancelled.

        Returns:
            New CancellationToken with this token as parent
        """
        child = CancellationToken(_parent=self)
        self._children.append(child)
        return child

    def on_cancel(self, callback: Callable) -> None:
        """
        Register a callback to run when this token is cancelled.

        Callbacks are executed in registration order.
        If a callback returns a coroutine, it will be scheduled as a task.

        Args:
            callback: Function to call on cancellation (can be sync or async)

        Example:
            token.on_cancel(lambda: print("Cancelled!"))
            token.on_cancel(lambda: create_safe_task(cleanup(), name="cleanup"))
        """
        if self._cancelled:
            # Already cancelled, execute immediately
            try:
                result = callback()
                if asyncio.iscoroutine(result):
                    try:
                        asyncio.get_running_loop()
                        # V9.5: Use SafeTaskManager for error tracking
                        from .safe_task_manager import SafeTaskManager

                        SafeTaskManager.create_task(result, name="on_cancel_immediate")
                    except RuntimeError:
                        pass
            except Exception as e:
                logger.warning(f"CancellationToken: on_cancel callback failed: {e}")
        else:
            self._callbacks.append(callback)

    def remove_callback(self, callback: Callable) -> bool:
        """
        Remove a previously registered callback.

        Args:
            callback: The callback to remove

        Returns:
            True if callback was found and removed
        """
        try:
            self._callbacks.remove(callback)
            return True
        except ValueError:
            return False

    def __enter__(self):
        """Context manager entry - returns self."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - no special handling."""
        return False

    def __repr__(self) -> str:
        status = "CANCELLED" if self.is_cancelled else "ACTIVE"
        children = len(self._children)
        return f"CancellationToken({status}, children={children})"


class CancellationTokenSource:
    """
    Factory for creating linked cancellation tokens.

    Similar to .NET's CancellationTokenSource, this allows creating
    tokens that can be cancelled together.

    Usage:
        source = CancellationTokenSource()
        token1 = source.token
        token2 = source.create_linked_token()

        source.cancel()  # Cancels both tokens
    """

    def __init__(self):
        self._root = CancellationToken()

    @property
    def token(self) -> CancellationToken:
        """Get the root token."""
        return self._root

    def create_linked_token(self) -> CancellationToken:
        """Create a new token linked to the root."""
        return self._root.create_child()

    def cancel(self, reason: str | None = None) -> None:
        """Cancel the root token (and all linked tokens)."""
        self._root.cancel(reason)

    @property
    def is_cancelled(self) -> bool:
        """Check if the source has been cancelled."""
        return self._root.is_cancelled
