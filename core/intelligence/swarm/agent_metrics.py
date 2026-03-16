"""
Agent Metrics - DyLAN-inspired Performance Tracking

Implements importance scoring for intelligent agent selection.
Designed to scale from 2 agents (V7) to N agents (Phase 6 Swarm).

DyLAN Formula: importance_score = quality / cost
- quality: Task success rate and output quality (0.0-1.0)
- cost: tokens_used / 1000 + time_seconds

Usage:
    from core.intelligence.swarm import AgentPool, AgentProfile, AgentInvocationResult

    pool = AgentPool()
    pool.register(AgentProfile(
        agent_id="claude_opus",
        provider="claude",
        model="claude-opus-4-6-20250116"
    ))

    # After invocation, record result
    result = AgentInvocationResult(
        agent_id="claude_opus",
        task_type="brainstorm",
        success=True,
        quality_score=0.85,
        tokens_used=1500,
        time_seconds=12.5
    )
    pool.agents["claude_opus"].record_invocation(result)

    # Select best agent for task
    best = pool.select_best_for_task("brainstorm")
"""

import contextlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.memory_pkg.memory import SuccessMemory


class AgentProvider(Enum):
    """Agent providers - extensible for future integrations"""

    GEMINI = "gemini"
    CLAUDE = "claude"
    # Future: OPENAI = "openai", LOCAL = "local"


@dataclass
class AgentInvocationResult:
    """
    Metrics for a single agent invocation.

    Used to calculate DyLAN importance score for agent selection.
    """

    agent_id: str
    task_type: str
    timestamp: datetime = field(default_factory=datetime.now)
    success: bool = True
    quality_score: float = 0.5  # 0.0-1.0
    tokens_used: int = 0
    time_seconds: float = 0.0
    error: str | None = None

    @property
    def importance_score(self) -> float:
        """
        DyLAN-style importance: quality / cost

        Higher is better. Rewards quality while penalizing resource usage.
        """
        if not self.success:
            return 0.0
        cost = (self.tokens_used / 1000) + self.time_seconds
        return self.quality_score / max(cost, 0.1)

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "task_type": self.task_type,
            "timestamp": self.timestamp.isoformat(),
            "success": self.success,
            "quality_score": self.quality_score,
            "tokens_used": self.tokens_used,
            "time_seconds": self.time_seconds,
            "importance_score": round(self.importance_score, 4),
            "error": self.error,
        }


@dataclass
class AgentProfile:
    """
    Profile for a single agent with performance history.

    Tracks invocation history for importance scoring.
    Scales to N agents in Phase 6 Swarm.
    """

    agent_id: str
    provider: str  # "gemini", "claude", "spawned"
    model: str
    capabilities: list[str] = field(default_factory=list)
    is_active: bool = True
    uuid: str | None = None  # V8.2.0: Unique identifier for spawned agents
    invocation_history: list[AgentInvocationResult] = field(default_factory=list)
    history_window: int = 100  # Keep last N invocations

    @property
    def average_importance(self) -> float:
        """Average importance score across all invocations"""
        if not self.invocation_history:
            return 0.5  # Neutral score for new agents
        scores = [r.importance_score for r in self.invocation_history]
        return sum(scores) / len(scores)

    @property
    def success_rate(self) -> float:
        """Success rate across invocations"""
        if not self.invocation_history:
            return 1.0
        successes = sum(1 for r in self.invocation_history if r.success)
        return successes / len(self.invocation_history)

    def get_task_importance(self, task_type: str) -> float:
        """Get importance score for specific task type"""
        relevant = [r for r in self.invocation_history if r.task_type == task_type]
        if not relevant:
            return self.average_importance
        return sum(r.importance_score for r in relevant) / len(relevant)

    def record_invocation(self, result: AgentInvocationResult):
        """Record an invocation result, maintaining window size"""
        self.invocation_history.append(result)
        # Trim to window size
        if len(self.invocation_history) > self.history_window:
            self.invocation_history = self.invocation_history[-self.history_window :]

    def to_dict(self, include_history: bool = False) -> dict:
        """
        Convert to dictionary.

        Args:
            include_history: If True, include full invocation history (for persistence)
        """
        result = {
            "agent_id": self.agent_id,
            "provider": self.provider,
            "model": self.model,
            "capabilities": self.capabilities,
            "is_active": self.is_active,
            "uuid": self.uuid,  # V8.2.0
            "average_importance": round(self.average_importance, 4),
            "success_rate": round(self.success_rate, 4),
            "invocation_count": len(self.invocation_history),
        }
        if include_history:
            result["invocation_history"] = [r.to_dict() for r in self.invocation_history]
        return result


