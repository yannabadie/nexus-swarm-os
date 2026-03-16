# TRUE HIVE MIND V8.0 - Integration Strategy

## Overview

This document describes how V8 Hive Mind integrates with existing V7 systems.

## Gating Logic

```
                    USER INPUT
                         |
                         v
                +-----------------+
                |  TaskAnalyzer   |
                +--------+--------+
                         |
         +---------------+---------------+
         |               |               |
      TRIVIAL         SIMPLE      MODERATE/COMPLEX/EXPERT
         |               |               |
         v               v               v
    +---------+    +---------+    +-----------------+
    | FAST    |    | SINGLE  |    |  GATE CHECK     |
    | PATH    |    | AGENT   |    |                 |
    +---------+    +---------+    +--------+--------+
                                           |
                    +----------------------+----------------------+
                    |                      |                      |
             MODERATE only          MODERATE (if              COMPLEX/EXPERT
             & hive_moderate=F      hive_moderate=T)
                    |                      |                      |
                    v                      v                      v
              +-------------+       +-----------------+    +-----------------+
              | V7 SWARM    |       | V8 HIVE MIND    |    | V8 HIVE MIND    |
              | (existing)  |       | (new)           |    | (new)           |
              +-------------+       +-----------------+    +-----------------+
```

## Component Relationships

### 1. Agent Management

| Existing | Hive Mind | Relationship |
|----------|-----------|--------------|
| `AgentPool` | `AgentRegistry` | **COMPLEMENTARY** |
| - DyLAN metrics | - Anti-duplication | Pool for metrics, Registry for spawn control |
| - select_best_for_task | - find_similar | Both needed |
| `SpawnedAgentLoader` | - | Registry CALLS loader |

**Integration**: `AgentRegistry` uses `AgentPool` for metrics, `SpawnedAgentLoader` for discovery.

### 2. Cost Tracking

| Existing | Hive Mind | Relationship |
|----------|-----------|--------------|
| `BudgetTracker` | `CostEstimator` | **COMPLEMENTARY** |
| - USD costs | - Token estimates | Estimator -> Tracker |
| - Daily limits | - Operation affordability | Chain: estimate -> budget check |

**Integration**: `CostEstimator.can_afford()` calls `BudgetTracker.can_spend()` for final check.

### 3. Negotiation vs Debate

| Existing | Hive Mind | Relationship |
|----------|-----------|--------------|
| `NegotiationProtocol` | `StrategicDebatePhase` | **DIFFERENT SCOPES** |
| - MODE selection | - APPROACH resolution | Do NOT mix |
| - XML `<negotiate>` | - JSON arguments | Different protocols |
| - Max 4 rounds | - 3-10 adaptive | Different dynamics |

**Integration**: Keep separate. Negotiation for Swarm mode selection, Debate for task approach.

### 4. Failure Handling

| Existing | Hive Mind | Relationship |
|----------|-----------|--------------|
| `StagnationDetector` | `StrategyBlacklist` | **CHAIN** |
| - Output similarity | - Strategy tracking | Stagnation -> Blacklist |
| `PanicSystem` | `AdaptiveRetryPhase` | **ESCALATION** |

**Integration**: Stagnation feeds blacklist. Retry phase uses blacklist. Panic if max retries.

### 5. Memory

| Existing | Hive Mind | Relationship |
|----------|-----------|--------------|
| `ProjectMemory` | `HiveMindContextManager` | **INTEGRATION IN PLACE** |
| `SuccessMemory` | `KnowledgeConsolidation` | Consolidation WRITES to memories |
| `MemoryManagerV7` | - | Blackboard persistence |

**Integration**: Phase 7 archives to ProjectMemory. Already implemented.

## Configuration Keys

```python
# In NexusConfig (nexus_config.py)

# V8 Hive Mind Settings
hive_mind_enabled: bool = True           # Enable V8 Hive Mind
hive_mind_moderate: bool = True          # Route MODERATE to Hive Mind (user decision)
hive_mind_budget_limit: int = 50000      # Token budget per task
hive_mind_max_debate_turns: int = 10     # Max debate turns
hive_mind_breakpoints_enabled: bool = True  # User breakpoints
```

## FSM State Additions

Existing V7 states are PRESERVED. V8 adds new states:

```python
# In core/fsm/states.py - OrchestratorState enum

# V7 States (unchanged)
IDLE = "idle"
BRAINSTORMING = "brainstorming"
EXECUTING_TOOL = "executing_tool"
VALIDATING_CFL = "validating_cfl"
WAITING_USER = "waiting_user"
ERROR = "error"
PANIC = "panic"
EVOLUTION_BRAINSTORM = "evolution_brainstorm"
SWARM_ANALYZING = "swarm_analyzing"
SWARM_NEGOTIATING = "swarm_negotiating"
SWARM_EXECUTING = "swarm_executing"

# V8 States (new)
HIVE_GATING = "hive_gating"
HIVE_ANALYZING = "hive_analyzing"
HIVE_DEBATING = "hive_debating"
HIVE_ARCHITECTING = "hive_architecting"
HIVE_EXECUTING = "hive_executing"
HIVE_DIAGNOSING = "hive_diagnosing"
HIVE_RETRYING = "hive_retrying"
HIVE_CONSOLIDATING = "hive_consolidating"
HIVE_BREAKPOINT = "hive_breakpoint"
```

## Entry Point

**File**: `core/orchestration/fsm_handlers.py`
**Method**: `_handle_moderate_plus()`

