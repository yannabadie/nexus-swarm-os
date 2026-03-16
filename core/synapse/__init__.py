"""NEXUS V7 Synapse - Protocol & Memory"""

# V12.4 COGNITIVE BOOST: Inter-Agent Message Protocol
# V12.4 COGNITIVE BOOST: Message Deduplicator
from .message_deduplicator import (  # noqa: F401  # public API re-exports
    DeduplicationStats,
    MessageDeduplicator,
    MessageFingerprint,
    MessageTrace,
    compute_fingerprint,
    get_deduplicator,
    reset_deduplicator,
)
from .message_protocol import (  # noqa: F401  # public API re-exports
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

# V12.4 COGNITIVE BOOST: Message Reliability Tracker
from .message_reliability_tracker import (  # noqa: F401  # public API re-exports
    ChannelMetrics,
    DeliveryRecord,
    MessageReliabilityTracker,
    get_message_tracker,
    reset_message_tracker,
)
from .message_reliability_tracker import (  # noqa: F401  # public API re-export
    ReliabilityStats as MessageReliabilityStats,
)

# V12.4: Message Router
from .message_router import (  # noqa: F401  # public API re-exports
    DeadLetter,
    MessageRouter,
    QueueInfo,
    RoutedMessage,
    RouteResult,
    RouterStats,
    get_message_router,
    reset_message_router,
)

# V12.4 COGNITIVE BOOST: AgentDiet Trajectory Pruner (arxiv:2509.23586)
from .trajectory_pruner import (  # noqa: F401  # public API re-exports
    PruneDecision,
    PruneReason,
    PruneResult,
    PrunerStats,
    TrajectoryMessage,
    TrajectoryPruner,
    get_trajectory_pruner,
    reset_trajectory_pruner,
)
