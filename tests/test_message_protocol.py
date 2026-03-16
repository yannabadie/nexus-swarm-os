"""
Tests for V12.4 Inter-Agent Message Protocol.

Validates:
- MessageType and Priority enums
- MessageHeader creation and serialization
- Message creation and convenience properties
- Reply, ACK, and error reply creation
- MessageThread tracking
- Factory functions (create_message, create_request, create_broadcast)
- Message validation
- Serialization round-trip
- Module exports
"""

from core.synapse.message_protocol import (
    MAX_PAYLOAD_SIZE,
    PRIORITY_ORDER,
    PROTOCOL_VERSION,
    Message,
    MessageHeader,
    MessageThread,
    MessageType,
    Priority,
    create_broadcast,
    create_message,
    create_request,
    validate_message,
)

# =============================================================================
# MessageType Tests
# =============================================================================


class TestMessageType:
    """Test MessageType enum."""

    def test_values(self):
        assert MessageType.REQUEST.value == "request"
        assert MessageType.RESPONSE.value == "response"
        assert MessageType.BROADCAST.value == "broadcast"
        assert MessageType.NOTIFY.value == "notify"
        assert MessageType.ERROR.value == "error"
        assert MessageType.ACK.value == "ack"

    def test_count(self):
        assert len(MessageType) == 6

    def test_from_value(self):
        assert MessageType("request") == MessageType.REQUEST
        assert MessageType("ack") == MessageType.ACK


# =============================================================================
# Priority Tests
# =============================================================================


class TestPriority:
    """Test Priority enum."""

    def test_values(self):
        assert Priority.LOW.value == "low"
        assert Priority.NORMAL.value == "normal"
        assert Priority.HIGH.value == "high"
        assert Priority.CRITICAL.value == "critical"

    def test_priority_order(self):
        assert PRIORITY_ORDER[Priority.LOW] < PRIORITY_ORDER[Priority.NORMAL]
        assert PRIORITY_ORDER[Priority.NORMAL] < PRIORITY_ORDER[Priority.HIGH]
        assert PRIORITY_ORDER[Priority.HIGH] < PRIORITY_ORDER[Priority.CRITICAL]

    def test_from_value(self):
        assert Priority("high") == Priority.HIGH


# =============================================================================
# MessageHeader Tests
# =============================================================================


class TestMessageHeader:
    """Test MessageHeader dataclass."""

    def test_auto_id(self):
        h = MessageHeader(sender="claude")
        assert h.message_id
        assert len(h.message_id) == 16

    def test_auto_timestamp(self):
        h = MessageHeader(sender="claude")
        assert h.timestamp > 0

    def test_auto_thread_id(self):
        h = MessageHeader(sender="claude")
        assert h.thread_id == h.message_id

    def test_explicit_thread_id(self):
        h = MessageHeader(sender="claude", thread_id="thread_123")
        assert h.thread_id == "thread_123"

    def test_protocol_version(self):
        h = MessageHeader(sender="claude")
        assert h.protocol_version == PROTOCOL_VERSION

    def test_defaults(self):
        h = MessageHeader()
        assert h.msg_type == MessageType.NOTIFY
        assert h.sender == ""
        assert h.recipient == ""
        assert h.topic == ""
        assert h.priority == Priority.NORMAL
        assert h.reply_to == ""

    def test_to_dict(self):
        h = MessageHeader(
            sender="claude",
            recipient="gemini",
            msg_type=MessageType.REQUEST,
            topic="task.review",
            priority=Priority.HIGH,
        )
        d = h.to_dict()
        assert d["sender"] == "claude"
        assert d["recipient"] == "gemini"
        assert d["type"] == "request"
        assert d["topic"] == "task.review"
        assert d["priority"] == "high"
        assert d["protocol_version"] == PROTOCOL_VERSION

    def test_from_dict(self):
        data = {
            "message_id": "abc123",
            "type": "request",
            "sender": "claude",
            "recipient": "gemini",
            "topic": "code.review",
            "priority": "high",
            "thread_id": "t1",
            "reply_to": "prev_msg",
        }
        h = MessageHeader.from_dict(data)
        assert h.message_id == "abc123"
        assert h.msg_type == MessageType.REQUEST
        assert h.sender == "claude"
        assert h.recipient == "gemini"
        assert h.priority == Priority.HIGH
        assert h.thread_id == "t1"
        assert h.reply_to == "prev_msg"

    def test_from_dict_defaults(self):
        h = MessageHeader.from_dict({})
        assert h.msg_type == MessageType.NOTIFY
        assert h.priority == Priority.NORMAL

    def test_unique_ids(self):
        h1 = MessageHeader(sender="a")
        h2 = MessageHeader(sender="b")
        assert h1.message_id != h2.message_id


