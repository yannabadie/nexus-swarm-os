"""
NEXUS V10 CEREBRO - Redis Event Bus

Async Redis pub/sub bus for external UI observation.
Fire-and-forget publishing with graceful degradation.

Architecture:
- Singleton via __new__ + RLock (thread-safe)
- Connection pool with Redis.from_url()
- Graceful degradation: if Redis unavailable, uses IN-MEMORY pub/sub
- V12.0: Added in-memory fallback for development without Redis

Channel Format: nexus:{tenant_id}:{workspace_id}:{event_type}

Usage:
    bus = get_redis_bus()
    await bus.connect()

    # Publish (fire-and-forget)
    event = CerebroEvent(...)
    await bus.publish(event)

    # Subscribe (async iterator)
    async for event in bus.subscribe("tenant_1", "ws_1"):
        print(event)

    await bus.disconnect()
"""

import asyncio
import contextlib
import logging
import uuid
from collections.abc import AsyncIterator
from threading import RLock
from typing import Any, Optional

from .types import CerebroEvent, CerebroEventType

logger = logging.getLogger(__name__)


class RedisEventBus:
    """
    Async Redis pub/sub event bus for CEREBRO.

    Thread-safe singleton with graceful degradation.
    """

    _instance: Optional["RedisEventBus"] = None
    _lock = RLock()

    def __new__(cls) -> "RedisEventBus":
        """Singleton pattern with double-checked locking."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._initialized = False
                    cls._instance = instance
        return cls._instance

    def __init__(self):
        """Initialize bus (only runs once due to singleton)."""
        if self._initialized:
            return

        self._redis: Any | None = None  # redis.asyncio.Redis
        self._pubsub: Any | None = None  # redis.asyncio.PubSub
        self._url: str = "redis://localhost:6379"
        self._connected: bool = False
        self._subscriptions: set[str] = set()
        self._initialized = True

        # V12.0: In-memory pub/sub fallback (when Redis unavailable)
        # Key: (tenant_id, workspace_id), Value: dict of {subscriber_id: asyncio.Queue}
        self._memory_subscribers: dict[tuple[str, str], dict[str, asyncio.Queue]] = {}
        # Store reference to main event loop for thread-safe queue operations
        self._main_loop: asyncio.AbstractEventLoop | None = None

        # V13.0: In-memory state storage (F5 recovery without Redis)
        # Key: (tenant_id, workspace_id), Value: {phase: dict, nodes: dict, logs: list}
        self._memory_state: dict[tuple[str, str], dict[str, Any]] = {}

        logger.info("CEREBRO: RedisEventBus initialized with in-memory fallback support")

    def set_main_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Set the main event loop for thread-safe operations."""
        self._main_loop = loop
        logger.info("CEREBRO: Main event loop registered for in-memory pub/sub")

    async def connect(self, url: str = "redis://localhost:6379") -> bool:
        """
        Connect to Redis server.

        Args:
            url: Redis connection URL

        Returns:
            True if connected successfully, False otherwise
        """
        if self._connected:
            return True

        self._url = url

        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(
                url,
                encoding="utf-8",
                decode_responses=True,
                health_check_interval=30,
                socket_connect_timeout=5.0,
                socket_timeout=5.0,
            )

            # Test connection
            await self._redis.ping()
            self._connected = True
            logger.info(f"CEREBRO: Connected to Redis at {url}")
            return True

        except ImportError:
            logger.warning("CEREBRO: redis package not installed, running in degraded mode")
            return False
        except Exception as e:
            logger.warning(f"CEREBRO: Failed to connect to Redis: {e}")
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Disconnect from Redis server."""
        if self._pubsub:
            with contextlib.suppress(Exception):
                await self._pubsub.close()
            self._pubsub = None

        if self._redis:
            with contextlib.suppress(Exception):
                await self._redis.aclose()
            self._redis = None

        self._connected = False
        self._subscriptions.clear()
        logger.info("CEREBRO: Disconnected from Redis")

    async def publish(self, event: CerebroEvent) -> bool:
        """
        Publish event to Redis or in-memory subscribers.

        V12.0: Falls back to in-memory pub/sub when Redis unavailable.

        Args:
            event: CerebroEvent to publish

        Returns:
            True if published successfully, False otherwise (graceful degradation)
        """
        # Try Redis first
        if self._connected and self._redis is not None:
            try:
                channel = event.channel_name()
                await self._redis.publish(channel, event.to_json())
                logger.debug(f"CEREBRO: Published {event.event_type.value} to Redis")
                return True
            except Exception as e:
                logger.warning(f"CEREBRO: Failed to publish to Redis: {e}")
                # Fall through to in-memory

        # V12.0: In-memory fallback
        key = (event.tenant_id, event.workspace_id)
        subscribers = self._memory_subscribers.get(key, {})

        logger.debug(
            f"CEREBRO: In-memory publish attempt - key={key}, subscribers={len(subscribers)}, event={event.event_type.value}"
        )

        if not subscribers:
            # Log at INFO level for debugging this issue
            logger.info(f"CEREBRO: No subscribers for {key}, available keys: {list(self._memory_subscribers.keys())}")
            return False

        # Push to all subscriber queues
        # NOTE: asyncio.Queue is NOT thread-safe, so we use call_soon_threadsafe
        published_count = 0

        # Determine if we're in the main loop or a worker thread
        try:
            current_loop = asyncio.get_running_loop()
            in_main_loop = self._main_loop is None or current_loop == self._main_loop
        except RuntimeError:
            # No running loop - we're in a worker thread
            in_main_loop = False

        for sub_id, queue in list(subscribers.items()):
            try:
                if in_main_loop:
                    # Same loop - direct put
                    queue.put_nowait(event)
                    published_count += 1
                    logger.debug(f"CEREBRO: Event {event.event_type.value} queued for {sub_id[:8]}...")
                elif self._main_loop and self._main_loop.is_running():
                    # Different thread - use thread-safe call
                    self._main_loop.call_soon_threadsafe(queue.put_nowait, event)
                    published_count += 1
                    logger.debug(f"CEREBRO: Event {event.event_type.value} queued (threadsafe) for {sub_id[:8]}...")
                else:
                    logger.warning("CEREBRO: Main loop not available for thread-safe publish")
            except asyncio.QueueFull:
                logger.warning(f"CEREBRO: Queue full for subscriber {sub_id}, dropping event")
            except Exception as e:
                logger.warning(f"CEREBRO: Failed to queue event for {sub_id}: {e}")

        if published_count > 0:
            logger.info(f"CEREBRO: Published {event.event_type.value} to {published_count} in-memory subscriber(s)")
            return True

        return False

    async def subscribe(
        self, tenant_id: str, workspace_id: str, event_types: list[CerebroEventType] | None = None
    ) -> AsyncIterator[CerebroEvent]:
        """
        Subscribe to events for a tenant/workspace.

        V12.0: Uses in-memory pub/sub when Redis unavailable.

        Args:
            tenant_id: Tenant identifier
            workspace_id: Workspace identifier
            event_types: List of event types to subscribe to (None = all)

        Yields:
            CerebroEvent instances as they arrive

        Example:
            async for event in bus.subscribe("t1", "ws1"):
                print(event.payload)
        """
        # Try Redis first
        if self._connected and self._redis is not None:
            pubsub = None
            try:
                pubsub = self._redis.pubsub()

                # Build patterns
                if event_types:
                    patterns = [CerebroEvent.wildcard_channel(tenant_id, workspace_id, et) for et in event_types]
                else:
                    patterns = [CerebroEvent.wildcard_channel(tenant_id, workspace_id)]

                # Subscribe to patterns
                for pattern in patterns:
                    await pubsub.psubscribe(pattern)
                    self._subscriptions.add(pattern)
                    logger.debug(f"CEREBRO: Subscribed to Redis pattern: {pattern}")

                # Yield events from Redis
                async for message in pubsub.listen():
                    if message["type"] == "pmessage":
                        try:
                            event = CerebroEvent.from_json(message["data"])
                            yield event
                        except Exception as e:
                            logger.warning(f"CEREBRO: Failed to parse event: {e}")

            except asyncio.CancelledError:
                logger.debug("CEREBRO: Redis subscription cancelled")
                raise
            except Exception as e:
                logger.error(f"CEREBRO: Redis subscription error: {e}")
            finally:
                if pubsub:
                    with contextlib.suppress(Exception):
                        await pubsub.close()
            return

        # V12.0: In-memory fallback
        logger.info(f"CEREBRO: Entering in-memory subscription mode for ({tenant_id}, {workspace_id})")

        key = (tenant_id, workspace_id)
        sub_id = str(uuid.uuid4())
        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)

        # Register subscriber
        if key not in self._memory_subscribers:
            self._memory_subscribers[key] = {}
        self._memory_subscribers[key][sub_id] = queue
        logger.info(
            f"CEREBRO: In-memory subscriber registered: {sub_id} for {key}, total subs: {len(self._memory_subscribers[key])}"
        )

        try:
            # Filter event types if specified
            filter_types = set(et.value for et in event_types) if event_types else None

            logger.info(f"CEREBRO: In-memory subscriber {sub_id[:8]}... entering event loop")

            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=60.0)

                    # Apply event type filter
                    if filter_types and event.event_type.value not in filter_types:
                        logger.debug(f"CEREBRO: Event {event.event_type.value} filtered out for {sub_id[:8]}")
                        continue

                    logger.info(f"CEREBRO: Yielding event {event.event_type.value} to subscriber {sub_id[:8]}...")
                    yield event
                except TimeoutError:
                    # No events for 60s, continue waiting
                    logger.debug(f"CEREBRO: No events for 60s, subscriber {sub_id[:8]} still waiting...")
                    continue

        except asyncio.CancelledError:
            logger.debug(f"CEREBRO: In-memory subscription cancelled: {sub_id}")
            raise
        except Exception as e:
            logger.error(f"CEREBRO: In-memory subscription error: {e}")
        finally:
            # Unregister subscriber
            if key in self._memory_subscribers and sub_id in self._memory_subscribers[key]:
                del self._memory_subscribers[key][sub_id]
                if not self._memory_subscribers[key]:
                    del self._memory_subscribers[key]
                logger.info(f"CEREBRO: In-memory subscriber unregistered: {sub_id}")

    def is_connected(self) -> bool:
        """Check if connected to Redis."""
        return self._connected

    def can_stream(self) -> bool:
        """
        Check if event streaming is available (Redis or in-memory).

        V12.0: Always returns True since in-memory fallback is available.

        Returns:
            True (streaming always available via Redis or in-memory)
        """
        return True

    def get_subscriber_count(self, tenant_id: str = None, workspace_id: str = None) -> int:
        """
        Get count of in-memory subscribers.

        Args:
            tenant_id: Filter by tenant (optional)
            workspace_id: Filter by workspace (optional)

        Returns:
            Number of active in-memory subscribers
        """
        if tenant_id and workspace_id:
            key = (tenant_id, workspace_id)
            return len(self._memory_subscribers.get(key, {}))

        total = 0
        for subs in self._memory_subscribers.values():
            total += len(subs)
        return total

    async def health_check(self) -> dict[str, Any]:
        """
        Perform health check on Redis connection.

        Returns:
            Health status dict with connected, latency_ms, etc.
        """
        result = {
            "connected": self._connected,
            "url": self._url,
            "subscriptions": len(self._subscriptions),
        }

        if self._connected and self._redis:
            try:
                import time

                start = time.perf_counter()
                await self._redis.ping()
                latency = (time.perf_counter() - start) * 1000
                result["latency_ms"] = round(latency, 2)
                result["status"] = "healthy"
            except Exception as e:
                result["status"] = "unhealthy"
                result["error"] = str(e)
        else:
            result["status"] = "disconnected"

        return result

    async def get_info(self) -> dict[str, Any]:
        """
        Get Redis server info.

        Returns:
            Redis INFO dict or empty dict if not connected
        """
        if not self._connected or self._redis is None:
            return {}

        try:
            info = await self._redis.info()
            return {
                "redis_version": info.get("redis_version"),
                "connected_clients": info.get("connected_clients"),
                "used_memory_human": info.get("used_memory_human"),
                "pubsub_channels": info.get("pubsub_channels"),
                "pubsub_patterns": info.get("pubsub_patterns"),
            }
        except Exception:
            return {}

    # =========================================================================
    # V13.0: In-Memory State Storage (F5 Recovery without Redis)
    # =========================================================================

    def _get_state_key(self, tenant_id: str, workspace_id: str) -> tuple[str, str]:
        """Get state key tuple."""
        return (tenant_id, workspace_id)

    def _ensure_state_exists(self, key: tuple[str, str]) -> dict[str, Any]:
        """Ensure state dict exists for key, return it."""
        if key not in self._memory_state:
            self._memory_state[key] = {
                "phase": None,
                "nodes": {},
                "logs": [],
            }
        return self._memory_state[key]

    def set_phase_state(self, tenant_id: str, workspace_id: str, phase_data: dict[str, Any]) -> None:
        """Set phase state (in-memory)."""
        key = self._get_state_key(tenant_id, workspace_id)
        state = self._ensure_state_exists(key)
        state["phase"] = phase_data
        logger.debug(f"CEREBRO: Phase state set for {key}")

    def get_phase_state(self, tenant_id: str, workspace_id: str) -> dict[str, Any] | None:
        """Get phase state (in-memory)."""
        key = self._get_state_key(tenant_id, workspace_id)
        state = self._memory_state.get(key)
        return state.get("phase") if state else None

    def set_node(self, tenant_id: str, workspace_id: str, node_id: str, node_data: dict[str, Any]) -> None:
        """Set or update a graph node (in-memory)."""
        key = self._get_state_key(tenant_id, workspace_id)
        state = self._ensure_state_exists(key)
        state["nodes"][node_id] = node_data
        logger.debug(f"CEREBRO: Node {node_id} set for {key}")

    def get_nodes(self, tenant_id: str, workspace_id: str) -> dict[str, dict[str, Any]]:
        """Get all graph nodes (in-memory)."""
        key = self._get_state_key(tenant_id, workspace_id)
        state = self._memory_state.get(key)
        return state.get("nodes", {}) if state else {}

    def add_log(self, tenant_id: str, workspace_id: str, log_entry: dict[str, Any]) -> None:
        """Add a log entry (in-memory, max 100)."""
        key = self._get_state_key(tenant_id, workspace_id)
        state = self._ensure_state_exists(key)
        logs = state["logs"]
        logs.insert(0, log_entry)  # Most recent first
        if len(logs) > 100:
            state["logs"] = logs[:100]  # Keep only 100 most recent
        logger.debug(f"CEREBRO: Log entry added for {key}, total={len(state['logs'])}")

    def get_logs(self, tenant_id: str, workspace_id: str) -> list[dict[str, Any]]:
        """Get log entries (in-memory)."""
        key = self._get_state_key(tenant_id, workspace_id)
        state = self._memory_state.get(key)
        return state.get("logs", []) if state else []

    def clear_state(self, tenant_id: str, workspace_id: str) -> None:
        """Clear all state for a tenant/workspace."""
        key = self._get_state_key(tenant_id, workspace_id)
        if key in self._memory_state:
            del self._memory_state[key]
            logger.debug(f"CEREBRO: State cleared for {key}")

    def get_full_state(self, tenant_id: str, workspace_id: str) -> dict[str, Any]:
        """Get full state snapshot (for API)."""
        key = self._get_state_key(tenant_id, workspace_id)
        state = self._memory_state.get(key)
        if state:
            return {
                "phase": state.get("phase"),
                "nodes": state.get("nodes", {}),
                "logs": state.get("logs", []),
            }
        return {"phase": None, "nodes": {}, "logs": []}


# =============================================================================
# Module-Level Singleton Access
# =============================================================================

_redis_bus: RedisEventBus | None = None


def get_redis_bus() -> RedisEventBus:
    """
    Get the global RedisEventBus singleton.

    Returns:
        RedisEventBus instance (may not be connected yet)
    """
    global _redis_bus
    if _redis_bus is None:
        _redis_bus = RedisEventBus()
    return _redis_bus


def reset_redis_bus() -> None:
    """
    Reset the global RedisEventBus singleton (for testing).

    Note: Does NOT disconnect - call disconnect() first if needed.
    """
    global _redis_bus
    RedisEventBus._instance = None
    _redis_bus = None


# =============================================================================
# Convenience Functions
# =============================================================================


async def publish_event(event: CerebroEvent) -> bool:
    """
    Quick publish function (uses global bus).

    Args:
        event: CerebroEvent to publish

    Returns:
        True if published, False otherwise
    """
    bus = get_redis_bus()
    return await bus.publish(event)


async def publish_interaction(event_type: CerebroEventType, tenant_id: str, workspace_id: str, **payload) -> bool:
    """
    Quick publish for interaction events.

    Args:
        event_type: Must be INTERACTION_* type
        tenant_id: Tenant identifier
        workspace_id: Workspace identifier
        **payload: Event payload fields

    Returns:
        True if published, False otherwise
    """
    event = CerebroEvent(
        event_type=event_type,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        payload=payload,
    )
    return await publish_event(event)
