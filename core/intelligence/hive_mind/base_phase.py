# core/intelligence/hive_mind/base_phase.py
"""
BasePhase — V12.4 Model-Agnostic Phase Base Class

All HiveMind phases extend this class. Provides:
- agents: dict[str, BaseAsyncDriver]  — keyed by semantic slot
- Deprecated .gemini / .claude properties for backward compat

Slot conventions (set by CapabilityRouter):
  "primary"   — lead analytical provider
  "secondary" — support / alternation
  "critic"    — adversarial / diagnosis
  "executor"  — tool-heavy / coding

Backward compat:
  self.gemini  -> self.agents.get("primary") or self.agents.get("gemini")
  self.claude  -> self.agents.get("secondary") or self.agents.get("claude")
"""
from __future__ import annotations

import warnings
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.foundation.agents.unified_registry import BaseAsyncDriver


class BasePhase:
    """
    Base class for all HiveMind phases.

    Subclasses receive agents keyed by semantic slot.
    The deprecated .gemini and .claude attributes remain available
    for one migration cycle, then will be removed.
    """

    def __init__(
        self,
        *,
        agents: dict[str, "BaseAsyncDriver"] | None = None,
    ) -> None:
        self.agents: dict[str, "BaseAsyncDriver"] = agents or {}

    # ------------------------------------------------------------------
    # Deprecated backward-compat aliases
    # ------------------------------------------------------------------

    @property
    def gemini(self) -> "BaseAsyncDriver | None":
        """
        Deprecated. Use self.agents["primary"] instead.

        Maps to: agents["primary"] -> agents["gemini"] -> None
        """
        warnings.warn(
            "self.gemini is deprecated since V12.4 — use self.agents['primary']",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.agents.get("primary") or self.agents.get("gemini")

    @gemini.setter
    def gemini(self, value: "BaseAsyncDriver | None") -> None:
        """Setter kept for legacy __init__ assignments in subclasses."""
        if value is not None:
            self.agents["gemini"] = value

    @property
    def claude(self) -> "BaseAsyncDriver | None":
        """
        Deprecated. Use self.agents["secondary"] instead.

        Maps to: agents["secondary"] -> agents["claude"] -> None
        """
        warnings.warn(
            "self.claude is deprecated since V12.4 — use self.agents['secondary']",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.agents.get("secondary") or self.agents.get("claude")

    @claude.setter
    def claude(self, value: "BaseAsyncDriver | None") -> None:
        """Setter kept for legacy __init__ assignments in subclasses."""
        if value is not None:
            self.agents["claude"] = value
