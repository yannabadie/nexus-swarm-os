# NEXUS Swarm Module

## Synopsis

The **swarm** module implements the Hybrid Swarm Engine - a dynamic multi-agent collaboration system where agents negotiate the optimal collaboration mode for each task at runtime. It provides 6 collaboration modes, task complexity analysis, DyLAN-based agent metrics, and self-healing fallback chains.

## Architecture

```
+-------------------------------------------------------------------------+
|                      SWARM ENGINE ARCHITECTURE                           |
+-------------------------------------------------------------------------+
|                                                                          |
|  +------------------------------------------------------------------+   |
|  |                       HybridSwarmEngine                           |   |
|  |  process_task() -> Analyze -> Negotiate -> Execute -> Validate        |   |
|  +----------------------------+-------------------------------------+   |
|                               |                                          |
|         +---------------------+-------------------------------------+   |
|         |                     |                     |               |   |
|         v                     v                     v               |   |
|  +--------------+    +--------------+    +----------------------+  |   |
|  | TaskAnalyzer |    | ModeSelector |    |NegotiationProtocol   |  |   |
|  | Complexity   |    | DyLAN Scores |    | Natural + JSON       |  |   |
|  | + Domains    |    |              |    |                      |  |   |
|  +--------------+    +--------------+    +----------------------+  |   |
|                                                                     |   |
|  +--------------------------------------------------------------+  |   |
|  |                     EXECUTOR_REGISTRY                         |  |   |
|  +--------------------------------------------------------------+  |   |
|  |  PARALLEL    | SEQUENTIAL  | LEAD_SUPPORT | PING_PONG        |  |   |
|  |  -------     | ----------  | -----------  | ---------        |  |   |
|  |  Both work   | Ordered     | 80% Lead     | Rapid            |  |   |
|  |  parallel    | execution   | 20% Support  | alternation      |  |   |
|  +--------------+-------------+--------------+------------------+  |   |
|  |  SPECIALIST  | RED_BLUE                                       |  |   |
|  |  ----------  | --------                                       |  |   |
|  |  Single      | Adversarial                                    |  |   |
|  |  expert      | propose/attack                                 |  |   |
|  +--------------+------------------------------------------------+  |   |
|                                                                          |
+-------------------------------------------------------------------------+
```

## Component Map

| File | Purpose | Key Exports |
|------|---------|-------------|
| `hybrid_swarm_engine.py` | Main orchestration engine | `HybridSwarmEngine`, `SwarmResult`, `SwarmPhase` |
| `collaboration_modes.py` | Mode definitions | `CollaborationMode`, `ModeCharacteristics` |
| `task_analyzer.py` | Complexity analysis | `TaskAnalyzer`, `TaskComplexity`, `TaskDomain` |
| `capability_router.py` | Model-agnostic slot assignment | `CapabilityRouter`, `AGENT_DOMAIN_STRENGTHS` |
| `mode_selector.py` | DyLAN-based selection | `ModeSelector`, `ModeProposal`, `AgentAssignment` |
| `negotiation_protocol.py` | Hybrid negotiation | `NegotiationProtocol`, `NegotiationResult` |
| `mode_executors.py` | 6 mode executors | `ParallelExecutor`, `SequentialExecutor`, etc. |
| `agent_metrics.py` | DyLAN agent profiles | `AgentProfile`, `AgentPool`, `AgentInvocationResult` |
| `merge_strategies.py` | Result merging | `MergeStrategy`, `CONCATENATE`, `INTERLEAVE` |
| `adaptive_fallback.py` | Self-healing chains | `FallbackChain`, `get_fallback_mode` |
| `session_manager.py` | Session tracking | `SwarmSessionManager`, `TaskSession` |
| `task_completion_validator.py` | Completion validation | `TaskCompletionValidator`, `ValidationResult` |
| `service.py` | Service layer | `SwarmService`, `SwarmStatus` |

## 6 Collaboration Modes

| Mode | Affinity | Parallelism | Adversarial | Rounds | Use Case |
|------|----------|-------------|-------------|--------|----------|
| **PARALLEL** | 0.5 | 100% | No | 1 | Independent subtasks |
| **SEQUENTIAL** | 0.6 | 0% | No | 2 | Pipeline dependencies |
| **LEAD_SUPPORT** | 0.7 | 30% | No | 3 | Complex implementation |
| **PING_PONG** | 0.6 | 20% | No | 6 | Creative iteration |
| **SPECIALIST** | 0.8 | 0% | No | 1 | Exclusive expertise |
| **RED_BLUE** | 1.0 | 10% | Yes | 4 | Security reviews |

### Mode Details

#### PARALLEL
```
+---------+     +---------+
| Primary |     |Secondary|  Both work simultaneously
|  Task   |     |  Task   |  Results merged via strategy
+----+----+     +----+----+
     |               |
     +-------+-------+
             v
        +---------+
        |  MERGE  |  CONCATENATE | INTERLEAVE | BEST_FIRST
        +---------+
```

#### SEQUENTIAL
```
+---------+     +---------+
| Agent 1 |---->| Agent 2 |  Ordered execution
| Execute |     | Refine  |  Second builds on first
+---------+     +---------+
```

#### LEAD_SUPPORT
```
+---------------------+
|       LEAD (80%)    |  Drives main implementation
|  +---------------+  |
|  |   SUPPORT     |  |  Reviews, assists, validates
|  |    (20%)      |  |
|  +---------------+  |
+---------------------+
```

