"""
NEXUS V8.0 - TRUE HIVE MIND Types

Core dataclasses and enums for the Hive Mind architecture.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

# =============================================================================
# ENUMS
# =============================================================================


class HiveMindState(Enum):
    """FSM states for TRUE HIVE MIND V8.0."""

    # Gating (decides which circuit to use)
    HIVE_GATING = "hive_gating"

    # Phase 1: Independent Analysis
    HIVE_ANALYZING_GEMINI = "hive_analyzing_gemini"
    HIVE_ANALYZING_CLAUDE = "hive_analyzing_claude"
    HIVE_COMPARING_ANALYSES = "hive_comparing_analyses"

    # Phase 2: Strategic Debate
    HIVE_DEBATING = "hive_debating"
    HIVE_CHECKING_CONSENSUS = "hive_checking_consensus"
    HIVE_BREAKPOINT_DEBATE = "hive_breakpoint_debate"

    # Phase 3: Architecture Generation
    HIVE_ARCHITECTING = "hive_architecting"
    HIVE_CHECKING_REGISTRY = "hive_checking_registry"
    HIVE_BREAKPOINT_SPAWN = "hive_breakpoint_spawn"
    HIVE_SPAWNING = "hive_spawning"

    # Phase 4: Monitored Execution
    HIVE_EXECUTING = "hive_executing"
    HIVE_MONITORING = "hive_monitoring"

    # Phase 5: Failure Analysis
    HIVE_DIAGNOSING = "hive_diagnosing"
    HIVE_BREAKPOINT_DIAGNOSIS = "hive_breakpoint_diagnosis"

    # Phase 6: Adaptive Retry
    HIVE_DECIDING_RETRY = "hive_deciding_retry"
    HIVE_APPLYING_CHANGES = "hive_applying_changes"

    # Phase 7: Knowledge Consolidation
    HIVE_REFLECTING = "hive_reflecting"
    HIVE_DECIDING_RETENTION = "hive_deciding_retention"
    HIVE_BREAKPOINT_CONSOLIDATION = "hive_breakpoint_consolidation"
    HIVE_CONSOLIDATING = "hive_consolidating"

    # Terminal states
    HIVE_SUCCESS = "hive_success"
    HIVE_FAILED = "hive_failed"
    HIVE_ESCALATE = "hive_escalate"


class UserBreakpoint(Enum):
    """Points where user can intervene."""

    AFTER_DEBATE = "after_debate"
    BEFORE_SPAWN = "before_spawn"
    AFTER_DIAGNOSIS = "after_diagnosis"
    KNOWLEDGE_CONSOLIDATION = "knowledge_consolidation"


class RetentionDecision(Enum):
    """Decisions for agent/knowledge retention."""

    KEEP_PERMANENT = "keep_permanent"
    ARCHIVE_KNOWLEDGE = "archive_knowledge"
    MERGE_INTO_EXISTING = "merge_into_existing"
    DELETE = "delete"


class IssueSeverity(Enum):
    """Severity levels for execution issues."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class FailureType(Enum):
    """Types of failures for diagnosis.

    Taxonomy inspired by PALADIN (arxiv:2509.25238) and AgentDebug
    (arxiv:2509.25370). Each type maps to a specific RecoveryStrategy.
    """

    TIMEOUT = "timeout"
    CAPABILITY_MISSING = "capability_missing"
    HALLUCINATION = "hallucination"
    STRATEGY_WRONG = "strategy_wrong"
    TOOL_ERROR = "tool_error"
    CONTEXT_LOST = "context_lost"
    BUDGET_EXCEEDED = "budget_exceeded"
    # V12.4: PALADIN-inspired additions
    MEMORY_ERROR = "memory_error"  # Lost track of prior context/decisions
    PLANNING_ERROR = "planning_error"  # Plan was infeasible or incomplete
    UNKNOWN = "unknown"


class RecoveryStrategy(Enum):
    """Recovery strategy mapped from FailureType.

    Based on PALADIN (arxiv:2509.25238): each failure type has a
    specific recovery action rather than generic retry.
    """

    RETRY_SAME = "retry_same"  # Transient failure, retry as-is
    RETRY_MODIFIED = "retry_modified"  # Same approach, modified parameters
    FALLBACK_MODEL = "fallback_model"  # Try cheaper/different model
    SIMPLIFY_TASK = "simplify_task"  # Break into smaller subtasks
    SPAWN_SPECIALIST = "spawn_specialist"  # Need domain-specific agent
    CONTEXT_RESET = "context_reset"  # Compress/reset context window
    ESCALATE_USER = "escalate_user"  # Needs human intervention
    ABORT = "abort"  # Unrecoverable, stop


