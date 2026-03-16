# Cerebro API

## Synopsis
FastAPI application providing real-time event streaming, state persistence, and control plane for NEXUS. Multi-tenant architecture with Redis pub/sub, JWT authentication, RBAC, and HTTP rate limiting.

## Component Map
| File | Purpose | Key Exports |
|------|---------|-------------|
| `app.py` | FastAPI application factory | `create_cerebro_app()`, `app` |
| `middleware.py` | Tenant context extraction | `TenantContextMiddleware` |
| `rate_limit.py` | HTTP rate limiting | `setup_rate_limiting()` |
| `rbac.py` | Role-Based Access Control | `require_permission()` |
| `deps.py` | FastAPI dependencies | `get_current_user()`, `get_admin_user()` |
| `__init__.py` | Module exports | - |

## Key Features

### Application Lifecycle
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Connect Redis, register event loop
    yield
    # Shutdown: Disconnect Redis
```

### Middleware Stack
1. **CORS** - Explicit origins from `NEXUS_CORS_ORIGINS`
2. **TenantContextMiddleware** - Extract `X-Tenant-ID`, set SessionContext
3. **Rate Limiting** (V12.1 RETINA) - Per-endpoint limits

### Included Routers
- **Core (V10):** `/health`, `/ws/stream`
- **V11.5 CORTEX:** `/api/state`, `/api/interactions`, `/api/workflow`, `/api/files`
- **V11.6 KEYMAKER:** `/api/auth`
- **V12.2 IRONCLAD:** `/api/users`
- **V13.0 MEMORIA:** `/api/memory`

## CORS Configuration
```bash
NEXUS_CORS_ORIGINS=http://localhost:3000,https://nexus.example.com
```

## Dependencies
- **Internal**: `core.events.redis_bus`, `core.api.cerebro.*`, `core.api.cerebro.routes.*`
- **External**: `fastapi`, `fastapi.middleware.cors`

## Integration Points

**Deployment:**
```bash
uvicorn core.api.cerebro.app:create_cerebro_app --factory --port 8080
```

**Client:**
```typescript
// WebSocket
const ws = new WebSocket('ws://localhost:8080/ws/stream?tenant_id=acme');

// REST with JWT
fetch('http://localhost:8080/api/state/snapshot', {
  headers: {
    'Authorization': `Bearer ${token}`,
    'X-Tenant-ID': 'acme'
  }
});
```

**Tenant Isolation:**
- All routes extract `X-Tenant-ID`
- SessionContext per request
- DB queries filtered by tenant_id
- Redis channels namespaced by tenant

## V12.4 COGNITIVE BOOST Additions

| File | Purpose | Key Exports |
|------|---------|-------------|
| `endpoint_analytics.py` | Per-endpoint performance tracking with request counts, throughput, latency distribution, error rates, error-prone endpoint detection, and slowest endpoint identification | `get_endpoint_analytics`, `EndpointAnalytics` |

## Version History
- V10: Initial CEREBRO API
- V11.3 HARDENING: CORS from environment
- V11.5 CORTEX: State/interactions/workflow/files
- V11.6 KEYMAKER: JWT auth
- V12.1 RETINA: Rate limiting
- V12.2 IRONCLAD: User management, RBAC
- V12.4 COGNITIVE BOOST: Endpoint analytics
- V13.0 MEMORIA: Memory API
