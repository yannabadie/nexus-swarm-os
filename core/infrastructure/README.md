# NEXUS V12.4 - Infrastructure Package

**P5.6 Phase 2: Package Consolidation for Reduced Cognitive Load**

This package consolidates all infrastructure-related components into a unified domain, reducing the number of top-level packages from 40 to 18.

## 📦 Package Structure

```
core/infrastructure/
+-- __init__.py           # Unified exports for all subpackages
+-- README.md             # This file
+-- context/              # Multi-tenant session management
|   +-- __init__.py
|   +-- session.py        # SessionContext, context managers
|   +-- audit_trail.py    # Context audit trail (V12.4)
|   +-- README.md
+-- db/                   # Database engine and models
|   +-- __init__.py
|   +-- engine.py         # SQLModel engine, session management
|   +-- models.py         # Tenant, User, Workspace, Quota models
|   +-- query_performance_tracker.py  # Query profiling (V12.4)
|   +-- README.md
+-- bootstrap/            # Startup and agent loading
|   +-- __init__.py
|   +-- auto_bootstrap.py # NEXUS.md auto-generation
|   +-- agent_loader.py   # Spawned agent discovery
|   +-- service.py        # Bootstrap service layer
|   +-- startup_analytics.py  # Boot profiling (V12.4)
|   +-- README.md
+-- session/              # Session lifecycle management
|   +-- __init__.py
|   +-- workspace_manager.py  # Session workspace isolation
|   +-- home_isolator.py      # HOME env spoofing for Gemini isolation
|   +-- state_recovery.py     # State snapshot/recovery (V12.4)
|   +-- session_analytics.py  # Session metrics (V12.4)
|   +-- session_efficiency_scorecard.py  # Session efficiency (V12.4)
|   +-- README.md
+-- resilience/           # Fault tolerance and resilience
    +-- __init__.py
    +-- circuit_breaker.py    # Circuit breaker pattern
    +-- system_health.py      # Unified health monitoring
    +-- rate_limiter.py       # Rate limiting (token bucket)
    +-- checkpoint_manager.py # Checkpointing (V12.4)
    +-- request_deduplicator.py  # Duplicate request detection (V12.4)
    +-- resilience_event_tracker.py  # Resilience event analytics (V12.4)
    +-- runtime_waste_filter.py  # Runtime waste detection (arxiv:2510.26585)
    +-- unified_rate_limiter.py   # Advanced rate limiting
    +-- README.md
```

## 🎯 Domain Purpose

The infrastructure package provides **foundational system capabilities** through:

1. **Context Management** - Multi-tenant request scoping and session context
2. **Database Layer** - ORM, multi-tenancy, query tracking
3. **Bootstrap** - Startup automation, agent discovery, analytics
4. **Session Management** - Workspace isolation, state recovery, analytics
5. **Resilience** - Circuit breakers, health monitoring, fault tolerance

## 📊 Key Components

### Context Subsystem

```python
from core.infrastructure import (
    SessionContext,
    use_context,
    get_current_session
)

# Set multi-tenant context
with use_context(tenant_id="acme", user_id="alice", workspace_id="project-x"):
    ctx = get_current_session()
    print(f"Tenant: {ctx.tenant_id}, User: {ctx.user_id}")
    # All operations within this block have access to the context

# Async version
async with use_context_async(tenant_id="acme"):
    ctx = get_current_session()
    await some_async_operation()

# Decorator for context requirement
from core.infrastructure import require_context

@require_context
def tenant_specific_function():
    ctx = get_current_session()
    # Context is guaranteed to exist here
```

**Features:**
- Thread-safe context isolation using `contextvars`
- Multi-tenant request scoping (tenant_id, user_id, workspace_id)
- Context audit trail for debugging (V12.4)
- Backward compatibility with default context

**Important Naming Note:**
- `SessionContext` - The context dataclass (tenant_id, user_id, etc.)
- `SessionUserRole` - User role enum from context package (ADMIN, USER, SERVICE, GUEST)
- `UserRole` - Database user role enum (OWNER, ADMIN, MEMBER, VIEWER)

### Database Subsystem

```python
from core.infrastructure import (
    init_db,
    get_session,
    Tenant,
    User,
    Workspace,
    PlanTier,
    get_tenant_by_slug
)

# Initialize database (creates tables)
init_db(db_path="workspace/.nexus/nexus.db")

# Create a tenant
with get_session() as session:
    tenant = Tenant(
        name="Acme Corp",
        slug="acme",
        plan_tier=PlanTier.PRO
    )
    session.add(tenant)
    session.commit()

# Query with helpers
tenant = get_tenant_by_slug(session, "acme")
quota = get_tenant_quota(session, tenant.id)
```

**Features:**
- SQLModel ORM (Pydantic + SQLAlchemy)
- Multi-tenant data model (Tenant, User, Workspace, Quota)
- Plan-based quota management (FREE, STARTER, PRO, ENTERPRISE)
- Query performance tracking (V12.4)
- Singleton engine pattern with reset capability

### Bootstrap Subsystem

```python
from core.infrastructure import (
    AutoBootstrap,
    SpawnedAgentLoader,
    BootstrapService,
    discover_and_register_spawned_agents
)

# Auto-generate NEXUS.md when deployed to new project
bootstrap = AutoBootstrap(workspace_path=Path.cwd())
analysis = await bootstrap.analyze_project()
await bootstrap.generate_nexus_md(analysis)

# Discover spawned agents in workspace/agents/
agents = discover_and_register_spawned_agents(workspace_path=Path("workspace"))

# Service layer
from core.infrastructure import _get_bootstrap_service
service = _get_bootstrap_service()
result = await service.bootstrap_project()
```

