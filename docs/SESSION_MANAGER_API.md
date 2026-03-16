# SwarmSessionManager API Documentation

**NEXUS V7.8 - Phase 7: Session Isolation & Context Management**

The `SwarmSessionManager` prevents "Context Bleeding" in parallel Swarm tasks by assigning unique session UUIDs to each agent-role combination.

## Overview

When running parallel tasks with the Gemini CLI, each task needs its own isolated context. Without session isolation, multiple parallel tasks would share and corrupt each other's context.

```
Problem: Context Bleeding
+-------------------------------------------------------------+
| Task A: "Analyze auth.py"    Task B: "Review tests"         |
|         |                            |                       |
|         +----------+-----------------+                       |
|                    v                                         |
|            Shared Gemini Context                             |
|            (Context Bleeding!)                               |
+-------------------------------------------------------------+

Solution: Session Isolation
+-------------------------------------------------------------+
| Task A: "Analyze auth.py"    Task B: "Review tests"         |
|         |                            |                       |
|         v                            v                       |
|   Session UUID-A               Session UUID-B                |
|   (Isolated)                   (Isolated)                    |
+-------------------------------------------------------------+
```

## Quick Start

```python
from pathlib import Path
from core.swarm.session_manager import SwarmSessionManager

# Initialize
manager = SwarmSessionManager(Path("workspace"))

# Create a task
task = manager.create_task(
    task_id="task_001",
    swarm_mode="PARALLEL"
)

# Get session UUID for each agent
gemini_uuid = manager.get_or_create_session("task_001", "worker", "gemini")
claude_uuid = manager.get_or_create_session("task_001", "worker", "claude")

# Pass to CLI: gemini --resume {gemini_uuid}
```

## Core Concepts

### Task
A unit of work being processed by the Swarm. Each task has:
- `task_id`: Unique identifier
- `swarm_mode`: Collaboration mode (PARALLEL, SEQUENTIAL, etc.)
- `roles`: Dictionary of agent sessions

### Session
An isolated context for one agent within a task. Each session has:
- `session_uuid`: Unique UUID for CLI resumption
- `agent_id`: Which agent (gemini, claude)
- `role`: Role in the task (lead, worker, support)
- `status`: PENDING, ACTIVE, COMPLETED, FAILED

### Session Mode
How a session is initialized:
- `FRESH`: New session, no prior context
- `CONTINUE`: Resume from existing session
- `BRANCH`: Fork from existing session (preserves context)

## API Reference

### SwarmSessionManager

#### Constructor

```python
SwarmSessionManager(workspace_path: Path)
```

Creates a new session manager. Registry is stored at `workspace/.nexus/session_registry.json`.

#### Methods

##### create_task()

```python
def create_task(
    task_id: str,
    swarm_mode: str,
    metadata: Optional[Dict] = None
) -> TaskSession
```

Create a new task session.

**Parameters:**
- `task_id`: Unique identifier for the task
- `swarm_mode`: Collaboration mode (PARALLEL, SEQUENTIAL, etc.)
- `metadata`: Optional additional metadata

**Returns:** TaskSession object

**Raises:** ValueError if task_id already exists

**Example:**
```python
task = manager.create_task("task_001", "PARALLEL", {"user": "yann"})
```

##### get_or_create_session()

```python
def get_or_create_session(
    task_id: str,
    role: str,
    agent_id: str,
    mode: SessionMode = SessionMode.FRESH,
    parent_session_uuid: Optional[str] = None
) -> str
```

Get or create a session UUID for an agent-role combination.

**IMPORTANT:** Task must exist before calling this method. Use `create_task()` or `get_or_create_task()` first.

**Parameters:**
- `task_id`: The task identifier
- `role`: Role in the task (e.g., "lead", "worker")
- `agent_id`: Agent identifier (e.g., "gemini", "claude")
- `mode`: Session initialization mode (default: FRESH)
- `parent_session_uuid`: For BRANCH mode, the parent session

**Returns:** Session UUID string

**Raises:** ValueError if task doesn't exist

**Example:**
```python
# WRONG - task doesn't exist yet!
uuid = manager.get_or_create_session("task_001", "worker", "gemini")  # Raises!

# CORRECT
manager.create_task("task_001", "PARALLEL")
uuid = manager.get_or_create_session("task_001", "worker", "gemini")  # OK
```

##### get_or_create_task()

```python
def get_or_create_task(
    task_id: str,
    swarm_mode: str,
    metadata: Optional[Dict] = None
) -> TaskSession
```

Get existing task or create new one.

**Example:**
```python
# Safe - creates if not exists
task = manager.get_or_create_task("task_001", "PARALLEL")
uuid = manager.get_or_create_session("task_001", "worker", "gemini")
```

##### create_checkpoint()

