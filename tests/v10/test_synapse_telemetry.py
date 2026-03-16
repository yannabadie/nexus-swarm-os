"""
V10 SYNAPSE Telemetry Tests - TelemetryBridge & Instrumentation.

Tests for the SYNAPSE telemetry architecture:
1. TelemetryBridge singleton and correlation tracking
2. Payload truncation
3. New SYNAPSE event types
4. CerebroEvent correlation fields

Run with:
    pytest tests/v10/test_synapse_telemetry.py -v

Note: Tests are designed to work without Redis (mock RedisEventBus).
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# =============================================================================
# TestTelemetryBridge - Singleton and correlation tracking
# =============================================================================


class TestTelemetryBridge:
    """Test TelemetryBridge singleton and behavior."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset singleton between tests."""
        from core.observability.events.telemetry_bridge import reset_telemetry_bridge

        reset_telemetry_bridge()
        yield
        reset_telemetry_bridge()

    def test_singleton_pattern(self):
        """Multiple calls to get_telemetry_bridge return same instance."""
        from core.observability.events.telemetry_bridge import get_telemetry_bridge

        bridge1 = get_telemetry_bridge()
        bridge2 = get_telemetry_bridge()

        assert bridge1 is bridge2
        assert id(bridge1) == id(bridge2)

    def test_start_trace_returns_id(self):
        """start_trace returns a trace ID."""
        from core.observability.events.telemetry_bridge import get_telemetry_bridge

        bridge = get_telemetry_bridge()
        trace_id = bridge.start_trace()

        assert trace_id is not None
        assert isinstance(trace_id, str)
        assert len(trace_id) == 12  # secrets.token_hex(6) = 12 chars

    def test_start_trace_custom_id(self):
        """start_trace with custom ID uses that ID."""
        from core.observability.events.telemetry_bridge import get_telemetry_bridge

        bridge = get_telemetry_bridge()
        trace_id = bridge.start_trace(trace_id="custom123")

        assert trace_id == "custom123"

    def test_get_correlation_id_before_trace(self):
        """get_correlation_id returns None when no trace active."""
        from core.observability.events.telemetry_bridge import get_telemetry_bridge

        bridge = get_telemetry_bridge()

        assert bridge.get_correlation_id() is None

    def test_get_correlation_id_during_trace(self):
        """get_correlation_id returns trace ID during trace."""
        from core.observability.events.telemetry_bridge import get_telemetry_bridge

        bridge = get_telemetry_bridge()
        trace_id = bridge.start_trace()

        assert bridge.get_correlation_id() == trace_id

    def test_end_trace_clears_correlation(self):
        """end_trace clears the correlation ID."""
        from core.observability.events.telemetry_bridge import get_telemetry_bridge

        bridge = get_telemetry_bridge()
        bridge.start_trace()
        bridge.end_trace()

        assert bridge.get_correlation_id() is None

    def test_sequence_numbers_increment(self):
        """Sequence numbers increment within a trace."""
        from core.observability.events.telemetry_bridge import get_telemetry_bridge

        bridge = get_telemetry_bridge()
        bridge.start_trace()

        seq1 = bridge._next_seq()
        seq2 = bridge._next_seq()
        seq3 = bridge._next_seq()

        assert seq1 == 1
        assert seq2 == 2
        assert seq3 == 3

    def test_sequence_resets_on_new_trace(self):
        """Sequence numbers reset when starting a new trace."""
        from core.observability.events.telemetry_bridge import get_telemetry_bridge

        bridge = get_telemetry_bridge()

        bridge.start_trace()
        bridge._next_seq()
        bridge._next_seq()
        bridge.end_trace()

        bridge.start_trace()
        seq = bridge._next_seq()

        assert seq == 1

    def test_payload_truncation_small(self):
        """Small payloads are not truncated."""
        from core.observability.events.telemetry_bridge import get_telemetry_bridge

        bridge = get_telemetry_bridge()
        payload = {"message": "Hello"}

        result, truncated = bridge._truncate_payload(payload)

        assert truncated is False
        assert result == payload

    def test_payload_truncation_large(self):
        """Large payloads are truncated."""
        from core.observability.events.telemetry_bridge import MAX_PAYLOAD_SIZE, get_telemetry_bridge

        bridge = get_telemetry_bridge()
        # Create payload larger than MAX_PAYLOAD_SIZE
        payload = {"content": "x" * (MAX_PAYLOAD_SIZE + 500)}

        result, truncated = bridge._truncate_payload(payload)

        assert truncated is True
        assert len(result["content"]) < len(payload["content"])
        assert result["content"].endswith("...")

    @pytest.mark.asyncio
    async def test_emit_async_with_mock_bus(self):
        """Async emit works with mocked bus."""
        from core.observability.events import redis_bus
        from core.observability.events.telemetry_bridge import get_telemetry_bridge
        from core.observability.events.types import CerebroEventType

        bridge = get_telemetry_bridge()

        # Create mock bus
        mock_bus = MagicMock()
        mock_bus.publish = AsyncMock(return_value=True)

        with patch.object(redis_bus, "get_redis_bus", return_value=mock_bus):
            result = await bridge.emit(CerebroEventType.HIVE_STATE_CHANGE, {"state": "test"})

            assert result is True
            mock_bus.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_emit_includes_correlation_id(self):
        """Emit includes correlation ID when trace is active."""
        from core.observability.events import redis_bus
        from core.observability.events.telemetry_bridge import get_telemetry_bridge
        from core.observability.events.types import CerebroEventType

        bridge = get_telemetry_bridge()
        trace_id = bridge.start_trace()

        mock_bus = MagicMock()
        mock_bus.publish = AsyncMock(return_value=True)

        with patch.object(redis_bus, "get_redis_bus", return_value=mock_bus):
            await bridge.emit(CerebroEventType.HIVE_STATE_CHANGE, {"state": "test"})

            # Check the event passed to publish
            call_args = mock_bus.publish.call_args[0][0]
            assert call_args.correlation_id == trace_id
            assert call_args.sequence_number == 1

    def test_emit_sync_without_loop(self):
        """emit_sync works when no event loop is running."""
        from core.observability.events import redis_bus
        from core.observability.events.telemetry_bridge import get_telemetry_bridge
        from core.observability.events.types import CerebroEventType

        bridge = get_telemetry_bridge()

        mock_bus = MagicMock()
        mock_bus.publish = AsyncMock(return_value=False)

        with patch.object(redis_bus, "get_redis_bus", return_value=mock_bus):
            result = bridge.emit_sync(CerebroEventType.HIVE_STATE_CHANGE, {"state": "test"})

            # Should return False (mocked bus returns False)
            assert result is False


