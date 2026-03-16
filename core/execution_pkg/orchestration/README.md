# NEXUS Orchestration Module

## Synopsis

The **orchestration** module contains the extracted components from the main `OrchestratorV7`. It provides modular building blocks for context construction, agent invocation, mutation detection, state machine handling, and HiveMind/Swarm synchronization. These components are used via composition by the main orchestrator.

## Architecture

```
+-------------------------------------------------------------------------+
|                    ORCHESTRATION COMPONENTS                              |
+-------------------------------------------------------------------------+
|                                                                          |
|  +------------------------------------------------------------------+   |
|  |                     OrchestratorV7 (parent)                       |   |
|  |                  Uses components via COMPOSITION                  |   |
|  +----------------------------+-------------------------------------+   |
|                               |                                          |
|    +--------------------------+--------------------------+              |
|    |              |           |           |              |              |
|    v              v           v           v              v              |
| +--------+  +---------+  +---------+  +---------+  +----------+        |
| |Context |  | Agent   |  |Mutation |  |  FSM    |  |  Swarm   |        |
| |Builder |  | Invoker |  |Detector |  |Handlers |  | Bridge   |        |
| +--------+  +---------+  +---------+  +---------+  +----------+        |
|      |            |            |            |            |              |
|      +------------+------------+------------+------------+              |
|                               |                                          |
|                               v                                          |
|              +--------------------------------------+                   |
|              |        OrchestratorSyncBridge        |                   |
|              |   HiveMind ↔ Swarm State Sync (V9.4)  |                   |
|              +--------------------------------------+                   |
|                                                                          |
+-------------------------------------------------------------------------+
```

## Component Map

| File | Purpose | Key Exports |
|------|---------|-------------|
| `context_builder.py` | Agent context construction | `ContextBuilder` |
| `agent_invoker.py` | Agent invocation handling | `AgentInvoker` |
| `detectors.py` | Mutation/response detection | `MutationDetector`, `ResponseDetector` |
| `fsm_handlers.py` | State machine event handlers | `FSMHandlers` |
| `swarm_bridge.py` | Swarm engine integration | `SwarmBridge` |
| `sync_bridge.py` | HiveMind/Swarm synchronization | `OrchestratorSyncBridge`, `SyncEvent` |

## Key Interfaces

### ContextBuilder
```python
class ContextBuilder:
    """Constructs execution context for agent invocations."""

    def build(
        self,
        task: str,
        history: List[Message],
        blackboard: Blackboard
    ) -> ExecutionContext

    def build_for_agent(
        self,
        agent_id: str,
        context: ExecutionContext
    ) -> AgentContext
```

### AgentInvoker
```python
class AgentInvoker:
    """Handles agent invocation with retries and error handling."""

    async def invoke(
        self,
        agent_id: str,
        prompt: str,
        context: AgentContext
    ) -> AgentResponse

    async def invoke_parallel(
        self,
        agents: List[str],
        prompts: Dict[str, str],
        context: AgentContext
    ) -> Dict[str, AgentResponse]
```

### MutationDetector
```python
class MutationDetector:
    """Detects evolution mutation proposals in agent responses."""

    def detect(self, response: str) -> Optional[MutationProposal]
    def is_evolution_response(self, response: str) -> bool
```

### FSMHandlers
```python
class FSMHandlers:
    """State-specific event handlers for FSM transitions."""

    async def handle_brainstorming(self, event: FSMEvent) -> FSMResult
    async def handle_executing_tool(self, event: FSMEvent) -> FSMResult
    async def handle_validating_cfl(self, event: FSMEvent) -> FSMResult
    # ... handlers for all 12 states
```

### OrchestratorSyncBridge (V9.4)
```python
class OrchestratorSyncBridge:
    """Synchronizes state between HiveMind and Swarm layers."""

    def emit(self, event: SyncEvent) -> None
    def subscribe(self, event_type: SyncEventType, handler: Callable) -> None
    def get_unified_state(self) -> UnifiedState
```

## Usage Pattern

The orchestration module follows a **composition** pattern:

```python
# In OrchestratorV7.__init__():
self.context_builder = ContextBuilder(config)
self.agent_invoker = AgentInvoker(drivers, config)
self.mutation_detector = get_mutation_detector()
self.fsm_handlers = FSMHandlers(self)
self.swarm_bridge = SwarmBridge(swarm_engine)
self.sync_bridge = get_sync_bridge()

# Usage in orchestrator:
context = self.context_builder.build(task, history, blackboard)
response = await self.agent_invoker.invoke("gemini", prompt, context)
mutation = self.mutation_detector.detect(response.content)
```

## Sync Events (V9.4)

```python
class SyncEventType(Enum):
    PHASE_STARTED = "phase_started"
    PHASE_COMPLETED = "phase_completed"
    MODE_CHANGED = "mode_changed"
    AGENT_ASSIGNED = "agent_assigned"
    ERROR_OCCURRED = "error_occurred"
    CHECKPOINT_CREATED = "checkpoint_created"
```

## Dependencies

### Internal
- `core.fsm` - State definitions
- `core.drivers` - Agent drivers
- `core.synapse` - Message types
- `core.swarm` - Swarm engine
- `core.hive_mind` - HiveMind pipeline

### External
- Standard library only

## Version History

- **V7.8** - Phase 14c: Extraction from monolithic orchestration_v7.py
- **V9.4** - ISSUE-003: OrchestratorSyncBridge for state synchronization
- **V12.4** - Enhanced context building, improved error handling
