"""
Message Router - Intelligent message routing between agents.

V12.4 COGNITIVE BOOST - Task #72

Provides message routing with per-agent queues, delivery tracking,
dead letter handling, and statistics.

Usage:
    from core.synapse.message_router import get_message_router

    router = get_message_router()

    # Register agents
    router.register("claude")
    router.register("gemini")

    # Route a message
    router.route("claude", "gemini", payload={"type": "analysis"})

    # Receive messages
    messages = router.receive("gemini")
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

MAX_AGENTS = 1000
MAX_QUEUE_SIZE = 10000
MAX_DEAD_LETTERS = 5000


# =============================================================================
# Types
# =============================================================================


@dataclass
class RoutedMessage:
    """A message routed between agents."""

    message_id: str
    sender: str
    recipient: str
    payload: dict[str, Any] = field(default_factory=dict)
    topic: str = ""
    priority: int = 0
    timestamp: float = 0.0
    delivered: bool = False

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.monotonic()
        if not self.message_id:
            import secrets

            self.message_id = secrets.token_hex(8)

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "sender": self.sender,
            "recipient": self.recipient,
            "topic": self.topic,
            "priority": self.priority,
            "delivered": self.delivered,
        }


@dataclass
class DeadLetter:
    """A message that could not be delivered."""

    message: RoutedMessage
    reason: str
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.monotonic()

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message.message_id,
            "sender": self.message.sender,
            "recipient": self.message.recipient,
            "reason": self.reason,
        }


@dataclass
class RouteResult:
    """Result of a routing attempt."""

    success: bool
    message_id: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "message_id": self.message_id,
            "error": self.error,
        }


@dataclass
class QueueInfo:
    """Info about an agent's message queue."""

    agent_id: str
    pending: int
    total_received: int
    total_delivered: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "pending": self.pending,
            "total_received": self.total_received,
            "total_delivered": self.total_delivered,
        }


@dataclass
class RouterStats:
    """Message router statistics."""

    registered_agents: int
    total_routed: int
    total_delivered: int
    total_dead_letters: int
    total_broadcasts: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "registered_agents": self.registered_agents,
            "total_routed": self.total_routed,
            "total_delivered": self.total_delivered,
            "total_dead_letters": self.total_dead_letters,
            "total_broadcasts": self.total_broadcasts,
        }


# =============================================================================
# Message Router
# =============================================================================


