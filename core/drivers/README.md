# NEXUS Drivers Module

## Synopsis

The **drivers** module provides the abstraction layer for communicating with LLM providers (Gemini and Claude). It implements a unified `DriverProtocol` interface that enables both synchronous CLI-based drivers and async API-based drivers, with automatic session management and tool execution capabilities.

## Architecture

```
+-------------------------------------------------------------------------+
|                         DRIVER ARCHITECTURE                              |
+-------------------------------------------------------------------------+
|                                                                          |
|  +------------------------------------------------------------------+   |
|  |                      DriverProtocol (ABC)                         |   |
|  |  invoke(prompt, tools, session) -> DriverResponse                  |   |
|  +----------------------------+-------------------------------------+   |
|                               |                                          |
|         +---------------------+---------------------+                   |
|         |                     |                     |                   |
|         v                     v                     v                   |
|  +--------------+    +--------------+    +--------------+              |
|  | AsyncClaudeDriver|  |AsyncGeminiDriver|  | CLIAdapter   |              |
|  | (API Native)     |  |(API Native)     |  | (Legacy Wrap)|              |
|  +--------------+    +--------------+    +--------------+              |
|         |                     |                     |                   |
|         v                     v                     v                   |
|  +------------------------------------------------------------------+   |
|  |                    SessionManager                                 |   |
|  |  CLISessionManager | APISessionManager (future)                   |   |
|  +------------------------------------------------------------------+   |
|         |                     |                                          |
|         v                     v                                          |
|  +------------------------------------------------------------------+   |
|  |                    ToolExecutor                                   |   |
|  |  LocalToolExecutor | RemoteToolExecutor (future)                  |   |
|  +------------------------------------------------------------------+   |
|                                                                          |
+-------------------------------------------------------------------------+
```

## Component Map

| File | Purpose | Key Exports |
|------|---------|-------------|
| `protocol.py` | Core abstractions | `DriverProtocol`, `DriverResponse`, `ToolCall` |
| `async_claude_driver.py` | Claude async driver | `AsyncClaudeDriver`, `AsyncClaudeDriverConfig` |
| `async_gemini_driver.py` | Gemini async driver | `AsyncGeminiDriver`, `AsyncGeminiDriverConfig` |
| `claude_driver_hybrid.py` | Legacy sync Claude | `ClaudeDriverHybrid` |
| `gemini_driver_v7.py` | Legacy sync Gemini | `GeminiDriverV7` |
| `cli_adapter.py` | CLI wrapper adapters | `GeminiCLIAdapter`, `ClaudeCLIAdapter` |
| `session_abstraction.py` | Session management | `SessionManager`, `SessionRegistry` |
| `tool_executor.py` | Tool execution layer | `ToolExecutor`, `LocalToolExecutor` |
| `async_factory.py` | Driver factory | `AsyncDriverFactory`, `create_driver_factory` |
| `async_adapter.py` | Async utilities | Async adaptation helpers |

## Key Interfaces

### DriverProtocol
```python
class DriverProtocol(Protocol):
    """Unified interface for all LLM drivers."""

    async def invoke(
        self,
        prompt: str,
        tools: List[ToolSchema],
        session_uuid: str,
        **kwargs
    ) -> DriverResponse

    async def stream(
        self,
        prompt: str,
        tools: List[ToolSchema],
        session_uuid: str,
    ) -> AsyncIterator[StreamChunk]
```

### DriverResponse
```python
@dataclass
class DriverResponse:
    status: DriverResponseStatus  # SUCCESS, ERROR, TOOL_CALL
    content: str                  # Text response
    tool_calls: List[ToolCall]    # Requested tool executions
    usage: Optional[Dict]         # Token usage stats
    model: str                    # Model identifier
```

### AsyncDriverFactory
```python
# Create drivers via factory
factory = create_driver_factory(config)
claude = await factory.get_claude_driver()
gemini = await factory.get_gemini_driver()
```

## Protocol Differences

| Aspect | Gemini | Claude |
|--------|--------|--------|
| **Message Format** | Strict JSON (`LightMessageV7`) | Natural + XML tools |
| **Tool Response** | JSON in response | `<tool_use>` XML blocks |
| **Streaming** | Server-sent events | Server-sent events |
| **Session** | API-managed | CLI subprocess |

## V11 Abstraction Layer (F31-F33)

The V11 update introduced three major abstractions:

### F31: DriverProtocol
Unified interface allowing CLI and API drivers to be used interchangeably.

### F32: SessionProtocol
```python
class SessionProtocol(Protocol):
    """Abstract session management."""

    async def create(self, config: Dict) -> str
    async def send(self, session_id: str, message: str) -> Any
    async def close(self, session_id: str) -> None
```

### F33: ToolExecutorProtocol
```python
class ToolExecutorProtocol(Protocol):
    """Abstract tool execution."""

    async def execute(
        self,
        tool_name: str,
        params: Dict,
        context: ExecutionContext
    ) -> ToolResult
```

## Usage Examples

### Async Driver (Preferred)
```python
from core.drivers import create_async_claude_driver, AsyncClaudeDriverConfig

config = AsyncClaudeDriverConfig(
    model="claude-opus-4-6-20250116",
    max_tokens=8192,
    temperature=0.7
)
driver = create_async_claude_driver(config)

response = await driver.invoke(
    prompt="Analyze this code",
    tools=[read_tool, edit_tool],
    session_uuid="session-123"
)
```

### CLI Adapter (Legacy)
```python
from core.drivers import create_cli_adapter

adapter = create_cli_adapter("gemini", workspace_path)
response = await adapter.invoke(prompt, tools, session_uuid)
```

## Dependencies

### Internal
- `core.synapse` - Message types
- `core.execution` - Tool schemas
- `core.security` - Execution policies

### External
- `anthropic` - Claude API client
- `google.generativeai` - Gemini API client
- `asyncio` - Async runtime

## Version History

- **V7.0** - Initial hybrid drivers
- **V9.0** - Async-first architecture (`AsyncClaudeDriver`, `AsyncGeminiDriver`)
- **V11.0** - SYNCHROTRON abstraction layer (F31-F33)
- **V12.4** - Deadlock prevention, improved streaming