# =============================================================================
# TestEventTypesSynapse - New SYNAPSE event types
# =============================================================================


class TestEventTypesSynapse:
    """Test new SYNAPSE event types."""

    def test_hive_event_types_exist(self):
        """HiveMind SYNAPSE event types are defined."""
        from core.observability.events.types import CerebroEventType

        assert hasattr(CerebroEventType, "HIVE_STATE_CHANGE")
        assert hasattr(CerebroEventType, "HIVE_PHASE_START")
        assert hasattr(CerebroEventType, "HIVE_PHASE_END")

        assert CerebroEventType.HIVE_STATE_CHANGE.value == "hive.state_change"
        assert CerebroEventType.HIVE_PHASE_START.value == "hive.phase_start"
        assert CerebroEventType.HIVE_PHASE_END.value == "hive.phase_end"

    def test_graph_event_types_exist(self):
        """Graph (React Flow) SYNAPSE event types are defined."""
        from core.observability.events.types import CerebroEventType

        assert hasattr(CerebroEventType, "GRAPH_NODE_SPAWN")
        assert hasattr(CerebroEventType, "GRAPH_NODE_UPDATE")
        assert hasattr(CerebroEventType, "GRAPH_EDGE_MESSAGE")

        assert CerebroEventType.GRAPH_NODE_SPAWN.value == "graph.node_spawn"
        assert CerebroEventType.GRAPH_NODE_UPDATE.value == "graph.node_update"
        assert CerebroEventType.GRAPH_EDGE_MESSAGE.value == "graph.edge_message"

    def test_swarm_phase_change_exists(self):
        """Swarm phase change event type is defined."""
        from core.observability.events.types import CerebroEventType

        assert hasattr(CerebroEventType, "SWARM_PHASE_CHANGE")
        assert CerebroEventType.SWARM_PHASE_CHANGE.value == "swarm.phase_change"


