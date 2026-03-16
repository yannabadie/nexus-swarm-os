"""
Database Models - Multi-Tenant Control Plane.

NEXUS V10 PRISM - SQLModel ORM

This module defines the control plane database schema for multi-tenant
SaaS deployment. The database stores tenant, user, workspace, and quota
information.

Architecture:
    .nexus/master.db (at NEXUS root, NOT inside workspace/)
    +-- tenant        # Tenant accounts
    +-- user          # Users per tenant
    +-- workspace     # Workspaces per tenant
    +-- quota         # Usage limits and tracking

Relationships:
    Tenant 1:N User
    Tenant 1:N Workspace
    Tenant 1:1 Quota

Author: Claude (NEXUS PRISM V10)
Date: 2025-12-15
"""

from datetime import UTC, datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from sqlmodel import Field, Relationship, SQLModel


class PlanTier(str, Enum):
    """Subscription plan tiers."""

    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class TenantStatus(str, Enum):
    """Tenant account status."""

    ACTIVE = "active"
    SUSPENDED = "suspended"
    PENDING = "pending"


# =============================================================================
# TENANT - The root of multi-tenancy
# =============================================================================


class Tenant(SQLModel, table=True):
    """
    Tenant account - the root entity for multi-tenant isolation.

    Each tenant has their own:
    - Users
    - Workspaces
    - Quota/Budget
    - Isolated data in data/tenants/{id}/
    """

    __tablename__ = "tenant"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(index=True, max_length=100)
    slug: str = Field(unique=True, index=True, max_length=50)  # URL-safe identifier

    # Subscription
    plan_tier: PlanTier = Field(default=PlanTier.FREE)
    status: TenantStatus = Field(default=TenantStatus.ACTIVE)

    # Metadata
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))

    # Contact
    email: str | None = Field(default=None, max_length=255)

    # Relationships
    users: list["User"] = Relationship(back_populates="tenant")
    workspaces: list["Workspace"] = Relationship(back_populates="tenant")
    quota: Optional["Quota"] = Relationship(back_populates="tenant")

    def __repr__(self) -> str:
        return f"Tenant(id={self.id}, name={self.name}, plan={self.plan_tier})"


# =============================================================================
# USER - Tenant members
# =============================================================================


class UserRole(str, Enum):
    """User roles within a tenant."""

    OWNER = "owner"  # Full control, billing
    ADMIN = "admin"  # Manage users, settings
    MEMBER = "member"  # Standard access
    VIEWER = "viewer"  # Read-only


class User(SQLModel, table=True):
    """
    User account within a tenant.

    Users belong to exactly one tenant. Cross-tenant access
    requires separate user accounts.
    """

    __tablename__ = "user"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(foreign_key="tenant.id", index=True)

    # Identity
    username: str = Field(max_length=50)
    email: str = Field(max_length=255)

    # Auth (stub - real implementation would use proper hashing)
    hashed_password: str = Field(default="", max_length=255)

    # Role
    role: UserRole = Field(default=UserRole.MEMBER)

    # Status
    is_active: bool = Field(default=True)
    last_login: datetime | None = Field(default=None)

    # Metadata
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))

    # Relationships
    tenant: Tenant | None = Relationship(back_populates="users")

    class Config:
        # Unique constraint on (tenant_id, username)
        # Note: SQLModel doesn't support table_args directly,
        # we enforce this in the application layer
        pass

    def __repr__(self) -> str:
        return f"User(id={self.id}, username={self.username}, role={self.role})"


# =============================================================================
# WORKSPACE - Isolated project environments
# =============================================================================


class Workspace(SQLModel, table=True):
    """
    Workspace - an isolated project environment within a tenant.

    Each workspace maps to a physical directory:
    data/tenants/{tenant_id}/workspaces/{workspace_id}/

    Workspaces contain:
    - .nexus/ (blackboard, state)
    - agents/ (spawned agents)
    - logs/ (event logs)
    - memory/ (RAG vectors)
    """

    __tablename__ = "workspace"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(foreign_key="tenant.id", index=True)

    # Identity
    name: str = Field(max_length=100)
    slug: str = Field(max_length=50)  # URL-safe, unique within tenant

    # Physical path (relative to data/tenants/{tenant_id}/)
    filesystem_path: str = Field(max_length=500)

    # Metadata
    description: str | None = Field(default=None, max_length=500)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))

    # Status
    is_active: bool = Field(default=True)

    # Relationships
    tenant: Tenant | None = Relationship(back_populates="workspaces")

    def __repr__(self) -> str:
        return f"Workspace(id={self.id}, name={self.name}, path={self.filesystem_path})"


