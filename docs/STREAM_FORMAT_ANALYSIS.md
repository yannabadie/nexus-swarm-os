# Stream-JSON Format Analysis - NEXUS V7.7

**Phase 15a Investigation - December 2025**
**Status**: COMPLETE

---

## Executive Summary

Both Gemini CLI and Claude CLI support native JSON streaming via `--output-format stream-json`. This document provides the technical specification for implementing response streaming in NEXUS drivers.

---

## GEMINI CLI Stream-JSON Format

### Command Flags
```bash
gemini -o stream-json "prompt"
# With YOLO mode for auto-approval:
gemini -o stream-json -y "prompt"
```

### Message Types (JSONL)

```jsonl
# 1. INIT - Session initialization
{"type":"init", "timestamp":"2025-12-05T09:46:42.998Z", "session_id":"uuid", "model":"auto"}

# 2. USER MESSAGE - User input echo
{"type":"message", "timestamp":"...", "role":"user", "content":"Prompt..."}

# 3. TOOL_USE - Tool invocation (before execution)
{"type":"tool_use", "timestamp":"...", "tool_name":"read_file", "tool_id":"read_file-xxx", "parameters":{"file_path":"...", "limit":1}}

# 4. TOOL_RESULT - Tool execution result
{"type":"tool_result", "timestamp":"...", "tool_id":"read_file-xxx", "status":"success", "output":"Read lines 1-1..."}

# 5. ASSISTANT CHUNK - Streaming text response
{"type":"message", "timestamp":"...", "role":"assistant", "content":"chunk of text", "delta":true}

# 6. RESULT - Final statistics
{"type":"result", "timestamp":"...", "status":"success", "stats":{"total_tokens":34784, "input_tokens":34466, "output_tokens":88, "duration_ms":4008, "tool_calls":1}}
```

### Text Extraction Logic

```python
def extract_gemini_text(data: dict) -> Optional[str]:
    """Extract streaming text from Gemini stream-json."""
    if data.get("type") == "message" and data.get("role") == "assistant" and data.get("delta"):
        return data.get("content", "")
    return None
```

### Key Observations

| Field | Description |
|-------|-------------|
| `type` | Message type: `init`, `message`, `tool_use`, `tool_result`, `result` |
| `delta` | Boolean flag indicating streaming chunk (only on assistant messages) |
| `role` | `user` or `assistant` |
| `stats` | Final statistics including token counts and duration |

---

## CLAUDE CLI Stream-JSON Format

### Command Flags
```bash
claude -p --verbose --output-format stream-json --include-partial-messages "prompt"
```

**Required flags:**
- `-p` / `--print`: Non-interactive mode
- `--verbose`: Required for stream-json
- `--output-format stream-json`: Enable streaming
- `--include-partial-messages`: Include delta chunks (CRITICAL)

### Message Types (JSONL)

```jsonl
# 1. INIT - Rich initialization with metadata
{"type":"system", "subtype":"init", "session_id":"uuid", "cwd":"C:\\...", "tools":["Task","Bash","Read",...], "model":"claude-opus-4-5-20251101", "permissionMode":"default", "claude_code_version":"2.0.59"}

# 2. MESSAGE_START - Generation start
{"type":"stream_event", "event":{"type":"message_start", "message":{"model":"...", "id":"msg_xxx", "type":"message", "role":"assistant", "content":[], "usage":{...}}}}

# 3. CONTENT_BLOCK_START - Block start (text or tool_use)
# For text:
{"type":"stream_event", "event":{"type":"content_block_start", "index":0, "content_block":{"type":"text", "text":""}}}
# For tool_use:
{"type":"stream_event", "event":{"type":"content_block_start", "index":0, "content_block":{"type":"tool_use", "id":"toolu_xxx", "name":"Read", "input":{}}}}

# 4. CONTENT_BLOCK_DELTA - Streaming chunks
# Text delta:
{"type":"stream_event", "event":{"type":"content_block_delta", "index":0, "delta":{"type":"text_delta", "text":"chunk of text"}}}
# Tool input JSON delta:
{"type":"stream_event", "event":{"type":"content_block_delta", "index":0, "delta":{"type":"input_json_delta", "partial_json":"{\"file_"}}}

# 5. ASSISTANT - Complete message (after all chunks)
{"type":"assistant", "message":{"model":"...", "content":[{"type":"text", "text":"complete response"}], "stop_reason":"end_turn", "usage":{...}}}

# 6. USER - Tool result (if tool_use occurred)
{"type":"user", "message":{"role":"user", "content":[{"tool_use_id":"toolu_xxx", "type":"tool_result", "content":"..."}]}, "tool_use_result":{"type":"text", "file":{...}}}

# 7. CONTENT_BLOCK_STOP
{"type":"stream_event", "event":{"type":"content_block_stop", "index":0}}

# 8. MESSAGE_DELTA - Stop reason
{"type":"stream_event", "event":{"type":"message_delta", "delta":{"stop_reason":"end_turn"}, "usage":{...}}}

# 9. MESSAGE_STOP
{"type":"stream_event", "event":{"type":"message_stop"}}

# 10. RESULT - Final statistics with costs
{"type":"result", "subtype":"success", "is_error":false, "duration_ms":12876, "num_turns":2, "result":"...", "total_cost_usd":0.0823685, "usage":{...}}
```