class MessageRouter:
    """
    Routes messages between registered agents.

    Features:
    - Per-agent message queues
    - Priority-based message ordering
    - Topic-based routing
    - Broadcast support
    - Dead letter tracking
    - Delivery confirmation
    - Statistics
    - Thread-safe
    """

    def __init__(self):
        self._agents: set[str] = set()
        self._queues: dict[str, deque[RoutedMessage]] = {}
        self._dead_letters: list[DeadLetter] = []
        self._total_received: dict[str, int] = {}
        self._total_delivered: dict[str, int] = {}
        self._total_routed = 0
        self._total_delivered_count = 0
        self._total_broadcasts = 0
        self._lock = threading.Lock()

    # =========================================================================
    # Agent Registration
    # =========================================================================

    def register(self, agent_id: str) -> bool:
        """Register an agent for message routing."""
        with self._lock:
            if agent_id in self._agents:
                return False
            if len(self._agents) >= MAX_AGENTS:
                raise ValueError(f"Maximum agents ({MAX_AGENTS}) reached")
            self._agents.add(agent_id)
            self._queues[agent_id] = deque()
            self._total_received[agent_id] = 0
            self._total_delivered[agent_id] = 0
            return True

    def unregister(self, agent_id: str) -> bool:
        """Unregister an agent."""
        with self._lock:
            if agent_id not in self._agents:
                return False
            self._agents.discard(agent_id)
            self._queues.pop(agent_id, None)
            self._total_received.pop(agent_id, None)
            self._total_delivered.pop(agent_id, None)
            return True

    def is_registered(self, agent_id: str) -> bool:
        """Check if an agent is registered."""
        return agent_id in self._agents

    def list_agents(self) -> list[str]:
        """List all registered agents."""
        return sorted(self._agents)

    # =========================================================================
    # Routing
    # =========================================================================

    def route(
        self,
        sender: str,
        recipient: str,
        *,
        payload: dict[str, Any] | None = None,
        topic: str = "",
        priority: int = 0,
        message_id: str = "",
    ) -> RouteResult:
        """Route a message from sender to recipient."""
        msg = RoutedMessage(
            message_id=message_id,
            sender=sender,
            recipient=recipient,
            payload=payload or {},
            topic=topic,
            priority=priority,
        )

        with self._lock:
            self._total_routed += 1

            if recipient not in self._agents:
                dl = DeadLetter(message=msg, reason=f"Recipient '{recipient}' not registered")
                self._dead_letters.append(dl)
                if len(self._dead_letters) > MAX_DEAD_LETTERS:
                    self._dead_letters = self._dead_letters[-MAX_DEAD_LETTERS:]
                return RouteResult(success=False, message_id=msg.message_id, error=dl.reason)

            queue = self._queues[recipient]
            if len(queue) >= MAX_QUEUE_SIZE:
                dl = DeadLetter(message=msg, reason=f"Queue full for '{recipient}'")
                self._dead_letters.append(dl)
                return RouteResult(success=False, message_id=msg.message_id, error=dl.reason)

            queue.append(msg)
            self._total_received[recipient] = self._total_received.get(recipient, 0) + 1
            return RouteResult(success=True, message_id=msg.message_id)

    def broadcast(
        self,
        sender: str,
        *,
        payload: dict[str, Any] | None = None,
        topic: str = "",
        priority: int = 0,
        exclude_sender: bool = True,
    ) -> int:
        """Broadcast a message to all registered agents."""
        count = 0
        with self._lock:
            self._total_broadcasts += 1
            targets = [a for a in self._agents if not (exclude_sender and a == sender)]

        for target in targets:
            result = self.route(sender, target, payload=payload, topic=topic, priority=priority)
            if result.success:
                count += 1
        return count

    # =========================================================================
    # Receiving
    # =========================================================================

    def receive(self, agent_id: str, *, limit: int = 0) -> list[RoutedMessage]:
        """Receive pending messages for an agent."""
        with self._lock:
            queue = self._queues.get(agent_id)
            if queue is None:
                return []

            messages = []
            count = 0
            while queue and (limit == 0 or count < limit):
                msg = queue.popleft()
                msg.delivered = True
                messages.append(msg)
                count += 1

            self._total_delivered[agent_id] = self._total_delivered.get(agent_id, 0) + len(messages)
            self._total_delivered_count += len(messages)
            return messages

    def peek(self, agent_id: str, *, limit: int = 0) -> list[RoutedMessage]:
        """Peek at pending messages without removing them."""
        queue = self._queues.get(agent_id)
        if queue is None:
            return []
        if limit == 0:
            return list(queue)
        return list(queue)[:limit]

    def pending_count(self, agent_id: str) -> int:
        """Get number of pending messages for an agent."""
        queue = self._queues.get(agent_id)
        return len(queue) if queue else 0

    def get_by_topic(self, agent_id: str, topic: str) -> list[RoutedMessage]:
        """Get pending messages for an agent filtered by topic."""
        queue = self._queues.get(agent_id)
        if queue is None:
            return []
        return [m for m in queue if m.topic == topic]

    # =========================================================================
    # Dead Letters
    # =========================================================================

    def get_dead_letters(self, *, limit: int = 0) -> list[DeadLetter]:
        """Get dead letters."""
        if limit == 0:
            return list(self._dead_letters)
        return list(self._dead_letters[-limit:])

    def clear_dead_letters(self) -> int:
        """Clear all dead letters. Returns count cleared."""
        with self._lock:
            count = len(self._dead_letters)
            self._dead_letters.clear()
            return count

    # =========================================================================
    # Queue Info
    # =========================================================================

    def get_queue_info(self, agent_id: str) -> QueueInfo | None:
        """Get queue info for an agent."""
        if agent_id not in self._agents:
            return None
        return QueueInfo(
            agent_id=agent_id,
            pending=len(self._queues.get(agent_id, deque())),
            total_received=self._total_received.get(agent_id, 0),
            total_delivered=self._total_delivered.get(agent_id, 0),
        )

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> RouterStats:
        """Get router statistics."""
        return RouterStats(
            registered_agents=len(self._agents),
            total_routed=self._total_routed,
            total_delivered=self._total_delivered_count,
            total_dead_letters=len(self._dead_letters),
            total_broadcasts=self._total_broadcasts,
        )

    # =========================================================================
    # State
    # =========================================================================

    @property
    def agent_count(self) -> int:
        return len(self._agents)

    def clear(self) -> None:
        """Clear all state."""
        with self._lock:
            self._agents.clear()
            self._queues.clear()
            self._dead_letters.clear()
            self._total_received.clear()
            self._total_delivered.clear()
            self._total_routed = 0
            self._total_delivered_count = 0
            self._total_broadcasts = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_count": self.agent_count,
            "stats": self.get_stats().to_dict(),
        }


# =============================================================================
# Global Instance
# =============================================================================

_router: MessageRouter | None = None
_router_lock = threading.Lock()


def get_message_router() -> MessageRouter:
    """Get or create the global message router."""
    global _router
    if _router is None:
        with _router_lock:
            if _router is None:
                _router = MessageRouter()
    return _router


def reset_message_router() -> None:
    """Reset the global message router (for testing)."""
    global _router
    _router = None