# =============================================================================
# Message Tests
# =============================================================================


class TestMessage:
    """Test Message dataclass."""

    def test_basic_creation(self):
        header = MessageHeader(
            msg_type=MessageType.REQUEST,
            sender="claude",
            recipient="gemini",
            topic="analysis",
        )
        msg = Message(header=header, payload={"task": "review"})
        assert msg.sender == "claude"
        assert msg.recipient == "gemini"
        assert msg.topic == "analysis"
        assert msg.payload == {"task": "review"}

    def test_convenience_properties(self):
        header = MessageHeader(
            msg_type=MessageType.BROADCAST,
            sender="claude",
            topic="status",
            priority=Priority.HIGH,
        )
        msg = Message(header=header)
        assert msg.message_id == header.message_id
        assert msg.msg_type == MessageType.BROADCAST
        assert msg.sender == "claude"
        assert msg.recipient == ""
        assert msg.topic == "status"
        assert msg.priority == Priority.HIGH
        assert msg.thread_id == header.thread_id

    def test_is_reply(self):
        h1 = MessageHeader(sender="claude")
        msg1 = Message(header=h1)
        assert msg1.is_reply is False

        h2 = MessageHeader(sender="gemini", reply_to="abc")
        msg2 = Message(header=h2)
        assert msg2.is_reply is True

    def test_is_broadcast(self):
        h1 = MessageHeader(sender="claude", recipient="")
        msg1 = Message(header=h1)
        assert msg1.is_broadcast is True

        h2 = MessageHeader(sender="claude", recipient="gemini")
        msg2 = Message(header=h2)
        assert msg2.is_broadcast is False

    def test_is_error(self):
        h1 = MessageHeader(msg_type=MessageType.ERROR)
        msg1 = Message(header=h1)
        assert msg1.is_error is True

        h2 = MessageHeader(msg_type=MessageType.NOTIFY)
        msg2 = Message(header=h2)
        assert msg2.is_error is False

    def test_metadata_default(self):
        msg = Message(header=MessageHeader())
        assert msg.metadata == {}

    def test_errors_default(self):
        msg = Message(header=MessageHeader())
        assert msg.errors == []

    def test_to_dict(self):
        msg = create_message(
            MessageType.REQUEST,
            "claude",
            recipient="gemini",
            topic="task",
            payload={"key": "value"},
        )
        d = msg.to_dict()
        assert "header" in d
        assert d["payload"] == {"key": "value"}
        assert d["metadata"] == {}
        assert d["errors"] == []
        assert d["header"]["type"] == "request"

    def test_from_dict(self):
        original = create_message(
            MessageType.REQUEST,
            "claude",
            recipient="gemini",
            topic="task",
            payload={"data": 42},
            metadata={"source": "test"},
        )
        d = original.to_dict()
        restored = Message.from_dict(d)
        assert restored.sender == "claude"
        assert restored.recipient == "gemini"
        assert restored.topic == "task"
        assert restored.payload == {"data": 42}
        assert restored.metadata == {"source": "test"}

    def test_round_trip(self):
        msg = create_request(
            "claude",
            "gemini",
            "review",
            payload={"code": "def foo(): pass"},
            priority=Priority.HIGH,
        )
        d = msg.to_dict()
        restored = Message.from_dict(d)
        assert restored.sender == msg.sender
        assert restored.recipient == msg.recipient
        assert restored.topic == msg.topic
        assert restored.priority == msg.priority
        assert restored.payload == msg.payload


# =============================================================================
# Reply Tests
# =============================================================================


