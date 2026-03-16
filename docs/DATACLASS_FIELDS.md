# NEXUS V8.0 - Dataclass Field Reference

**Purpose**: Exact field definitions to prevent LLM hallucinations.
**Last Updated**: 2025-12-08
**Version**: 1.0

---

## CRITICAL: Commonly Confused Dataclasses

### TaskAnalysis vs IndependentAnalysis

| Field | TaskAnalysis | IndependentAnalysis |
|-------|--------------|---------------------|
| Location | `swarm/task_analyzer.py:159` | `hive_mind/types.py:104` |
| Domain | Swarm routing | HiveMind phases |
| complexity | `TaskComplexity` (IntEnum) | `str` (free text) |
| reasoning | **DOES NOT EXIST** | **EXISTS** |
| confidence | `float = 0.5` | `float` (required) |
| domains | `List[TaskDomain]` | N/A |

### ModeProposal Field Names

| CORRECT | WRONG (hallucination) |
|---------|----------------------|
| `mode` | ~~recommended_mode~~ |
| `mode` | ~~suggested_mode~~ |

---

## 1. SWARM DOMAIN

### TaskAnalysis (`swarm/task_analyzer.py:159`)

```python
@dataclass
class TaskAnalysis:
    # REQUIRED fields
    complexity: TaskComplexity          # IntEnum: TRIVIAL=1 to EXPERT=5
    domains: List[TaskDomain]           # List of detected domains
    primary_domain: TaskDomain          # Main domain

    # OPTIONAL fields (with defaults)
    requires_web: bool = False
    requires_code_execution: bool = False
    requires_deep_reasoning: bool = False
    requires_iteration: bool = False
    gemini_fit_score: float = 0.5       # 0.0-1.0
    claude_fit_score: float = 0.5       # 0.0-1.0
    raw_input: str = ""
    confidence: float = 0.5             # 0.0-1.0
    detected_keywords: List[str] = field(default_factory=list)

    # DOES NOT EXIST:
    # - reasoning (use ModeProposal.reasoning instead)
    # - description
    # - task_id
```

### ModeProposal (`swarm/mode_selector.py:57`)

```python
@dataclass
class ModeProposal:
    mode: CollaborationMode             # NOTE: .mode NOT .recommended_mode
    confidence: float                   # 0.0-1.0
    agent_assignments: List[AgentAssignment]
    reasoning: str                      # EXISTS HERE
    alternatives: List[Tuple[CollaborationMode, float]] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)
```

### AgentAssignment (`swarm/mode_selector.py:44`)

```python
@dataclass
class AgentAssignment:
    agent_id: str                       # "gemini" or "claude"
    role: str                           # "lead", "support", "specialist", etc.
    responsibilities: List[str]
```

### AgentResponse (`swarm/mode_executors.py:39`)

```python
@dataclass
class AgentResponse:
    agent_id: str
    content: str
    status: str = "success"
    tool_results: List[Dict] = field(default_factory=list)
    tokens_used: int = 0
    time_seconds: float = 0.0
    error: Optional[str] = None
```

### ExecutionContext (`swarm/mode_executors.py:96`)

```python
@dataclass
class ExecutionContext:
    task_input: str
    agent_assignments: List[AgentAssignment]
    blackboard: Dict = field(default_factory=dict)
    max_rounds: int = 6
    task_id: Optional[str] = None       # V7.5 Phase 7
    session_manager: Optional[Any] = None
    force_cot: bool = False             # V7.7 Phase 14e
```

### ExecutionResult (`swarm/mode_executors.py:150`)

```python
@dataclass
class ExecutionResult:
    mode: CollaborationMode
    status: ExecutionStatus
    final_output: str
    agent_outputs: List[AgentResponse]
    total_rounds: int
    total_tokens: int
    total_time_seconds: float
    metadata: Dict = field(default_factory=dict)
```

---

## 2. HIVE MIND DOMAIN

### AnalysisPhaseResult (`hive_mind/phases/phase_analysis.py:67`)

```python
@dataclass
class AnalysisPhaseResult:
    """Result of Phase 1 - Independent Analysis."""
    gemini_analysis: IndependentAnalysis   # [warning]️ NOT .payload!
    claude_analysis: IndependentAnalysis
    comparison: AnalysisComparison
    needs_debate: bool
    skip_reason: Optional[str] = None

    # DOES NOT EXIST:
    # - payload (use .gemini_analysis or .claude_analysis)
    # - result (use specific analysis fields)
    # - output
```

### IndependentAnalysis (`hive_mind/types.py:104`)

```python
@dataclass
class IndependentAnalysis:
    agent_id: str
    task_understanding: str
    complexity_assessment: str          # STRING, not enum!
    proposed_approach: str
    required_capabilities: List[str]
    potential_risks: List[str]
    confidence: float
    reasoning: str                      # EXISTS HERE (unlike TaskAnalysis)
    timestamp: datetime = field(default_factory=datetime.now)
```

### AnalysisComparison (`hive_mind/types.py:142`)

```python
@dataclass
class AnalysisComparison:
    gemini_analysis: IndependentAnalysis
    claude_analysis: IndependentAnalysis
    disagreements: List[Disagreement]
    agreement_score: float              # 0-1
    needs_debate: bool
    merged_capabilities: List[str]
    merged_risks: List[str]
```

### Disagreement (`hive_mind/types.py:131`)

```python
@dataclass
class Disagreement:
    topic: str                          # "complexity", "approach", etc.
    gemini_position: Any
    claude_position: Any
    severity: float = 0.5               # 0-1
    gemini_only: List[str] = field(default_factory=list)
    claude_only: List[str] = field(default_factory=list)
```

