"""
Config Manager - Centralized typed configuration management.

V12.4 COGNITIVE BOOST - Task #62

Provides centralized configuration with sections, typed access,
validation, defaults, and dynamic updates.

Usage:
    from core.utils.config_manager import get_config_manager

    config = get_config_manager()

    # Set values
    config.set("swarm", "auto_route", True)
    config.set("models", "default_provider", "claude")
    config.set("limits", "max_tokens", 128000)

    # Get with type safety
    auto_route = config.get_bool("swarm", "auto_route", default=True)
    max_tokens = config.get_int("limits", "max_tokens", default=100000)
    provider = config.get_str("models", "default_provider")

    # List
    sections = config.list_sections()
    keys = config.list_keys("swarm")
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Types
# =============================================================================


@dataclass
class ConfigEntry:
    """A single configuration entry."""

    section: str
    key: str
    value: Any
    value_type: str = ""  # "str", "int", "float", "bool", "list", "dict"
    description: str = ""

    def __post_init__(self):
        if not self.value_type:
            self.value_type = type(self.value).__name__

    def to_dict(self) -> dict[str, Any]:
        return {
            "section": self.section,
            "key": self.key,
            "value": self.value,
            "value_type": self.value_type,
            "description": self.description,
        }


@dataclass
class ConfigValidation:
    """Result of config validation."""

    is_valid: bool
    missing_keys: list[str] = field(default_factory=list)
    type_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "missing_keys": self.missing_keys,
            "type_errors": self.type_errors,
        }


# =============================================================================
# Config Manager
# =============================================================================


class ConfigManager:
    """
    Centralized configuration management.

    Features:
    - Section-based organization
    - Typed get methods (str, int, float, bool)
    - Default values
    - Bulk load from dict
    - Validation against required keys
    - Dynamic updates
    - Thread-safe operations
    """

    def __init__(self):
        self._data: dict[str, dict[str, ConfigEntry]] = defaultdict(dict)
        self._required: dict[str, set[str]] = defaultdict(set)
        self._lock = threading.Lock()

    # =========================================================================
    # Set
    # =========================================================================

    def set(
        self,
        section: str,
        key: str,
        value: Any,
        *,
        description: str = "",
    ) -> None:
        """Set a configuration value."""
        entry = ConfigEntry(
            section=section,
            key=key,
            value=value,
            description=description,
        )
        with self._lock:
            self._data[section][key] = entry

    def set_many(self, section: str, values: dict[str, Any]) -> int:
        """Set multiple values in a section. Returns count set."""
        count = 0
        with self._lock:
            for key, value in values.items():
                entry = ConfigEntry(section=section, key=key, value=value)
                self._data[section][key] = entry
                count += 1
        return count

    def load_dict(self, data: dict[str, dict[str, Any]]) -> int:
        """Load configuration from a nested dict (section -> key -> value). Returns count."""
        count = 0
        with self._lock:
            for section, keys in data.items():
                for key, value in keys.items():
                    entry = ConfigEntry(section=section, key=key, value=value)
                    self._data[section][key] = entry
                    count += 1
        return count

    # =========================================================================
    # Get
    # =========================================================================

    def get(self, section: str, key: str, default: Any = None) -> Any:
        """Get a configuration value."""
        with self._lock:
            entry = self._data.get(section, {}).get(key)
        if entry is None:
            return default
        return entry.value

    def get_str(self, section: str, key: str, default: str = "") -> str:
        """Get a string configuration value."""
        val = self.get(section, key)
        if val is None:
            return default
        return str(val)

    def get_int(self, section: str, key: str, default: int = 0) -> int:
        """Get an integer configuration value."""
        val = self.get(section, key)
        if val is None:
            return default
        try:
            return int(val)
        except (ValueError, TypeError):
            return default

    def get_float(self, section: str, key: str, default: float = 0.0) -> float:
        """Get a float configuration value."""
        val = self.get(section, key)
        if val is None:
            return default
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    def get_bool(self, section: str, key: str, default: bool = False) -> bool:
        """Get a boolean configuration value."""
        val = self.get(section, key)
        if val is None:
            return default
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.lower() in ("true", "1", "yes")
        return bool(val)

    def get_entry(self, section: str, key: str) -> ConfigEntry | None:
        """Get the full ConfigEntry."""
        with self._lock:
            return self._data.get(section, {}).get(key)

    def has(self, section: str, key: str) -> bool:
        """Check if a key exists."""
        with self._lock:
            return key in self._data.get(section, {})

    # =========================================================================
    # Delete
    # =========================================================================

    def delete(self, section: str, key: str) -> bool:
        """Delete a configuration entry."""
        with self._lock:
            entries = self._data.get(section, {})
            if key in entries:
                del entries[key]
                if not entries:
                    del self._data[section]
                return True
            return False

    def delete_section(self, section: str) -> bool:
        """Delete an entire section."""
        with self._lock:
            return self._data.pop(section, None) is not None

    # =========================================================================
    # Validation
    # =========================================================================

    def require(self, section: str, key: str) -> None:
        """Mark a key as required."""
        with self._lock:
            self._required[section].add(key)

    def validate(self) -> ConfigValidation:
        """Validate that all required keys exist."""
        missing = []
        type_errors = []
        with self._lock:
            for section, keys in self._required.items():
                for key in keys:
                    if key not in self._data.get(section, {}):
                        missing.append(f"{section}.{key}")
        return ConfigValidation(
            is_valid=len(missing) == 0 and len(type_errors) == 0,
            missing_keys=missing,
            type_errors=type_errors,
        )

    # =========================================================================
    # Listing
    # =========================================================================

    def list_sections(self) -> list[str]:
        """List all sections."""
        with self._lock:
            return sorted(self._data.keys())

    def list_keys(self, section: str) -> list[str]:
        """List all keys in a section."""
        with self._lock:
            return sorted(self._data.get(section, {}).keys())

    def get_section(self, section: str) -> dict[str, Any]:
        """Get all key-value pairs in a section."""
        with self._lock:
            entries = self._data.get(section, {})
            return {k: e.value for k, e in entries.items()}

    def get_all(self) -> dict[str, dict[str, Any]]:
        """Get all configuration as nested dict."""
        with self._lock:
            return {section: {k: e.value for k, e in entries.items()} for section, entries in self._data.items()}

    # =========================================================================
    # State
    # =========================================================================

    @property
    def section_count(self) -> int:
        return len(self._data)

    @property
    def key_count(self) -> int:
        return sum(len(v) for v in self._data.values())

    def clear(self) -> None:
        """Clear all configuration."""
        with self._lock:
            self._data.clear()
            self._required.clear()

    def to_dict(self) -> dict[str, Any]:
        return {
            "section_count": self.section_count,
            "key_count": self.key_count,
            "sections": self.list_sections(),
        }


# =============================================================================
# Global Instance
# =============================================================================

_manager: ConfigManager | None = None
_manager_lock = threading.Lock()


def get_config_manager() -> ConfigManager:
    """Get or create the global config manager."""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = ConfigManager()
    return _manager


def reset_config_manager() -> None:
    """Reset the global config manager (for testing)."""
    global _manager
    _manager = None
