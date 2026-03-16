# MISSION V8.1.6: Fix Parallel Execution (Thread Safety & Async)

**Version**: Complete (Claude Code verified)
**Date**: 2025-12-09
**Priority**: P1

---

## Context

We are implementing **Phase 14f** to enable true `PARALLEL` execution in the Hybrid Swarm.
Analysis revealed **Critical Race Conditions** in the current driver implementation:

1. **I/O Collision (CRITICAL):** Both `GeminiDriverV7` and `ClaudeDriverHybrid` use hardcoded filenames (`gemini_context_in.md`, `claude_context_in.md`, `gemini_output.json`). If two agents run in parallel, they corrupt each other's data.

2. **Missing Parameter:** `ClaudeDriverHybrid.invoke()` lacks the `session_uuid` parameter required for isolation.

3. **Broken Propagation:** The `session_uuid` is stored in the blackboard by `ModeExecutor` but is NOT passed through the full call chain.

4. **Blocking I/O:** Drivers use synchronous `subprocess.Popen` logic that blocks the thread.

---

## Call Chain Analysis

```
ModeExecutor._invoke()                          <- Has session_uuid in blackboard
    ↓ context.invoke_agent(agent_id, task_type, context)
    ↓ _wrap_invoke_agent().wrapper()            <- Must pass session_uuid
    ↓ self.invoke_agent()                       <- invoke_for_swarm
    ↓ AgentInvoker.invoke_for_swarm()           <- Must accept session_uuid
    ↓ AgentInvoker.invoke_agent_direct()        <- Must accept session_uuid
    ↓ driver.invoke(context, session_uuid)      <- Must use for unique filenames
```

---

## Implementation Steps

### Step 1: Standardize Driver Signatures

**File:** `core/drivers/claude_driver_hybrid.py`

Update `invoke()` (line 97) and `invoke_stream()` (line 231) to accept `session_uuid`:

```python
# BEFORE (line 97):
def invoke(self, context: str) -> Dict:

# AFTER:
def invoke(self, context: str, session_uuid: Optional[str] = None) -> Dict:
```

```python
# BEFORE (line 231):
def invoke_stream(self, context: str, on_token: Callable[[str], None]) -> Dict:

# AFTER:
def invoke_stream(self, context: str, on_token: Callable[[str], None],
                  session_uuid: Optional[str] = None) -> Dict:
```

---

### Step 2: Fix I/O Race Conditions - GeminiDriverV7

**File:** `core/drivers/gemini_driver_v7.py`

**Locations to fix:**
- Line 200: `context_file` in `_invoke_subprocess()`
- Line 205: `context_file_relative`
- Line 207: `output_file`
- Line 498: `context_file` in `_invoke_subprocess_stream()`
- Line 500: `context_file_relative`

**Pattern:**
```python
# Add at top of method:
unique_id = session_uuid or str(uuid.uuid4())[:8]

# Replace hardcoded filenames:
context_file = self.io_buffer / f"gemini_context_{unique_id}.md"
context_file_relative = Path("_IO_BUFFER") / f"gemini_context_{unique_id}.md"
output_file = self.io_buffer / f"gemini_output_{unique_id}.json"

# Add cleanup in finally block:
finally:
    # Cleanup unique files
    for f in [context_file, output_file]:
        if f.exists():
            try:
                f.unlink()
            except Exception:
                pass
```

---

### Step 3: Fix I/O Race Conditions - ClaudeDriverHybrid

**File:** `core/drivers/claude_driver_hybrid.py`

**Locations to fix:**
- Line 112: `context_file` in `invoke()`
- Line 254: `context_file` in `invoke_stream()`

**Pattern:** Same as Step 2

---

### Step 4: Propagate session_uuid - AgentInvoker

**File:** `core/orchestration/agent_invoker.py`

**4.1 Update invoke_for_swarm() (line 144):**
```python
# BEFORE:
def invoke_for_swarm(self, agent_id: str, task_type: str, context: str) -> str:

# AFTER:
def invoke_for_swarm(self, agent_id: str, task_type: str, context: str,
                     session_uuid: Optional[str] = None) -> str:
    # ... existing code ...
    # Line 189: Pass session_uuid
    response = self.invoke_agent_direct(task_type_enum, enriched_context,
                                        target_agent, session_uuid=session_uuid)
```

**4.2 Update invoke_agent_direct() (line 279):**
```python
# BEFORE:
def invoke_agent_direct(self, task_type: TaskType, context: str,
                        target_agent: Optional[str] = None) -> Dict:

# AFTER:
def invoke_agent_direct(self, task_type: TaskType, context: str,
                        target_agent: Optional[str] = None,
                        session_uuid: Optional[str] = None) -> Dict:
    # ... existing code ...
    # Pass session_uuid to driver.invoke()
    return driver.invoke(context, session_uuid=session_uuid)
```

