"""
Database Module - Multi-Tenant Control Plane.

NEXUS V10 PRISM - SQLModel ORM

This module provides the database layer for multi-tenant management.

Quick Start:
    from core.infrastructure.db import init_db, get_session, Tenant, Workspace

    # Initialize database (creates tables)
    init_db()

    # Create a tenant
    with get_session() as session:
        tenant = Tenant(name="Acme Corp", slug="acme")
        session.add(tenant)

    # Query tenants
    with get_session() as session:
        tenant = get_tenant_by_slug(session, "acme")

Author: Claude (NEXUS PRISM V10)
Date: 2025-12-15
"""

from .engine import (
    # Constants
    DEFAULT_DB_PATH,
    # Convenience functions
    create_default_tenant,
    # Engine management
    get_engine,
    # Session management
    get_session,
    get_tenant_by_slug,
    get_tenant_quota,
    init_db,
    reset_engine,
)
from .models import (
    # Helpers
    DEFAULT_QUOTAS,
    # Enums
    PlanTier,
    Quota,
    # Models
    Tenant,
    TenantStatus,
    User,
    UserRole,
    Workspace,
    create_quota_for_plan,
)

# V12.4 COGNITIVE BOOST: Query Performance Tracker
from .query_performance_tracker import (
    QueryPerformanceStats,
    QueryPerformanceTracker,
    QueryRecord,
    TableProfile,
    get_query_tracker,
    reset_query_tracker,
)

__all__ = [
    # Enums
    "PlanTier",
    "TenantStatus",
    "UserRole",
    # Models
    "Tenant",
    "User",
    "Workspace",
    "Quota",
    # Model helpers
    "DEFAULT_QUOTAS",
    "create_quota_for_plan",
    # Engine
    "get_engine",
    "init_db",
    "reset_engine",
    # Session
    "get_session",
    # Convenience
    "create_default_tenant",
    "get_tenant_by_slug",
    "get_tenant_quota",
    # Constants
    "DEFAULT_DB_PATH",
    # V12.4 COGNITIVE BOOST: Query Performance Tracker
    "QueryPerformanceTracker",
    "QueryRecord",
    "TableProfile",
    "QueryPerformanceStats",
    "get_query_tracker",
    "reset_query_tracker",
]
