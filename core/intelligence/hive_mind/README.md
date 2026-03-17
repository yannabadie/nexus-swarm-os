# NEXUS HiveMind Module

## Synopsis

The **hive_mind** module implements the TRUE HIVE MIND - a 7-phase collaborative pipeline that transforms NEXUS from a sequential orchestrator into a genuine collaborative intelligence. It enables strategic multi-agent problem-solving for MODERATE+ complexity tasks, with user breakpoints, adaptive debate, and knowledge consolidation.

## Architecture

```text
HIVE MIND 7-PHASE PIPELINE
==========================

Phase 1: ANALYSIS
  - Independent multi-agent analysis in parallel (N providers via CapabilityRouter)

Phase 2: DEBATE
  - Resolve disagreements
  - Breakpoint: debate

Phase 3: ARCHITECTURE
  - Design execution plan
  - Breakpoint: spawn

Phase 4: EXECUTION
  - Monitored delivery via SwarmBridge delegation

Phase 5: DIAGNOSIS
  - Root cause analysis
  - Breakpoint: diagnosis

Phase 6: RETRY
  - Adaptive retry decision

Phase 7: CONSOLIDATION
  - Knowledge archival
  - Breakpoint: consolidation

Terminal states:
  - HIVE_SUCCESS
  - HIVE_FAILED
  - HIVE_ESCALATE
```

## Component Map

| File | Purpose | Key Exports |
|------|---------|-------------|
| `orchestrator.py` | Main pipeline orchestrator | `TrueHiveMind`, `HiveMindResult` |
| `base_phase.py` | Base class for all phases | `BasePhase` (agents dict, deprecated `.gemini`/`.claude` aliases) |
| `types.py` | Core dataclasses & enums | `HiveMindState`, `IndependentAnalysis`, `DebateResult` |
| `agent_registry.py` | Anti-duplication registry | `AgentRegistry` |
| `cost_estimator.py` | Budget control | `CostEstimator` |
| `context_manager.py` | Sliding window context | `HiveMindContextManager` |
| `strategy_blacklist.py` | Anti-circular retry | `StrategyBlacklist` |
| `user_interaction.py` | Breakpoint handling | `UserInteractionHandler` |
| `adaptive_debate.py` | Dynamic debate turns | `AdaptiveDebateConfig`, `DebateParams` |
| `swarm_bridge.py` | HiveMind -> Swarm delegation | `SwarmBridge`, `SwarmDelegationResult` |
| `saga_manager.py` | Checkpoint/recovery | `SagaManager`, `PhaseCheckpoint` |
| `json_parser.py` | Response parsing | JSON extraction utilities |
| `async_adapter.py` | Async utilities | Async adaptation helpers |
| `session_integration.py` | Session management | Session context integration |
| `success_adapter.py` | Success memory integration | Learning from successes |

## 7 Phases Explained

### Phase 1: Independent Analysis
**States**: `HIVE_ANALYZING_GEMINI`, `HIVE_ANALYZING_CLAUDE`, `HIVE_COMPARING_ANALYSES`

All active agents analyze the task independently without communication (N-agent support via CapabilityRouter):
- Primary agent produces JSON-structured analysis
- Secondary agent produces natural language analysis
- System compares and calculates agreement score (0-1)

### Phase 2: Strategic Debate
**States**: `HIVE_DEBATING`, `HIVE_CHECKING_CONSENSUS`, `HIVE_BREAKPOINT_DEBATE`

If agreement score < threshold, agents debate through structured argumentation:
- Adaptive turn count based on complexity
- Evidence-based arguments
- Convergence detection

### Phase 3: Architecture Generation
**States**: `HIVE_ARCHITECTING`, `HIVE_CHECKING_REGISTRY`, `HIVE_BREAKPOINT_SPAWN`, `HIVE_SPAWNING`

Design the execution plan:
- Agent topology (spawn new specialists?)
- Step-by-step execution plan
- Resource allocation

### Phase 4: Monitored Execution
**States**: `HIVE_EXECUTING`, `HIVE_MONITORING`

Execute with real-time monitoring:
- Tool execution tracking
- Issue detection
- **SwarmBridge**: Delegate to Swarm modes per step

### Phase 5: Failure Diagnosis
**States**: `HIVE_DIAGNOSING`, `HIVE_BREAKPOINT_DIAGNOSIS`

Dual-agent failure analysis:
- Root cause identification
- Pattern matching with past failures
- Blame attribution

### Phase 6: Adaptive Retry
**States**: `HIVE_DECIDING_RETRY`, `HIVE_APPLYING_CHANGES`

Decide retry strategy:
- **RETRY**: Try again with modifications
- **STOP**: Accept failure
- **ESCALATE**: Require user intervention

### Phase 7: Knowledge Consolidation
**States**: `HIVE_REFLECTING`, `HIVE_DECIDING_RETENTION`, `HIVE_BREAKPOINT_CONSOLIDATION`, `HIVE_CONSOLIDATING`

Post-task knowledge management:
- Archive successful patterns to SuccessMemory
- Decide agent retention (keep spawned agents?)
- Update blackboard

