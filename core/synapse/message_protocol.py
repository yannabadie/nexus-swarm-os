"""
Inter-Agent Message Protocol - Lightweight structured messaging.

V12.4 COGNITIVE BOOST - Task #47

Complements the existing LightMessageV7/HeavyMessageV7 (Pydantic, complex)
with a simpler dataclass-based protocol for V12.4 module communication.

Features:
- Typed message categories (REQUEST, RESPONSE, BROADCAST, NOTIFY)
- Routing headers (sender, recipient, priority)
- Conversation threading (thread_id + reply_to)
- Message validation
- Envelope pattern for serialization

Usage:
    from core.synapse.message_protocol import Message, MessageType, create_message

    msg = create_message(
        msg_type=MessageType.REQUEST,
        sender="claude",
        recipient="gemini",
        topic="task.analysis",
        payload={"task": "Review auth module"},
    )

    reply = msg.create_reply(
        sender="gemini",
        payload={"analysis": "Found 3 issues"},
    )
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# =============================================================================
# Constants
# =============================================================================

PROTOCOL_VERSION = "1.0"
MAX_PAYLOAD_SIZE = 1_000_000  # 1MB serialized


# =============================================================================
# Types
# =============================================================================


class MessageType(Enum):
    """Message category."""

    REQUEST = "request"  # Ask another agent to do something
    RESPONSE = "response"  # Reply to a request
    BROADCAST = "broadcast"  # Send to all agents
    NOTIFY = "notify"  # One-way notification
    ERROR = "error"  # Error report
    ACK = "ack"  # Acknowledgement


class Priority(Enum):
    """Message priority."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


PRIORITY_ORDER = {
    Priority.LOW: 0,
    Priority.NORMAL: 1,
    Priority.HIGH: 2,
    Priority.CRITICAL: 3,
}


@dataclass
class MessageHeader:
    """Routing and metadata header."""

    message_id: str = ""
    msg_type: MessageType = MessageType.NOTIFY
    sender: str = ""
    recipient: str = ""  # empty = broadcast
    topic: str = ""
    priority: Priority = Priority.NORMAL
    thread_id: str = ""  # conversation thread
    reply_to: str = ""  # message_id being replied to
    timestamp: float = 0.0
    protocol_version: str = PROTOCOL_VERSION

    def __post_init__(self):
        if not self.message_id:
            self.message_id = uuid.uuid4().hex[:16]
        if self.timestamp == 0.0:
            self.timestamp = time.monotonic()
        if not self.thread_id:
            self.thread_id = self.message_id  # new thread

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "type": self.msg_type.value,
            "sender": self.sender,
            "recipient": self.recipient,
            "topic": self.topic,
            "priority": self.priority.value,
            "thread_id": self.thread_id,
            "reply_to": self.reply_to,
            "protocol_version": self.protocol_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MessageHeader:
        return cls(
            message_id=data.get("message_id", ""),
            msg_type=MessageType(data.get("type", "notify")),
            sender=data.get("sender", ""),
            recipient=data.get("recipient", ""),
            topic=data.get("topic", ""),
            priority=Priority(data.get("priority", "normal")),
            thread_id=data.get("thread_id", ""),
            reply_to=data.get("reply_to", ""),
            protocol_version=data.get("protocol_version", PROTOCOL_VERSION),
        )


