# NEXUS Core Module

## Synopsis

The **core** package contains the runtime modules that power NEXUS V12.4 "COGNITIVE BOOST". The live codebase is organized around `intelligence`, `execution_pkg`, `memory_pkg`, `security_pkg`, `interface_pkg`, `infrastructure`, and `observability`, with `OrchestratorV7` and `NexusSessionRuntime` acting as the main runtime facades.

## Architecture Overview

```
+-------------------------------------------------------------------------+
|                         NEXUS CORE ARCHITECTURE                          |
+-------------------------------------------------------------------------+
|  +------------------+    +------------------+    +------------------+  |
|  |   User Input     |--->|   FSM Layer      |--->|   Complexity     |  |
|  |   (REPL/API)     |    |   (12 States)    |    |   Assessment     |  |
|  +------------------+    +--------+---------+    +--------+---------+  |
|                                   |                        |            |
|           +-----------------------+------------------------+            |
|           v                       v                                     |
|  +------------------+    +------------------+                          |
|  |   BRAINSTORMING  |    |   HiveMind       |  MODERATE+ Complexity    |
|  |   (Simple Tasks) |    |   (7 Phases)     |                          |
|  +--------+---------+    +--------+---------+                          |
|           |                       |                                     |
|           |              +--------v---------+                          |
|           |              |   SwarmBridge    |  Phase 4 Delegation      |
|           |              +--------+---------+                          |
|           |                       |                                     |
|           +-----------+-----------+                                     |
|                       v                                                 |
|           +----------------------+                                     |
|           |    Swarm Engine      |  6 Collaboration Modes              |
|           |    (Negotiation)     |                                     |
|           +----------+-----------+                                     |
|                      |                                                  |
|           +----------v-----------+                                     |
|           |   Agent Drivers      |  Gemini + Claude                    |
|           |   (JSON/XML)         |                                     |
|           +----------------------+                                     |
+-------------------------------------------------------------------------+
```

## Component Map

| Component | Path | Purpose |
|-----------|------|---------|
| **OrchestratorV7** | `orchestration_v7.py` | Main FSM controller, persistent singleton |
| **ServiceFactory** | `factory.py` | Context-aware service instantiation |
| **NexusConfig** | `config.py` | Configuration management |
| **Constants** | `constants.py` | TIMEOUTS, RETRY_LIMITS, SAGA_LIMITS |

## Submodule Overview

| Module | Purpose | Key Exports |
|--------|---------|-------------|
| [drivers/](drivers/README.md) | LLM driver abstraction layer | `AsyncClaudeDriver`, `AsyncGeminiDriver`, `DriverProtocol` |
| [fsm/](fsm/README.md) | Finite State Machine components | `OrchestratorState`, `TaskExecutionContext`, `HealthStateMachine` |
| [intelligence/hive_mind/](intelligence/hive_mind/README.md) | 7-phase strategic pipeline | `TrueHiveMind`, `HiveMindState`, `SwarmBridge` |
| [intelligence/swarm/](intelligence/swarm/README.md) | 6-mode collaboration engine | `HybridSwarmEngine`, `CollaborationMode`, `TaskAnalyzer` |
| [execution_pkg/execution/](execution_pkg/execution/README.md) | Tool execution layer | `ToolManager`, `AgentToolRegistry`, `ExecutionEngine` |
| [execution_pkg/routing/](execution_pkg/routing/README.md) | Model routing intelligence | `ModelRouter`, `CascadedRouter` |
| [execution_pkg/orchestration/](execution_pkg/orchestration/README.md) | FSM handlers, context builder, swarm bridge | `AgentInvoker`, `ContextBuilder`, `SwarmBridge` |
| [memory_pkg/memory/](memory_pkg/memory/README.md) | Project memory, success memory, retrieval backends | `ProjectMemory`, `SuccessMemoryV2`, `MemoryService` |
| [security_pkg/security/](security_pkg/security/README.md) | Runtime guards and execution policy | `ExecutionPolicy`, `PathGuardian`, `IntegrityMonitor` |
| [security_pkg/governance/](security_pkg/governance/README.md) | Governance and red-team support | `SandboxPolicy`, `AlignmentJournal`, `DecisionLogger` |
| [interface_pkg/interface/](interface_pkg/interface/README.md) | REPL and slash-command layer | `InteractiveNexusV7`, `CommandRegistry` |
| [api/cerebro/](api/cerebro/README.md) | FastAPI control plane | `create_cerebro_app` |
| [observability/telemetry/](observability/telemetry/README.md) | Metrics, budgets, OTel, profiling | `BudgetTracker`, `HealthAggregator`, `OTelProvider` |
| [infrastructure/context/](infrastructure/context/README.md) | Context and multi-tenant isolation | `SessionContext`, `TenantContextMiddleware` |

