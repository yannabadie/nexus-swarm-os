"""
NEXUS V10 CEREBRO - Events Package

Redis-based event bus for external UI observation.
Coexists with internal EventBus (core/async_primitives/event_bus.py).

Usage:
    from core.observability.events import CerebroEvent, CerebroEventType, get_redis_bus

    # Publish event
    event = CerebroEvent(
        event_type=CerebroEventType.INTERACTION_ASK,
        tenant_id="tenant_123",
        workspace_id="default",
        payload={"prompt": "Continue?"}
    )
    await get_redis_bus().publish(event)
"""

# V12.4 COGNITIVE BOOST: Event Analytics
from .event_analytics import (
    EventAnalytics,
    EventAnalyticsStats,
    EventRecord,
    EventTypeMetrics,
    get_event_analytics,
    reset_event_analytics,
)
from .redis_bus import RedisEventBus, get_redis_bus, reset_redis_bus
from .telemetry_bridge import TelemetryBridge, get_telemetry_bridge, reset_telemetry_bridge
from .types import CerebroEvent, CerebroEventType

__all__ = [
    "CerebroEvent",
    "CerebroEventType",
    "RedisEventBus",
    "get_redis_bus",
    "reset_redis_bus",
    # V10 SYNAPSE
    "TelemetryBridge",
    "get_telemetry_bridge",
    "reset_telemetry_bridge",
    # V12.4 COGNITIVE BOOST: Event Analytics
    "EventAnalytics",
    "EventRecord",
    "EventTypeMetrics",
    "EventAnalyticsStats",
    "get_event_analytics",
    "reset_event_analytics",
]
