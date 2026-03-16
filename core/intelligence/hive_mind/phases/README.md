# NEXUS HiveMind Phases Module

## Synopsis

The **phases** module contains the implementation of each of the 7 HiveMind pipeline phases. Each phase is a standalone module that handles a specific stage of the collaborative intelligence pipeline.

## Architecture

```
+-------------------------------------------------------------------------+
|                    HIVEMIND 7-PHASE PIPELINE                             |
+-------------------------------------------------------------------------+
|                                                                          |
|  Phase 1          Phase 2          Phase 3          Phase 4             |
|  +---------+      +---------+      +---------+      +---------+         |
|  |ANALYSIS |----->| DEBATE  |----->|ARCHITECT|----->|EXECUTION|         |
|  |         |      |         |      |         |      |         |         |
|  +---------+      +---------+      +---------+      +----+----+         |
|                                                          |              |
|                                         +----------------+              |
|                                         |                               |
|  Phase 7          Phase 6          Phase 5                              |
|  +---------+      +---------+      +---------+                          |
|  |CONSOLID.|<-----|  RETRY  |<-----|DIAGNOSIS|                          |
|  |         |      |         |      |         |                          |
|  +---------+      +---------+      +---------+                          |
|                                                                          |
+-------------------------------------------------------------------------+
```

## Component Map

| File | Phase | Purpose |
|------|-------|---------|
| `phase_analysis.py` | 1 | Independent analysis by both agents |
| `phase_debate.py` | 2 | Resolve disagreements via debate |
| `phase_architecture.py` | 3 | Design execution plan and agent topology |
| `phase_execution.py` | 4 | Monitored execution with SwarmBridge |
| `phase_diagnosis.py` | 5 | Failure root cause analysis |
| `phase_retry.py` | 6 | Adaptive retry decision |
| `phase_consolidation.py` | 7 | Knowledge archival and retention |

## Phase Interfaces

Each phase follows a common interface:

```python
class PhaseHandler(Protocol):
    """Common interface for phase handlers."""

    async def execute(
        self,
        context: HiveContext,
        previous_result: Optional[PhaseResult]
    ) -> PhaseResult

    def get_states(self) -> List[HiveMindState]
    def can_skip(self, context: HiveContext) -> bool
```

## Phase Details

### Phase 1: Analysis
```python
class AnalysisPhase:
    """Independent analysis by both agents."""

    async def analyze_gemini(self, task: str) -> IndependentAnalysis
    async def analyze_claude(self, task: str) -> IndependentAnalysis
    async def compare(self, g: IndependentAnalysis, c: IndependentAnalysis) -> AnalysisComparison
```

### Phase 2: Debate
```python
class DebatePhase:
    """Structured argumentation to resolve disagreements."""

    async def debate(
        self,
        disagreements: List[Disagreement],
        max_turns: int
    ) -> DebateResult
```

### Phase 3: Architecture
```python
class ArchitecturePhase:
    """Design execution plan."""

    async def design(
        self,
        analysis: AnalysisComparison,
        debate_result: Optional[DebateResult]
    ) -> AgentArchitecture
```

### Phase 4: Execution
```python
class ExecutionPhase:
    """Monitored execution with SwarmBridge."""

    async def execute_step(
        self,
        step: ExecutionStep,
        context: ExecutionContext
    ) -> MonitoredStepResult
```

### Phase 5: Diagnosis
```python
class DiagnosisPhase:
    """Failure analysis."""

    async def diagnose(
        self,
        failure: ExecutionFailure,
        context: HiveContext
    ) -> FailureDiagnosis
```

### Phase 6: Retry
```python
class RetryPhase:
    """Adaptive retry decision."""

    async def decide(
        self,
        diagnosis: FailureDiagnosis,
        attempt_count: int
    ) -> RetryDecision  # RETRY, STOP, ESCALATE
```

### Phase 7: Consolidation
```python
class ConsolidationPhase:
    """Knowledge archival."""

    async def consolidate(
        self,
        result: HiveResult,
        context: HiveContext
    ) -> KnowledgeConsolidation
```

## Usage

```python
from core.intelligence.hive_mind.phases import (
    AnalysisPhase,
    DebatePhase,
    ArchitecturePhase,
    ExecutionPhase
)

# Phases are typically called by TrueHiveMind orchestrator
analysis = await AnalysisPhase().execute(context, None)
debate = await DebatePhase().execute(context, analysis)
arch = await ArchitecturePhase().execute(context, debate)
execution = await ExecutionPhase().execute(context, arch)
```

## Dependencies

### Internal
- `core.hive_mind.types` - Phase dataclasses
- `core.drivers` - Agent invocation
- `core.swarm` - SwarmBridge delegation

## Version History

- **V8.0** - Initial 7-phase implementation
- **V8.3** - SwarmBridge integration in Phase 4
- **V12.4** - Adaptive debate turns, enhanced diagnosis