## Key Interfaces

### TrueHiveMind
```python
class TrueHiveMind:
    """Main HiveMind orchestrator."""

    async def process_task(
        self,
        task: str,
        context: TaskExecutionContext
    ) -> HiveMindResult

    def get_current_phase(self) -> HiveMindState
    def get_saga_checkpoint(self) -> PhaseCheckpoint
```

### HiveMindState (24 States)
```python
class HiveMindState(Enum):
    HIVE_GATING = "hive_gating"
    # Phase 1
    HIVE_ANALYZING_GEMINI = "hive_analyzing_gemini"
    HIVE_ANALYZING_CLAUDE = "hive_analyzing_claude"
    HIVE_COMPARING_ANALYSES = "hive_comparing_analyses"
    # Phase 2
    HIVE_DEBATING = "hive_debating"
    HIVE_CHECKING_CONSENSUS = "hive_checking_consensus"
    HIVE_BREAKPOINT_DEBATE = "hive_breakpoint_debate"
    # Phase 3
    HIVE_ARCHITECTING = "hive_architecting"
    HIVE_CHECKING_REGISTRY = "hive_checking_registry"
    HIVE_BREAKPOINT_SPAWN = "hive_breakpoint_spawn"
    HIVE_SPAWNING = "hive_spawning"
    # Phase 4
    HIVE_EXECUTING = "hive_executing"
    HIVE_MONITORING = "hive_monitoring"
    # Phase 5
    HIVE_DIAGNOSING = "hive_diagnosing"
    HIVE_BREAKPOINT_DIAGNOSIS = "hive_breakpoint_diagnosis"
    # Phase 6
    HIVE_DECIDING_RETRY = "hive_deciding_retry"
    HIVE_APPLYING_CHANGES = "hive_applying_changes"
    # Phase 7
    HIVE_REFLECTING = "hive_reflecting"
    HIVE_DECIDING_RETENTION = "hive_deciding_retention"
    HIVE_BREAKPOINT_CONSOLIDATION = "hive_breakpoint_consolidation"
    HIVE_CONSOLIDATING = "hive_consolidating"
    # Terminal
    HIVE_SUCCESS = "hive_success"
    HIVE_FAILED = "hive_failed"
    HIVE_ESCALATE = "hive_escalate"
```

### SwarmBridge (V8.3.0)
```python
class SwarmBridge:
    """Delegate execution steps to Swarm Engine."""

    async def delegate(
        self,
        step: ExecutionStep,
        context: ExecutionContext
    ) -> SwarmDelegationResult
```

## User Breakpoints

4 configurable breakpoints for user intervention:

| Breakpoint | Location | Options |
|------------|----------|---------|
| `BREAKPOINT_DEBATE` | After Phase 2 | Accept/Reject consensus |
| `BREAKPOINT_SPAWN` | After Phase 3 | Approve agent spawning |
| `BREAKPOINT_DIAGNOSIS` | After Phase 5 | Review diagnosis |
| `BREAKPOINT_CONSOLIDATION` | After Phase 7 | Approve knowledge retention |

## Configuration

```bash
# .env configuration
HIVE_MIND_ENABLED=True
HIVE_MIND_BUDGET_LIMIT=50000      # Token budget per task
HIVE_MIND_BREAKPOINT_TIMEOUT=60   # User response timeout (seconds)
HIVE_MIND_MIN_AGREEMENT=0.7       # Skip debate if agreement >= this
```

## Dependencies

### Internal
- `core.swarm` - SwarmBridge delegation
- `core.memory` - SuccessMemory, Blackboard
- `core.drivers` - Agent invocation
- `core.fsm` - State transitions

### External
- `pydantic` - Validation
- Standard library (asyncio, dataclasses)

## BasePhase (V12.4 NX-CG)

All 6 HiveMind phase classes now extend `BasePhase`, which stores agents as a provider-agnostic `dict[str, BaseAsyncDriver]`:

```python
from core.intelligence.hive_mind.base_phase import BasePhase

class MyPhase(BasePhase):
    def __init__(self, agents: dict | None = None, **kwargs):
        super().__init__(agents=agents)
        # self.agents["primary"]   → primary driver
        # self.agents["secondary"] → secondary driver
        # self.agent_ids           → ["primary", "secondary", ...]
```

**Backward compatibility**: `.gemini` and `.claude` properties emit `DeprecationWarning` and map to `agents["primary"]` / `agents["secondary"]` respectively.

**Agent routing**: `TrueHiveMind` uses `CapabilityRouter` to resolve slots before instantiating phases — phases never see raw provider IDs.

## Version History

- **V8.0** - TRUE HIVE MIND initial implementation
- **V8.3.0** - SwarmBridge integration
- **V8.4.4** - SagaManager checkpoint/recovery
- **V12.4** - Adaptive debate, cost optimization
- **V12.4 NX-CG** - Model-agnostic migration: BasePhase, CapabilityRouter wired in orchestrator, all 6 phases provider-agnostic