## Three-Layer Orchestration

### Layer 1: FSM (12 States)
Low-level state machine managing basic orchestration flow:
- `IDLE` -> `BRAINSTORMING` -> `EXECUTING_TOOL` -> `VALIDATING_CFL` -> `IDLE`
- Special states: `SWARM_*`, `HIBERNATE`, `ERROR`, `PANIC`

### Layer 2: HiveMind (7 Phases)
High-level strategic pipeline for MODERATE+ complexity tasks:
1. **Analysis** - Independent analysis by both agents
2. **Debate** - Resolve disagreements through argumentation
3. **Architecture** - Design execution plan
4. **Execution** - Execute with monitoring (SwarmBridge delegation)
5. **Diagnosis** - Failure root cause analysis
6. **Retry** - Adaptive retry decision
7. **Consolidation** - Knowledge archival

### Layer 3: Swarm Engine (6 Modes)
Dynamic collaboration where agents negotiate optimal mode:
- `PARALLEL` - Simultaneous work, merge results
- `SEQUENTIAL` - Ordered execution
- `LEAD_SUPPORT` - 80% lead / 20% support
- `PING_PONG` - Rapid alternation
- `SPECIALIST` - Single expert
- `RED_BLUE` - Adversarial review

## Key Interfaces

### OrchestratorV7
```python
class OrchestratorV7:
    """Main persistent FSM controller. Created once at startup."""

    def process_turn(user_input: Optional[str]) -> Dict
    async def process_turn_async(user_input: Optional[str]) -> Dict
    def reset_to_idle(clear_task: bool = True)
    def get_system_status() -> Dict
```

### ServiceFactory
```python
from pathlib import Path

from core.config import Config
from core.runtime import NexusSessionRuntime

config = Config()
runtime = NexusSessionRuntime.from_config(
    config,
    workspace_path=Path("workspace"),
    interaction_mode="headless",
)
result = runtime.execute_task("Inspect the current project")
```

## Complexity Routing

```
User Input -> TaskAnalyzer -> Complexity Assessment
                               |
    +--------------------------+--------------------------+
    |                          |                          |
 TRIVIAL               SIMPLE/MODERATE              COMPLEX/EXPERT
 Fast Path             Brainstorming                   HiveMind
 (regex)               + Swarm Auto                    7 Phases
```

## Dependencies

### Internal
- `core.fsm.*` - State machine
- `core.drivers.*` - LLM drivers
- `core.intelligence.hive_mind.*` - Strategic pipeline
- `core.intelligence.swarm.*` - Collaboration engine
- `core.memory_pkg.memory.*` - RAG & persistence
- `core.execution_pkg.execution.*` - Tool execution
- `core.execution_pkg.orchestration.*` - Orchestration support
- `core.security_pkg.security.*` - Runtime guards

### External
- `pydantic` - Validation
- `tiktoken` - Token counting
- `python-dotenv` - Configuration
- Standard library (asyncio, pathlib, json)

## Entry Points

1. **REPL**: `nexus7.py` -> bootstraps `InteractiveNexusV7` / `NexusSessionRuntime`
2. **REST API**: `core/api/cerebro/` -> session-scoped runtime facade
3. **Commands**: `core/interface_pkg/interface/commands/` -> slash-command registry

## Configuration

```bash
NEXUS_DRIVER_MODE=auto
WORKSPACE_PATH=./workspace
NEXUS_ROOT=.
SWARM_AUTO_ROUTE=True
HIVE_MIND_ENABLED=True
```

## Governance Note

`KERNEL.py` and `INVARIANTS.md` still exist for compatibility, heredity, and historical review, but they are not the default runtime authority on `NX-CG`. The live runtime path is `nexus7.py` -> `NexusSessionRuntime` -> `OrchestratorV7`.

## Version History

- **V7.0** - FSM Persistent architecture
- **V8.0** - TRUE HIVE MIND (7-phase pipeline)
- **V9.0** - Async-first drivers
- **V10.0** - PRISM multi-tenant
- **V11.0** - SYNCHROTRON abstraction layer
- **V12.0** - IRONCLAD security + RETINA monitoring
- **V12.4** - COGNITIVE BOOST (current)
