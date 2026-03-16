# Context

## Synopsis
Multi-tenant session management using Python's contextvars. Provides request-scoped context for tenant/user/workspace isolation across the entire stack.

## Component Map
| File | Purpose | Key Exports |
|------|---------|-------------|
| `session.py` | SessionContext and context management | `SessionContext`, `UserRole`, `current_session`, `get_current_session`, `use_context`, `require_context` |
| `__init__.py` | Module exports | All above |

## Key Interfaces

### SessionContext
Immutable context for request-scoped tenant isolation.

**Fields:**
```python
@dataclass(frozen=True)
class SessionContext:
    tenant_id: str              # Tenant UUID
    user_id: str                # User UUID
    workspace_id: str           # Workspace UUID
    role: UserRole              # ADMIN, USER, SERVICE, GUEST
    request_id: str             # Unique request ID
    created_at: datetime        # Context creation time
    workspace_root: Optional[Path]  # Filesystem root for workspace
```

**Methods:**
```python
# Computed property
ctx.tenant_workspace_path() -> Path  # workspace_root/tenant_id/workspace_id

# Create variant with different workspace
new_ctx = ctx.with_workspace(workspace_id="new-ws", workspace_root=Path("/data"))
```

### Context Management

**Set context:**
```python
from core.context import use_context, use_context_async

# Sync
with use_context(tenant_id="acme", user_id="alice"):
    ctx = get_current_session()
    print(ctx.tenant_id)  # "acme"

# Async
async with use_context_async(tenant_id="acme", user_id="alice"):
    ctx = get_current_session()
```

**Get context:**
```python
from core.context import get_current_session, get_current_session_or_none, has_active_session

# Raises if no context active
ctx = get_current_session()

# Returns None if no context
ctx = get_current_session_or_none()

# Check if context exists
if has_active_session():
    ctx = get_current_session()
```

**Require context (decorator):**
```python
from core.context import require_context

@require_context
def tenant_specific_operation():
    ctx = get_current_session()
    # Guaranteed to have active context
```

**Backward compatibility:**
```python
from core.context import get_default_context, ensure_context

# Get default single-tenant context
ctx = get_default_context()

# Ensure context exists (uses default if none)
ctx = ensure_context()
```

### UserRole Enum
```python
class UserRole(Enum):
    ADMIN = "admin"      # Full access
    USER = "user"        # Standard user
    SERVICE = "service"  # Service account
    GUEST = "guest"      # Read-only
```

## Dependencies
- **Internal**: None (core primitive)
- **External**: `contextvars`, `dataclasses`, `pathlib`, `datetime`, `uuid`

## Integration Points

**Used By:**
- `core.api.cerebro.middleware` - Extract tenant from HTTP headers
- `core.api.cerebro.routes.*` - All route handlers
- `core.db` - V10 PRISM tenant-scoped queries
- `core.factory` - V10 PRISM ServiceFactory
- `core.agents.unified_registry` - V10 PRISM tenant-scoped registry

**V10 PRISM Architecture:**
The context module is the "invisible spine" of NEXUS multi-tenancy:
```
Request -> Middleware -> Set SessionContext (contextvars)
   ↓
All code paths see tenant_id via get_current_session()
   ↓
DB queries auto-filtered by tenant_id
ServiceFactory returns tenant-scoped services
Agent registry returns tenant-scoped agents
```

**Critical:**
- ContextVars are thread-local and async-safe
- Context propagates to child tasks automatically
- Context does NOT cross process boundaries (subprocess needs explicit context)

## Version History
- V10 PRISM: Initial implementation (Claude, 2025-12-15)
- Problem Solved: No multi-tenant isolation in codebase
