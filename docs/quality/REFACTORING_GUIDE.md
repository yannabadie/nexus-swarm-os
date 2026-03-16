# NEXUS V12.4 Refactoring Guide

**Companion to**: CODE_QUALITY_REVIEW_2026-02-24.md
**Purpose**: Practical refactoring patterns and scripts

---

## Quick Reference: Anti-Patterns -> Solutions

| Anti-Pattern | Files Affected | Solution | Effort |
|--------------|----------------|----------|--------|
| Print statements | 142 occurrences | Replace with `logger.info()` | 2h |
| Global singletons | 106 occurrences | Dependency Injection via `ServiceFactory` | 12h |
| God Objects | 21 classes | Extract Class refactoring | 16h |
| Long functions | 239 functions | Extract Method refactoring | 8h |
| Missing type hints | 51 functions | Add return type annotations | 2h |
| Missing docstrings | 284 APIs | Add Google-style docstrings | 4h |
| Classes vs Dataclasses | 79 classes | Convert to `@dataclass` | 6h |

---

## 1. Replace Print Statements (P0 - 2 hours)

### Automated Script

```bash
#!/bin/bash
# replace_prints.sh

# Backup first
git stash

# Replace print() with logger.info()
find core/intelligence core/execution_pkg core/metagraph -name "*.py" | while read file; do
    # Skip if already imports logging
    if ! grep -q "^import logging" "$file"; then
        # Add logging import after first docstring
        sed -i '1 a\import logging\nlogger = logging.getLogger(__name__)' "$file"
    fi

    # Replace print(f"...") with logger.info(f"...")
    sed -i 's/print(f"/logger.info(f"/g' "$file"

    # Replace print("...") with logger.info("...")
    sed -i 's/print("/logger.info("/g' "$file"

    # Replace print(...) with logger.info(...)
    sed -i 's/print(/logger.info(/g' "$file"
done

# Verify changes
git diff core/intelligence/evolution/evaluator.py | head -20

# If good, commit
# git add .
# git commit -m "refactor(V12.4): Replace print statements with logging (142 fixes)"
```

### Manual Review Checklist

After running script, manually review:
- [ ] Debug prints -> `logger.debug()`
- [ ] Error messages -> `logger.error()`
- [ ] User-facing output -> Keep as `print()` (e.g., REPL responses)

---

## 2. Add Missing Return Types (P0 - 2 hours)

### Pattern: `record_*()` Methods

```python
# Before
def record_evolution(self, child_count: int, parent_id: str):
    self._history.append({"count": child_count, "parent": parent_id})

# After
def record_evolution(self, child_count: int, parent_id: str) -> None:
    self._history.append({"count": child_count, "parent": parent_id})
```

### Files to Fix (Top 10)

1. `core/intelligence/evolution/rate_limiter.py`
   - `record_evolution()` -> `-> None`
   - `reset_daily()` -> `-> None`

2. `core/intelligence/hive_mind/context_manager.py`
   - `add_item()` -> `-> None`
   - `clear()` -> `-> None`

3. `core/intelligence/swarm/agent_metrics.py`
   - `record_usage()` -> `-> None`
   - `update_importance()` -> `-> None`

### Automated Fix

```bash
# Add return type hints to common patterns
python3 << 'EOF'
import re
import sys

patterns = [
    (r'def (record_\w+)\(([^)]+)\):', r'def \1(\2) -> None:'),
    (r'def (update_\w+)\(([^)]+)\):', r'def \1(\2) -> None:'),
    (r'def (add_\w+)\(([^)]+)\):', r'def \1(\2) -> None:'),
    (r'def (clear|reset)\(self\):', r'def \1(self) -> None:'),
]

for filepath in sys.argv[1:]:
    with open(filepath, 'r') as f:
        content = f.read()

    for pattern, replacement in patterns:
        content = re.sub(pattern, replacement, content)

    with open(filepath, 'w') as f:
        f.write(content)
EOF
```

---

## 3. Decompose God Objects (P0/P1 - 16 hours)

### Example: `TrueHiveMind` (1201 lines -> 4 classes)

#### Step 1: Extract StateManager

```python
# NEW FILE: core/intelligence/hive_mind/state_manager.py

from enum import Enum
from typing import Callable, Optional

class HiveMindStateManager:
    """Manages state transitions for Hive Mind pipeline."""

    def __init__(
        self,
        on_state_change: Optional[Callable] = None
    ):
        self._state = HiveMindState.HIVE_GATING
        self._on_state_change = on_state_change

    def transition_to(self, new_state: HiveMindState) -> None:
        """Transition to new state with notification."""
        old_state = self._state
        self._state = new_state

        if self._on_state_change:
            self._on_state_change(old_state, new_state)

    @property
    def current_state(self) -> HiveMindState:
        return self._state
```