@dataclass
class AgentPool:
    """
    Pool of agents for multi-agent coordination.

    Foundation for Phase 6 Hybrid Swarm:
    - V7: 2 fixed agents (Gemini + Claude)
    - Phase 6: Dynamic N agents with spawning

    Selection uses DyLAN importance scoring.

    V7 Enhancement: Auto-persistence of DyLAN scores.
    """

    agents: dict[str, AgentProfile] = field(default_factory=dict)
    _persistence_path: str | None = field(default=None, repr=False)
    _auto_save: bool = field(default=False, repr=False)
    _save_counter: int = field(default=0, repr=False)
    _save_interval: int = field(default=5, repr=False)  # Save every N invocations

    def enable_persistence(self, path: str, auto_save: bool = True, save_interval: int = 5):
        """
        Enable auto-persistence of DyLAN scores.

        Args:
            path: File path for persistence (JSON)
            auto_save: Whether to auto-save after invocations
            save_interval: Save every N invocations (default 5)
        """
        self._persistence_path = path
        self._auto_save = auto_save
        self._save_interval = save_interval

        # Try to load existing data
        with contextlib.suppress(FileNotFoundError, json.JSONDecodeError):
            self._load_history_from_file(path)

    def register(self, profile: AgentProfile):
        """Register an agent in the pool"""
        self.agents[profile.agent_id] = profile

    def unregister(self, agent_id: str):
        """Remove an agent from the pool"""
        if agent_id in self.agents:
            del self.agents[agent_id]

    def get_active_agents(self) -> list[AgentProfile]:
        """Get all active agents"""
        return [a for a in self.agents.values() if a.is_active]

    def get_spawned_agents(self) -> list[AgentProfile]:
        """
        Get all spawned agents (provider == 'spawned').

        V7.5 HIVE MIND: Spawned agents are created via /spawn command
        and stored in workspace/agents/.

        Returns:
            List of AgentProfile for spawned agents only
        """
        return [a for a in self.agents.values() if a.is_active and a.provider == "spawned"]

    def get_internal_agents(self) -> list[AgentProfile]:
        """
        Get internal agents (Gemini + Claude).

        Returns:
            List of AgentProfile for internal agents only
        """
        return [a for a in self.agents.values() if a.is_active and a.provider in ("gemini", "claude")]

    def select_best_for_task(self, task_type: str, top_k: int = 1, min_importance: float = 0.0) -> list[AgentProfile]:
        """
        Select best agent(s) for a task using importance scoring.

        Args:
            task_type: Type of task (brainstorm, validation, etc.)
            top_k: Number of agents to return (1 for V7, N for Phase 6)
            min_importance: Minimum importance threshold

        Returns:
            List of top-k agents sorted by task-specific importance
        """
        active = self.get_active_agents()
        if not active:
            return []

        # Score by task-specific importance
        scored = [(agent, agent.get_task_importance(task_type)) for agent in active]

        # Filter by minimum threshold
        scored = [(a, s) for a, s in scored if s >= min_importance]

        # Sort by score descending
        scored.sort(key=lambda x: x[1], reverse=True)

        return [agent for agent, _ in scored[:top_k]]

    def select_agents_by_capability(
        self, domain: str, count: int = 1, include_spawned: bool = True
    ) -> list[AgentProfile]:
        """
        Select top agents by capability/DyLAN score for a domain.

        V7.5 Phase 5b: N-Agent Agnosticism - selects agents based on
        capability matching and performance history, not hardcoded names.

        Selection priority:
        1. Agents with explicit capability matching the domain
        2. Agents with high DyLAN importance score for the domain
        3. Agents with general high performance

        Args:
            domain: Task domain (e.g., "CODING", "RESEARCH", "DATABASE")
            count: Number of agents to return
            include_spawned: Whether to include spawned agents (default True)

        Returns:
            List of top agents sorted by domain fitness
        """
        active = self.get_active_agents()
        if not active:
            return []

        # Filter by spawned preference
        if not include_spawned:
            active = [a for a in active if a.provider != "spawned"]

        domain_lower = domain.lower()
        scored: list[tuple] = []

        for agent in active:
            score = 0.0

            # 1. Direct capability match (highest weight)
            capabilities_lower = [c.lower() for c in agent.capabilities]
            if domain_lower in capabilities_lower:
                score += 1.0  # Full bonus for direct match
            elif any(domain_lower in cap for cap in capabilities_lower):
                score += 0.7  # Partial bonus for substring match

            # 2. DyLAN importance score (0.0-1.0 typically, scaled)
            dylan_score = agent.get_task_importance(domain_lower)
            score += dylan_score * 0.5  # Weight DyLAN contribution

            # 3. Overall success rate as tiebreaker
            score += agent.success_rate * 0.1

            scored.append((agent, score))

        # Sort by score descending
        scored.sort(key=lambda x: x[1], reverse=True)

        return [agent for agent, _ in scored[:count]]

    def get_best_for_role(self, role: str, domain: str, exclude_agents: list[str] | None = None) -> AgentProfile | None:
        """
        Get the best single agent for a specific role in a domain.

        V7.5 Phase 5b: Helper for ModeSelector agent assignment.

        Args:
            role: Role name (for logging, not used in selection)
            domain: Task domain to match against
            exclude_agents: Agent IDs to exclude (already assigned)

        Returns:
            Best matching AgentProfile or None
        """
        exclude = set(exclude_agents or [])
        candidates = self.select_agents_by_capability(domain, count=10)

        for agent in candidates:
            if agent.agent_id not in exclude:
                return agent

        return None

    def record_invocation(self, result: AgentInvocationResult):
        """Record invocation result to appropriate agent with auto-persistence"""
        if result.agent_id in self.agents:
            self.agents[result.agent_id].record_invocation(result)

            # Auto-save if enabled (every N invocations to avoid I/O overhead)
            if self._auto_save and self._persistence_path:
                self._save_counter += 1
                if self._save_counter >= self._save_interval:
                    self._save_counter = 0
                    with contextlib.suppress(Exception):
                        self.save_to_file(self._persistence_path)

    # =========================================================================
    # Phase 10d: Session-Aware Agent Selection
    # =========================================================================

    # Session bonus constants (configurable)
    SESSION_BONUS_HIGH = 0.08  # High quality session (>0.8)
    SESSION_BONUS_MEDIUM = 0.05  # Medium quality session (>0.6)
    SESSION_BONUS_LOW = 0.02  # Low quality session (>0.4)
    SESSION_MIN_QUALITY = 0.4  # Minimum quality to apply any bonus

    def update_from_session_metrics(
        self, task_id: str, agents_used: list, quality_score: float, domains: list, task_type: str = "session"
    ) -> dict[str, float]:
        """
        Update agent scores based on completed session metrics.

        Phase 10d: Session-Aware Agent Selection.

        Rewards agents that participated in successful sessions with a bonus
        to their DyLAN importance score. This creates a feedback loop where
        agents performing well in complete tasks are favored.

        Args:
            task_id: Unique task identifier.
            agents_used: List of agent IDs that participated.
            quality_score: Session quality score (0.0-1.0).
            domains: List of task domains (for domain-specific boost).
            task_type: Task type for categorization.

        Returns:
            Dictionary mapping agent_id to bonus applied.
        """
        bonuses_applied: dict[str, float] = {}

        # Skip if quality too low
        if quality_score < self.SESSION_MIN_QUALITY:
            return bonuses_applied

        # Calculate bonus based on quality tier
        if quality_score > 0.8:
            bonus = self.SESSION_BONUS_HIGH
        elif quality_score > 0.6:
            bonus = self.SESSION_BONUS_MEDIUM
        else:
            bonus = self.SESSION_BONUS_LOW

        # Apply bonus to each participating agent
        for agent_id in agents_used:
            if agent_id not in self.agents:
                continue

            agent = self.agents[agent_id]

            # Create a synthetic invocation result to boost the score
            # This gives agents credit for successful session participation
            synthetic_result = AgentInvocationResult(
                agent_id=agent_id,
                task_type=task_type,
                success=True,
                quality_score=min(1.0, 0.5 + bonus),  # Base + bonus
                tokens_used=0,  # No actual token usage
                time_seconds=0.1,  # Minimal time for good importance score
            )

            agent.record_invocation(synthetic_result)
            bonuses_applied[agent_id] = bonus

            # Also record for primary domain if specified
            if domains:
                domain_result = AgentInvocationResult(
                    agent_id=agent_id,
                    task_type=domains[0].lower(),  # Use primary domain
                    success=True,
                    quality_score=min(1.0, 0.5 + bonus),
                    tokens_used=0,
                    time_seconds=0.1,
                )
                agent.record_invocation(domain_result)

        return bonuses_applied

    def get_session_aware_score(
        self, agent_id: str, task_type: str, success_memory: "SuccessMemory" = None, dylan_weight: float = 0.7
    ) -> float:
        """
        Get combined score using DyLAN and session success rate.

        Phase 10d: Hybrid scoring formula.

        Formula: Score = (DyLAN_score * dylan_weight) + (Session_rate * (1-dylan_weight))

        Args:
            agent_id: Agent identifier.
            task_type: Task type / domain for scoring.
            success_memory: SuccessMemory instance for session metrics.
            dylan_weight: Weight for DyLAN score (default 0.7 = 70%).

        Returns:
            Combined score between 0.0 and 1.0.
        """
        if agent_id not in self.agents:
            return 0.5  # Neutral for unknown agents

        agent = self.agents[agent_id]

        # Get DyLAN importance score
        dylan_score = agent.get_task_importance(task_type)

        # Get session success rate if available
        session_rate = 0.5  # Neutral default
        if success_memory:
            session_rate, sample_count = success_memory.get_agent_success_rate(agent_id, domain=task_type)
            # If not enough samples for domain, try global
            if sample_count < 3:
                session_rate, _ = success_memory.get_agent_success_rate(agent_id)

        # Combined formula
        combined = (dylan_score * dylan_weight) + (session_rate * (1 - dylan_weight))

        return min(1.0, max(0.0, combined))

    def get_pool_stats(self) -> dict:
        """Get aggregate statistics for the pool"""
        active = self.get_active_agents()
        if not active:
            return {"agents": 0, "total_invocations": 0}

        total_invocations = sum(len(a.invocation_history) for a in active)
        avg_importance = sum(a.average_importance for a in active) / len(active)

        return {
            "agents": len(active),
            "total_invocations": total_invocations,
            "average_pool_importance": round(avg_importance, 4),
            "agents_detail": {a.agent_id: a.to_dict() for a in active},
        }

    def to_dict(self, include_history: bool = False) -> dict:
        """Convert to dictionary, optionally with full history for persistence."""
        return {
            "agents": {
                agent_id: profile.to_dict(include_history=include_history) for agent_id, profile in self.agents.items()
            },
            "stats": self.get_pool_stats(),
        }

    def save_to_file(self, path: str):
        """Persist pool state with full history to JSON file"""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(include_history=True), f, indent=2)

    def _load_history_from_file(self, path: str):
        """
        Load invocation history from file into existing agents.

        Only loads history for agents that already exist in the pool.
        This preserves the current agent configuration while restoring DyLAN scores.
        """
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        for agent_id, agent_data in data.get("agents", {}).items():
            if agent_id in self.agents:
                # Load history into existing agent
                history_data = agent_data.get("invocation_history", [])
                for inv_data in history_data:
                    # Reconstruct AgentInvocationResult
                    result = AgentInvocationResult(
                        agent_id=inv_data.get("agent_id", agent_id),
                        task_type=inv_data.get("task_type", "unknown"),
                        success=inv_data.get("success", True),
                        quality_score=inv_data.get("quality_score", 0.5),
                        tokens_used=inv_data.get("tokens_used", 0),
                        time_seconds=inv_data.get("time_seconds", 0.0),
                        error=inv_data.get("error"),
                    )
                    self.agents[agent_id].invocation_history.append(result)

    @classmethod
    def load_from_file(cls, path: str) -> "AgentPool":
        """Load pool state from JSON file"""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        pool = cls()
        for _agent_id, agent_data in data.get("agents", {}).items():
            profile = AgentProfile(
                agent_id=agent_data["agent_id"],
                provider=agent_data["provider"],
                model=agent_data["model"],
                capabilities=agent_data.get("capabilities", []),
                is_active=agent_data.get("is_active", True),
            )
            pool.register(profile)

        return pool


def create_default_pool(config=None) -> AgentPool:
    """
    Create default 2-agent pool for V7.

    Args:
        config: Optional config with model names

    Returns:
        AgentPool with Gemini and Claude profiles
    """
    pool = AgentPool()

    # Gemini agent
    gemini_model = "gemini-3-pro-preview"
    if config:
        gemini_model = getattr(config, "gemini_default_model", gemini_model)

    pool.register(
        AgentProfile(
            agent_id="gemini_primary",
            provider="gemini",
            model=gemini_model,
            capabilities=["reasoning", "coding", "research"],
        )
    )

    # Claude agent
    claude_model = "claude-opus-4-6-20250116"
    if config:
        claude_model = getattr(config, "claude_opus_model", claude_model)

    pool.register(
        AgentProfile(
            agent_id="claude_opus",
            provider="claude",
            model=claude_model,
            capabilities=["brainstorm", "creativity", "architecture"],
        )
    )

    return pool
