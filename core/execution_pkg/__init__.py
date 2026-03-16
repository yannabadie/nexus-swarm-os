"""
NEXUS V12.4 - Execution Package

P5.6 Phase 6: Package Consolidation

Consolidated execution components for tool execution, model routing, and orchestration coordination.

## 📦 Subpackages

- **execution/**: Tool execution engine, validation, workflow engine, retry handling, timeout management
- **routing/**: Model routing (TaskType -> Model), cascaded router, resource optimizer, decision cache
- **orchestration/**: Context building, agent invoker, swarm bridge, guard pipeline, dependency injection

## 🎯 Key Features

### Tool Execution
```python
from core.execution_pkg import ExecutionEngine, ToolRegistry

engine = get_execution_engine()
result = await engine.execute(tool_request)
```

### Model Routing
```python
from core.execution_pkg import ModelRouter, TaskType

router = ModelRouter(config)
decision = router.select_claude_model(TaskType.BRAINSTORM)
# Returns: claude-opus-4-6 for complex tasks
```

### Orchestration
```python
from core.execution_pkg import ContextBuilder, AgentInvoker

context_builder = ContextBuilder(...)
context = context_builder.build_context(user_input, session)

invoker = AgentInvoker(drivers, router)
response = await invoker.invoke_agent(context)
```

## 📊 Migration Impact

**Statistics:**
- Files migrated: TBD
- Import updates: TBD
- Commit: TBD
- Impact: TBD

---
**Status:** P5.6 Phase 6 IN PROGRESS | **Version:** V12.4
"""

# Execution exports (38 items)
from core.execution_pkg.execution import (
    BaseHandler,
    Deadline,
    ExecutionEngine,
    ExecutionResult,
    HandlerExecution,
    HandlerPerformanceTracker,
    HandlerTrackerStats,
    HandlerTypeMetrics,
    ObservationReport,
    Priority,
    ReliabilityPatternTracker,
    ReliabilityRetryAttempt,
    ReliabilityStats,
    RetryAttempt,
    RetryHandler,
    RetryPolicy,
    RetryResult,
    RetryStats,
    ScheduledTask,
    StepStatus,
    TaskScheduler,
    TaskStatus,
    TimeoutConfig,
    TimeoutEvent,
    TimeoutManager,
    TimeoutStats,
    ToolMetric,
    ToolObserver,
    ToolObserverStats,
    ToolRegistry,
    ToolReliabilityProfile,
    ToolResult,
    ToolSpan,
    ValidationService,
    Workflow,
    WorkflowEngine,
    WorkflowStatus,
    WorkflowStep,
    get_execution_engine,
    get_handler_tracker,
    get_reliability_tracker,
    get_retry_handler,
    get_timeout_manager,
    get_tool_observer,
    get_tool_registry,
    reset_execution_engine,
    reset_handler_tracker,
    reset_reliability_tracker,
    reset_retry_handler,
    reset_timeout_manager,
    reset_tool_observer,
    reset_tool_registry,
)

# Orchestration exports (29 items)
from core.execution_pkg.orchestration import (
    AgentInvoker,
    AgentRequirements,
    CallGraphTracer,
    CallRecord,
    Capability,
    Conflict,
    ContextBuilder,
    DependencyInjector,
    DependencyManifest,
    DependencyValidationResult,
    EdgeMetrics,
    FSMHandlers,
    GuardPipeline,
    GuardValidationResult,
    MutationDetector,
    OrchestratorSyncBridge,
    ResponseDetector,
    ResultHandler,
    RouteDecision,
    RouteType,
    StateHandler,
    SwarmBridge,
    SyncEvent,
    SyncEventType,
    TaskRouter,
    TracerStats,
    get_call_tracer,
    get_injector,
    get_mutation_detector,
    get_sync_bridge,
    reset_call_tracer,
    reset_injector,
    reset_sync_bridge,
)