**4.3 Update streaming calls (lines 137, 141):**
```python
# Pass session_uuid to invoke_stream as well
return driver.invoke_stream(context, self._orch.on_token, session_uuid=session_uuid)
```

---

### Step 5: Propagate session_uuid - HybridSwarmEngine

**File:** `core/swarm/hybrid_swarm_engine.py`

**Update _wrap_invoke_agent() (line 456):**
```python
def _wrap_invoke_agent(self) -> Callable:
    """Wrap invoke_agent to return AgentResponse"""
    def wrapper(agent_id: str, task_type: str, context: str,
                session_uuid: Optional[str] = None) -> AgentResponse:
        # ... existing code ...
        # Line 472: Pass session_uuid
        response = self.invoke_agent(agent_id, task_type, context,
                                     session_uuid=session_uuid)
        # ...
    return wrapper
```

---

### Step 6: Propagate session_uuid - ModeExecutors

**File:** `core/swarm/mode_executors.py`

**6.1 Update ExecutionContext (line 106):**
```python
# Update callable signature comment:
invoke_agent: Optional[Callable] = None  # Callable[[str, str, str, Optional[str]], AgentResponse]
```

**6.2 Update _invoke() (around line 226):**
```python
# BEFORE:
response = context.invoke_agent(agent_id, "execution", task_context)

# AFTER:
response = context.invoke_agent(agent_id, "execution", task_context, session_uuid)
```

---

### Step 7: Create AsyncDriverAdapter (Optional Enhancement)

**File:** `core/drivers/async_adapter.py` (NEW)

```python
"""
Async adapter for synchronous LLM drivers.

V8.1.6: Enables true parallel execution via asyncio.gather()
"""
import asyncio
from typing import Dict, Optional, Callable

class AsyncDriverAdapter:
    """
    Wraps synchronous drivers for async execution.

    Uses asyncio.to_thread (Python 3.9+) to run blocking
    driver.invoke() without blocking the event loop.
    """

    def __init__(self, sync_driver):
        self.driver = sync_driver

    async def invoke_async(self, context: str,
                          session_uuid: Optional[str] = None) -> Dict:
        """Async wrapper for driver.invoke()"""
        return await asyncio.to_thread(
            self.driver.invoke,
            context,
            session_uuid=session_uuid
        )

    async def invoke_stream_async(self, context: str,
                                  on_token: Callable[[str], None],
                                  session_uuid: Optional[str] = None) -> Dict:
        """Async wrapper for driver.invoke_stream()"""
        return await asyncio.to_thread(
            self.driver.invoke_stream,
            context,
            on_token,
            session_uuid=session_uuid
        )
```

---

## Verification Checklist

- [ ] `ClaudeDriverHybrid.invoke()` accepts `session_uuid`
- [ ] `ClaudeDriverHybrid.invoke_stream()` accepts `session_uuid`
- [ ] `GeminiDriverV7` writes to `gemini_context_{uuid}.md`
- [ ] `GeminiDriverV7` writes to `gemini_output_{uuid}.json`
- [ ] `ClaudeDriverHybrid` writes to `claude_context_{uuid}.md`
- [ ] Temporary files are deleted after execution
- [ ] `AgentInvoker.invoke_for_swarm()` accepts `session_uuid`
- [ ] `AgentInvoker.invoke_agent_direct()` accepts `session_uuid`
- [ ] `_wrap_invoke_agent()` passes `session_uuid`
- [ ] `ModeExecutor._invoke()` passes `session_uuid` from blackboard
- [ ] All tests pass

---

## Constraints

- **NO NEW DEPENDENCIES:** Use `uuid`, `asyncio`, `pathlib` (standard library)
- **Backwards Compatibility:** All `session_uuid` parameters have `= None` default
- **Cleanup Required:** Use `try...finally` for file cleanup
- **Anti-Hallucination:** Check `CODEBASE_SNAPSHOT.md` if unsure

---

## Files Modified

| File | Changes |
|------|---------|
| `core/drivers/gemini_driver_v7.py` | Unique filenames, cleanup |
| `core/drivers/claude_driver_hybrid.py` | Add session_uuid, unique filenames |
| `core/orchestration/agent_invoker.py` | Propagate session_uuid |
| `core/swarm/hybrid_swarm_engine.py` | Propagate session_uuid |
| `core/swarm/mode_executors.py` | Pass session_uuid from blackboard |
| `core/drivers/async_adapter.py` | NEW - Optional async wrapper |

---

*This prompt was verified against actual codebase by Claude Code (2025-12-09)*
