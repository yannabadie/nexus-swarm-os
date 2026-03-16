"""
NEXUS V7 - Reasoning Module

Advanced reasoning patterns for complex problem-solving:
- Graph of Thought (GoT): Non-linear exploration with branching and merging
- Chain of Thought (CoT): Linear step-by-step reasoning
- Tree of Thought (ToT): Tree-based exploration with pruning

NOTE: GoT implementation is optional and loaded lazily by HybridSwarmEngine.
This module currently exports nothing - implementations pending.
To use GoT, create core/reasoning/graph_of_thought.py with the required classes.
"""

# V7 FIX: Make imports optional to avoid blocking the entire system
# GoT is a future enhancement, not required for core functionality

__all__ = []

# Lazy loading pattern - consumers should check availability:
# from core.intelligence.reasoning import GOT_AVAILABLE
# if GOT_AVAILABLE:
#     from core.intelligence.reasoning import GraphOfThought

GOT_AVAILABLE = False

try:
    from .graph_of_thought import GraphOfThought, ThoughtGraph, ThoughtNode, ThoughtStatus, ThoughtType

    GOT_AVAILABLE = True
    __all__ = ["GraphOfThought", "ThoughtNode", "ThoughtGraph", "ThoughtStatus", "ThoughtType", "GOT_AVAILABLE"]
except ImportError:
    # GoT not implemented yet - this is OK
    GraphOfThought = None
    ThoughtNode = None
    ThoughtGraph = None
    ThoughtStatus = None
    ThoughtType = None
    __all__ = ["GOT_AVAILABLE"]

# V12.4 COGNITIVE BOOST: Thought Evaluator
from .thought_evaluator import (  # noqa: E402  # after module setup
    EvaluationResult,
    EvaluatorStats,
    ThoughtEvaluator,
    ThoughtScore,
    get_thought_evaluator,
    reset_thought_evaluator,
)

__all__ += [
    "ThoughtEvaluator",
    "ThoughtScore",
    "EvaluationResult",
    "EvaluatorStats",
    "get_thought_evaluator",
    "reset_thought_evaluator",
]

# V12.4 COGNITIVE BOOST: Reasoning Quality Scorer
from .reasoning_quality_scorer import (  # noqa: E402  # after module setup
    AgentReasoningProfile,
    ReasoningEvaluation,
    ReasoningQualityScorer,
    ScorerStats,
    get_quality_scorer,
    reset_quality_scorer,
)

__all__ += [
    "ReasoningQualityScorer",
    "ReasoningEvaluation",
    "AgentReasoningProfile",
    "ScorerStats",
    "get_quality_scorer",
    "reset_quality_scorer",
]

# V12.4 COGNITIVE BOOST: Cognitive Degradation Detector
from .cognitive_degradation import (  # noqa: E402  # after module setup
    CognitiveDegradationDetector,
    DegradationReason,
    DegradationSignal,
    DetectorStats,
    Mitigation,
    get_degradation_detector,
    reset_degradation_detector,
)

__all__ += [
    "CognitiveDegradationDetector",
    "DegradationSignal",
    "DegradationReason",
    "Mitigation",
    "DetectorStats",
    "get_degradation_detector",
    "reset_degradation_detector",
]

# V12.4 COGNITIVE BOOST: Evaluation Panel (CRM-inspired)
from .evaluation_panel import (  # noqa: E402  # after module setup
    DimensionScore,
    EvalDimension,
    EvaluationPanel,
    PanelResult,
    get_evaluation_panel,
    reset_evaluation_panel,
)

__all__ += [
    "EvaluationPanel",
    "EvalDimension",
    "DimensionScore",
    "PanelResult",
    "get_evaluation_panel",
    "reset_evaluation_panel",
]

# V12.4 COGNITIVE BOOST: Consensus Verifier (Six Sigma-inspired)
from .consensus_verifier import (  # noqa: E402  # after module setup
    ConsensusVerifier,
    QualityGate,
    VerificationOutcome,
    VerificationResult,
    get_consensus_verifier,
    reset_consensus_verifier,
)

__all__ += [
    "ConsensusVerifier",
    "VerificationOutcome",
    "VerificationResult",
    "QualityGate",
    "get_consensus_verifier",
    "reset_consensus_verifier",
]

# V12.4 COGNITIVE BOOST: Meta-Policy Memory (MPR, arxiv:2509.03990)
from .meta_policy_memory import (  # noqa: E402  # after module setup
    AdmissibilityResult,
    MetaPolicyMemory,
    PolicyRule,
    RuleCategory,
    get_meta_policy_memory,
    reset_meta_policy_memory,
)