# Routing exports (27 items)
from core.execution_pkg.routing import (
    AgentRouting,
    CachedDecision,
    CascadedRouter,
    CascadedRoutingDecision,
    CascadeRoute,
    DecisionCacheStats,
    DecisionOutcome,
    ModelRouter,
    ModelSpec,
    ModelTier,
    OptimizationDecision,
    OptimizationReport,
    PolicyMetrics,
    ResourceOptimizer,
    RouterStats,
    RoutingAnalyzerStats,
    RoutingDecision,
    RoutingDecisionCache,
    RoutingDecisionRecord,
    RoutingEffectivenessAnalyzer,
    RoutingPolicy,
    RoutingStage,
    TaskType,
    UsageRecord,
    get_cascaded_router,
    get_decision_cache,
    get_resource_optimizer,
    get_routing_analyzer,
    reset_cascaded_router,
    reset_decision_cache,
    reset_resource_optimizer,
    reset_routing_analyzer,
)

__all__ = [
    # Execution (38 items)
    "ToolResult",
    "BaseHandler",
    "ToolRegistry",
    "ValidationService",
    "ExecutionEngine",
    "get_tool_registry",
    "reset_tool_registry",
    "get_execution_engine",
    "reset_execution_engine",
    "TaskScheduler",
    "ScheduledTask",
    "Priority",
    "TaskStatus",
    "WorkflowEngine",
    "Workflow",
    "WorkflowStep",
    "WorkflowStatus",
    "StepStatus",
    "ExecutionResult",
    "RetryHandler",
    "RetryPolicy",
    "RetryResult",
    "RetryAttempt",
    "RetryStats",
    "get_retry_handler",
    "reset_retry_handler",
    "TimeoutManager",
    "TimeoutConfig",
    "Deadline",
    "TimeoutEvent",
    "TimeoutStats",
    "get_timeout_manager",
    "reset_timeout_manager",
    "ToolObserver",
    "ToolSpan",
    "ToolMetric",
    "ObservationReport",
    "ToolObserverStats",
    "get_tool_observer",
    "reset_tool_observer",
    "HandlerPerformanceTracker",
    "HandlerExecution",
    "HandlerTypeMetrics",
    "HandlerTrackerStats",
    "get_handler_tracker",
    "reset_handler_tracker",
    "ReliabilityPatternTracker",
    "ReliabilityRetryAttempt",
    "ToolReliabilityProfile",
    "ReliabilityStats",
    "get_reliability_tracker",
    "reset_reliability_tracker",
    # Routing (27 items)
    "ModelRouter",
    "TaskType",
    "RoutingDecision",
    "RoutingPolicy",
    "ModelTier",
    "CascadeRoute",
    "ResourceOptimizer",
    "ModelSpec",
    "OptimizationDecision",
    "OptimizationReport",
    "UsageRecord",
    "get_resource_optimizer",
    "reset_resource_optimizer",
    "RoutingDecisionCache",
    "CachedDecision",
    "DecisionOutcome",
    "DecisionCacheStats",
    "get_decision_cache",
    "reset_decision_cache",
    "RoutingEffectivenessAnalyzer",
    "RoutingDecisionRecord",
    "PolicyMetrics",
    "RoutingAnalyzerStats",
    "get_routing_analyzer",
    "reset_routing_analyzer",
    "CascadedRouter",
    "CascadedRoutingDecision",
    "AgentRouting",
    "RoutingStage",
    "RouterStats",
    "get_cascaded_router",
    "reset_cascaded_router",
    # Orchestration (29 items)
    "ContextBuilder",
    "MutationDetector",
    "ResponseDetector",
    "get_mutation_detector",
    "AgentInvoker",
    "SwarmBridge",
    "FSMHandlers",
    "GuardPipeline",
    "GuardValidationResult",
    "TaskRouter",
    "RouteDecision",
    "RouteType",
    "ResultHandler",
    "StateHandler",
    "OrchestratorSyncBridge",
    "SyncEvent",
    "SyncEventType",
    "get_sync_bridge",
    "reset_sync_bridge",
    "DependencyInjector",
    "Capability",
    "AgentRequirements",
    "DependencyValidationResult",
    "Conflict",
    "DependencyManifest",
    "get_injector",
    "reset_injector",
    "CallGraphTracer",
    "CallRecord",
    "EdgeMetrics",
    "TracerStats",
    "get_call_tracer",
    "reset_call_tracer",
]

__version__ = "12.4.0"
