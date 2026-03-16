# NEXUS FSM Module

## Synopsis

The **fsm** (Finite State Machine) module provides the low-level orchestration layer for NEXUS. It defines the 12 states that govern the system's behavior, manages task execution context, handles stagnation detection/prediction, and provides health monitoring with automatic recovery strategies.

## Architecture

```
+-------------------------------------------------------------------------+
|                         FSM ARCHITECTURE                                 |
+-------------------------------------------------------------------------+
|                                                                          |
|  +------------------------------------------------------------------+   |
|  |                     OrchestratorState (Enum)                      |   |
|  |  12 States: IDLE, BRAINSTORMING, EXECUTING_TOOL, VALIDATING_CFL,  |   |
|  |  EVOLUTION_BRAINSTORM, WAITING_USER, ERROR, PANIC,                |   |
|  |  SWARM_ANALYZING, SWARM_NEGOTIATING, SWARM_EXECUTING, HIBERNATE   |   |
|  +----------------------------+-------------------------------------+   |
|                               |                                          |
|         +---------------------+-------------------------------------+   |
|         v                     v                                     v   |
|  +--------------+    +--------------+    +----------------------+      |
|  |TaskExecution |    |HealthState   |    | StagnationPredictor  |      |
|  |   Context    |    |  Machine     |    |  (ML-based)          |      |
|  +--------------+    +--------------+    +----------------------+      |
|         |                     |                     |                   |
|         v                     v                     v                   |
|  +--------------+    +--------------+    +----------------------+      |
|  |  Hibernation |    |  Recovery    |    |  Stagnation          |      |
|  |   Manager    |    |  Strategies  |    |  Detector            |      |
|  +--------------+    +--------------+    +----------------------+      |
|                                                                          |
+-------------------------------------------------------------------------+
```

## Component Map

| File | Purpose | Key Exports |
|------|---------|-------------|
| `states.py` | State definitions & transitions | `OrchestratorState`, `TRANSITION_MATRIX` |
| `context.py` | Execution context management | `TaskExecutionContext` |
| `health_state_machine.py` | Health monitoring FSM | `HealthStateMachine`, `HealthState`, `RecoveryStrategy` |
| `stagnation_detector.py` | Loop/stagnation detection | `StagnationDetector` |
| `stagnation_predictor.py` | ML-based prediction | `StagnationPredictor`, `PredictionLevel` |
| `hibernation_manager.py` | WebSocket disconnect handling | `HibernationManager` |
| `panic_system.py` | Fatal error handling | `PanicSystem`, `PanicReason` |
| `plan_health.py` | Plan execution health | `PlanHealthMonitor` |

## State Diagram

```
                    +--------------------------------------------------+
                    |                                                  |
                    v                                                  |
            +-----------+                                              |
            |   IDLE    |<--------------------------------------------+|
            +-----+-----+                                             ||
                  | user_input                                         ||
    +-------------+-------------+                                     ||
    |             v             |                                     ||
    |    +---------------+      | swarm_auto_route                    ||
    |    | BRAINSTORMING |      |                                     ||
    |    +-------+-------+      |                                     ||
    |            |              v                                     ||
    |            |     +-----------------+                            ||
    |            |     | SWARM_ANALYZING |                            ||
    |            |     +--------+--------+                            ||
    |            |              |                                     ||
    |            |              v                                     ||
    |  tool_use  |     +------------------+                           ||
    |            |     |SWARM_NEGOTIATING |                           ||
    |            |     +--------+---------+                           ||
    |            |              |                                     ||
    |            |              v                                     ||
    |            |     +-----------------+                            ||
    |            |     | SWARM_EXECUTING |                            ||
    |            |     +--------+--------+                            ||
    |            |              |                                     ||
    |            v              |                                     ||
    |    +---------------+      |                                     ||
    |    |EXECUTING_TOOL |<-----+                                     ||
    |    +-------+-------+                                            ||
    |            |                                                    ||
    |            v                                                    ||
    |    +---------------+     success                                ||
    |    |VALIDATING_CFL |---------------------------------------------+|
    |    +-------+-------+                                             |
    |            | failure                                             |
    |            +------------------------------------------------------+
    |
    +----> ERROR ----> PANIC (fatal)
              |
              | /reset
              +--------> IDLE
```