```python
def _handle_moderate_plus(self, user_input: str, task_analysis) -> Dict:
    complexity = task_analysis.complexity

    # V8 HIVE MIND GATE
    if self._should_use_hive_mind(complexity):
        return self._route_to_hive_mind(user_input, task_analysis)

    # V7 Swarm (existing behavior)
    if self._orch.swarm_engine and getattr(self._orch.config, 'swarm_auto_route', True):
        # ... existing swarm code ...
```

## Files Modified

1. `core/orchestration/fsm_handlers.py` - Add gating logic
2. `core/fsm/states.py` - Add HIVE_* states
3. `nexus_config.py` - Add hive_mind_* settings
4. `core/orchestration_v7.py` - Initialize HiveMind components

## Files Added (already created)

- `core/hive_mind/` - Complete V8 module
- `core/hive_mind/phases/` - 7 phases implementation

## Migration Path

1. **Phase A**: Add gating (no behavior change for existing tasks)
2. **Phase B**: Enable for COMPLEX/EXPERT only (safe)
3. **Phase C**: Enable for MODERATE (user decision implemented)
4. **Phase D**: Deprecate V7 Swarm for complex tasks (future)

---

## V8.0 Integration Implementation Details

### Integration 1: fsm_handlers -> TrueHiveMind

**File**: `core/orchestration/fsm_handlers.py`

**Methods Added**:
- `_should_use_hive_mind(complexity)`: Gating logic
  - Returns `True` for COMPLEX/EXPERT
  - Returns `True` for MODERATE if `hive_mind_moderate=True`
  - Returns `False` otherwise (routes to V7 Swarm)

- `_route_to_hive_mind(user_input, task_analysis)`: Entry point
  - Initializes `TrueHiveMind` with workspace, config, drivers
  - Runs async pipeline via `asyncio.run()`
  - Returns result in FSM-compatible format
  - Falls back to Swarm on error

- `_fallback_to_swarm_or_brainstorm()`: Error recovery
  - Logs warning and routes to existing V7 path

**Code Flow**:
```
_handle_moderate_plus()
    |
    +-> _should_use_hive_mind(complexity)
    |       |
    |       +-> True: _route_to_hive_mind()
    |       |           |
    |       |           +-> TrueHiveMind.process_task()
    |       |           +-> Return result
    |       |
    |       +-> False: Existing V7 Swarm code
```

### Integration 2: CostEstimator -> BudgetTracker

**File**: `core/hive_mind/cost_estimator.py`

**Methods Added**:
- `set_budget_tracker(tracker)`: Link to BudgetTracker
- `tokens_to_usd(tokens)`: Convert tokens to USD (~$3/1M tokens)
- `check_usd_budget(tokens)`: Check USD budget via BudgetTracker

**Modified Methods**:
- `can_afford(operation, count)`: Now checks BOTH token AND USD budgets
- `can_afford_multiple(operations)`: Now checks BOTH budgets
- `get_stats()`: Now includes USD integration stats

**Chain Logic**:
```
can_afford("spawn_agent")
    |
    +-> Check token budget (self.spent + cost <= self.budget_limit)
    |       |
    |       +-> False: Return False (token limit exceeded)
    |
    +-> check_usd_budget(cost)
            |
            +-> tokens_to_usd(cost)
            +-> BudgetTracker.get_remaining()
            +-> Return (estimated_usd <= remaining_usd)
```

### Integration 3: StagnationDetector -> StrategyBlacklist

**File**: `core/fsm/stagnation_detector.py`

**Methods Added**:
- `set_strategy_blacklist(blacklist)`: Link to StrategyBlacklist
- `extract_stagnant_strategy()`: Extract discussion topic from repeated messages
- `report_to_blacklist(task_context)`: Report stagnation to blacklist
- `check_and_report(task_context)`: Combined check + report

**File**: `core/hive_mind/strategy_blacklist.py`

**Additions**:
- `FailureCategory.STAGNATION`: New failure category
- Suggestions for STAGNATION in `suggest_alternatives()`:
  - "Stop discussing and take a concrete action"
  - "Use a tool immediately without further deliberation"
  - "Switch to a different agent or perspective"
  - "Force a decision: pick the simplest viable option"
  - "Break the impasse by reading a specific file"

**Chain Logic**:
```
StagnationDetector.add_message(msg)
    |
    +-> is_stagnant()
            |
            +-> True: check_and_report()
                    |
                    +-> extract_stagnant_strategy()
                    +-> StrategyBlacklist.add_failed_strategy(
                            strategy,
                            reason="Agents stuck in circular discussion",
                            category=FailureCategory.STAGNATION
                        )
```

---

## Testing the Integrations

```python
# Test CostEstimator -> BudgetTracker
from core.intelligence.hive_mind.cost_estimator import CostEstimator
from core.telemetry.budget_tracker import BudgetTracker

tracker = BudgetTracker(config)
estimator = CostEstimator(budget_limit=50000)
estimator.set_budget_tracker(tracker)

# Now can_afford() checks both token AND USD budgets
estimator.can_afford("spawn_agent")  # Checks both

# Test StagnationDetector -> StrategyBlacklist
from core.fsm.stagnation_detector import StagnationDetector
from core.intelligence.hive_mind.strategy_blacklist import StrategyBlacklist

blacklist = StrategyBlacklist()
detector = StagnationDetector()
detector.set_strategy_blacklist(blacklist)

detector.add_message("let's read auth.py")
detector.add_message("yes, read auth.py first")
detector.add_message("ok, reading auth.py")

if detector.check_and_report():
    print("Stagnation reported to blacklist")
```
