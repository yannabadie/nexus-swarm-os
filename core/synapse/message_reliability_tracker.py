"""
Message Reliability Tracker - Inter-Agent Message Delivery Monitoring

NEXUS V12.4 COGNITIVE BOOST - Track message delivery reliability between agents.

This module provides comprehensive tracking of message delivery between agents,
including success rates per agent pair, latency patterns, dead letter analysis,
and agent responsiveness metrics.

Thread Safety:
    Uses threading.Lock() for thread-safe operations across all public methods.
    Implements singleton pattern with double-checked locking.

Storage:
    In-memory bounded FIFO queue with configurable maximum deliveries.
    Oldest deliveries are evicted when limit is reached.

Metrics Tracked:
    - Per-channel delivery rates (sender -> receiver pairs)
    - Message latency patterns (ms)
    - Dead letter analysis
    - Agent responsiveness metrics
    - Message type distribution

Usage:
    tracker = get_message_tracker()

    # Record a successful delivery
    record = tracker.record_delivery(
        sender="gemini",
        receiver="claude",
        message_type="talk",
        delivered=True,
        latency_ms=125.5
    )

    # Get channel metrics
    metrics = tracker.get_channel_metrics("gemini", "claude")
    print(f"Delivery rate: {metrics.delivery_rate:.2%}")

    # Get overall stats
    stats = tracker.get_stats()
    print(f"Total messages: {stats.total_messages}")

Author: Claude (NEXUS V12.4)
Date: 2026-02-16
"""

from __future__ import annotations

import dataclasses
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

# =============================================================================
# Constants
# =============================================================================

MAX_DELIVERIES: int = 50000


# =============================================================================
# Dataclasses
# =============================================================================


@dataclass
class DeliveryRecord:
    """
    A single message delivery record.

    Captures all metadata about one message delivery attempt between agents,
    including delivery status, latency, and dead letter flag.

    Attributes:
        delivery_id: Unique identifier for this delivery (auto-generated)
        sender: Agent ID that sent the message
        receiver: Agent ID that should receive the message
        message_type: Type of message (e.g. "talk", "tool_request", "tool_result")
        delivered: Whether the message was successfully delivered
        latency_ms: Message delivery latency in milliseconds
        dead_letter: Whether this message ended up in dead letter queue
        timestamp: ISO timestamp of delivery attempt
    """

    delivery_id: str = ""
    sender: str = ""
    receiver: str = ""
    message_type: str = ""
    delivered: bool = True
    latency_ms: float = 0.0
    dead_letter: bool = False
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return dataclasses.asdict(self)


@dataclass
class ChannelMetrics:
    """
    Aggregate metrics for a sender->receiver channel.

    Tracks cumulative statistics for all messages sent from one agent to another,
    including delivery rates and latency patterns.

    Attributes:
        sender: Sender agent ID
        receiver: Receiver agent ID
        total_messages: Total number of messages sent on this channel
        delivered_count: Number of successfully delivered messages
        dead_letters: Number of messages that became dead letters
        total_latency_ms: Cumulative latency across all delivered messages

    Computed Properties:
        delivery_rate: Percentage of messages successfully delivered (0.0-1.0)
        avg_latency_ms: Average latency per delivered message
    """

    sender: str = ""
    receiver: str = ""
    total_messages: int = 0
    delivered_count: int = 0
    dead_letters: int = 0
    total_latency_ms: float = 0.0

    @property
    def delivery_rate(self) -> float:
        """Calculate delivery success rate (0.0 to 1.0)."""
        if self.total_messages == 0:
            return 0.0
        return self.delivered_count / self.total_messages

    @property
    def avg_latency_ms(self) -> float:
        """Calculate average delivery latency in milliseconds."""
        if self.delivered_count == 0:
            return 0.0
        return self.total_latency_ms / self.delivered_count

    def to_dict(self) -> dict[str, Any]:
        """
        Convert to dictionary including computed properties.

        Returns dict with all fields plus delivery_rate and avg_latency_ms.
        """
        base = dataclasses.asdict(self)
        base["delivery_rate"] = round(self.delivery_rate, 4)
        base["avg_latency_ms"] = round(self.avg_latency_ms, 2)
        return base


@dataclass
class ReliabilityStats:
    """
    Overall reliability statistics across all channels.

    Provides high-level metrics about message delivery reliability
    across the entire agent communication network.

    Attributes:
        total_messages: Total messages tracked
        unique_senders: Number of unique sender agents
        unique_receivers: Number of unique receiver agents
        unique_channels: Number of unique sender->receiver pairs
        overall_delivery_rate: System-wide delivery success rate (0.0-1.0)
        total_dead_letters: Total messages in dead letter state
    """

    total_messages: int = 0
    unique_senders: int = 0
    unique_receivers: int = 0
    unique_channels: int = 0
    overall_delivery_rate: float = 0.0
    total_dead_letters: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return dataclasses.asdict(self)


