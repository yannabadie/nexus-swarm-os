# Audit

## Synopsis
Append-only audit logging for compliance and security. Provides async-safe logging interface, SQLModel persistence, and Human-in-the-Loop (HITL) request tracking.

## Component Map
| File | Purpose | Key Exports |
|------|---------|-------------|
| `models.py` | SQLModel definitions | `AuditLog`, `HITLRequest`, `AuditAction`, `AuditStatus`, `HITLRequestStatus`, `HITLRequestType` |
| `audit_logger.py` | Async logging interface | `AuditLogger` |
| `__init__.py` | Module exports | All above |

## Key Interfaces

### AuditLogger
Append-only audit logger with async support.

**Core Methods:**
```python
# Generic audit log
await AuditLogger.log(
    tenant_id=user.tenant_id,
    user_id=user.id,
    action=AuditAction.FILE_READ,
    resource_type="file",
    resource_id="/path/to/file.py",
    status=AuditStatus.SUCCESS,
    request=request  # FastAPI Request for IP/user-agent
)

# Convenience methods
await AuditLogger.log_auth(tenant_id, user_id, action, success, request)
await AuditLogger.log_file(tenant_id, user_id, action, file_path, success, request)
await AuditLogger.log_permission_denied(tenant_id, user_id, permission, resource_type)

# Query logs
logs = await AuditLogger.query(
    tenant_id=user.tenant_id,
    status=AuditStatus.DENIED,
    since=datetime.now() - timedelta(days=7),
    limit=50
)

# Count logs
count = await AuditLogger.count(tenant_id=user.tenant_id, status=AuditStatus.ERROR)

# Cleanup old logs
deleted = await AuditLogger.cleanup(retention_days=90)
```

**Design:**
- Thread-safe: Uses `asyncio.to_thread()` for DB operations
- Append-only: Only INSERT, never UPDATE/DELETE
- Fast: Non-blocking async interface
- Reliable: Catches errors, never fails requests

### AuditLog Model
SQLModel for audit entries.

**Fields:**
- `id`: UUID
- `tenant_id`: UUID (multi-tenant isolation)
- `user_id`: UUID
- `action`: str (AuditAction enum value)
- `resource_type`: str (file, user, workflow, etc.)
- `resource_id`: Optional[str] (path, ID, etc.)
- `status`: str (success, denied, error)
- `details`: Optional[str] (JSON details)
- `ip_address`: Optional[str]
- `user_agent`: Optional[str]
- `timestamp`: datetime (auto-generated)

### HITLRequest Model
SQLModel for Human-in-the-Loop persistence.

**Fields:**
- `id`: UUID
- `tenant_id`: UUID
- `workspace_id`: str
- `request_type`: str (ask, confirm, choose)
- `prompt`: str
- `options`: Optional[str] (JSON array)
- `context_data`: Optional[str] (JSON)
- `status`: str (pending, answered, expired, cancelled)
- `answer`: Optional[str]
- `created_at`, `answered_at`, `expires_at`: datetime

**Methods:**
- `is_expired()`: Check if past expiration
- `is_pending()`: Check if still awaiting response

## Dependencies
- **Internal**: `core.db` (get_session)
- **External**: `sqlmodel`, `asyncio`, `json`, `logging`

## Integration Points

**Used By:**
- `core.api.cerebro.routes.*` - All sensitive operations
- `core.api.cerebro.rbac` - Permission denials
- `core.api.cerebro.routes.auth` - Authentication events
- `core.api.cerebro.routes.files` - File access
- `core.api.cerebro.routes.users` - User management

**Use Cases:**
1. Compliance: Track all file reads/writes
2. Security: Log authentication failures, permission denials
3. Debugging: Audit trail for error analysis
4. Analytics: Usage patterns, user activity

## Version History
- V12.2 IRONCLAD: Initial implementation (Claude, 2025-12-16)
- Problem Solved: No audit trail for multi-tenant operations