# =============================================================================
# TestCerebroEventCorrelation - Correlation fields
# =============================================================================


class TestCerebroEventCorrelation:
    """Test CerebroEvent correlation fields."""

    def test_cerebro_event_has_correlation_fields(self):
        """CerebroEvent has correlation_id and sequence_number fields."""
        from core.observability.events.types import CerebroEvent, CerebroEventType

        event = CerebroEvent(
            event_type=CerebroEventType.HIVE_STATE_CHANGE,
            tenant_id="test",
            workspace_id="default",
            payload={"test": True},
            correlation_id="trace123",
            sequence_number=5,
        )

        assert event.correlation_id == "trace123"
        assert event.sequence_number == 5

    def test_cerebro_event_correlation_defaults_to_none(self):
        """Correlation fields default to None."""
        from core.observability.events.types import CerebroEvent, CerebroEventType

        event = CerebroEvent(
            event_type=CerebroEventType.HIVE_STATE_CHANGE,
            tenant_id="test",
            workspace_id="default",
            payload={"test": True},
        )

        assert event.correlation_id is None
        assert event.sequence_number is None

    def test_to_json_includes_correlation(self):
        """to_json includes correlation fields when present."""
        from core.observability.events.types import CerebroEvent, CerebroEventType

        event = CerebroEvent(
            event_type=CerebroEventType.HIVE_STATE_CHANGE,
            tenant_id="test",
            workspace_id="default",
            payload={"test": True},
            correlation_id="trace123",
            sequence_number=5,
        )

        json_str = event.to_json()
        data = json.loads(json_str)

        assert data["correlation_id"] == "trace123"
        assert data["sequence_number"] == 5

    def test_to_json_excludes_none_correlation(self):
        """to_json excludes correlation fields when None."""
        from core.observability.events.types import CerebroEvent, CerebroEventType

        event = CerebroEvent(
            event_type=CerebroEventType.HIVE_STATE_CHANGE,
            tenant_id="test",
            workspace_id="default",
            payload={"test": True},
        )

        json_str = event.to_json()
        data = json.loads(json_str)

        assert "correlation_id" not in data
        assert "sequence_number" not in data

    def test_from_json_parses_correlation(self):
        """from_json parses correlation fields."""
        from core.observability.events.types import CerebroEvent

        json_str = json.dumps(
            {
                "event_type": "hive.state_change",
                "tenant_id": "test",
                "workspace_id": "default",
                "payload": {"test": True},
                "timestamp": "2025-12-15T10:00:00Z",
                "event_id": "abc123",
                "correlation_id": "trace456",
                "sequence_number": 10,
            }
        )

        event = CerebroEvent.from_json(json_str)

        assert event.correlation_id == "trace456"
        assert event.sequence_number == 10

    def test_from_json_without_correlation(self):
        """from_json works without correlation fields."""
        from core.observability.events.types import CerebroEvent

        json_str = json.dumps(
            {
                "event_type": "hive.state_change",
                "tenant_id": "test",
                "workspace_id": "default",
                "payload": {"test": True},
            }
        )

        event = CerebroEvent.from_json(json_str)

        assert event.correlation_id is None
        assert event.sequence_number is None

    def test_to_dict_includes_correlation(self):
        """to_dict includes correlation fields when present."""
        from core.observability.events.types import CerebroEvent, CerebroEventType

        event = CerebroEvent(
            event_type=CerebroEventType.HIVE_STATE_CHANGE,
            tenant_id="test",
            workspace_id="default",
            payload={"test": True},
            correlation_id="trace789",
            sequence_number=15,
        )

        data = event.to_dict()

        assert data["correlation_id"] == "trace789"
        assert data["sequence_number"] == 15


