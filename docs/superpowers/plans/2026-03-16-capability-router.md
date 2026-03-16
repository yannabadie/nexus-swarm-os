# CapabilityRouter — Model-Agnostic Swarm/HiveMind Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all hardcoded `["gemini", "claude"]` references in swarm/hivemind with a `CapabilityRouter` that maps task domains → semantic slots → any available provider.

**Architecture:** New `CapabilityRouter` class scores active providers against task domains using `AGENT_DOMAIN_STRENGTHS`, assigns them to semantic slots (`primary`, `secondary`, `critic`, `executor`). Phases receive `agents: dict[slot, driver]` — never provider IDs. `BasePhase` provides deprecated `gemini`/`claude` aliases for backward compat. `NegotiationProtocol` guards against empty registry.

**Tech Stack:** Python 3.11+, pytest, existing `UnifiedAgentRegistry`, `AGENT_DOMAIN_STRENGTHS`, `TaskAnalysis.domains`

---

## Chunk 1: CapabilityRouter core

**Files:**
- Create: `core/intelligence/swarm/capability_router.py`
- Create: `tests/test_capability_router.py`

### Task 1: Write failing tests for CapabilityRouter

- [ ] **Step 1: Create test file**

```python
# tests/test_capability_router.py
"""Tests for CapabilityRouter — model-agnostic slot assignment."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from core.intelligence.swarm.capability_router import (
    CapabilityRouter,
    SlotAssignment,
    SLOT_PRIMARY,
    SLOT_SECONDARY,
    SLOT_CRITIC,
    SLOT_EXECUTOR,
)
from core.intelligence.swarm.task_analyzer import TaskAnalysis, TaskDomain, TaskComplexity


def _make_registry(provider_ids: list[str]):
    """Build a minimal mock registry."""
    registry = MagicMock()
    registry.get_active_builtin_ids.return_value = provider_ids
    # get_driver returns a distinguishable mock per provider
    registry.get_driver.side_effect = lambda pid: MagicMock(name=f"driver_{pid}")
    return registry


def _make_analysis(domains: list[TaskDomain] | None = None) -> TaskAnalysis:
    return TaskAnalysis(
        raw_input="test",
        complexity=TaskComplexity.MODERATE,
        domains=domains or [TaskDomain.CODING],
        gemini_fit_score=0.5,
        claude_fit_score=0.5,
    )


class TestCapabilityRouterTwoProviders:
    def test_returns_four_slots(self):
        router = CapabilityRouter(_make_registry(["claude", "gemini"]))
        result = router.route(_make_analysis())
        assert set(result.keys()) == {SLOT_PRIMARY, SLOT_SECONDARY, SLOT_CRITIC, SLOT_EXECUTOR}

    def test_primary_and_secondary_are_drivers(self):
        router = CapabilityRouter(_make_registry(["claude", "gemini"]))
        result = router.route(_make_analysis())
        assert result[SLOT_PRIMARY] is not None
        assert result[SLOT_SECONDARY] is not None

    def test_coding_domain_selects_deepseek_or_claude_as_primary(self):
        """DeepSeek has highest coding score (0.88). If available, it leads."""
        router = CapabilityRouter(_make_registry(["deepseek", "gemini", "claude"]))
        result = router.route(_make_analysis([TaskDomain.CODING]))
        # Primary driver should be deepseek
        registry = router._registry
        primary_driver = result[SLOT_PRIMARY]
        # deepseek driver should be primary
        assert registry.get_driver.call_args_list[0][0][0] == "deepseek"

    def test_research_domain_selects_gemini_as_primary(self):
        """Gemini has highest research score (0.95)."""
        router = CapabilityRouter(_make_registry(["gemini", "claude", "openai"]))
        result = router.route(_make_analysis([TaskDomain.RESEARCH]))
        registry = router._registry
        # First driver call should be gemini
        first_call = registry.get_driver.call_args_list[0][0][0]
        assert first_call == "gemini"

    def test_primary_secondary_different_providers(self):
        """With 2+ providers, secondary should differ from primary."""
        router = CapabilityRouter(_make_registry(["claude", "gemini"]))
        result = router.route(_make_analysis())
        # Both slots use different drivers (different mock objects)
        assert result[SLOT_PRIMARY] is not result[SLOT_SECONDARY]


class TestCapabilityRouterSingleProvider:
    def test_single_provider_all_slots_same_driver(self):
        registry = _make_registry(["claude"])
        router = CapabilityRouter(registry)
        result = router.route(_make_analysis())
        # All slots map to the same driver instance
        drivers = list(result.values())
        assert all(d is drivers[0] for d in drivers)

    def test_single_provider_no_error(self):
        router = CapabilityRouter(_make_registry(["deepseek"]))
        result = router.route(_make_analysis())
        assert len(result) == 4


class TestCapabilityRouterEmptyRegistry:
    def test_empty_registry_raises(self):
        router = CapabilityRouter(_make_registry([]))
        with pytest.raises(RuntimeError, match="No providers registered"):
            router.route(_make_analysis())


class TestCapabilityRouterScoring:
    def test_score_assignment_dataclass(self):
        sa = SlotAssignment(slot=SLOT_PRIMARY, provider_id="claude", score=0.85)
        assert sa.slot == SLOT_PRIMARY
        assert sa.provider_id == "claude"
        assert sa.score == 0.85
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_capability_router.py -x --tb=short -q
```
Expected: `ImportError` or `ModuleNotFoundError` — `capability_router` doesn't exist yet.

