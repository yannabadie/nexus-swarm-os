"""
NEXUS V12.3 SCALE-OUT - Workflow Module

Redis-backed workflow registry with graceful degradation to in-memory.
Enables multi-instance deployment where workflows are visible across all nodes.

Components:
- RedisWorkflowRegistry: Redis-backed workflow storage
- DistributedLock: Redlock pattern for concurrent safety
- get_workflow_registry(): Factory function with graceful degradation

Author: Claude (NEXUS V12.3 SCALE-OUT)
Date: 2025-12-16
"""

# V12.4: Dependency Graph
from .dependency_graph import (
    ExecutionOrder,
    GraphStats,
    WorkflowDependencyGraph,
    WorkflowEdge,
    WorkflowNode,
    get_dependency_graph,
    reset_dependency_graph,
)
from .distributed_lock import (
    DistributedLock,
    LockAcquisitionError,
    acquire_workflow_lock,
    try_acquire_workflow_lock,
)
from .redis_registry import (
    RedisWorkflowRegistry,
    WorkflowStatus,
    get_workflow_registry,
    reset_workflow_registry,
)
from .workflow_performance_analyzer import (
    PerformanceStats as WorkflowPerformanceStats,
)

# V12.4 COGNITIVE BOOST: Workflow Performance Analyzer
from .workflow_performance_analyzer import (
    WorkflowPerformanceAnalyzer,
    WorkflowProfile,
    WorkflowRunRecord,
    get_workflow_analyzer,
    reset_workflow_analyzer,
)

__all__ = [
    # Registry
    "RedisWorkflowRegistry",
    "WorkflowStatus",
    "get_workflow_registry",
    "reset_workflow_registry",
    # Locks
    "DistributedLock",
    "LockAcquisitionError",
    "acquire_workflow_lock",
    "try_acquire_workflow_lock",
    # V12.4: Dependency Graph
    "WorkflowDependencyGraph",
    "WorkflowNode",
    "WorkflowEdge",
    "ExecutionOrder",
    "GraphStats",
    "get_dependency_graph",
    "reset_dependency_graph",
    # V12.4 COGNITIVE BOOST: Workflow Performance Analyzer
    "WorkflowPerformanceAnalyzer",
    "WorkflowRunRecord",
    "WorkflowProfile",
    "WorkflowPerformanceStats",
    "get_workflow_analyzer",
    "reset_workflow_analyzer",
]
