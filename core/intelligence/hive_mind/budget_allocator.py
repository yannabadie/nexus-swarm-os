"""
NEXUS V12.4 - Phase Budget Allocator

Dynamic per-phase token budget allocation for the HiveMind pipeline.
Based on:
- TALE (arxiv:2412.18547): Budget allocation across reasoning steps
- BudgetThinker (arxiv:2508.17196): Control token budget awareness

Allocates a total token budget across the 7 HiveMind phases based on
task complexity, then dynamically redistributes savings from phases that
finish under-budget to later phases that may need more resources.

Usage:
    allocator = PhaseBudgetAllocator(total_budget=50000)
    budgets = allocator.allocate(complexity="MODERATE")
    # Phase 1 completes using 800 tokens (allocated 3000)
    allocator.report_actual("analysis", 800)
    # Remaining phases get proportionally more budget
    print(allocator.get_budget("execution"))  # Increased from savings
"""

import logging
import threading
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# Base budget proportions per phase (sum = 1.0)
# These represent the fraction of total budget allocated to each phase
PHASE_PROPORTIONS = {
    "analysis": 0.12,  # Phase 1: Two LLM calls (gemini + claude analysis)
    "debate": 0.15,  # Phase 2: Variable turns of debate
    "architecture": 0.08,  # Phase 3: Architecture generation
    "execution": 0.35,  # Phase 4: Most expensive - actual tool execution
    "diagnosis": 0.12,  # Phase 5: Failure analysis (if needed)
    "retry": 0.08,  # Phase 6: Retry logic (lightweight)
    "consolidation": 0.10,  # Phase 7: Knowledge archival
}

# Complexity multipliers for total budget
COMPLEXITY_MULTIPLIERS = {
    "TRIVIAL": 0.3,
    "SIMPLE": 0.5,
    "MODERATE": 1.0,
    "COMPLEX": 1.5,
    "EXPERT": 2.0,
}

# Phase execution order (for redistribution)
PHASE_ORDER = ["analysis", "debate", "architecture", "execution", "diagnosis", "retry", "consolidation"]


@dataclass
class PhaseBudget:
    """Budget tracking for a single phase."""

    phase: str
    allocated: int  # Initial allocation
    adjusted: int  # After redistributions
    actual: int | None = None  # Actual tokens used
    completed: bool = False

    @property
    def savings(self) -> int:
        """How much was saved (negative means over-budget)."""
        if self.actual is None:
            return 0
        return self.adjusted - self.actual

    @property
    def utilization(self) -> float:
        """Fraction of budget used (0.0 to 1.0+)."""
        if self.actual is None or self.adjusted == 0:
            return 0.0
        return self.actual / self.adjusted


@dataclass
class BudgetReport:
    """Summary report of budget allocation and usage."""

    total_budget: int
    total_allocated: int
    total_spent: int
    total_savings: int
    redistributed: int
    phases: dict[str, PhaseBudget]
    utilization: float  # Overall utilization


