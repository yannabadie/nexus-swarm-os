"""
NEXUS V9.8 - Centralized Constants

This module consolidates all magic numbers previously scattered across the codebase.
These are INTERNAL constants - not meant to be user-configurable.

For user-configurable settings, see config.py (loads from .env).

Structure:
- Timeouts: Operation timeouts in seconds
- RetryLimits: Retry/attempt limits
- SagaLimits: Saga pattern constraints (V9.5)
- DebateLimits: HiveMind debate parameters
- MemoryLimits: RAG and context limits
- ExecutionLimits: Swarm and tool execution limits
- SwarmDepthLimits: Anti-recursion (Inception Trap prevention)
- ThresholdConstants: Scoring thresholds

V9.8 DETOX: Added headless mode support (see core/interaction/)
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Timeouts:
    """Operation timeouts in seconds.

    These are DEFAULT values. Some may be overridden by config.py/.env.
    """

    # Tool Execution
    BASH_COMMAND: float = 60.0  # Standard bash command
    BASH_LONG_RUNNING: float = 300.0  # npm install, build, etc.
    GIT_COMMAND: float = 60.0  # git operations
    WEB_SEARCH: float = 90.0  # Web search (includes grounding latency)
    WEB_FETCH: float = 30.0  # HTTP fetch single URL
    TODO_WRITE: float = 10.0  # JSON file write

    # Orchestration
    CFL_VALIDATION: float = 60.0  # Cognitive Feedback Loop validation
    HIVE_MIND_ASYNC: float = 300.0  # Async HiveMind operations (5 min)
    FSM_ITERATION: float = 30.0  # Single FSM iteration
    BREAKPOINT_USER: float = 60.0  # User interaction at breakpoint

    # Process Management
    PROCESS_GRACEFUL_TERMINATION: float = 2.0  # Grace period before kill
    MCP_PROCESS_WAIT: float = 5.0  # MCP server shutdown
    CLI_VERSION_CHECK: float = 10.0  # Quick CLI version check

    # Rate Limiter
    RATE_LIMITER_ACQUIRE: float = 60.0  # Wait for rate limit slot


@dataclass(frozen=True)
class RetryLimits:
    """Retry and attempt limits."""

    MAX_PARSE_FAILURES: int = 3  # LLM response parsing
    MAX_TOOL_ITERATIONS: int = 5  # Tool execution retries
    MAX_FSM_ITERATIONS: int = 50  # FSM loop guard (repl.py)
    MAX_CFL_ITERATIONS: int = 5  # CFL stalemate prevention
    MAX_LEAD_SWAPS: int = 3  # Lead-Support role swaps


@dataclass(frozen=True)
class SagaLimits:
    """Saga pattern constraints (V9.5 - from Gemini feedback).

    Prevents infinite rollback loops and manages checkpoint lifecycle.
    """

    MAX_ROLLBACK_ATTEMPTS: int = 3  # Absolute max before FAILED_PERMANENT
    ROLLBACK_TIMEOUT: float = 30.0  # Timeout per rollback operation
    CHECKPOINT_RETENTION_HOURS: int = 24  # Hours before cleanup
    MAX_CHECKPOINTS_PER_TASK: int = 10  # Memory guard


@dataclass(frozen=True)
class DebateLimits:
    """HiveMind debate parameters.

    Note: Some are also in config.py for user override.
    These are the hardcoded defaults/bounds.
    """

    MIN_TURNS: int = 3  # Minimum debate rounds
    MAX_TURNS: int = 10  # Maximum debate rounds
    COMPLEX_TURNS_MIN: int = 5  # COMPLEX task minimum
    COMPLEX_TURNS_MAX: int = 8  # COMPLEX task maximum
    EXPERT_TURNS_MIN: int = 6  # EXPERT task minimum
    EXPERT_TURNS_MAX: int = 10  # EXPERT task maximum
    ADAPTIVE_TURN_CAP: int = 10  # Cap on adaptive increases
    NEGOTIATION_MAX_TURNS: int = 4  # Swarm negotiation rounds


@dataclass(frozen=True)
class MemoryLimits:
    """Memory and retrieval limits."""

    RAG_CHUNKS_RETRIEVE: int = 3  # Initial RAG retrieval
    RAG_CHUNKS_MAX: int = 10  # Absolute max chunks
    SIMILAR_TASKS_LIMIT: int = 5  # Similar task results from SuccessMemory
    CONTEXT_WINDOW_TOKENS: int = 100000  # Context compression threshold
    MIN_SIMILARITY_SCORE: float = 0.05  # Relevance threshold


@dataclass(frozen=True)
class ExecutionLimits:
    """Swarm and execution limits."""

    SWARM_MAX_ROUNDS: int = 6  # Default max collaboration rounds
    MAX_SWARM_DEPTH: int = 2  # Anti-recursion (Inception Trap)
    MAX_PARALLEL_AGENTS: int = 4  # Concurrent agent limit
    MAX_EXECUTION_STEPS: int = 20  # HiveMind execution steps


@dataclass(frozen=True)
class ThresholdConstants:
    """Scoring and threshold values."""

    DEFAULT_CONFIDENCE: float = 0.5  # When unknown
    FALLBACK_QUALITY_PENALTY: float = 0.15  # Per fallback step
    STAGNATION_SIMILARITY: float = 0.8  # Task stagnation detection
    HIVE_MIND_AGREEMENT: float = 0.85  # Early agreement threshold
    RED_TEAM_PASS: float = 0.60  # Minimum red team score


@dataclass(frozen=True)
class CostEstimates:
    """Token cost estimates for HiveMind operations.

    Used for budget tracking. Values are ESTIMATES, not exact.
    """

    ANALYSIS_COMPARE: int = 500
    CONSENSUS_CHECK: int = 300
    EXECUTION_STEP: int = 1000
    DIAGNOSIS_SINGLE: int = 1000
    DIAGNOSIS_SYNTHESIS: int = 500
    CHANGES_APPLY: int = 300
    RETENTION_DECIDE: int = 500
    CONSOLIDATION: int = 300
    RAG_INJECTION: int = 500
    DEFAULT_OPERATION: int = 500


# Singleton instances for easy import
TIMEOUTS = Timeouts()
RETRY_LIMITS = RetryLimits()
SAGA_LIMITS = SagaLimits()
DEBATE_LIMITS = DebateLimits()
MEMORY_LIMITS = MemoryLimits()
EXECUTION_LIMITS = ExecutionLimits()
THRESHOLDS = ThresholdConstants()
COST_ESTIMATES = CostEstimates()


# Version marker for migration
CONSTANTS_VERSION = "9.8.0"
