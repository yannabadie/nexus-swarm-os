# Workflow Module

## Synopsis
The Workflow module provides Redis-backed workflow registry with distributed locking for NEXUS V12.3 SCALE-OUT. Enables multi-instance deployment where workflows are visible across all nodes with graceful degradation to in-memory storage when Redis is unavailable. Critical for horizontal scaling and multi-tenant deployments.

## Component Map
| File | Purpose | Key Exports |
|------|---------|-------------|
| `redis_registry.py` | Redis-backed workflow storage with tenant isolation and graceful degradation | `RedisWorkflowRegistry`, `WorkflowStatus`, `get_workflow_registry()`, `reset_workflow_registry()` |
| `distributed_lock.py` | Redlock pattern implementation for distributed locking | `DistributedLock`, `LockAcquisitionError` |
| `__init__.py` | Module initialization with public exports | All classes and functions from submodules |

## Key Interfaces

### RedisWorkflowRegistry

**`RedisWorkflowRegistry`**
- Singleton workflow registry with Redis backend
- Tenant-scoped workflow storage
- Automatic TTL (time-to-live) for workflows
- Graceful degradation to in-memory storage if Redis unavailable
- JSON serialization for workflow state

**Configuration:**
- `configure(redis_url: str = "redis://localhost:6379", use_redis: bool = True, workflow_ttl_hours: int = 72)`: Configure Redis connection and TTL

**Connection Management:**
- `connect() -> bool`: Connect to Redis (returns False if unavailable, falls back to memory)
- `disconnect()`: Disconnect from Redis

**Workflow CRUD:**
- `create_workflow(workflow_id: str, tenant_id: str, task: str, workspace_id: str = "default", complexity: Optional[str] = None) -> Dict`: Create new workflow
- `update_status(workflow_id: str, tenant_id: str, status: str, result: Any = None, error: Optional[str] = None) -> Optional[Dict]`: Update workflow status
- `get_workflow(workflow_id: str, tenant_id: str) -> Optional[Dict]`: Get workflow by ID
- `list_workflows(tenant_id: str, status: Optional[str] = None, limit: int = 100) -> List[Dict]`: List workflows for tenant
- `delete_workflow(workflow_id: str, tenant_id: str) -> bool`: Delete workflow

**Maintenance:**
- `cleanup_expired(max_age_hours: int = 72) -> int`: Cleanup expired workflows
- `get_stats() -> Dict`: Get registry statistics

**Workflow States:**
- `PENDING`: Workflow created, not yet started
- `RUNNING`: Workflow in progress
- `COMPLETED`: Workflow finished successfully
- `FAILED`: Workflow failed with error
- `CANCELLED`: Workflow cancelled by user

**Storage Keys:**
```
nexus:workflows:<tenant_id>:<workflow_id> -> JSON workflow data
nexus:workflows:<tenant_id>:index -> Set of workflow IDs
```

### DistributedLock

**`DistributedLock`**
- Redlock pattern implementation for distributed systems
- Automatic TTL and lock extension
- Context manager support for RAII pattern
- Prevents race conditions in multi-instance deployments

**Key Methods:**
- `acquire(blocking: bool = True, timeout: float = 10.0) -> bool`: Acquire lock
- `release() -> bool`: Release lock
- `extend(additional_ttl: int = 30) -> bool`: Extend lock TTL
- `is_acquired() -> bool`: Check if lock is held

**Context Manager:**
```python
async with DistributedLock(redis, "resource_name"):
    # Critical section
    pass
```

**Lock Keys:**
```
nexus:lock:<resource_name> -> owner_id (TTL: 30s default)
```

### Global Access

**`get_workflow_registry() -> RedisWorkflowRegistry`**
- Get singleton workflow registry instance
- Initializes if not already created

**`reset_workflow_registry() -> None`**
- Reset singleton (for testing)

## Dependencies & Integration

### External Dependencies
- `redis` (optional) - Redis client for distributed storage
- Falls back gracefully to in-memory if redis unavailable

### Internal Dependencies
- `json` - Workflow serialization
- `uuid` - Workflow ID generation
- `datetime` - Timestamps
- `threading` - Singleton lock

### Integration Points
- **V10 CEREBRO**: Tenant-scoped workflow storage
- **Multi-Instance Deployment**: Workflows visible across all nodes
- **HiveMind/SwarmEngine**: Can register long-running workflows
- **API**: `/workflows` endpoints use registry