---

### Task 2: Implement CapabilityRouter

- [ ] **Step 3: Create capability_router.py**

```python
# core/intelligence/swarm/capability_router.py
"""
CapabilityRouter — V12.4 Model-Agnostic Slot Assignment

Maps TaskAnalysis.domains → semantic slots → BaseAsyncDriver instances.
Phases receive agents: dict[SlotId, BaseAsyncDriver] — never provider IDs.

Slots:
  primary   — Lead: best provider for the task's primary domain
  secondary — Support: best different provider (anti-homogeneity)
  critic    — Adversarial: best at security/analysis (RED_BLUE, Diagnosis)
  executor  — Tool-heavy: best at coding/web_interaction
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.foundation.agents.unified_registry import UnifiedAgentRegistry
    from core.foundation.agents.unified_registry import BaseAsyncDriver
    from core.intelligence.swarm.task_analyzer import TaskAnalysis

from core.intelligence.swarm.task_analyzer import AGENT_DOMAIN_STRENGTHS

SLOT_PRIMARY = "primary"
SLOT_SECONDARY = "secondary"
SLOT_CRITIC = "critic"
SLOT_EXECUTOR = "executor"

ALL_SLOTS = (SLOT_PRIMARY, SLOT_SECONDARY, SLOT_CRITIC, SLOT_EXECUTOR)


@dataclass(frozen=True)
class SlotAssignment:
    """Scored provider assignment for a single slot."""
    slot: str
    provider_id: str
    score: float


class CapabilityRouter:
    """
    Assigns available providers to semantic slots based on task domains.

    Usage:
        router = CapabilityRouter(registry)
        agents = router.route(task_analysis)
        # agents = {"primary": driver_a, "secondary": driver_b, ...}
    """

    def __init__(self, registry: "UnifiedAgentRegistry") -> None:
        self._registry = registry

    def route(self, task: "TaskAnalysis") -> dict[str, "BaseAsyncDriver"]:
        """
        Assign providers to slots for the given task.

        Returns:
            dict mapping slot name → driver instance

        Raises:
            RuntimeError: If no providers are registered
        """
        available = self._registry.get_active_builtin_ids()
        if not available:
            raise RuntimeError(
                "No providers registered — cannot route. "
                "Register at least one driver via UnifiedAgentRegistry."
            )

        slot_to_provider = self._assign_slots(task, available)

        # Single-provider case: all slots → same driver
        if len(available) == 1:
            driver = self._registry.get_driver(available[0])
            return {slot: driver for slot in ALL_SLOTS}

        return {
            slot: self._registry.get_driver(pid)
            for slot, pid in slot_to_provider.items()
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _assign_slots(
        self, task: "TaskAnalysis", available: list[str]
    ) -> dict[str, str]:
        """Return {slot: provider_id} for each slot."""
        ranked = self._rank_by_task(task, available)

        primary = ranked[0]
        secondary = next(
            (p for p in ranked[1:] if p != primary),
            primary,  # fallback: same provider
        )
        critic = self._best_for_domain("security", available, exclude=primary) or secondary
        executor = self._best_for_domain("coding", available) or primary

        return {
            SLOT_PRIMARY: primary,
            SLOT_SECONDARY: secondary,
            SLOT_CRITIC: critic,
            SLOT_EXECUTOR: executor,
        }

    def _rank_by_task(self, task: "TaskAnalysis", available: list[str]) -> list[str]:
        """Rank providers by average score across task domains."""
        domain_names = [d.value for d in task.domains] if task.domains else ["general"]

        def _score(provider_id: str) -> float:
            strengths = AGENT_DOMAIN_STRENGTHS.get(provider_id, {})
            if not strengths:
                return 0.5  # unknown provider → neutral score
            total = 0.0
            for domain in domain_names:
                # AGENT_DOMAIN_STRENGTHS keys are TaskDomain enums, values are floats
                # Try direct string match first (for unknown domains), then enum match
                matched = next(
                    (v for k, v in strengths.items()
                     if (k.value if hasattr(k, "value") else k) == domain),
                    0.5,
                )
                total += matched
            return total / len(domain_names)

        return sorted(available, key=_score, reverse=True)

    def _best_for_domain(
        self,
        domain: str,
        available: list[str],
        exclude: str | None = None,
    ) -> str | None:
        """Return provider with highest score for a specific domain."""
        candidates = [p for p in available if p != exclude]
        if not candidates:
            return None

        def _domain_score(provider_id: str) -> float:
            strengths = AGENT_DOMAIN_STRENGTHS.get(provider_id, {})
            return next(
                (v for k, v in strengths.items()
                 if (k.value if hasattr(k, "value") else k) == domain),
                0.5,
            )

        return max(candidates, key=_domain_score)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_capability_router.py -x --tb=short -q
```
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add core/intelligence/swarm/capability_router.py tests/test_capability_router.py
git commit -m "feat(swarm): add CapabilityRouter — model-agnostic slot assignment"
```

---

## Chunk 2: Fix NegotiationProtocol + BasePhase

**Files:**
- Modify: `core/intelligence/swarm/negotiation_protocol.py` (line ~312)
- Create: `core/intelligence/hive_mind/base_phase.py`
- Modify: `tests/test_negotiation_protocol.py` (already partially fixed)

### Task 3: Fix negotiation_protocol.py hardcoded fallback

- [ ] **Step 1: Read current code**

```bash
grep -n "get_active_builtin_ids\|gemini.*claude\|claude.*gemini" \
  core/intelligence/swarm/negotiation_protocol.py