# =============================================================================
# Main Tracker Class
# =============================================================================


class MessageReliabilityTracker:
    """
    Thread-safe tracker for inter-agent message delivery reliability.

    Maintains bounded FIFO history of message deliveries with automatic
    eviction when capacity is reached. Tracks per-channel metrics and
    overall system reliability statistics.

    Thread Safety:
        All public methods are protected by a single threading.Lock().
        Safe for concurrent access from multiple threads.

    Capacity Management:
        When delivery_count reaches max_deliveries, oldest delivery is
        evicted (FIFO) to maintain bounded memory usage.

    Attributes:
        _max_deliveries: Maximum number of deliveries to track
        _deliveries: List of all delivery records (FIFO)
        _channels: Dict mapping "sender->receiver" to ChannelMetrics
        _counter: Auto-incrementing counter for delivery IDs
        _lock: Thread lock for synchronization
    """

    def __init__(self, max_deliveries: int = MAX_DELIVERIES):
        """
        Initialize message reliability tracker.

        Args:
            max_deliveries: Maximum number of delivery records to retain.
                          Oldest records are evicted when this limit is reached.
        """
        self._max_deliveries = max_deliveries
        self._deliveries: list[DeliveryRecord] = []
        self._channels: dict[str, ChannelMetrics] = {}
        self._counter: int = 1
        self._lock = threading.Lock()

    def record_delivery(
        self,
        sender: str,
        receiver: str,
        message_type: str = "",
        delivered: bool = True,
        latency_ms: float = 0.0,
        dead_letter: bool = False,
    ) -> DeliveryRecord:
        """
        Record a message delivery attempt.

        Creates a delivery record and updates channel metrics. Auto-generates
        delivery_id and timestamp. Evicts oldest record if at capacity.

        Args:
            sender: Agent ID that sent the message
            receiver: Agent ID that should receive the message
            message_type: Type of message (e.g. "talk", "tool_request")
            delivered: Whether delivery succeeded
            latency_ms: Delivery latency in milliseconds
            dead_letter: Whether message became a dead letter

        Returns:
            DeliveryRecord instance with all metadata populated

        Thread Safety:
            Method is thread-safe. Can be called concurrently.
        """
        with self._lock:
            # Auto-generate delivery_id
            delivery_id = f"md_{self._counter:06d}"
            self._counter += 1

            # Create timestamp
            timestamp = datetime.now(UTC).isoformat()

            # Create delivery record
            record = DeliveryRecord(
                delivery_id=delivery_id,
                sender=sender,
                receiver=receiver,
                message_type=message_type,
                delivered=delivered,
                latency_ms=latency_ms,
                dead_letter=dead_letter,
                timestamp=timestamp,
            )

            # Update channel metrics
            channel_key = f"{sender}->{receiver}"
            if channel_key not in self._channels:
                self._channels[channel_key] = ChannelMetrics(sender=sender, receiver=receiver)

            channel = self._channels[channel_key]
            channel.total_messages += 1
            if delivered:
                channel.delivered_count += 1
                channel.total_latency_ms += latency_ms
            if dead_letter:
                channel.dead_letters += 1

            # FIFO eviction if at capacity
            if len(self._deliveries) >= self._max_deliveries:
                self._deliveries.pop(0)

            self._deliveries.append(record)

            return record

    def get_channel_metrics(self, sender: str, receiver: str) -> ChannelMetrics | None:
        """
        Get metrics for a specific sender->receiver channel.

        Args:
            sender: Sender agent ID
            receiver: Receiver agent ID

        Returns:
            ChannelMetrics instance if channel exists, None otherwise

        Thread Safety:
            Method is thread-safe.
        """
        with self._lock:
            channel_key = f"{sender}->{receiver}"
            return self._channels.get(channel_key)

    def get_all_channels(self) -> list[ChannelMetrics]:
        """
        Get metrics for all channels.

        Returns:
            List of ChannelMetrics sorted by total_messages descending

        Thread Safety:
            Method is thread-safe.
        """
        with self._lock:
            channels = list(self._channels.values())
            return sorted(channels, key=lambda c: c.total_messages, reverse=True)

    def get_dead_letters(self) -> list[DeliveryRecord]:
        """
        Get all deliveries marked as dead letters.

        Returns:
            List of DeliveryRecord instances with dead_letter=True

        Thread Safety:
            Method is thread-safe.
        """
        with self._lock:
            return [d for d in self._deliveries if d.dead_letter]

    def get_messages_by_sender(self, sender: str) -> list[DeliveryRecord]:
        """
        Get all deliveries from a specific sender.

        Args:
            sender: Agent ID to filter by

        Returns:
            List of DeliveryRecord instances from this sender

        Thread Safety:
            Method is thread-safe.
        """
        with self._lock:
            return [d for d in self._deliveries if d.sender == sender]

    def get_recent_deliveries(self, limit: int = 10) -> list[DeliveryRecord]:
        """
        Get the most recent delivery records.

        Args:
            limit: Maximum number of records to return

        Returns:
            List of up to 'limit' most recent DeliveryRecord instances

        Thread Safety:
            Method is thread-safe.
        """
        with self._lock:
            return self._deliveries[-limit:]

    def list_senders(self) -> list[str]:
        """
        Get list of all unique sender agent IDs.

        Returns:
            List of sender IDs sorted alphabetically

        Thread Safety:
            Method is thread-safe.
        """
        with self._lock:
            senders = set(d.sender for d in self._deliveries)
            return sorted(senders)

    def list_receivers(self) -> list[str]:
        """
        Get list of all unique receiver agent IDs.

        Returns:
            List of receiver IDs sorted alphabetically

        Thread Safety:
            Method is thread-safe.
        """
        with self._lock:
            receivers = set(d.receiver for d in self._deliveries)
            return sorted(receivers)

    def get_stats(self) -> ReliabilityStats:
        """
        Calculate overall reliability statistics.

        Computes system-wide metrics across all channels including
        total messages, unique agents, delivery rates, and dead letters.

        Returns:
            ReliabilityStats instance with current statistics

        Thread Safety:
            Method is thread-safe.
        """
        with self._lock:
            total_messages = len(self._deliveries)
            unique_senders = len(set(d.sender for d in self._deliveries))
            unique_receivers = len(set(d.receiver for d in self._deliveries))
            unique_channels = len(self._channels)

            # Calculate overall delivery rate
            if total_messages > 0:
                delivered = sum(1 for d in self._deliveries if d.delivered)
                overall_delivery_rate = delivered / total_messages
            else:
                overall_delivery_rate = 0.0

            # Count dead letters
            total_dead_letters = sum(1 for d in self._deliveries if d.dead_letter)

            return ReliabilityStats(
                total_messages=total_messages,
                unique_senders=unique_senders,
                unique_receivers=unique_receivers,
                unique_channels=unique_channels,
                overall_delivery_rate=round(overall_delivery_rate, 4),
                total_dead_letters=total_dead_letters,
            )

    @property
    def delivery_count(self) -> int:
        """
        Get current number of tracked deliveries.

        Returns:
            Number of delivery records currently in tracker

        Thread Safety:
            Property is thread-safe.
        """
        with self._lock:
            return len(self._deliveries)

    def clear(self) -> None:
        """
        Clear all delivery records and channel metrics.

        Resets tracker to initial state. Counter is NOT reset to maintain
        unique delivery_id generation across clears.

        Thread Safety:
            Method is thread-safe.
        """
        with self._lock:
            self._deliveries.clear()
            self._channels.clear()

    def to_dict(self) -> dict[str, Any]:
        """
        Export tracker state to dictionary.

        CRITICAL: Calls get_stats() and get_all_channels() BEFORE acquiring lock
        to prevent deadlock, as they also acquire the lock internally.

        Returns:
            Dict with stats, channels, and recent deliveries

        Thread Safety:
            Method is thread-safe.
        """
        # CRITICAL: Call methods that acquire lock BEFORE acquiring lock ourselves
        stats = self.get_stats()
        channels = self.get_all_channels()

        with self._lock:
            return {
                "stats": stats.to_dict(),
                "channels": [c.to_dict() for c in channels],
                "recent_deliveries": [d.to_dict() for d in self._deliveries[-20:]],
                "delivery_count": len(self._deliveries),
                "max_deliveries": self._max_deliveries,
            }


# =============================================================================
# Singleton Pattern (Double-Checked Locking)
# =============================================================================

_instance: MessageReliabilityTracker | None = None
_lock = threading.Lock()


def get_message_tracker() -> MessageReliabilityTracker:
    """
    Get the global MessageReliabilityTracker singleton instance.

    Uses double-checked locking pattern for thread-safe lazy initialization.
    The singleton is created on first call and reused for all subsequent calls.

    Returns:
        Global MessageReliabilityTracker instance

    Thread Safety:
        Function is thread-safe. Multiple concurrent calls will return
        the same instance without creating duplicates.

    Example:
        tracker = get_message_tracker()
        tracker.record_delivery("gemini", "claude", delivered=True)
    """
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = MessageReliabilityTracker()
    return _instance


def reset_message_tracker() -> None:
    """
    Reset the global singleton instance.

    Creates a new MessageReliabilityTracker instance, discarding all
    existing delivery records and metrics. Primarily used for testing.

    Thread Safety:
        Function is thread-safe.

    Warning:
        This destroys all tracked delivery history. Use only for testing
        or when explicitly needed to clear state.
    """
    global _instance
    with _lock:
        _instance = MessageReliabilityTracker()
