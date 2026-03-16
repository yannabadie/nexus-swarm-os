"""
Access Control Manager - Role-based access control for agents and tools.

V12.4 COGNITIVE BOOST - Task #67

Manages permissions for agents to use specific tools, access resources,
and perform operations. Supports role-based and per-agent grants/denials.

Usage:
    from core.security_pkg.security.access_control import get_access_controller

    ac = get_access_controller()

    # Define roles
    ac.define_role("analyst", permissions={"read", "search", "analyze"})
    ac.define_role("executor", permissions={"read", "write", "execute"})

    # Assign roles to agents
    ac.assign_role("claude", "analyst")

    # Check access
    if ac.is_allowed("claude", "read"):
        # proceed
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

DEFAULT_ROLE = "default"
ADMIN_ROLE = "admin"
MAX_ROLES = 200
MAX_AGENTS = 5000


# =============================================================================
# Types
# =============================================================================


@dataclass
class Role:
    """A named set of permissions."""

    name: str
    permissions: set[str] = field(default_factory=set)
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "permissions": sorted(self.permissions),
            "description": self.description,
        }


@dataclass
class AgentAccess:
    """Access configuration for an agent."""

    agent_id: str
    roles: set[str] = field(default_factory=set)
    extra_permissions: set[str] = field(default_factory=set)
    denied_permissions: set[str] = field(default_factory=set)
    created_at: float = 0.0

    def __post_init__(self):
        if self.created_at == 0.0:
            self.created_at = time.monotonic()

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "roles": sorted(self.roles),
            "extra_permissions": sorted(self.extra_permissions),
            "denied_permissions": sorted(self.denied_permissions),
        }


@dataclass
class AccessCheckResult:
    """Result of an access check."""

    allowed: bool
    agent_id: str = ""
    permission: str = ""
    reason: str = ""
    matched_role: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "agent_id": self.agent_id,
            "permission": self.permission,
            "reason": self.reason,
        }


@dataclass
class AccessStats:
    """Access control statistics."""

    total_roles: int
    total_agents: int
    total_checks: int
    total_allowed: int
    total_denied: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_roles": self.total_roles,
            "total_agents": self.total_agents,
            "total_checks": self.total_checks,
            "total_allowed": self.total_allowed,
            "total_denied": self.total_denied,
        }


# =============================================================================
# Access Control Manager
# =============================================================================


class AccessControlManager:
    """
    Role-based access control for agents.

    Features:
    - Named roles with permission sets
    - Per-agent role assignment
    - Extra grants and explicit denials per agent
    - Denial takes precedence over grants
    - Admin role bypasses all checks
    - Statistics tracking
    - Thread-safe
    """

    def __init__(self):
        self._roles: dict[str, Role] = {}
        self._agents: dict[str, AgentAccess] = {}
        self._total_checks = 0
        self._total_allowed = 0
        self._total_denied = 0
        self._lock = threading.Lock()

    # =========================================================================
    # Role Management
    # =========================================================================

    def define_role(
        self,
        name: str,
        *,
        permissions: set[str] | None = None,
        description: str = "",
    ) -> Role:
        """Define or update a role."""
        role = Role(
            name=name,
            permissions=permissions or set(),
            description=description,
        )
        with self._lock:
            if len(self._roles) >= MAX_ROLES and name not in self._roles:
                raise ValueError(f"Maximum roles ({MAX_ROLES}) reached")
            self._roles[name] = role
        return role

    def remove_role(self, name: str) -> bool:
        """Remove a role definition."""
        with self._lock:
            if name not in self._roles:
                return False
            del self._roles[name]
            # Remove from all agents
            for agent in self._agents.values():
                agent.roles.discard(name)
            return True

    def get_role(self, name: str) -> Role | None:
        """Get a role by name."""
        return self._roles.get(name)

    def list_roles(self) -> list[Role]:
        """List all defined roles."""
        return list(self._roles.values())

    def add_permission_to_role(self, role_name: str, permission: str) -> bool:
        """Add a permission to an existing role."""
        with self._lock:
            role = self._roles.get(role_name)
            if role is None:
                return False
            role.permissions.add(permission)
            return True

    def remove_permission_from_role(self, role_name: str, permission: str) -> bool:
        """Remove a permission from an existing role."""
        with self._lock:
            role = self._roles.get(role_name)
            if role is None:
                return False
            role.permissions.discard(permission)
            return True

    # =========================================================================
    # Agent Management
    # =========================================================================

    def register_agent(self, agent_id: str) -> AgentAccess:
        """Register an agent for access control."""
        with self._lock:
            if agent_id in self._agents:
                return self._agents[agent_id]
            if len(self._agents) >= MAX_AGENTS:
                raise ValueError(f"Maximum agents ({MAX_AGENTS}) reached")
            access = AgentAccess(agent_id=agent_id)
            self._agents[agent_id] = access
            return access

    def unregister_agent(self, agent_id: str) -> bool:
        """Remove an agent."""
        with self._lock:
            return self._agents.pop(agent_id, None) is not None

    def get_agent(self, agent_id: str) -> AgentAccess | None:
        """Get agent access configuration."""
        return self._agents.get(agent_id)

    def assign_role(self, agent_id: str, role_name: str) -> bool:
        """Assign a role to an agent."""
        with self._lock:
            if role_name not in self._roles:
                return False
            agent = self._agents.get(agent_id)
            if agent is None:
                agent = AgentAccess(agent_id=agent_id)
                self._agents[agent_id] = agent
            agent.roles.add(role_name)
            return True

    def revoke_role(self, agent_id: str, role_name: str) -> bool:
        """Revoke a role from an agent."""
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent is None:
                return False
            if role_name not in agent.roles:
                return False
            agent.roles.discard(role_name)
            return True

    def grant_permission(self, agent_id: str, permission: str) -> bool:
        """Grant an extra permission to an agent (beyond roles)."""
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent is None:
                agent = AgentAccess(agent_id=agent_id)
                self._agents[agent_id] = agent
            agent.extra_permissions.add(permission)
            return True

    def deny_permission(self, agent_id: str, permission: str) -> bool:
        """Explicitly deny a permission to an agent (overrides roles)."""
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent is None:
                agent = AgentAccess(agent_id=agent_id)
                self._agents[agent_id] = agent
            agent.denied_permissions.add(permission)
            return True

    # =========================================================================
    # Access Checks
    # =========================================================================

    def is_allowed(self, agent_id: str, permission: str) -> bool:
        """Check if an agent has a permission."""
        result = self.check(agent_id, permission)
        return result.allowed

    def check(self, agent_id: str, permission: str) -> AccessCheckResult:
        """Detailed access check."""
        with self._lock:
            self._total_checks += 1
            agent = self._agents.get(agent_id)

            if agent is None:
                self._total_denied += 1
                return AccessCheckResult(
                    allowed=False,
                    agent_id=agent_id,
                    permission=permission,
                    reason="Agent not registered",
                )

            # Explicit deny always wins
            if permission in agent.denied_permissions:
                self._total_denied += 1
                return AccessCheckResult(
                    allowed=False,
                    agent_id=agent_id,
                    permission=permission,
                    reason="Explicitly denied",
                )

            # Check admin role
            if ADMIN_ROLE in agent.roles:
                self._total_allowed += 1
                return AccessCheckResult(
                    allowed=True,
                    agent_id=agent_id,
                    permission=permission,
                    reason="Admin role",
                    matched_role=ADMIN_ROLE,
                )

            # Check extra permissions
            if permission in agent.extra_permissions:
                self._total_allowed += 1
                return AccessCheckResult(
                    allowed=True,
                    agent_id=agent_id,
                    permission=permission,
                    reason="Extra grant",
                )

            # Check role permissions
            for role_name in agent.roles:
                role = self._roles.get(role_name)
                if role and permission in role.permissions:
                    self._total_allowed += 1
                    return AccessCheckResult(
                        allowed=True,
                        agent_id=agent_id,
                        permission=permission,
                        reason=f"Role: {role_name}",
                        matched_role=role_name,
                    )

            self._total_denied += 1
            return AccessCheckResult(
                allowed=False,
                agent_id=agent_id,
                permission=permission,
                reason="No matching permission",
            )

    def get_effective_permissions(self, agent_id: str) -> set[str]:
        """Get all effective permissions for an agent."""
        agent = self._agents.get(agent_id)
        if agent is None:
            return set()

        perms: set[str] = set()

        # Admin gets everything (represented as {"*"})
        if ADMIN_ROLE in agent.roles:
            perms.add("*")
            return perms

        # Collect from roles
        for role_name in agent.roles:
            role = self._roles.get(role_name)
            if role:
                perms.update(role.permissions)

        # Add extras
        perms.update(agent.extra_permissions)

        # Remove denied
        perms -= agent.denied_permissions

        return perms

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> AccessStats:
        """Get access control statistics."""
        return AccessStats(
            total_roles=len(self._roles),
            total_agents=len(self._agents),
            total_checks=self._total_checks,
            total_allowed=self._total_allowed,
            total_denied=self._total_denied,
        )

    # =========================================================================
    # State
    # =========================================================================

    @property
    def role_count(self) -> int:
        return len(self._roles)

    @property
    def agent_count(self) -> int:
        return len(self._agents)

    def clear(self) -> None:
        """Clear all roles, agents, and stats."""
        with self._lock:
            self._roles.clear()
            self._agents.clear()
            self._total_checks = 0
            self._total_allowed = 0
            self._total_denied = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "role_count": self.role_count,
            "agent_count": self.agent_count,
            "stats": self.get_stats().to_dict(),
        }


# =============================================================================
# Global Instance
# =============================================================================

_controller: AccessControlManager | None = None
_controller_lock = threading.Lock()


def get_access_controller() -> AccessControlManager:
    """Get or create the global access controller."""
    global _controller
    if _controller is None:
        with _controller_lock:
            if _controller is None:
                _controller = AccessControlManager()
    return _controller


def reset_access_controller() -> None:
    """Reset the global access controller (for testing)."""
    global _controller
    _controller = None