__all__ += [
    "MetaPolicyMemory",
    "PolicyRule",
    "RuleCategory",
    "AdmissibilityResult",
    "get_meta_policy_memory",
    "reset_meta_policy_memory",
]

# V12.4 COGNITIVE BOOST: Metacognitive Monitor (MASC, arxiv:2510.14319)
from .metacognitive_monitor import (  # noqa: E402  # after module setup
    AnomalyScore,
    MetacognitiveMonitor,
    get_metacognitive_monitor,
    reset_metacognitive_monitor,
)

__all__ += [
    "MetacognitiveMonitor",
    "AnomalyScore",
    "get_metacognitive_monitor",
    "reset_metacognitive_monitor",
]

# V12.4 COGNITIVE BOOST: Inspector Guard (arxiv:2408.00989)
from .inspector_guard import (  # noqa: E402  # after module setup
    GuardStats,
    InspectionResult,
    InspectorGuard,
    IssuePattern,
    RiskLevel,
    get_inspector_guard,
    reset_inspector_guard,
)

__all__ += [
    "InspectorGuard",
    "InspectionResult",
    "RiskLevel",
    "IssuePattern",
    "GuardStats",
    "get_inspector_guard",
    "reset_inspector_guard",
]

# V12.4 COGNITIVE BOOST: Confidence Calibrator (arxiv:2404.09127)
from .confidence_calibrator import (  # noqa: E402  # after module setup
    AgentCalibrationProfile,
    CalibratedConfidence,
    CalibratorStats,
    ConfidenceBias,
    ConfidenceCalibrator,
    get_confidence_calibrator,
    reset_confidence_calibrator,
)

__all__ += [
    "ConfidenceCalibrator",
    "CalibratedConfidence",
    "ConfidenceBias",
    "AgentCalibrationProfile",
    "CalibratorStats",
    "get_confidence_calibrator",
    "reset_confidence_calibrator",
]

# V12.4 COGNITIVE BOOST: Trajectory Scorer (FREE-MAD, arxiv:2509.11035)
from .trajectory_scorer import (  # noqa: E402  # after module setup
    AgentTrajectory,
    ConformityAnalysis,
    TrajectoryResult,
    TrajectoryScorer,
    get_trajectory_scorer,
    reset_trajectory_scorer,
)

__all__ += [
    "TrajectoryScorer",
    "TrajectoryResult",
    "AgentTrajectory",
    "ConformityAnalysis",
    "get_trajectory_scorer",
    "reset_trajectory_scorer",
]

# V12.4 COGNITIVE BOOST: Uncertainty Propagator (arxiv:2601.15703)
from .uncertainty_propagator import (  # noqa: E402  # after module setup
    ChainSummary,
    PropagationSignal,
    PropagatorStats,
    UncertaintyLevel,
    UncertaintyPropagator,
    get_uncertainty_propagator,
    reset_uncertainty_propagator,
)

__all__ += [
    "UncertaintyPropagator",
    "PropagationSignal",
    "UncertaintyLevel",
    "ChainSummary",
    "PropagatorStats",
    "get_uncertainty_propagator",
    "reset_uncertainty_propagator",
]

# V12.4 COGNITIVE BOOST: Failure Classifier (AgentDebug, arxiv:2509.25370)
from .failure_classifier import (  # noqa: E402  # after module setup
    Classification,
    ClassifierStats,
    FailureCategory,
    FailureClassifier,
    get_failure_classifier,
    reset_failure_classifier,
)

__all__ += [
    "FailureClassifier",
    "FailureCategory",
    "Classification",
    "ClassifierStats",
    "get_failure_classifier",
    "reset_failure_classifier",
]

# V12.4 COGNITIVE BOOST: Fault Detector (CP-WBFT, arxiv:2511.10400)
from .fault_detector import (  # noqa: E402  # after module setup
    AgentStatus,
    FaultDetector,
    FaultStatus,
    get_fault_detector,
    reset_fault_detector,
)

__all__ += [
    "FaultDetector",
    "FaultStatus",
    "AgentStatus",
    "get_fault_detector",
    "reset_fault_detector",
]

# V12.4 P5.5: Task Complexity (Adaptive Metacognition)
from .task_complexity import (  # noqa: E402  # after module setup
    TaskComplexity,
    estimate_complexity,
    should_monitor_metacognition,
)

__all__ += [
    "TaskComplexity",
    "estimate_complexity",
    "should_monitor_metacognition",
]