# Maps each failure type to its default recovery strategy
FAILURE_RECOVERY_MAP: dict = {
    FailureType.TIMEOUT: RecoveryStrategy.RETRY_MODIFIED,
    FailureType.CAPABILITY_MISSING: RecoveryStrategy.SPAWN_SPECIALIST,
    FailureType.HALLUCINATION: RecoveryStrategy.RETRY_MODIFIED,
    FailureType.STRATEGY_WRONG: RecoveryStrategy.SIMPLIFY_TASK,
    FailureType.TOOL_ERROR: RecoveryStrategy.RETRY_SAME,
    FailureType.CONTEXT_LOST: RecoveryStrategy.CONTEXT_RESET,
    FailureType.BUDGET_EXCEEDED: RecoveryStrategy.ABORT,
    FailureType.MEMORY_ERROR: RecoveryStrategy.CONTEXT_RESET,
    FailureType.PLANNING_ERROR: RecoveryStrategy.SIMPLIFY_TASK,
    FailureType.UNKNOWN: RecoveryStrategy.ESCALATE_USER,
}


# =============================================================================
# PHASE 1: INDEPENDENT ANALYSIS
# =============================================================================


@dataclass
class IndependentAnalysis:
    """Result of independent analysis by one agent."""

    agent_id: str
    task_understanding: str
    complexity_assessment: str
    proposed_approach: str
    required_capabilities: list[str]
    potential_risks: list[str]
    confidence: float
    reasoning: str
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "task_understanding": self.task_understanding,
            "complexity_assessment": self.complexity_assessment,
            "proposed_approach": self.proposed_approach,
            "required_capabilities": self.required_capabilities,
            "potential_risks": self.potential_risks,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class Disagreement:
    """A specific point of disagreement between agents."""

    topic: str  # "complexity", "approach", "capabilities", etc.
    positions: dict[str, Any] = field(default_factory=dict)  # {agent_id: position}
    severity: float = 0.5  # 0-1, how significant is this disagreement
    gemini_only: list[str] = field(default_factory=list)
    claude_only: list[str] = field(default_factory=list)

    # Backward compatibility properties
    @property
    def gemini_position(self) -> Any:
        return self.positions.get("gemini")

    @property
    def claude_position(self) -> Any:
        return self.positions.get("claude")


@dataclass
class AnalysisComparison:
    """Comparison of two or more independent analyses."""

    analyses: dict[str, "IndependentAnalysis"] = field(default_factory=dict)
    disagreements: list[Disagreement] = field(default_factory=list)
    agreement_score: float = 0.0  # 0-1
    needs_debate: bool = False
    merged_capabilities: list[str] = field(default_factory=list)
    merged_risks: list[str] = field(default_factory=list)

    # Backward compatibility properties
    @property
    def gemini_analysis(self) -> "IndependentAnalysis | None":
        return self.analyses.get("gemini")

    @property
    def claude_analysis(self) -> "IndependentAnalysis | None":
        return self.analyses.get("claude")


# =============================================================================
# PHASE 2: STRATEGIC DEBATE
# =============================================================================


@dataclass
class DebateArgument:
    """A single argument in the debate."""

    agent_id: str
    turn_number: int
    position: str  # "SUPPORT" or "OPPOSE"
    target_point: str  # Which point of the other's argument is addressed
    argument: str
    evidence: list[str]
    proposed_modification: str | None = None
    concession: str | None = None  # What they concede to the other
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class DebateResult:
    """Result of strategic debate."""

    status: str  # "IMMEDIATE_CONSENSUS", "CONSENSUS_REACHED", "FORCED_VOTE", "TIMEOUT"
    final_approach: str
    final_capabilities: list[str]
    final_mode: str  # Collaboration mode decided
    debate_history: list[DebateArgument]
    total_turns: int
    resolved_disagreements: list[str]
    unresolved_disagreements: list[str]
    consensus_confidence: float
    satisfactions: dict[str, float] = field(default_factory=dict)  # {agent_id: satisfaction}

    # Backward compatibility properties
    @property
    def gemini_satisfaction(self) -> float:
        return self.satisfactions.get("gemini", 0.0)

    @property
    def claude_satisfaction(self) -> float:
        return self.satisfactions.get("claude", 0.0)


# =============================================================================
# PHASE 3: ARCHITECTURE GENERATION
# =============================================================================


@dataclass
class AgentSpec:
    """Specification for an agent to spawn."""

    role: str
    mission: str
    capabilities: list[str]
    tools_priority: list[str] = field(default_factory=list)
    spawn_if_missing: bool = True
    fallback_agent: str = "claude"
    estimated_cost: int = 500  # tokens


@dataclass
class RAGConfig:
    """RAG configuration for architecture."""

    enabled: bool = True
    depth: str = "standard"  # "shallow", "standard", "deep"
    sources: list[str] = field(default_factory=lambda: ["codebase"])
    max_chunks: int = 10


@dataclass
class ExecutionStep:
    """A step in the execution plan."""

    name: str
    agent_id: str
    action: str
    expected_duration: float = 30.0  # seconds
    depends_on: list[str] = field(default_factory=list)
    verification_required: bool = False
    # V8.3: Optional Swarm mode for delegation
    # If set, step is executed via SwarmBridge instead of direct driver call
    swarm_mode: str | None = None  # "parallel", "red_blue", etc.