#### PING_PONG
```
+---------+     +---------+     +---------+     +---------+
| Agent 1 |---->| Agent 2 |---->| Agent 1 |---->| Agent 2 |
| Round 1 |     | Round 2 |     | Round 3 |     | Round 4 |
+---------+     +---------+     +---------+     +---------+
```

#### SPECIALIST
```
+---------------------+
|    SPECIALIST       |  Single expert handles everything
|    (100%)           |
|  +---------------+  |
|  |   Observer    |  |  Other agent observes only
|  |    (0%)       |  |
|  +---------------+  |
+---------------------+
```

#### RED_BLUE (Adversarial)
```
+---------+         +---------+
|  BLUE   |-------->|   RED   |
| Propose |         | Attack  |
+----+----+         +----+----+
     |                   |
     |    +---------+    |
     +--->|  BLUE   |<---+
          | Defend  |
          +---------+
```

## Key Interfaces

### HybridSwarmEngine
```python
class HybridSwarmEngine:
    """Main Swarm orchestration engine."""

    def process_task(
        self,
        task: str,
        blackboard: Blackboard,
        context: Optional[ExecutionContext] = None
    ) -> SwarmResult

    def get_current_phase(self) -> SwarmPhase
    def get_session_info(self) -> TaskSession
```

### TaskAnalyzer
```python
class TaskAnalyzer:
    """3-stage cost-aware complexity analysis."""

    def analyze(self, task: str) -> TaskAnalysis
    # Stage 1: Regex (instant commands) - $0
    # Stage 2: Heuristic (keywords) - Low CPU
    # Stage 3: LLM (ambiguous) - API Tokens
```

### TaskComplexity
```python
class TaskComplexity(Enum):
    TRIVIAL = 1   # /status, /clear - Skip negotiation
    SIMPLE = 2    # Basic tasks
    MODERATE = 3  # Standard multi-agent (HiveMind eligible)
    COMPLEX = 4   # Careful coordination
    EXPERT = 5    # RED_BLUE or specialist required
```

### NegotiationProtocol
```python
class NegotiationProtocol:
    """Hybrid natural language + JSON negotiation."""

    def negotiate(
        self,
        agents: List[AgentProfile],
        task_analysis: TaskAnalysis,
        max_turns: int = 4
    ) -> NegotiationResult
```

## Self-Healing Fallback Chain (V7.5)

```
PARALLEL      -> SEQUENTIAL    (simplify parallelism)
RED_BLUE      -> LEAD_SUPPORT  (remove adversarial)
LEAD_SUPPORT  -> SPECIALIST    (simplify to single agent)
PING_PONG     -> SEQUENTIAL    (simplify alternation)
SEQUENTIAL    -> SPECIALIST    (last resort)
```

## DyLAN Agent Metrics

Each agent maintains performance history:

```python
@dataclass
class AgentProfile:
    agent_id: str
    importance_scores: Dict[TaskDomain, float]  # Per-domain quality
    success_rate: float                          # Overall success
    avg_response_time: float                     # Latency
    specializations: List[TaskDomain]            # Best domains
```

## Configuration

```bash
# .env configuration
SWARM_AUTO_ROUTE=True               # Auto-route MODERATE+ tasks
SWARM_NEGOTIATION_ENABLED=True      # Enable agent negotiation
SWARM_NEGOTIATION_MAX_TURNS=4       # Max negotiation rounds
SWARM_MAX_ROUNDS=6                  # Max execution rounds
SWARM_SELF_HEALING=True             # Enable graceful degradation
```

## Dependencies

### Internal
- `core.drivers` - Agent invocation
- `core.memory` - Blackboard access
- `core.routing` - Model routing

### External
- `pydantic` - Validation
- Standard library

## CapabilityRouter (V12.4 NX-CG)

The `CapabilityRouter` maps task domains to semantic agent slots, decoupling phases from specific provider IDs.

```python
from core.intelligence.swarm.capability_router import CapabilityRouter
from core.foundation.agents.unified_registry import get_registry

router = CapabilityRouter(get_registry())
agents = router.route(task_analysis)
# agents = {"primary": <driver>, "secondary": <driver>, ...}
```

**Semantic slots**: `primary`, `secondary`, `critic`, `executor`

**Scoring**: `AGENT_DOMAIN_STRENGTHS` maps 7 providers × 13 domains to float scores (0.0–1.0):

| Domain | Best providers |
|--------|---------------|
| `CODING` | deepseek, claude |
| `RESEARCH` | gemini, claude |
| `ANALYSIS` | gemini, claude |
| `MATH` | deepseek, gemini |
| `WRITING` | claude, kimi |
| `REASONING` | claude, openai |

**Single-provider degradation**: When only 1 provider is registered, multi-agent modes (`PARALLEL`, `LEAD_SUPPORT`, `PING_PONG`, `RED_BLUE`) automatically degrade to `SPECIALIST` to avoid no-op multi-agent calls.

## Version History

- **V7.0** - Sprint 9: Initial Hybrid Swarm Engine
- **V7.5** - Self-healing fallback chains
- **V7.9** - Task completion validator
- **V8.3** - SwarmBridge (HiveMind integration)
- **V9.1** - Service layer extraction
- **V12.4** - Adaptive rounds, cost optimization
- **V12.4 NX-CG** - Model-agnostic migration: CapabilityRouter, 7-provider domain strengths, single-provider mode degradation
