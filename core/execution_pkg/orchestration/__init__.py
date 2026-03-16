"""
NEXUS V7.8 - Orchestration Package (Phase 14c)

This package contains the refactored orchestration components:
- OrchestratorV7: Main orchestrator (re-exported from parent for compatibility)
- ContextBuilder: Context construction for agents
- MutationDetector: Format detection for evolution
- AgentInvoker: Agent invocation handling
- SwarmBridge: Swarm engine integration
- FSMHandlers: State machine handlers

Phase 14c Migration Strategy:
1. Extracted modules are used via COMPOSITION by OrchestratorV7
2. Original orchestration_v7.py remains as entry point
3. New modules can be used directly for testing/extension

Usage:
    # Standard usage (unchanged):
    from core.orchestration_v7 import OrchestratorV7

    # Direct module access:
    from core.execution_pkg.orchestration.context_builder import ContextBuilder
    from core.execution_pkg.orchestration.detectors import MutationDetector
    from core.execution_pkg.orchestration.agent_invoker import AgentInvoker
    from core.execution_pkg.orchestration.swarm_bridge import SwarmBridge
    from core.execution_pkg.orchestration.fsm_handlers import FSMHandlers
"""

# Re-export OrchestratorV7 for backwards compatibility
# Note: OrchestratorV7 remains in core/orchestration_v7.py for now
# It uses the extracted modules via composition

from core.execution_pkg.orchestration.agent_invoker import AgentInvoker

# V12.4: Call Graph Tracer
from core.execution_pkg.orchestration.call_graph_tracer import (
    CallGraphTracer,
    CallRecord,
    EdgeMetrics,
    TracerStats,
    get_call_tracer,
    reset_call_tracer,
)
from core.execution_pkg.orchestration.context_builder import ContextBuilder

# V12.4: Dependency Injector
from core.execution_pkg.orchestration.dependency_injector import (
    AgentRequirements,
    Capability,
    Conflict,
    DependencyInjector,
    DependencyManifest,
    get_injector,
    reset_injector,
)
from core.execution_pkg.orchestration.dependency_injector import (
    ValidationResult as DependencyValidationResult,
)
from core.execution_pkg.orchestration.detectors import MutationDetector, ResponseDetector, get_mutation_detector

# P5.1 Phase 1: GuardPipeline extraction
from core.execution_pkg.orchestration.guard_pipeline import GuardPipeline, GuardValidationResult

# P5.1 Phase 3: ResultHandler extraction
from core.execution_pkg.orchestration.result_handler import ResultHandler

# P5.1 Phase 4: StateHandler extraction
from core.execution_pkg.orchestration.state_handler import StateHandler
from core.execution_pkg.orchestration.swarm_bridge import SwarmBridge

# V9.4 ISSUE-003: Sync bridge for HiveMind/Swarm state synchronization
from core.execution_pkg.orchestration.sync_bridge import (
    OrchestratorSyncBridge,
    SyncEvent,
    SyncEventType,
    get_sync_bridge,
    reset_sync_bridge,
)

# P5.1 Phase 2: TaskRouter extraction
from core.execution_pkg.orchestration.task_router import RouteDecision, RouteType, TaskRouter
from core.fsm.handlers import FSMHandlers  # V12.4: Migrated to modular handlers

__all__ = [
    # Extracted modules (new in V7.8)
    "ContextBuilder",
    "MutationDetector",
    "ResponseDetector",
    "get_mutation_detector",
    "AgentInvoker",
    "SwarmBridge",
    "FSMHandlers",
    # P5.1 Phase 1: GuardPipeline
    "GuardPipeline",
    "GuardValidationResult",
    # P5.1 Phase 2: TaskRouter
    "TaskRouter",
    "RouteDecision",
    "RouteType",
    # P5.1 Phase 3: ResultHandler
    "ResultHandler",
    # P5.1 Phase 4: StateHandler
    "StateHandler",
    # V9.4: Sync bridge
    "OrchestratorSyncBridge",
    "SyncEvent",
    "SyncEventType",
    "get_sync_bridge",
    "reset_sync_bridge",
    # V12.4: Dependency Injector
    "DependencyInjector",
    "Capability",
    "AgentRequirements",
    "DependencyValidationResult",
    "Conflict",
    "DependencyManifest",
    "get_injector",
    "reset_injector",
    # V12.4: Call Graph Tracer
    "CallGraphTracer",
    "CallRecord",
    "EdgeMetrics",
    "TracerStats",
    "get_call_tracer",
    "reset_call_tracer",
]
