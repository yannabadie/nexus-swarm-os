"""
Evolution Models - V7.5 Phase 0a

Dataclasses for evolution operations, extracted from repl.py.
Provides type-safe results for evolution phases.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class EvolutionPhaseStatus(Enum):
    """Status of an evolution phase"""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class MutationProposal:
    """A proposed mutation from AI brainstorming"""

    id: str
    name: str
    description: str
    files_to_modify: list[str]
    patches: list[dict[str, Any]]
    rationale: str
    source_agent: str  # "Gemini", "Claude", or "consensus"
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChildCreationResult:
    """Result of creating child instances from mutations"""

    success: bool
    children_created: list[str]  # List of child IDs
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0


@dataclass
class ValidationResult:
    """Result of validating a child"""

    child_id: str
    passed: bool
    tier_reached: int  # 1=syntax, 2=smoke, 3=benchmark, 4=redteam
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvaluationResult:
    """Result of fitness evaluation"""

    child_id: str
    fitness_score: float
    parent_score: float
    improvement_pct: float
    metrics: dict[str, float] = field(default_factory=dict)
    passed_threshold: bool = False
    red_team_score: float | None = None


@dataclass
class PromotionResult:
    """Result of promoting a child to parent"""

    success: bool
    child_id: str
    new_generation: int = 0
    backup_path: str | None = None
    errors: list[str] = field(default_factory=list)


@dataclass
class ArchiveResult:
    """Result of archiving a rejected child"""

    success: bool
    child_id: str
    archive_path: str | None = None
    reason: str = ""


@dataclass
class BrainstormResult:
    """Result of brainstorming mutations or prompts (V8.1.8)"""

    mutations: list[MutationProposal]
    debate_turns: int
    consensus_reached: bool
    duration_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)
    # V8.1.8: Generated prompt for mode="prompt"
    generated_prompt: str | None = None


@dataclass
class EvolutionResult:
    """Complete result of an evolution cycle"""

    success: bool
    phase_reached: str  # brainstorm, create, validate, evaluate, promote
    mutations_proposed: int = 0
    children_created: int = 0
    children_validated: int = 0
    winner_id: str | None = None
    winner_score: float | None = None
    promoted: bool = False
    errors: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None


@dataclass
class SpecializationResult:
    """Result of specialization/spinoff creation"""

    success: bool
    agent_id: str | None = None
    agent_path: str | None = None
    mission: str = ""
    errors: list[str] = field(default_factory=list)


@dataclass
class EvolutionStatus:
    """Current status of evolution system"""

    current_generation: int
    total_children: int
    pending_children: int
    last_evolution: datetime | None = None
    rate_limit_remaining: int = 0
    can_evolve: bool = True
    block_reason: str | None = None


@dataclass
class EvolutionContext:
    """Context passed between evolution phases"""

    parent_id: str
    objective: str
    child_count: int = 3
    current_phase: EvolutionPhaseStatus = EvolutionPhaseStatus.PENDING
    mutations: list[MutationProposal] = field(default_factory=list)
    children: list[str] = field(default_factory=list)
    evaluations: list[EvaluationResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