### DebateArgument (`hive_mind/types.py:158`)

```python
@dataclass
class DebateArgument:
    agent_id: str
    turn_number: int
    position: str                       # "SUPPORT" or "OPPOSE"
    target_point: str
    argument: str
    evidence: List[str]
    proposed_modification: Optional[str] = None
    concession: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
```

### DebateResult (`hive_mind/types.py:172`)

```python
@dataclass
class DebateResult:
    status: str                         # "IMMEDIATE_CONSENSUS", "CONSENSUS_REACHED", etc.
    final_approach: str
    final_capabilities: List[str]
    final_mode: str
    debate_history: List[DebateArgument]
    total_turns: int
    resolved_disagreements: List[str]
    unresolved_disagreements: List[str]
    consensus_confidence: float
    gemini_satisfaction: float
    claude_satisfaction: float
```

### AgentArchitecture (`hive_mind/types.py:233`)

```python
@dataclass
class AgentArchitecture:
    status: str                         # "READY", "SPAWN_SUGGESTED", "SPAWN_REQUIRED"
    collaboration_mode: str
    agents_to_use: List[str]
    agents_to_spawn: List[AgentSpec]
    rag_config: RAGConfig
    execution_plan: ExecutionPlan
    spawn_commands: List[str] = field(default_factory=list)
    estimated_cost: int = 0
    reasoning: str = ""                 # EXISTS HERE TOO
```

### FailureDiagnosis (`hive_mind/types.py:281`)

```python
@dataclass
class FailureDiagnosis:
    failure_type: FailureType
    root_cause: str
    contributing_factors: List[str]
    evidence: List[str]
    recommended_changes: List[str]
    confidence: float
    gemini_diagnosis: Optional[str] = None
    claude_diagnosis: Optional[str] = None
    missing_capability: Optional[str] = None
```

### RetryDecision (`hive_mind/types.py:310`)

```python
@dataclass
class RetryDecision:
    action: str                         # "RETRY", "STOP", "ESCALATE"
    reason: str
    new_architecture: Optional[AgentArchitecture] = None
    changes_made: List[str] = field(default_factory=list)
    expected_improvement: float = 0.0
    suggestion: Optional[str] = None
```

---

## 3. MEMORY DOMAIN

### SuccessEntry (`memory/success_memory.py:41`)

```python
@dataclass
class SuccessEntry:
    task_id: str
    description: str
    complexity: str                     # STRING (stored from TaskComplexity.name)
    domains: List[str]
    primary_domain: Optional[str]
    swarm_mode: str
    lead_agent: Optional[str]
    support_agent: Optional[str]
    duration_seconds: float
    success: bool
    quality_score: float
    timestamp: str
    tags: List[str]
    embedding: Optional[List[float]] = None
```

---

## 4. ORCHESTRATOR DOMAIN

### HiveMindResult (`hive_mind/orchestrator.py:60`)

```python
@dataclass
class HiveMindResult:
    success: bool
    output: str
    state: HiveMindState
    phases_completed: list
    total_duration: float
    total_tokens: int
    agents_used: list
    agents_spawned: list
    artifacts_created: list
    knowledge_archived: int
    error: Optional[str] = None

    # DOES NOT EXIST:
    # - dylan_score
    # - panic_recoveries
    # - reasoning
```

### SwarmResult (`swarm/hybrid_swarm_engine.py`)

```python
# SwarmResult is actually a Dict, not a dataclass!
# Returned by HybridSwarmEngine.process_task()
{
    "status": str,                      # "success", "failed"
    "mode": str,                        # CollaborationMode.value
    "output": str,
    "rounds": int,
    "tokens": int,
    "duration": float,
    "error": Optional[str]
}
```

---

## 5. FIELD CONFUSION MATRIX

| If you need... | Use this dataclass | Field name |
|----------------|-------------------|------------|
| Task complexity (enum) | TaskAnalysis | `.complexity` |
| Task complexity (str) | IndependentAnalysis | `.complexity_assessment` |
| Mode proposal | ModeProposal | `.mode` (NOT recommended_mode) |
| Reasoning for mode | ModeProposal | `.reasoning` |
| Reasoning for analysis | IndependentAnalysis | `.reasoning` |
| Reasoning for architecture | AgentArchitecture | `.reasoning` |
| Agent fit scores | TaskAnalysis | `.gemini_fit_score`, `.claude_fit_score` |
| Execution duration | ExecutionResult | `.total_time_seconds` |
| HiveMind duration | HiveMindResult | `.total_duration` |
| Phase 1 Gemini analysis | AnalysisPhaseResult | `.gemini_analysis` (NOT .payload) |
| Phase 1 Claude analysis | AnalysisPhaseResult | `.claude_analysis` |
| Phase 1 needs debate? | AnalysisPhaseResult | `.needs_debate` |

---

## 6. ANTI-HALLUCINATION QUICK REFERENCE

```
TaskAnalysis DOES NOT have:
  - reasoning
  - description
  - task_id
  - lead_agent

ModeProposal DOES NOT have:
  - recommended_mode (use .mode)
  - suggested_mode (use .mode)

HiveMindResult DOES NOT have:
  - dylan_score
  - panic_recoveries
  - reasoning

AnalysisPhaseResult DOES NOT have:
  - payload (use .gemini_analysis or .claude_analysis)
  - result
  - output

HiveMindState DOES NOT have:
  - HIVE_COMPLETE (use HIVE_SUCCESS)

GeminiDriverV7.invoke() signature:
  - invoke(context, session_uuid=None)
  - NOT invoke(context, task_type=...)

SwarmResult is a Dict, NOT a dataclass
```

---

*This document is the authoritative reference for dataclass fields. Update when modifying dataclasses.*
