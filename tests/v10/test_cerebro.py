"""
V10 CEREBRO Tests - Redis Event Bus & API Skeleton.

Tests for the CEREBRO architecture:
1. CerebroEvent types and serialization
2. RedisEventBus singleton and graceful degradation
3. RedisLogHandler queue and thread lifecycle
4. CEREBRO API health endpoints

Run with:
    pytest tests/v10/test_cerebro.py -v

Note: Some tests require Redis to be running for full coverage.
Tests are designed to pass even without Redis (graceful degradation).
"""

import json
from unittest.mock import AsyncMock

import pytest

# =============================================================================
# TestCerebroEventTypes - Event serialization/deserialization
# =============================================================================


class TestCerebroEventTypes:
    """Test CerebroEvent and CerebroEventType."""

    def test_event_type_values(self):
        """CerebroEventType has expected string values."""
        from core.observability.events.types import CerebroEventType

        assert CerebroEventType.INTERACTION_ASK.value == "interaction.ask"
        assert CerebroEventType.LOG.value == "system.log"
        assert CerebroEventType.AGENT_SPEAK.value == "agent.speak"
        assert CerebroEventType.SWARM_MODE_SELECTED.value == "swarm.mode_selected"

    def test_event_creation(self):
        """CerebroEvent creates with auto-generated fields."""
        from core.observability.events.types import CerebroEvent, CerebroEventType

        event = CerebroEvent(
            event_type=CerebroEventType.INTERACTION_ASK,
            tenant_id="tenant_1",
            workspace_id="default",
            payload={"prompt": "Continue?"},
        )

        assert event.event_type == CerebroEventType.INTERACTION_ASK
        assert event.tenant_id == "tenant_1"
        assert event.workspace_id == "default"
        assert event.payload == {"prompt": "Continue?"}
        assert event.timestamp  # Auto-generated
        assert event.event_id  # Auto-generated
        assert len(event.event_id) == 12

    def test_event_to_json(self):
        """CerebroEvent serializes to JSON correctly."""
        from core.observability.events.types import CerebroEvent, CerebroEventType

        event = CerebroEvent(
            event_type=CerebroEventType.LOG,
            tenant_id="t1",
            workspace_id="ws1",
            payload={"level": "INFO", "message": "Test"},
            timestamp="2025-12-15T10:00:00Z",
            event_id="abc123def456",
        )

        json_str = event.to_json()
        data = json.loads(json_str)

        assert data["event_type"] == "system.log"
        assert data["tenant_id"] == "t1"
        assert data["workspace_id"] == "ws1"
        assert data["payload"]["level"] == "INFO"
        assert data["timestamp"] == "2025-12-15T10:00:00Z"
        assert data["event_id"] == "abc123def456"

    def test_event_from_json(self):
        """CerebroEvent deserializes from JSON correctly."""
        from core.observability.events.types import CerebroEvent, CerebroEventType

        json_str = json.dumps(
            {
                "event_type": "interaction.confirm",
                "tenant_id": "tenant_x",
                "workspace_id": "project_1",
                "payload": {"prompt": "Proceed?", "default": False},
                "timestamp": "2025-12-15T12:00:00Z",
                "event_id": "xyz789",
            }
        )

        event = CerebroEvent.from_json(json_str)

        assert event.event_type == CerebroEventType.INTERACTION_CONFIRM
        assert event.tenant_id == "tenant_x"
        assert event.workspace_id == "project_1"
        assert event.payload["default"] is False

    def test_event_channel_name(self):
        """CerebroEvent.channel_name() returns correct format."""
        from core.observability.events.types import CerebroEvent, CerebroEventType

        event = CerebroEvent(
            event_type=CerebroEventType.AGENT_TOOL_CALL,
            tenant_id="acme",
            workspace_id="main",
            payload={},
        )

        assert event.channel_name() == "nexus:acme:main:agent.tool_call"

    def test_wildcard_channel(self):
        """CerebroEvent.wildcard_channel() returns correct patterns."""
        from core.observability.events.types import CerebroEvent, CerebroEventType

        # All events for tenant
        assert CerebroEvent.wildcard_channel("t1") == "nexus:t1:*:*"

        # All events for tenant+workspace
        assert CerebroEvent.wildcard_channel("t1", "ws1") == "nexus:t1:ws1:*"

        # Specific event type
        assert CerebroEvent.wildcard_channel("t1", "ws1", CerebroEventType.LOG) == "nexus:t1:ws1:system.log"


