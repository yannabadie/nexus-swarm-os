"""
NEXUS V9.5 Execution Module

Refactored from monolithic tool_manager.py (1848 LOC).

Modules:
- tool_registry: Tool registration and discovery
- validation_service: Path and security validation
- execution_engine: Centralized tool execution
- handlers/: Individual tool handlers

Usage:
    from core.execution_pkg.execution import ExecutionEngine, ToolResult
    engine = ExecutionEngine(workspace_path)
    result = engine.execute(tool_request)
"""

from .execution_engine import ExecutionEngine, get_execution_engine, reset_execution_engine

# V12.4 COGNITIVE BOOST: Handler Performance Tracker
from .handler_performance_tracker import (
    HandlerExecution,
    HandlerPerformanceTracker,
    HandlerTypeMetrics,
    get_handler_tracker,
    reset_handler_tracker,
)
from .handler_performance_tracker import (
    TrackerStats as HandlerTrackerStats,
)
from .handlers.base import BaseHandler, ToolResult

# V12.4 COGNITIVE BOOST: Reliability Pattern Tracker
from .reliability_pattern_tracker import (
    ReliabilityPatternTracker,
    ReliabilityStats,
    ToolReliabilityProfile,
    get_reliability_tracker,
    reset_reliability_tracker,
)
from .reliability_pattern_tracker import (
    RetryAttempt as ReliabilityRetryAttempt,
)

# V12.4: Retry Handler
from .retry_handler import (
    RetryAttempt,
    RetryHandler,
    RetryPolicy,
    RetryResult,
    RetryStats,
    get_retry_handler,
    reset_retry_handler,
)
from .task_scheduler import Priority, ScheduledTask, TaskScheduler, TaskStatus

# V12.4: Timeout Manager
from .timeout_manager import (
    Deadline,
    TimeoutConfig,
    TimeoutEvent,
    TimeoutManager,
    TimeoutStats,
    get_timeout_manager,
    reset_timeout_manager,
)

# V12.4 COGNITIVE BOOST: Tool Observer
from .tool_observer import (
    ObservationReport,
    ToolMetric,
    ToolObserver,
    ToolObserverStats,
    ToolSpan,
    get_tool_observer,
    reset_tool_observer,
)
from .tool_registry import ToolRegistry, get_tool_registry, reset_tool_registry
from .validation_service import ValidationService

# V12.4 Workflow Engine
from .workflow_engine import (
    ExecutionResult,
    StepStatus,
    Workflow,
    WorkflowEngine,
    WorkflowStatus,
    WorkflowStep,
)

__all__ = [
    # Core classes
    "ToolResult",
    "BaseHandler",
    "ToolRegistry",
    "ValidationService",
    "ExecutionEngine",
    # Factory functions
    "get_tool_registry",
    "reset_tool_registry",
    "get_execution_engine",
    "reset_execution_engine",
    # V12.4: Task Scheduler
    "TaskScheduler",
    "ScheduledTask",
    "Priority",
    "TaskStatus",
    # V12.4: Workflow Engine
    "WorkflowEngine",
    "Workflow",
    "WorkflowStep",
    "WorkflowStatus",
    "StepStatus",
    "ExecutionResult",
    # V12.4: Retry Handler
    "RetryHandler",
    "RetryPolicy",
    "RetryResult",
    "RetryAttempt",
    "RetryStats",
    "get_retry_handler",
    "reset_retry_handler",
    # V12.4: Timeout Manager
    "TimeoutManager",
    "TimeoutConfig",
    "Deadline",
    "TimeoutEvent",
    "TimeoutStats",
    "get_timeout_manager",
    "reset_timeout_manager",
    # V12.4 COGNITIVE BOOST: Tool Observer
    "ToolObserver",
    "ToolSpan",
    "ToolMetric",
    "ObservationReport",
    "ToolObserverStats",
    "get_tool_observer",
    "reset_tool_observer",
    # V12.4 COGNITIVE BOOST: Handler Performance Tracker
    "HandlerPerformanceTracker",
    "HandlerExecution",
    "HandlerTypeMetrics",
    "HandlerTrackerStats",
    "get_handler_tracker",
    "reset_handler_tracker",
    # V12.4 COGNITIVE BOOST: Reliability Pattern Tracker
    "ReliabilityPatternTracker",
    "ReliabilityRetryAttempt",
    "ToolReliabilityProfile",
    "ReliabilityStats",
    "get_reliability_tracker",
    "reset_reliability_tracker",
]

__version__ = "12.4.0"
