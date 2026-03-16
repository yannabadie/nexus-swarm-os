# core/intelligence/swarm/capability_router.py
"""
CapabilityRouter — V12.4 Model-Agnostic Slot Assignment

Maps TaskAnalysis.domains → semantic slots → BaseAsyncDriver instances.
Phases receive agents: dict[SlotId, BaseAsyncDriver] — never provider IDs.

Slots:
  primary   — Lead: best provider for the task's primary domain
  secondary — Support: best different provider (anti-homogeneity)
  critic    — Adversarial: best at security/analysis (RED_BLUE, Diagnosis)
  executor  — Tool-heavy: best at coding/web_interaction
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.foundation.agents.unified_registry import UnifiedAgentRegistry
    from core.foundation.agents.unified_registry import BaseAsyncDriver
    from core.intelligence.swarm.task_analyzer import TaskAnalysis

from core.intelligence.swarm.task_analyzer import AGENT_DOMAIN_STRENGTHS

SLOT_PRIMARY = "primary"
SLOT_SECONDARY = "secondary"
SLOT_CRITIC = "critic"
SLOT_EXECUTOR = "executor"

ALL_SLOTS = (SLOT_PRIMARY, SLOT_SECONDARY, SLOT_CRITIC, SLOT_EXECUTOR)


@dataclass(frozen=True)
class SlotAssignment:
    """Scored provider assignment for a single slot."""

    slot: str
    provider_id: str
    score: float


class CapabilityRouter:
    """
    Assigns available providers to semantic slots based on task domains.

    Usage:
        router = CapabilityRouter(registry)
        agents = router.route(task_analysis)
        # agents = {"primary": driver_a, "secondary": driver_b, ...}
    """

    def __init__(self, registry: "UnifiedAgentRegistry") -> None:
        self._registry = registry

    def route(self, task: "TaskAnalysis") -> dict[str, "BaseAsyncDriver"]:
        """
        Assign providers to slots for the given task.

        Returns:
            dict mapping slot name → driver instance

        Raises:
            RuntimeError: If no providers are registered
        """
        available = self._registry.get_active_builtin_ids()
        if not available:
            raise RuntimeError(
                "No providers registered — cannot route. "
                "Register at least one driver via UnifiedAgentRegistry."
            )

        # Single-provider case: all slots → same driver
        if len(available) == 1:
            driver = self._registry.get_driver(available[0])
            return {slot: driver for slot in ALL_SLOTS}

        slot_to_provider = self._assign_slots(task, available)

        return {
            slot: self._registry.get_driver(pid)
            for slot, pid in slot_to_provider.items()
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _assign_slots(
        self, task: "TaskAnalysis", available: list[str]
    ) -> dict[str, str]:
        """Return {slot: provider_id} for each slot."""
        ranked = self._rank_by_task(task, available)

        primary = ranked[0]
        secondary = next(
            (p for p in ranked[1:] if p != primary),
            primary,  # fallback: same provider if only 1 available
        )
        critic = (
            self._best_for_domain("security", available, exclude=primary) or secondary
        )
        executor = self._best_for_domain("coding", available) or primary

        return {
            SLOT_PRIMARY: primary,
            SLOT_SECONDARY: secondary,
            SLOT_CRITIC: critic,
            SLOT_EXECUTOR: executor,
        }

    def _rank_by_task(self, task: "TaskAnalysis", available: list[str]) -> list[str]:
        """Rank providers by average score across task domains."""
        domain_names = [d.value for d in task.domains] if task.domains else ["general"]

        def _score(provider_id: str) -> float:
            strengths = AGENT_DOMAIN_STRENGTHS.get(provider_id, {})
            if not strengths:
                return 0.5
            total = 0.0
            for domain in domain_names:
                matched = next(
                    (
                        v
                        for k, v in strengths.items()
                        if (k.value if hasattr(k, "value") else k) == domain
                    ),
                    0.5,
                )
                total += matched
            return total / len(domain_names)

        return sorted(available, key=_score, reverse=True)

    def _best_for_domain(
        self,
        domain: str,
        available: list[str],
        exclude: str | None = None,
    ) -> str | None:
        """Return provider with highest score for a specific domain."""
        candidates = [p for p in available if p != exclude]
        if not candidates:
            return None

        def _domain_score(provider_id: str) -> float:
            strengths = AGENT_DOMAIN_STRENGTHS.get(provider_id, {})
            return next(
                (
                    v
                    for k, v in strengths.items()
                    if (k.value if hasattr(k, "value") else k) == domain
                ),
                0.5,
            )

        return max(candidates, key=_domain_score)
