"""
NEXUS V10 CEREBRO - Event Types

Defines CerebroEventType enum and CerebroEvent dataclass for Redis pub/sub.

Event Categories:
- INTERACTION_*  : HeadlessProvider interactions (ask, confirm, choose, etc.)
- ORCHESTRATION_*: FSM/HiveMind state changes
- AGENT_*        : Agent communication and tool usage
- SWARM_*        : Swarm mode selection and negotiation
- SYSTEM_*       : Logs, errors, heartbeats

Channel Format: nexus:{tenant_id}:{workspace_id}:{event_type}
"""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4


class CerebroEventType(str, Enum):
    """
    Event types for CEREBRO Redis pub/sub bus.

    Naming convention: CATEGORY_ACTION
    All values are lowercase with dots for hierarchy.
    """

    # =========================================================================
    # Interaction Events (from HeadlessProvider)
    # =========================================================================
    INTERACTION_ASK = "interaction.ask"
    INTERACTION_CONFIRM = "interaction.confirm"
    INTERACTION_CHOOSE = "interaction.choose"
    INTERACTION_ANNOUNCE = "interaction.announce"
    INTERACTION_PROGRESS = "interaction.progress"

    # =========================================================================
    # Orchestration Events (FSM/HiveMind)
    # =========================================================================
    STATE_CHANGE = "orchestration.state_change"
    PHASE_START = "orchestration.phase_start"
    PHASE_END = "orchestration.phase_end"

    # =========================================================================
    # Agent Events
    # =========================================================================
    AGENT_SPEAK = "agent.speak"
    AGENT_TOOL_CALL = "agent.tool_call"
    AGENT_TOOL_RESULT = "agent.tool_result"

    # =========================================================================
    # Swarm Events
    # =========================================================================
    SWARM_MODE_SELECTED = "swarm.mode_selected"
    SWARM_NEGOTIATION = "swarm.negotiation"
    SWARM_PHASE_CHANGE = "swarm.phase_change"  # V10 SYNAPSE

    # =========================================================================
    # HiveMind Telemetry Events (V10 SYNAPSE)
    # =========================================================================
    HIVE_STATE_CHANGE = "hive.state_change"
    HIVE_PHASE_START = "hive.phase_start"
    HIVE_PHASE_END = "hive.phase_end"

    # =========================================================================
    # Saga Events (V12.4.1 Epic 1.3 - Durable Sagas)
    # =========================================================================
    SAGA_CHECKPOINT = "saga.checkpoint"  # Phase checkpoint created
    SAGA_ROLLBACK = "saga.rollback"  # Rollback to previous phase
    SAGA_RESUME = "saga.resume"  # Saga resumed from disk/Redis

    # =========================================================================
    # Graph Events for React Flow UI (V10 SYNAPSE)
    # =========================================================================
    GRAPH_NODE_SPAWN = "graph.node_spawn"
    GRAPH_NODE_UPDATE = "graph.node_update"
    GRAPH_EDGE_MESSAGE = "graph.edge_message"

    # =========================================================================
    # System Events
    # =========================================================================
    LOG = "system.log"
    ERROR = "system.error"
    HEARTBEAT = "system.heartbeat"


def _generate_event_id() -> str:
    """Generate a short unique event ID."""
    return uuid4().hex[:12]


def _generate_timestamp() -> str:
    """Generate ISO 8601 timestamp in UTC."""
    return datetime.now(UTC).isoformat()


