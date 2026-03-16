# Cerebro Routes

## Synopsis
FastAPI route modules for CEREBRO API. Organized by domain: health, streaming, state, interactions, workflow, files, auth, users, and memory.

## Component Map
| File | Endpoints | Purpose |
|------|-----------|---------|
| `health.py` | `GET /health`, `GET /health/redis` | Health checks |
| `stream.py` | `WS /ws/stream` | WebSocket streaming |
| `state.py` | `GET /api/state/snapshot`, `GET /api/state/history` | FSM state snapshots |
| `interactions.py` | `GET /api/interactions/pending`, `POST /api/interactions/{id}/respond` | HITL management |
| `workflow.py` | `POST /api/workflow/start`, `POST /api/workflow/stop` | Workflow control |
| `files.py` | `GET /api/files/content`, `POST /api/files/content` | File access |
| `auth.py` | `POST /api/auth/login`, `POST /api/auth/refresh`, `GET /api/auth/me`, `POST /api/auth/logout` | JWT auth (V11.6) |
| `users.py` | `GET /api/users`, `POST /api/users/invite`, `DELETE /api/users/{id}`, `PUT /api/users/{id}/role` | User management (V12.2) |
| `memory.py` | `GET /api/memory/stats`, `GET /api/memory/namespaces`, `POST /api/memory/ingest` | Memory API (V13.0) |

## Common Patterns

### Multi-Tenant Isolation
```python
from core.context import get_current_session

@router.get("/endpoint")
async def endpoint():
    ctx = get_current_session()
    tenant_id = ctx.tenant_id
    # Query filtered by tenant_id
```

### Authentication
```python
from core.api.cerebro.deps import get_current_user

@router.get("/endpoint")
async def endpoint(user = Depends(get_current_user)):
    # user.id, user.tenant_id, user.role available
```

### RBAC Enforcement
```python
from core.api.cerebro.rbac import require_permission

@router.post("/admin-only")
@require_permission("admin")
async def admin_endpoint(user = Depends(get_current_user)):
    # Only accessible to admin role
```

### Audit Logging
```python
from core.audit import AuditLogger, AuditAction

await AuditLogger.log_file(
    tenant_id=user.tenant_id,
    user_id=user.id,
    action=AuditAction.FILE_READ,
    file_path="/path/to/file.py",
    success=True,
    request=request
)
```

### Rate Limiting (V12.1 RETINA)
```python
"/api/auth/login": 5 requests/minute
"/api/users/invite": 10 requests/minute
```

## Dependencies
- **Internal**: `core.context`, `core.db`, `core.audit`, `core.api.cerebro.deps`, `core.api.cerebro.rbac`, `core.events.redis_bus`
- **External**: `fastapi`, `pydantic`

## Version History
- V10: Health, stream, state
- V11.5 CORTEX: Interactions, workflow, files
- V11.6 KEYMAKER: Auth (JWT)
- V12.2 IRONCLAD: Users (RBAC)
- V13.0 MEMORIA: Memory (RAG)