**Features:**
- Auto-generation of NEXUS.md for new projects
- Spawned agent discovery from workspace/agents/
- Project structure analysis (tech stack detection)
- Startup analytics and profiling (V12.4)
- Service layer for async operations

### Session Subsystem

```python
from core.infrastructure import (
    SessionWorkspaceManager,
    HomeIsolator,
    StateRecoveryManager,
    get_session_analytics
)

# Session workspace isolation
manager = SessionWorkspaceManager(workspace_path=Path("workspace"))

# Get isolated environment for subprocess (Gemini session isolation)
isolated_env = manager.get_isolated_env(
    session_id="task_123_lead",
    task_type="swarm"
)

# Pass to subprocess (CWD stays at project root!)
subprocess.Popen(cmd, env=isolated_env, cwd=workspace_path)

# Cleanup after task
manager.cleanup_workspace("task_123_lead", "swarm")

# State recovery (V12.4)
recovery = get_recovery_manager()
snapshot = await recovery.create_snapshot(
    session_uuid="abc123",
    reason="before_risky_operation"
)

# Session analytics
analytics = get_session_analytics()
stats = analytics.get_stats()
print(f"Total sessions: {stats.total_sessions}")
```

**Features:**
- V9.7.1 HOME spoofing for Gemini session isolation (prevents context bleeding)
- Workspace isolation per session/task
- State snapshot/recovery for crash resilience (V12.4)
- Session analytics and efficiency scorecard (V12.4)
- Automatic cleanup on task completion

### Resilience Subsystem

```python
from core.infrastructure import (
    CircuitBreaker,
    SystemHealth,
    get_checkpoint_manager,
    RuntimeWasteFilter
)

# Circuit breaker for fault tolerance
breaker = get_circuit_breaker("gemini_api")

try:
    with breaker:
        response = await call_gemini_api()
except CircuitOpenError:
    print("Circuit is open, too many failures")

# System health monitoring
health = get_system_health()
health.register_component("gemini", check_fn=lambda: check_gemini_health())
report = health.get_health_report()

# Checkpoint for state recovery
checkpoint_mgr = get_checkpoint_manager()
checkpoint = await checkpoint_mgr.create_checkpoint(
    session_uuid="abc123",
    state_data={"current_phase": "execution", "step": 5}
)

# Runtime waste detection (arxiv:2510.26585)
from core.infrastructure import get_runtime_waste_filter
waste_filter = get_runtime_waste_filter()
intervention = waste_filter.check_exchange(
    exchange_record={
        "prompt": "...",
        "response": "...",
        "reasoning_quality": 0.3  # Low quality
    }
)
if intervention:
    print(f"Intervention: {intervention.action}")
```

**Features:**
- Circuit breaker pattern with configurable thresholds
- Unified system health monitoring (V9.5+)
- Rate limiting with token bucket algorithm
- Checkpoint manager for state snapshots (V12.4)
- Request deduplication (V12.4)
- Resilience event tracking and analytics (V12.4)
- Runtime waste filter (arxiv:2510.26585) - detects unproductive LLM exchanges

## 🔧 Migration Impact

**Before P5.6 Phase 2:**
```python
from core.context import get_current_session
from core.db import init_db, get_session
from core.bootstrap import AutoBootstrap
from core.session import SessionWorkspaceManager
from core.resilience import CircuitBreaker
```

**After P5.6 Phase 2:**
```python
# All imports from unified package
from core.infrastructure import (
    get_current_session,
    init_db,
    get_session,
    AutoBootstrap,
    SessionWorkspaceManager,
    CircuitBreaker
)

# Or from subpackages
from core.infrastructure.context import get_current_session
from core.infrastructure.db import init_db
from core.infrastructure.bootstrap import AutoBootstrap
from core.infrastructure.session import SessionWorkspaceManager
from core.infrastructure.resilience import CircuitBreaker
```

**Statistics:**
- **Files migrated:** 27 Python files + 5 READMEs
- **Import updates:** 96 files across codebase
- **Commits:** 5 atomic commits (55a3af5, 4a96d98, 51085cd, 3a3b905, a43e46c)
- **Impact:** 85 files changed, +436/-154 lines

## 📚 Related Documentation

- [Context README](context/README.md) - Multi-tenant session management
- [Database README](db/README.md) - SQLModel ORM and multi-tenancy
- [Bootstrap README](bootstrap/README.md) - Startup automation
- [Session README](session/README.md) - Session lifecycle management
- [Resilience README](resilience/README.md) - Fault tolerance patterns

## 🚀 Next Steps (P5.6 Phase 3-8)

Phase 2 (Infrastructure) is complete. Remaining phases:

- **Phase 3**: Interface (interface, workspace, notifications, mcp)
- **Phase 4**: Security (security, governance, interaction)
- **Phase 5**: Memory (memory, prompts, skills)
- **Phase 6**: Execution (DEFERRED - high complexity)
- **Phase 7**: Intelligence (DEFERRED - high complexity)
- **Phase 8**: Final validation and documentation

---

**Version:** NEXUS V12.4 COGNITIVE BOOST
**Status:** P5.6 Phase 2 COMPLETE [OK]
**Date:** 2026-02-19