class TestReply:
    """Test reply creation."""

    def test_create_reply(self):
        original = create_request(
            "claude",
            "gemini",
            "review",
            payload={"code": "x = 1"},
        )
        reply = original.create_reply(
            sender="gemini",
            payload={"analysis": "looks good"},
        )
        assert reply.sender == "gemini"
        assert reply.recipient == "claude"
        assert reply.msg_type == MessageType.RESPONSE
        assert reply.topic == "review"
        assert reply.thread_id == original.thread_id
        assert reply.is_reply is True
        assert reply.header.reply_to == original.message_id

    def test_reply_preserves_priority(self):
        original = create_message(
            MessageType.REQUEST,
            "claude",
            recipient="gemini",
            topic="urgent",
            priority=Priority.CRITICAL,
        )
        reply = original.create_reply(sender="gemini")
        assert reply.priority == Priority.CRITICAL

    def test_reply_custom_type(self):
        original = create_request("claude", "gemini", "task")
        reply = original.create_reply(
            sender="gemini",
            msg_type=MessageType.NOTIFY,
        )
        assert reply.msg_type == MessageType.NOTIFY

    def test_reply_with_metadata(self):
        original = create_request("claude", "gemini", "task")
        reply = original.create_reply(
            sender="gemini",
            metadata={"timing": 1.5},
        )
        assert reply.metadata == {"timing": 1.5}

    def test_create_ack(self):
        original = create_request("claude", "gemini", "task")
        ack = original.create_ack(sender="gemini")
        assert ack.msg_type == MessageType.ACK
        assert ack.sender == "gemini"
        assert ack.recipient == "claude"
        assert ack.payload == {"acked_message_id": original.message_id}
        assert ack.thread_id == original.thread_id

    def test_create_error_reply(self):
        original = create_request("claude", "gemini", "task")
        err = original.create_error_reply(
            sender="gemini",
            error="Resource not found",
        )
        assert err.msg_type == MessageType.ERROR
        assert err.sender == "gemini"
        assert err.recipient == "claude"
        assert err.payload == {"error": "Resource not found"}
        assert err.is_error is True
        assert err.thread_id == original.thread_id


# =============================================================================
# MessageThread Tests
# =============================================================================


class TestMessageThread:
    """Test MessageThread."""

    def test_empty_thread(self):
        thread = MessageThread(thread_id="t1")
        assert thread.message_count == 0
        assert thread.participants == []
        assert thread.last_message is None

    def test_add_message(self):
        thread = MessageThread(thread_id="t1")
        msg = create_message(MessageType.REQUEST, "claude", topic="task")
        thread.add(msg)
        assert thread.message_count == 1

    def test_topic_from_first_message(self):
        thread = MessageThread(thread_id="t1")
        msg = create_message(MessageType.REQUEST, "claude", topic="code.review")
        thread.add(msg)
        assert thread.topic == "code.review"

    def test_topic_not_overwritten(self):
        thread = MessageThread(thread_id="t1")
        msg1 = create_message(MessageType.REQUEST, "claude", topic="first")
        msg2 = create_message(MessageType.REQUEST, "gemini", topic="second")
        thread.add(msg1)
        thread.add(msg2)
        assert thread.topic == "first"

    def test_participants(self):
        thread = MessageThread(thread_id="t1")
        thread.add(create_message(MessageType.REQUEST, "claude", topic="t"))
        thread.add(create_message(MessageType.RESPONSE, "gemini", topic="t"))
        thread.add(create_message(MessageType.NOTIFY, "claude", topic="t"))
        assert thread.participants == ["claude", "gemini"]

    def test_last_message(self):
        thread = MessageThread(thread_id="t1")
        msg1 = create_message(MessageType.REQUEST, "claude", topic="t")
        msg2 = create_message(MessageType.RESPONSE, "gemini", topic="t")
        thread.add(msg1)
        thread.add(msg2)
        assert thread.last_message is msg2

    def test_to_dict(self):
        thread = MessageThread(thread_id="t1")
        thread.add(create_message(MessageType.REQUEST, "claude", topic="review"))
        thread.add(create_message(MessageType.RESPONSE, "gemini", topic="review"))
        d = thread.to_dict()
        assert d["thread_id"] == "t1"
        assert d["topic"] == "review"
        assert d["message_count"] == 2
        assert d["participants"] == ["claude", "gemini"]

    def test_explicit_topic(self):
        thread = MessageThread(thread_id="t1", topic="preset")
        msg = create_message(MessageType.REQUEST, "claude", topic="other")
        thread.add(msg)
        assert thread.topic == "preset"


# =============================================================================
# Factory Function Tests
# =============================================================================