```python
def create_checkpoint(task_id: str) -> str
```

Create a checkpoint for crash recovery.

**Returns:** Checkpoint ID string

**Example:**
```python
cp_id = manager.create_checkpoint("task_001")
# Later: restore_checkpoint(cp_id)
```

##### complete_task()

```python
def complete_task(task_id: str, success: bool = True) -> None
```

Mark a task as completed or failed.

**Example:**
```python
try:
    # ... execute task ...
    manager.complete_task("task_001", success=True)
except Exception:
    manager.complete_task("task_001", success=False)
```

##### cleanup_old_tasks()

```python
def cleanup_old_tasks(max_age_hours: int = 24) -> int
```

Remove old completed/failed tasks from registry.

**Returns:** Number of tasks cleaned up

## Common Patterns

### Pattern 1: Simple Task Execution

```python
from core.swarm.session_manager import SwarmSessionManager

manager = SwarmSessionManager(Path("workspace"))

# 1. Create task
task_id = f"task_{uuid.uuid4().hex[:8]}"
manager.create_task(task_id, "PARALLEL")

# 2. Get sessions for each agent
gemini_session = manager.get_or_create_session(task_id, "worker_0", "gemini")
claude_session = manager.get_or_create_session(task_id, "worker_1", "claude")

# 3. Execute with sessions
# gemini --resume {gemini_session} -p "..."
# claude --resume {claude_session} -p "..."

# 4. Mark complete
manager.complete_task(task_id)
```

### Pattern 2: Lead-Support Mode

```python
# Lead drives, support assists
manager.create_task("audit_task", "LEAD_SUPPORT")

lead_session = manager.get_or_create_session("audit_task", "lead", "claude")
support_session = manager.get_or_create_session("audit_task", "support", "gemini")

# Lead executes first
# gemini CLI: --resume {lead_session}

# Support reviews lead's output
# gemini CLI: --resume {support_session}
```

### Pattern 3: With Checkpoints

```python
manager.create_task("long_task", "SEQUENTIAL")

# Checkpoint before risky operation
cp_id = manager.create_checkpoint("long_task")

try:
    # ... risky operation ...
except Exception:
    # Restore from checkpoint
    manager.restore_checkpoint(cp_id)
```

### Pattern 4: Branching Sessions

```python
# Create main session
main_session = manager.get_or_create_session(
    "task_001", "main", "gemini",
    mode=SessionMode.FRESH
)

# Branch for experimentation (preserves context)
branch_session = manager.get_or_create_session(
    "task_001", "experiment", "gemini",
    mode=SessionMode.BRANCH,
    parent_session_uuid=main_session
)
```

## Integration with Gemini CLI

The session UUID is passed to Gemini CLI via `--resume`:

```python
# In GeminiDriverV7
cmd = ["gemini", "--resume", session_uuid, "-p", prompt]
subprocess.run(cmd, ...)
```

This ensures each task gets isolated context that persists across multiple CLI invocations.

## Persistence

The session registry is stored at:
```
workspace/.nexus/session_registry.json
```

Format:
```json
{
  "version": "1.0",
  "updated_at": "2025-12-07T19:40:00",
  "tasks": {
    "task_001": {
      "task_id": "task_001",
      "swarm_mode": "PARALLEL",
      "status": "completed",
      "roles": {
        "worker_0": {
          "agent_id": "gemini",
          "session_uuid": "8df53386-bcdf-43e6-85e0-631b5596311c",
          "role": "worker_0"
        }
      }
    }
  }
}
```

## Thread Safety

SwarmSessionManager is thread-safe:
- All methods use internal `RLock`
- AtomicJsonStore handles concurrent writes safely
- Safe for parallel Swarm execution

## Error Handling

```python
# Task not found
try:
    manager.get_or_create_session("nonexistent", "worker", "gemini")
except ValueError as e:
    print(f"Task not found: {e}")

# Duplicate task
try:
    manager.create_task("task_001", "PARALLEL")
    manager.create_task("task_001", "PARALLEL")  # Raises!
except ValueError as e:
    print(f"Task already exists: {e}")
```

## Best Practices

1. **Always create task first**: Call `create_task()` before `get_or_create_session()`
2. **Use unique task IDs**: Include timestamp or UUID to avoid collisions
3. **Clean up old tasks**: Call `cleanup_old_tasks()` periodically
4. **Use checkpoints for long tasks**: Create checkpoints before risky operations
5. **Mark tasks complete**: Always call `complete_task()` when done

## Related Modules

- `core/drivers/gemini_driver_v7.py`: Uses session UUIDs for CLI invocation
- `core/swarm/hybrid_swarm_engine.py`: Creates tasks and sessions automatically
- `core/utils/atomic_store.py`: Thread-safe JSON persistence
