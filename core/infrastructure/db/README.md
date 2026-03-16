# Database

## Synopsis
Multi-tenant control plane using SQLModel ORM. Provides tenant, user, workspace, and quota management with SQLite backend.

## Component Map
| File | Purpose | Key Exports |
|------|---------|-------------|
| `models.py` | SQLModel definitions | `Tenant`, `User`, `Workspace`, `Quota`, `PlanTier`, `TenantStatus`, `UserRole` |
| `engine.py` | Engine and session management | `get_engine`, `init_db`, `get_session`, `create_default_tenant`, `get_tenant_by_slug` |
| `__init__.py` | Module exports | All above |

## Key Interfaces

### SQLModel Definitions

**Tenant:**
```python
class Tenant(SQLModel, table=True):
    id: UUID
    name: str               # "Acme Corp"
    slug: str               # "acme" (unique)
    plan_tier: PlanTier     # FREE, PRO, ENTERPRISE
    status: TenantStatus    # ACTIVE, SUSPENDED, PENDING
    created_at, updated_at: datetime
    email: Optional[str]

    # Relationships
    users: List["User"]
    workspaces: List["Workspace"]
    quota: Optional["Quota"]
```

**User:**
```python
class User(SQLModel, table=True):
    id: UUID
    tenant_id: UUID (foreign key)
    username: str
    email: str (unique)
    hashed_password: str
    role: UserRole          # OWNER, ADMIN, MEMBER, VIEWER
    is_active: bool
    last_login: Optional[datetime]
    created_at: datetime

    # Relationship
    tenant: Optional[Tenant]
```

**Workspace:**
```python
class Workspace(SQLModel, table=True):
    id: UUID
    tenant_id: UUID (foreign key)
    name: str
    slug: str (unique within tenant)
    filesystem_path: str    # Absolute path
    description: Optional[str]
    created_at, updated_at: datetime
    is_active: bool

    # Relationship
    tenant: Optional[Tenant]
```

**Quota:**
```python
class Quota(SQLModel, table=True):
    id: UUID
    tenant_id: UUID (foreign key, unique)
    daily_budget_usd: float
    daily_requests_gemini: int
    daily_requests_claude: int
    monthly_budget_usd: float
    max_workspaces: int
    max_agents: int
    max_concurrent_tasks: int
    hive_mind_enabled: bool
    swarm_enabled: bool
    evolution_enabled: bool
    current_spend_usd: float
    current_requests_gemini: int
    current_requests_claude: int
    monthly_spend_usd: float
    daily_reset_at, monthly_reset_at: datetime

    # Methods
    is_over_daily_budget() -> bool
    is_over_monthly_budget() -> bool
    remaining_daily_budget() -> float
```

### Engine Management

**Initialize database:**
```python
from core.db import init_db

init_db()  # Creates tables if they don't exist
```

**Session management:**
```python
from core.db import get_session

with get_session() as session:
    tenant = session.get(Tenant, tenant_id)
    # Auto-commit on success, rollback on exception
```

**Convenience functions:**
```python
from core.db import create_default_tenant, get_tenant_by_slug, get_tenant_quota

# Create default single-tenant setup
tenant, user, workspace, quota = create_default_tenant()

# Query by slug
tenant = get_tenant_by_slug(session, "acme")

# Get quota for tenant
quota = get_tenant_quota(session, tenant_id)
```

### Plan Tier Defaults

```python
DEFAULT_QUOTAS = {
    PlanTier.FREE: {
        "daily_budget_usd": 1.0,
        "daily_requests_gemini": 100,
        "daily_requests_claude": 50,
        "monthly_budget_usd": 20.0,
        "max_workspaces": 3,
        "max_agents": 5,
        "max_concurrent_tasks": 2,
        "hive_mind_enabled": False,
        "swarm_enabled": True,
        "evolution_enabled": False,
    },
    PlanTier.PRO: {
        "daily_budget_usd": 10.0,
        "daily_requests_gemini": 1000,
        "daily_requests_claude": 500,
        "monthly_budget_usd": 200.0,
        "max_workspaces": 20,
        "max_agents": 50,
        "max_concurrent_tasks": 10,
        "hive_mind_enabled": True,
        "swarm_enabled": True,
        "evolution_enabled": True,
    },
    PlanTier.ENTERPRISE: {
        # Unlimited/very high limits
    }
}
```

## Dependencies
- **Internal**: None (core data layer)
- **External**: `sqlmodel`, `sqlalchemy`, `uuid`, `datetime`, `pathlib`

## Integration Points

**Used By:**
- `core.api.cerebro.routes.auth` - User authentication
- `core.api.cerebro.routes.users` - User management
- `core.context` - Tenant context resolution
- `core.factory` - V10 PRISM ServiceFactory
- `core.audit` - Audit log persistence

**Database Location:**
- Default: `.nexus/master.db` (SQLite)
- Environment: `NEXUS_DB_PATH`

## V12.4 COGNITIVE BOOST Additions

| File | Purpose | Key Exports |
|------|---------|-------------|
| `query_performance_tracker.py` | Centralized tracking of database query performance including execution times, row counts, query type distribution (SELECT/INSERT/UPDATE/DELETE), table-level aggregate profiles, and bottleneck identification | `get_query_tracker`, `QueryPerformanceTracker` |

## Version History
- V10 PRISM: Initial implementation (Claude, 2025-12-15)
- V12.4: Query performance tracking
- Problem Solved: No multi-tenant data model