# =============================================================================
# QUOTA - Usage limits and tracking
# =============================================================================


class Quota(SQLModel, table=True):
    """
    Quota and usage tracking per tenant.

    Enforces resource limits based on plan tier and tracks
    current usage for billing and throttling.
    """

    __tablename__ = "quota"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(foreign_key="tenant.id", unique=True, index=True)

    # Daily limits (reset at midnight UTC)
    daily_budget_usd: float = Field(default=50.0)
    daily_requests_gemini: int = Field(default=1000)
    daily_requests_claude: int = Field(default=500)

    # Monthly limits
    monthly_budget_usd: float = Field(default=500.0)

    # Feature limits
    max_workspaces: int = Field(default=5)
    max_agents: int = Field(default=10)
    max_concurrent_tasks: int = Field(default=4)

    # Feature flags (based on plan)
    hive_mind_enabled: bool = Field(default=True)
    swarm_enabled: bool = Field(default=True)
    evolution_enabled: bool = Field(default=False)  # Enterprise only

    # Current usage (reset daily)
    current_spend_usd: float = Field(default=0.0)
    current_requests_gemini: int = Field(default=0)
    current_requests_claude: int = Field(default=0)

    # Monthly usage
    monthly_spend_usd: float = Field(default=0.0)

    # Reset tracking
    daily_reset_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))
    monthly_reset_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))

    # Relationships
    tenant: Tenant | None = Relationship(back_populates="quota")

    def is_over_daily_budget(self) -> bool:
        """Check if tenant has exceeded daily budget."""
        return self.current_spend_usd >= self.daily_budget_usd

    def is_over_monthly_budget(self) -> bool:
        """Check if tenant has exceeded monthly budget."""
        return self.monthly_spend_usd >= self.monthly_budget_usd

    def remaining_daily_budget(self) -> float:
        """Get remaining daily budget in USD."""
        return max(0.0, self.daily_budget_usd - self.current_spend_usd)

    def __repr__(self) -> str:
        return f"Quota(tenant={self.tenant_id}, daily=${self.current_spend_usd:.2f}/${self.daily_budget_usd:.2f})"


# =============================================================================
# DEFAULT QUOTA VALUES BY PLAN
# =============================================================================

DEFAULT_QUOTAS = {
    PlanTier.FREE: {
        "daily_budget_usd": 5.0,
        "monthly_budget_usd": 50.0,
        "daily_requests_gemini": 100,
        "daily_requests_claude": 50,
        "max_workspaces": 1,
        "max_agents": 3,
        "max_concurrent_tasks": 1,
        "hive_mind_enabled": False,
        "swarm_enabled": False,
        "evolution_enabled": False,
    },
    PlanTier.PRO: {
        "daily_budget_usd": 50.0,
        "monthly_budget_usd": 500.0,
        "daily_requests_gemini": 1000,
        "daily_requests_claude": 500,
        "max_workspaces": 5,
        "max_agents": 10,
        "max_concurrent_tasks": 4,
        "hive_mind_enabled": True,
        "swarm_enabled": True,
        "evolution_enabled": False,
    },
    PlanTier.ENTERPRISE: {
        "daily_budget_usd": 500.0,
        "monthly_budget_usd": 5000.0,
        "daily_requests_gemini": 10000,
        "daily_requests_claude": 5000,
        "max_workspaces": 50,
        "max_agents": 100,
        "max_concurrent_tasks": 10,
        "hive_mind_enabled": True,
        "swarm_enabled": True,
        "evolution_enabled": True,
    },
}


def create_quota_for_plan(tenant_id: UUID, plan: PlanTier) -> Quota:
    """
    Create a Quota instance with defaults for the given plan tier.

    Args:
        tenant_id: The tenant's UUID
        plan: The plan tier

    Returns:
        Quota instance with plan-appropriate limits
    """
    defaults = DEFAULT_QUOTAS.get(plan, DEFAULT_QUOTAS[PlanTier.FREE])
    return Quota(tenant_id=tenant_id, **defaults)
