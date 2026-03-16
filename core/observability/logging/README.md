# NEXUS Logging Module

## Synopsis

The **logging** module provides structured logging for NEXUS with JSONL event logging, rotating log files, and a lightweight driver logger for LLM interactions. It supports multiple log levels and event types for comprehensive observability.

## Architecture

```
+-------------------------------------------------------------------------+
|                      LOGGING ARCHITECTURE                                |
+-------------------------------------------------------------------------+
|                                                                          |
|  +------------------------------------------------------------------+   |
|  |                       NexusLogger                                 |   |
|  |              Main structured logger (JSONL)                       |   |
|  +----------------------------+-------------------------------------+   |
|                               |                                          |
|         +---------------------+---------------------+                   |
|         |                     |                     |                   |
|         v                     v                     v                   |
|  +--------------+    +--------------+    +------------------+          |
|  | events_*.jsonl|   | errors_*.log |    | driver_*.log     |          |
|  | (all events)  |   | (errors only)|    | (LLM calls)      |          |
|  +--------------+    +--------------+    +------------------+          |
|                                                                          |
|  +------------------------------------------------------------------+   |
|  |                      DriverLogger (V8.4.5)                        |   |
|  |            Lightweight logger for driver invocations              |   |
|  +------------------------------------------------------------------+   |
|                                                                          |
+-------------------------------------------------------------------------+
```

## Component Map

| File | Purpose | Key Exports |
|------|---------|-------------|
| `logger_v7.py` | Main structured logger | `NexusLogger`, `LogLevel`, `EventType` |
| `driver_logger.py` | LLM driver logging | `DriverLogger`, `get_driver_logger` |

## Log Levels

```python
class LogLevel(Enum):
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40
    CRITICAL = 50
```

## Event Types

```python
class EventType(Enum):
    # Orchestration
    TURN_START = "turn_start"
    TURN_END = "turn_end"
    STATE_CHANGE = "state_change"

    # Agents
    AGENT_INVOKE = "agent_invoke"
    AGENT_RESPONSE = "agent_response"
    AGENT_ERROR = "agent_error"

    # Tools
    TOOL_EXECUTE = "tool_execute"
    TOOL_RESULT = "tool_result"
    TOOL_ERROR = "tool_error"

    # HiveMind
    HIVE_PHASE = "hive_phase"
    HIVE_DEBATE = "hive_debate"

    # Swarm
    SWARM_MODE = "swarm_mode"
    SWARM_NEGOTIATE = "swarm_negotiate"

    # System
    SYSTEM_START = "system_start"
    SYSTEM_STOP = "system_stop"
    ERROR = "error"
```

## Key Interfaces

### NexusLogger
```python
class NexusLogger:
    """Main structured logger."""

    def __init__(self, workspace_path: Path, log_level: LogLevel = LogLevel.INFO)
    def log(self, event_type: EventType, data: Dict, level: LogLevel = LogLevel.INFO)
    def debug(self, message: str, **kwargs)
    def info(self, message: str, **kwargs)
    def warning(self, message: str, **kwargs)
    def error(self, message: str, **kwargs)
```

### DriverLogger (V8.4.5)
```python
class DriverLogger:
    """Lightweight logger for LLM driver interactions."""

    def log_request(self, agent: str, prompt: str, tokens: int)
    def log_response(self, agent: str, response: str, latency: float)
    def log_error(self, agent: str, error: str)
```

## Log File Structure

```
workspace/logs/
+-- events_20251217.jsonl   # All events (JSONL format)
+-- errors_20251217.log     # Errors only (text)
+-- driver_20251217.log     # LLM driver calls
+-- ...
```

## JSONL Event Format

```json
{
  "timestamp": "2025-12-17T10:30:00.123Z",
  "event_type": "agent_invoke",
  "level": "INFO",
  "data": {
    "agent": "gemini",
    "prompt_tokens": 1500,
    "model": "gemini-3-pro-preview"
  }
}
```

## Usage

```python
from core.logging import init_logger, get_logger, EventType

# Initialize logger
init_logger(workspace_path=Path("workspace"))

# Get logger instance
logger = get_logger()

# Log events
logger.log(EventType.TURN_START, {"user_input": "Fix the bug"})
logger.info("Processing request", agent="gemini")
logger.error("Tool execution failed", tool="bash", error=str(e))

# Driver logging
from core.logging import get_driver_logger
driver_logger = get_driver_logger()
driver_logger.log_request("claude", prompt, token_count)
```

## Log Cleanup

```python
from core.logging import cleanup_old_logs

# Remove logs older than 7 days
cleanup_old_logs(workspace_path, max_age_days=7)
```

## Dependencies

### External
- Standard library (logging, json, pathlib, datetime)

## Version History

- **V7.0** - NexusLogger with JSONL events
- **V8.4.5** - DriverLogger for LLM calls
- **V12.4** - Enhanced event types, log rotation