```

- [ ] **Step 2: Replace hardcoded fallback with guard**

In `core/intelligence/swarm/negotiation_protocol.py`, find:
```python
        # V12.4 Multi-provider: dynamic agent list from registry
        registry = get_registry()
        agents = registry.get_active_builtin_ids() or ["gemini", "claude"]
```

Replace with:
```python
        # V12.4 Multi-provider: dynamic agent list from registry
        registry = get_registry()
        agents = registry.get_active_builtin_ids()
        if not agents:
            # No providers registered → forced result with initial proposal
            return NegotiationResult(
                status=NegotiationStatus.FORCED,
                selected_mode=current_proposal.mode,
                agent_assignments=current_proposal.agent_assignments,
                negotiation_history=history,
                total_turns=0,
                consensus_confidence=current_proposal.confidence,
            )
```

- [ ] **Step 3: Run negotiation tests**

```bash
pytest tests/test_negotiation_protocol.py -x --tb=short -q
```
Expected: All 449 pass (the `get_active_builtin_ids.return_value = ["gemini", "claude"]` mock already in place from prior fix).

- [ ] **Step 4: Commit**

```bash
git add core/intelligence/swarm/negotiation_protocol.py
git commit -m "fix(swarm): remove hardcoded fallback in NegotiationProtocol — guard empty registry"
```

---

### Task 4: Create BasePhase with deprecated aliases

- [ ] **Step 1: Write test**

```python
# Add to tests/test_phase_architecture.py or a new test file
# tests/test_base_phase.py

import warnings
import pytest
from unittest.mock import MagicMock

