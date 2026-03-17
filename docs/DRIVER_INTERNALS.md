# NEXUS Driver Implementation Internals

> **WARNING DOCUMENT STATUS: OUTDATED (V8.0 -> V12.4)**
>
> This document was written for V8.0 sync CLI drivers (`GeminiDriverV7`, `ClaudeDriverHybrid`).
> As of V12.4, all drivers are **async** and SDK-based. The sync/blocking description is
> no longer accurate. See `core/drivers/` for current implementation.
>
> **Current driver hierarchy (V12.4)**:
> - `BaseAsyncDriver` (protocol) -- `core/drivers/protocol.py`
> - `AsyncGeminiDriver` -- `core/drivers/async_gemini_driver.py`
> - `AsyncClaudeDriver` -- `core/drivers/async_claude_driver.py`
> - `AnthropicSDKDriver` -- `core/drivers/anthropic_sdk_driver.py`
> - `GoogleGenAISDKDriver` -- `core/drivers/google_genai_sdk_driver.py`
> - `AsyncDriverFactory` -- `core/drivers/async_factory.py`
>
> Historical reference below preserved for context.

---

**Original**: V8.0 Driver Internals
**Last Updated (original)**: 2025-12-08

---

## 1. GeminiDriverV7

**File**: `core/drivers/gemini_driver_v7.py`
**Lines**: 624 total

### Class Definition (line 76)

```python
class GeminiDriverV7:
    """Gemini CLI wrapper with persistent session support"""

    def __init__(self, config, workspace_path: Path, model: str = None):
        self.cli_path = "gemini"
        self.model = model or config.gemini_default_model
        self.workspace_path = workspace_path
        self.io_buffer = workspace_path / "_IO_BUFFER"
        self.timeout = 120
```

### invoke() Method (line 122)

```python
def invoke(
    self,
    context: str,
    session_uuid: Optional[str] = None
) -> Dict:
    """
    SYNC method - blocks until completion.
    Returns: {"sender": "Gemini", "content": str, "action_type": str, ...}
    """
    return self._invoke_subprocess(context, session_uuid=session_uuid)
```

### _invoke_subprocess() Implementation (line 178)

```python
def _invoke_subprocess(self, context: str, session_uuid: Optional[str] = None) -> Dict:
    # 1. Write context to file
    context_file = self.io_buffer / "gemini_context_in.md"
    context_file.write_text(context, encoding="utf-8")

    # 2. Build command
    command = f'gemini -m {self.model} -p @"{context_file}" -o json'

    # 3. Execute with Popen (NOT subprocess.run!)
    proc = subprocess.Popen(
        command,
        cwd=str(self.workspace_path),
        shell=True,  # Windows
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding='utf-8'
    )

    # 4. Threading for stdout/stderr reading
    stdout_thread = threading.Thread(target=read_stream, args=(proc.stdout,))
    stderr_thread = threading.Thread(target=read_stream, args=(proc.stderr,))
    stdout_thread.start()
    stderr_thread.start()

    # 5. Polling loop (BLOCKS until completion)
    while proc.poll() is None:
        elapsed = time.time() - start_time
        if elapsed > self.timeout:
            proc.kill()
            raise TimeoutError(f"Timeout after {self.timeout}s")
        time.sleep(0.1)  # Poll every 100ms

    # 6. Parse output
    return self._parse_output(stdout_data)
```

### Key Points

- Uses `subprocess.Popen`, NOT `subprocess.run`
- Threading for reading stdout/stderr non-blocking
- **BUT** the method itself BLOCKS the caller via polling loop
- Returns Dict with parsed JSON

---

## 2. ClaudeDriverHybrid

**File**: `core/drivers/claude_driver_hybrid.py`
**Lines**: 483 total

### Class Definition (line 71)

```python
class ClaudeDriverHybrid:
    """Claude API wrapper with hybrid XML/natural language"""

    def __init__(self, config, workspace_path: Path, model: str = None, agent_id: str = None):
        self.cli_path = "claude"
        self.workspace_path = workspace_path
        self.io_buffer = workspace_path / "_IO_BUFFER"
        self.timeout = 120
        self.model = model or config.claude_sonnet_model
```

### invoke() Method (line 97)

```python
def invoke(self, context: str) -> Dict:
    """
    SYNC method - blocks until completion.
    Returns: {"sender": "Claude", "content": str, "action_type": str, ...}
    """
    # 1. Write context to file
    context_file = self.io_buffer / "claude_context_in.md"
    context_file.write_text(context, encoding="utf-8")

    # 2. Build command
    command = f'claude -p @"{context_file}" --dangerously-skip-permissions'

    # 3. Execute with Popen
    proc = subprocess.Popen(
        command,
        cwd=str(self.workspace_path),
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding='utf-8'
    )

    # 4. Same threading + polling pattern as Gemini
    # ... (BLOCKS until completion)

    return self._parse_output(stdout_data)
```

### invoke_with_retry() Method (line 444)

