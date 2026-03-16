"""
Agent Role Tracker - Track agent performance per assigned role.

V12.4 COGNITIVE BOOST

Tracks how well each agent performs in different swarm roles
(lead, support, specialist, proposer, attacker, defender), enabling
data-driven role assignment for future collaborations.

Usage:
    from core.intelligence.swarm.agent_role_tracker import get_role_tracker

    tracker = get_role_tracker()

    # Record a role assignment outcome
    assignment = tracker.record_assignment(
        agent_id="claude",
        role="lead",
        mode="LEAD_SUPPORT",
        task_domain="coding",
        quality_score=0.92,
        success=True,
        duration_ms=1250.0,
    )

    # Query best agent for a role
    best = tracker.get_best_agent_for_role("lead")

    # Query best role for an agent
    role = tracker.get_best_role_for_agent("claude")

    # Get aggregated statistics
    stats = tracker.get_stats()
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

MAX_ASSIGNMENTS = 50000

ROLES = {"lead", "support", "specialist", "proposer", "attacker", "defender"}


# =============================================================================
# Helpers
# =============================================================================


def _utc_iso_now() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(UTC).isoformat()


# =============================================================================
# Types
# =============================================================================


@dataclass
class RoleAssignment:
    """Record of a single role assignment."""

    agent_id: str = ""
    role: str = ""
    mode: str = ""
    task_domain: str = ""
    quality_score: float = 0.0
    success: bool = True
    duration_ms: float = 0.0
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = _utc_iso_now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "role": self.role,
            "mode": self.mode,
            "task_domain": self.task_domain,
            "quality_score": round(self.quality_score, 4),
            "success": self.success,
            "duration_ms": round(self.duration_ms, 2),
            "timestamp": self.timestamp,
        }


@dataclass
class AgentRoleProfile:
    """Aggregated per-agent per-role performance."""

    agent_id: str = ""
    role: str = ""
    total_assignments: int = 0
    successes: int = 0
    total_quality: float = 0.0

    @property
    def success_rate(self) -> float:
        if self.total_assignments > 0:
            return self.successes / self.total_assignments
        return 0.0

    @property
    def avg_quality(self) -> float:
        if self.total_assignments > 0:
            return self.total_quality / self.total_assignments
        return 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "role": self.role,
            "total_assignments": self.total_assignments,
            "successes": self.successes,
            "total_quality": round(self.total_quality, 4),
            "success_rate": round(self.success_rate, 4),
            "avg_quality": round(self.avg_quality, 4),
        }


@dataclass
class RoleTrackerStats:
    """Overall role tracker statistics."""

    total_assignments: int = 0
    unique_agents: int = 0
    unique_roles: int = 0
    overall_success_rate: float = 0.0
    overall_avg_quality: float = 0.0
    best_agent: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_assignments": self.total_assignments,
            "unique_agents": self.unique_agents,
            "unique_roles": self.unique_roles,
            "overall_success_rate": round(self.overall_success_rate, 4),
            "overall_avg_quality": round(self.overall_avg_quality, 4),
            "best_agent": self.best_agent,
        }


# =============================================================================
# Agent Role Tracker
# =============================================================================


class AgentRoleTracker:
    """
    Tracks agent performance per assigned role.

    Features:
    - Record role assignment outcomes with quality and success
    - Aggregated per-agent per-role profiles
    - Best agent/role queries for intelligent assignment
    - Bounded history with FIFO eviction
    - Thread-safe operations
    """

    def __init__(self, max_assignments: int = MAX_ASSIGNMENTS) -> None:
        self._assignments: list[RoleAssignment] = []
        self._profiles: dict[str, AgentRoleProfile] = {}
        self._max_assignments = max_assignments
        self._lock = threading.Lock()

    # =========================================================================
    # Recording
    # =========================================================================

    def record_assignment(
        self,
        agent_id: str,
        role: str,
        mode: str = "",
        task_domain: str = "",
        quality_score: float = 0.0,
        success: bool = True,
        duration_ms: float = 0.0,
    ) -> RoleAssignment:
        """
        Record a role assignment outcome.

        Args:
            agent_id: Identifier of the agent assigned
            role: Role assigned (lead, support, specialist, etc.)
            mode: Swarm mode used (PARALLEL, LEAD_SUPPORT, etc.)
            task_domain: Domain of the task
            quality_score: Outcome quality (0.0-1.0)
            success: Whether the assignment succeeded
            duration_ms: Duration in milliseconds

        Returns:
            The recorded RoleAssignment
        """
        assignment = RoleAssignment(
            agent_id=agent_id,
            role=role,
            mode=mode,
            task_domain=task_domain,
            quality_score=quality_score,
            success=success,
            duration_ms=duration_ms,
        )

        with self._lock:
            # Update profile
            key = f"{agent_id}:{role}"
            if key not in self._profiles:
                self._profiles[key] = AgentRoleProfile(
                    agent_id=agent_id,
                    role=role,
                )

            profile = self._profiles[key]
            profile.total_assignments += 1
            if success:
                profile.successes += 1
            profile.total_quality += quality_score

            # FIFO eviction
            self._assignments.append(assignment)
            while len(self._assignments) > self._max_assignments:
                self._assignments.pop(0)

        return assignment

    # =========================================================================
    # Profile Queries
    # =========================================================================

    def get_agent_role_profile(self, agent_id: str, role: str) -> AgentRoleProfile | None:
        """
        Get the performance profile for a specific agent-role combination.

        Args:
            agent_id: Agent identifier
            role: Role name

        Returns:
            AgentRoleProfile or None if no data exists
        """
        with self._lock:
            key = f"{agent_id}:{role}"
            profile = self._profiles.get(key)
            return profile

    def get_agent_profiles(self, agent_id: str) -> list[AgentRoleProfile]:
        """
        Get all role profiles for a given agent, sorted by avg_quality desc.

        Args:
            agent_id: Agent identifier

        Returns:
            List of AgentRoleProfile sorted by average quality descending
        """
        with self._lock:
            profiles = [p for p in self._profiles.values() if p.agent_id == agent_id]
        profiles.sort(key=lambda p: p.avg_quality, reverse=True)
        return profiles

    def get_role_profiles(self, role: str) -> list[AgentRoleProfile]:
        """
        Get all agent profiles for a given role, sorted by avg_quality desc.

        Args:
            role: Role name

        Returns:
            List of AgentRoleProfile sorted by average quality descending
        """
        with self._lock:
            profiles = [p for p in self._profiles.values() if p.role == role]
        profiles.sort(key=lambda p: p.avg_quality, reverse=True)
        return profiles

    # =========================================================================
    # Best-Of Queries
    # =========================================================================

    def get_best_agent_for_role(self, role: str) -> str | None:
        """
        Get the agent with highest avg_quality for a role.

        Args:
            role: Role name

        Returns:
            Agent ID of the best performer, or None if no data
        """
        profiles = self.get_role_profiles(role)
        if not profiles:
            return None
        return profiles[0].agent_id

    def get_best_role_for_agent(self, agent_id: str) -> str | None:
        """
        Get the role with highest avg_quality for an agent.

        Args:
            agent_id: Agent identifier

        Returns:
            Role name of the best fit, or None if no data
        """
        profiles = self.get_agent_profiles(agent_id)
        if not profiles:
            return None
        return profiles[0].role

    # =========================================================================
    # Recent Assignments
    # =========================================================================

    def get_recent_assignments(self, limit: int = 20) -> list[RoleAssignment]:
        """
        Get the most recent role assignments.

        Args:
            limit: Maximum number of assignments to return

        Returns:
            List of RoleAssignment (newest first)
        """
        with self._lock:
            assignments = list(self._assignments[-limit:])
        assignments.reverse()
        return assignments

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> RoleTrackerStats:
        """Get aggregated role tracker statistics."""
        with self._lock:
            total = len(self._assignments)
            if total == 0:
                return RoleTrackerStats()

            successes = sum(1 for a in self._assignments if a.success)
            total_quality = sum(a.quality_score for a in self._assignments)

            agents = set(p.agent_id for p in self._profiles.values())
            roles = set(p.role for p in self._profiles.values())

            # Find best agent by overall avg_quality across all roles
            agent_quality: dict[str, list[float]] = {}
            for p in self._profiles.values():
                if p.agent_id not in agent_quality:
                    agent_quality[p.agent_id] = []
                agent_quality[p.agent_id].append(p.avg_quality)

            best_agent = ""
            if agent_quality:
                best_agent = max(
                    agent_quality,
                    key=lambda a: sum(agent_quality[a]) / len(agent_quality[a]),
                )

        return RoleTrackerStats(
            total_assignments=total,
            unique_agents=len(agents),
            unique_roles=len(roles),
            overall_success_rate=successes / total,
            overall_avg_quality=total_quality / total,
            best_agent=best_agent,
        )

    # =========================================================================
    # State
    # =========================================================================

    @property
    def assignment_count(self) -> int:
        return len(self._assignments)

    def list_agents(self) -> list[str]:
        """Get sorted list of unique agent IDs."""
        with self._lock:
            agents = set(p.agent_id for p in self._profiles.values())
        return sorted(agents)

    def list_roles(self) -> list[str]:
        """Get sorted list of unique role names used."""
        with self._lock:
            roles = set(p.role for p in self._profiles.values())
        return sorted(roles)

    def clear(self) -> None:
        """Clear all tracked data."""
        with self._lock:
            self._assignments.clear()
            self._profiles.clear()

    def to_dict(self) -> dict[str, Any]:
        # CRITICAL: call get_stats() BEFORE acquiring self._lock
        # to avoid deadlock (get_stats also acquires the lock).
        stats = self.get_stats()
        with self._lock:
            return {
                "assignment_count": len(self._assignments),
                "stats": stats.to_dict(),
            }


# =============================================================================
# Global Instance
# =============================================================================

_tracker: AgentRoleTracker | None = None
_tracker_lock = threading.Lock()


def get_role_tracker() -> AgentRoleTracker:
    """Get or create the global agent role tracker."""
    global _tracker
    if _tracker is None:
        with _tracker_lock:
            if _tracker is None:
                _tracker = AgentRoleTracker()
    return _tracker


def reset_role_tracker() -> None:
    """Reset the global agent role tracker (for testing)."""
    global _tracker
    _tracker = None
