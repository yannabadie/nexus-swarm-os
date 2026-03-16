"""
NEXUS V12.4 - Foundation Package

P5.6 Phase 6: Package Consolidation

Consolidated foundational components for async primitives and agent management.

## 📦 Subpackages

- **async_primitives/**: Core async building blocks (CancellationToken, AsyncRWLock, SafeTaskManager)
- **agents/**: Agent registry, lifecycle management, capability profiling

## 🎯 Key Features

### Async Primitives
```python
from core.foundation import CancellationToken, AsyncBlackboard, SafeTaskManager

token = CancellationToken()
blackboard = AsyncBlackboard()
task_manager = SafeTaskManager()
```

### Agent Management
```python
from core.foundation import UnifiedAgentRegistry, AgentLifecycleManager

registry = get_registry()
lifecycle = get_lifecycle_manager()
```

## 📊 Migration Impact

**Statistics:**
- Files migrated: 12 Python files
- Import updates: TBD
- Commit: TBD
- Impact: TBD

---
**Status:** P5.6 Phase 6 IN PROGRESS | **Version:** V12.4
"""

# Async Primitives exports
# Agents exports
from core.foundation.agents import (
    KNOWN_CAPABILITIES,
    AgentCapability,
    AgentDescriptor,
    AgentHealthSnapshot,
    AgentInfo,
    AgentLifecycleManager,
    AgentProfile,
    AgentProvider,
    AgentService,
    CapabilityProfiler,
    CapabilityRecord,
    DriverProtocol,
    LifecycleEvent,
    LifecycleStats,
    MatchResult,
    PoolStats,
    RetirementPolicy,
    SpawnResult,
    UnifiedAgentRegistry,
    get_lifecycle_manager,
    get_registry,
    reset_lifecycle_manager,
)
from core.foundation.async_primitives import (
    AsyncBlackboard,
    AsyncProcessHandle,
    AsyncRWLock,
    CancellationToken,
    CollectorStats,
    EventBus,
    EventType,
    SafeTaskManager,
    SyncEvent,
    TaskMetricsCollector,
    TaskRecord,
    TaskTypeMetrics,
    create_safe_task,
    get_event_bus,
    get_task_metrics_collector,
    reset_task_metrics_collector,
)

__all__ = [
    # Async Primitives
    "CancellationToken",
    "AsyncProcessHandle",
    "AsyncRWLock",
    "AsyncBlackboard",
    "SafeTaskManager",
    "create_safe_task",
    "EventBus",
    "SyncEvent",
    "EventType",
    "get_event_bus",
    "TaskMetricsCollector",
    "TaskRecord",
    "TaskTypeMetrics",
    "CollectorStats",
    "get_task_metrics_collector",
    "reset_task_metrics_collector",
    # Agents
    "UnifiedAgentRegistry",
    "AgentDescriptor",
    "AgentProvider",
    "AgentCapability",
    "DriverProtocol",
    "get_registry",
    "AgentService",
    "SpawnResult",
    "AgentInfo",
    "PoolStats",
    "CapabilityProfiler",
    "AgentProfile",
    "CapabilityRecord",
    "MatchResult",
    "KNOWN_CAPABILITIES",
    "AgentLifecycleManager",
    "RetirementPolicy",
    "AgentHealthSnapshot",
    "LifecycleEvent",
    "LifecycleStats",
    "get_lifecycle_manager",
    "reset_lifecycle_manager",
]

__version__ = "12.4.0"
