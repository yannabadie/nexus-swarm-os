"""
Context Module - Multi-Tenant Session Management.

NEXUS V10 PRISM - The Invisible Spine

This module provides request-scoped context for multi-tenant isolation
using Python's contextvars.

Quick Start:
    from core.infrastructure.context import use_context, get_current_session

    # Set context for a request
    with use_context(tenant_id="acme", user_id="alice"):
        ctx = get_current_session()
        print(ctx.tenant_id)  # "acme"

    # Async version
    async with use_context_async(tenant_id="acme"):
        ctx = get_current_session()

    # Decorator for required context
    @require_context
    def tenant_specific_operation():
        ctx = get_current_session()
        ...

Author: Claude (NEXUS PRISM V10)
Date: 2025-12-15
"""

# V12.4 COGNITIVE BOOST: Context Audit Trail
from .audit_trail import (
    AuditEntry,
    AuditStats,
    ContextAuditTrail,
    get_audit_trail,
    reset_audit_trail,
)
from .session import (
    DEFAULT_TENANT_ID,
    DEFAULT_USER_ID,
    DEFAULT_WORKSPACE_ID,
    # Core types
    SessionContext,
    UserRole,
    # ContextVar
    current_session,
    ensure_context,
    # Getters
    get_current_session,
    get_current_session_or_none,
    # Backward compatibility
    get_default_context,
    has_active_session,
    # Decorator
    require_context,
    # Context managers
    use_context,
    use_context_async,
)

__all__ = [
    # Core types
    "SessionContext",
    "UserRole",
    # ContextVar
    "current_session",
    # Getters
    "get_current_session",
    "get_current_session_or_none",
    "has_active_session",
    # Context managers
    "use_context",
    "use_context_async",
    # Decorator
    "require_context",
    # Backward compatibility
    "get_default_context",
    "ensure_context",
    "DEFAULT_TENANT_ID",
    "DEFAULT_USER_ID",
    "DEFAULT_WORKSPACE_ID",
    # V12.4 COGNITIVE BOOST: Context Audit Trail
    "ContextAuditTrail",
    "AuditEntry",
    "AuditStats",
    "get_audit_trail",
    "reset_audit_trail",
]
