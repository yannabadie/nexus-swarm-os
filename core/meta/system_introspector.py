"""
System Introspector - Runtime state and capability introspection.

V12.4 COGNITIVE BOOST

Provides a registry of system components and their capabilities,
enabling agents to query what the system can do at runtime.

Usage:
    from core.meta.system_introspector import get_introspector

    intro = get_introspector()
    intro.register_component("swarm_engine", category="orchestration",
                             capabilities=["parallel", "sequential", "lead_support"])

    snapshot = intro.get_snapshot()
    components = intro.find_by_capability("parallel")
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

MAX_COMPONENTS = 1000
CATEGORIES = {"orchestration", "memory", "security", "telemetry", "reasoning", "execution", "interface", "other"}


# =============================================================================
# Types
# =============================================================================


@dataclass
class ComponentInfo:
    """Information about a registered system component."""

    component_id: str
    category: str = "other"
    version: str = ""
    description: str = ""
    capabilities: list[str] = field(default_factory=list)
    status: str = "active"  # active, degraded, inactive
    registered_at: float = field(default_factory=time.monotonic)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "component_id": self.component_id,
            "category": self.category,
            "version": self.version,
            "description": self.description,
            "capabilities": self.capabilities,
            "status": self.status,
            "metadata": self.metadata,
        }


@dataclass
class SystemSnapshot:
    """A point-in-time snapshot of system state."""

    total_components: int
    active_components: int
    degraded_components: int
    inactive_components: int
    categories: dict[str, int]
    total_capabilities: int
    timestamp: float = field(default_factory=time.monotonic)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_components": self.total_components,
            "active_components": self.active_components,
            "degraded_components": self.degraded_components,
            "inactive_components": self.inactive_components,
            "categories": self.categories,
            "total_capabilities": self.total_capabilities,
        }


@dataclass
class IntrospectorStats:
    """Introspector statistics."""

    total_registered: int
    total_queries: int
    total_capability_lookups: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_registered": self.total_registered,
            "total_queries": self.total_queries,
            "total_capability_lookups": self.total_capability_lookups,
        }


# =============================================================================
# System Introspector
# =============================================================================


class SystemIntrospector:
    """
    Registry of system components and their capabilities.

    Features:
    - Register/unregister components with capabilities
    - Query by component, category, capability, status
    - System snapshot generation
    - Status updates (active, degraded, inactive)
    - Thread-safe
    """

    def __init__(self):
        self._components: dict[str, ComponentInfo] = {}
        self._total_queries = 0
        self._total_capability_lookups = 0
        self._lock = threading.Lock()

    # =========================================================================
    # Registration
    # =========================================================================

    def register_component(
        self,
        component_id: str,
        *,
        category: str = "other",
        version: str = "",
        description: str = "",
        capabilities: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Register a system component. Returns False if already exists or at limit."""
        with self._lock:
            if component_id in self._components:
                return False
            if len(self._components) >= MAX_COMPONENTS:
                return False
            self._components[component_id] = ComponentInfo(
                component_id=component_id,
                category=category,
                version=version,
                description=description,
                capabilities=capabilities or [],
                metadata=metadata or {},
            )
            return True

    def unregister_component(self, component_id: str) -> bool:
        """Unregister a component."""
        with self._lock:
            if component_id in self._components:
                del self._components[component_id]
                return True
            return False

    def update_status(self, component_id: str, status: str) -> bool:
        """Update a component's status (active, degraded, inactive)."""
        with self._lock:
            comp = self._components.get(component_id)
            if comp is None:
                return False
            comp.status = status
            return True

    def add_capability(self, component_id: str, capability: str) -> bool:
        """Add a capability to a component."""
        with self._lock:
            comp = self._components.get(component_id)
            if comp is None:
                return False
            if capability not in comp.capabilities:
                comp.capabilities.append(capability)
            return True

    def remove_capability(self, component_id: str, capability: str) -> bool:
        """Remove a capability from a component."""
        with self._lock:
            comp = self._components.get(component_id)
            if comp is None:
                return False
            if capability in comp.capabilities:
                comp.capabilities.remove(capability)
                return True
            return False

    # =========================================================================
    # Queries
    # =========================================================================

    def get_component(self, component_id: str) -> ComponentInfo | None:
        """Get a component by ID."""
        self._total_queries += 1
        return self._components.get(component_id)

    def is_registered(self, component_id: str) -> bool:
        return component_id in self._components

    def list_components(self, *, category: str | None = None, status: str | None = None) -> list[str]:
        """List component IDs with optional filters."""
        self._total_queries += 1
        result = []
        for cid, comp in self._components.items():
            if category and comp.category != category:
                continue
            if status and comp.status != status:
                continue
            result.append(cid)
        return sorted(result)

    def find_by_capability(self, capability: str) -> list[ComponentInfo]:
        """Find all components that have a specific capability."""
        self._total_capability_lookups += 1
        return [
            comp for comp in self._components.values() if capability in comp.capabilities and comp.status != "inactive"
        ]

    def list_all_capabilities(self) -> list[str]:
        """List all unique capabilities across all components."""
        caps: set[str] = set()
        for comp in self._components.values():
            caps.update(comp.capabilities)
        return sorted(caps)

    def get_by_category(self, category: str) -> list[ComponentInfo]:
        """Get all components in a category."""
        self._total_queries += 1
        return [comp for comp in self._components.values() if comp.category == category]

    # =========================================================================
    # Snapshot
    # =========================================================================

    def get_snapshot(self) -> SystemSnapshot:
        """Generate a point-in-time system snapshot."""
        active = sum(1 for c in self._components.values() if c.status == "active")
        degraded = sum(1 for c in self._components.values() if c.status == "degraded")
        inactive = sum(1 for c in self._components.values() if c.status == "inactive")

        cats: dict[str, int] = {}
        for comp in self._components.values():
            cats[comp.category] = cats.get(comp.category, 0) + 1

        all_caps: set[str] = set()
        for comp in self._components.values():
            all_caps.update(comp.capabilities)

        return SystemSnapshot(
            total_components=len(self._components),
            active_components=active,
            degraded_components=degraded,
            inactive_components=inactive,
            categories=cats,
            total_capabilities=len(all_caps),
        )

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> IntrospectorStats:
        return IntrospectorStats(
            total_registered=len(self._components),
            total_queries=self._total_queries,
            total_capability_lookups=self._total_capability_lookups,
        )

    # =========================================================================
    # State
    # =========================================================================

    @property
    def component_count(self) -> int:
        return len(self._components)

    def clear(self) -> None:
        with self._lock:
            self._components.clear()
            self._total_queries = 0
            self._total_capability_lookups = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "component_count": self.component_count,
            "snapshot": self.get_snapshot().to_dict(),
            "stats": self.get_stats().to_dict(),
        }


# =============================================================================
# Global Instance
# =============================================================================

_introspector: SystemIntrospector | None = None
_introspector_lock = threading.Lock()


def get_introspector() -> SystemIntrospector:
    """Get or create the global system introspector."""
    global _introspector
    if _introspector is None:
        with _introspector_lock:
            if _introspector is None:
                _introspector = SystemIntrospector()
    return _introspector


def reset_introspector() -> None:
    """Reset the global system introspector (for testing)."""
    global _introspector
    _introspector = None