@dataclass
class ExecutionPlan:
    """Plan for executing the architecture."""

    strategy: str  # "sequential", "parallel", "pipeline"
    steps: list[ExecutionStep] = field(default_factory=list)
    estimated_total_duration: float = 0.0
    estimated_total_tokens: int = 0


@dataclass
class AgentArchitecture:
    """Generated architecture for a task."""

    status: str  # "READY", "SPAWN_SUGGESTED", "SPAWN_REQUIRED"
    collaboration_mode: str
    agents_to_use: list[str]
    agents_to_spawn: list[AgentSpec]
    rag_config: RAGConfig
    execution_plan: ExecutionPlan
    spawn_commands: list[str] = field(default_factory=list)
    estimated_cost: int = 0
    reasoning: str = ""


# =============================================================================
# PHASE 4: MONITORED EXECUTION
# =============================================================================


@dataclass
class ExecutionIssue:
    """An issue detected during execution."""

    issue_type: str
    severity: IssueSeverity
    details: str
    step_name: str
    timestamp: datetime = field(default_factory=datetime.now)
    error_category: str | None = None


@dataclass
class MonitoredStepResult:
    """Result of a monitored execution step."""

    step_name: str
    agent_id: str
    status: str  # "success", "warning", "error"
    output: str
    duration: float
    expected_duration: float
    tokens_used: int
    issues: list[ExecutionIssue] = field(default_factory=list)
    artifacts_created: list[str] = field(default_factory=list)
    artifacts_verified: bool = True


# =============================================================================
# PHASE 5: FAILURE ANALYSIS
# =============================================================================


@dataclass
class FailureDiagnosis:
    """Detailed diagnosis of a failure."""

    failure_type: FailureType
    root_cause: str
    contributing_factors: list[str]
    evidence: list[str]
    recommended_changes: list[str]
    confidence: float
    gemini_diagnosis: str | None = None
    claude_diagnosis: str | None = None
    missing_capability: str | None = None

    def to_dict(self) -> dict:
        return {
            "failure_type": self.failure_type.value,
            "root_cause": self.root_cause,
            "contributing_factors": self.contributing_factors,
            "evidence": self.evidence,
            "recommended_changes": self.recommended_changes,
            "confidence": self.confidence,
            "missing_capability": self.missing_capability,
        }


# =============================================================================
# PHASE 6: ADAPTIVE RETRY
# =============================================================================


@dataclass
class RetryDecision:
    """Decision about whether and how to retry."""

    action: str  # "RETRY", "STOP", "ESCALATE"
    reason: str
    new_architecture: AgentArchitecture | None = None
    changes_made: list[str] = field(default_factory=list)
    expected_improvement: float = 0.0
    suggestion: str | None = None


# =============================================================================
# PHASE 7: KNOWLEDGE CONSOLIDATION
# =============================================================================


@dataclass
class AgentRetention:
    """Decision about retaining a spawned agent."""

    agent_id: str
    decision: RetentionDecision
    reason: str
    gemini_vote: RetentionDecision
    claude_vote: RetentionDecision
    user_override: RetentionDecision | None = None
    capabilities_to_merge: list[str] = field(default_factory=list)


@dataclass
class KnowledgeEntry:
    """A piece of knowledge to archive."""

    category: str  # "pattern", "antipattern", "recipe", "insight"
    content: str
    source_task: str
    usefulness_score: float
    tags: list[str] = field(default_factory=list)


@dataclass
class KnowledgeConsolidation:
    """Result of knowledge consolidation phase."""

    # What was learned
    learned_patterns: list[str]
    learned_antipatterns: list[str]
    new_capabilities_identified: list[str]

    # Decisions on assets
    agents_retention: list[AgentRetention]
    knowledge_to_archive: list[KnowledgeEntry]
    tools_to_create: list[str]

    # Suggestions for NEXUS improvement
    nexus_improvements: list[str]

    # Metrics
    task_success: bool
    confidence_in_decisions: float
    gemini_reflection: str
    claude_reflection: str


# =============================================================================
# USER BREAKPOINTS
# =============================================================================


@dataclass
class BreakpointOption:
    """An option presented to the user at a breakpoint."""

    id: str
    label: str
    description: str
    is_recommended: bool = False


@dataclass
class BreakpointRequest:
    """Request for user decision at a breakpoint."""

    breakpoint_type: UserBreakpoint
    context: str
    recommendation: str
    options: list[BreakpointOption]
    timeout_seconds: int = 60
    default_action: str = "accept"
    metadata: dict = field(default_factory=dict)


@dataclass
class BreakpointResponse:
    """User's response to a breakpoint."""

    breakpoint_type: UserBreakpoint
    chosen_option: str
    custom_input: str | None = None
    was_timeout: bool = False
    timestamp: datetime = field(default_factory=datetime.now)