#### Step 2: Extract PhaseCoordinator

```python
# NEW FILE: core/intelligence/hive_mind/phase_coordinator_v2.py

from dataclasses import dataclass
from typing import Dict, List

@dataclass
class PhaseMetrics:
    phase_name: str
    duration_seconds: float
    tokens_used: int
    success: bool

class PhaseCoordinator:
    """Coordinates phase execution and tracks metrics."""

    def __init__(self):
        self._phase_history: List[PhaseMetrics] = []

    def record_phase(
        self,
        phase_name: str,
        duration: float,
        tokens: int,
        success: bool
    ) -> None:
        self._phase_history.append(
            PhaseMetrics(phase_name, duration, tokens, success)
        )

    def get_summary(self) -> Dict:
        return {
            "total_phases": len(self._phase_history),
            "total_duration": sum(p.duration_seconds for p in self._phase_history),
            "total_tokens": sum(p.tokens_used for p in self._phase_history),
        }
```

#### Step 3: Refactor `TrueHiveMind.__init__`

```python
# UPDATED: core/intelligence/hive_mind/orchestrator.py

from .state_manager import HiveMindStateManager
from .phase_coordinator_v2 import PhaseCoordinator

class TrueHiveMind:
    def __init__(self, ...):
        # OLD: self.state = HiveMindState.HIVE_GATING
        # NEW:
        self._state_manager = HiveMindStateManager(on_state_change)
        self._phase_coordinator = PhaseCoordinator()

        # ... rest of init
```

#### Step 4: Update state transitions

```python
# OLD:
self._set_state(HiveMindState.HIVE_ANALYZING_GEMINI)

# NEW:
self._state_manager.transition_to(HiveMindState.HIVE_ANALYZING_GEMINI)
```

**Benefits**:
- Reduces `TrueHiveMind` from 1201 -> ~800 lines
- Improves testability (mock `StateManager`)
- Single Responsibility Principle

---

## 4. Refactor Global Singletons (P1 - 12 hours)

### Anti-Pattern: Global Singleton

```python
# CURRENT: core/intelligence/evolution/mutation_tracker.py

_tracker = None

def get_mutation_tracker():
    global _tracker
    if _tracker is None:
        _tracker = MutationTracker()
    return _tracker
```

