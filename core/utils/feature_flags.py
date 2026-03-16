"""
Feature Flag System - Runtime feature toggles for safe experimentation.

V12.4 COGNITIVE BOOST - Task #48

Enables gradual rollouts, A/B testing of agent configurations, and
safe experimentation with new features. Flags can be toggled at runtime
without restarting NEXUS.

Usage:
    from core.utils.feature_flags import FeatureFlags, get_flags

    flags = get_flags()
    flags.define("swarm_auto_route", default=True, description="Auto-route to swarm")
    flags.define("new_debate_engine", default=False, description="V12.4 debate engine")

    if flags.is_enabled("swarm_auto_route"):
        # Use swarm routing
        ...

    # Override at runtime
    flags.set("new_debate_engine", True)

    # Percentage rollout
    flags.define("experimental_cache", default=False, rollout_pct=25)
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

DEFAULT_FLAGS_FILE = "workspace/.nexus/feature_flags.json"


# =============================================================================
# Types
# =============================================================================


@dataclass
class FlagDefinition:
    """Definition of a feature flag."""

    name: str
    default: bool = False
    description: str = ""
    rollout_pct: int = 100  # 0-100, percentage of contexts that get True
    tags: list[str] = field(default_factory=list)
    created_at: float = 0.0

    def __post_init__(self):
        if self.created_at == 0.0:
            self.created_at = time.monotonic()
        self.rollout_pct = max(0, min(100, self.rollout_pct))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "default": self.default,
            "description": self.description,
            "rollout_pct": self.rollout_pct,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FlagDefinition:
        return cls(
            name=data["name"],
            default=data.get("default", False),
            description=data.get("description", ""),
            rollout_pct=data.get("rollout_pct", 100),
            tags=data.get("tags", []),
        )


@dataclass
class FlagOverride:
    """A runtime override for a flag."""

    name: str
    value: bool
    reason: str = ""
    set_at: float = 0.0

    def __post_init__(self):
        if self.set_at == 0.0:
            self.set_at = time.monotonic()


@dataclass
class FlagStatus:
    """Current status of a flag."""

    name: str
    enabled: bool
    source: str  # "default", "override", "rollout"
    definition: FlagDefinition
    override: FlagOverride | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "source": self.source,
            "description": self.definition.description,
            "default": self.definition.default,
            "rollout_pct": self.definition.rollout_pct,
            "has_override": self.override is not None,
        }


# =============================================================================
# Feature Flags
# =============================================================================


class FeatureFlags:
    """
    Runtime feature flag system.

    Supports:
    - Boolean flags with defaults
    - Runtime overrides
    - Percentage-based rollouts (deterministic per context key)
    - Tag-based grouping
    - Persistence to disk
    """

    def __init__(
        self,
        *,
        flags_file: str | None = None,
        persist: bool = True,
    ):
        self._definitions: dict[str, FlagDefinition] = {}
        self._overrides: dict[str, FlagOverride] = {}
        self._flags_file = Path(flags_file) if flags_file else Path(DEFAULT_FLAGS_FILE)
        self._persist = persist
        self._lock = threading.Lock()

        if self._persist:
            self._load()

    # =========================================================================
    # Define Flags
    # =========================================================================

    def define(
        self,
        name: str,
        *,
        default: bool = False,
        description: str = "",
        rollout_pct: int = 100,
        tags: list[str] | None = None,
    ) -> FlagDefinition:
        """
        Define a feature flag.

        Args:
            name: Flag name (unique identifier)
            default: Default value when no override
            description: Human-readable description
            rollout_pct: Percentage rollout (0-100)
            tags: Optional tags for grouping

        Returns:
            The created FlagDefinition
        """
        flag = FlagDefinition(
            name=name,
            default=default,
            description=description,
            rollout_pct=rollout_pct,
            tags=tags or [],
        )
        with self._lock:
            self._definitions[name] = flag
        if self._persist:
            self._save()
        return flag

    # =========================================================================
    # Query Flags
    # =========================================================================

    def is_enabled(
        self,
        name: str,
        *,
        context_key: str = "",
    ) -> bool:
        """
        Check if a flag is enabled.

        Args:
            name: Flag name
            context_key: Context key for rollout percentage (e.g. session_id)

        Returns:
            True if enabled
        """
        with self._lock:
            # Check override first
            override = self._overrides.get(name)
            if override is not None:
                return override.value

            # Check definition
            defn = self._definitions.get(name)
            if defn is None:
                return False

            # Percentage rollout
            if defn.rollout_pct < 100 and context_key:
                return self._in_rollout(name, context_key, defn.rollout_pct)

            return defn.default

    def get_status(self, name: str) -> FlagStatus | None:
        """Get detailed status of a flag."""
        with self._lock:
            defn = self._definitions.get(name)
            if defn is None:
                return None

            override = self._overrides.get(name)
            if override is not None:
                return FlagStatus(
                    name=name,
                    enabled=override.value,
                    source="override",
                    definition=defn,
                    override=override,
                )

            return FlagStatus(
                name=name,
                enabled=defn.default,
                source="default",
                definition=defn,
            )

    def is_defined(self, name: str) -> bool:
        """Check if a flag is defined."""
        return name in self._definitions

    # =========================================================================
    # Override Flags
    # =========================================================================

    def set(self, name: str, value: bool, *, reason: str = "") -> bool:
        """
        Set a runtime override for a flag.

        Args:
            name: Flag name
            value: Override value
            reason: Optional reason for the override

        Returns:
            True if flag exists and override was set
        """
        with self._lock:
            if name not in self._definitions:
                return False
            self._overrides[name] = FlagOverride(
                name=name,
                value=value,
                reason=reason,
            )
        if self._persist:
            self._save()
        return True

    def unset(self, name: str) -> bool:
        """
        Remove a runtime override, reverting to default.

        Returns:
            True if override was removed
        """
        with self._lock:
            if name not in self._overrides:
                return False
            del self._overrides[name]
        if self._persist:
            self._save()
        return True

    def clear_overrides(self) -> int:
        """Clear all overrides."""
        with self._lock:
            count = len(self._overrides)
            self._overrides.clear()
        if self._persist:
            self._save()
        return count

    # =========================================================================
    # Listing & Filtering
    # =========================================================================

    def list_flags(
        self,
        *,
        tag: str | None = None,
        enabled_only: bool = False,
    ) -> list[FlagStatus]:
        """
        List all defined flags.

        Args:
            tag: Filter by tag
            enabled_only: Only return enabled flags
        """
        results = []
        for name in sorted(self._definitions):
            status = self.get_status(name)
            if status is None:
                continue
            if tag and tag not in status.definition.tags:
                continue
            if enabled_only and not status.enabled:
                continue
            results.append(status)
        return results

    def list_names(self) -> list[str]:
        """List all flag names."""
        return sorted(self._definitions.keys())

    def list_tags(self) -> list[str]:
        """List all unique tags."""
        tags: set[str] = set()
        for defn in self._definitions.values():
            tags.update(defn.tags)
        return sorted(tags)

    @property
    def flag_count(self) -> int:
        return len(self._definitions)

    @property
    def override_count(self) -> int:
        return len(self._overrides)

    # =========================================================================
    # Rollout
    # =========================================================================

    def _in_rollout(self, flag_name: str, context_key: str, pct: int) -> bool:
        """Deterministic percentage check using hash."""
        raw = f"{flag_name}:{context_key}"
        h = hashlib.md5(raw.encode(), usedforsecurity=False).hexdigest()
        bucket = int(h[:8], 16) % 100
        return bucket < pct

    # =========================================================================
    # Persistence
    # =========================================================================

    def _save(self) -> None:
        if not self._persist:
            return
        try:
            self._flags_file.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "definitions": {name: defn.to_dict() for name, defn in self._definitions.items()},
                "overrides": {name: {"value": ov.value, "reason": ov.reason} for name, ov in self._overrides.items()},
            }
            self._flags_file.write_text(
                json.dumps(data, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            _logger.warning("Failed to save flags: %s", e)

    def _load(self) -> None:
        if not self._flags_file.exists():
            return
        try:
            data = json.loads(self._flags_file.read_text(encoding="utf-8"))
            for name, d in data.get("definitions", {}).items():
                self._definitions[name] = FlagDefinition.from_dict(d)
            for name, d in data.get("overrides", {}).items():
                self._overrides[name] = FlagOverride(
                    name=name,
                    value=d["value"],
                    reason=d.get("reason", ""),
                )
        except (json.JSONDecodeError, KeyError) as e:
            _logger.warning("Failed to load flags: %s", e)

    # =========================================================================
    # State
    # =========================================================================

    def clear(self) -> None:
        """Clear all definitions and overrides."""
        with self._lock:
            self._definitions.clear()
            self._overrides.clear()

    def to_dict(self) -> dict[str, Any]:
        return {
            "flag_count": self.flag_count,
            "override_count": self.override_count,
            "flags": {
                name: status.to_dict()
                for name in sorted(self._definitions)
                if (status := self.get_status(name)) is not None
            },
        }


# =============================================================================
# Global Instance
# =============================================================================

_flags: FeatureFlags | None = None
_flags_lock = threading.Lock()


def get_flags() -> FeatureFlags:
    """Get or create the global feature flags instance."""
    global _flags
    if _flags is None:
        with _flags_lock:
            if _flags is None:
                _flags = FeatureFlags()
    return _flags


def reset_flags() -> None:
    """Reset the global flags instance (for testing)."""
    global _flags
    _flags = None
