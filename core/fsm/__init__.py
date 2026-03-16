"""NEXUS V7/V8 FSM Module"""

from core.fsm.context import TaskExecutionContext
from core.fsm.health_state_machine import (
    HealthState,
    HealthStateMachine,
    RecoveryStrategy,
)
from core.fsm.stagnation_predictor import (
    PredictionLevel,
    PredictionResult,
    StagnationPredictor,
)

# V12.4 COGNITIVE BOOST: Guard Logger
from .guard_logger import (
    BlockedTransition,
    GuardEvaluation,
    GuardLogger,
    GuardLoggerStats,
    GuardMetrics,
    get_guard_logger,
    reset_guard_logger,
)

# V12.4: State Validator
from .state_validator import (
    StateValidator,
    ValidatorStats,
    get_state_validator,
    reset_state_validator,
)
from .state_validator import (
    ValidationResult as StateValidationResult,
)

# V12.4: Transition Logger
from .transition_logger import (
    LoggerStats,
    StateDurationStats,
    TransitionEntry,
    TransitionFrequency,
    TransitionLogger,
    get_transition_logger,
    reset_transition_logger,
)

__all__ = [
    "TaskExecutionContext",
    # V8.4.4 Health FSM
    "HealthState",
    "HealthStateMachine",
    "RecoveryStrategy",
    # V8.4.4 Stagnation Predictor
    "StagnationPredictor",
    "PredictionLevel",
    "PredictionResult",
    # V12.4: State Validator
    "StateValidator",
    "StateValidationResult",
    "ValidatorStats",
    "get_state_validator",
    "reset_state_validator",
    # V12.4: Transition Logger
    "TransitionLogger",
    "TransitionEntry",
    "StateDurationStats",
    "TransitionFrequency",
    "LoggerStats",
    "get_transition_logger",
    "reset_transition_logger",
    # V12.4 COGNITIVE BOOST: Guard Logger
    "GuardLogger",
    "GuardEvaluation",
    "GuardMetrics",
    "BlockedTransition",
    "GuardLoggerStats",
    "get_guard_logger",
    "reset_guard_logger",
]