### Text Extraction Logic

```python
def extract_claude_text(data: dict) -> Optional[str]:
    """Extract streaming text from Claude stream-json."""
    if data.get("type") == "stream_event":
        event = data.get("event", {})
        if event.get("type") == "content_block_delta":
            delta = event.get("delta", {})
            if delta.get("type") == "text_delta":
                return delta.get("text", "")
    return None
```

### Key Observations

| Field | Description |
|-------|-------------|
| `type` | Top-level: `system`, `stream_event`, `assistant`, `user`, `result` |
| `event.type` | Event type: `message_start`, `content_block_start`, `content_block_delta`, etc. |
| `delta.type` | Delta type: `text_delta` (text) or `input_json_delta` (tool args) |
| `total_cost_usd` | Actual API cost in USD (useful for budget tracking) |
| `stop_reason` | `end_turn` (normal) or `tool_use` (needs tool execution) |

---

## Comparison Table

| Aspect | Gemini CLI | Claude CLI |
|--------|------------|------------|
| **Required Flags** | `-o stream-json` | `--output-format stream-json --verbose --include-partial-messages` |
| **Text Chunk Format** | `{"type":"message", "delta":true, "content":"..."}` | `{"type":"stream_event", "event":{"delta":{"type":"text_delta", "text":"..."}}}` |
| **Tool Use Streaming** | No (complete result only) | Yes (`input_json_delta`) |
| **Cost Tracking** | No | Yes (`total_cost_usd`) |
| **Session ID** | Yes | Yes |
| **Parsing Complexity** | Simple (1 level) | Medium (3 levels nested) |
| **Token Stats** | In `result.stats` | In `result.usage` |

---

## Unified Parser Implementation

```python
"""
Unified stream parser for NEXUS V7.7
Handles both Gemini and Claude stream-json formats.
"""

import json
from typing import Optional, Tuple, Dict, Any


def parse_stream_chunk(line: str, source: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """
    Parse a single line of stream-json output.

    Args:
        line: JSON line from CLI stdout
        source: "gemini" or "claude"

    Returns:
        Tuple of (text_chunk, metadata)
        - text_chunk: Extracted text if this is a text delta, else None
        - metadata: Full parsed JSON for other processing
    """
    if not line.strip():
        return None, None

    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None, None

    text_chunk = None

    if source == "gemini":
        # Gemini: {"type":"message", "role":"assistant", "content":"...", "delta":true}
        if (data.get("type") == "message" and
            data.get("role") == "assistant" and
            data.get("delta") is True):
            text_chunk = data.get("content", "")

    elif source == "claude":
        # Claude: {"type":"stream_event", "event":{"type":"content_block_delta", "delta":{"type":"text_delta", "text":"..."}}}
        if data.get("type") == "stream_event":
            event = data.get("event", {})
            if event.get("type") == "content_block_delta":
                delta = event.get("delta", {})
                if delta.get("type") == "text_delta":
                    text_chunk = delta.get("text", "")

    return text_chunk, data


def is_result_message(data: Dict[str, Any], source: str) -> bool:
    """Check if this message is the final result."""
    if source == "gemini":
        return data.get("type") == "result"
    elif source == "claude":
        return data.get("type") == "result"
    return False


def extract_final_result(data: Dict[str, Any], source: str) -> Optional[str]:
    """Extract final result text from result message."""
    if source == "gemini":
        # Gemini doesn't include full text in result, need to accumulate
        return None
    elif source == "claude":
        return data.get("result")
    return None


def extract_stats(data: Dict[str, Any], source: str) -> Dict[str, Any]:
    """Extract statistics from result message."""
    if source == "gemini":
        return data.get("stats", {})
    elif source == "claude":
        return {
            "duration_ms": data.get("duration_ms"),
            "num_turns": data.get("num_turns"),
            "total_cost_usd": data.get("total_cost_usd"),
            "usage": data.get("usage", {})
        }
    return {}
```

