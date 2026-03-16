# NEXUS Events Module

## Synopsis

The **events** module provides a Redis-based event bus for external UI observation of NEXUS activities. It enables real-time event streaming to CEREBRO API clients while coexisting with the internal EventBus (`core/async_primitives/event_bus.py`). Events are typed with `CerebroEventType` for structured handling.

## Architecture

```
+-------------------------------------------------------------------------+
|                        EVENT ARCHITECTURE                                |
+-------------------------------------------------------------------------+
|                                                                          |
|  +------------------+         +------------------+                      |
|  |   NEXUS Core     |         |   External UI    |                      |
|  |   Orchestrator   |         |   (CEREBRO Web)  |                      |
|  +--------+---------+         +--------^---------+                      |
|           |                            |                                 |
|           | publish()                  | subscribe()                     |
|           v                            |                                 |
|  +-----------------------------------------------------------------+    |
|  |                     RedisEventBus                                |    |
|  |              Redis Streams / Pub-Sub                             |    |
|  +-----------------------------------------------------------------+    |
|           |                            ^                                 |
|           |                            |                                 |
|  +--------v---------+         +--------+---------+                      |
|  |  TelemetryBridge |         |  Internal        |                      |
|  |  (metrics sync)  |         |  EventBus        |                      |
|  +------------------+         +------------------+                      |
|                                                                          |
+-------------------------------------------------------------------------+
```

## Component Map

| File | Purpose | Key Exports |
|------|---------|-------------|
| `types.py` | Event dataclasses | `CerebroEvent`, `CerebroEventType` |
| `redis_bus.py` | Redis pub/sub implementation | `RedisEventBus`, `get_redis_bus` |
| `telemetry_bridge.py` | Telemetry integration | `TelemetryBridge`, `get_telemetry_bridge` |

## Event Types

```python
class CerebroEventType(Enum):
    # User interaction
    INTERACTION_ASK = "interaction.ask"
    INTERACTION_CONFIRM = "interaction.confirm"
    INTERACTION_CHOOSE = "interaction.choose"

    # Orchestration
    ORCHESTRATION_STATE = "orchestration.state"
    ORCHESTRATION_TURN = "orchestration.turn"

    # Agents
    AGENT_INVOKE = "agent.invoke"
    AGENT_RESPONSE = "agent.response"

    # Tools
    TOOL_EXECUTE = "tool.execute"
    TOOL_RESULT = "tool.result"

    # HiveMind
    HIVE_PHASE = "hive.phase"
    HIVE_DEBATE = "hive.debate"

    # Telemetry
    TELEMETRY_METRIC = "telemetry.metric"
```

## Key Interfaces

### RedisEventBus
```python
class RedisEventBus:
    """Redis-backed event bus for UI observation."""

    async def publish(self, event: CerebroEvent) -> None
    async def subscribe(self, event_types: List[CerebroEventType]) -> AsyncIterator[CerebroEvent]
    def get_stream_name(self, tenant_id: str) -> str
```

### CerebroEvent
```python
@dataclass
class CerebroEvent:
    event_type: CerebroEventType
    tenant_id: str
    workspace_id: str
    payload: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.utcnow)
    event_id: str = field(default_factory=lambda: str(uuid4()))
```

## Usage

```python
from core.events import CerebroEvent, CerebroEventType, get_redis_bus

# Publish event
event = CerebroEvent(
    event_type=CerebroEventType.INTERACTION_ASK,
    tenant_id="tenant_123",
    workspace_id="default",
    payload={"prompt": "Continue?", "options": ["Yes", "No"]}
)
await get_redis_bus().publish(event)

# Subscribe to events
async for event in get_redis_bus().subscribe([CerebroEventType.AGENT_RESPONSE]):
    print(f"Agent response: {event.payload}")
```

## Dependencies

### Internal
- `core.async_primitives.event_bus` - Internal event bus (coexists)
- `core.telemetry` - Metrics integration

### External
- `redis` - Redis client
- `aioredis` - Async Redis client

## V12.4 COGNITIVE BOOST Additions

| File | Purpose | Key Exports |
|------|---------|-------------|
| `event_analytics.py` | Event stream analytics tracking event counts by type, processing latency per event type, throughput metrics, and event flow patterns (source/type distribution) | `get_event_analytics`, `EventAnalytics` |

## Version History

- **V10.0** - CEREBRO: Redis-based event bus for external UI
- **V10.5** - SYNAPSE: TelemetryBridge for metrics sync
- **V12.4** - Multi-tenant event streams, event analytics
