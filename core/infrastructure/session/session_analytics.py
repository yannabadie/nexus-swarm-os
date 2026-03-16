"""
Session Analytics - Per-session performance tracking and analysis.

V12.4 COGNITIVE BOOST

Tracks per-session metrics:
- Phase timings (duration, tokens, cost)
- Agent actions (success rate, quality)
- Session-level aggregates
- Cross-session pattern detection

Usage:
    from core.infrastructure.session.session_analytics import get_session_analytics

    analytics = get_session_analytics()
    analytics.record_phase("sess_1", phase="ANALYSIS", duration_ms=500, tokens=1200)
    analytics.record_action("sess_1", agent_id="claude", action="tool_call", success=True)
    metrics = analytics.get_session_metrics("sess_1")
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

MAX_SESSIONS = 5000
MAX_EVENTS_PER_SESSION = 10000


# =============================================================================
# Types
# =============================================================================


@dataclass
class PhaseMetric:
    """Metric for a single phase execution."""

    session_id: str
    phase: str
    duration_ms: float = 0.0
    tokens_used: int = 0
    cost: float = 0.0
    timestamp: float = field(default_factory=time.monotonic)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "phase": self.phase,
            "duration_ms": self.duration_ms,
            "tokens_used": self.tokens_used,
            "cost": self.cost,
        }


@dataclass
class AgentAction:
    """Record of an agent action within a session."""

    session_id: str
    agent_id: str
    action_type: str  # tool_call, brainstorm, validate, etc.
    success: bool = True
    quality: float = 0.0
    duration_ms: float = 0.0
    timestamp: float = field(default_factory=time.monotonic)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "action_type": self.action_type,
            "success": self.success,
            "quality": self.quality,
            "duration_ms": self.duration_ms,
        }


@dataclass
class SessionMetrics:
    """Aggregated metrics for a single session."""

    session_id: str
    total_phases: int = 0
    total_actions: int = 0
    total_duration_ms: float = 0.0
    total_tokens: int = 0
    total_cost: float = 0.0
    success_rate: float = 0.0
    average_quality: float = 0.0
    agents_involved: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "total_phases": self.total_phases,
            "total_actions": self.total_actions,
            "total_duration_ms": round(self.total_duration_ms, 2),
            "total_tokens": self.total_tokens,
            "total_cost": round(self.total_cost, 6),
            "success_rate": round(self.success_rate, 4),
            "average_quality": round(self.average_quality, 4),
            "agents_involved": self.agents_involved,
        }


@dataclass
class AnalyticsStats:
    """Overall analytics statistics."""

    total_sessions: int
    total_phases: int
    total_actions: int
    total_tokens: int
    total_cost: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_sessions": self.total_sessions,
            "total_phases": self.total_phases,
            "total_actions": self.total_actions,
            "total_tokens": self.total_tokens,
            "total_cost": round(self.total_cost, 6),
        }


# =============================================================================
# Session Analytics
# =============================================================================


class SessionAnalytics:
    """
    Per-session and cross-session performance analytics.

    Features:
    - Record phase timings (duration, tokens, cost)
    - Record agent actions (success, quality, latency)
    - Compute per-session aggregate metrics
    - Compare sessions
    - Thread-safe
    """

    def __init__(self, *, max_sessions: int = MAX_SESSIONS):
        self._max_sessions = max_sessions
        self._phases: dict[str, list[PhaseMetric]] = {}  # session_id -> phases
        self._actions: dict[str, list[AgentAction]] = {}  # session_id -> actions
        self._session_order: list[str] = []  # Track insertion order for eviction
        self._lock = threading.Lock()

    def _ensure_session(self, session_id: str) -> None:
        """Ensure session exists, evicting oldest if at limit."""
        if session_id not in self._phases:
            if len(self._phases) >= self._max_sessions:
                oldest = self._session_order.pop(0)
                self._phases.pop(oldest, None)
                self._actions.pop(oldest, None)
            self._phases[session_id] = []
            self._actions[session_id] = []
            self._session_order.append(session_id)

    # =========================================================================
    # Recording
    # =========================================================================

    def record_phase(
        self,
        session_id: str,
        *,
        phase: str,
        duration_ms: float = 0.0,
        tokens: int = 0,
        cost: float = 0.0,
    ) -> PhaseMetric:
        """Record a phase execution metric."""
        with self._lock:
            self._ensure_session(session_id)
            metric = PhaseMetric(
                session_id=session_id,
                phase=phase,
                duration_ms=duration_ms,
                tokens_used=tokens,
                cost=cost,
            )
            self._phases[session_id].append(metric)
            return metric

    def record_action(
        self,
        session_id: str,
        *,
        agent_id: str,
        action: str,
        success: bool = True,
        quality: float = 0.0,
        duration_ms: float = 0.0,
    ) -> AgentAction:
        """Record an agent action."""
        with self._lock:
            self._ensure_session(session_id)
            act = AgentAction(
                session_id=session_id,
                agent_id=agent_id,
                action_type=action,
                success=success,
                quality=quality,
                duration_ms=duration_ms,
            )
            self._actions[session_id].append(act)
            return act

    # =========================================================================
    # Session Metrics
    # =========================================================================

    def get_session_metrics(self, session_id: str) -> SessionMetrics | None:
        """Compute aggregate metrics for a session."""
        phases = self._phases.get(session_id)
        actions = self._actions.get(session_id)
        if phases is None:
            return None

        total_duration = sum(p.duration_ms for p in phases)
        total_tokens = sum(p.tokens_used for p in phases)
        total_cost = sum(p.cost for p in phases)

        successes = sum(1 for a in actions if a.success)
        total_actions = len(actions)
        success_rate = successes / total_actions if total_actions > 0 else 0.0

        qualities = [a.quality for a in actions if a.quality > 0]
        avg_quality = sum(qualities) / len(qualities) if qualities else 0.0

        agents = sorted(set(a.agent_id for a in actions))

        return SessionMetrics(
            session_id=session_id,
            total_phases=len(phases),
            total_actions=total_actions,
            total_duration_ms=total_duration,
            total_tokens=total_tokens,
            total_cost=total_cost,
            success_rate=success_rate,
            average_quality=avg_quality,
            agents_involved=agents,
        )

    def get_phase_breakdown(self, session_id: str) -> list[PhaseMetric]:
        """Get all phase metrics for a session."""
        return list(self._phases.get(session_id, []))

    def get_agent_actions(self, session_id: str, *, agent_id: str | None = None) -> list[AgentAction]:
        """Get agent actions for a session, optionally filtered by agent."""
        actions = self._actions.get(session_id, [])
        if agent_id:
            return [a for a in actions if a.agent_id == agent_id]
        return list(actions)

    # =========================================================================
    # Cross-Session Analysis
    # =========================================================================

    def get_agent_effectiveness(self, agent_id: str) -> dict[str, Any]:
        """Get aggregate effectiveness for an agent across all sessions."""
        all_actions = []
        for actions in self._actions.values():
            all_actions.extend(a for a in actions if a.agent_id == agent_id)

        if not all_actions:
            return {"agent_id": agent_id, "total_actions": 0, "success_rate": 0.0}

        successes = sum(1 for a in all_actions if a.success)
        qualities = [a.quality for a in all_actions if a.quality > 0]

        return {
            "agent_id": agent_id,
            "total_actions": len(all_actions),
            "success_rate": round(successes / len(all_actions), 4),
            "average_quality": round(sum(qualities) / len(qualities), 4) if qualities else 0.0,
            "sessions_participated": len({a.session_id for a in all_actions}),
        }

    def list_sessions(self) -> list[str]:
        """List all tracked session IDs."""
        return list(self._session_order)

    def has_session(self, session_id: str) -> bool:
        return session_id in self._phases

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> AnalyticsStats:
        total_phases = sum(len(p) for p in self._phases.values())
        total_actions = sum(len(a) for a in self._actions.values())
        total_tokens = sum(p.tokens_used for phases in self._phases.values() for p in phases)
        total_cost = sum(p.cost for phases in self._phases.values() for p in phases)
        return AnalyticsStats(
            total_sessions=len(self._phases),
            total_phases=total_phases,
            total_actions=total_actions,
            total_tokens=total_tokens,
            total_cost=total_cost,
        )

    # =========================================================================
    # State
    # =========================================================================

    @property
    def session_count(self) -> int:
        return len(self._phases)

    def clear(self) -> None:
        with self._lock:
            self._phases.clear()
            self._actions.clear()
            self._session_order.clear()

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_count": self.session_count,
            "max_sessions": self._max_sessions,
            "stats": self.get_stats().to_dict(),
        }


# =============================================================================
# Global Instance
# =============================================================================

_analytics: SessionAnalytics | None = None
_analytics_lock = threading.Lock()


def get_session_analytics() -> SessionAnalytics:
    """Get or create the global session analytics."""
    global _analytics
    if _analytics is None:
        with _analytics_lock:
            if _analytics is None:
                _analytics = SessionAnalytics()
    return _analytics


def reset_session_analytics() -> None:
    """Reset the global session analytics (for testing)."""
    global _analytics
    _analytics = None