class TestFactoryFunctions:
    """Test message factory functions."""

    def test_create_message_basic(self):
        msg = create_message(
            MessageType.NOTIFY,
            "claude",
            topic="status.update",
            payload={"status": "ready"},
        )
        assert msg.msg_type == MessageType.NOTIFY
        assert msg.sender == "claude"
        assert msg.topic == "status.update"
        assert msg.payload == {"status": "ready"}

    def test_create_message_with_recipient(self):
        msg = create_message(
            MessageType.REQUEST,
            "claude",
            recipient="gemini",
            topic="task",
        )
        assert msg.recipient == "gemini"
        assert msg.is_broadcast is False

    def test_create_message_defaults(self):
        msg = create_message(MessageType.NOTIFY, "claude")
        assert msg.recipient == ""
        assert msg.topic == ""
        assert msg.payload is None
        assert msg.priority == Priority.NORMAL
        assert msg.metadata == {}

    def test_create_message_with_priority(self):
        msg = create_message(
            MessageType.REQUEST,
            "claude",
            priority=Priority.CRITICAL,
        )
        assert msg.priority == Priority.CRITICAL

    def test_create_message_with_thread_id(self):
        msg = create_message(
            MessageType.REQUEST,
            "claude",
            thread_id="existing_thread",
        )
        assert msg.thread_id == "existing_thread"

    def test_create_message_with_metadata(self):
        msg = create_message(
            MessageType.NOTIFY,
            "claude",
            metadata={"session": "s1"},
        )
        assert msg.metadata == {"session": "s1"}

    def test_create_request(self):
        msg = create_request(
            "claude",
            "gemini",
            "code.review",
            payload={"file": "main.py"},
        )
        assert msg.msg_type == MessageType.REQUEST
        assert msg.sender == "claude"
        assert msg.recipient == "gemini"
        assert msg.topic == "code.review"
        assert msg.payload == {"file": "main.py"}

    def test_create_request_with_priority(self):
        msg = create_request(
            "claude",
            "gemini",
            "urgent",
            priority=Priority.HIGH,
        )
        assert msg.priority == Priority.HIGH

    def test_create_broadcast(self):
        msg = create_broadcast(
            "claude",
            "system.status",
            payload={"online": True},
        )
        assert msg.msg_type == MessageType.BROADCAST
        assert msg.sender == "claude"
        assert msg.recipient == ""
        assert msg.topic == "system.status"
        assert msg.is_broadcast is True

    def test_create_broadcast_with_priority(self):
        msg = create_broadcast(
            "claude",
            "alert",
            priority=Priority.CRITICAL,
        )
        assert msg.priority == Priority.CRITICAL


# =============================================================================
# Validation Tests
# =============================================================================


class TestValidation:
    """Test message validation."""

    def test_valid_request(self):
        msg = create_request("claude", "gemini", "task")
        errors = validate_message(msg)
        assert errors == []

    def test_valid_broadcast(self):
        msg = create_broadcast("claude", "status")
        errors = validate_message(msg)
        assert errors == []

    def test_missing_sender(self):
        msg = create_message(MessageType.NOTIFY, "", topic="test")
        errors = validate_message(msg)
        assert any("sender" in e for e in errors)

    def test_missing_topic(self):
        msg = create_message(MessageType.NOTIFY, "claude", topic="")
        errors = validate_message(msg)
        assert any("topic" in e for e in errors)

    def test_request_without_recipient(self):
        msg = create_message(
            MessageType.REQUEST,
            "claude",
            topic="task",
        )
        errors = validate_message(msg)
        assert any("recipient" in e.lower() for e in errors)

    def test_response_without_reply_to(self):
        header = MessageHeader(
            msg_type=MessageType.RESPONSE,
            sender="gemini",
            recipient="claude",
            topic="task",
        )
        msg = Message(header=header)
        errors = validate_message(msg)
        assert any("reply" in e.lower() for e in errors)

    def test_valid_response_with_reply_to(self):
        original = create_request("claude", "gemini", "task")
        reply = original.create_reply(sender="gemini", payload="done")
        errors = validate_message(reply)
        assert errors == []

    def test_multiple_errors(self):
        msg = create_message(MessageType.REQUEST, "")
        errors = validate_message(msg)
        assert len(errors) >= 2  # missing sender, topic, recipient


# =============================================================================
# Constants Tests
# =============================================================================


class TestConstants:
    """Test module constants."""

    def test_protocol_version(self):
        assert PROTOCOL_VERSION == "1.0"

    def test_max_payload_size(self):
        assert MAX_PAYLOAD_SIZE == 1_000_000


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_synapse_package(self):
        from core.synapse import (
            Message,
            MessageHeader,
            MessageThread,
            MessageType,
            Priority,
            create_broadcast,
            create_message,
            create_request,
            validate_message,
        )

        assert all(
            [
                Message,
                MessageHeader,
                MessageThread,
                MessageType,
                Priority,
                create_message,
                create_request,
                create_broadcast,
                validate_message,
            ]
        )

    def test_from_module(self):
        from core.synapse.message_protocol import (
            PRIORITY_ORDER,
            Message,
            MessageHeader,
            MessageThread,
            MessageType,
            Priority,
            create_message,
            validate_message,
        )

        assert all(
            [
                Message,
                MessageHeader,
                MessageThread,
                MessageType,
                Priority,
                PRIORITY_ORDER,
                create_message,
                validate_message,
            ]
        )
