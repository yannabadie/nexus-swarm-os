"""
SagaManager - Checkpoint and Recovery System for HiveMind Pipeline.

NEXUS V8.4.4 - Blind Spot Remediation Phase 2

This module provides the Saga Pattern implementation for HiveMind's 7-phase
pipeline. It enables:
- Phase checkpoints with atomic disk persistence
- Context snapshot and restoration (prevents context bleeding)
- Compensating transactions for rollback
- Crash recovery via AtomicJsonStore

Key Innovation (from external critique):
- On rollback, we truncate conversation history to prevent "hallucination"
  about events that didn't happen after rollback.

Architecture:
    SagaManager
    +-- checkpoint_phase(phase, result, state, context_index)
    +-- rollback_to(phase) -> runs compensations + truncates context
    +-- resume_from(task_id) -> recovers from disk after crash
    +-- get_checkpoint(phase)

Storage Layout:
    workspace/.nexus/sagas/{task_id}.json
    +-- task_id: str
    +-- checkpoints: {phase_name: PhaseCheckpoint}
    +-- recovery_point: str (last successful phase)
    +-- created_at: str (ISO timestamp)

Author: Claude (NEXUS V8.4.4)
Date: 2025-12-10
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.utils.atomic_store import AtomicJsonStore
from core.utils.serialization import serialize_for_checkpoint

if TYPE_CHECKING:
    from core.intelligence.hive_mind.types import HiveMindState


logger = logging.getLogger(__name__)


# V12.4.1 Epic 1.3: Redis integration for durable sagas
def get_redis_bus():
    """Lazy import of Redis bus to avoid circular dependencies."""
    try:
        from core.observability.events.redis_bus import RedisEventBus

        return RedisEventBus()
    except ImportError:
        return None


# =============================================================================
# PHASE DEFINITIONS
# =============================================================================

# Ordered phases for rollback traversal
PHASE_ORDER = [
    "analysis",
    "debate",
    "architecture",
    "execution",
    "diagnosis",
    "retry",
    "consolidation",
]

# Guards: conditions that must be true to enter a phase
PHASE_GUARDS = {
    "debate": lambda ctx: ctx.get("analysis_complete", False),
    "architecture": lambda ctx: (
        ctx.get("debate_complete", False) or ctx.get("debate_skipped", False) or ctx.get("immediate_consensus", False)
    ),
    "execution": lambda ctx: ctx.get("architecture_approved", False),
    "diagnosis": lambda ctx: ctx.get("execution_failed", False),
    "retry": lambda ctx: ctx.get("diagnosis_complete", False),
    "consolidation": lambda ctx: (ctx.get("execution_complete", False) or ctx.get("retry_exhausted", False)),
}


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class PhaseCheckpoint:
    """
    Checkpoint data for a single HiveMind phase.

    Attributes:
        phase: Phase name (analysis, debate, architecture, etc.)
        result: Serialized phase result (via to_dict() or serialize_for_checkpoint)
        state: HiveMindState value at checkpoint time
        timestamp: When checkpoint was created
        context_index: Index in conversation history (for rollback truncation)
        compensation_name: Name of compensation function to run on rollback
        conversation_summary: V10 FIX F10 - Compressed conversation for LLM context restoration
        agent_states: V10 FIX F10 - Per-agent state snapshots
    """

    phase: str
    result: dict[str, Any]
    state: str  # HiveMindState.value
    timestamp: datetime
    context_index: int = 0
    compensation_name: str | None = None
    # V10 FIX F10: LLM context restoration support
    conversation_summary: str | None = None
    agent_states: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize checkpoint to dict for JSON storage."""
        data = {
            "phase": self.phase,
            "result": self.result,
            "state": self.state,
            "timestamp": self.timestamp.isoformat(),
            "context_index": self.context_index,
            "compensation_name": self.compensation_name,
        }
        # V10 FIX F10: Include LLM context if present
        if self.conversation_summary:
            data["conversation_summary"] = self.conversation_summary
        if self.agent_states:
            data["agent_states"] = self.agent_states
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PhaseCheckpoint:
        """Deserialize checkpoint from dict."""
        return cls(
            phase=data["phase"],
            result=data.get("result", {}),
            state=data["state"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            context_index=data.get("context_index", 0),
            compensation_name=data.get("compensation_name"),
            # V10 FIX F10: Restore LLM context
            conversation_summary=data.get("conversation_summary"),
            agent_states=data.get("agent_states"),
        )


@dataclass
class SagaContext:
    """
    Mutable context passed through the saga.

    This context tracks phase completion flags for guard evaluation.
    """

    analysis_complete: bool = False
    debate_complete: bool = False
    debate_skipped: bool = False
    immediate_consensus: bool = False
    architecture_approved: bool = False
    execution_complete: bool = False
    execution_failed: bool = False
    diagnosis_complete: bool = False
    retry_exhausted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_complete": self.analysis_complete,
            "debate_complete": self.debate_complete,
            "debate_skipped": self.debate_skipped,
            "immediate_consensus": self.immediate_consensus,
            "architecture_approved": self.architecture_approved,
            "execution_complete": self.execution_complete,
            "execution_failed": self.execution_failed,
            "diagnosis_complete": self.diagnosis_complete,
            "retry_exhausted": self.retry_exhausted,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SagaContext:
        return cls(**{k: v for k, v in data.items() if hasattr(cls, k)})


# =============================================================================
# SAGA MANAGER
# =============================================================================


class SagaManager:
    """
    Saga Pattern implementation for HiveMind pipeline.

    Provides checkpoint/rollback capability with context snapshot
    to prevent "hallucination" about events that didn't happen.

    Usage:
        saga = SagaManager(workspace / ".nexus" / "sagas", task_id)

        # During phase execution
        await saga.checkpoint_phase(
            phase="analysis",
            result=analysis_result,
            state=HiveMindState.HIVE_COMPARING_ANALYSES,
            context_index=len(conversation_history),
            compensation=compensate_analysis
        )

        # On failure, rollback to safe point
        await saga.rollback_to("analysis", context_manager)

        # After crash, resume
        saga = await SagaManager.resume_from(sagas_dir, task_id)
    """

    def __init__(
        self,
        sagas_dir: Path,
        task_id: str,
        *,
        auto_persist: bool = True,
        tenant_id: str = "default",
        workspace_id: str = "default",
        enable_redis: bool = True,
    ):
        """
        Initialize SagaManager.

        Args:
            sagas_dir: Directory for saga persistence (e.g., workspace/.nexus/sagas)
            task_id: Unique task identifier (from SwarmSessionManager)
            auto_persist: If True, persist to disk after each checkpoint
            tenant_id: Tenant identifier for multi-tenant isolation (V12.4.1 Epic 1.3)
            workspace_id: Workspace identifier (V12.4.1 Epic 1.3)
            enable_redis: If True, publish events to Redis bus (V12.4.1 Epic 1.3)
        """
        self._sagas_dir = Path(sagas_dir)
        self._task_id = task_id
        self._auto_persist = auto_persist

        # AtomicJsonStore for crash-safe persistence
        self._store = AtomicJsonStore(self._sagas_dir / f"{task_id}.json")

        # In-memory checkpoints
        self._checkpoints: dict[str, PhaseCheckpoint] = {}

        # Saga context for guards
        self._context = SagaContext()

        # Registered compensation functions
        self._compensations: dict[str, Callable] = {}

        # Metadata
        self._created_at = datetime.now()
        self._recovery_point: str | None = None

        # V12.4.1 Epic 1.3: Redis event bus integration
        self._tenant_id = tenant_id
        self._workspace_id = workspace_id
        self._enable_redis = enable_redis
        self._redis_bus = get_redis_bus() if enable_redis else None

        logger.debug(f"SagaManager initialized for task {task_id[:8]}... (Redis: {enable_redis})")

    @property
    def task_id(self) -> str:
        """Get the task ID."""
        return self._task_id

    @property
    def context(self) -> SagaContext:
        """Get the saga context."""
        return self._context

    @property
    def recovery_point(self) -> str | None:
        """Get the last successful phase."""
        return self._recovery_point

    @property
    def checkpointed_phases(self) -> list[str]:
        """Get list of phases that have checkpoints."""
        return list(self._checkpoints.keys())

    # -------------------------------------------------------------------------
    # Compensation Registration
    # -------------------------------------------------------------------------

    def register_compensation(self, phase: str, func: Callable) -> None:
        """
        Register a compensation function for a phase.

        Args:
            phase: Phase name
            func: Async callable to run on rollback (takes no args)
        """
        self._compensations[phase] = func
        logger.debug(f"Registered compensation for phase '{phase}'")

    def register_default_compensations(self, orchestrator: Any) -> None:
        """
        Register default compensations based on orchestrator instance.

        Args:
            orchestrator: TrueHiveMind or similar orchestrator
        """

        # Analysis: Clear analysis results, reset comparison
        async def compensate_analysis():
            if hasattr(orchestrator, "_analysis_comparison"):
                orchestrator._analysis_comparison = None
            if hasattr(orchestrator, "_gemini_analysis"):
                orchestrator._gemini_analysis = None
            if hasattr(orchestrator, "_claude_analysis"):
                orchestrator._claude_analysis = None
            logger.info("Compensated analysis phase")

        # Debate: Clear debate result, restore analysis state
        async def compensate_debate():
            if hasattr(orchestrator, "_debate_result"):
                orchestrator._debate_result = None
            logger.info("Compensated debate phase")

        # Architecture: Despawn created agents, clear plan
        # V8.4.4b: Enhanced with file cleanup
        async def compensate_architecture():
            if hasattr(orchestrator, "_execution_plan"):
                orchestrator._execution_plan = None
            if hasattr(orchestrator, "_spawned_agents"):
                spawned_list = list(orchestrator._spawned_agents)
                # V8.4.4b: Delete spawned agent files
                if hasattr(orchestrator, "workspace_path") and spawned_list:
                    from pathlib import Path

                    agents_dir = Path(orchestrator.workspace_path) / "agents"
                    for agent_id in spawned_list:
                        agent_file = agents_dir / f"{agent_id}.json"
                        try:
                            if agent_file.exists():
                                agent_file.unlink()
                                logger.info(f"Deleted agent file: {agent_file}")
                        except Exception as e:
                            logger.warning(f"Failed to delete agent file {agent_file}: {e}")
                orchestrator._spawned_agents = []
            logger.info("Compensated architecture phase (with file cleanup)")

        # Execution: Mark incomplete, cleanup artifacts
        async def compensate_execution():
            if hasattr(orchestrator, "_execution_results"):
                orchestrator._execution_results = []
            if hasattr(orchestrator, "_current_step"):
                orchestrator._current_step = 0
            logger.info("Compensated execution phase")

        # Diagnosis: Clear diagnosis
        async def compensate_diagnosis():
            if hasattr(orchestrator, "_failure_analysis"):
                orchestrator._failure_analysis = None
            logger.info("Compensated diagnosis phase")

        # Retry: Clear retry state
        async def compensate_retry():
            if hasattr(orchestrator, "_retry_count"):
                orchestrator._retry_count = 0
            logger.info("Compensated retry phase")

        # Register all
        self._compensations["analysis"] = compensate_analysis
        self._compensations["debate"] = compensate_debate
        self._compensations["architecture"] = compensate_architecture
        self._compensations["execution"] = compensate_execution
        self._compensations["diagnosis"] = compensate_diagnosis
        self._compensations["retry"] = compensate_retry
        # Consolidation is terminal, no compensation needed

    # -------------------------------------------------------------------------
    # Phase Guards
    # -------------------------------------------------------------------------

    def can_enter_phase(self, phase: str) -> tuple[bool, str]:
        """
        Check if the current context allows entering a phase.

        Args:
            phase: Phase name to check

        Returns:
            Tuple of (can_enter, reason_if_not)
        """
        guard = PHASE_GUARDS.get(phase)
        if guard is None:
            return True, ""

        ctx_dict = self._context.to_dict()
        if guard(ctx_dict):
            return True, ""
        else:
            return False, f"Guard failed for phase '{phase}': context = {ctx_dict}"

    def update_context(self, **kwargs) -> None:
        """
        Update saga context flags.

        Args:
            **kwargs: Flags to update (e.g., analysis_complete=True)
        """
        for key, value in kwargs.items():
            if hasattr(self._context, key):
                setattr(self._context, key, value)
                logger.debug(f"Saga context updated: {key}={value}")

    # -------------------------------------------------------------------------
    # Checkpointing
    # -------------------------------------------------------------------------

    async def checkpoint_phase(
        self,
        phase: str,
        result: Any,
        state: HiveMindState,
        context_index: int,
        compensation: Callable | None = None,
        conversation_summary: str | None = None,
        agent_states: dict[str, str] | None = None,
    ) -> PhaseCheckpoint:
        """
        Create a checkpoint after successful phase completion.

        Args:
            phase: Phase name (analysis, debate, etc.)
            result: Phase result object (will be serialized)
            state: Current HiveMindState
            context_index: Index in conversation history for rollback truncation
            compensation: Optional compensation function for rollback
            conversation_summary: V10 FIX F10 - Summary of conversation for LLM context
            agent_states: V10 FIX F10 - Per-agent state snapshots

        Returns:
            Created PhaseCheckpoint
        """
        # Serialize result
        serialized_result = serialize_for_checkpoint(result)

        # Create checkpoint
        checkpoint = PhaseCheckpoint(
            phase=phase,
            result=serialized_result,
            state=state.value if hasattr(state, "value") else str(state),
            timestamp=datetime.now(),
            context_index=context_index,
            compensation_name=phase if compensation else None,
            # V10 FIX F10: LLM context for recovery
            conversation_summary=conversation_summary,
            agent_states=agent_states,
        )

        # Store in memory
        self._checkpoints[phase] = checkpoint
        self._recovery_point = phase

        # Register compensation if provided
        if compensation:
            self._compensations[phase] = compensation

        # Persist to disk if auto_persist
        if self._auto_persist:
            await self._persist()

        # V12.4.1 Epic 1.3: Publish SAGA_CHECKPOINT event to Redis
        if self._enable_redis and self._redis_bus:
            try:
                from core.observability.events.types import CerebroEvent, CerebroEventType

                event = CerebroEvent(
                    event_type=CerebroEventType.SAGA_CHECKPOINT,
                    tenant_id=self._tenant_id,
                    workspace_id=self._workspace_id,
                    payload={
                        "task_id": self._task_id,
                        "phase": phase,
                        "state": checkpoint.state,
                        "context_index": context_index,
                        "timestamp": checkpoint.timestamp.isoformat(),
                        "recovery_point": self._recovery_point,
                    },
                    correlation_id=self._task_id,
                )
                await self._redis_bus.publish(event)
                logger.debug(f"Published SAGA_CHECKPOINT to Redis for phase={phase}")
            except Exception as e:
                # Graceful degradation - checkpoint still saved to disk
                logger.warning(f"Failed to publish saga checkpoint to Redis: {e}")

        logger.info(f"Checkpoint created: phase={phase}, context_index={context_index}")
        return checkpoint

    def get_checkpoint(self, phase: str) -> PhaseCheckpoint | None:
        """
        Get checkpoint for a specific phase.

        Args:
            phase: Phase name

        Returns:
            PhaseCheckpoint or None if not found
        """
        return self._checkpoints.get(phase)

    # -------------------------------------------------------------------------
    # Rollback
    # -------------------------------------------------------------------------

    async def rollback_to(
        self,
        target_phase: str,
        context_manager: Any | None = None,
    ) -> bool:
        """
        Rollback to a specific phase, running compensations and truncating context.

        CRITICAL: This also truncates conversation history to prevent
        "hallucination" about events that didn't happen.

        Args:
            target_phase: Phase to roll back to
            context_manager: Object with 'messages' list to truncate

        Returns:
            True if rollback successful
        """
        if target_phase not in self._checkpoints:
            logger.error(f"Cannot rollback to '{target_phase}': no checkpoint found")
            return False

        target_checkpoint = self._checkpoints[target_phase]
        target_idx = PHASE_ORDER.index(target_phase) if target_phase in PHASE_ORDER else -1

        if target_idx < 0:
            logger.error(f"Unknown phase '{target_phase}' for rollback")
            return False

        # Run compensations in reverse order for phases AFTER target
        for phase in reversed(PHASE_ORDER[target_idx + 1 :]):
            if phase in self._checkpoints:
                # Run compensation
                compensation = self._compensations.get(phase)
                if compensation:
                    try:
                        if asyncio.iscoroutinefunction(compensation):
                            await compensation()
                        else:
                            compensation()
                        logger.info(f"Compensation executed for phase '{phase}'")
                    except Exception as e:
                        logger.error(f"Compensation failed for phase '{phase}': {e}")

                # Remove checkpoint
                del self._checkpoints[phase]

        # Truncate conversation history (CRITICAL for context bleeding prevention)
        # V8.4.4b: Support HiveMindContextManager (._items) and generic (.messages)
        if context_manager:
            if hasattr(context_manager, "_items"):
                # HiveMindContextManager uses deque
                from collections import deque

                original_len = len(context_manager._items)
                items_list = list(context_manager._items)[: target_checkpoint.context_index]
                context_manager._items = deque(items_list)
                # Recalculate token count
                if hasattr(context_manager, "_current_tokens"):
                    context_manager._current_tokens = sum(
                        getattr(item, "token_estimate", 0) for item in context_manager._items
                    )
                logger.info(
                    f"Context truncated: {original_len} -> {len(context_manager._items)} items "
                    f"(rollback to index {target_checkpoint.context_index})"
                )
            elif hasattr(context_manager, "messages"):
                # Generic context manager with messages list
                original_len = len(context_manager.messages)
                context_manager.messages = context_manager.messages[: target_checkpoint.context_index]
                logger.info(
                    f"Context truncated: {original_len} -> {len(context_manager.messages)} messages "
                    f"(rollback to index {target_checkpoint.context_index})"
                )

        # Update recovery point
        self._recovery_point = target_phase

        # Reset context flags for phases after target
        self._reset_context_after(target_phase)

        # Persist state
        if self._auto_persist:
            await self._persist()

        # V12.4.1 Epic 1.3: Publish SAGA_ROLLBACK event to Redis
        if self._enable_redis and self._redis_bus:
            try:
                from core.observability.events.types import CerebroEvent, CerebroEventType

                event = CerebroEvent(
                    event_type=CerebroEventType.SAGA_ROLLBACK,
                    tenant_id=self._tenant_id,
                    workspace_id=self._workspace_id,
                    payload={
                        "task_id": self._task_id,
                        "target_phase": target_phase,
                        "compensated_phases": [p for p in PHASE_ORDER[target_idx + 1 :] if p in self._checkpoints],
                        "timestamp": datetime.now().isoformat(),
                    },
                    correlation_id=self._task_id,
                )
                await self._redis_bus.publish(event)
                logger.debug(f"Published SAGA_ROLLBACK to Redis for target_phase={target_phase}")
            except Exception as e:
                logger.warning(f"Failed to publish saga rollback to Redis: {e}")

        logger.info(f"Rolled back to phase '{target_phase}'")
        return True

    def _reset_context_after(self, phase: str) -> None:
        """Reset context flags for phases after the given phase."""
        phase_idx = PHASE_ORDER.index(phase) if phase in PHASE_ORDER else -1

        flag_mapping = {
            "analysis": "analysis_complete",
            "debate": "debate_complete",
            "architecture": "architecture_approved",
            "execution": "execution_complete",
            "diagnosis": "diagnosis_complete",
            "retry": "retry_exhausted",
        }

        for p in PHASE_ORDER[phase_idx + 1 :]:
            flag = flag_mapping.get(p)
            if flag and hasattr(self._context, flag):
                setattr(self._context, flag, False)

    # -------------------------------------------------------------------------
    # Persistence
    # -------------------------------------------------------------------------

    async def _persist(self) -> None:
        """Persist saga state to disk atomically."""
        data = {
            "task_id": self._task_id,
            "created_at": self._created_at.isoformat(),
            "recovery_point": self._recovery_point,
            "context": self._context.to_dict(),
            "checkpoints": {phase: cp.to_dict() for phase, cp in self._checkpoints.items()},
        }

        # Use AtomicJsonStore for crash-safe write
        # Note: AtomicJsonStore.save() is sync, run in executor to not block
        # V12.4 FIX F19: Use get_running_loop() instead of deprecated get_event_loop()
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._store.save, data)
        logger.debug(f"Saga persisted to {self._store.filepath}")

    @classmethod
    async def resume_from(cls, sagas_dir: Path, task_id: str) -> SagaManager | None:
        """
        Resume a saga from disk after crash/restart.

        Args:
            sagas_dir: Directory containing saga files
            task_id: Task ID to resume

        Returns:
            SagaManager instance or None if no saga found
        """
        store = AtomicJsonStore(sagas_dir / f"{task_id}.json")

        if not store.exists:
            logger.debug(f"No saga found for task {task_id[:8]}...")
            return None

        try:
            data = store.load()
        except Exception as e:
            logger.error(f"Failed to load saga for task {task_id[:8]}: {e}")
            return None

        # Create manager
        saga = cls(sagas_dir, task_id, auto_persist=True)

        # Restore state
        saga._created_at = datetime.fromisoformat(data.get("created_at", datetime.now().isoformat()))
        saga._recovery_point = data.get("recovery_point")

        # Restore context
        ctx_data = data.get("context", {})
        saga._context = SagaContext.from_dict(ctx_data)

        # Restore checkpoints
        for phase, cp_data in data.get("checkpoints", {}).items():
            saga._checkpoints[phase] = PhaseCheckpoint.from_dict(cp_data)

        # V12.4.1 Epic 1.3: Publish SAGA_RESUME event to Redis
        if saga._enable_redis and saga._redis_bus:
            try:
                from core.observability.events.types import CerebroEvent, CerebroEventType

                event = CerebroEvent(
                    event_type=CerebroEventType.SAGA_RESUME,
                    tenant_id=saga._tenant_id,
                    workspace_id=saga._workspace_id,
                    payload={
                        "task_id": task_id,
                        "recovery_point": saga._recovery_point,
                        "checkpointed_phases": list(saga._checkpoints.keys()),
                        "timestamp": datetime.now().isoformat(),
                    },
                    correlation_id=task_id,
                )
                await saga._redis_bus.publish(event)
                logger.debug(f"Published SAGA_RESUME to Redis for task_id={task_id[:8]}...")
            except Exception as e:
                logger.warning(f"Failed to publish saga resume to Redis: {e}")

        logger.info(
            f"Saga resumed for task {task_id[:8]}... "
            f"(recovery_point={saga._recovery_point}, phases={list(saga._checkpoints.keys())})"
        )
        return saga

    def cleanup(self) -> bool:
        """
        Delete saga file after successful completion.

        Returns:
            True if file was deleted
        """
        return self._store.delete()

    # -------------------------------------------------------------------------
    # V10 FIX F10: LLM Context Management
    # -------------------------------------------------------------------------

    def get_recovery_context(self) -> dict[str, Any] | None:
        """
        V10 FIX F10: Get LLM context from last checkpoint for recovery.

        Returns:
            Dict with 'conversation_summary' and 'agent_states' if available
        """
        if not self._recovery_point:
            return None

        checkpoint = self._checkpoints.get(self._recovery_point)
        if not checkpoint:
            return None

        return {
            "phase": checkpoint.phase,
            "conversation_summary": checkpoint.conversation_summary,
            "agent_states": checkpoint.agent_states,
            "timestamp": checkpoint.timestamp.isoformat(),
        }

    @staticmethod
    def create_conversation_summary(context_manager: Any, max_tokens: int = 1000) -> str:
        """
        V10 FIX F10: Create a compressed summary of conversation for checkpointing.

        Args:
            context_manager: HiveMindContextManager instance
            max_tokens: Maximum tokens for summary

        Returns:
            Compressed conversation summary string
        """
        if context_manager is None:
            return ""

        try:
            # Use context_manager's summarize method if available
            if hasattr(context_manager, "summarize_for_inheritance"):
                return context_manager.summarize_for_inheritance(max_tokens=max_tokens)

            # Fallback: extract key items
            if hasattr(context_manager, "_items"):
                summary_parts = []
                for item in list(context_manager._items)[-10:]:  # Last 10 items
                    summary_parts.append(f"[{item.category}:{item.source}] {item.content[:200]}")
                return "\n".join(summary_parts)

            return ""
        except Exception as e:
            logger.warning(f"Failed to create conversation summary: {e}")
            return ""

    @staticmethod
    def create_agent_states(agents: dict[str, Any]) -> dict[str, str]:
        """
        V10 FIX F10: Capture current state of each agent for checkpoint.

        Args:
            agents: Dict of agent_id -> agent instance

        Returns:
            Dict of agent_id -> state summary string
        """
        states = {}
        for agent_id, agent in agents.items():
            try:
                if hasattr(agent, "get_state_summary"):
                    states[agent_id] = agent.get_state_summary()
                elif hasattr(agent, "last_response"):
                    states[agent_id] = f"Last response: {str(agent.last_response)[:500]}"
                else:
                    states[agent_id] = "active"
            except Exception as e:
                states[agent_id] = f"error: {e}"
        return states

    def build_recovery_prompt(self, task: str) -> str:
        """
        V10 FIX F10: Build a prompt that includes recovery context for agents.

        Args:
            task: Original task description

        Returns:
            Enhanced prompt with recovery context
        """
        context = self.get_recovery_context()
        if not context:
            return task

        recovery_prompt = f"""[RECOVERY MODE - Resuming from checkpoint]

Original Task: {task}

Last Successful Phase: {context["phase"]}
Checkpoint Time: {context["timestamp"]}

Previous Progress Summary:
{context.get("conversation_summary", "No summary available")}

Please continue from where we left off. The task was partially completed up to the {context["phase"]} phase.
"""
        return recovery_prompt

    # -------------------------------------------------------------------------
    # Status & Debugging
    # -------------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Get saga status for debugging/monitoring."""
        return {
            "task_id": self._task_id,
            "recovery_point": self._recovery_point,
            "checkpointed_phases": self.checkpointed_phases,
            "context": self._context.to_dict(),
            "compensations_registered": list(self._compensations.keys()),
            "created_at": self._created_at.isoformat(),
            "persisted": self._store.exists,
        }

    def __repr__(self) -> str:
        return (
            f"SagaManager(task_id={self._task_id[:8]}..., "
            f"recovery_point={self._recovery_point}, "
            f"phases={self.checkpointed_phases})"
        )


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    "SagaManager",
    "PhaseCheckpoint",
    "SagaContext",
    "PHASE_ORDER",
    "PHASE_GUARDS",
]