# =============================================================================
# TestSyncBridgeTelemetry - SyncBridge telemetry hook
# =============================================================================


class TestSyncBridgeTelemetry:
    """Test SyncBridge telemetry integration."""

    def test_sync_bridge_has_setup_telemetry(self):
        """SyncBridge has _setup_telemetry method."""
        # Import directly to avoid circular dependency
        import ast
        import importlib.util

        sync_bridge_path = "core/execution_pkg/orchestration/sync_bridge.py"
        spec = importlib.util.spec_from_file_location("sync_bridge", sync_bridge_path)
        importlib.util.module_from_spec(spec)

        # Check if the method exists in the source
        with open(sync_bridge_path, encoding="utf-8") as f:
            source = f.read()

        tree = ast.parse(source)
        methods = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]

        assert "_setup_telemetry" in methods

    def test_sync_bridge_setup_telemetry_in_init(self):
        """SyncBridge.__init__ calls _setup_telemetry."""
        # Check that __init__ contains the call
        sync_bridge_path = "core/execution_pkg/orchestration/sync_bridge.py"
        with open(sync_bridge_path, encoding="utf-8") as f:
            source = f.read()

        # Verify the call exists in the file
        assert "_setup_telemetry()" in source
        assert "# V10 SYNAPSE: Setup telemetry hook" in source


# =============================================================================
# TestIntegration - End-to-end integration tests
# =============================================================================


class TestIntegration:
    """Integration tests for telemetry pipeline."""

    @pytest.fixture(autouse=True)
    def reset_singletons(self):
        """Reset singletons between tests."""
        from core.observability.events.redis_bus import reset_redis_bus
        from core.observability.events.telemetry_bridge import reset_telemetry_bridge

        reset_telemetry_bridge()
        reset_redis_bus()
        yield
        reset_telemetry_bridge()
        reset_redis_bus()

    @pytest.mark.asyncio
    async def test_full_trace_lifecycle(self):
        """Test complete trace lifecycle with events."""
        from core.observability.events import redis_bus
        from core.observability.events.telemetry_bridge import get_telemetry_bridge
        from core.observability.events.types import CerebroEventType

        bridge = get_telemetry_bridge()

        # Mock the bus
        mock_bus = MagicMock()
        published_events = []

        async def capture_event(event):
            published_events.append(event)
            return True

        mock_bus.publish = capture_event

        with patch.object(redis_bus, "get_redis_bus", return_value=mock_bus):
            # Start trace
            trace_id = bridge.start_trace()

            # Emit multiple events
            await bridge.emit(CerebroEventType.HIVE_PHASE_START, {"phase": "analysis"})
            await bridge.emit(CerebroEventType.HIVE_STATE_CHANGE, {"state": "analyzing"})
            await bridge.emit(CerebroEventType.HIVE_PHASE_END, {"phase": "analysis"})

            # End trace
            bridge.end_trace()

            # Verify events
            assert len(published_events) == 3

            # All should have same correlation_id
            for event in published_events:
                assert event.correlation_id == trace_id

            # Sequence should be 1, 2, 3
            assert published_events[0].sequence_number == 1
            assert published_events[1].sequence_number == 2
            assert published_events[2].sequence_number == 3

    @pytest.mark.asyncio
    async def test_emit_graceful_degradation(self):
        """Test emit doesn't raise when bus fails."""
        from core.observability.events import redis_bus
        from core.observability.events.telemetry_bridge import get_telemetry_bridge
        from core.observability.events.types import CerebroEventType

        bridge = get_telemetry_bridge()

        mock_bus = MagicMock()
        mock_bus.publish = AsyncMock(side_effect=Exception("Redis down"))

        with patch.object(redis_bus, "get_redis_bus", return_value=mock_bus):
            # Should not raise
            result = await bridge.emit(CerebroEventType.HIVE_STATE_CHANGE, {"state": "test"})

            # Should return False
            assert result is False
