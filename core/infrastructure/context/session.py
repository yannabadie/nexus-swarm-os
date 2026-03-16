"""
SessionContext - The Invisible Spine for Multi-Tenant Isolation.

NEXUS V10 PRISM - Multi-Tenant Architecture

This module provides request-scoped context using Python's contextvars,
enabling deep code to know "Who is calling me" without passing arguments everywhere.

Key Concepts:
- SessionContext: Dataclass holding tenant/user/workspace identity
- current_session: ContextVar storing the active session
- use_context: Context manager for scoped session activation

Usage:
    from core.infrastructure.context import use_context, get_current_session

    # Set context for a request
    async with use_context(tenant_id="acme", user_id="user_123"):
        # All code in this block sees the same context
        ctx = get_current_session()
        print(ctx.tenant_id)  # "acme"

    # Factory pattern integration
    registry = ServiceFactory.get_registry()  # Uses current context automatically

Thread Safety:
- ContextVars are inherently thread-safe and async-safe
- Each task/thread gets its own copy of the context
- No locks needed - isolation is built into the design

Author: Claude (NEXUS PRISM V10)
Date: 2025-12-15
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from functools import wraps
from pathlib import Path
from typing import ParamSpec, TypeVar


class UserRole(Enum):
    """User roles for authorization."""

    ADMIN = "admin"
    USER = "user"
    SERVICE = "service"  # For automated/headless operations
    GUEST = "guest"


@dataclass(frozen=True)
class SessionContext:
    """
    Immutable context for the current request/session.

    This dataclass holds all identity information needed for
    multi-tenant isolation. It's frozen to prevent accidental
    modification during request processing.

    Attributes:
        tenant_id: Unique tenant identifier (UUID string)
        user_id: User identifier within the tenant
        workspace_id: Active workspace identifier
        role: User's role for authorization
        request_id: Unique request ID for tracing
        created_at: When this context was created
        workspace_root: Resolved path to tenant's workspace
    """

    tenant_id: str
    user_id: str = "anonymous"
    workspace_id: str = "default"
    role: UserRole = UserRole.USER
    request_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    created_at: datetime = field(default_factory=datetime.now)

    # Computed paths (set by factory based on tenant)
    workspace_root: Path | None = None

    def __post_init__(self):
        """Validate context on creation."""
        if not self.tenant_id:
            raise ValueError("tenant_id is required")

    @property
    def tenant_workspace_path(self) -> Path:
        """
        Get the resolved workspace path for this tenant.

        Returns:
            Path to data/tenants/{tenant_id}/workspaces/{workspace_id}/

        Raises:
            ValueError: If workspace_root not set
        """
        if self.workspace_root is None:
            # Compute default path
            return Path(f"data/tenants/{self.tenant_id}/workspaces/{self.workspace_id}")
        return self.workspace_root

    def with_workspace(self, workspace_id: str, workspace_root: Path | None = None) -> SessionContext:
        """
        Create a new context with different workspace.

        Args:
            workspace_id: New workspace ID
            workspace_root: Optional explicit workspace path

        Returns:
            New SessionContext with updated workspace
        """
        return SessionContext(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            workspace_id=workspace_id,
            role=self.role,
            request_id=self.request_id,
            created_at=self.created_at,
            workspace_root=workspace_root,
        )

    def __repr__(self) -> str:
        return (
            f"SessionContext(tenant={self.tenant_id}, "
            f"user={self.user_id}, "
            f"workspace={self.workspace_id}, "
            f"request={self.request_id})"
        )


# The global ContextVar - each async task/thread gets its own value
current_session: ContextVar[SessionContext | None] = ContextVar("current_session", default=None)


def get_current_session() -> SessionContext:
    """
    Get the current session context.

    Returns:
        The active SessionContext

    Raises:
        RuntimeError: If no context is active (code running outside use_context)
    """
    ctx = current_session.get()
    if ctx is None:
        raise RuntimeError(
            "No session context active. "
            "Wrap your code in 'with use_context(...)' or 'async with use_context_async(...)'"
        )
    return ctx


def get_current_session_or_none() -> SessionContext | None:
    """
    Get the current session context, or None if not set.

    Use this for optional context access (e.g., logging).

    Returns:
        The active SessionContext or None
    """
    return current_session.get()


def has_active_session() -> bool:
    """
    Check if a session context is currently active.

    Returns:
        True if a context is set, False otherwise
    """
    return current_session.get() is not None


@contextmanager
def use_context(
    tenant_id: str,
    user_id: str = "anonymous",
    workspace_id: str = "default",
    role: UserRole = UserRole.USER,
    workspace_root: Path | None = None,
):
    """
    Synchronous context manager for setting session context.

    All code within this block will see the specified context.
    Context is automatically restored when the block exits.

    Args:
        tenant_id: Tenant identifier (required)
        user_id: User identifier
        workspace_id: Workspace identifier
        role: User role
        workspace_root: Optional explicit workspace path

    Yields:
        The created SessionContext

    Example:
        with use_context(tenant_id="acme", user_id="alice"):
            ctx = get_current_session()
            # ctx.tenant_id == "acme"
            service = ServiceFactory.get_registry()
            # service is scoped to "acme" tenant
    """
    ctx = SessionContext(
        tenant_id=tenant_id,
        user_id=user_id,
        workspace_id=workspace_id,
        role=role,
        workspace_root=workspace_root,
    )

    token: Token = current_session.set(ctx)
    try:
        yield ctx
    finally:
        current_session.reset(token)


@asynccontextmanager
async def use_context_async(
    tenant_id: str,
    user_id: str = "anonymous",
    workspace_id: str = "default",
    role: UserRole = UserRole.USER,
    workspace_root: Path | None = None,
):
    """
    Async context manager for setting session context.

    Same as use_context but for async code.

    Args:
        tenant_id: Tenant identifier (required)
        user_id: User identifier
        workspace_id: Workspace identifier
        role: User role
        workspace_root: Optional explicit workspace path

    Yields:
        The created SessionContext

    Example:
        async with use_context_async(tenant_id="acme"):
            ctx = get_current_session()
            await some_async_operation()
    """
    ctx = SessionContext(
        tenant_id=tenant_id,
        user_id=user_id,
        workspace_id=workspace_id,
        role=role,
        workspace_root=workspace_root,
    )

    token: Token = current_session.set(ctx)
    try:
        yield ctx
    finally:
        current_session.reset(token)


# Type variables for decorator
P = ParamSpec("P")
R = TypeVar("R")


def require_context(func: Callable[P, R]) -> Callable[P, R]:
    """
    Decorator that ensures a session context is active.

    Use this on functions that require tenant context to work.

    Args:
        func: Function to wrap

    Returns:
        Wrapped function that raises RuntimeError if no context

    Example:
        @require_context
        def get_tenant_data():
            ctx = get_current_session()
            return load_data(ctx.tenant_id)
    """

    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        if not has_active_session():
            raise RuntimeError(
                f"Function {func.__name__} requires an active session context. "
                f"Wrap the call in 'with use_context(tenant_id=...)'."
            )
        return func(*args, **kwargs)

    return wrapper


# Default context for CLI/single-tenant mode
DEFAULT_TENANT_ID = "default"
DEFAULT_USER_ID = "local"
DEFAULT_WORKSPACE_ID = "default"


def get_default_context(nexus_root: Path | None = None) -> SessionContext:
    """
    Get the default context for single-tenant/CLI mode.

    Used during migration period and for backward compatibility.

    Args:
        nexus_root: Optional NEXUS root path for workspace resolution

    Returns:
        Default SessionContext for single-tenant mode
    """
    workspace_root = None
    if nexus_root:
        workspace_root = nexus_root / "data" / "tenants" / DEFAULT_TENANT_ID / "workspaces" / DEFAULT_WORKSPACE_ID

    return SessionContext(
        tenant_id=DEFAULT_TENANT_ID,
        user_id=DEFAULT_USER_ID,
        workspace_id=DEFAULT_WORKSPACE_ID,
        role=UserRole.ADMIN,
        workspace_root=workspace_root,
    )


def ensure_context(nexus_root: Path | None = None) -> SessionContext:
    """
    Get current context or create default if none exists.

    Useful for backward compatibility during migration.

    Args:
        nexus_root: Optional NEXUS root for default context

    Returns:
        Active SessionContext or new default context
    """
    ctx = current_session.get()
    if ctx is None:
        ctx = get_default_context(nexus_root)
        current_session.set(ctx)
    return ctx
