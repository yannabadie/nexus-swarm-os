"""
Interaction Quality Tracker - Human-in-the-Loop Interaction Metrics.

V12.4 COGNITIVE BOOST

Tracks quality metrics for human-in-the-loop interactions including response
times, user satisfaction signals, interaction types (ask/confirm/choose/announce),
and session engagement patterns. Enables data-driven improvements to the
interaction layer by identifying friction points and preferred interaction modes.

Metrics Tracked:
    - Per-type interaction profiles (satisfaction rate, response time)
    - User response latency distribution
    - Satisfaction signals per interaction type
    - Session engagement via recent interaction history
    - Overall quality statistics

Thread-Safety:
    Uses threading.Lock for all mutations. Global singleton with double-checked locking.

Usage:
    from core.security_pkg.interaction.interaction_quality_tracker import get_interaction_tracker

    tracker = get_interaction_tracker()

    # Record an interaction
    record = tracker.record_interaction(
        interaction_type="ask",
        user_response_ms=1200.5,
        satisfied=True,
        context="project_name_prompt"
    )

    # Query type profile
    profile = tracker.get_type_profile("ask")
    print(f"Ask satisfaction: {profile.satisfaction_rate:.2%}")

    # Overall stats
    stats = tracker.get_stats()
    print(f"Avg response time: {stats.avg_response_ms:.0f}ms")

Author: Claude (NEXUS V12.4)
Date: 2026-02-16
"""

from __future__ import annotations

import dataclasses
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

MAX_INTERACTIONS: int = 50000


# =============================================================================
# Dataclasses
# =============================================================================


@dataclass
class InteractionRecord:
    """
    Single human-in-the-loop interaction record.

    Captures metadata for one user interaction event including type,
    response latency, satisfaction signal, and contextual information.
    """

    interaction_id: str = ""
    interaction_type: str = ""  # ask, confirm, choose, announce
    user_response_ms: float = 0.0
    satisfied: bool = True
    context: str = ""
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return dataclasses.asdict(self)