from core.intelligence.hive_mind.base_phase import BasePhase


class ConcretePhase(BasePhase):
    pass


class TestBasePhase:
    def test_agents_dict_stored(self):
        d = MagicMock()
        phase = ConcretePhase(agents={"primary": d})
        assert phase.agents == {"primary": d}

    def test_gemini_alias_deprecated(self):
        d = MagicMock()
        phase = ConcretePhase(agents={"primary": d})
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = phase.gemini
            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert "primary" in str(w[0].message)
        assert result is d

    def test_claude_alias_deprecated(self):
        d = MagicMock()
        phase = ConcretePhase(agents={"secondary": d})
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = phase.claude
            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
        assert result is d

    def test_empty_agents_aliases_return_none(self):
        phase = ConcretePhase(agents={})
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            assert phase.gemini is None
            assert phase.claude is None
```

- [ ] **Step 2: Run test to see it fail**

```bash
pytest tests/test_base_phase.py -x --tb=short -q
```
Expected: `ImportError`

- [ ] **Step 3: Create base_phase.py**

```python
# core/intelligence/hive_mind/base_phase.py
"""
BasePhase — V12.4 Model-Agnostic Phase Base Class

All HiveMind phases extend this class. Provides:
- agents: dict[str, BaseAsyncDriver]  — keyed by semantic slot
- Deprecated .gemini / .claude properties for backward compat

Slot conventions (set by CapabilityRouter):
  "primary"   — lead analytical provider
  "secondary" — support / alternation
  "critic"    — adversarial / diagnosis
  "executor"  — tool-heavy / coding

Backward compat:
  self.gemini  → self.agents.get("primary") or self.agents.get("gemini")
  self.claude  → self.agents.get("secondary") or self.agents.get("claude")
"""
from __future__ import annotations

import warnings
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.foundation.agents.unified_registry import BaseAsyncDriver