```python
def invoke_with_retry(self, context: str, max_retries: int = 3) -> Dict:
    """SYNC with exponential backoff on failure"""
    for attempt in range(max_retries):
        try:
            return self.invoke(context)
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # SYNC sleep!
            else:
                raise
```

---

## 3. Async/Sync Problem

### The Issue

```
TrueHiveMind.process_task()      # ASYNC (line 235)
    +-- calls GeminiDriverV7.invoke()  # SYNC (blocks event loop!)
    +-- calls ClaudeDriverHybrid.invoke()  # SYNC (blocks event loop!)
```

### Why PARALLEL Mode is Actually Sequential

```python
# In PARALLEL mode executor, this happens:
async def _execute_parallel(self, context):
    # These look parallel but actually run SEQUENTIALLY
    # because invoke() is sync and blocks!
    gemini_result = self.gemini.invoke(context)  # Blocks 10-30s
    claude_result = self.claude.invoke(context)  # Then blocks 10-30s
    # Total: 20-60s instead of max(10-30s, 10-30s)
```

### Correct PARALLEL Would Require

```python
# Option A: run_in_executor (less invasive)
async def invoke_async(self, context: str) -> Dict:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, self.invoke, context)

# Option B: asyncio.create_subprocess_exec (more efficient)
async def invoke_async(self, context: str) -> Dict:
    proc = await asyncio.create_subprocess_exec(
        self.cli_path, "-p", f"@{context_file}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    return self._parse_output(stdout.decode())

# Then in executor:
async def _execute_parallel(self, context):
    results = await asyncio.gather(
        self.gemini.invoke_async(context),
        self.claude.invoke_async(context)
    )  # TRUE parallel: max(t1, t2) instead of t1 + t2
```

---

## 4. Streaming Implementation

### GeminiDriverV7.invoke_stream() (line 149)

```python
def invoke_stream(
    self,
    context: str,
    on_token: Callable[[str], None],  # Callback for each chunk
    session_uuid: Optional[str] = None
) -> Dict:
    """SYNC with streaming callback"""
    # Same Popen pattern, but:
    # - Reads stdout line by line
    # - Calls on_token(line) for each line
    # - Still BLOCKS until completion
```

### ClaudeDriverHybrid.invoke_stream() (line 231)

```python
def invoke_stream(
    self,
    context: str,
    on_token: Callable[[str], None]
) -> Dict:
    """SYNC with streaming callback"""
    # Same pattern as Gemini
```

---

## 5. Process Management

### Active Process Tracking

```python
# Global lists for cleanup on exit
_active_processes = []       # Gemini processes
_active_claude_processes = []  # Claude processes

# In invoke():
proc = subprocess.Popen(...)
_active_processes.append(proc)

# Cleanup registered via atexit
import atexit
atexit.register(cleanup_processes)
```

### Timeout Handling

```python
while proc.poll() is None:
    elapsed = time.time() - start_time
    if elapsed > self.timeout:
        proc.kill()       # SIGKILL
        proc.wait()       # Wait for termination
        raise TimeoutError(...)
    time.sleep(0.1)
```

---

## 6. Return Format

### Gemini Response

```python
{
    "sender": "Gemini",
    "content": "Natural language response...",
    "action_type": "TALK" | "TOOL_USE",
    "tool_use": {...} | None,
    "json_extracted": {...} | None,
    "raw_output": "Original CLI output"
}
```

### Claude Response

```python
{
    "sender": "Claude",
    "content": "Natural language response...",
    "action_type": "TALK" | "TOOL_USE",
    "tool_use": {...} | None,  # Extracted from <tool_use> XML
    "artifacts": [...] | None
}
```

---

## 7. Configuration

### Timeouts

| Driver | Default | Config Key |
|--------|---------|------------|
| Gemini | 120s | `config.timeout` |
| Claude | 120s | `config.timeout` |

### Models

| Driver | Default | Config Key |
|--------|---------|------------|
| Gemini | gemini-3-pro-preview | `config.gemini_default_model` |
| Claude (Opus) | claude-opus-4-5-20251101 | `config.claude_opus_model` |
| Claude (Sonnet) | claude-sonnet-4-5-20250929 | `config.claude_sonnet_model` |

---

## 8. Summary Table

| Aspect | GeminiDriverV7 | ClaudeDriverHybrid |
|--------|----------------|-------------------|
| File | gemini_driver_v7.py | claude_driver_hybrid.py |
| Lines | 624 | 483 |
| invoke() | SYNC (line 122) | SYNC (line 97) |
| Subprocess | Popen + threading | Popen + threading |
| Protocol | JSON output (-o json) | Natural + XML |
| Streaming | invoke_stream() | invoke_stream() |
| Async | **NOT IMPLEMENTED** | **NOT IMPLEMENTED** |

---

## 9. Planned Improvements (V8.1.6)

See ROADMAP.md V8.1.6 for async driver wrapper implementation plan.

---

*This document describes the actual implementation. Do not assume features that are not documented here.*
