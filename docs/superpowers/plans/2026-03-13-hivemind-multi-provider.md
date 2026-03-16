# HiveMind Multi-Provider Refactoring Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make HiveMind and all orchestration layers provider-agnostic, replacing 64 hardcoded Claude/Gemini references with a dynamic N-agent architecture that works with any combination of the 7 supported providers.

**Architecture:** Replace `(gemini_driver, claude_driver)` constructor pattern with `agents: dict[str, BaseAsyncDriver]` throughout all 7 HiveMind phases, debate logic, and FSM dispatch. Keep backward compatibility: `{"gemini": driver, "claude": driver}` produces identical behavior to current code. Generalize 2-way comparison/alternation to N-way voting/round-robin using research-backed protocols (arxiv 2502.19130: voting > consensus for reasoning).

**Tech Stack:** Python 3.11+, Pydantic V2, existing BaseAsyncDriver protocol, AsyncDriverFactory, unified_registry.

**Constraints:**
- Zero breaking change for existing 2-agent (Claude+Gemini) usage
- All 11,307 existing tests must remain green
- Minimum 2 agents required, no upper limit
- TDD: write failing tests first, then implement

---

## File Structure

### Modified files (by priority):

| File | Responsibility | Change Type |
|------|---------------|-------------|
| `core/foundation/agents/unified_registry.py` | Agent registry + alternation | Replace `get_alternate()` binary → `get_next()` round-robin |
| `core/intelligence/swarm/agent_metrics.py` | ProviderType enum + agent pool filter | Extend enum, generalize filter |
| `core/intelligence/hive_mind/types.py` | Disagreement, AnalysisComparison, DebateResult | Replace hardcoded fields with dicts |
| `core/intelligence/hive_mind/orchestrator.py` | HiveMind main coordinator | Replace 2-driver constructor with agents dict |
| `core/intelligence/hive_mind/phases/phase_analysis.py` | Analysis phase | N-agent parallel analysis + comparison |
| `core/intelligence/hive_mind/phases/phase_debate.py` | Debate phase | N-agent debate with voting |
| `core/intelligence/hive_mind/adaptive_debate.py` | Debate decision logic | N-way scoring + winner selection |
| `core/intelligence/hive_mind/phases/phase_architecture.py` | Architecture phase | Generic agent list |
| `core/intelligence/hive_mind/phases/phase_execution.py` | Execution phase | Generic agent dispatch |
| `core/intelligence/hive_mind/phases/phase_diagnosis.py` | Diagnosis phase | Generic agent dispatch |
| `core/intelligence/hive_mind/phases/phase_consolidation.py` | Consolidation phase | Generic agent satisfaction |
| `core/intelligence/hive_mind/phases/phase_retry.py` | Retry phase | Generic agent dispatch |
| `core/execution_pkg/orchestration/agent_invoker.py` | LLM invocation | Registry-based dispatch |
| `core/execution_pkg/routing/model_router.py` | Model selection | Registry dispatch instead of if/elif |
| `core/fsm/handlers/validating_cfl.py` | CFL validation | Driver factory dispatch |
| `core/execution_pkg/orchestration/fsm_handlers.py` | FSM handler dispatch | Registry-based driver selection |
| `core/fsm/stagnation_detector.py` | Stagnation recovery | Round-robin instead of binary swap |
| `core/intelligence/swarm/negotiation_protocol.py` | Agent negotiation | Dynamic agent list |
| `core/intelligence/swarm/task_analyzer.py` | Domain strengths | Extensible capability matrix |
| `core/fsm/handlers/idle_waiting.py` | Init active agent | Configurable default |
| `core/orchestration_v7.py` | Main orchestrator | Pass agents dict to HiveMind |

### New files:

| File | Responsibility |
|------|---------------|
| `tests/test_multi_provider_registry.py` | Tests for N-agent registry operations |
| `tests/test_multi_provider_hivemind.py` | Tests for N-agent HiveMind pipeline |

---

## Chunk 1: Foundation — Registry & Types

