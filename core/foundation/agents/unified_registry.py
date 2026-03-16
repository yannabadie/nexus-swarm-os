"""
UnifiedAgentRegistry - Centralized Agent Management for NEXUS V8.4.0

This module unifies several existing agent-related components:
- AgentRegistry (hive_mind/) - Anti-duplication for spawns
- AgentPool (swarm/) - DyLAN scoring + metrics
- SpawnedAgentLoader (bootstrap/) - Discovery from workspace/agents/
- AgentInvoker (orchestration/) - Routing task -> driver

Replaces 41+ hardcoded if/else chains like:
    if "gemini" in agent_id.lower()
    if agent == "Claude"

With O(1) lookups:
    registry.get(agent_id)
    registry.is_gemini(agent_id)
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


class AgentProvider(Enum):
    """Supported agent providers - all 7 backends + spawned"""

    GEMINI = "gemini"
    CLAUDE = "claude"
    OPENAI = "openai"
    DEEPSEEK = "deepseek"
    KIMI = "kimi"
    MINIMAX = "minimax"
    OLLAMA = "ollama"
    SPAWNED = "spawned"  # Custom agents from workspace/agents/


class AgentCapability(Enum):
    """Agent capability domains for intelligent routing"""

    CODING = "coding"
    RESEARCH = "research"
    CREATIVE = "creative"
    ANALYSIS = "analysis"
    GENERAL = "general"


@dataclass
class AgentDescriptor:
    """
    Complete metadata for an agent.

    Attributes:
        id: Unique lowercase identifier (e.g., "gemini", "claude", "security_expert")
        provider: Which provider backs this agent
        display_name: Human-readable name for UI (e.g., "Gemini", "Claude")
        capabilities: List of domains this agent excels at
        dylan_scores: DyLAN performance scores per capability
        config_path: Path to config file (for spawned agents)
        is_available: Whether agent is currently usable
    """

    id: str
    provider: AgentProvider
    display_name: str
    capabilities: list[AgentCapability] = field(default_factory=list)
    dylan_scores: dict[str, float] = field(default_factory=dict)
    config_path: Path | None = None
    is_available: bool = True

    @property
    def is_builtin(self) -> bool:
        """Check if this is a builtin agent (Gemini or Claude)"""
        return self.provider in (AgentProvider.GEMINI, AgentProvider.CLAUDE)


@runtime_checkable
class DriverProtocol(Protocol):
    """Protocol that agent drivers must implement"""

    async def invoke(self, prompt: str, **kwargs: Any) -> str:
        """Invoke the agent with a prompt and return response"""
        ...


class UnifiedAgentRegistry:
    """
    Centralized registry for all agents in NEXUS.

    Replaces hardcoded if/else chains with O(1) dictionary lookups.
    Supports builtins (Gemini, Claude), spawned agents, and future Ollama.

    Usage:
        registry = get_registry()

        # Get agent info
        agent = registry.get("gemini")
        name = registry.get_display_name("gemini")  # "Gemini"

        # Check provider
        if registry.is_gemini(agent_id):
            ...

        # Get driver
        driver = registry.get_driver(agent_id)
        await driver.invoke(prompt)

        # Alternation (for BRAINSTORMING mode)
        next_agent = registry.get_alternate("gemini")  # "claude"
    """

    def __init__(self) -> None:
        self._agents: dict[str, AgentDescriptor] = {}
        self._drivers: dict[str, DriverProtocol] = {}
        self._aliases: dict[str, str] = {}  # "Gemini" -> "gemini"
        self._builtin_ids: list[str] = []  # Tracks registration order for round-robin
        self._register_builtins()

    def _register_builtins(self) -> None:
        """Register Gemini and Claude as builtin agents"""
        self.register(
            AgentDescriptor(
                id="gemini",
                provider=AgentProvider.GEMINI,
                display_name="Gemini",
                capabilities=[AgentCapability.RESEARCH, AgentCapability.ANALYSIS, AgentCapability.GENERAL],
            )
        )
        self.register(
            AgentDescriptor(
                id="claude",
                provider=AgentProvider.CLAUDE,
                display_name="Claude",
                capabilities=[AgentCapability.CODING, AgentCapability.CREATIVE, AgentCapability.GENERAL],
            )
        )
        # Register common aliases for case-insensitive lookup
        self._aliases["Gemini"] = "gemini"
        self._aliases["Claude"] = "claude"
        self._aliases["GEMINI"] = "gemini"
        self._aliases["CLAUDE"] = "claude"

    def register(self, agent: AgentDescriptor) -> None:
        """
        Register an agent in the registry.

        Args:
            agent: AgentDescriptor with agent metadata
        """
        self._agents[agent.id] = agent
        self._aliases[agent.display_name] = agent.id

    def unregister(self, agent_id: str) -> bool:
        """
        Remove an agent from the registry.

        Args:
            agent_id: ID of agent to remove

        Returns:
            True if agent was removed, False if not found
        """
        normalized = self._normalize_id(agent_id)
        if normalized in self._agents:
            agent = self._agents.pop(normalized)
            # Remove alias
            if agent.display_name in self._aliases:
                del self._aliases[agent.display_name]
            # Remove driver if present
            if normalized in self._drivers:
                del self._drivers[normalized]
            return True
        return False

    def register_driver(self, agent_id: str, driver: DriverProtocol) -> None:
        """
        Associate a driver with an agent.

        Args:
            agent_id: ID of agent
            driver: Driver instance implementing DriverProtocol
        """
        normalized = self._normalize_id(agent_id)
        self._drivers[normalized] = driver
        if normalized not in self._builtin_ids:
            self._builtin_ids.append(normalized)

    def _normalize_id(self, agent_id: str) -> str:
        """Normalize agent ID to lowercase, resolving aliases"""
        if agent_id in self._aliases:
            return self._aliases[agent_id]
        return agent_id.lower()

    def get(self, agent_id: str) -> AgentDescriptor | None:
        """
        Get agent descriptor by ID or alias (O(1) lookup).

        Args:
            agent_id: Agent ID or alias (case-insensitive)

        Returns:
            AgentDescriptor or None if not found
        """
        normalized = self._normalize_id(agent_id)
        return self._agents.get(normalized)

    def get_driver(self, agent_id: str) -> DriverProtocol | None:
        """
        Get driver for an agent.

        Args:
            agent_id: Agent ID or alias

        Returns:
            Driver instance or None if not registered
        """
        normalized = self._normalize_id(agent_id)
        return self._drivers.get(normalized)

    def get_display_name(self, agent_id: str) -> str:
        """
        Get human-readable display name for an agent.

        Args:
            agent_id: Agent ID or alias

        Returns:
            Display name (e.g., "Gemini") or titlecased ID if not found
        """
        agent = self.get(agent_id)
        return agent.display_name if agent else agent_id.title()

    def get_active_builtin_ids(self) -> list[str]:
        """
        Return ordered list of all registered agent IDs that have drivers.

        The order matches driver registration order, enabling deterministic
        round-robin across N agents.

        Returns:
            List of agent IDs with registered drivers, in registration order
        """
        return [aid for aid in self._builtin_ids if aid in self._drivers]

    def get_next(self, current: str) -> str:
        """
        Get the next agent after `current` in round-robin order.

        For 2 agents: identical behavior to the legacy get_alternate().
        For 3+ agents: cycles through in registration order.
        For 1 agent: returns itself.
        Unknown agent: returns first registered agent.

        Args:
            current: Current agent ID or alias

        Returns:
            Next agent ID in round-robin order, or first registered
            agent if current is unknown. Returns empty string if no
            agents have drivers registered.
        """
        active = self.get_active_builtin_ids()
        if not active:
            return ""
        normalized = self._normalize_id(current)
        try:
            idx = active.index(normalized)
            return active[(idx + 1) % len(active)]
        except ValueError:
            # Unknown agent: return first registered
            return active[0]

    def get_alternate(self, agent_id: str) -> str | None:
        """
        Get the next agent for alternation (e.g., BRAINSTORMING mode).

        When 2+ drivers are registered, delegates to get_next() for N-agent
        round-robin support. Falls back to legacy gemini/claude swap when
        fewer than 2 drivers are registered (backward compatibility for
        cases where Claude driver is created dynamically).

        Args:
            agent_id: Current agent ID

        Returns:
            Next agent ID, or None if current agent is not in the
            active round-robin list (e.g., spawned agents without drivers)
        """
        normalized = self._normalize_id(agent_id)
        active = self.get_active_builtin_ids()
        if len(active) >= 2:
            # N-agent round-robin via get_next()
            if normalized not in active:
                return None
            return self.get_next(agent_id)
        # Legacy fallback: hardcoded swap when <2 drivers registered
        # This handles the common case where Claude driver is created
        # dynamically and not pre-registered
        if normalized == "gemini":
            return "claude"
        elif normalized == "claude":
            return "gemini"
        return None

    def is_gemini(self, agent_id: str) -> bool:
        """
        Check if agent is Gemini (replaces 'if "gemini" in').

        Args:
            agent_id: Agent ID or alias

        Returns:
            True if agent provider is GEMINI
        """
        agent = self.get(agent_id)
        return agent is not None and agent.provider == AgentProvider.GEMINI

    def is_claude(self, agent_id: str) -> bool:
        """
        Check if agent is Claude.

        Args:
            agent_id: Agent ID or alias

        Returns:
            True if agent provider is CLAUDE
        """
        agent = self.get(agent_id)
        return agent is not None and agent.provider == AgentProvider.CLAUDE

    def is_builtin(self, agent_id: str) -> bool:
        """
        Check if agent is a builtin (Gemini or Claude).

        Args:
            agent_id: Agent ID or alias

        Returns:
            True if agent is builtin
        """
        agent = self.get(agent_id)
        return agent is not None and agent.is_builtin

    def list_available(self) -> list[AgentDescriptor]:
        """
        List all available agents.

        Returns:
            List of available AgentDescriptors
        """
        return [a for a in self._agents.values() if a.is_available]

    def list_builtins(self) -> list[AgentDescriptor]:
        """
        List builtin agents only.

        Returns:
            List of builtin AgentDescriptors
        """
        return [a for a in self._agents.values() if a.is_builtin]

    def list_spawned(self) -> list[AgentDescriptor]:
        """
        List spawned agents only.

        Returns:
            List of spawned AgentDescriptors
        """
        return [a for a in self._agents.values() if a.provider == AgentProvider.SPAWNED]

    def select_for_capability(
        self, capability: AgentCapability, exclude: list[str] | None = None
    ) -> AgentDescriptor | None:
        """
        Select best agent for a capability using DyLAN scores.

        Args:
            capability: Desired capability
            exclude: Agent IDs to exclude from selection

        Returns:
            Best matching agent, or None if no match
        """
        exclude_set = set(exclude or [])
        candidates = [
            a
            for a in self._agents.values()
            if capability in a.capabilities and a.is_available and a.id not in exclude_set
        ]
        if not candidates:
            return None
        # Sort by DyLAN score for this capability (default 0.5)
        return max(candidates, key=lambda a: a.dylan_scores.get(capability.value, 0.5))

    def update_dylan_score(self, agent_id: str, capability: str, score: float) -> bool:
        """
        Update DyLAN score for an agent capability.

        Args:
            agent_id: Agent ID
            capability: Capability name
            score: New score (0.0 to 1.0)

        Returns:
            True if updated, False if agent not found
        """
        agent = self.get(agent_id)
        if agent:
            agent.dylan_scores[capability] = max(0.0, min(1.0, score))
            return True
        return False

    def __contains__(self, agent_id: str) -> bool:
        """Check if agent is registered"""
        return self.get(agent_id) is not None

    def __len__(self) -> int:
        """Return number of registered agents"""
        return len(self._agents)


# =============================================================================
# V10 PRISM: Multi-Tenant Registry Access
# =============================================================================
# The registry is now tenant-scoped via ServiceFactory.
# Legacy global singleton kept for backward compatibility.

import threading  # noqa: E402  # singleton setup after class definition

_registry: UnifiedAgentRegistry | None = None
_registry_lock = threading.Lock()


def get_registry() -> UnifiedAgentRegistry:
    """
    Get the agent registry for the current tenant context.

    V10 PRISM: Returns tenant-scoped registry via ServiceFactory.
    Falls back to global singleton if no context is active (backward compat).

    Returns:
        UnifiedAgentRegistry instance scoped to current tenant
    """
    # V10: Try ServiceFactory first (tenant-scoped)
    try:
        from ..context import has_active_session

        if has_active_session():
            from ..factory import ServiceFactory

            return ServiceFactory.get_registry()
    except ImportError:
        pass  # context module not available, use legacy

    # Legacy fallback: global singleton
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = UnifiedAgentRegistry()
    return _registry


def reset_registry() -> None:
    """
    Reset the global registry (for testing).

    Note: In V10, also clears ServiceFactory cache for current tenant.
    """
    global _registry
    _registry = None

    # V10: Also clear factory cache
    try:
        from ..context import get_current_session_or_none
        from ..factory import ServiceFactory

        ctx = get_current_session_or_none()
        if ctx:
            ServiceFactory.clear_tenant_cache(ctx.tenant_id)
    except ImportError:
        pass
