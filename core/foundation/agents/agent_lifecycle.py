"""
Agent Lifecycle Manager - Degradation, retirement, and replacement.

V12.4 COGNITIVE BOOST

Tracks agent health over time and applies lifecycle policies:
- Degradation: Agents with declining performance get flagged
- Retirement: Agents below thresholds are marked for retirement
- Replacement: Suggests replacement agents based on capabilities

Usage:
    from core.foundation.agents.agent_lifecycle import get_lifecycle_manager

    mgr = get_lifecycle_manager()
    mgr.register("claude", capabilities=["coding", "debugging"])
    mgr.record_outcome("claude", success=True, quality=0.9)

    # Check health
    health = mgr.get_health("claude")

    # Apply retirement policy
    retired = mgr.apply_retirements()
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

DEFAULT_MIN_QUALITY = 0.3  # Below this = retirement candidate
DEFAULT_MAX_CONSECUTIVE_FAILURES = 5  # This many failures in a row = retire
DEFAULT_OBSERVATION_WINDOW = 50  # Last N outcomes considered
MAX_AGENTS = 5000


# =============================================================================
# Types
# =============================================================================


@dataclass
class RetirementPolicy:
    """Configuration for agent retirement triggers."""

    min_quality: float = DEFAULT_MIN_QUALITY
    max_consecutive_failures: int = DEFAULT_MAX_CONSECUTIVE_FAILURES
    observation_window: int = DEFAULT_OBSERVATION_WINDOW
    min_observations: int = 5  # Need at least this many before retiring

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_quality": self.min_quality,
            "max_consecutive_failures": self.max_consecutive_failures,
            "observation_window": self.observation_window,
            "min_observations": self.min_observations,
        }


@dataclass
class AgentHealthSnapshot:
    """Current health status of an agent."""

    agent_id: str
    total_tasks: int = 0
    successes: int = 0
    failures: int = 0
    consecutive_failures: int = 0
    average_quality: float = 0.0
    is_degraded: bool = False
    is_retired: bool = False
    registered_at: float = field(default_factory=time.monotonic)
    last_active_at: float = field(default_factory=time.monotonic)
    capabilities: list[str] = field(default_factory=list)
    retirement_reason: str = ""

    @property
    def success_rate(self) -> float:
        if self.total_tasks == 0:
            return 0.0
        return self.successes / self.total_tasks

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "total_tasks": self.total_tasks,
            "successes": self.successes,
            "failures": self.failures,
            "consecutive_failures": self.consecutive_failures,
            "average_quality": round(self.average_quality, 4),
            "success_rate": round(self.success_rate, 4),
            "is_degraded": self.is_degraded,
            "is_retired": self.is_retired,
            "capabilities": self.capabilities,
            "retirement_reason": self.retirement_reason,
        }


@dataclass
class LifecycleEvent:
    """Record of a lifecycle state change."""

    agent_id: str
    event_type: str  # "registered", "degraded", "recovered", "retired", "replaced"
    timestamp: float = field(default_factory=time.monotonic)
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "details": self.details,
        }


@dataclass
class LifecycleStats:
    """Aggregate lifecycle statistics."""

    total_agents: int
    active_agents: int
    degraded_agents: int
    retired_agents: int
    total_events: int
    total_retirements: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_agents": self.total_agents,
            "active_agents": self.active_agents,
            "degraded_agents": self.degraded_agents,
            "retired_agents": self.retired_agents,
            "total_events": self.total_events,
            "total_retirements": self.total_retirements,
        }


# =============================================================================
# Lifecycle Manager
# =============================================================================


class AgentLifecycleManager:
    """
    Manages agent lifecycle: degradation, retirement, replacement.

    Features:
    - Track agent health via outcome recording
    - Configurable retirement policies
    - Automatic degradation detection
    - Lifecycle event history
    - Thread-safe
    """

    def __init__(self, *, policy: RetirementPolicy | None = None):
        self._policy = policy or RetirementPolicy()
        self._agents: dict[str, AgentHealthSnapshot] = {}
        self._quality_history: dict[str, list[float]] = {}  # agent_id -> recent quality scores
        self._events: list[LifecycleEvent] = []
        self._total_retirements = 0
        self._lock = threading.Lock()

    @property
    def policy(self) -> RetirementPolicy:
        return self._policy

    def set_policy(self, policy: RetirementPolicy) -> None:
        """Update the retirement policy."""
        with self._lock:
            self._policy = policy

    # =========================================================================
    # Registration
    # =========================================================================

    def register(self, agent_id: str, *, capabilities: list[str] | None = None) -> bool:
        """Register an agent for lifecycle tracking. Returns False if already registered or at limit."""
        with self._lock:
            if agent_id in self._agents:
                return False
            if len(self._agents) >= MAX_AGENTS:
                return False
            self._agents[agent_id] = AgentHealthSnapshot(
                agent_id=agent_id,
                capabilities=capabilities or [],
            )
            self._quality_history[agent_id] = []
            self._events.append(
                LifecycleEvent(
                    agent_id=agent_id,
                    event_type="registered",
                    details=f"Capabilities: {capabilities or []}",
                )
            )
            return True

    def unregister(self, agent_id: str) -> bool:
        """Remove an agent from lifecycle tracking."""
        with self._lock:
            if agent_id not in self._agents:
                return False
            del self._agents[agent_id]
            self._quality_history.pop(agent_id, None)
            return True

    def is_registered(self, agent_id: str) -> bool:
        return agent_id in self._agents

    def list_agents(self) -> list[str]:
        """List all registered agent IDs (sorted)."""
        return sorted(self._agents.keys())

    # =========================================================================
    # Outcome Recording
    # =========================================================================

    def record_outcome(self, agent_id: str, *, success: bool, quality: float = 1.0) -> bool:
        """
        Record a task outcome for an agent.

        Args:
            agent_id: Agent identifier
            success: Whether the task succeeded
            quality: Quality score 0.0-1.0 (only matters if success=True)

        Returns:
            True if recorded, False if agent not found
        """
        with self._lock:
            snap = self._agents.get(agent_id)
            if snap is None:
                return False

            snap.total_tasks += 1
            snap.last_active_at = time.monotonic()

            if success:
                snap.successes += 1
                snap.consecutive_failures = 0
                q = max(0.0, min(1.0, quality))
            else:
                snap.failures += 1
                snap.consecutive_failures += 1
                q = 0.0

            # Update quality history (bounded window)
            history = self._quality_history[agent_id]
            history.append(q)
            if len(history) > self._policy.observation_window:
                history.pop(0)

            # Recalculate average quality
            snap.average_quality = sum(history) / len(history) if history else 0.0

            # Check degradation
            was_degraded = snap.is_degraded
            snap.is_degraded = self._check_degraded(snap)

            if snap.is_degraded and not was_degraded:
                self._events.append(
                    LifecycleEvent(
                        agent_id=agent_id,
                        event_type="degraded",
                        details=f"Quality={snap.average_quality:.3f}, ConsecFail={snap.consecutive_failures}",
                    )
                )
            elif not snap.is_degraded and was_degraded:
                self._events.append(
                    LifecycleEvent(
                        agent_id=agent_id,
                        event_type="recovered",
                        details=f"Quality={snap.average_quality:.3f}",
                    )
                )

            return True

    def _check_degraded(self, snap: AgentHealthSnapshot) -> bool:
        """Check if an agent should be flagged as degraded."""
        if snap.is_retired:
            return True
        # Degraded if quality is low (but above retirement threshold) or consecutive failures mounting
        half_max = self._policy.max_consecutive_failures // 2
        if snap.consecutive_failures >= max(1, half_max):
            return True
        return (
            snap.total_tasks >= self._policy.min_observations and snap.average_quality < self._policy.min_quality * 1.5
        )

    # =========================================================================
    # Retirement
    # =========================================================================

    def should_retire(self, agent_id: str) -> bool:
        """Check if an agent meets retirement criteria."""
        snap = self._agents.get(agent_id)
        if snap is None or snap.is_retired:
            return False
        return self._meets_retirement_criteria(snap)

    def _meets_retirement_criteria(self, snap: AgentHealthSnapshot) -> bool:
        """Check retirement criteria against policy."""
        if snap.total_tasks < self._policy.min_observations:
            return False
        if snap.consecutive_failures >= self._policy.max_consecutive_failures:
            return True
        return snap.average_quality < self._policy.min_quality

    def retire(self, agent_id: str, *, reason: str = "") -> bool:
        """Manually retire an agent."""
        with self._lock:
            snap = self._agents.get(agent_id)
            if snap is None or snap.is_retired:
                return False
            snap.is_retired = True
            snap.is_degraded = True
            snap.retirement_reason = reason or "Manual retirement"
            self._total_retirements += 1
            self._events.append(
                LifecycleEvent(
                    agent_id=agent_id,
                    event_type="retired",
                    details=snap.retirement_reason,
                )
            )
            return True

    def apply_retirements(self) -> list[str]:
        """Apply retirement policy to all agents. Returns list of newly retired agent IDs."""
        with self._lock:
            retired = []
            for agent_id, snap in self._agents.items():
                if snap.is_retired:
                    continue
                if self._meets_retirement_criteria(snap):
                    snap.is_retired = True
                    snap.is_degraded = True
                    if snap.consecutive_failures >= self._policy.max_consecutive_failures:
                        snap.retirement_reason = f"Consecutive failures: {snap.consecutive_failures}"
                    else:
                        snap.retirement_reason = f"Low quality: {snap.average_quality:.3f}"
                    self._total_retirements += 1
                    self._events.append(
                        LifecycleEvent(
                            agent_id=agent_id,
                            event_type="retired",
                            details=snap.retirement_reason,
                        )
                    )
                    retired.append(agent_id)
            return retired

    def reinstate(self, agent_id: str) -> bool:
        """Reinstate a retired agent, resetting its failure counters."""
        with self._lock:
            snap = self._agents.get(agent_id)
            if snap is None or not snap.is_retired:
                return False
            snap.is_retired = False
            snap.is_degraded = False
            snap.consecutive_failures = 0
            snap.retirement_reason = ""
            self._quality_history[agent_id] = []
            snap.average_quality = 0.0
            self._events.append(
                LifecycleEvent(
                    agent_id=agent_id,
                    event_type="reinstated",
                    details="Retired agent reinstated, history cleared",
                )
            )
            return True

    # =========================================================================
    # Queries
    # =========================================================================

    def get_health(self, agent_id: str) -> AgentHealthSnapshot | None:
        """Get health snapshot for an agent."""
        return self._agents.get(agent_id)

    def get_active_agents(self) -> list[str]:
        """List agents that are not retired."""
        return sorted(aid for aid, snap in self._agents.items() if not snap.is_retired)

    def get_degraded_agents(self) -> list[str]:
        """List agents flagged as degraded (but not yet retired)."""
        return sorted(aid for aid, snap in self._agents.items() if snap.is_degraded and not snap.is_retired)

    def get_retired_agents(self) -> list[str]:
        """List retired agents."""
        return sorted(aid for aid, snap in self._agents.items() if snap.is_retired)

    def get_events(
        self, *, agent_id: str | None = None, event_type: str | None = None, limit: int = 100
    ) -> list[LifecycleEvent]:
        """Get lifecycle events with optional filters."""
        events = list(reversed(self._events))
        if agent_id:
            events = [e for e in events if e.agent_id == agent_id]
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        return events[:limit]

    def find_replacement(self, agent_id: str) -> str | None:
        """
        Find a replacement for a retired/degraded agent based on shared capabilities.
        Returns the best active agent with overlapping capabilities, or None.
        """
        snap = self._agents.get(agent_id)
        if snap is None:
            return None

        target_caps = set(snap.capabilities)
        if not target_caps:
            return None

        best_id = None
        best_overlap = 0
        best_quality = -1.0

        for aid, other in self._agents.items():
            if aid == agent_id or other.is_retired:
                continue
            overlap = len(target_caps & set(other.capabilities))
            if overlap > best_overlap or (overlap == best_overlap and other.average_quality > best_quality):
                best_id = aid
                best_overlap = overlap
                best_quality = other.average_quality

        return best_id if best_overlap > 0 else None

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> LifecycleStats:
        active = sum(1 for s in self._agents.values() if not s.is_retired)
        degraded = sum(1 for s in self._agents.values() if s.is_degraded and not s.is_retired)
        retired = sum(1 for s in self._agents.values() if s.is_retired)
        return LifecycleStats(
            total_agents=len(self._agents),
            active_agents=active,
            degraded_agents=degraded,
            retired_agents=retired,
            total_events=len(self._events),
            total_retirements=self._total_retirements,
        )

    # =========================================================================
    # State
    # =========================================================================

    @property
    def agent_count(self) -> int:
        return len(self._agents)

    def clear(self) -> None:
        """Clear all lifecycle data."""
        with self._lock:
            self._agents.clear()
            self._quality_history.clear()
            self._events.clear()
            self._total_retirements = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_count": self.agent_count,
            "policy": self._policy.to_dict(),
            "stats": self.get_stats().to_dict(),
        }


# =============================================================================
# Global Instance
# =============================================================================

_manager: AgentLifecycleManager | None = None
_manager_lock = threading.Lock()


def get_lifecycle_manager() -> AgentLifecycleManager:
    """Get or create the global lifecycle manager."""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = AgentLifecycleManager()
    return _manager


def reset_lifecycle_manager() -> None:
    """Reset the global lifecycle manager (for testing)."""
    global _manager
    _manager = None