@dataclass
class InteractionTypeProfile:
    """
    Aggregate metrics for a single interaction type.

    Computed from all interactions of this type (ask, confirm, choose, announce).
    """

    interaction_type: str = ""
    total_interactions: int = 0
    satisfied_count: int = 0
    total_response_ms: float = 0.0

    @property
    def satisfaction_rate(self) -> float:
        """Ratio of satisfied interactions to total (0.0-1.0)."""
        if self.total_interactions == 0:
            return 0.0
        return self.satisfied_count / self.total_interactions

    @property
    def avg_response_ms(self) -> float:
        """Average user response time in milliseconds."""
        if self.total_interactions == 0:
            return 0.0
        return self.total_response_ms / self.total_interactions

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary with computed properties."""
        base = dataclasses.asdict(self)
        base["satisfaction_rate"] = round(self.satisfaction_rate, 4)
        base["avg_response_ms"] = round(self.avg_response_ms, 2)
        return base


@dataclass
class InteractionQualityStats:
    """
    Overall interaction quality statistics.

    Provides high-level summary of all tracked interactions.
    """

    total_interactions: int = 0
    unique_types: int = 0
    overall_satisfaction_rate: float = 0.0
    avg_response_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return dataclasses.asdict(self)


# =============================================================================
# Interaction Quality Tracker
# =============================================================================


class InteractionQualityTracker:
    """
    Tracks human-in-the-loop interaction quality metrics.

    Thread-safe singleton that records interaction events and computes
    quality metrics per interaction type and overall.

    Features:
        - Per-type interaction profiles with satisfaction and latency
        - Recent interaction history with optional type filtering
        - Overall quality statistics aggregation
        - Bounded FIFO history (configurable max)
        - Thread-safe operations

    Thread-Safety:
        All mutations are protected by threading.Lock.
        Singleton access via get_interaction_tracker() with double-checked locking.
    """

    def __init__(self, max_interactions: int = MAX_INTERACTIONS) -> None:
        """
        Initialize interaction quality tracker.

        Args:
            max_interactions: Maximum number of interactions to keep in history.
                              Oldest interactions are evicted when limit is reached.
        """
        self._max_interactions = max_interactions
        self._interactions: list[InteractionRecord] = []
        self._profiles: dict[str, InteractionTypeProfile] = {}
        self._counter = 1
        self._lock = threading.Lock()

    # =========================================================================
    # Recording
    # =========================================================================

    def record_interaction(
        self,
        interaction_type: str,
        user_response_ms: float = 0.0,
        satisfied: bool = True,
        context: str = "",
    ) -> InteractionRecord:
        """
        Record a human-in-the-loop interaction event.

        Thread-safe. Updates per-type profile and adds to history with
        FIFO eviction if at capacity.

        Args:
            interaction_type: Type of interaction (ask, confirm, choose, announce)
            user_response_ms: User response latency in milliseconds
            satisfied: Whether the user expressed satisfaction
            context: Contextual label for this interaction

        Returns:
            The created InteractionRecord
        """
        with self._lock:
            interaction_id = f"ix_{self._counter:06d}"
            self._counter += 1

            record = InteractionRecord(
                interaction_id=interaction_id,
                interaction_type=interaction_type,
                user_response_ms=user_response_ms,
                satisfied=satisfied,
                context=context,
                timestamp=datetime.now(UTC).isoformat(),
            )

            # FIFO eviction
            while len(self._interactions) >= self._max_interactions:
                self._interactions.pop(0)

            self._interactions.append(record)

            # Update type profile
            if interaction_type not in self._profiles:
                self._profiles[interaction_type] = InteractionTypeProfile(interaction_type=interaction_type)

            profile = self._profiles[interaction_type]
            profile.total_interactions += 1
            profile.total_response_ms += user_response_ms
            if satisfied:
                profile.satisfied_count += 1

        return record

    # =========================================================================
    # Profile Queries
    # =========================================================================

    def get_type_profile(self, interaction_type: str) -> InteractionTypeProfile | None:
        """
        Get the profile for a specific interaction type.

        Args:
            interaction_type: Interaction type to query (ask, confirm, choose, announce)

        Returns:
            InteractionTypeProfile if found, None otherwise
        """
        with self._lock:
            return self._profiles.get(interaction_type)

    def get_all_profiles(self) -> list[InteractionTypeProfile]:
        """
        Get profiles for all interaction types.

        Returns:
            List of InteractionTypeProfile sorted by total_interactions (descending)
        """
        with self._lock:
            profiles = list(self._profiles.values())
        return sorted(profiles, key=lambda p: p.total_interactions, reverse=True)

    # =========================================================================
    # Interaction Queries
    # =========================================================================

    def get_recent_interactions(
        self,
        limit: int = 10,
        interaction_type: str | None = None,
    ) -> list[InteractionRecord]:
        """
        Get recent interactions, optionally filtered by type.

        Args:
            limit: Maximum number of interactions to return
            interaction_type: If provided, filter to this interaction type

        Returns:
            List of InteractionRecord (most recent first)
        """
        with self._lock:
            interactions = list(self._interactions)

        if interaction_type:
            interactions = [i for i in interactions if i.interaction_type == interaction_type]

        interactions.reverse()
        return interactions[:limit]

    def list_interaction_types(self) -> list[str]:
        """
        Get list of all tracked interaction types.

        Returns:
            List of interaction type strings (sorted alphabetically)
        """
        with self._lock:
            return sorted(self._profiles.keys())

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> InteractionQualityStats:
        """
        Get overall interaction quality statistics.

        Computes aggregate metrics from all tracked interactions.

        Returns:
            InteractionQualityStats with aggregate metrics
        """
        with self._lock:
            total = len(self._interactions)
            if total == 0:
                return InteractionQualityStats()

            satisfied_count = sum(1 for i in self._interactions if i.satisfied)
            total_response_ms = sum(i.user_response_ms for i in self._interactions)

            return InteractionQualityStats(
                total_interactions=total,
                unique_types=len(self._profiles),
                overall_satisfaction_rate=satisfied_count / total,
                avg_response_ms=total_response_ms / total,
            )

    # =========================================================================
    # State
    # =========================================================================

    @property
    def interaction_count(self) -> int:
        """Total number of interactions tracked."""
        with self._lock:
            return len(self._interactions)

    def clear(self) -> None:
        """
        Clear all tracked data.

        Thread-safe. Resets tracker to initial state.
        """
        with self._lock:
            self._interactions.clear()
            self._profiles.clear()
            self._counter = 1

    def to_dict(self) -> dict[str, Any]:
        """
        Convert tracker to dictionary representation.

        CRITICAL: Calls get_stats(), get_all_profiles(), and
        get_recent_interactions() BEFORE acquiring self._lock
        to avoid deadlock (those methods also acquire the lock).

        Returns:
            Dictionary with stats, profiles, and recent interactions
        """
        # Collect data BEFORE acquiring lock (deadlock prevention)
        stats = self.get_stats()
        profiles = self.get_all_profiles()
        recent = self.get_recent_interactions(limit=20)

        with self._lock:
            return {
                "stats": stats.to_dict(),
                "profiles": [p.to_dict() for p in profiles],
                "recent_interactions": [r.to_dict() for r in recent],
                "interaction_count": len(self._interactions),
                "max_interactions": self._max_interactions,
            }


# =============================================================================
# Global Instance
# =============================================================================

_instance: InteractionQualityTracker | None = None
_lock = threading.Lock()


def get_interaction_tracker() -> InteractionQualityTracker:
    """
    Get the global InteractionQualityTracker singleton.

    Thread-safe with double-checked locking pattern.

    Returns:
        InteractionQualityTracker: Global singleton instance
    """
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = InteractionQualityTracker()
    return _instance


def reset_interaction_tracker() -> None:
    """
    Reset the global InteractionQualityTracker singleton.

    Thread-safe. Useful for testing or reinitializing state.
    """
    global _instance
    with _lock:
        _instance = None