## Key Interfaces

### OrchestratorState
```python
class OrchestratorState(Enum):
    IDLE = auto()                    # Awaiting user input
    BRAINSTORMING = auto()           # Agents exchange TALK messages
    EXECUTING_TOOL = auto()          # Tool execution (synchronous)
    VALIDATING_CFL = auto()          # Cognitive Feedback Loop validation
    EVOLUTION_BRAINSTORM = auto()    # Debate for emergent mutations
    WAITING_USER = auto()            # Task finished, awaiting next input
    ERROR = auto()                   # Recoverable error (/reset)
    PANIC = auto()                   # Fatal error (restart required)
    SWARM_ANALYZING = auto()         # Swarm analyzes task complexity
    SWARM_NEGOTIATING = auto()       # Agents negotiate collaboration mode
    SWARM_EXECUTING = auto()         # Execute negotiated mode
    HIBERNATE = auto()               # V12.2: WebSocket disconnected
```

### TaskExecutionContext
```python
@dataclass(frozen=True)
class TaskExecutionContext:
    """Immutable context for task execution."""
    task_id: str
    user_input: str
    start_time: datetime
    complexity: TaskComplexity
    domains: List[TaskDomain]
    budget_tokens: int
    session_uuid: str
```

### HealthStateMachine
```python
class HealthStateMachine:
    """Monitors system health and triggers recovery."""

    def check_health(self) -> HealthState
    def get_recovery_strategy(self) -> RecoveryStrategy
    def apply_recovery(self, strategy: RecoveryStrategy) -> bool
```

### StagnationPredictor
```python
class StagnationPredictor:
    """ML-based stagnation prediction."""

    def predict(self, history: List[Message]) -> PredictionResult
    # Returns: PredictionLevel (LOW, MEDIUM, HIGH, CRITICAL)
```

## Transition Matrix

| From State | Trigger | To State |
|------------|---------|----------|
| IDLE | user_input | BRAINSTORMING |
| IDLE | swarm_auto_route | SWARM_ANALYZING |
| BRAINSTORMING | tool_use | EXECUTING_TOOL |
| BRAINSTORMING | finished | WAITING_USER |
| BRAINSTORMING | stagnation | ERROR |
| BRAINSTORMING | ws_disconnect | HIBERNATE |
| EXECUTING_TOOL | tool_completed | VALIDATING_CFL |
| VALIDATING_CFL | success | IDLE |
| VALIDATING_CFL | failure | BRAINSTORMING |
| VALIDATING_CFL | stalemate | ERROR |
| SWARM_ANALYZING | analysis_complete | SWARM_NEGOTIATING |
| SWARM_NEGOTIATING | consensus | SWARM_EXECUTING |
| SWARM_EXECUTING | execution_complete | VALIDATING_CFL |
| HIBERNATE | ws_reconnect | previous_state |
| ERROR | reset | IDLE |
| ERROR | timeout | PANIC |

## Recovery Strategies

```python
class RecoveryStrategy(Enum):
    RETRY = "retry"           # Retry current operation
    ROLLBACK = "rollback"     # Rollback to checkpoint
    ESCALATE = "escalate"     # Escalate to user
    RESET = "reset"           # Full state reset
    HIBERNATE = "hibernate"   # Enter dormant state
```

## Dependencies

### Internal
- `core.synapse` - Message types
- `core.db.models` - HibernationState persistence

### External
- Standard library only

## Version History

- **V7.0** - Initial 8-state FSM
- **V7.5** - Added SWARM_* states
- **V8.4.4** - Health FSM, Stagnation Predictor
- **V12.2** - HIBERNATE state for WebSocket disconnect
- **V12.4** - Plan health monitoring