@dataclass
class Message:
    """A complete inter-agent message."""

    header: MessageHeader
    payload: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    # Convenience properties
    @property
    def message_id(self) -> str:
        return self.header.message_id

    @property
    def msg_type(self) -> MessageType:
        return self.header.msg_type

    @property
    def sender(self) -> str:
        return self.header.sender

    @property
    def recipient(self) -> str:
        return self.header.recipient

    @property
    def topic(self) -> str:
        return self.header.topic

    @property
    def priority(self) -> Priority:
        return self.header.priority

    @property
    def thread_id(self) -> str:
        return self.header.thread_id

    @property
    def is_reply(self) -> bool:
        return bool(self.header.reply_to)

    @property
    def is_broadcast(self) -> bool:
        return not self.header.recipient

    @property
    def is_error(self) -> bool:
        return self.header.msg_type == MessageType.ERROR

    def create_reply(
        self,
        sender: str,
        payload: Any = None,
        *,
        msg_type: MessageType = MessageType.RESPONSE,
        metadata: dict[str, Any] | None = None,
    ) -> Message:
        """
        Create a reply to this message.

        Preserves thread_id and sets reply_to.
        """
        header = MessageHeader(
            msg_type=msg_type,
            sender=sender,
            recipient=self.header.sender,  # reply back to sender
            topic=self.header.topic,
            priority=self.header.priority,
            thread_id=self.header.thread_id,
            reply_to=self.header.message_id,
        )
        return Message(
            header=header,
            payload=payload,
            metadata=metadata or {},
        )

    def create_ack(self, sender: str) -> Message:
        """Create an acknowledgement for this message."""
        return self.create_reply(
            sender=sender,
            msg_type=MessageType.ACK,
            payload={"acked_message_id": self.message_id},
        )

    def create_error_reply(
        self,
        sender: str,
        error: str,
    ) -> Message:
        """Create an error reply to this message."""
        return self.create_reply(
            sender=sender,
            msg_type=MessageType.ERROR,
            payload={"error": error},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "header": self.header.to_dict(),
            "payload": self.payload,
            "metadata": self.metadata,
            "errors": self.errors,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Message:
        return cls(
            header=MessageHeader.from_dict(data.get("header", {})),
            payload=data.get("payload"),
            metadata=data.get("metadata", {}),
            errors=data.get("errors", []),
        )


@dataclass
class MessageThread:
    """A conversation thread (sequence of related messages)."""

    thread_id: str
    messages: list[Message] = field(default_factory=list)
    topic: str = ""

    def add(self, message: Message) -> None:
        self.messages.append(message)
        if not self.topic and message.topic:
            self.topic = message.topic

    @property
    def message_count(self) -> int:
        return len(self.messages)

    @property
    def participants(self) -> list[str]:
        return sorted(set(m.sender for m in self.messages if m.sender))

    @property
    def last_message(self) -> Message | None:
        return self.messages[-1] if self.messages else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "topic": self.topic,
            "message_count": self.message_count,
            "participants": self.participants,
        }


# =============================================================================
# Factory Functions
# =============================================================================


def create_message(
    msg_type: MessageType,
    sender: str,
    *,
    recipient: str = "",
    topic: str = "",
    payload: Any = None,
    priority: Priority = Priority.NORMAL,
    thread_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> Message:
    """
    Create a new message.

    Args:
        msg_type: Message type
        sender: Sender agent ID
        recipient: Recipient agent ID (empty for broadcast)
        topic: Message topic
        payload: Message payload
        priority: Message priority
        thread_id: Thread ID (auto-generated if empty)
        metadata: Optional metadata

    Returns:
        New Message instance
    """
    header = MessageHeader(
        msg_type=msg_type,
        sender=sender,
        recipient=recipient,
        topic=topic,
        priority=priority,
        thread_id=thread_id,
    )
    return Message(
        header=header,
        payload=payload,
        metadata=metadata or {},
    )


def create_request(
    sender: str,
    recipient: str,
    topic: str,
    payload: Any = None,
    *,
    priority: Priority = Priority.NORMAL,
) -> Message:
    """Shortcut to create a REQUEST message."""
    return create_message(
        MessageType.REQUEST,
        sender,
        recipient=recipient,
        topic=topic,
        payload=payload,
        priority=priority,
    )


def create_broadcast(
    sender: str,
    topic: str,
    payload: Any = None,
    *,
    priority: Priority = Priority.NORMAL,
) -> Message:
    """Shortcut to create a BROADCAST message."""
    return create_message(
        MessageType.BROADCAST,
        sender,
        topic=topic,
        payload=payload,
        priority=priority,
    )


# =============================================================================
# Validation
# =============================================================================


def validate_message(message: Message) -> list[str]:
    """
    Validate a message for correctness.

    Returns:
        List of error strings (empty = valid)
    """
    errors = []

    if not message.sender:
        errors.append("Message must have a sender")

    if not message.topic:
        errors.append("Message must have a topic")

    if message.msg_type == MessageType.REQUEST and not message.recipient:
        errors.append("REQUEST messages must have a recipient")

    if message.msg_type == MessageType.RESPONSE and not message.is_reply:
        errors.append("RESPONSE messages must be a reply (reply_to required)")

    return errors
