"""
V8.3 SwarmBridge - Hive Mind -> Swarm Delegation

Enables "Dictator Mode" where HiveMind commands Swarm execution.
HiveMind acts as the strategist, Swarm as the tactician.

Usage:
    bridge = SwarmBridge(swarm_engine, context_manager)
    result = await bridge.delegate(
        task="Run security review",
        mode=CollaborationMode.RED_BLUE,
        phase=HivePhase.DIAGNOSIS
    )
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.intelligence.swarm.collaboration_modes import CollaborationMode


# V9.3 ISSUE-008: Exception for exhausted fallback chains (no more silent failures)
class FallbackExhaustedError(Exception):
    """
    Raised when all fallback modes have been exhausted without success.

    V9.3: Replaces silent `return None` to make failures explicit and traceable.
    Callers can catch this to handle graceful degradation or escalation.
    """

    def __init__(self, modes_tried: list[CollaborationMode], task: str, last_result: Any = None):
        self.modes_tried = modes_tried
        self.task = task
        self.last_result = last_result
        modes_str = " -> ".join(m.value for m in modes_tried)
        super().__init__(f"All fallback modes exhausted ({modes_str}). Task: {task[:100]}...")


# V8.8 (GROK-004): Adaptive fallback selection
try:
    from core.intelligence.swarm.adaptive_fallback import (
        FallbackContext,
        get_adaptive_fallback_selector,
    )

    ADAPTIVE_FALLBACK_AVAILABLE = True
except ImportError:
    ADAPTIVE_FALLBACK_AVAILABLE = False
    FallbackContext = None

logger = logging.getLogger(__name__)


# =============================================================================
# HIVE PHASES (for mode validation)
# =============================================================================


class HivePhase(Enum):
    """
    Logical phases of HiveMind execution.

    Mapped from HiveMindState for mode validation.
    """

    ANALYSIS = "analysis"
    DEBATE = "debate"
    ARCHITECTURE = "architecture"
    EXECUTION = "execution"
    DIAGNOSIS = "diagnosis"
    CONSOLIDATION = "consolidation"


# =============================================================================
# DELEGATION RESULT
# =============================================================================


@dataclass
class SwarmDelegationResult:
    """
    Result of a Swarm delegation from HiveMind.

    Provides diagnostic information for failure analysis.
    """

    success: bool
    result: Any
    mode_used: CollaborationMode
    fallback_chain: list[CollaborationMode] = field(default_factory=list)
    failure_diagnostics: list[str] = field(default_factory=list)
    execution_time: float = 0.0
    summary: str = ""

    def to_dict(self) -> dict:
        """Serialize for logging/persistence."""
        return {
            "success": self.success,
            "mode_used": self.mode_used.value,
            "fallback_chain": [m.value for m in self.fallback_chain],
            "failure_diagnostics": self.failure_diagnostics,
            "execution_time": self.execution_time,
            "summary": self.summary[:200] if self.summary else "",
        }


# =============================================================================
# SWARM BRIDGE
# =============================================================================


class SwarmBridge:
    """
    Bridge between HiveMind (strategist) and Swarm (tactician).

    Responsibilities:
    1. Validate mode selection per phase (guardrails)
    2. Extract relevant context for Swarm
    3. Execute delegation to Swarm Engine
    4. Inject results back into HiveMind context

    V8.3 "Dictator Mode": HiveMind decides WHEN and WHAT mode to use,
    Swarm executes tactically.
    """

    # Guardrails: Which modes are allowed per phase
    # Total: 9 valid combinations (not 6^6 = 46656)
    ALLOWED_MODES: dict[HivePhase, list[CollaborationMode]] = {
        HivePhase.ANALYSIS: [CollaborationMode.SPECIALIST],
        HivePhase.DEBATE: [CollaborationMode.PING_PONG, CollaborationMode.RED_BLUE],
        HivePhase.ARCHITECTURE: [CollaborationMode.LEAD_SUPPORT],
        HivePhase.EXECUTION: [CollaborationMode.PARALLEL, CollaborationMode.SEQUENTIAL, CollaborationMode.SPECIALIST],
        HivePhase.DIAGNOSIS: [CollaborationMode.RED_BLUE],
        HivePhase.CONSOLIDATION: [CollaborationMode.SPECIALIST],
    }

    def __init__(self, swarm_engine: Any = None, context_manager: Any = None, success_memory: Any = None):
        """
        Initialize SwarmBridge.

        Args:
            swarm_engine: HybridSwarmEngine instance (lazy import to avoid circular)
            context_manager: HiveMindContextManager for context transfer
            success_memory: V8.3.2 - SuccessMemory instance for feedback loop
        """
        self.swarm = swarm_engine
        self.context = context_manager
        self.success_memory = success_memory  # V8.3.2: FG-001 fix

    async def delegate(
        self,
        task: str,
        mode: CollaborationMode,
        phase: HivePhase | None = None,
        context_categories: list[str] | None = None,
        config: dict | None = None,
        task_id: str | None = None,
    ) -> SwarmDelegationResult:
        """
        Delegate a subtask to the Swarm Engine.

        Args:
            task: The subtask to execute
            mode: Requested collaboration mode
            phase: Current HiveMind phase (for validation)
            context_categories: Which context categories to include
            config: Additional Swarm configuration
            task_id: Optional task ID for checkpoint support (V8.3.1)

        Returns:
            SwarmDelegationResult with success/failure and diagnostics
        """
        start_time = time.time()

        # 1. Validate mode if phase specified
        if phase is not None:
            validation_result = self._validate_mode_for_phase(mode, phase)
            if not validation_result["valid"]:
                return SwarmDelegationResult(
                    success=False,
                    result=None,
                    mode_used=mode,
                    failure_diagnostics=validation_result["reasons"],
                    execution_time=time.time() - start_time,
                )

        # 2. Check Swarm Engine availability
        if self.swarm is None:
            return SwarmDelegationResult(
                success=False,
                result=None,
                mode_used=mode,
                failure_diagnostics=["SwarmBridge: No Swarm Engine configured"],
                execution_time=time.time() - start_time,
            )

        # 3. Extract context for Swarm
        blackboard = {}
        if self.context is not None:
            blackboard = self._extract_context(context_categories)

        # 4. Execute via Swarm
        fallback_chain = []
        current_mode = mode

        try:
            # Attempt execution with fallback
            # V8.3.1: Generate task_id if not provided for checkpoint support
            effective_task_id = task_id
            if effective_task_id is None:
                import uuid

                effective_task_id = f"swarm_delegate_{uuid.uuid4().hex[:8]}"

            result = await self._execute_with_fallback(
                task=task,
                mode=current_mode,
                blackboard=blackboard,
                config=config or {},
                fallback_chain=fallback_chain,
                task_id=effective_task_id,
            )

            execution_time = time.time() - start_time

            # Determine success
            success = self._is_success(result)
            final_mode = fallback_chain[-1] if fallback_chain else mode

            delegation_result = SwarmDelegationResult(
                success=success,
                result=result,
                mode_used=final_mode,
                fallback_chain=fallback_chain,
                execution_time=execution_time,
                summary=self._summarize_result(result),
            )

            # V8.3.2 FG-001: Record successful delegations in SuccessMemory
            if success and self.success_memory is not None:
                self._record_delegation_success(
                    task=task,
                    mode_used=final_mode,
                    execution_time=execution_time,
                    fallback_count=len(fallback_chain) - 1 if fallback_chain else 0,
                )

            return delegation_result

        except Exception as e:
            logger.error(f"SwarmBridge delegation failed: {e}")
            return SwarmDelegationResult(
                success=False,
                result=None,
                mode_used=mode,
                fallback_chain=fallback_chain,
                failure_diagnostics=[str(e)],
                execution_time=time.time() - start_time,
            )

    async def _execute_with_fallback(
        self,
        task: str,
        mode: CollaborationMode,
        blackboard: dict,
        config: dict,
        fallback_chain: list[CollaborationMode],
        max_fallbacks: int = 2,
        task_id: str | None = None,
    ) -> Any:
        """
        Execute Swarm mode with fallback chain.

        Uses CollaborationMode.fallback_mode property for graceful degradation.

        V8.3.1: Aligned with ModeExecutor.execute_with_fallback() for full
        self-healing support with checkpoint create/restore.
        """
        current_mode = mode
        attempts = 0
        last_error = None
        checkpoint_id = None

        # V8.3.1: Create checkpoint before attempting execution
        if task_id and self.swarm and hasattr(self.swarm, "session_manager"):
            try:
                checkpoint_id = self.swarm.session_manager.create_checkpoint(task_id)
                logger.debug(f"SwarmBridge: Created checkpoint {checkpoint_id}")
            except Exception as e:
                logger.warning(f"SwarmBridge: Checkpoint creation failed: {e}")
                checkpoint_id = None

        while current_mode is not None and attempts <= max_fallbacks:
            fallback_chain.append(current_mode)

            try:
                # Execute via Swarm Engine
                result = await self._call_swarm(task, current_mode, blackboard, config)

                # Check if result is acceptable
                if self._is_success(result):
                    # V8.3.1: Mark as recovered if we fell back
                    if attempts > 0 and hasattr(result, "metadata"):
                        result.metadata["status"] = "RECOVERED"
                        result.metadata["fallback_count"] = attempts
                        result.metadata["original_mode"] = mode.value
                    return result

                # Result not successful, try fallback
                logger.warning(f"SwarmBridge: Mode {current_mode.value} did not succeed, trying fallback")

            except Exception as e:
                logger.warning(f"SwarmBridge: Mode {current_mode.value} failed with {e}, trying fallback")
                last_error = e

            # V8.3.1: Restore checkpoint before trying fallback
            if checkpoint_id and self.swarm and hasattr(self.swarm, "session_manager"):
                try:
                    self.swarm.session_manager.restore_checkpoint(task_id, checkpoint_id)
                    logger.debug(f"SwarmBridge: Restored checkpoint {checkpoint_id}")
                except Exception as e:
                    logger.warning(f"SwarmBridge: Checkpoint restore failed: {e}")

            # V8.8 (GROK-004): Get adaptive fallback based on context
            if ADAPTIVE_FALLBACK_AVAILABLE:
                selector = get_adaptive_fallback_selector()
                context = FallbackContext(
                    domains=config.get("domains", []),
                    complexity=config.get("complexity", "moderate"),
                    raw_input=task,
                    modes_tried=[m.value for m in fallback_chain],
                    errors_encountered=[str(last_error)] if last_error else [],
                )
                decision = selector.get_adaptive_fallback(current_mode, context)
                current_mode = decision.fallback_mode
                if decision.skip_intermediate:
                    logger.info(f"SwarmBridge: Adaptive skip to {current_mode.value}: {decision.reason}")
                elif current_mode:
                    logger.debug(f"SwarmBridge: Adaptive fallback to {current_mode.value}: {decision.reason}")
            else:
                # Static fallback chain
                current_mode = current_mode.fallback_mode
            attempts += 1

        # V9.3 ISSUE-008: All fallbacks exhausted - raise explicit exception
        # BEFORE: Silent `return None` caused caller to not detect failure
        # AFTER: Explicit exception enables proper error handling and diagnosis
        if last_error:
            raise last_error

        raise FallbackExhaustedError(modes_tried=fallback_chain, task=task, last_result=None)

    async def _call_swarm(self, task: str, mode: CollaborationMode, blackboard: dict, config: dict) -> Any:
        """
        Make the actual call to Swarm Engine.

        Handles different Swarm Engine API patterns.
        """
        # Try different method signatures
        if hasattr(self.swarm, "execute_swarm_mode"):
            return await self.swarm.execute_swarm_mode(task=task, mode=mode, initial_blackboard=blackboard, **config)
        elif hasattr(self.swarm, "execute"):
            return await self.swarm.execute(task=task, mode=mode.value, blackboard=blackboard, **config)
        else:
            raise NotImplementedError("SwarmBridge: Swarm Engine has no compatible execute method")

    def _validate_mode_for_phase(self, mode: CollaborationMode, phase: HivePhase) -> dict[str, Any]:
        """
        Validate that the requested mode is allowed for the given phase.

        Returns:
            Dict with "valid" bool and "reasons" list
        """
        allowed = self.ALLOWED_MODES.get(phase, [])

        if mode in allowed:
            return {"valid": True, "reasons": []}

        return {
            "valid": False,
            "reasons": [
                f"Mode {mode.value} not allowed in phase {phase.value}",
                f"Allowed modes: {[m.value for m in allowed]}",
            ],
        }

    def _extract_context(self, categories: list[str] | None = None) -> dict:
        """
        Extract relevant context from HiveMind for Swarm.

        Uses dedicated "swarm_delegation" budget to avoid token dilution.
        """
        if self.context is None:
            return {}

        # Use context manager's get_context_for if available
        if hasattr(self.context, "get_context_for"):
            try:
                return self.context.get_context_for(
                    operation="swarm_delegation",
                    include_categories=categories or ["task", "architecture", "tools"],
                    exclude_categories=["chat_history"],
                )
            except Exception as e:
                logger.warning(f"SwarmBridge: Context extraction failed: {e}")
                return {}

        # Fallback: return raw context if dict-like
        if hasattr(self.context, "to_dict"):
            return self.context.to_dict()

        return {}

    def _is_success(self, result: Any) -> bool:
        """Determine if Swarm result is successful."""
        if result is None:
            return False
        if hasattr(result, "success"):
            return bool(result.success)
        if hasattr(result, "status"):
            return result.status in ("success", "completed", "done")
        if isinstance(result, dict):
            return result.get("success", False) or result.get("status") == "success"
        # Non-None result assumed successful
        return True

    def _record_delegation_success(
        self, task: str, mode_used: CollaborationMode, execution_time: float, fallback_count: int = 0
    ) -> None:
        """
        V8.3.2 FG-001: Record successful delegation in SuccessMemory.

        This closes the feedback loop so the system learns which
        Swarm modes work best for different types of delegated tasks.
        """
        try:
            from core.intelligence.hive_mind.success_adapter import create_swarm_delegation_adapters

            analysis, result_adapter = create_swarm_delegation_adapters(
                task=task,
                mode_used=mode_used.value,
                duration=execution_time,
                success=True,
                fallback_count=fallback_count,
            )

            # Generate unique task ID for this delegation
            import uuid

            task_id = f"delegation_{uuid.uuid4().hex[:8]}"

            # Compute quality score (penalize fallbacks)
            quality_score = max(0.5, 1.0 - (fallback_count * 0.15))

            self.success_memory.record_success(
                task_id=task_id, analysis=analysis, result=result_adapter, quality_score=quality_score
            )

            logger.debug(
                f"SwarmBridge: Recorded delegation success (mode={mode_used.value}, quality={quality_score:.2f})"
            )

        except Exception as e:
            # Don't fail the delegation just because memory recording failed
            logger.warning(f"SwarmBridge: Failed to record success: {e}")

    def _summarize_result(self, result: Any) -> str:
        """Create summary for injection back into HiveMind context."""
        if result is None:
            return ""

        # Try various result formats
        if hasattr(result, "final_response"):
            return str(result.final_response)[:500]
        if hasattr(result, "output"):
            return str(result.output)[:500]
        if hasattr(result, "summary"):
            return str(result.summary)[:500]
        if isinstance(result, dict):
            return str(result.get("response", result.get("output", "")))[:500]

        return str(result)[:500]

    def inject_results_into_context(self, delegation_result: SwarmDelegationResult) -> bool:
        """
        Inject Swarm results back into HiveMind context.

        Args:
            delegation_result: Result from delegate() call

        Returns:
            True if injection successful
        """
        if self.context is None:
            return False

        if not hasattr(self.context, "add_entry"):
            logger.warning("SwarmBridge: Context has no add_entry method")
            return False

        try:
            # Use HIGH priority so results aren't easily evicted
            self.context.add_entry(
                category="swarm_results",
                content=delegation_result.summary,
                priority="HIGH",  # Or ContextPriority.HIGH if enum
            )
            return True
        except Exception as e:
            logger.warning(f"SwarmBridge: Result injection failed: {e}")
            return False

    @classmethod
    def get_allowed_modes(cls, phase: HivePhase) -> list[CollaborationMode]:
        """Get allowed modes for a phase."""
        return cls.ALLOWED_MODES.get(phase, [])

    @classmethod
    def get_all_valid_combinations(cls) -> list[tuple]:
        """
        Get all valid (phase, mode) combinations.

        Returns:
            List of (HivePhase, CollaborationMode) tuples
        """
        combinations = []
        for phase, modes in cls.ALLOWED_MODES.items():
            for mode in modes:
                combinations.append((phase, mode))
        return combinations


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def create_bridge_for_phase(phase: HivePhase, swarm_engine: Any = None, context_manager: Any = None) -> SwarmBridge:
    """
    Factory function to create a SwarmBridge for a specific phase.

    Args:
        phase: The HiveMind phase
        swarm_engine: Optional Swarm Engine instance
        context_manager: Optional Context Manager instance

    Returns:
        Configured SwarmBridge instance
    """
    return SwarmBridge(swarm_engine=swarm_engine, context_manager=context_manager)


def suggest_mode_for_subtask(subtask: str, phase: HivePhase) -> CollaborationMode | None:
    """
    Suggest a collaboration mode for a subtask based on keywords.

    Args:
        subtask: The subtask description
        phase: Current HiveMind phase

    Returns:
        Suggested CollaborationMode or None if no delegation needed
    """
    allowed = SwarmBridge.ALLOWED_MODES.get(phase, [])
    if not allowed:
        return None

    subtask_lower = subtask.lower()

    # Keyword-based heuristics
    if CollaborationMode.PARALLEL in allowed and any(
        kw in subtask_lower for kw in ["parallel", "simultaneous", "concurrent", "multiple"]
    ):
        return CollaborationMode.PARALLEL

    if CollaborationMode.RED_BLUE in allowed and any(
        kw in subtask_lower for kw in ["review", "security", "audit", "critique", "attack"]
    ):
        return CollaborationMode.RED_BLUE

    if CollaborationMode.PING_PONG in allowed and any(
        kw in subtask_lower for kw in ["brainstorm", "iterate", "refine", "debate"]
    ):
        return CollaborationMode.PING_PONG

    if CollaborationMode.LEAD_SUPPORT in allowed and any(
        kw in subtask_lower for kw in ["lead", "assist", "support", "help"]
    ):
        return CollaborationMode.LEAD_SUPPORT

    if CollaborationMode.SEQUENTIAL in allowed and any(
        kw in subtask_lower for kw in ["then", "after", "sequence", "sequential", "pipeline"]
    ):
        return CollaborationMode.SEQUENTIAL

    # Default: None (don't delegate)
    return None
