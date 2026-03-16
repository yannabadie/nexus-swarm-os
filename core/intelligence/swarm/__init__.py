"""
NEXUS V7 Swarm Module - Hybrid Swarm Engine

Sprint 9: Dynamic multi-agent collaboration where agents negotiate
the optimal mode for each task at runtime.

Architecture:
- TaskAnalyzer: Analyzes task complexity and domains
- ModeSelector: Selects optimal mode using DyLAN scores
- NegotiationProtocol: Hybrid natural+JSON negotiation
- ModeExecutors: 6 collaboration mode executors
- HybridSwarmEngine: Main orchestration engine

Collaboration Modes:
- PARALLEL: Simultaneous work, merge results
- SEQUENTIAL: Ordered execution (first -> second)
- LEAD_SUPPORT: Lead drives, support reviews
- PING_PONG: Rapid alternation until convergence
- SPECIALIST: Single expert handles all
- RED_BLUE: Adversarial propose/attack/defend

Usage:
    from core.intelligence.swarm import HybridSwarmEngine, CollaborationMode

    engine = HybridSwarmEngine(agent_pool, model_router, config)
    result = engine.process_task("Fix the auth bug", blackboard)
"""

# Agent Metrics (Sprint 3)
from .agent_metrics import AgentInvocationResult, AgentPool, AgentProfile, create_default_pool

# V12.4: Agent Role Tracker
from .agent_role_tracker import (
    AgentRoleProfile,
    AgentRoleTracker,
    RoleAssignment,
    RoleTrackerStats,
    get_role_tracker,
    reset_role_tracker,
)

# Collaboration Modes (Sprint 9)
from .collaboration_modes import (
    MODE_CHARACTERISTICS,
    CollaborationMode,
    ModeCharacteristics,
    get_adversarial_modes,
    get_all_modes,
    get_mode_characteristics,
    get_parallel_modes,
    suggest_mode_for_complexity,
)

# V12.4 COGNITIVE BOOST: Dynamic Role Assigner (arxiv:2601.17152)
from .dynamic_role_assigner import (
    AssignerStats,
    CapabilityProposal,
    DynamicRoleAssigner,
    RoleAssignmentResult,
    RoleScore,
    RoleType,
    get_dynamic_role_assigner,
    reset_dynamic_role_assigner,
)

# Hybrid Swarm Engine (Sprint 9)
from .hybrid_swarm_engine import HybridSwarmEngine, SwarmPhase, SwarmResult

# V12.4: Mode Effectiveness Evaluator
from .mode_effectiveness_evaluator import (
    EvaluatorStats,
    ModeEffectivenessEvaluator,
    ModeEffectivenessSummary,
    ModeEvaluation,
    get_mode_evaluator,
    reset_mode_evaluator,
)

# Mode Executors (Sprint 9)
from .mode_executors import (
    EXECUTOR_REGISTRY,
    AgentResponse,
    ExecutionContext,
    ExecutionResult,
    ExecutionStatus,
    LeadSupportExecutor,
    ModeExecutor,
    ParallelExecutor,
    PingPongExecutor,
    RedBlueExecutor,
    SequentialExecutor,
    SpecialistExecutor,
    get_executor,
)

# Mode Selector (Sprint 9)
from .mode_selector import AgentAssignment, ModeProposal, ModeSelector

# Negotiation Protocol (Sprint 9)
from .negotiation_protocol import (
    HybridNegotiationMessage,
    NegotiationProposal,
    NegotiationProtocol,
    NegotiationResult,
    NegotiationStatus,
    extract_negotiate_json,
)

# V12.4: Negotiation Tracker
from .negotiation_tracker import (
    NegotiationRecord,
    NegotiationStats,
    NegotiationTracker,
    NegotiationTurn,
    get_negotiation_tracker,
    reset_negotiation_tracker,
)

# V12.4: Result Aggregator
from .result_aggregator import (
    AggregatorStats,
    MergeResult,
    MergeStrategy,
    ResultAggregator,
    get_aggregator,
    reset_aggregator,
)

# V12.4 COGNITIVE BOOST: Scaling Heuristics (arxiv:2512.08296)
from .scaling_heuristics import (
    CoordinationType,
    ScalingHeuristicEvaluator,
    ScalingRecommendation,
    ScalingStats,
    TaskCharacteristic,
    get_scaling_heuristics,
    reset_scaling_heuristics,
)
from .service import (
    SwarmResult as SwarmServiceResult,
)

# Service Layer (V9.1)
from .service import (
    SwarmService,
    SwarmStatus,
)

# Session Manager (Phase 7 - V7.5)
from .session_manager import (
    AgentSession,
    SessionMode,
    SessionStatus,
    SwarmSessionManager,
    TaskSession,
    generate_task_id,
)

