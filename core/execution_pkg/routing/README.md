# Routing Module

## Synopsis
The Routing module provides intelligent model selection for NEXUS, routing tasks to the most appropriate model based on task type and complexity. It supports static routing (task type to model mapping) and dynamic routing via DyLAN agent performance metrics. Handles both Claude (Opus/Sonnet) and Gemini (Pro/Flash) model selection.

## Component Map
| File | Purpose | Key Exports |
|------|---------|-------------|
| `model_router.py` | Intelligent model selection engine with static and dynamic routing | `ModelRouter`, `TaskType`, `RoutingDecision` |
| `__init__.py` | Module initialization with public exports | `ModelRouter`, `TaskType` |

## Key Interfaces

### Core Classes

**`TaskType`** (enum)
- Defines task categories for routing decisions
- **Opus/Pro tasks** (complex): `BRAINSTORM`, `REDTEAM`, `ARCHITECT`, `EVOLUTION`, `REASONING`, `RESEARCH`, `ANALYSIS`
- **Sonnet/Flash tasks** (simple): `TOOL`, `VALIDATION`, `SIMPLE`, `FORMAT`
- **Default**: `DEFAULT`

**`RoutingDecision`** (dataclass)
- Result of routing decision with explanation
- Fields: `model_id`, `task_type`, `reason`, `is_opus`
- Provides transparency for model selection

**`ModelRouter`**
- Main router class with static and dynamic routing capabilities
- Configurable model IDs and task type mappings
- Integrates with DyLAN agent pool for performance-based routing

### Routing Methods

**`select_claude_model(task_type: TaskType) -> str`**
- Select Claude model (Opus or Sonnet) based on task type
- Complex tasks (BRAINSTORM, EVOLUTION) -> Opus
- Simple tasks (TOOL, VALIDATION) -> Sonnet

**`select_gemini_model(task_type: TaskType) -> str`**
- Select Gemini model (3-Pro or Flash) based on task type
- Complex tasks (REASONING, RESEARCH) -> Gemini 3 Pro
- Simple tasks (TOOL, FORMAT) -> Gemini Flash
- **Note**: V7 Sprint 6 currently uses Pro for all tasks

**`select_claude_model_str(task_type_str: str) -> str`**
- String-based variant of Claude model selection
- Handles invalid task types gracefully (defaults to DEFAULT)

**`select_gemini_model_str(task_type_str: str) -> str`**
- String-based variant of Gemini model selection

**`route(task_type: TaskType) -> RoutingDecision`**
- Full routing decision with explanation
- Returns `RoutingDecision` with model, task type, and reasoning

### Dynamic Routing (DyLAN Integration)

**`select_best_agent(task_type: TaskType, agent_pool: Optional[AgentPool] = None, min_importance: float = 0.5) -> RoutingDecision`**
- Select best agent using DyLAN performance metrics when available
- Combines static routing with dynamic performance history
- Falls back to static routing if no pool or insufficient metrics
- Filters agents by minimum importance score threshold
- Returns agent with best importance score and success rate for task type

### Utility Methods

**`should_use_opus(task_type: TaskType) -> bool`**
- Check if task requires Claude Opus

**`should_use_gemini_pro(task_type: TaskType) -> bool`**
- Check if task requires Gemini 3 Pro

**`get_gemini_model() -> str`**
- Get default configured Gemini model

**`get_routing_stats(agent_pool: Optional[AgentPool] = None) -> dict`**
- Get routing configuration and pool statistics for debugging
- Returns model IDs, task mappings, pool availability, and agent metrics

## Dependencies & Integration

### Internal Dependencies
- `core.config` - Configuration with model IDs and task type mappings
- `core.swarm` (optional) - AgentPool for DyLAN metrics

### Integration Points
- **Drivers**: Gemini and Claude drivers use router to select appropriate models
- **SwarmEngine**: Uses DyLAN-based routing for agent selection
- **Config**: Model IDs and task type mappings configurable via Config object

### Configuration

Default Model IDs:
- **Claude Opus**: `claude-opus-4-6-20250116`
- **Claude Sonnet**: `claude-sonnet-4-6-20250929`
- **Gemini Pro**: `gemini-3-pro-preview`
- **Gemini Flash**: `gemini-3-pro-preview` (V7: uses Pro for all)

Task Type Mappings:
- **Opus Tasks**: BRAINSTORM, REDTEAM, ARCHITECT, EVOLUTION
- **Sonnet Tasks**: TOOL, VALIDATION, SIMPLE, FORMAT
- **Gemini Pro Tasks**: REASONING, RESEARCH, ANALYSIS, BRAINSTORM, EVOLUTION
- **Gemini Flash Tasks**: SIMPLE, FORMAT, VALIDATION, TOOL

All defaults are overridable via Config object.

### Usage Examples

```python
from core.execution_pkg.routing import ModelRouter, TaskType

# Static routing
router = ModelRouter(config)

# Claude model selection
model = router.select_claude_model(TaskType.BRAINSTORM)
# Returns: "claude-opus-4-6-20250116"

model = router.select_claude_model(TaskType.TOOL)
# Returns: "claude-sonnet-4-6-20250929"

# Gemini model selection
model = router.select_gemini_model(TaskType.REASONING)
# Returns: "gemini-3-pro-preview"

# Full routing decision with explanation
decision = router.route(TaskType.EVOLUTION)
print(decision.reason)
# "Task type 'evolution' requires complex reasoning - routing to Opus"

# Dynamic routing with DyLAN metrics
from core.intelligence.swarm import create_default_pool

pool = create_default_pool(config)
decision = router.select_best_agent(TaskType.BRAINSTORM, pool)
print(decision.reason)
# "DyLAN selection: claude-opus (importance=0.872, success_rate=94.3%)"

# Routing stats
stats = router.get_routing_stats(pool)
print(stats)
# {
#   "opus_model": "claude-opus-4-6-20250116",
#   "pool_agents": 2,
#   "pool_invocations": 147,
#   ...
# }
```

### Design Notes
- **Static Routing**: Task type -> Model mapping (fast, predictable)
- **Dynamic Routing**: DyLAN metrics -> Agent selection (adaptive, performance-based)
- **Fallback Strategy**: Dynamic routing falls back to static if no metrics available
- **Importance Threshold**: Filters agents by minimum importance score (default 0.5)
- **Transparency**: All routing decisions include reasoning
- **Configurability**: Model IDs and task mappings fully configurable
- **V7 Gemini**: Currently uses Pro for all tasks (Flash routing ready but not active)

## V12.4 COGNITIVE BOOST Additions

| File | Purpose | Key Exports |
|------|---------|-------------|
| `routing_effectiveness_analyzer.py` | Tracks routing decision outcomes to determine optimality, analyzes policy effectiveness, and monitors cost-quality tradeoffs across models and task types | `get_routing_analyzer`, `RoutingEffectivenessAnalyzer` |
| `decision_cache.py` | Caches model routing decisions to avoid re-computation for repeated task patterns and learns from execution outcomes to improve future routing | `get_decision_cache`, `DecisionCache` |
| `resource_optimizer.py` | Token budget and cost optimization across models with actual-vs-estimated usage tracking and pattern-based learning | `get_resource_optimizer`, `ResourceOptimizer` |
