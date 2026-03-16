"""
NEXUS V8.0 - Phase 6: Adaptive Retry

Applies changes from diagnosis and retries execution.
Uses Strategy Blacklist to prevent circular retries.

Flow:
1. Check if strategy is blacklisted
2. Apply recommended changes to architecture
3. Retry execution (back to Phase 4)
4. If still fails -> blacklist strategy, suggest escalation

Key Features:
- Blacklist prevents trying same failing approach
- Changes are applied incrementally
- Max retry limit to prevent infinite loops
- Escalation to user when stuck
"""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..context_manager import HiveMindContextManager
from ..cost_estimator import CostEstimator
from ..strategy_blacklist import FailureCategory, StrategyBlacklist
from ..types import (
    AgentArchitecture,
    AgentSpec,
    FailureDiagnosis,
    FailureType,
    RetryDecision,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class RetryPhaseResult:
    """Result of Phase 6."""

    decision: RetryDecision
    modified_architecture: AgentArchitecture | None
    retry_count: int
    blacklisted: bool


class AdaptiveRetryPhase:
    """
    Phase 6: Adaptive Retry

    Applies changes and retries with anti-circular protection.
    """

    # Max retries before escalation
    MAX_RETRIES = 3

    # Failure type to blacklist category mapping
    FAILURE_TO_BLACKLIST = {
        FailureType.TIMEOUT: FailureCategory.TIMEOUT,
        FailureType.CAPABILITY_MISSING: FailureCategory.CAPABILITY_MISSING,
        FailureType.HALLUCINATION: FailureCategory.HALLUCINATION,
        FailureType.STRATEGY_WRONG: FailureCategory.WRONG_APPROACH,
        FailureType.TOOL_ERROR: FailureCategory.TOOL_ERROR,
        FailureType.CONTEXT_LOST: FailureCategory.RESOURCE_EXCEEDED,
        FailureType.BUDGET_EXCEEDED: FailureCategory.RESOURCE_EXCEEDED,
        FailureType.MEMORY_ERROR: FailureCategory.RESOURCE_EXCEEDED,
        FailureType.PLANNING_ERROR: FailureCategory.WRONG_APPROACH,
        FailureType.UNKNOWN: FailureCategory.UNKNOWN,
    }

    def __init__(
        self, cost_estimator: CostEstimator, context_manager: HiveMindContextManager, blacklist: StrategyBlacklist
    ):
        """
        Initialize Phase 6.

        Args:
            cost_estimator: Cost estimator
            context_manager: Context manager
            blacklist: Strategy blacklist
        """
        self.cost_estimator = cost_estimator
        self.context_manager = context_manager
        self.blacklist = blacklist
        self._retry_count = 0

    def execute(
        self,
        diagnosis: FailureDiagnosis,
        current_architecture: AgentArchitecture,
        recommendations: dict[str, Any],
        user_decision: str,
    ) -> RetryPhaseResult:
        """
        Execute Phase 6: Adaptive Retry.

        Args:
            diagnosis: Diagnosis from Phase 5
            current_architecture: Current architecture
            recommendations: Retry recommendations
            user_decision: User's decision (retry, escalate, abort)

        Returns:
            RetryPhaseResult with decision and modified architecture
        """
        logger.info(f"Phase 6: Adaptive Retry (attempt {self._retry_count + 1})")

        # Check user decision
        if user_decision == "abort":
            return RetryPhaseResult(
                decision=RetryDecision(action="STOP", reason="User chose to abort"),
                modified_architecture=None,
                retry_count=self._retry_count,
                blacklisted=False,
            )

        if user_decision == "escalate":
            return RetryPhaseResult(
                decision=RetryDecision(action="ESCALATE", reason="User requested escalation"),
                modified_architecture=None,
                retry_count=self._retry_count,
                blacklisted=False,
            )

        # Check retry limit
        self._retry_count += 1
        if self._retry_count > self.MAX_RETRIES:
            logger.warning(f"Max retries ({self.MAX_RETRIES}) reached")
            return RetryPhaseResult(
                decision=RetryDecision(
                    action="ESCALATE",
                    reason=f"Max retries ({self.MAX_RETRIES}) exceeded",
                    suggestion="Consider breaking task into smaller parts",
                ),
                modified_architecture=None,
                retry_count=self._retry_count,
                blacklisted=True,
            )

        # Check budget for retry
        if not self.cost_estimator.can_afford("decide_retry"):
            return RetryPhaseResult(
                decision=RetryDecision(action="STOP", reason="Budget exceeded for retry"),
                modified_architecture=None,
                retry_count=self._retry_count,
                blacklisted=False,
            )

        # Check blacklist
        strategy_desc = self._describe_strategy(current_architecture, diagnosis)
        blacklisted_entry = self.blacklist.is_blacklisted(strategy_desc)

        if blacklisted_entry:
            # Strategy already failed - get alternatives
            alternatives = self.blacklist.suggest_alternatives(strategy_desc, task_context=str(diagnosis.root_cause))

            return RetryPhaseResult(
                decision=RetryDecision(
                    action="ESCALATE",
                    reason=f"Strategy blacklisted (failed {blacklisted_entry.attempt_count} times)",
                    suggestion=alternatives[0] if alternatives else "Try a different approach",
                ),
                modified_architecture=None,
                retry_count=self._retry_count,
                blacklisted=True,
            )

        # Apply changes and retry
        try:
            modified_arch = self._apply_changes(current_architecture, diagnosis, recommendations)

            # Record cost
            self.cost_estimator.record_cost("decide_retry", 400)
            self.cost_estimator.record_cost("apply_changes", 300)

            # Calculate expected improvement
            expected_improvement = self._estimate_improvement(diagnosis, recommendations)

            return RetryPhaseResult(
                decision=RetryDecision(
                    action="RETRY",
                    reason=f"Applying {len(diagnosis.recommended_changes)} changes",
                    new_architecture=modified_arch,
                    changes_made=diagnosis.recommended_changes[:5],  # Top 5
                    expected_improvement=expected_improvement,
                ),
                modified_architecture=modified_arch,
                retry_count=self._retry_count,
                blacklisted=False,
            )

        except Exception as e:
            logger.error(f"Failed to apply changes: {e}")

            # Blacklist this strategy
            self._add_to_blacklist(strategy_desc, diagnosis)

            return RetryPhaseResult(
                decision=RetryDecision(action="ESCALATE", reason=f"Could not apply changes: {e}"),
                modified_architecture=None,
                retry_count=self._retry_count,
                blacklisted=True,
            )

    def _describe_strategy(self, architecture: AgentArchitecture, diagnosis: FailureDiagnosis) -> str:
        """Create a description of the current strategy for blacklisting."""
        parts = [
            f"mode:{architecture.collaboration_mode}",
            f"agents:{','.join(architecture.agents_to_use)}",
            f"steps:{len(architecture.execution_plan.steps)}",
            f"approach:{architecture.reasoning[:100]}" if architecture.reasoning else "",
        ]
        return " | ".join(p for p in parts if p)

    def _apply_changes(
        self, architecture: AgentArchitecture, diagnosis: FailureDiagnosis, recommendations: dict[str, Any]
    ) -> AgentArchitecture:
        """Apply recommended changes to architecture."""
        arch_changes = recommendations.get("architecture_changes", {})

        # Clone architecture (simple copy for now)
        modified = AgentArchitecture(
            status=architecture.status,
            collaboration_mode=architecture.collaboration_mode,
            agents_to_use=architecture.agents_to_use.copy(),
            agents_to_spawn=architecture.agents_to_spawn.copy(),
            rag_config=architecture.rag_config,
            execution_plan=architecture.execution_plan,
            spawn_commands=architecture.spawn_commands.copy(),
            estimated_cost=architecture.estimated_cost,
            reasoning=architecture.reasoning,
        )

        # Apply changes based on failure type
        if arch_changes.get("increase_timeout"):
            # Increase step timeouts
            for step in modified.execution_plan.steps:
                step.expected_duration = int(step.expected_duration * 1.5)

        if arch_changes.get("spawn_specialist"):
            # Add specialist agent to spawn
            capability = arch_changes.get("capability_needed", "specialist")
            modified.agents_to_spawn.append(
                AgentSpec(
                    role=f"{capability}_specialist",
                    mission=f"Handle {capability} tasks",
                    capabilities=[capability],
                    spawn_if_missing=True,
                )
            )
            modified.status = "SPAWN_REQUIRED"

        if arch_changes.get("add_verification"):
            # Add verification to all steps
            for step in modified.execution_plan.steps:
                step.verification_required = True

        if arch_changes.get("simplify_steps") and len(modified.execution_plan.steps) > 2:
            # Keep only essential steps (first and last)
            modified.execution_plan.steps = [modified.execution_plan.steps[0], modified.execution_plan.steps[-1]]

        if arch_changes.get("rethink_approach"):
            # Change collaboration mode
            modes = ["sequential", "parallel", "pipeline"]
            current_idx = modes.index(modified.collaboration_mode) if modified.collaboration_mode in modes else 0
            modified.collaboration_mode = modes[(current_idx + 1) % len(modes)]

        if arch_changes.get("reduce_context"):
            # Reduce RAG depth
            if modified.rag_config.depth == "deep":
                modified.rag_config.depth = "standard"
            elif modified.rag_config.depth == "standard":
                modified.rag_config.depth = "shallow"

        # V12.4: CONTEXT_LOST / MEMORY_ERROR recovery via ContextCompressor
        if arch_changes.get("compress_context") or arch_changes.get("fresh_session"):
            try:
                from core.memory_pkg.memory.context_compressor import get_compressor

                compressor = get_compressor()
                if compressor.should_compress():
                    result = compressor.compress()
                    logger.info(
                        f"Context compressed: {result.turns_pruned} turns pruned, "
                        f"{result.compression_ratio:.0%} reduction"
                    )
            except Exception as e:
                logger.debug(f"Context compression failed: {e}")

        # Update reasoning
        changes_desc = ", ".join(diagnosis.recommended_changes[:3])
        modified.reasoning = f"Retry after: {changes_desc}"

        return modified

    def _estimate_improvement(self, diagnosis: FailureDiagnosis, recommendations: dict[str, Any]) -> float:
        """Estimate expected improvement from changes."""
        base_improvement = 0.3  # Base 30% improvement expectation

        # Higher confidence diagnosis = better improvement estimate
        base_improvement += diagnosis.confidence * 0.2

        # More specific changes = better improvement
        if diagnosis.recommended_changes:
            base_improvement += min(len(diagnosis.recommended_changes) * 0.05, 0.2)

        # Cap at 80%
        return min(base_improvement, 0.8)

    def _add_to_blacklist(self, strategy_desc: str, diagnosis: FailureDiagnosis):
        """Add failed strategy to blacklist."""
        category = self.FAILURE_TO_BLACKLIST.get(diagnosis.failure_type, FailureCategory.UNKNOWN)

        self.blacklist.add_failed_strategy(
            strategy=strategy_desc,
            failure_reason=diagnosis.root_cause,
            diagnosis=str(diagnosis.to_dict()),
            failure_category=category,
            tags=[diagnosis.failure_type.value],
        )

        logger.info(f"Added strategy to blacklist: {strategy_desc[:50]}...")

    def mark_success(self, architecture: AgentArchitecture, diagnosis: FailureDiagnosis | None):
        """Mark a strategy as successful (remove from blacklist if present)."""
        if diagnosis:
            strategy_desc = self._describe_strategy(architecture, diagnosis)
            self.blacklist.mark_success(strategy_desc)

    def reset_retry_count(self):
        """Reset retry count for new task."""
        self._retry_count = 0

    def get_retry_stats(self) -> dict[str, Any]:
        """Get retry statistics."""
        return {
            "current_retry_count": self._retry_count,
            "max_retries": self.MAX_RETRIES,
            "blacklist_stats": self.blacklist.get_stats(),
        }