### Task 1: Extend unified_registry with `get_next()` round-robin

**Files:**
- Modify: `core/foundation/agents/unified_registry.py:226-241`
- Test: `tests/test_multi_provider_registry.py`

- [ ] **Step 1: Write failing tests for `get_next()`**

```python
# tests/test_multi_provider_registry.py
from core.foundation.agents.unified_registry import AgentRegistry, get_registry, reset_registry

class TestGetNext:
    def setup_method(self):
        reset_registry()
        self.registry = get_registry()

    def test_two_agents_alternates(self):
        """Backward compatible: 2 agents alternate like get_alternate."""
        result = self.registry.get_next("gemini")
        assert result == "claude"
        result2 = self.registry.get_next("claude")
        assert result2 == "gemini"

    def test_three_agents_round_robin(self):
        """3+ agents cycle in registration order."""
        from unittest.mock import MagicMock
        # Register a third agent
        self.registry.register_driver("deepseek", MagicMock())
        result = self.registry.get_next("gemini")
        assert result == "claude"
        result2 = self.registry.get_next("claude")
        assert result2 == "deepseek"
        result3 = self.registry.get_next("deepseek")
        assert result3 == "gemini"

    def test_unknown_agent_returns_first(self):
        result = self.registry.get_next("unknown_agent")
        assert result is not None  # Returns first registered agent

    def test_get_alternate_still_works(self):
        """Backward compatibility: get_alternate() delegates to get_next()."""
        assert self.registry.get_alternate("gemini") == "claude"
        assert self.registry.get_alternate("claude") == "gemini"

    def test_get_active_agents(self):
        """List all active builtin agents."""
        agents = self.registry.get_active_builtin_ids()
        assert "gemini" in agents
        assert "claude" in agents
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_multi_provider_registry.py -v`
Expected: FAIL (get_next, get_active_builtin_ids don't exist)

- [ ] **Step 3: Implement `get_next()` and `get_active_builtin_ids()`**

In `core/foundation/agents/unified_registry.py`, add after `get_alternate()`:

```python
def get_active_builtin_ids(self) -> list[str]:
    """Return IDs of all registered builtin agents with drivers, in registration order."""
    return [
        aid for aid, agent in self._agents.items()
        if agent.driver is not None and aid in self._builtin_ids
    ]

def get_next(self, current: str) -> str:
    """Get the next agent in round-robin order among active builtins.

    For 2 agents: identical to get_alternate().
    For 3+ agents: cycles through registration order.
    """
    normalized = self._normalize_id(current)
    active = self.get_active_builtin_ids()
    if not active:
        return normalized  # No agents registered, return self
    if normalized not in active:
        return active[0]  # Unknown agent, return first
    idx = active.index(normalized)
    return active[(idx + 1) % len(active)]
```

Update `get_alternate()` to delegate:
```python
def get_alternate(self, agent_id: str) -> str | None:
    """Get alternate agent. Delegates to get_next() for backward compatibility."""
    result = self.get_next(agent_id)
    return result if result != self._normalize_id(agent_id) else None
```

Also add `_builtin_ids` tracking in `__init__`:
```python
self._builtin_ids: list[str] = []  # Track registration order
```

And in `register_driver()`, track builtin IDs:
```python
if agent_id not in self._builtin_ids:
    self._builtin_ids.append(agent_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_multi_provider_registry.py -v`
Expected: PASS

- [ ] **Step 5: Run full suite to verify no regressions**

Run: `pytest tests/ -q --tb=no --maxfail=20 --ignore=tests/test_llm_context_isolation.py --ignore=tests/test_dense_backend.py --ignore=tests/v10/test_memory_optimization.py`
Expected: 0 failures

- [ ] **Step 6: Commit**

```bash
git add core/foundation/agents/unified_registry.py tests/test_multi_provider_registry.py
git commit -m "feat(registry): add get_next() round-robin for N-agent alternation

Replaces binary get_alternate() with round-robin get_next() that supports
2+ agents. get_alternate() delegates to get_next() for backward compat.
Adds get_active_builtin_ids() for ordered agent listing."
```

---

### Task 2: Extend ProviderType enum and agent pool filter

**Files:**
- Modify: `core/intelligence/swarm/agent_metrics.py:47-52, 238`
- Test: existing tests + inline verification

- [ ] **Step 1: Extend ProviderType enum**

```python
class AgentProvider(Enum):
    """Agent providers - extensible for all supported integrations"""
    GEMINI = "gemini"
    CLAUDE = "claude"
    OPENAI = "openai"
    DEEPSEEK = "deepseek"
    KIMI = "kimi"
    MINIMAX = "minimax"
    OLLAMA = "ollama"
```

- [ ] **Step 2: Fix hardcoded filter in `get_active_agents()`**

Replace line 238:
```python
# BEFORE
return [a for a in self.agents.values() if a.is_active and a.provider in ("gemini", "claude")]
# AFTER
return [a for a in self.agents.values() if a.is_active]
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/ -k "agent_metrics or agent_pool" -q --tb=short`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add core/intelligence/swarm/agent_metrics.py
git commit -m "feat(metrics): extend ProviderType enum to all 7 providers

Adds OPENAI, DEEPSEEK, KIMI, MINIMAX, OLLAMA to AgentProvider enum.
Removes hardcoded 2-provider filter in get_active_agents()."
```

---

### Task 3: Generalize HiveMind types (Disagreement, AnalysisComparison, DebateResult)

**Files:**
- Modify: `core/intelligence/hive_mind/types.py:178-234`
- Test: `tests/test_multi_provider_hivemind.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_multi_provider_hivemind.py
from core.intelligence.hive_mind.types import Disagreement, AnalysisComparison, DebateResult

class TestGenericTypes:
    def test_disagreement_uses_positions_dict(self):
        d = Disagreement(
            topic="approach",
            positions={"gemini": "option A", "deepseek": "option B", "kimi": "option C"},
            severity=0.5,
        )
        assert len(d.positions) == 3
        assert d.positions["kimi"] == "option C"

    def test_disagreement_backward_compat_properties(self):
        """gemini_position/claude_position still work for 2-agent case."""
        d = Disagreement(
            topic="test",
            positions={"gemini": "pos_g", "claude": "pos_c"},
            severity=0.3,
        )
        assert d.gemini_position == "pos_g"
        assert d.claude_position == "pos_c"

    def test_analysis_comparison_uses_analyses_dict(self):
        from core.intelligence.hive_mind.types import IndependentAnalysis
        a1 = IndependentAnalysis(task_understanding="t1", complexity_assessment="SIMPLE",
                                 proposed_approach="a1", required_capabilities=[], potential_risks=[],
                                 confidence=0.8)
        a2 = IndependentAnalysis(task_understanding="t2", complexity_assessment="MODERATE",
                                 proposed_approach="a2", required_capabilities=[], potential_risks=[],
                                 confidence=0.7)
        comp = AnalysisComparison(
            analyses={"gemini": a1, "deepseek": a2},
            disagreements=[], agreement_score=0.6, needs_debate=True,
            merged_capabilities=[], merged_risks=[],
        )
        assert len(comp.analyses) == 2
        # Backward compat
        assert comp.gemini_analysis == a1

    def test_debate_result_uses_satisfactions_dict(self):
        dr = DebateResult(
            winner="merged",
            winning_position="combined approach",
            satisfactions={"gemini": 0.8, "deepseek": 0.7, "kimi": 0.6},
            consensus_reached=True, debate_rounds=3,
        )
        assert dr.satisfactions["kimi"] == 0.6
        # Backward compat
        assert dr.gemini_satisfaction == 0.8
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Refactor types.py**

Replace hardcoded fields with dicts + backward-compat properties:

```python
@dataclass
class Disagreement:
    topic: str
    positions: dict[str, Any]  # {agent_id: position}
    severity: float = 0.5

    # Backward compatibility properties
    @property
    def gemini_position(self) -> Any:
        return self.positions.get("gemini")

    @property
    def claude_position(self) -> Any:
        return self.positions.get("claude")


@dataclass
class AnalysisComparison:
    analyses: dict[str, "IndependentAnalysis"]  # {agent_id: analysis}
    disagreements: list[Disagreement] = field(default_factory=list)
    agreement_score: float = 0.0
    needs_debate: bool = False
    merged_capabilities: list[str] = field(default_factory=list)
    merged_risks: list[str] = field(default_factory=list)

    @property
    def gemini_analysis(self) -> "IndependentAnalysis":
        return self.analyses.get("gemini")

    @property
    def claude_analysis(self) -> "IndependentAnalysis":
        return self.analyses.get("claude")


@dataclass
class DebateResult:
    winner: str
    winning_position: str
    satisfactions: dict[str, float]  # {agent_id: satisfaction_score}
    consensus_reached: bool = False
    debate_rounds: int = 0
    key_insights: list[str] = field(default_factory=list)
    action_items: list[str] = field(default_factory=list)

    @property
    def gemini_satisfaction(self) -> float:
        return self.satisfactions.get("gemini", 0.0)

    @property
    def claude_satisfaction(self) -> float:
        return self.satisfactions.get("claude", 0.0)
```

- [ ] **Step 4: Run tests + full suite**

- [ ] **Step 5: Commit**

```bash
git add core/intelligence/hive_mind/types.py tests/test_multi_provider_hivemind.py
git commit -m "feat(hivemind): generalize types to N-agent with backward-compat properties

Disagreement: positions dict instead of gemini_position/claude_position
AnalysisComparison: analyses dict instead of gemini_analysis/claude_analysis
DebateResult: satisfactions dict instead of gemini/claude_satisfaction
All old field names preserved as @property for backward compatibility."
```

---

### Task 4: Refactor HiveMind orchestrator constructor

**Files:**
- Modify: `core/intelligence/hive_mind/orchestrator.py:97-180`
- Modify: `core/fsm/handlers/idle_waiting.py:285-286`

- [ ] **Step 1: Modify orchestrator to accept agents dict**

Change constructor from:
```python
def __init__(self, ..., gemini_driver, claude_driver, ...):
    self.gemini = gemini_driver
    self.claude = claude_driver
```
To:
```python
def __init__(self, ..., agents: dict[str, "BaseAsyncDriver"] | None = None,
             gemini_driver: "BaseAsyncDriver | None" = None,
             claude_driver: "BaseAsyncDriver | None" = None, ...):
    # Support both new and legacy calling conventions
    if agents is not None:
        self.agents = agents
    else:
        self.agents = {}
        if gemini_driver is not None:
            self.agents["gemini"] = gemini_driver
        if claude_driver is not None:
            self.agents["claude"] = claude_driver
    self.agent_ids = list(self.agents.keys())
    # Backward compat
    self.gemini = self.agents.get("gemini")
    self.claude = self.agents.get("claude")
```

- [ ] **Step 2: Propagate agents dict to all phases**

Each phase constructor gets the same pattern. Update the orchestrator's phase creation to pass `agents=self.agents`.

- [ ] **Step 3: Update idle_waiting.py to pass agents dict**

Where HiveMind is created (line ~285):
```python
# BEFORE
gemini_driver=self._orch.gemini_driver,
claude_driver=self._orch._get_claude_driver(TaskType.BRAINSTORM),
# AFTER (add agents dict, keep legacy params for compat)
agents=self._build_hivemind_agents(),
```

Add helper:
```python
def _build_hivemind_agents(self) -> dict[str, Any]:
    """Build agents dict from available drivers."""
    agents = {}
    factory = getattr(self._orch, '_driver_factory', None)
    if factory:
        # Add all available SDK providers
        if factory.gemini_sdk_available or True:  # Gemini always available (CLI fallback)
            agents["gemini"] = self._orch.gemini_driver
        if factory.claude_sdk_available:
            agents["claude"] = self._orch._driver_factory.get_best_claude()
        for provider in ["deepseek", "openai", "kimi", "minimax"]:
            if getattr(factory, f"{provider}_sdk_available", False):
                try:
                    agents[provider] = factory.get_driver(provider, prefer_sdk=True)
                except Exception:
                    pass
    else:
        agents["gemini"] = self._orch.gemini_driver
    return agents
```

- [ ] **Step 4: Run tests**

- [ ] **Step 5: Commit**

```bash
git add core/intelligence/hive_mind/orchestrator.py core/fsm/handlers/idle_waiting.py
git commit -m "feat(hivemind): accept agents dict, auto-discover available providers

HiveMind now accepts agents={} dict alongside legacy gemini_driver/claude_driver.
idle_waiting auto-discovers all available SDK providers from the factory."
```

---

## Chunk 2: Routing & Dispatch

### Task 5: Make ModelRouter provider-agnostic

**Files:**
- Modify: `core/execution_pkg/routing/model_router.py:490-573`

Replace if/elif chains with registry dispatch:
```python
def select_model(self, agent_id: str, task_type: TaskType) -> str:
    """Select model for any provider."""
    agent_lower = agent_id.lower()
    # Check if there's a provider-specific selector
    selector = self._provider_selectors.get(agent_lower)
    if selector:
        return selector(task_type)
    # Fallback: return config default for the provider
    return getattr(self.config, f"{agent_lower}_model", agent_lower)
```

- [ ] Steps: Read current code, write tests, implement, verify, commit

---

### Task 6: Make CFL validation provider-agnostic

**Files:**
- Modify: `core/fsm/handlers/validating_cfl.py:30-34`

Replace:
```python
if self._orch.active_agent == "claude":
    driver = self._get_claude_driver(...)
else:
    response = self._orch.gemini_driver.invoke(...)
```
With:
```python
validator_id = self._registry.get_next(self._orch.active_agent)
driver = self._orch._driver_factory.get_driver(validator_id, prefer_sdk=True)
response = await driver.invoke(context)
```

- [ ] Steps: Read, test, implement, verify, commit

---

### Task 7: Make FSM handler dispatch provider-agnostic

**Files:**
- Modify: `core/execution_pkg/orchestration/fsm_handlers.py:1821-1839, 992-998`
- Modify: `core/execution_pkg/orchestration/agent_invoker.py`

Replace all `if agent == "gemini"` / `elif agent == "claude"` with:
```python
driver = self._orch._driver_factory.get_driver(agent, prefer_sdk=True)
```

- [ ] Steps: Read, test, implement, verify, commit

---

### Task 8: Fix stagnation recovery

**Files:**
- Modify: `core/fsm/stagnation_detector.py:482`

Replace binary swap with round-robin:
```python
# BEFORE
new_lead = "claude" if current_lead.lower() == "gemini" else "gemini"
# AFTER
from core.foundation.agents.unified_registry import get_registry
new_lead = get_registry().get_next(current_lead)
```

- [ ] Steps: Read, test, implement, verify, commit

---

## Chunk 3: HiveMind Intelligence

### Task 9: Refactor phase_analysis.py for N agents

**Files:**
- Modify: `core/intelligence/hive_mind/phases/phase_analysis.py`

Key changes:
- Constructor accepts `agents: dict[str, BaseAsyncDriver]`
- `_run_parallel_analysis()` uses `asyncio.gather(*[analyze(agent_id, driver) for agent_id, driver in self.agents.items()])`
- `_compare_analyses()` takes `dict[str, IndependentAnalysis]` instead of 2 positional args
- Build `AnalysisComparison(analyses={...})` instead of `AnalysisComparison(gemini_analysis=..., claude_analysis=...)`

- [ ] Steps: Read full file, write tests, implement, verify, commit

---

### Task 10: Refactor adaptive_debate.py for N-way voting

**Files:**
- Modify: `core/intelligence/hive_mind/adaptive_debate.py:356-402`

Replace 2-way comparison with N-way scoring:
```python
def decide_winner(self, agent_scores: dict[str, float]) -> dict:
    """N-way winner selection using majority voting (arxiv 2502.19130)."""
    ranked = sorted(agent_scores.items(), key=lambda x: x[1], reverse=True)
    top_score = ranked[0][1]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0

    if top_score > runner_up + 0.1:
        return {"winner": ranked[0][0], "winning_position": ..., "method": "majority"}
    return {"winner": "merged", "winning_position": ..., "method": "consensus"}
```

- [ ] Steps: Read, test, implement, verify, commit

---

### Task 11: Refactor phase_debate.py for N agents

**Files:**
- Modify: `core/intelligence/hive_mind/phases/phase_debate.py`

Key changes:
- Constructor accepts `agents: dict`
- Speaker alternation uses `registry.get_next()`
- Satisfaction tracking uses `satisfactions: dict[str, float]`
- Consensus check picks first agent (configurable) instead of hardcoded Gemini

- [ ] Steps: Read full file, write tests, implement, verify, commit

---

### Task 12: Refactor remaining phases (architecture, execution, diagnosis, consolidation, retry)

**Files:**
- Modify: `core/intelligence/hive_mind/phases/phase_architecture.py`
- Modify: `core/intelligence/hive_mind/phases/phase_execution.py`
- Modify: `core/intelligence/hive_mind/phases/phase_diagnosis.py`
- Modify: `core/intelligence/hive_mind/phases/phase_consolidation.py`
- Modify: `core/intelligence/hive_mind/phases/phase_retry.py`

Pattern for each: accept `agents: dict`, replace `self.gemini`/`self.claude` with `self.agents[agent_id]`, keep `self.gemini`/`self.claude` as backward-compat properties.

- [ ] Steps: Implement each phase, test, commit

---

### Task 13: Make negotiation protocol N-agent

**Files:**
- Modify: `core/intelligence/swarm/negotiation_protocol.py:311, 341`

Replace:
```python
agents = ["gemini", "claude"]
other_agent = "claude" if agent_id == "gemini" else "gemini"
```
With:
```python
agents = registry.get_active_builtin_ids()
other_agents = [a for a in agents if a != agent_id]
```

- [ ] Steps: Read, test, implement, verify, commit

---

### Task 14: Extend domain strengths matrix

**Files:**
- Modify: `core/intelligence/swarm/task_analyzer.py:197-221`

Add profiles for all 7 providers:
```python
AGENT_DOMAIN_STRENGTHS = {
    "gemini": {RESEARCH: 0.95, WEB_INTERACTION: 0.90, ...},
    "claude": {CODING: 0.95, DEBUGGING: 0.90, ...},
    "openai": {CODING: 0.90, RESEARCH: 0.85, ...},
    "deepseek": {CODING: 0.92, REASONING: 0.88, ...},
    "kimi": {REASONING: 0.90, RESEARCH: 0.85, ...},
    "minimax": {CODING: 0.80, REASONING: 0.82, ...},
    "ollama": {CODING: 0.70, SIMPLE: 0.85, ...},
}
```

- [ ] Steps: Read, implement, test, commit

---

## Chunk 4: Final Integration & Verification

### Task 15: Integration test — full HiveMind with 3 providers

Write integration test that creates HiveMind with 3 mock drivers and runs a full pipeline.

- [ ] Steps: Write test, run, verify all phases work with 3 agents

### Task 16: Full suite regression check

- [ ] Run: `pytest tests/ -q --tb=no --maxfail=500 --ignore=tests/test_llm_context_isolation.py --ignore=tests/test_dense_backend.py --ignore=tests/v10/test_memory_optimization.py`
- [ ] Target: 0 failures
- [ ] Commit all remaining changes
- [ ] Push to GitHub

---

## Execution Order

Tasks 1→2→3→4 (sequential, each depends on previous)
Tasks 5→6→7→8 (can parallelize after Task 1)
Tasks 9→10→11→12→13→14 (sequential, depend on Task 3)
Tasks 15→16 (final verification)
