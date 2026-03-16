"""
Mode Executors - V9.6 Re-export Module

BACKWARD COMPATIBILITY LAYER

All executor classes have been extracted to core/swarm/executors/:
- executors/base.py: Base classes (ModeExecutor, ExecutionContext, etc.)
- executors/parallel_executor.py: ParallelExecutor
- executors/sequential_executor.py: SequentialExecutor
- executors/specialist_executor.py: SpecialistExecutor
- executors/lead_support_executor.py: LeadSupportExecutor
- executors/ping_pong_executor.py: PingPongExecutor
- executors/red_blue_executor.py: RedBlueExecutor
- executors/registry.py: EXECUTOR_REGISTRY, get_executor

This file re-exports all classes for backward compatibility.
Import from `core.swarm.executors` for new code.
"""

# Re-export all base classes
from .executors.base import (
    COMPLETION_PATTERN,
    AgentResponse,
    ExecutionContext,
    ExecutionError,
    ExecutionResult,
    ExecutionStatus,
    ModeExecutor,
    _blackboard_lock,
)
from .executors.lead_support_executor import LeadSupportExecutor

# Re-export all executors
from .executors.parallel_executor import ParallelExecutor
from .executors.ping_pong_executor import PingPongExecutor
from .executors.red_blue_executor import RedBlueExecutor

# Re-export registry
from .executors.registry import get_executor, get_executor_registry
from .executors.sequential_executor import SequentialExecutor
from .executors.specialist_executor import SpecialistExecutor

# Re-export AgentAssignment for backward compatibility
# (was imported in original mode_executors.py)
from .mode_selector import AgentAssignment

# Build EXECUTOR_REGISTRY for backward compatibility
# Note: Use get_executor() or get_executor_registry() for new code
EXECUTOR_REGISTRY = get_executor_registry()

__all__ = [
    # Base classes
    "ExecutionStatus",
    "AgentResponse",
    "ExecutionContext",
    "ExecutionResult",
    "ModeExecutor",
    "ExecutionError",
    "COMPLETION_PATTERN",
    "_blackboard_lock",
    "AgentAssignment",
    # Executors
    "ParallelExecutor",
    "SequentialExecutor",
    "SpecialistExecutor",
    "LeadSupportExecutor",
    "PingPongExecutor",
    "RedBlueExecutor",
    # Registry
    "EXECUTOR_REGISTRY",
    "get_executor",
    "get_executor_registry",
]

__version__ = "9.6.0"
