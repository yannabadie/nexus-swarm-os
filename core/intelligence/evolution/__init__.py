"""
NEXUS V7.5 Evolution Engine

Handles self-modification, lineage tracking, child evaluation, and validation.

Modules:
- manager.py: Central orchestrator (V7.5 Phase 0a - extracted from repl.py)
- models.py: Dataclasses for evolution operations (V7.5 Phase 0a)
- phases/: Individual phase implementations
- lineage.py: Manages LINEAGE.json and ancestry tree
- evaluator.py: Runs benchmarks and compares to parent
- validator.py: Validates children before promotion (syntax, import, smoke, benchmark, redteam)
- tiered_validator.py: V7 fast-fail validation with parallel benchmarks
- rate_limiter.py: Controls evolution frequency

Note: Child creation uses emergent JSON patches from Gemini+Claude symbiotic debate.
V7.5: Evolution logic is being extracted from repl.py to manager.py for better separation.
"""

# V12.4: Agent Reaper (DyLAN-based lifecycle management)
from .agent_reaper import AgentReaper, ArchivalCandidate, ReaperConfig, ReaperReport

# V12.4: Auto-Specializer (data-driven agent spawning)
from .auto_specializer import AutoSpecializer, DomainProfile, SpecializationConfig, SpecializationProposal
from .evaluator import (
    compare_to_parent,
    run_benchmarks,
    select_winner,
)
from .lineage import (
    add_child,
    get_ancestry,
    load_lineage,
    sign_birth_certificate,
)
from .manager import EvolutionManager

# V7.5 Phase 0a: Evolution Manager and Models
from .models import (
    ArchiveResult,
    BrainstormResult,
    ChildCreationResult,
    EvaluationResult,
    EvolutionContext,
    EvolutionPhaseStatus,
    EvolutionResult,
    EvolutionStatus,
    MutationProposal,
    PromotionResult,
    SpecializationResult,
)

# V12.4: Mutation Tracker
from .mutation_tracker import (
    AgentPerformance,
    LineageNode,
    MutationRecord,
    MutationTracker,
    get_mutation_tracker,
    reset_mutation_tracker,
)

# V9.1: Service Layer
from .service import (
    EvolutionService,
    EvolutionServiceResult,
    _get_evolution_service,
)

# V12.4 COGNITIVE BOOST: Strategy Performance Tracker
from .strategy_performance_tracker import (
    StrategyApplication,
    StrategyMetrics,
    StrategyPerformanceTracker,
    StrategyRecommendation,
    TrackerStats,
    get_strategy_tracker,
    reset_strategy_tracker,
)
from .tiered_validator import TieredValidationResult, TieredValidator, TierResult, ValidationTier
from .validator import AutoPromotionDecision, ChildValidator, FullValidationResult, SafetyGate, ValidationResult

# V7: mutator.py removed - evolution uses emergent JSON patches from AI debate

__all__ = [
    # V7.5 Phase 0a: Evolution Manager
    "EvolutionManager",
    # V9.1: Service Layer
    "EvolutionService",
    "EvolutionServiceResult",
    "_get_evolution_service",
    # V7.5 Phase 0a: Models
    "MutationProposal",
    "BrainstormResult",
    "ChildCreationResult",
    "EvaluationResult",
    "PromotionResult",
    "ArchiveResult",
    "EvolutionResult",
    "SpecializationResult",
    "EvolutionStatus",
    "EvolutionContext",
    "EvolutionPhaseStatus",
    # Lineage
    "load_lineage",
    "add_child",
    "get_ancestry",
    "sign_birth_certificate",
    # Evaluator (V7.5: Fitness-based, no ASI)
    "run_benchmarks",
    "compare_to_parent",
    "select_winner",
    # Validator (Legacy)
    "ChildValidator",
    "ValidationResult",
    "FullValidationResult",
    # V7: Auto-Promotion
    "SafetyGate",
    "AutoPromotionDecision",
    # V7 Sprint 2: Tiered Validator
    "TieredValidator",
    "ValidationTier",
    "TieredValidationResult",
    "TierResult",
    # V12.4: Agent Reaper
    "AgentReaper",
    "ReaperConfig",
    "ReaperReport",
    "ArchivalCandidate",
    # V12.4: Auto-Specializer
    "AutoSpecializer",
    "SpecializationConfig",
    "SpecializationProposal",
    "DomainProfile",
    # V12.4: Mutation Tracker
    "MutationTracker",
    "MutationRecord",
    "AgentPerformance",
    "LineageNode",
    "get_mutation_tracker",
    "reset_mutation_tracker",
    # V12.4 COGNITIVE BOOST: Strategy Performance Tracker
    "StrategyPerformanceTracker",
    "StrategyApplication",
    "StrategyMetrics",
    "StrategyRecommendation",
    "TrackerStats",
    "get_strategy_tracker",
    "reset_strategy_tracker",
]