### Usage Examples

```python
from core.workflow import get_workflow_registry, DistributedLock, WorkflowStatus
import asyncio

# Get registry singleton
registry = get_workflow_registry()

# Configure Redis (optional - falls back to memory)
registry.configure(
    redis_url="redis://localhost:6379",
    use_redis=True,
    workflow_ttl_hours=72
)

# Connect (graceful degradation if Redis unavailable)
connected = registry.connect()
if connected:
    print("Using Redis for workflow storage")
else:
    print("Redis unavailable, using in-memory storage")

# Create workflow
workflow = registry.create_workflow(
    workflow_id="wf_abc123",
    tenant_id="tenant_001",
    task="Process customer data",
    workspace_id="ws_default",
    complexity="MODERATE"
)
print(workflow)
# {
#   "workflow_id": "wf_abc123",
#   "tenant_id": "tenant_001",
#   "status": "PENDING",
#   "task": "Process customer data",
#   "created_at": "2025-12-17T10:30:00",
#   ...
# }

# Update status
registry.update_status(
    workflow_id="wf_abc123",
    tenant_id="tenant_001",
    status=WorkflowStatus.RUNNING
)

# List workflows for tenant
workflows = registry.list_workflows(
    tenant_id="tenant_001",
    status=WorkflowStatus.RUNNING,
    limit=50
)

# Complete workflow
registry.update_status(
    workflow_id="wf_abc123",
    tenant_id="tenant_001",
    status=WorkflowStatus.COMPLETED,
    result={"output": "Success"}
)

# Distributed locking
async def critical_section():
    redis = registry._redis  # Internal Redis client

    async with DistributedLock(redis, "shared_resource", ttl=60):
        # Only one instance can execute this at a time
        print("In critical section")
        await asyncio.sleep(5)
        # Lock automatically released on exit

# Cleanup old workflows
expired = registry.cleanup_expired(max_age_hours=72)
print(f"Cleaned up {expired} expired workflows")

# Get stats
stats = registry.get_stats()
print(stats)
# {
#   "mode": "redis",  # or "in_memory"
#   "connected": True,
#   "total_workflows": 42,
#   "by_status": {"RUNNING": 5, "COMPLETED": 30, "FAILED": 7}
# }
```

## Design Notes

### V12.3 SCALE-OUT

- **Multi-Instance**: Workflows visible across all NEXUS instances
- **Horizontal Scaling**: Add more instances without coordination
- **Tenant Isolation**: Workflows scoped to tenant_id
- **TTL Management**: Automatic cleanup after 72 hours (configurable)

### Graceful Degradation

- **Redis Optional**: Falls back to in-memory if Redis unavailable
- **No Hard Dependency**: System continues functioning without Redis
- **Automatic Fallback**: Detects Redis connection failure and switches mode
- **Memory Storage**: Dict-based in-memory storage for single-instance mode

### Distributed Locking

- **Redlock Pattern**: Industry-standard distributed lock algorithm
- **TTL Protection**: Locks expire automatically to prevent deadlocks
- **Lock Extension**: Can extend lock TTL for long operations
- **Race Condition Prevention**: Ensures only one instance modifies shared state

### Tenant Scoping

- **Namespace Isolation**: Each tenant has separate workflow namespace
- **Key Pattern**: `nexus:workflows:<tenant_id>:<workflow_id>`
- **Index Pattern**: `nexus:workflows:<tenant_id>:index`
- **Multi-Tenancy Ready**: Designed for SaaS deployments

### Future Enhancements

- **Event Streaming**: Publish workflow events to Redis Streams
- **Distributed Tracing**: OpenTelemetry integration
- **Workflow Recovery**: Automatic retry on instance failure

## V12.4 COGNITIVE BOOST Additions

| File | Purpose | Key Exports |
|------|---------|-------------|
| `workflow_performance_analyzer.py` | Runtime workflow execution analytics tracking execution times, step completion rates, bottleneck detection, workflow throughput, and parallel efficiency with per-workflow profiles | `get_workflow_analyzer`, `WorkflowPerformanceAnalyzer` |
| `dependency_graph.py` | DAG topology analysis for workflow steps with cycle detection, topological sort for execution order, parallelizable group identification, and critical path computation | `get_dependency_graph`, `DependencyGraph` |
