"""
NEXUS V8.0 - Cost Estimator

Budget control before expensive decisions.
Prevents runaway costs by estimating token usage before operations.

V8.0 Integration: Chains with BudgetTracker for USD limits.
- CostEstimator: Token-level budget (fast, pre-check)
- BudgetTracker: USD-level budget (daily limits, persistence)

Usage:
    estimator = CostEstimator(budget_limit=50000)

    # With BudgetTracker integration
    estimator.set_budget_tracker(budget_tracker)

    if estimator.can_afford("spawn_agent"):
        spawn_agent()
        estimator.record_cost("spawn_agent", actual_tokens)

    if estimator.budget_remaining < 1000:
        escalate_to_user()
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from core.observability.telemetry.budget_tracker import BudgetTracker

logger = logging.getLogger(__name__)

# Token-to-USD conversion (approximate)
# Based on Gemini 3 Pro pricing as baseline: $1.25/1M input, $5/1M output
# Average: ~$3/1M tokens
DEFAULT_USD_PER_MILLION_TOKENS = 3.0


class CostCategory(Enum):
    """Categories of costs."""

    ANALYSIS = "analysis"
    DEBATE = "debate"
    SPAWN = "spawn"
    EXECUTION = "execution"
    DIAGNOSIS = "diagnosis"
    CONSOLIDATION = "consolidation"
    RAG = "rag"
    OTHER = "other"


@dataclass
class CostRecord:
    """Record of a cost incurred."""

    operation: str
    category: CostCategory
    estimated_tokens: int
    actual_tokens: int
    timestamp: datetime = field(default_factory=datetime.now)


class CostEstimator:
    """
    Estimates and tracks token costs for Hive Mind operations.

    Prevents budget overruns by checking before expensive operations.
    """

    # Base costs per operation (in tokens)
    OPERATION_COSTS = {
        # Phase 1: Independent Analysis
        "independent_analysis_gemini": 1500,
        "independent_analysis_claude": 1500,
        "compare_analyses": 500,
        # Phase 2: Debate
        "debate_turn": 1200,
        "check_consensus": 300,
        # Phase 3: Architecture
        "generate_architecture": 800,
        "check_registry": 100,
        "spawn_agent": 600,
        # Phase 4: Execution
        "execution_step": 1000,
        "monitoring_check": 200,
        # Phase 5: Diagnosis
        "failure_diagnosis_gemini": 1000,
        "failure_diagnosis_claude": 1000,
        "synthesize_diagnosis": 500,
        # Phase 6: Retry
        "decide_retry": 400,
        "apply_changes": 300,
        # Phase 7: Consolidation
        "reflection_gemini": 800,
        "reflection_claude": 800,
        "decide_retention": 500,
        "consolidate": 300,
        # RAG
        "rag_retrieval": 200,
        "rag_injection": 500,
        # Breakpoints
        "breakpoint_display": 50,
    }

    # Category mappings
    OPERATION_CATEGORIES = {
        "independent_analysis_gemini": CostCategory.ANALYSIS,
        "independent_analysis_claude": CostCategory.ANALYSIS,
        "compare_analyses": CostCategory.ANALYSIS,
        "debate_turn": CostCategory.DEBATE,
        "check_consensus": CostCategory.DEBATE,
        "generate_architecture": CostCategory.EXECUTION,
        "check_registry": CostCategory.EXECUTION,
        "spawn_agent": CostCategory.SPAWN,
        "execution_step": CostCategory.EXECUTION,
        "monitoring_check": CostCategory.EXECUTION,
        "failure_diagnosis_gemini": CostCategory.DIAGNOSIS,
        "failure_diagnosis_claude": CostCategory.DIAGNOSIS,
        "synthesize_diagnosis": CostCategory.DIAGNOSIS,
        "decide_retry": CostCategory.DIAGNOSIS,
        "apply_changes": CostCategory.DIAGNOSIS,
        "reflection_gemini": CostCategory.CONSOLIDATION,
        "reflection_claude": CostCategory.CONSOLIDATION,
        "decide_retention": CostCategory.CONSOLIDATION,
        "consolidate": CostCategory.CONSOLIDATION,
        "rag_retrieval": CostCategory.RAG,
        "rag_injection": CostCategory.RAG,
    }

    def __init__(
        self,
        budget_limit: int = 50000,
        budget_tracker: Optional["BudgetTracker"] = None,
        usd_per_million_tokens: float = None,
    ):
        """
        Initialize cost estimator.

        Args:
            budget_limit: Maximum tokens to spend (default: 50000)
            budget_tracker: Optional BudgetTracker for USD limit chain
            usd_per_million_tokens: USD per million tokens for conversion
        """
        self.budget_limit = budget_limit
        self.spent = 0
        self.records: list[CostRecord] = []
        self._task_start_spent = 0

        # V8.0: BudgetTracker integration
        self._budget_tracker: BudgetTracker | None = budget_tracker
        self._usd_per_million = usd_per_million_tokens or DEFAULT_USD_PER_MILLION_TOKENS

    def set_budget_tracker(self, tracker: "BudgetTracker"):
        """
        Set the BudgetTracker for USD limit checking.

        Args:
            tracker: BudgetTracker instance
        """
        self._budget_tracker = tracker
        logger.info("CostEstimator linked to BudgetTracker")

    def tokens_to_usd(self, tokens: int) -> float:
        """
        Convert tokens to estimated USD cost.

        Args:
            tokens: Number of tokens

        Returns:
            Estimated cost in USD
        """
        return (tokens / 1_000_000) * self._usd_per_million

    def check_usd_budget(self, tokens: int) -> bool:
        """
        Check if tokens would exceed USD budget.

        V8.0 Integration: Chains CostEstimator -> BudgetTracker

        Args:
            tokens: Tokens to spend

        Returns:
            True if within USD budget (or no tracker set)
        """
        if not self._budget_tracker:
            return True  # No USD tracking, allow

        estimated_usd = self.tokens_to_usd(tokens)
        remaining_usd = self._budget_tracker.get_remaining()

        if estimated_usd > remaining_usd:
            logger.warning(f"USD budget check failed: need ${estimated_usd:.4f}, have ${remaining_usd:.4f}")
            return False

        return True

    def start_task(self):
        """Mark the start of a new task for per-task tracking."""
        self._task_start_spent = self.spent

    @property
    def budget_remaining(self) -> int:
        """Get remaining budget."""
        return max(0, self.budget_limit - self.spent)

    @property
    def task_spent(self) -> int:
        """Get tokens spent on current task."""
        return self.spent - self._task_start_spent

    def estimate_operation(self, operation: str, count: int = 1) -> int:
        """
        Estimate cost of an operation.

        Args:
            operation: Operation name
            count: Number of times to perform

        Returns:
            Estimated token cost
        """
        base_cost = self.OPERATION_COSTS.get(operation, 500)
        return base_cost * count

    def can_afford(self, operation: str, count: int = 1) -> bool:
        """
        Check if operation is affordable.

        V8.0: Now checks both token budget AND USD budget (via BudgetTracker).

        Args:
            operation: Operation name
            count: Number of times to perform

        Returns:
            True if affordable in both token and USD budgets
        """
        cost = self.estimate_operation(operation, count)

        # Check token budget
        token_affordable = (self.spent + cost) <= self.budget_limit
        if not token_affordable:
            logger.warning(f"Cannot afford {operation} x{count} (need {cost} tokens, have {self.budget_remaining})")
            return False

        # V8.0: Also check USD budget if tracker is set
        if not self.check_usd_budget(cost):
            logger.warning(f"Cannot afford {operation} x{count} (USD budget exceeded)")
            return False

        return True

    def can_afford_multiple(self, operations: dict[str, int]) -> bool:
        """
        Check if multiple operations are affordable.

        V8.0: Now checks both token budget AND USD budget.

        Args:
            operations: Dict of {operation: count}

        Returns:
            True if all affordable in both token and USD budgets
        """
        total_cost = sum(self.estimate_operation(op, count) for op, count in operations.items())

        # Check token budget
        if (self.spent + total_cost) > self.budget_limit:
            return False

        # V8.0: Also check USD budget
        return self.check_usd_budget(total_cost)

    def record_cost(self, operation: str, actual_tokens: int, count: int = 1):
        """
        Record actual cost of an operation.

        Args:
            operation: Operation name
            actual_tokens: Actual tokens used
            count: Number of operations
        """
        estimated = self.estimate_operation(operation, count)
        category = self.OPERATION_CATEGORIES.get(operation, CostCategory.OTHER)

        record = CostRecord(
            operation=operation, category=category, estimated_tokens=estimated, actual_tokens=actual_tokens
        )
        self.records.append(record)
        self.spent += actual_tokens

        # Log if actual differs significantly from estimate
        if actual_tokens > estimated * 1.5:
            logger.warning(f"Cost overrun for {operation}: estimated {estimated}, actual {actual_tokens}")

    def reserve(self, operation: str, count: int = 1) -> bool:
        """
        Reserve budget for an operation (pre-commit).

        Args:
            operation: Operation name
            count: Number of operations

        Returns:
            True if reserved successfully
        """
        cost = self.estimate_operation(operation, count)
        if (self.spent + cost) <= self.budget_limit:
            self.spent += cost  # Tentatively add
            return True
        return False

    def release(self, operation: str, count: int = 1):
        """
        Release reserved budget (if operation cancelled).

        Args:
            operation: Operation name
            count: Number of operations
        """
        cost = self.estimate_operation(operation, count)
        self.spent = max(0, self.spent - cost)

    def estimate_full_hive_mind(
        self,
        debate_turns: int = 4,
        spawns: int = 1,
        execution_steps: int = 5,
        with_retry: bool = True,
        with_consolidation: bool = True,
    ) -> int:
        """
        Estimate total cost of a full Hive Mind run.

        Args:
            debate_turns: Expected debate turns
            spawns: Expected agent spawns
            execution_steps: Expected execution steps
            with_retry: Include retry cost
            with_consolidation: Include consolidation cost

        Returns:
            Estimated total tokens
        """
        total = 0

        # Phase 1: Analysis
        total += self.estimate_operation("independent_analysis_gemini")
        total += self.estimate_operation("independent_analysis_claude")
        total += self.estimate_operation("compare_analyses")

        # Phase 2: Debate
        total += self.estimate_operation("debate_turn", debate_turns)
        total += self.estimate_operation("check_consensus", debate_turns)

        # Phase 3: Architecture
        total += self.estimate_operation("generate_architecture")
        total += self.estimate_operation("check_registry")
        total += self.estimate_operation("spawn_agent", spawns)

        # Phase 4: Execution
        total += self.estimate_operation("execution_step", execution_steps)
        total += self.estimate_operation("monitoring_check", execution_steps)

        # Phase 5-6: Diagnosis + Retry (if enabled)
        if with_retry:
            total += self.estimate_operation("failure_diagnosis_gemini")
            total += self.estimate_operation("failure_diagnosis_claude")
            total += self.estimate_operation("decide_retry")
            total += self.estimate_operation("apply_changes")

        # Phase 7: Consolidation (if enabled)
        if with_consolidation:
            total += self.estimate_operation("reflection_gemini")
            total += self.estimate_operation("reflection_claude")
            total += self.estimate_operation("decide_retention")
            total += self.estimate_operation("consolidate")

        return total

    def would_exceed_budget(self, debate_turns: int = 4, spawns: int = 1, execution_steps: int = 5) -> bool:
        """
        Check if a full Hive Mind run would exceed budget.

        Returns:
            True if would exceed
        """
        estimated = self.estimate_full_hive_mind(
            debate_turns=debate_turns, spawns=spawns, execution_steps=execution_steps
        )
        return (self.spent + estimated) > self.budget_limit

    def get_category_breakdown(self) -> dict[str, int]:
        """Get cost breakdown by category."""
        breakdown = {cat.value: 0 for cat in CostCategory}

        for record in self.records:
            breakdown[record.category.value] += record.actual_tokens

        return breakdown

    def get_stats(self) -> dict:
        """Get cost statistics including USD integration."""
        breakdown = self.get_category_breakdown()

        stats = {
            "budget_limit": self.budget_limit,
            "total_spent": self.spent,
            "budget_remaining": self.budget_remaining,
            "task_spent": self.task_spent,
            "utilization_percent": round(self.spent / self.budget_limit * 100, 1),
            "operations_count": len(self.records),
            "category_breakdown": breakdown,
            "average_cost_per_operation": (round(self.spent / len(self.records), 1) if self.records else 0),
        }

        # V8.0: Add USD stats if tracker is linked
        if self._budget_tracker:
            usd_stats = self._budget_tracker.get_stats()
            stats["usd_integration"] = {
                "linked": True,
                "estimated_usd_spent": round(self.tokens_to_usd(self.spent), 4),
                "budget_tracker_spent_today": usd_stats.get("spent_today_usd", 0),
                "budget_tracker_remaining": usd_stats.get("remaining_usd", 0),
                "budget_tracker_warning": usd_stats.get("warning_level"),
            }
        else:
            stats["usd_integration"] = {"linked": False}

        return stats

    def reset_for_new_session(self):
        """Reset for a new session (keeps records for analysis)."""
        self.spent = 0
        self._task_start_spent = 0

    def hard_reset(self):
        """Complete reset (clears all records)."""
        self.spent = 0
        self._task_start_spent = 0
        self.records = []
