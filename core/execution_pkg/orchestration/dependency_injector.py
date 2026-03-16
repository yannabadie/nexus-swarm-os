"""
Dependency Injector - Capability registry and agent dependency resolution.

V12.4 COGNITIVE BOOST - Task #51

Registers available capabilities, validates agent readiness, resolves
dependencies, and detects conflicts between agents requesting exclusive
resources.

Usage:
    from core.execution_pkg.orchestration.dependency_injector import get_injector

    injector = get_injector()

    # Register capabilities
    injector.register("web_search", provider="tools.web")
    injector.register("code_exec", provider="tools.bash", exclusive=True)

    # Declare agent requirements
    injector.require("claude", ["web_search", "code_exec"])
    injector.require("gemini", ["web_search"])

    # Validate readiness
    result = injector.validate("claude")
    assert result.ready

    # Detect conflicts
    conflicts = injector.detect_conflicts(["claude", "gemini"])
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Types
# =============================================================================


@dataclass
class Capability:
    """A registered capability."""

    name: str
    provider: str = ""
    description: str = ""
    exclusive: bool = False  # Only one agent can use at a time
    available: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "provider": self.provider,
            "description": self.description,
            "exclusive": self.exclusive,
            "available": self.available,
        }


@dataclass
class AgentRequirements:
    """Requirements for an agent."""

    agent_id: str
    required: set[str] = field(default_factory=set)
    optional: set[str] = field(default_factory=set)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "required": sorted(self.required),
            "optional": sorted(self.optional),
        }


@dataclass
class ValidationResult:
    """Result of validating agent readiness."""

    agent_id: str
    ready: bool
    satisfied: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)
    optional_satisfied: list[str] = field(default_factory=list)
    optional_missing: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "ready": self.ready,
            "satisfied": self.satisfied,
            "missing": self.missing,
            "unavailable": self.unavailable,
            "optional_satisfied": self.optional_satisfied,
            "optional_missing": self.optional_missing,
        }


@dataclass
class Conflict:
    """A capability conflict between agents."""

    capability: str
    agents: list[str]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "agents": self.agents,
            "reason": self.reason,
        }


@dataclass
class DependencyManifest:
    """Complete dependency manifest for an agent."""

    agent_id: str
    required_capabilities: list[str]
    optional_capabilities: list[str]
    resolved: dict[str, str]  # capability -> provider
    unresolved: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "required": self.required_capabilities,
            "optional": self.optional_capabilities,
            "resolved": self.resolved,
            "unresolved": self.unresolved,
        }


# =============================================================================
# Dependency Injector
# =============================================================================


class DependencyInjector:
    """
    Capability registry and agent dependency resolver.

    Tracks:
    - Available capabilities and their providers
    - Agent requirements (required + optional)
    - Exclusive resource constraints
    - Dependency resolution and conflict detection
    """

    def __init__(self):
        self._capabilities: dict[str, Capability] = {}
        self._requirements: dict[str, AgentRequirements] = {}
        self._lock = threading.Lock()

    # =========================================================================
    # Register Capabilities
    # =========================================================================

    def register(
        self,
        name: str,
        *,
        provider: str = "",
        description: str = "",
        exclusive: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> Capability:
        """
        Register a capability.

        Args:
            name: Capability name
            provider: Provider identifier
            description: Human-readable description
            exclusive: Whether only one agent can use this at a time
            metadata: Optional metadata
        """
        cap = Capability(
            name=name,
            provider=provider,
            description=description,
            exclusive=exclusive,
            metadata=metadata or {},
        )
        with self._lock:
            self._capabilities[name] = cap
        return cap

    def unregister(self, name: str) -> bool:
        """Remove a capability."""
        with self._lock:
            return self._capabilities.pop(name, None) is not None

    def set_available(self, name: str, available: bool) -> bool:
        """Set capability availability."""
        with self._lock:
            cap = self._capabilities.get(name)
            if cap is None:
                return False
            cap.available = available
        return True

    def is_registered(self, name: str) -> bool:
        """Check if a capability is registered."""
        return name in self._capabilities

    def is_available(self, name: str) -> bool:
        """Check if a capability is registered and available."""
        cap = self._capabilities.get(name)
        return cap is not None and cap.available

    def get_capability(self, name: str) -> Capability | None:
        """Get a capability by name."""
        return self._capabilities.get(name)

    # =========================================================================
    # Agent Requirements
    # =========================================================================

    def require(
        self,
        agent_id: str,
        capabilities: list[str],
        *,
        optional: list[str] | None = None,
    ) -> AgentRequirements:
        """
        Declare an agent's capability requirements.

        Args:
            agent_id: Agent identifier
            capabilities: Required capabilities
            optional: Optional (nice-to-have) capabilities
        """
        with self._lock:
            reqs = self._requirements.get(agent_id)
            if reqs is None:
                reqs = AgentRequirements(agent_id=agent_id)
                self._requirements[agent_id] = reqs
            reqs.required.update(capabilities)
            if optional:
                reqs.optional.update(optional)
        return reqs

    def get_requirements(self, agent_id: str) -> AgentRequirements | None:
        """Get requirements for an agent."""
        return self._requirements.get(agent_id)

    # =========================================================================
    # Validation
    # =========================================================================

    def validate(self, agent_id: str) -> ValidationResult:
        """
        Validate that an agent has all required capabilities.

        Returns:
            ValidationResult with satisfied/missing/unavailable lists
        """
        with self._lock:
            reqs = self._requirements.get(agent_id)
            if reqs is None:
                return ValidationResult(
                    agent_id=agent_id,
                    ready=True,  # No requirements = ready
                )

            satisfied = []
            missing = []
            unavailable = []

            for cap_name in sorted(reqs.required):
                cap = self._capabilities.get(cap_name)
                if cap is None:
                    missing.append(cap_name)
                elif not cap.available:
                    unavailable.append(cap_name)
                else:
                    satisfied.append(cap_name)

            optional_satisfied = []
            optional_missing = []
            for cap_name in sorted(reqs.optional):
                cap = self._capabilities.get(cap_name)
                if cap is not None and cap.available:
                    optional_satisfied.append(cap_name)
                else:
                    optional_missing.append(cap_name)

            return ValidationResult(
                agent_id=agent_id,
                ready=len(missing) == 0 and len(unavailable) == 0,
                satisfied=satisfied,
                missing=missing,
                unavailable=unavailable,
                optional_satisfied=optional_satisfied,
                optional_missing=optional_missing,
            )

    def validate_all(self) -> list[ValidationResult]:
        """Validate all registered agents."""
        with self._lock:
            agent_ids = list(self._requirements.keys())
        return [self.validate(aid) for aid in sorted(agent_ids)]

    # =========================================================================
    # Conflict Detection
    # =========================================================================

    def detect_conflicts(self, agent_ids: list[str] | None = None) -> list[Conflict]:
        """
        Detect capability conflicts between agents.

        Finds exclusive capabilities required by multiple agents.

        Args:
            agent_ids: Agents to check (default: all)
        """
        with self._lock:
            if agent_ids is None:
                agent_ids = list(self._requirements.keys())

            # Map: capability -> [agents needing it]
            cap_to_agents: dict[str, list[str]] = {}
            for aid in agent_ids:
                reqs = self._requirements.get(aid)
                if reqs is None:
                    continue
                for cap_name in reqs.required:
                    cap_to_agents.setdefault(cap_name, []).append(aid)

            conflicts = []
            for cap_name, agents in sorted(cap_to_agents.items()):
                if len(agents) <= 1:
                    continue
                cap = self._capabilities.get(cap_name)
                if cap and cap.exclusive:
                    conflicts.append(
                        Conflict(
                            capability=cap_name,
                            agents=sorted(agents),
                            reason=f"Exclusive capability '{cap_name}' required by multiple agents",
                        )
                    )

        return conflicts

    # =========================================================================
    # Manifest
    # =========================================================================

    def get_manifest(self, agent_id: str) -> DependencyManifest | None:
        """
        Get a dependency manifest for an agent.

        Shows what's resolved and what's unresolved.
        """
        with self._lock:
            reqs = self._requirements.get(agent_id)
            if reqs is None:
                return None

            resolved = {}
            unresolved = []

            for cap_name in sorted(reqs.required):
                cap = self._capabilities.get(cap_name)
                if cap and cap.available:
                    resolved[cap_name] = cap.provider
                else:
                    unresolved.append(cap_name)

            return DependencyManifest(
                agent_id=agent_id,
                required_capabilities=sorted(reqs.required),
                optional_capabilities=sorted(reqs.optional),
                resolved=resolved,
                unresolved=unresolved,
            )

    # =========================================================================
    # Listing
    # =========================================================================

    def list_capabilities(self, *, available_only: bool = False) -> list[Capability]:
        """List all registered capabilities."""
        caps = list(self._capabilities.values())
        if available_only:
            caps = [c for c in caps if c.available]
        return sorted(caps, key=lambda c: c.name)

    def list_agents(self) -> list[str]:
        """List all agents with requirements."""
        return sorted(self._requirements.keys())

    # =========================================================================
    # State
    # =========================================================================

    @property
    def capability_count(self) -> int:
        return len(self._capabilities)

    @property
    def agent_count(self) -> int:
        return len(self._requirements)

    def clear(self) -> None:
        """Clear all capabilities and requirements."""
        with self._lock:
            self._capabilities.clear()
            self._requirements.clear()

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_count": self.capability_count,
            "agent_count": self.agent_count,
            "capabilities": {name: cap.to_dict() for name, cap in sorted(self._capabilities.items())},
            "agents": {aid: reqs.to_dict() for aid, reqs in sorted(self._requirements.items())},
        }


# =============================================================================
# Global Instance
# =============================================================================

_injector: DependencyInjector | None = None
_injector_lock = threading.Lock()


def get_injector() -> DependencyInjector:
    """Get or create the global dependency injector."""
    global _injector
    if _injector is None:
        with _injector_lock:
            if _injector is None:
                _injector = DependencyInjector()
    return _injector


def reset_injector() -> None:
    """Reset the global injector (for testing)."""
    global _injector
    _injector = None