# V12.4: Strategy Memory
from .strategy_memory import (
    ModeEffectiveness,
    ModeSuggestion,
    StrategyMemory,
    StrategyRecord,
    StrategyStats,
    get_strategy_memory,
    reset_strategy_memory,
)

# Task Analyzer (Sprint 9)
from .task_analyzer import TaskAnalysis, TaskAnalyzer, TaskComplexity, TaskDomain

# Task Completion Validator (Phase V7.9)
from .task_completion_validator import (
    CompletionCriteria,
    TaskCompletionValidator,
    ValidationResult,
    get_adaptive_max_rounds,
)

# V12.4: Task Queue
from .task_queue import (
    QueueStats,
    SwarmTask,
    SwarmTaskQueue,
    get_task_queue,
    reset_task_queue,
)
from .task_queue import (
    TaskStatus as SwarmTaskStatus,
)

__all__ = [
    # Agent Metrics
    "AgentInvocationResult",
    "AgentProfile",
    "AgentPool",
    "create_default_pool",
    # Collaboration Modes
    "CollaborationMode",
    "ModeCharacteristics",
    "MODE_CHARACTERISTICS",
    "get_mode_characteristics",
    "get_all_modes",
    "get_adversarial_modes",
    "get_parallel_modes",
    "suggest_mode_for_complexity",
    # Task Analyzer
    "TaskComplexity",
    "TaskDomain",
    "TaskAnalysis",
    "TaskAnalyzer",
    # Mode Selector
    "AgentAssignment",
    "ModeProposal",
    "ModeSelector",
    # Negotiation Protocol
    "NegotiationStatus",
    "NegotiationProposal",
    "HybridNegotiationMessage",
    "NegotiationResult",
    "NegotiationProtocol",
    "extract_negotiate_json",
    # Mode Executors
    "ExecutionStatus",
    "AgentResponse",
    "ExecutionContext",
    "ExecutionResult",
    "ModeExecutor",
    "ParallelExecutor",
    "SequentialExecutor",
    "LeadSupportExecutor",
    "PingPongExecutor",
    "SpecialistExecutor",
    "RedBlueExecutor",
    "EXECUTOR_REGISTRY",
    "get_executor",
    # Hybrid Swarm Engine
    "SwarmPhase",
    "SwarmResult",
    "HybridSwarmEngine",
    # Session Manager (Phase 7)
    "SessionStatus",
    "SessionMode",
    "AgentSession",
    "TaskSession",
    "SwarmSessionManager",
    "generate_task_id",
    # Task Completion Validator (V7.9)
    "TaskCompletionValidator",
    "CompletionCriteria",
    "ValidationResult",
    "get_adaptive_max_rounds",
    # Service Layer (V9.1)
    "SwarmService",
    "SwarmServiceResult",
    "SwarmStatus",
    # V12.4: Task Queue
    "SwarmTaskQueue",
    "SwarmTask",
    "SwarmTaskStatus",
    "QueueStats",
    "get_task_queue",
    "reset_task_queue",
    # V12.4: Result Aggregator
    "ResultAggregator",
    "MergeStrategy",
    "MergeResult",
    "AggregatorStats",
    "get_aggregator",
    "reset_aggregator",
    # V12.4: Strategy Memory
    "StrategyMemory",
    "StrategyRecord",
    "ModeEffectiveness",
    "ModeSuggestion",
    "StrategyStats",
    "get_strategy_memory",
    "reset_strategy_memory",
    # V12.4: Negotiation Tracker
    "NegotiationTracker",
    "NegotiationTurn",
    "NegotiationRecord",
    "NegotiationStats",
    "get_negotiation_tracker",
    "reset_negotiation_tracker",
    # V12.4: Mode Effectiveness Evaluator
    "ModeEffectivenessEvaluator",
    "ModeEvaluation",
    "ModeEffectivenessSummary",
    "EvaluatorStats",
    "get_mode_evaluator",
    "reset_mode_evaluator",
    # V12.4: Agent Role Tracker
    "AgentRoleTracker",
    "RoleAssignment",
    "AgentRoleProfile",
    "RoleTrackerStats",
    "get_role_tracker",
    "reset_role_tracker",
    # V12.4 COGNITIVE BOOST: Dynamic Role Assigner (arxiv:2601.17152)
    "DynamicRoleAssigner",
    "CapabilityProposal",
    "RoleScore",
    "RoleAssignmentResult",
    "RoleType",
    "AssignerStats",
    "get_dynamic_role_assigner",
    "reset_dynamic_role_assigner",
    # V12.4 COGNITIVE BOOST: Scaling Heuristics (arxiv:2512.08296)
    "ScalingHeuristicEvaluator",
    "ScalingRecommendation",
    "CoordinationType",
    "TaskCharacteristic",
    "ScalingStats",
    "get_scaling_heuristics",
    "reset_scaling_heuristics",
]