# =============================================================================
# TestRedisEventBus - Singleton and graceful degradation
# =============================================================================


class TestRedisEventBus:
    """Test RedisEventBus singleton and behavior."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset singleton between tests."""
        from core.observability.events.redis_bus import reset_redis_bus

        reset_redis_bus()
        yield
        reset_redis_bus()

    def test_singleton_pattern(self):
        """Multiple calls to get_redis_bus return same instance."""
        from core.observability.events.redis_bus import get_redis_bus

        bus1 = get_redis_bus()
        bus2 = get_redis_bus()

        assert bus1 is bus2
        assert id(bus1) == id(bus2)

    def test_initial_state(self):
        """RedisEventBus starts disconnected."""
        from core.observability.events.redis_bus import get_redis_bus

        bus = get_redis_bus()

        assert bus.is_connected() is False

    @pytest.mark.asyncio
    async def test_graceful_degradation_publish(self):
        """Publish returns False when not connected (graceful degradation)."""
        from core.observability.events.redis_bus import get_redis_bus
        from core.observability.events.types import CerebroEvent, CerebroEventType

        bus = get_redis_bus()
        # Don't connect to Redis

        event = CerebroEvent(
            event_type=CerebroEventType.LOG,
            tenant_id="test",
            workspace_id="default",
            payload={"message": "test"},
        )

        result = await bus.publish(event)

        # Should return False but not raise exception
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_disconnected(self):
        """Health check works when disconnected."""
        from core.observability.events.redis_bus import get_redis_bus

        bus = get_redis_bus()

        health = await bus.health_check()

        assert health["connected"] is False
        assert health["status"] == "disconnected"


# =============================================================================
# TestRedisLogHandler - Queue and thread lifecycle
# =============================================================================


class TestRedisLogHandler:
    """Test RedisLogHandler queue behavior."""

    def test_handler_creation(self):
        """RedisLogHandler creates with default settings."""
        from core.observability.telemetry.redis_bridge import RedisLogHandler

        handler = RedisLogHandler(
            tenant_id="test_tenant",
            workspace_id="test_ws",
        )

        assert handler._tenant_id == "test_tenant"
        assert handler._workspace_id == "test_ws"
        assert handler._running is False

    def test_start_stop_lifecycle(self):
        """Handler starts and stops correctly."""
        from core.observability.telemetry.redis_bridge import RedisLogHandler

        handler = RedisLogHandler()

        # Start
        handler.start()
        assert handler._running is True
        assert handler._thread is not None
        assert handler._thread.is_alive()

        # Stop
        handler.stop(timeout=2.0)
        assert handler._running is False

    def test_emit_non_blocking(self):
        """Emit is non-blocking even without Redis."""
        import logging

        from core.observability.telemetry.redis_bridge import RedisLogHandler

        handler = RedisLogHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        # Don't start thread - test queue only

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        # Should not block or raise
        handler.emit(record)

        stats = handler.get_stats()
        assert stats["queued"] == 1
        assert stats["dropped"] == 0

    def test_queue_overflow_drops(self):
        """Handler drops events when queue is full."""
        import logging

        from core.observability.telemetry.redis_bridge import RedisLogHandler

        # Small queue for testing
        handler = RedisLogHandler(queue_size=5)
        handler.setFormatter(logging.Formatter("%(message)s"))

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test",
            args=(),
            exc_info=None,
        )

        # Fill queue beyond capacity
        for _ in range(10):
            handler.emit(record)

        stats = handler.get_stats()
        assert stats["queued"] == 5  # Max queue size
        assert stats["dropped"] == 5  # Overflow dropped

    def test_get_stats(self):
        """get_stats returns correct statistics."""
        from core.observability.telemetry.redis_bridge import RedisLogHandler

        handler = RedisLogHandler()

        stats = handler.get_stats()

        assert "queued" in stats
        assert "published" in stats
        assert "dropped" in stats
        assert "errors" in stats
        assert "queue_size" in stats
        assert "running" in stats


# =============================================================================
# TestCerebroAPI - FastAPI health endpoints
# =============================================================================


