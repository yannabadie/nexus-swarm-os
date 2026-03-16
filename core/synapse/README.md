# NEXUS Synapse Module

## Synopsis

The **synapse** module defines the communication protocol between agents in NEXUS. It provides Pydantic-based message schemas with intelligent defaults, auto-repair validators, and both lightweight (TALK) and heavyweight (TOOL_USE) message types. The protocol ensures robust agent communication even when responses contain errors or typos.

## Architecture

```
+-------------------------------------------------------------------------+
|                      SYNAPSE PROTOCOL V7                                 |
+-------------------------------------------------------------------------+
|                                                                          |
|  +------------------------------------------------------------------+   |
|  |                       Message Types                               |   |
|  +------------------------------------------------------------------+   |
|  |                                                                   |   |
|  |  +-----------------+           +---------------------+           |   |
|  |  | LightMessageV7  |           |   HeavyMessageV7    |           |   |
|  |  | --------------- |           | ------------------- |           |   |
|  |  | TALK            |           | TOOL_USE            |           |   |
|  |  | DELEGATE        |           | FINISH              |           |   |
|  |  | CONTINUE        |           | ERROR               |           |   |
|  |  +-----------------+           +---------------------+           |   |
|  |                                                                   |   |
|  +------------------------------------------------------------------+   |
|                                                                          |
|  +------------------------------------------------------------------+   |
|  |                     Auto-Repair System                            |   |
|  +------------------------------------------------------------------+   |
|  |  - Typo correction: "DELEGATION" -> "DELEGATE"                     |   |
|  |  - Case normalization: "talk" -> "TALK"                            |   |
|  |  - Missing field defaults: next_agent -> alternate agent           |   |
|  |  - Sender capitalization: "gemini" -> "Gemini"                     |   |
|  +------------------------------------------------------------------+   |
|                                                                          |
+-------------------------------------------------------------------------+
```

## Component Map

| File | Purpose | Key Exports |
|------|---------|-------------|
| `protocol_v7.py` | Message schemas | `LightMessageV7`, `HeavyMessageV7`, `ThoughtChain` |
| `memory_v7.py` | Message history management | `MessageMemory`, `ConversationBuffer` |

## Message Types

### LightMessageV7
For communication actions (TALK, DELEGATE, CONTINUE):

```python
class LightMessageV7(BaseModel):
    sender: str                          # "Gemini" or "Claude"
    action_type: str                     # TALK, DELEGATE, CONTINUE
    content: Optional[str] = ""          # Message content
    thought_process: List[ThoughtChain]  # Reasoning steps
    reflection: Optional[str] = None     # Self-reflection
    next_agent: Optional[str] = None     # Target agent (auto-alternates)
    status: Optional[str] = "CONTINUE"   # CONTINUE, FINISHED, ERROR
    action_summary: Optional[str] = None # Summary of action taken
    instructions_for_next: Optional[str] # Instructions for next agent
    strategic_plan_update: List[Dict]    # Plan modifications
```

### HeavyMessageV7
For action-oriented messages (TOOL_USE, FINISH, ERROR):

```python
class HeavyMessageV7(BaseModel):
    sender: str
    action_type: str                     # TOOL_USE, FINISH, ERROR
    content: Optional[str] = ""
    thought_process: List[ThoughtChain]
    tool_name: Optional[str] = None      # Tool to execute
    tool_params: Optional[Dict] = None   # Tool parameters
    tool_result: Optional[str] = None    # Execution result
    error_message: Optional[str] = None  # Error details
    final_response: Optional[str] = None # Task completion response
```

### ThoughtChain
Represents a reasoning step:

```python
class ThoughtChain(BaseModel):
    step: int          # Step number
    reasoning: str     # Reasoning content
```

## Action Types

| Action | Message Type | Description |
|--------|--------------|-------------|
| `TALK` | Light | Agent-to-agent communication |
| `DELEGATE` | Light | Hand off to specific agent |
| `CONTINUE` | Light | Continue current processing |
| `TOOL_USE` | Heavy | Request tool execution |
| `FINISH` | Heavy | Task completion |
| `ERROR` | Heavy | Error occurred |

## Auto-Repair Validators

The protocol includes Pydantic validators that auto-correct common errors:

```python
# Typo corrections
repairs = {
    "DELEGATION": "DELEGATE",
    "DELEGATING": "DELEGATE",
    "TALKING": "TALK",
    "TOOL": "TOOL_USE",
    "USING_TOOL": "TOOL_USE",
    "FINISHED": "FINISH",
}

# Auto-alternate next_agent when missing
if next_agent is None:
    return "Claude" if sender == "Gemini" else "Gemini"
```

## Usage Example

```python
from core.synapse.protocol_v7 import LightMessageV7, HeavyMessageV7

# Parsing agent response (auto-repairs typos)
msg = LightMessageV7.model_validate({
    "sender": "gemini",          # -> "Gemini"
    "action_type": "delegation", # -> "DELEGATE"
    "content": "Please analyze the code",
    # next_agent missing -> auto-set to "Claude"
})

# Tool use message
tool_msg = HeavyMessageV7(
    sender="Claude",
    action_type="TOOL_USE",
    tool_name="read",
    tool_params={"file_path": "src/main.py"}
)
```

## Dependencies

### External
- `pydantic` - Schema validation and auto-repair

## V12.4 COGNITIVE BOOST Additions

| File | Purpose | Key Exports |
|------|---------|-------------|
| `message_protocol.py` | Lightweight dataclass-based inter-agent messaging with typed categories (REQUEST, RESPONSE, BROADCAST, NOTIFY), routing headers, and conversation threading | `Message`, `MessageType`, `create_message` |
| `message_deduplicator.py` | Idempotent message processing via SHA-256 content fingerprinting, TTL-based expiration, and correlation-ID tracing for end-to-end observability | `get_deduplicator`, `MessageDeduplicator` |
| `message_router.py` | Intelligent message routing with per-agent queues, delivery tracking, dead letter handling, and routing statistics | `get_message_router`, `MessageRouter` |
| `message_reliability_tracker.py` | Inter-agent message delivery monitoring with per-channel success rates, latency patterns, dead letter analysis, and agent responsiveness metrics | `get_message_tracker`, `MessageReliabilityTracker` |

## Version History

- **V7.0** - Protocol V7 with Pydantic BaseModel schemas
- **V7.5** - Auto-repair validators for typos
- **V8.0** - ThoughtChain for explicit reasoning
- **V12.4** - Enhanced defaults, strategic_plan_update, message protocol, deduplication, routing, and reliability tracking
