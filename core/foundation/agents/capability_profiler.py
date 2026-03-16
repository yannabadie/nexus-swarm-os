"""
Capability Profiler - Fine-grained agent capability tracking and matching.

V12.4 COGNITIVE BOOST - Task #42

Extends the basic AgentCapability enum with:
- Detailed capability descriptors with proficiency levels
- Task-capability matching for intelligent routing
- Performance learning from task outcomes
- Historical proficiency tracking with decay

The existing UnifiedAgentRegistry has 5 coarse capabilities (CODING, RESEARCH,
CREATIVE, ANALYSIS, GENERAL) and DyLAN scores. This profiler adds a richer
layer that tracks fine-grained skills, learns from outcomes, and provides
best-match agent selection for specific task requirements.

Usage:
    from core.foundation.agents.capability_profiler import CapabilityProfiler

    profiler = CapabilityProfiler()
    profiler.register_agent("gemini", capabilities=["research", "web_search", "summarization"])
    profiler.register_agent("claude", capabilities=["coding", "debugging", "architecture"])

    # Record outcomes
    profiler.record_outcome("claude", "coding", success=True, quality=0.95)

    # Find best agent for a set of required capabilities
    match = profiler.best_match(required=["coding", "debugging"])
    print(match.agent_id)  # "claude"
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

# Default proficiency for newly registered capabilities
DEFAULT_PROFICIENCY = 0.5

# Learning rate for exponential moving average
LEARNING_RATE = 0.2

# Decay rate per hour of inactivity (proficiency drifts toward 0.5)
DECAY_RATE_PER_HOUR = 0.01

# Minimum observations before proficiency is considered reliable
MIN_OBSERVATIONS = 3

# Known fine-grained capabilities (superset of AgentCapability enum)
KNOWN_CAPABILITIES: dict[str, str] = {
    # Coding
    "coding": "General code writing",
    "debugging": "Bug diagnosis and fixing",
    "architecture": "System design and architecture",
    "refactoring": "Code restructuring and cleanup",
    "testing": "Test writing and validation",
    "code_review": "Code review and quality checks",
    # Research
    "research": "General research and information gathering",
    "web_search": "Web search and source evaluation",
    "summarization": "Text summarization and distillation",
    "fact_checking": "Fact verification and source validation",
    # Analysis
    "analysis": "General data and problem analysis",
    "security_analysis": "Security audit and vulnerability analysis",
    "performance_analysis": "Performance profiling and optimization",
    "log_analysis": "Log parsing and error diagnosis",
    # Creative
    "creative": "Creative writing and ideation",
    "prompt_engineering": "Prompt design and optimization",
    "documentation": "Documentation writing",
    "naming": "Variable/function/project naming",
    # Collaboration
    "brainstorming": "Collaborative ideation",
    "planning": "Task planning and decomposition",
    "negotiation": "Swarm mode negotiation",
    # General
    "general": "General-purpose tasks",
    "tool_use": "Tool invocation and orchestration",
    "math": "Mathematical computation",
    "translation": "Language translation",
}


# =============================================================================
# Types
# =============================================================================


@dataclass
class CapabilityRecord:
    """Proficiency record for one agent-capability pair."""

    capability: str
    proficiency: float = DEFAULT_PROFICIENCY
    observations: int = 0
    successes: int = 0
    total_quality: float = 0.0
    last_used: float = 0.0  # monotonic time
    last_updated: float = 0.0  # monotonic time

    @property
    def success_rate(self) -> float:
        if self.observations == 0:
            return 0.0
        return self.successes / self.observations

    @property
    def average_quality(self) -> float:
        if self.observations == 0:
            return 0.0
        return self.total_quality / self.observations

    @property
    def is_reliable(self) -> bool:
        """Whether we have enough data to trust the proficiency."""
        return self.observations >= MIN_OBSERVATIONS

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "proficiency": round(self.proficiency, 4),
            "observations": self.observations,
            "success_rate": round(self.success_rate, 4),
            "average_quality": round(self.average_quality, 4),
            "is_reliable": self.is_reliable,
        }


@dataclass
class AgentProfile:
    """Complete capability profile for one agent."""

    agent_id: str
    capabilities: dict[str, CapabilityRecord] = field(default_factory=dict)
    total_tasks: int = 0
    total_successes: int = 0
    registered_at: float = field(default_factory=time.monotonic)

    @property
    def overall_success_rate(self) -> float:
        if self.total_tasks == 0:
            return 0.0
        return self.total_successes / self.total_tasks

    @property
    def capability_names(self) -> list[str]:
        return sorted(self.capabilities.keys())

    def get_proficiency(self, capability: str) -> float:
        """Get proficiency for a capability (0.0 if not registered)."""
        rec = self.capabilities.get(capability)
        return rec.proficiency if rec else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "total_tasks": self.total_tasks,
            "overall_success_rate": round(self.overall_success_rate, 4),
            "capabilities": {name: rec.to_dict() for name, rec in sorted(self.capabilities.items())},
        }


@dataclass
class MatchResult:
    """Result of matching required capabilities to an agent."""

    agent_id: str
    score: float  # 0.0 to 1.0
    matched_capabilities: list[str]
    missing_capabilities: list[str]
    proficiency_details: dict[str, float]

    @property
    def is_full_match(self) -> bool:
        return len(self.missing_capabilities) == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "score": round(self.score, 4),
            "is_full_match": self.is_full_match,
            "matched": self.matched_capabilities,
            "missing": self.missing_capabilities,
            "proficiency": {k: round(v, 4) for k, v in self.proficiency_details.items()},
        }


# =============================================================================
# Capability Profiler
# =============================================================================


class CapabilityProfiler:
    """
    Tracks fine-grained capabilities per agent with proficiency learning.

    Extends the basic AgentCapability enum with:
    - Arbitrary string capabilities (not limited to 5 enum values)
    - Per-agent proficiency levels (0.0-1.0) that learn from outcomes
    - Task-capability matching with composite scoring
    - Proficiency decay for inactive capabilities
    """

    def __init__(
        self,
        *,
        learning_rate: float = LEARNING_RATE,
        decay_rate_per_hour: float = DECAY_RATE_PER_HOUR,
        min_observations: int = MIN_OBSERVATIONS,
    ):
        self._profiles: dict[str, AgentProfile] = {}
        self._learning_rate = learning_rate
        self._decay_rate = decay_rate_per_hour
        self._min_observations = min_observations

    # =========================================================================
    # Registration
    # =========================================================================

    def register_agent(
        self,
        agent_id: str,
        *,
        capabilities: list[str] | None = None,
        initial_proficiency: dict[str, float] | None = None,
    ) -> AgentProfile:
        """
        Register an agent with its capabilities.

        Args:
            agent_id: Unique agent identifier
            capabilities: List of capability names
            initial_proficiency: Optional map of capability -> initial proficiency

        Returns:
            The created AgentProfile
        """
        now = time.monotonic()
        profile = AgentProfile(agent_id=agent_id, registered_at=now)

        caps = capabilities or []
        profs = initial_proficiency or {}

        for cap in caps:
            prof = profs.get(cap, DEFAULT_PROFICIENCY)
            profile.capabilities[cap] = CapabilityRecord(
                capability=cap,
                proficiency=prof,
                last_updated=now,
            )

        self._profiles[agent_id] = profile
        return profile

    def add_capability(
        self,
        agent_id: str,
        capability: str,
        proficiency: float = DEFAULT_PROFICIENCY,
    ) -> bool:
        """
        Add a capability to an existing agent.

        Returns:
            True if added, False if agent not found
        """
        profile = self._profiles.get(agent_id)
        if profile is None:
            return False

        now = time.monotonic()
        profile.capabilities[capability] = CapabilityRecord(
            capability=capability,
            proficiency=max(0.0, min(1.0, proficiency)),
            last_updated=now,
        )
        return True

    def remove_capability(self, agent_id: str, capability: str) -> bool:
        """
        Remove a capability from an agent.

        Returns:
            True if removed, False if agent or capability not found
        """
        profile = self._profiles.get(agent_id)
        if profile is None:
            return False
        if capability not in profile.capabilities:
            return False
        del profile.capabilities[capability]
        return True

    # =========================================================================
    # Outcome Recording & Learning
    # =========================================================================

    def record_outcome(
        self,
        agent_id: str,
        capability: str,
        *,
        success: bool,
        quality: float = 0.0,
    ) -> bool:
        """
        Record a task outcome to update proficiency.

        Uses exponential moving average:
            new_proficiency = (1 - lr) * old + lr * outcome

        Args:
            agent_id: Agent that performed the task
            capability: Capability used
            success: Whether the task succeeded
            quality: Quality score (0.0-1.0), used if success=True

        Returns:
            True if recorded, False if agent not found
        """
        profile = self._profiles.get(agent_id)
        if profile is None:
            return False

        now = time.monotonic()

        # Auto-create capability record if not exists
        if capability not in profile.capabilities:
            profile.capabilities[capability] = CapabilityRecord(
                capability=capability,
                proficiency=DEFAULT_PROFICIENCY,
                last_updated=now,
            )

        rec = profile.capabilities[capability]
        rec.observations += 1
        rec.last_used = now

        if success:
            rec.successes += 1
            outcome = max(0.0, min(1.0, quality)) if quality > 0 else 0.7
        else:
            outcome = 0.0

        rec.total_quality += outcome

        # Exponential moving average update
        lr = self._learning_rate
        rec.proficiency = (1 - lr) * rec.proficiency + lr * outcome
        rec.proficiency = max(0.0, min(1.0, rec.proficiency))
        rec.last_updated = now

        # Update agent-level stats
        profile.total_tasks += 1
        if success:
            profile.total_successes += 1

        return True

    def apply_decay(self, agent_id: str | None = None) -> int:
        """
        Apply proficiency decay for inactive capabilities.

        Proficiency drifts toward DEFAULT_PROFICIENCY over time.

        Args:
            agent_id: Specific agent, or None for all agents

        Returns:
            Number of capabilities decayed
        """
        now = time.monotonic()
        decayed = 0

        profiles = [self._profiles[agent_id]] if agent_id and agent_id in self._profiles else self._profiles.values()

        for profile in profiles:
            for rec in profile.capabilities.values():
                if rec.last_updated == 0:
                    continue
                hours = (now - rec.last_updated) / 3600.0
                if hours < 1.0:
                    continue

                decay = self._decay_rate * hours
                if rec.proficiency > DEFAULT_PROFICIENCY:
                    rec.proficiency = max(
                        DEFAULT_PROFICIENCY,
                        rec.proficiency - decay,
                    )
                    decayed += 1
                elif rec.proficiency < DEFAULT_PROFICIENCY:
                    rec.proficiency = min(
                        DEFAULT_PROFICIENCY,
                        rec.proficiency + decay,
                    )
                    decayed += 1
                rec.last_updated = now

        return decayed

    # =========================================================================
    # Matching & Selection
    # =========================================================================

    def best_match(
        self,
        required: list[str],
        *,
        preferred: list[str] | None = None,
        exclude: list[str] | None = None,
    ) -> MatchResult | None:
        """
        Find the best agent for a set of required capabilities.

        Scoring:
        - Required capabilities: weighted by proficiency (missing = 0)
        - Preferred capabilities: bonus (weighted at 0.5x)

        Args:
            required: Must-have capabilities
            preferred: Nice-to-have capabilities
            exclude: Agent IDs to exclude

        Returns:
            Best MatchResult, or None if no agents registered
        """
        candidates = self._match_all(
            required=required,
            preferred=preferred,
            exclude=exclude,
        )
        if not candidates:
            return None
        return candidates[0]

    def match_all(
        self,
        required: list[str],
        *,
        preferred: list[str] | None = None,
        exclude: list[str] | None = None,
    ) -> list[MatchResult]:
        """
        Rank all agents for a set of required capabilities.

        Returns:
            List of MatchResults sorted by score (descending)
        """
        return self._match_all(
            required=required,
            preferred=preferred,
            exclude=exclude,
        )

    def _match_all(
        self,
        required: list[str],
        preferred: list[str] | None = None,
        exclude: list[str] | None = None,
    ) -> list[MatchResult]:
        exclude_set = set(exclude or [])
        preferred_caps = preferred or []
        results = []

        for agent_id, profile in self._profiles.items():
            if agent_id in exclude_set:
                continue

            matched = []
            missing = []
            proficiency_details = {}
            score_sum = 0.0

            # Score required capabilities
            for cap in required:
                rec = profile.capabilities.get(cap)
                if rec:
                    matched.append(cap)
                    proficiency_details[cap] = rec.proficiency
                    score_sum += rec.proficiency
                else:
                    missing.append(cap)
                    proficiency_details[cap] = 0.0

            # Bonus for preferred capabilities (half weight)
            preferred_bonus = 0.0
            for cap in preferred_caps:
                rec = profile.capabilities.get(cap)
                if rec:
                    preferred_bonus += rec.proficiency * 0.5

            # Composite score
            total_weight = len(required) + len(preferred_caps) * 0.5
            if total_weight > 0:
                score = (score_sum + preferred_bonus) / total_weight
            else:
                score = 0.0

            results.append(
                MatchResult(
                    agent_id=agent_id,
                    score=score,
                    matched_capabilities=matched,
                    missing_capabilities=missing,
                    proficiency_details=proficiency_details,
                )
            )

        results.sort(key=lambda r: r.score, reverse=True)
        return results

    # =========================================================================
    # Queries
    # =========================================================================

    def get_profile(self, agent_id: str) -> AgentProfile | None:
        """Get profile for an agent."""
        return self._profiles.get(agent_id)

    def get_proficiency(self, agent_id: str, capability: str) -> float:
        """Get proficiency for a specific agent-capability pair."""
        profile = self._profiles.get(agent_id)
        if profile is None:
            return 0.0
        return profile.get_proficiency(capability)

    def list_agents(self) -> list[str]:
        """List all registered agent IDs."""
        return sorted(self._profiles.keys())

    def list_capabilities(self, agent_id: str) -> list[str]:
        """List capabilities for an agent."""
        profile = self._profiles.get(agent_id)
        if profile is None:
            return []
        return profile.capability_names

    def agents_with_capability(self, capability: str) -> list[str]:
        """Find all agents that have a specific capability."""
        return sorted(agent_id for agent_id, profile in self._profiles.items() if capability in profile.capabilities)

    def top_agents(
        self,
        capability: str,
        *,
        limit: int = 5,
    ) -> list[tuple]:
        """
        Get top agents for a capability, ranked by proficiency.

        Returns:
            List of (agent_id, proficiency) tuples
        """
        agents = []
        for agent_id, profile in self._profiles.items():
            rec = profile.capabilities.get(capability)
            if rec:
                agents.append((agent_id, rec.proficiency))
        agents.sort(key=lambda x: x[1], reverse=True)
        return agents[:limit]

    # =========================================================================
    # State Management
    # =========================================================================

    def clear(self) -> None:
        """Clear all profiles."""
        self._profiles.clear()

    def remove_agent(self, agent_id: str) -> bool:
        """Remove an agent profile."""
        if agent_id in self._profiles:
            del self._profiles[agent_id]
            return True
        return False

    @property
    def agent_count(self) -> int:
        return len(self._profiles)

    def to_dict(self) -> dict[str, Any]:
        """Export profiler state."""
        return {
            "agent_count": self.agent_count,
            "learning_rate": self._learning_rate,
            "decay_rate_per_hour": self._decay_rate,
            "profiles": {agent_id: profile.to_dict() for agent_id, profile in sorted(self._profiles.items())},
        }


# =============================================================================
# Singleton
# =============================================================================

_profiler: CapabilityProfiler | None = None
_profiler_lock = threading.Lock()


def get_capability_profiler() -> CapabilityProfiler:
    """Get or create the global CapabilityProfiler."""
    global _profiler
    if _profiler is None:
        with _profiler_lock:
            if _profiler is None:
                _profiler = CapabilityProfiler()
    return _profiler


def reset_capability_profiler() -> None:
    """Reset the global CapabilityProfiler."""
    global _profiler
    _profiler = None