**Problems**:
1. Single global instance (can't have multiple NEXUS instances)
2. State persists between tests
3. Tight coupling (hard to swap implementations)

### Solution: Dependency Injection

```python
# NEW: Use ServiceFactory (V10 PRISM pattern)

from core.execution_pkg.context import get_current_session_or_none
from core.execution_pkg.factory import ServiceFactory

def get_mutation_tracker() -> MutationTracker:
    """
    Get mutation tracker for current tenant context.

    V10 PRISM: Returns tenant-scoped instance.
    Falls back to global singleton in legacy mode.
    """
    # V10: Try ServiceFactory first (tenant-scoped)
    try:
        if get_current_session_or_none():
            return ServiceFactory.get_mutation_tracker()
    except ImportError:
        pass

    # Legacy fallback
    global _tracker
    if _tracker is None:
        _tracker = MutationTracker()
    return _tracker
```

### Files to Refactor (53 singletons)

Use this pattern for:
- `get_mutation_tracker()` -> `ServiceFactory.get_mutation_tracker()`
- `get_strategy_tracker()` -> `ServiceFactory.get_strategy_tracker()`
- `get_budget_allocator()` -> `ServiceFactory.get_budget_allocator()`
- `get_consensus_tracker()` -> `ServiceFactory.get_consensus_tracker()`
- `get_echo_chamber_guard()` -> `ServiceFactory.get_echo_chamber_guard()`
- ... (and 48 more)

**Effort**: 15 minutes per singleton × 53 = ~13 hours

---

## 5. Convert to @dataclass (P2 - 6 hours)

### Pattern: Simple Init -> Dataclass

```python
# BEFORE (79 classes like this)
class EvolutionManager:
    def __init__(
        self,
        workspace_path: Path,
        nexus_root: Path,
        config: Any,
        orchestrator: Any,
        rate_limiter: Optional[EvolutionRateLimiter] = None,
    ):
        self.workspace_path = workspace_path
        self.nexus_root = nexus_root
        self.config = config
        self.orchestrator = orchestrator
        self.rate_limiter = rate_limiter or EvolutionRateLimiter(...)

# AFTER (recommended)
from dataclasses import dataclass, field

@dataclass
class EvolutionManager:
    workspace_path: Path
    nexus_root: Path
    config: Any
    orchestrator: Any
    rate_limiter: Optional[EvolutionRateLimiter] = None

    def __post_init__(self):
        if self.rate_limiter is None:
            self.rate_limiter = EvolutionRateLimiter(
                self.workspace_path, self.config
            )
```

**Benefits**:
- Reduces 15 lines -> 10 lines (30% reduction)
- Auto-generates `__repr__`, `__eq__`, `__hash__`
- Improves type safety (mypy catches field mismatches)

### Candidates (Top 10)

1. `EvolutionManager` (evolution/manager.py)
2. `TieredValidator` (evolution/tiered_validator.py)
3. `ChildValidator` (evolution/validator.py)
4. `AgentReaper` (evolution/agent_reaper.py)
5. `AutoSpecializer` (evolution/auto_specializer.py)
6. `DeterministicFitness` (evolution/fitness.py)
7. `MutationTracker` (evolution/mutation_tracker.py)
8. `BrainstormPhase` (evolution/phases/brainstorm.py)
9. `CreatePhase` (evolution/phases/create.py)
10. `PromotePhase` (evolution/phases/promote.py)

---

## 6. Extract Long Functions (P2 - 8 hours)

### Example: `process_task()` (770 lines -> 8 methods)

```python
# BEFORE: All in one method
async def process_task(self, task: str) -> HiveMindResult:
    # ... 770 lines of logic

# AFTER: Extracted methods
async def process_task(self, task: str) -> HiveMindResult:
    start_time = time.time()

    # Phase 1: Analysis
    analysis_result = await self._run_analysis_phase(task)
    if not analysis_result.success:
        return self._create_failed_result(...)

    # Phase 2: Debate (if needed)
    debate_result = await self._run_debate_phase(task, analysis_result)

    # Phase 3: Architecture
    arch_result = await self._run_architecture_phase(task, debate_result)

    # Phase 4-6: Execution Loop
    execution_result = await self._run_execution_loop(task, arch_result)

    # Phase 7: Consolidation
    consolidation_result = await self._run_consolidation_phase(
        task, execution_result
    )

    return self._create_success_result(
        start_time, execution_result, consolidation_result
    )

# NEW: Extracted method example
async def _run_analysis_phase(
    self,
    task: str
) -> AnalysisPhaseResult:
    """Run Phase 1: Independent Analysis."""
    self._state_manager.transition_to(HiveMindState.HIVE_ANALYZING_GEMINI)

    result = await self.phase_analysis.execute(task)
    self._phase_coordinator.record_phase(
        "analysis",
        duration=result.duration,
        tokens=result.tokens_used,
        success=result.success
    )

    return result
```

**Benefits**:
- Reduces cognitive load (8 small functions vs 1 giant function)
- Improves testability (test each phase independently)
- Better error handling (localized try/except)

---

## 7. Add Docstrings (P2 - 4 hours)

### Templates

#### Template 1: Simple Method

```python
def record_evolution(self, child_count: int, parent_id: str) -> None:
    """Record an evolution event to history."""
    self._history.append({"count": child_count, "parent": parent_id})
```

#### Template 2: Complex Method

```python
def evaluate_fitness(
    self,
    children: List[str],
    parent_id: str,
) -> List[EvaluationResult]:
    """
    Evaluate fitness of validated children.

    Args:
        children: List of child IDs to evaluate
        parent_id: Parent ID for comparison

    Returns:
        List of EvaluationResult for each child

    Raises:
        ValueError: If parent_id not found
    """
    # ... implementation
```

#### Template 3: Class Docstring

```python
class EvolutionManager:
    """
    Central orchestrator for evolution operations.

    Coordinates:
    - Brainstorming: AI-driven mutation proposals
    - Child Creation: Applying mutations
    - Validation: Tiered validation pipeline
    - Evaluation: Fitness scoring
    - Promotion: Winner selection

    Example:
        >>> manager = EvolutionManager(workspace, nexus_root, config, orchestrator)
        >>> result = manager.run_evolution_cycle(child_count=3)
        >>> if result.success:
        ...     print(f"Winner: {result.winner_id}")
    """
```

---

## 8. Reduce Deep Nesting (P3 - 4 hours)

### Anti-Pattern: Nested Conditionals

```python
# BEFORE (depth 5)
def get_status(self) -> EvolutionStatus:
    if self.children_path.exists():
        for child_dir in self.children_path.iterdir():
            if child_dir.is_dir():
                status_file = child_dir / "status.json"
                if status_file.exists():
                    status = json.loads(status_file.read_text())
                    if status.get("status") == "pending":
                        pending_children += 1
```

### Solution: Guard Clauses + Early Returns

```python
# AFTER (depth 2)
def get_status(self) -> EvolutionStatus:
    if not self.children_path.exists():
        return self._create_empty_status()

    pending_children = 0
    for child_dir in self.children_path.iterdir():
        if not child_dir.is_dir():
            continue

        pending_children += self._count_pending_in_dir(child_dir)

    return self._create_status_with_count(pending_children)

def _count_pending_in_dir(self, child_dir: Path) -> int:
    """Count pending children in directory."""
    status_file = child_dir / "status.json"
    if not status_file.exists():
        return 0

    status = json.loads(status_file.read_text())
    return 1 if status.get("status") == "pending" else 0
```

**Benefits**:
- Reduces nesting from 5 -> 2 levels
- Easier to read (flat flow)
- Easier to test (`_count_pending_in_dir` is isolated)

---

## 9. Automated Code Quality Tools

### Setup Pre-Commit Hooks

```bash
# Install pre-commit
pip install pre-commit

# Create .pre-commit-config.yaml
cat > .pre-commit-config.yaml << 'EOF'
repos:
  - repo: https://github.com/psf/black
    rev: 24.2.0
    hooks:
      - id: black
        language_version: python3.11

  - repo: https://github.com/PyCQA/flake8
    rev: 7.0.0
    hooks:
      - id: flake8
        args: [--max-line-length=120]

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.8.0
    hooks:
      - id: mypy
        args: [--ignore-missing-imports]

  - repo: https://github.com/PyCQA/bandit
    rev: 1.7.7
    hooks:
      - id: bandit
        args: [-ll, -r, core/]
EOF

# Install hooks
pre-commit install

# Run on all files
pre-commit run --all-files
```

---

## 10. Refactoring Checklist

Use this checklist for each refactoring task:

### Before Refactoring
- [ ] Read existing tests (understand behavior)
- [ ] Create feature branch (`git checkout -b refactor/component-name`)
- [ ] Run tests to establish baseline (`pytest tests/`)
- [ ] Backup complex files (`cp file.py file.py.bak`)

### During Refactoring
- [ ] Make small, incremental changes
- [ ] Run tests after each change
- [ ] Keep commits atomic (one logical change per commit)
- [ ] Update docstrings as you refactor

### After Refactoring
- [ ] Run full test suite (`pytest tests/`)
- [ ] Check type hints (`mypy core/`)
- [ ] Check linting (`ruff check core/`)
- [ ] Update relevant documentation
- [ ] Create PR with before/after metrics

---

## 11. Metrics to Track

Track these metrics before and after refactoring:

```bash
# Line count
find core/intelligence -name "*.py" | xargs wc -l | tail -1

# Function length distribution
python3 << 'EOF'
import ast
import sys
from pathlib import Path

lengths = []
for file in Path("core/intelligence").rglob("*.py"):
    tree = ast.parse(file.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if hasattr(node, 'end_lineno'):
                lengths.append(node.end_lineno - node.lineno)

print(f"Functions: {len(lengths)}")
print(f"Average: {sum(lengths)/len(lengths):.1f} lines")
print(f"Max: {max(lengths)} lines")
print(f"Functions >50 lines: {sum(1 for l in lengths if l > 50)}")
EOF

# Type hint coverage
mypy core/intelligence --strict --show-column-numbers 2>&1 | grep "error:" | wc -l

# Docstring coverage
interrogate -v core/intelligence
```

---

## 12. Example Refactoring PR Template

```markdown
## Refactoring: Decompose TrueHiveMind God Object

### Summary
Extracts `StateManager` and `PhaseCoordinator` from `TrueHiveMind` to reduce class size from 1201 -> 780 lines.

### Changes
- **NEW**: `core/intelligence/hive_mind/state_manager.py` (85 lines)
- **NEW**: `core/intelligence/hive_mind/phase_coordinator_v2.py` (120 lines)
- **MODIFIED**: `core/intelligence/hive_mind/orchestrator.py` (-216 lines)

### Metrics
| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Class Size | 1201 lines | 780 lines | -35% |
| Methods | 25 | 18 | -28% |
| Complexity | 0.063 | 0.045 | -29% |

### Testing
- [x] All existing tests pass (`pytest tests/`)
- [x] New unit tests for `StateManager`
- [x] New unit tests for `PhaseCoordinator`
- [x] Integration test for `TrueHiveMind` unchanged

### Migration Guide
No breaking changes. `TrueHiveMind` API remains identical.

Internal usage:
```python
# OLD: self.state = HiveMindState.HIVE_ANALYZING
# NEW: self._state_manager.transition_to(HiveMindState.HIVE_ANALYZING)
```
```

---

## 13. References

- **Martin Fowler - Refactoring**: https://refactoring.com/
- **Python Patterns**: https://python-patterns.guide/
- **Google Python Style Guide**: https://google.github.io/styleguide/pyguide.html
- **PEP 8**: https://peps.python.org/pep-0008/
- **Clean Code (Robert C. Martin)**: Chapters 3 (Functions), 10 (Classes)

---

**Generated by**: Claude Sonnet 4.5
**Date**: 2026-02-24
**Next Update**: After P0-P1 refactoring (est. 2026-03-08)