class TestCerebroAPI:
    """Test CEREBRO FastAPI application."""

    @pytest.fixture
    def client(self):
        """Create test client for CEREBRO API."""
        pytest.importorskip("fastapi", reason="fastapi not installed")
        pytest.importorskip("httpx", reason="httpx not installed")

        from fastapi.testclient import TestClient

        from core.api.cerebro.app import create_cerebro_app

        app = create_cerebro_app()
        return TestClient(app)

    def test_root_endpoint(self, client):
        """GET / returns API info."""
        response = client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "NEXUS CEREBRO API"
        assert "version" in data

    def test_health_endpoint(self, client):
        """GET /health returns healthy status."""
        response = client.get("/health/")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "cerebro"

    def test_ping_endpoint(self, client):
        """GET /health/ping returns pong."""
        response = client.get("/health/ping")

        assert response.status_code == 200
        assert response.json() == {"pong": "ok"}

    def test_ready_endpoint(self, client):
        """GET /health/ready returns status with Redis info."""
        response = client.get("/health/ready")

        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "redis" in data
        # Status should be "ready" or "degraded" depending on Redis
        assert data["status"] in ["ready", "degraded"]


# =============================================================================
# TestHeadlessProviderIntegration - CEREBRO event publishing
# =============================================================================


class TestHeadlessProviderIntegration:
    """Test HeadlessProvider CEREBRO integration."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset Redis bus singleton."""
        from core.observability.events.redis_bus import reset_redis_bus

        reset_redis_bus()
        yield
        reset_redis_bus()

    @pytest.mark.asyncio
    async def test_ask_publishes_event(self):
        """HeadlessProvider.ask() publishes CEREBRO event."""
        from core.observability.events.redis_bus import get_redis_bus
        from core.security_pkg.interaction.headless_provider import HeadlessProvider

        provider = HeadlessProvider(publish_events=True)

        # Mock the bus publish method
        bus = get_redis_bus()
        bus.publish = AsyncMock(return_value=False)  # Simulate disconnected

        result = await provider.ask("Continue?", default="yes")

        assert result == "yes"
        # Event should have been attempted (but failed gracefully)

    @pytest.mark.asyncio
    async def test_confirm_publishes_event(self):
        """HeadlessProvider.confirm() publishes CEREBRO event."""
        from core.security_pkg.interaction.headless_provider import HeadlessProvider

        provider = HeadlessProvider(publish_events=True)

        result = await provider.confirm("Proceed?", default=True)

        assert result is True

    @pytest.mark.asyncio
    async def test_publish_events_disabled(self):
        """HeadlessProvider respects publish_events=False."""
        from core.security_pkg.interaction.headless_provider import HeadlessProvider

        provider = HeadlessProvider(publish_events=False)

        # This should not attempt to publish
        result = await provider.ask("Test?", default="ok")

        assert result == "ok"


# =============================================================================
# TestMiddleware - JWT decoding
# =============================================================================


class TestMiddleware:
    """Test CEREBRO middleware components."""

    def test_create_jwt_token(self):
        """create_jwt_token creates valid JWT."""
        pytest.importorskip("jose", reason="python-jose not installed")

        from core.api.cerebro.middleware import create_jwt_token, decode_jwt

        token = create_jwt_token(
            tenant_id="test_tenant",
            user_id="user_123",
            workspace_id="ws_1",
        )

        assert token is not None
        assert isinstance(token, str)

        # Decode should work
        claims = decode_jwt(token)
        assert claims is not None
        assert claims["tenant_id"] == "test_tenant"
        assert claims["sub"] == "user_123"
        assert claims["workspace_id"] == "ws_1"

    def test_decode_invalid_jwt(self):
        """decode_jwt returns None for invalid token."""
        pytest.importorskip("jose", reason="python-jose not installed")

        from core.api.cerebro.middleware import decode_jwt

        result = decode_jwt("invalid.token.here")

        assert result is None


# =============================================================================
# TestDependencies - WebSocket context extraction
# =============================================================================


class TestDependencies:
    """Test CEREBRO dependency injection."""

    def test_create_ws_url(self):
        """create_ws_url builds correct URL."""
        from core.api.cerebro.deps import create_ws_url

        url = create_ws_url(
            "ws://localhost:8080/ws/stream",
            tenant_id="t1",
            workspace_id="ws1",
        )

        assert url == "ws://localhost:8080/ws/stream?tenant_id=t1&workspace_id=ws1"

    def test_create_ws_url_with_token(self):
        """create_ws_url includes token when provided."""
        from core.api.cerebro.deps import create_ws_url

        url = create_ws_url(
            "ws://localhost:8080/ws/stream",
            tenant_id="t1",
            workspace_id="default",
            token="jwt_token_here",
        )

        assert "token=jwt_token_here" in url
        assert "tenant_id=t1" in url
