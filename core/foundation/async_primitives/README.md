# Async Primitives

## Synopsis
Core async building blocks for NEXUS Async-First architecture. Provides cancellation tokens, process tracking, read-write locks, shared state, task management, and event bus.

## Component Map
| File | Purpose | Key Exports |
|------|---------|-------------|
| `cancellation.py` | Hierarchical cancellation | `CancellationToken`, `CancellationTokenSource` |
| `process_handle.py` | Track async subprocesses by session | `AsyncProcessHandle`, `ProcessHandleRegistry` |
| `rwlock.py` | Multiple readers OR single writer lock | `AsyncRWLock`, `AsyncRWLockWithTimeout`, `InstrumentedAsyncRWLock` |
| `blackboard.py` | Thread-safe async shared state | `AsyncBlackboard` |
| `safe_task_manager.py` | Fire-and-forget task error tracking | `SafeTaskManager`, `create_safe_task` |
| `event_bus.py` | Lightweight async pub/sub | `EventBus`, `SyncEvent`, `EventType`, `get_event_bus` |
| `__init__.py` | Module exports | All above |

## Key Interfaces

### CancellationToken
Hierarchical cancellation with propagation.

```python
token = CancellationToken()
child = token.create_child()

def on_cancel():
    print("Cancelled!")
token.on_cancel(on_cancel)

token.cancel(reason="User requested")
token.check()  # Raises if cancelled
```

### AsyncProcessHandle
Track subprocess by session_uuid, task_id, agent_id.

```python
handle = AsyncProcessHandle(proc, session_uuid="abc-123")
await handle.terminate_gracefully(timeout=5.0)
runtime = handle.runtime_seconds()
```

### AsyncRWLock
Multiple readers OR single writer.

```python
lock = AsyncRWLock()

async with lock.read():
    # Multiple readers allowed
    ...

async with lock.write():
    # Exclusive write access
    ...
```

### AsyncBlackboard
Thread-safe async shared state with TTL and versioning.

```python
bb = AsyncBlackboard()
version = bb.set("key", value, ttl_seconds=60)
value = bb.get("key", default=None)
success, new_version = bb.compare_and_set("key", expected_version, new_value)
```

### SafeTaskManager (V9.5)
Fire-and-forget task error tracking.

```python
manager = SafeTaskManager()
task = await manager.create_task(
    some_coro(),
    name="background_job",
    on_error=lambda e: print(f"Error: {e}")
)
stats = manager.get_stats()
```

### EventBus (V9.5)
Lightweight async pub/sub for synchronization events.

```python
bus = get_event_bus()

def handler(event: SyncEvent):
    print(event.payload)

bus.subscribe(EventType.STATE_CHANGE, handler)
bus.publish(SyncEvent(
    event_type=EventType.STATE_CHANGE,
    source="orchestrator",
    task_id="task-123",
    payload={"from": "IDLE", "to": "BRAINSTORMING"}
))
```

## Dependencies
- **Internal**: None (standalone primitives)
- **External**: `asyncio`, `threading`, `dataclasses`, `datetime`, `collections`

## Integration Points

**Used By:**
- `core.orchestration_v7` - Cancellation, state management
- `core.swarm.executors` - Process tracking, RW locks
- `core.hive_mind` - Blackboard for phase coordination
- `core.resilience` - EventBus for checkpointing
- `core.execution` - SafeTaskManager for background tasks

## Version History
- V9.0: CancellationToken, AsyncProcessHandle, AsyncRWLock, AsyncBlackboard
- V9.5: SafeTaskManager, EventBus