class PhaseBudgetAllocator:
    """
    Allocates and dynamically redistributes token budgets across HiveMind phases.

    The allocator pre-distributes a total budget across phases based on
    task complexity. As phases complete, unspent tokens are redistributed
    proportionally to remaining phases, allowing expensive phases (like
    execution) to benefit from savings in cheaper phases.
    """

    def __init__(
        self,
        total_budget: int = 50000,
        proportions: dict[str, float] | None = None,
    ):
        self._total_budget = total_budget
        self._proportions = proportions or PHASE_PROPORTIONS.copy()
        self._budgets: dict[str, PhaseBudget] = {}
        self._redistributed: int = 0
        self._complexity: str = "MODERATE"

    def allocate(self, complexity: str = "MODERATE") -> dict[str, int]:
        """
        Allocate budget across phases based on complexity.

        Args:
            complexity: Task complexity (TRIVIAL, SIMPLE, MODERATE, COMPLEX, EXPERT)

        Returns:
            Dict mapping phase name to allocated token budget
        """
        self._complexity = complexity
        multiplier = COMPLEXITY_MULTIPLIERS.get(complexity, 1.0)
        effective_budget = int(self._total_budget * multiplier)

        self._budgets.clear()
        self._redistributed = 0

        result = {}
        for phase, proportion in self._proportions.items():
            allocated = int(effective_budget * proportion)
            self._budgets[phase] = PhaseBudget(
                phase=phase,
                allocated=allocated,
                adjusted=allocated,
            )
            result[phase] = allocated

        logger.info(
            f"PhaseBudgetAllocator: Allocated {effective_budget} tokens "
            f"({complexity}, multiplier={multiplier}x) across {len(result)} phases"
        )
        return result

    def report_actual(self, phase: str, actual_tokens: int) -> int:
        """
        Report actual token usage for a completed phase.

        Triggers redistribution of savings to remaining phases.

        Args:
            phase: Phase name
            actual_tokens: Actual tokens consumed

        Returns:
            Amount of savings redistributed to remaining phases
        """
        if phase not in self._budgets:
            logger.warning(f"PhaseBudgetAllocator: Unknown phase '{phase}'")
            return 0

        budget = self._budgets[phase]
        budget.actual = actual_tokens
        budget.completed = True

        savings = budget.savings
        if savings <= 0:
            if savings < 0:
                logger.warning(f"PhaseBudgetAllocator: Phase '{phase}' over-budget by {-savings} tokens")
            return 0

        # Redistribute savings to remaining incomplete phases
        remaining = [p for p in PHASE_ORDER if p in self._budgets and not self._budgets[p].completed]

        if not remaining:
            return 0

        # Proportional redistribution based on original proportions
        total_remaining_proportion = sum(self._proportions.get(p, 0) for p in remaining)
        if total_remaining_proportion == 0:
            return 0

        redistributed = 0
        for p in remaining:
            share = self._proportions.get(p, 0) / total_remaining_proportion
            extra = int(savings * share)
            self._budgets[p].adjusted += extra
            redistributed += extra

        self._redistributed += redistributed
        logger.info(
            f"PhaseBudgetAllocator: Phase '{phase}' saved {savings} tokens, "
            f"redistributed {redistributed} to {len(remaining)} remaining phases"
        )
        return redistributed

    def get_budget(self, phase: str) -> int:
        """Get current adjusted budget for a phase."""
        if phase in self._budgets:
            return self._budgets[phase].adjusted
        return 0

    def get_remaining(self, phase: str) -> int:
        """Get remaining budget for a phase (adjusted - actual so far)."""
        if phase not in self._budgets:
            return 0
        budget = self._budgets[phase]
        if budget.actual is not None:
            return max(0, budget.adjusted - budget.actual)
        return budget.adjusted

    def can_afford(self, phase: str, estimated_cost: int) -> bool:
        """Check if a phase can afford an operation."""
        return self.get_remaining(phase) >= estimated_cost

    def get_report(self) -> BudgetReport:
        """Generate a full budget report."""
        total_allocated = sum(b.allocated for b in self._budgets.values())
        total_spent = sum(b.actual or 0 for b in self._budgets.values())
        total_savings = sum(b.savings for b in self._budgets.values() if b.completed)

        return BudgetReport(
            total_budget=self._total_budget,
            total_allocated=total_allocated,
            total_spent=total_spent,
            total_savings=total_savings,
            redistributed=self._redistributed,
            phases=self._budgets.copy(),
            utilization=total_spent / total_allocated if total_allocated > 0 else 0.0,
        )

    def get_stats(self) -> dict:
        """Get allocator statistics."""
        report = self.get_report()
        return {
            "total_budget": report.total_budget,
            "total_allocated": report.total_allocated,
            "total_spent": report.total_spent,
            "total_savings": report.total_savings,
            "redistributed": report.redistributed,
            "utilization": round(report.utilization, 3),
            "complexity": self._complexity,
            "phases_completed": sum(1 for b in self._budgets.values() if b.completed),
            "phases_total": len(self._budgets),
        }

    def reset(self) -> None:
        """Reset allocator state."""
        self._budgets.clear()
        self._redistributed = 0
        self._complexity = "MODERATE"


# Module-level singleton
_allocator: PhaseBudgetAllocator | None = None
_allocator_lock = threading.Lock()


def get_budget_allocator(total_budget: int = 50000) -> PhaseBudgetAllocator:
    """Get or create the global PhaseBudgetAllocator instance."""
    global _allocator
    if _allocator is None:
        with _allocator_lock:
            if _allocator is None:
                _allocator = PhaseBudgetAllocator(total_budget=total_budget)
    return _allocator


def reset_budget_allocator() -> None:
    """Reset the global PhaseBudgetAllocator instance."""
    global _allocator
    _allocator = None