@dataclass
class CerebroEvent:
    """
    Event payload for Redis pub/sub.

    Attributes:
        event_type: Type of event (from CerebroEventType enum)
        tenant_id: Tenant identifier for multi-tenant isolation
        workspace_id: Workspace within tenant
        payload: Event-specific data (JSON-serializable dict)
        timestamp: ISO 8601 timestamp (auto-generated)
        event_id: Unique event identifier (auto-generated)

    Example:
        event = CerebroEvent(
            event_type=CerebroEventType.INTERACTION_ASK,
            tenant_id="tenant_abc",
            workspace_id="project_1",
            payload={"prompt": "Continue?", "default": "yes"}
        )
        json_str = event.to_json()
    """

    event_type: CerebroEventType
    tenant_id: str
    workspace_id: str
    payload: dict[str, Any]
    timestamp: str = field(default_factory=_generate_timestamp)
    event_id: str = field(default_factory=_generate_event_id)
    # V10 SYNAPSE: Correlation tracking for tracing related events
    correlation_id: str | None = None
    sequence_number: int | None = None

    def to_json(self) -> str:
        """
        Serialize event to JSON string.

        Returns:
            JSON string representation of the event
        """
        data = {
            "event_type": self.event_type.value,
            "tenant_id": self.tenant_id,
            "workspace_id": self.workspace_id,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "event_id": self.event_id,
        }
        # V10 SYNAPSE: Include correlation fields if present
        if self.correlation_id is not None:
            data["correlation_id"] = self.correlation_id
        if self.sequence_number is not None:
            data["sequence_number"] = self.sequence_number
        return json.dumps(data, ensure_ascii=False)

    def to_dict(self) -> dict[str, Any]:
        """
        Convert event to dictionary.

        Returns:
            Dictionary representation of the event
        """
        data = {
            "event_type": self.event_type.value,
            "tenant_id": self.tenant_id,
            "workspace_id": self.workspace_id,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "event_id": self.event_id,
        }
        # V10 SYNAPSE: Include correlation fields if present
        if self.correlation_id is not None:
            data["correlation_id"] = self.correlation_id
        if self.sequence_number is not None:
            data["sequence_number"] = self.sequence_number
        return data

    @classmethod
    def from_json(cls, data: str) -> "CerebroEvent":
        """
        Deserialize event from JSON string.

        Args:
            data: JSON string representation of an event

        Returns:
            CerebroEvent instance

        Raises:
            ValueError: If event_type is invalid
            json.JSONDecodeError: If JSON is malformed
        """
        d = json.loads(data)
        return cls(
            event_type=CerebroEventType(d["event_type"]),
            tenant_id=d["tenant_id"],
            workspace_id=d["workspace_id"],
            payload=d["payload"],
            timestamp=d.get("timestamp", _generate_timestamp()),
            event_id=d.get("event_id", _generate_event_id()),
            # V10 SYNAPSE: Correlation fields
            correlation_id=d.get("correlation_id"),
            sequence_number=d.get("sequence_number"),
        )

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CerebroEvent":
        """
        Create event from dictionary.

        Args:
            d: Dictionary representation of an event

        Returns:
            CerebroEvent instance
        """
        return cls(
            event_type=CerebroEventType(d["event_type"]),
            tenant_id=d["tenant_id"],
            workspace_id=d["workspace_id"],
            payload=d["payload"],
            timestamp=d.get("timestamp", _generate_timestamp()),
            event_id=d.get("event_id", _generate_event_id()),
            # V10 SYNAPSE: Correlation fields
            correlation_id=d.get("correlation_id"),
            sequence_number=d.get("sequence_number"),
        )

    def channel_name(self) -> str:
        """
        Get Redis channel name for this event.

        Format: nexus:{tenant_id}:{workspace_id}:{event_type}

        Returns:
            Redis channel name string
        """
        return f"nexus:{self.tenant_id}:{self.workspace_id}:{self.event_type.value}"

    @staticmethod
    def wildcard_channel(
        tenant_id: str, workspace_id: str | None = None, event_type: CerebroEventType | None = None
    ) -> str:
        """
        Get Redis pattern for subscribing to multiple channels.

        Args:
            tenant_id: Tenant identifier (required)
            workspace_id: Workspace ID or None for all workspaces
            event_type: Event type or None for all types

        Returns:
            Redis pattern string for PSUBSCRIBE

        Examples:
            wildcard_channel("t1") -> "nexus:t1:*:*"
            wildcard_channel("t1", "ws1") -> "nexus:t1:ws1:*"
            wildcard_channel("t1", "ws1", CerebroEventType.LOG) -> "nexus:t1:ws1:system.log"
        """
        ws = workspace_id or "*"
        et = event_type.value if event_type else "*"
        return f"nexus:{tenant_id}:{ws}:{et}"


# =============================================================================
# Convenience Functions
# =============================================================================


def create_interaction_event(event_type: CerebroEventType, tenant_id: str, workspace_id: str, **kwargs) -> CerebroEvent:
    """
    Create an interaction event with common fields.

    Args:
        event_type: Must be an INTERACTION_* type
        tenant_id: Tenant identifier
        workspace_id: Workspace identifier
        **kwargs: Additional payload fields

    Returns:
        CerebroEvent instance
    """
    return CerebroEvent(
        event_type=event_type,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        payload=kwargs,
    )


def create_system_log_event(
    tenant_id: str,
    workspace_id: str,
    level: str,
    message: str,
    logger_name: str | None = None,
) -> CerebroEvent:
    """
    Create a system log event.

    Args:
        tenant_id: Tenant identifier
        workspace_id: Workspace identifier
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        message: Log message
        logger_name: Optional logger name

    Returns:
        CerebroEvent instance
    """
    return CerebroEvent(
        event_type=CerebroEventType.LOG,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        payload={
            "level": level,
            "message": message,
            "logger": logger_name,
        },
    )