class BasePhase:
    """
    Base class for all HiveMind phases.

    Subclasses receive agents keyed by semantic slot.
    The deprecated .gemini and .claude attributes remain available
    for one migration cycle, then will be removed.
    """

    def __init__(
        self,
        *,
        agents: dict[str, "BaseAsyncDriver"] | None = None,
    ) -> None:
        self.agents: dict[str, "BaseAsyncDriver"] = agents or {}

    # ------------------------------------------------------------------
    # Deprecated backward-compat aliases
    # ------------------------------------------------------------------

    @property
    def gemini(self) -> "BaseAsyncDriver | None":
        """
        Deprecated. Use self.agents["primary"] instead.

        Maps to: agents["primary"] → agents["gemini"] → None
        """
        warnings.warn(
            "self.gemini is deprecated since V12.4 — use self.agents['primary']",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.agents.get("primary") or self.agents.get("gemini")

    @gemini.setter
    def gemini(self, value: "BaseAsyncDriver | None") -> None:
        """Setter kept for legacy __init__ assignments in subclasses."""
        if value is not None:
            self.agents["gemini"] = value

    @property
    def claude(self) -> "BaseAsyncDriver | None":
        """
        Deprecated. Use self.agents["secondary"] instead.

        Maps to: agents["secondary"] → agents["claude"] → None
        """
        warnings.warn(
            "self.claude is deprecated since V12.4 — use self.agents['secondary']",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.agents.get("secondary") or self.agents.get("claude")

    @claude.setter
    def claude(self, value: "BaseAsyncDriver | None") -> None:
        """Setter kept for legacy __init__ assignments in subclasses."""
        if value is not None:
            self.agents["claude"] = value
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_base_phase.py -x --tb=short -q
```
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add core/intelligence/hive_mind/base_phase.py tests/test_base_phase.py
git commit -m "feat(hivemind): add BasePhase with deprecated gemini/claude aliases"
```

---

## Chunk 3: Wire CapabilityRouter into HiveMind phases

**Files:**
- Modify: `core/intelligence/hive_mind/phases/phase_analysis.py`
- Modify: `core/intelligence/hive_mind/phases/phase_debate.py`
- Modify: `core/intelligence/hive_mind/phases/phase_architecture.py`
- Modify: `core/intelligence/hive_mind/phases/phase_consolidation.py`
- Modify: `core/intelligence/hive_mind/phases/phase_diagnosis.py`
- Modify: `core/intelligence/hive_mind/phases/phase_execution.py`

**Pattern to apply to each phase** (identical for all 6):

The phases already have the `agents: dict` kwarg and the backward compat code from the in-progress migration. We need to:
1. Import `BasePhase` and add it as a parent class
2. Remove the duplicated `self.gemini = ...` / `self.claude = ...` assignments (now handled by `BasePhase.gemini.setter`)

### Task 5: Update phase_analysis.py

- [ ] **Step 1: Read current __init__**

```bash
grep -n "class IndependentAnalysisPhase\|def __init__\|self\.gemini\|self\.claude\|self\.agents\|BasePhase" \
  core/intelligence/hive_mind/phases/phase_analysis.py | head -20
```

- [ ] **Step 2: Apply pattern**

At top of file, add import:
```python
from core.intelligence.hive_mind.base_phase import BasePhase
```

Change class declaration:
```python
class IndependentAnalysisPhase(BasePhase):
```

In `__init__`, replace the current agents/backward-compat block:
```python
        # V12.4: N-agent support — delegate to BasePhase
        if agents is not None:
            super().__init__(agents=agents)
        else:
            _agents: dict = {}
            if gemini_driver is not None:
                _agents["gemini"] = gemini_driver
            if claude_driver is not None:
                _agents["claude"] = claude_driver
            super().__init__(agents=_agents)
        self.agent_ids = list(self.agents.keys())
        # Remove self.gemini = ... and self.claude = ... lines — now in BasePhase
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/test_phase_analysis.py -x --tb=short -q 2>/dev/null || \
pytest tests/ -k "phase_analysis" -x --tb=short -q
```

- [ ] **Step 4: Commit**

```bash
git add core/intelligence/hive_mind/phases/phase_analysis.py
git commit -m "refactor(hivemind): phase_analysis extends BasePhase"
```

### Task 6: Update remaining 5 phases

Apply the same pattern (Tasks 5 steps 1-4) to:
- `core/intelligence/hive_mind/phases/phase_debate.py` → `class StrategicDebatePhase(BasePhase)`
- `core/intelligence/hive_mind/phases/phase_architecture.py` → `class ArchitectureGenerationPhase(BasePhase)`
- `core/intelligence/hive_mind/phases/phase_consolidation.py` → `class ConsolidationPhase(BasePhase)` (or whatever its class name is)
- `core/intelligence/hive_mind/phases/phase_diagnosis.py` → `class FailureDiagnosisPhase(BasePhase)` (or whatever)
- `core/intelligence/hive_mind/phases/phase_execution.py` → `class MonitoredExecutionPhase(BasePhase)` (or whatever)

For each:
1. Add `from core.intelligence.hive_mind.base_phase import BasePhase`
2. Add `(BasePhase)` to class declaration
3. Replace agents/compat block with `super().__init__(agents=...)` pattern
4. Remove `self.gemini = ...` / `self.claude = ...` direct assignments

- [ ] **Step 1: Apply to phase_debate.py and run tests**

```bash
pytest tests/test_negotiation_protocol.py tests/test_phase_architecture.py -x --tb=short -q
```

- [ ] **Step 2: Apply to remaining 4 phases and run tests**

```bash
pytest tests/ -x --tb=short -q 2>&1 | tail -10
```

- [ ] **Step 3: Commit all 5 phases**

```bash
git add core/intelligence/hive_mind/phases/
git commit -m "refactor(hivemind): all phases extend BasePhase — N-agent clean migration"
```

---

## Chunk 4: HybridSwarmEngine mode degradation + CapabilityRouter integration

**Files:**
- Modify: `core/intelligence/swarm/hybrid_swarm_engine.py`
- Modify: `core/intelligence/hive_mind/orchestrator.py`

### Task 7: Mode degradation for 1-provider

- [ ] **Step 1: Read HybridSwarmEngine.process_task**

```bash
grep -n "process_task\|selected_mode\|CollaborationMode\|available\|builtin_ids" \
  core/intelligence/swarm/hybrid_swarm_engine.py | head -30
```

- [ ] **Step 2: Add single-provider mode degradation**

After mode selection, before execution, add:
```python
# V12.4: Graceful degradation — multi-agent modes require 2+ providers
available_providers = registry.get_active_builtin_ids()
if len(available_providers) <= 1:
    multi_agent_modes = {
        CollaborationMode.PARALLEL,
        CollaborationMode.LEAD_SUPPORT,
        CollaborationMode.PING_PONG,
        CollaborationMode.RED_BLUE,
    }
    if selected_mode in multi_agent_modes:
        logger.info(
            f"Single provider detected — degrading {selected_mode.value} → SPECIALIST"
        )
        selected_mode = CollaborationMode.SPECIALIST
```

- [ ] **Step 3: Wire CapabilityRouter in orchestrator**

In `core/intelligence/hive_mind/orchestrator.py`, find `__init__` and add:
```python
from core.intelligence.swarm.capability_router import CapabilityRouter

# After self.agents is populated:
self._capability_router = CapabilityRouter(self.agent_registry_or_unified_registry)
```

In `_init_phases()`, replace `agents=self.agents` with router output:
```python
routed_agents = self._route_agents_for_phase()
# pass routed_agents to each phase
```

Add helper:
```python
def _route_agents_for_phase(self) -> dict[str, "BaseAsyncDriver"]:
    """Route available providers to semantic slots."""
    try:
        # Use a default analysis (no task yet at phase init time)
        # Phases will re-route per-task in future iterations
        from core.intelligence.swarm.task_analyzer import TaskAnalysis, TaskDomain, TaskComplexity
        dummy = TaskAnalysis(
            raw_input="",
            complexity=TaskComplexity.MODERATE,
            domains=[TaskDomain.GENERAL],
            gemini_fit_score=0.5,
            claude_fit_score=0.5,
        )
        return self._capability_router.route(dummy)
    except RuntimeError:
        # No providers registered yet — return existing agents dict
        return self.agents
```

- [ ] **Step 4: Run full test suite**

```bash
pytest tests/ -x --tb=short -q 2>&1 | tail -20
```
Expected: All pass (or isolate any regressions).

- [ ] **Step 5: Commit**

```bash
git add core/intelligence/swarm/hybrid_swarm_engine.py \
        core/intelligence/hive_mind/orchestrator.py
git commit -m "feat(swarm/hivemind): CapabilityRouter integration + single-provider mode degradation"
```

---

## Chunk 5: Full test suite + cleanup

### Task 8: Verify all 14 original modified files are clean

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/ --tb=short -q 2>&1 | tail -20
```
Expected: All pass, 0 failures.

- [ ] **Step 2: Check no hardcoded ["gemini", "claude"] remain in production code**

```bash
grep -rn '"gemini", "claude"\|"claude", "gemini"' \
  core/intelligence/swarm/ core/intelligence/hive_mind/ \
  --include="*.py" | grep -v "test_\|#"
```
Expected: 0 results.

- [ ] **Step 3: Verify tests use generic or properly mocked IDs**

```bash
grep -n 'get_active_builtin_ids.return_value' tests/ -r
```
Should show only properly configured mocks (no bare MagicMock()).

- [ ] **Step 4: Update SESSION_CONTINUITY.md**

Update `docs/sessions/SESSION_CONTINUITY.md` with:
- Current branch state
- CapabilityRouter added
- BasePhase added
- All 14 files committed

- [ ] **Step 5: Final commit**

```bash
git add docs/sessions/SESSION_CONTINUITY.md
git commit -m "docs: update session continuity — CapabilityRouter migration complete"
```

---

## Execution Notes

### Key invariants to preserve
- `AGENT_DOMAIN_STRENGTHS` remains static (EMA is v13 work)
- `TaskAnalysis.gemini_fit_score` / `claude_fit_score` NOT changed (25+ usages, YAGNI)
- All existing tests must pass
- No `--no-verify` flags

### Test commands
```bash
# Targeted (fast)
pytest tests/test_capability_router.py tests/test_base_phase.py \
       tests/test_negotiation_protocol.py tests/test_phase_architecture.py \
       tests/test_task_analyzer.py -v --tb=short

# Full suite
pytest tests/ --tb=short -q
```

### Verification after each chunk
```bash
pytest tests/ -x --tb=short -q 2>&1 | tail -5
```
