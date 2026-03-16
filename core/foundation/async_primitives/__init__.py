"""
NEXUS V9.5 Async Primitives
===========================

Core async building blocks for the Async-First architecture.

Components:
- CancellationToken: Hierarchical cancellation with propagation
- AsyncProcessHandle: Track subprocess by session_uuid
- AsyncRWLock: Multiple readers OR single writer lock
- AsyncBlackboard: Thread-safe async shared state
- SafeTaskManager: Fire-and-forget task error tracking (V9.5)
- EventBus: Lightweight async pub/sub for sync events (V9.5)

Usage:
    from core.foundation.async_primitives import (
        CancellationToken,
        AsyncProcessHandle,
        AsyncRWLock,
        AsyncBlackboard,
        SafeTaskManager,
        create_safe_task,
        EventBus,
        SyncEvent,
        get_event_bus,
    )
"""

from .blackboard import AsyncBlackboard
from .cancellation import CancellationToken
from .event_bus import EventBus, EventType, SyncEvent, get_event_bus
from .process_handle import AsyncProcessHandle
from .rwlock import AsyncRWLock
from .safe_task_manager import SafeTaskManager, create_safe_task

# V12.4 COGNITIVE BOOST: Task Metrics Collector
from .task_metrics_collector import (
    CollectorStats,
    TaskMetricsCollector,
    TaskRecord,
    TaskTypeMetrics,
    get_task_metrics_collector,
    reset_task_metrics_collector,
)

__all__ = [
    # Original V9.0
    "CancellationToken",
    "AsyncProcessHandle",
    "AsyncRWLock",
    "AsyncBlackboard",
    # V9.5 additions
    "SafeTaskManager",
    "create_safe_task",
    "EventBus",
    "SyncEvent",
    "EventType",
    "get_event_bus",
    # V12.4 COGNITIVE BOOST: Task Metrics Collector
    "TaskMetricsCollector",
    "TaskRecord",
    "TaskTypeMetrics",
    "CollectorStats",
    "get_task_metrics_collector",
    "reset_task_metrics_collector",
]

__version__ = "9.5.0"