---

## Implementation Notes for Phase 15

### V1 Scope (Recommended)
1. Stream **text only** (`text_delta`)
2. Ignore `input_json_delta` (tool args)
3. Accumulate full response for final NEXUS JSON parsing
4. Display streaming text in REPL with `print(..., end="", flush=True)`

### V2 Scope (Future)
1. Stream tool_use progress
2. Real-time tool execution display
3. Partial JSON reconstruction

### Driver Integration Points

**Gemini Driver:**
```python
def invoke_stream(self, context: str) -> Generator[str, None, Dict]:
    """Stream invoke with text chunks."""
    proc = subprocess.Popen(
        ["gemini", "-o", "stream-json", "-y", context],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )

    accumulated_text = []
    final_result = None

    for line in proc.stdout:
        text, data = parse_stream_chunk(line, "gemini")
        if text:
            accumulated_text.append(text)
            yield text  # Stream to UI
        if is_result_message(data, "gemini"):
            final_result = data

    # Return final parsed response
    return self._build_response(accumulated_text, final_result)
```

**Claude Driver:**
```python
def invoke_stream(self, context: str) -> Generator[str, None, Dict]:
    """Stream invoke with text chunks."""
    proc = subprocess.Popen(
        ["claude", "-p", "--verbose", "--output-format", "stream-json",
         "--include-partial-messages", context],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )

    # Similar logic...
```

---

## Test Data

### Gemini Sample (Simple Response)
```jsonl
{"type":"init","timestamp":"2025-12-05T09:46:42.998Z","session_id":"8dee5df5-fcc5-4dfe-b8fd-9bf4777d9283","model":"auto"}
{"type":"message","timestamp":"2025-12-05T09:46:42.999Z","role":"user","content":"Réponds juste: Bonjour"}
{"type":"message","timestamp":"2025-12-05T09:46:45.485Z","role":"assistant","content":"Bonjour","delta":true}
{"type":"result","timestamp":"2025-12-05T09:46:45.497Z","status":"success","stats":{"total_tokens":18275,"input_tokens":18095,"output_tokens":45,"duration_ms":2498,"tool_calls":0}}
```

### Claude Sample (With Streaming)
```jsonl
{"type":"system","subtype":"init","session_id":"6c996e64-3353-4527-87f6-fec5e5a0a3f1","model":"claude-opus-4-5-20251101"}
{"type":"stream_event","event":{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Python"}}}
{"type":"stream_event","event":{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":" est un langage"}}}
{"type":"result","subtype":"success","result":"Python est un langage...","total_cost_usd":0.06}
```

---

## Implementation (V7.7)

Phase 15 implementation complete. Files:

| File | Purpose |
|------|---------|
| `core/utils/stream_parser.py` | Unified JSONL parser |
| `core/drivers/gemini_driver_v7.py` | `invoke_stream()` method |
| `core/drivers/claude_driver_hybrid.py` | `invoke_stream()` method |
| `core/config.py` | `streaming_enabled` toggle |
| `core/orchestration_v7.py` | `on_token` callback |
| `core/interface/repl.py` | `_stream_token()` display |
| `tests/test_stream_parser.py` | 23 tests for parser |

**Enable/Disable**: Set `STREAMING_ENABLED=False` in `.env` to disable.

## References

- Gemini CLI: `gemini --help`
- Claude CLI: `claude --help`
- Investigation Date: 2025-12-05
- Implementation Date: 2025-12-05
- NEXUS Version: V7.7.0
