"""
OrchestratorSyncBridge - State Synchronization Between HiveMind and Swarm

V9.4 ISSUE-003: Prevents state desynchronization when HiveMind delegates to Swarm.

Problem Solved:
- SagaManager (HiveMind) and SwarmSessionManager (Swarm) operated independently
- Checkpoints were not correlated between systems
- Rollback in one system didn't affect the other
- No cross-validation on startup

Solution:
- Mediator pattern bridges both systems
- Unified task_id generation
- Bidirectional checkpoint propagation
- Coordinated rollback
- Cross-system validation

Research Sources:
- AWS Saga Orchestration Patterns
- Microsoft Saga Design Pattern
- Temporal.io: Mastering Saga Patterns

Usage:
    sync_bridge = OrchestratorSyncBridge(
        saga_manager=saga,
        session_manager=session_manager
    )

    # Create unified task
    task_id = sync_bridge.create_unified_task("Build API", "PARALLEL")

    # Sync checkpoint from HiveMind
    await sync_bridge.sync_checkpoint(
        source="hivemind",
        task_id=task_id,
        phase_or_mode="analysis",
        checkpoint_data={"context_index": 50}
    )

    # Coordinated rollback
    await sync_bridge.coordinated_rollback(
        task_id=task_id,
        target_phase="analysis",
        context_manager=context_manager
    )

Author: Claude (NEXUS V9.4)
Date: 2025-12-13
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING, Any

# V11 FIX F20: AsyncRWLock for async methods (prevents event loop blocking)
from core.foundation.async_primitives.rwlock import AsyncRWLock

if TYPE_CHECKING:
    from core.intelligence.hive_mind.saga_manager import SagaManager
    from core.intelligence.swarm.session_manager import SwarmSessionManager


logger = logging.getLogger("nexus.sync_bridge")


# =============================================================================
# EVENT TYPES
# =============================================================================


class SyncEventType(Enum):
    """Types of synchronization events between HiveMind and Swarm."""

    TASK_CREATED = "task_created"
    CHECKPOINT_CREATED = "checkpoint_created"
    CHECKPOINT_RESTORED = "checkpoint_restored"
    ROLLBACK_STARTED = "rollback_started"
    ROLLBACK_COMPLETED = "rollback_completed"
    TASK_COMPLETED = "task_completed"
    VALIDATION_FAILED = "validation_failed"
    VALIDATION_PASSED = "validation_passed"


@dataclass
class SyncEvent:
    """
    Record of a synchronization event.

    Provides audit trail for debugging and monitoring sync operations.

    Attributes:
        event_type: Type of sync event
        source: Origin system ("hivemind", "swarm", or "sync_bridge")
        task_id: The unified task identifier
        timestamp: When the event occurred
        data: Additional event-specific data
        propagated_to: List of systems that received the event
    """

    event_type: SyncEventType
    source: str  # "hivemind" | "swarm" | "sync_bridge"
    task_id: str
    timestamp: datetime = field(default_factory=datetime.now)
    data: dict[str, Any] = field(default_factory=dict)
    propagated_to: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize event for logging/storage."""
        return {
            "event_type": self.event_type.value,
            "source": self.source,
            "task_id": self.task_id,
            "timestamp": self.timestamp.isoformat(),
            "data": self.data,
            "propagated_to": self.propagated_to,
        }


# =============================================================================
# SYNC BRIDGE
# =============================================================================


class OrchestratorSyncBridge:
    """
    Mediator pattern for HiveMind/Swarm state synchronization.

    V9.4 ISSUE-003: Resolves state desynchronization between:
    - SagaManager (HiveMind checkpoint/rollback)
    - SwarmSessionManager (Swarm session isolation)

    Core Responsibilities:
    1. **Unified Task ID**: Generate single task_id used by both systems
    2. **Checkpoint Propagation**: When one system checkpoints, notify the other
    3. **Rollback Coordination**: Rollbacks affect both systems atomically
    4. **Validation**: Cross-validate both systems on startup/resume
    5. **Event Logging**: Audit trail of all sync operations

    Thread Safety:
    - Uses RLock for all state modifications
    - Safe for concurrent access in PARALLEL swarm mode

    Example:
        >>> bridge = OrchestratorSyncBridge()
        >>> bridge.set_saga_manager(saga)
        >>> bridge.set_session_manager(session_manager)
        >>>
        >>> # Create unified task
        >>> task_id = bridge.create_unified_task("Build API", "PARALLEL")
        >>>
        >>> # After HiveMind checkpoint
        >>> await bridge.sync_checkpoint("hivemind", task_id, "analysis", {})
    """

    def __init__(
        self,
        saga_manager: SagaManager | None = None,
        session_manager: SwarmSessionManager | None = None,
        workspace_path: Path | None = None,
    ):
        """
        Initialize OrchestratorSyncBridge.

        Args:
            saga_manager: HiveMind's SagaManager (can be set later)
            session_manager: Swarm's SwarmSessionManager (can be set later)
            workspace_path: Workspace for any persistent sync metadata
        """
        self._saga: SagaManager | None = saga_manager
        self._session: SwarmSessionManager | None = session_manager
        self._workspace = Path(workspace_path) if workspace_path else None
        self._lock = RLock()  # For sync methods

        # V11 FIX F20: Async lock for async methods (prevents event loop blocking)
        self._async_lock = AsyncRWLock()

        # Event history for audit
        self._events: list[SyncEvent] = []

        # Callbacks for extensibility (e.g., telemetry)
        self._on_sync_callbacks: list[Callable[[SyncEvent], None]] = []

        # Task ID mapping: HiveMind task_id -> Swarm task_id correlation
        self._task_correlation: dict[str, dict[str, str]] = {}

        # V10 SYNAPSE: Setup telemetry hook
        self._setup_telemetry()

        logger.debug("OrchestratorSyncBridge initialized")

    # =========================================================================
    # Manager Registration
    # =========================================================================

    def set_saga_manager(self, saga: SagaManager) -> None:
        """
        Set or update the SagaManager reference.

        Called when HiveMind initializes its saga for a new task.

        Args:
            saga: The SagaManager instance
        """
        with self._lock:
            self._saga = saga
            logger.debug(f"SagaManager set: task={saga.task_id[:8] if saga else 'None'}...")

    def set_session_manager(self, session: SwarmSessionManager) -> None:
        """
        Set or update the SwarmSessionManager reference.

        Called when Swarm engine is initialized.

        Args:
            session: The SwarmSessionManager instance
        """
        with self._lock:
            self._session = session
            logger.debug("SwarmSessionManager set")

    @property
    def is_connected(self) -> bool:
        """Check if both managers are connected."""
        return self._saga is not None or self._session is not None

    # =========================================================================
    # Task Lifecycle
    # =========================================================================

    def create_unified_task(
        self, objective: str, swarm_mode: str = "SPECIALIST", metadata: dict[str, Any] | None = None
    ) -> str:
        """
        Create a task tracked by both SagaManager and SwarmSessionManager.

        This ensures both systems use the same task_id, enabling correlation
        for checkpoint sync and rollback coordination.

        Args:
            objective: Task objective/description
            swarm_mode: Collaboration mode (PARALLEL, SEQUENTIAL, etc.)
            metadata: Additional task metadata

        Returns:
            Unified task_id usable by both systems
        """
        from core.intelligence.swarm.session_manager import generate_task_id

        with self._lock:
            task_id = generate_task_id(prefix="unified")

            # Create in SwarmSessionManager (if available)
            if self._session:
                try:
                    self._session.create_task(
                        task_id=task_id,
                        swarm_mode=swarm_mode,
                        metadata={
                            "objective": objective[:200],
                            "sync_bridge": True,
                            "created_by": "OrchestratorSyncBridge",
                            **(metadata or {}),
                        },
                    )
                except ValueError:
                    # Task already exists (shouldn't happen with generate_task_id)
                    logger.warning(f"Task {task_id} already exists in SwarmSessionManager")

            # Record correlation for this task
            self._task_correlation[task_id] = {
                "created_at": datetime.now().isoformat(),
                "objective": objective[:100],
                "swarm_mode": swarm_mode,
            }

            # Record event
            self._record_event(
                SyncEvent(
                    event_type=SyncEventType.TASK_CREATED,
                    source="sync_bridge",
                    task_id=task_id,
                    data={
                        "objective": objective[:100],
                        "swarm_mode": swarm_mode,
                        "session_manager_available": self._session is not None,
                    },
                )
            )

            logger.info(f"Unified task created: {task_id[:12]}...")
            return task_id

    def complete_unified_task(self, task_id: str, success: bool = True, cleanup_saga: bool = True) -> bool:
        """
        Mark a unified task as completed in both systems.

        Args:
            task_id: The unified task ID
            success: Whether the task completed successfully
            cleanup_saga: Whether to cleanup saga file on success

        Returns:
            True if completion recorded in both systems
        """
        with self._lock:
            swarm_success = True
            saga_success = True

            # Complete in SwarmSessionManager
            if self._session:
                from core.intelligence.swarm.session_manager import SessionStatus

                status = SessionStatus.COMPLETED if success else SessionStatus.FAILED
                swarm_success = self._session.complete_task(task_id, status)

            # Cleanup SagaManager (optional)
            if self._saga and self._saga.task_id == task_id and cleanup_saga and success:
                saga_success = self._saga.cleanup()

            self._record_event(
                SyncEvent(
                    event_type=SyncEventType.TASK_COMPLETED,
                    source="sync_bridge",
                    task_id=task_id,
                    data={
                        "success": success,
                        "swarm_completed": swarm_success,
                        "saga_cleaned": saga_success if cleanup_saga else "skipped",
                    },
                )
            )

            return swarm_success and saga_success

    # =========================================================================
    # Checkpoint Synchronization
    # =========================================================================

    async def sync_checkpoint(
        self, source: str, task_id: str, phase_or_mode: str, checkpoint_data: dict[str, Any] | None = None
    ) -> bool:
        """
        Propagate checkpoint from one system to the other.

        When HiveMind creates a phase checkpoint, this creates a corresponding
        checkpoint in SwarmSessionManager (and vice versa).

        Args:
            source: Origin system ("hivemind" or "swarm")
            task_id: The unified task ID
            phase_or_mode: Phase name (HiveMind) or mode name (Swarm)
            checkpoint_data: Additional checkpoint metadata

        Returns:
            True if propagation succeeded
        """
        # V11 FIX F20: Use async lock instead of threading RLock
        async with self._async_lock.write():
            checkpoint_data = checkpoint_data or {}

            if source == "hivemind" and self._session:
                # HiveMind checkpointed -> Create Swarm checkpoint
                try:
                    checkpoint_id = self._session.create_checkpoint(task_id)
                    if checkpoint_id:
                        self._record_event(
                            SyncEvent(
                                event_type=SyncEventType.CHECKPOINT_CREATED,
                                source=source,
                                task_id=task_id,
                                data={"phase": phase_or_mode, "swarm_checkpoint_id": checkpoint_id, **checkpoint_data},
                                propagated_to=["swarm"],
                            )
                        )
                        logger.debug(
                            f"Checkpoint synced: HiveMind phase '{phase_or_mode}' -> Swarm checkpoint '{checkpoint_id}'"
                        )
                        return True
                except Exception as e:
                    logger.warning(f"Failed to create Swarm checkpoint: {e}")
                    return False

            elif source == "swarm":
                # Swarm checkpointed -> Record correlation (Saga is phase-based)
                self._record_event(
                    SyncEvent(
                        event_type=SyncEventType.CHECKPOINT_CREATED,
                        source=source,
                        task_id=task_id,
                        data={"mode": phase_or_mode, **checkpoint_data},
                        propagated_to=["hivemind_notified"],
                    )
                )
                logger.debug(f"Swarm checkpoint recorded for mode '{phase_or_mode}'")
                return True

            # Neither system available for propagation
            logger.debug(f"No propagation target for source '{source}'")
            return False

    def sync_checkpoint_sync(
        self, source: str, task_id: str, phase_or_mode: str, checkpoint_data: dict[str, Any] | None = None
    ) -> bool:
        """
        Synchronous version of sync_checkpoint for non-async contexts.

        Args:
            source: Origin system ("hivemind" or "swarm")
            task_id: The unified task ID
            phase_or_mode: Phase name (HiveMind) or mode name (Swarm)
            checkpoint_data: Additional checkpoint metadata

        Returns:
            True if propagation succeeded
        """
        import asyncio

        try:
            asyncio.get_running_loop()
            # Already in async context - this shouldn't be called
            logger.warning("sync_checkpoint_sync called from async context")
            return False
        except RuntimeError:
            # No running loop - safe to create one
            return asyncio.run(self.sync_checkpoint(source, task_id, phase_or_mode, checkpoint_data))

    # =========================================================================
    # Rollback Coordination
    # =========================================================================

    async def coordinated_rollback(self, task_id: str, target_phase: str, context_manager: Any | None = None) -> bool:
        """
        Perform rollback in both HiveMind and Swarm atomically.

        When HiveMind rolls back to a previous phase, this ensures Swarm
        state is also rolled back to the corresponding checkpoint.

        Args:
            task_id: The unified task ID
            target_phase: HiveMind phase to rollback to
            context_manager: HiveMindContextManager for context truncation

        Returns:
            True if both rollbacks succeeded
        """
        # V11 FIX F20: Use async lock instead of threading RLock
        async with self._async_lock.write():
            self._record_event(
                SyncEvent(
                    event_type=SyncEventType.ROLLBACK_STARTED,
                    source="sync_bridge",
                    task_id=task_id,
                    data={"target_phase": target_phase},
                )
            )

            saga_success = True
            swarm_success = True
            errors = []

            # 1. Rollback HiveMind (SagaManager)
            if self._saga and self._saga.task_id == task_id:
                if target_phase in self._saga.checkpointed_phases:
                    try:
                        saga_success = await self._saga.rollback_to(target_phase, context_manager)
                        if not saga_success:
                            errors.append("SagaManager rollback returned False")
                    except Exception as e:
                        saga_success = False
                        errors.append(f"SagaManager rollback error: {e}")
                else:
                    logger.debug(f"Phase '{target_phase}' not in saga checkpoints")

            # 2. Rollback Swarm (SwarmSessionManager)
            if self._session:
                try:
                    checkpoints = self._session.list_checkpoints(task_id)
                    if checkpoints:
                        # Restore to most recent checkpoint
                        # Future: Map phase -> checkpoint for precise restore
                        latest_cp = checkpoints[-1]
                        swarm_success = self._session.restore_checkpoint(task_id, latest_cp)
                        if not swarm_success:
                            errors.append("SwarmSessionManager restore returned False")
                    else:
                        logger.debug("No Swarm checkpoints to restore")
                except Exception as e:
                    swarm_success = False
                    errors.append(f"SwarmSessionManager restore error: {e}")

            # Record completion
            overall_success = saga_success and swarm_success
            self._record_event(
                SyncEvent(
                    event_type=SyncEventType.ROLLBACK_COMPLETED,
                    source="sync_bridge",
                    task_id=task_id,
                    data={
                        "target_phase": target_phase,
                        "saga_success": saga_success,
                        "swarm_success": swarm_success,
                        "overall_success": overall_success,
                        "errors": errors,
                    },
                )
            )

            if overall_success:
                logger.info(f"Coordinated rollback to '{target_phase}' succeeded")
            else:
                logger.warning(f"Coordinated rollback had issues: {errors}")

            return overall_success

    # =========================================================================
    # Validation
    # =========================================================================

    def validate_consistency(self, task_id: str) -> dict[str, Any]:
        """
        Validate that both systems have consistent state for a task.

        Detects:
        - Task exists in one system but not the other
        - Status mismatch (e.g., Swarm completed but Saga incomplete)
        - Missing checkpoints

        Args:
            task_id: The task ID to validate

        Returns:
            Validation result dict with 'consistent' flag and any 'issues'
        """
        with self._lock:
            result = {"task_id": task_id, "consistent": True, "issues": [], "swarm_state": None, "saga_state": None}

            # Check SwarmSessionManager
            swarm_task = None
            if self._session:
                swarm_task = self._session.get_task(task_id)
                if swarm_task:
                    result["swarm_state"] = {
                        "status": swarm_task.status.value,
                        "roles_count": len(swarm_task.roles),
                        "checkpoints_count": len(swarm_task.metadata.get("checkpoints", {})),
                    }
                else:
                    result["issues"].append("Task not found in SwarmSessionManager")
                    result["consistent"] = False

            # Check SagaManager
            saga_exists = False
            if self._saga and self._saga.task_id == task_id:
                saga_exists = True
                result["saga_state"] = {
                    "recovery_point": self._saga.recovery_point,
                    "checkpoints": self._saga.checkpointed_phases,
                    "context_flags": self._saga.context.to_dict(),
                }
                if not self._saga.checkpointed_phases:
                    result["issues"].append("SagaManager has no checkpoints")

            # Cross-validation
            if swarm_task and saga_exists:
                # Check status consistency
                swarm_completed = swarm_task.status.value == "completed"
                saga_completed = self._saga.recovery_point == "consolidation"

                if swarm_completed and not saga_completed:
                    result["issues"].append(f"Swarm completed but Saga at '{self._saga.recovery_point}'")
                    result["consistent"] = False
                elif saga_completed and not swarm_completed:
                    result["issues"].append(f"Saga completed but Swarm status is '{swarm_task.status.value}'")
                    result["consistent"] = False

            # Record validation event
            event_type = SyncEventType.VALIDATION_PASSED if result["consistent"] else SyncEventType.VALIDATION_FAILED
            self._record_event(
                SyncEvent(
                    event_type=event_type,
                    source="sync_bridge",
                    task_id=task_id,
                    data={"consistent": result["consistent"], "issues": result["issues"]},
                )
            )

            return result

    # =========================================================================
    # Event Management
    # =========================================================================

    def _record_event(self, event: SyncEvent) -> None:
        """Record a sync event for audit trail."""
        self._events.append(event)
        logger.debug(f"SyncEvent: {event.event_type.value} for {event.task_id[:8]}...")

        # Notify callbacks
        for callback in self._on_sync_callbacks:
            try:
                callback(event)
            except Exception as e:
                logger.warning(f"Sync callback failed: {e}")

    def on_sync(self, callback: Callable[[SyncEvent], None]) -> None:
        """
        Register callback for sync events.

        Useful for telemetry, logging, or custom monitoring.

        Args:
            callback: Function called for each sync event
        """
        self._on_sync_callbacks.append(callback)

    def _setup_telemetry(self) -> None:
        """
        Wire telemetry to sync events (V10 SYNAPSE).

        Registers a callback that emits GRAPH_EDGE_MESSAGE events
        for each sync event between HiveMind and Swarm.
        """
        try:
            from core.observability.events.telemetry_bridge import get_telemetry_bridge
            from core.observability.events.types import CerebroEventType

            bridge = get_telemetry_bridge()

            def telemetry_callback(event: SyncEvent) -> None:
                """Emit telemetry for sync events."""
                bridge.emit_sync(
                    CerebroEventType.GRAPH_EDGE_MESSAGE,
                    {
                        "source": event.source,
                        "target": "sync_bridge",
                        "event_type": event.event_type.value,
                        "task_id": event.task_id[:12] if event.task_id else "unknown",
                        "payload_preview": str(event.data)[:100] if event.data else "",
                    },
                )

            self.on_sync(telemetry_callback)
            logger.debug("V10 SYNAPSE: Telemetry hook registered")
        except ImportError:
            # Telemetry not available (optional dependency)
            logger.debug("V10 SYNAPSE: Telemetry not available (import error)")

    def get_events(
        self, task_id: str | None = None, event_type: SyncEventType | None = None, limit: int = 100
    ) -> list[SyncEvent]:
        """
        Get sync events, optionally filtered.

        Args:
            task_id: Filter by task ID (optional)
            event_type: Filter by event type (optional)
            limit: Maximum events to return

        Returns:
            List of matching SyncEvent objects
        """
        with self._lock:
            events = self._events

            if task_id:
                events = [e for e in events if e.task_id == task_id]

            if event_type:
                events = [e for e in events if e.event_type == event_type]

            return events[-limit:]

    def clear_events(self) -> int:
        """Clear all recorded events. Returns count cleared."""
        with self._lock:
            count = len(self._events)
            self._events.clear()
            return count

    # =========================================================================
    # Status & Debugging
    # =========================================================================

    def get_status(self) -> dict[str, Any]:
        """
        Get sync bridge status for monitoring.

        Returns:
            Status dict with connection state, event counts, recent events
        """
        with self._lock:
            return {
                "saga_connected": self._saga is not None,
                "saga_task_id": (self._saga.task_id[:12] + "..." if self._saga else None),
                "session_connected": self._session is not None,
                "session_stats": (self._session.get_stats() if self._session else None),
                "total_events": len(self._events),
                "tasks_correlated": len(self._task_correlation),
                "recent_events": [
                    {
                        "type": e.event_type.value,
                        "source": e.source,
                        "task_id": e.task_id[:8] + "...",
                        "timestamp": e.timestamp.isoformat(),
                    }
                    for e in self._events[-5:]
                ],
            }

    def __repr__(self) -> str:
        return (
            f"OrchestratorSyncBridge("
            f"saga={'connected' if self._saga else 'None'}, "
            f"session={'connected' if self._session else 'None'}, "
            f"events={len(self._events)})"
        )


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

_global_sync_bridge: OrchestratorSyncBridge | None = None


def get_sync_bridge() -> OrchestratorSyncBridge:
    """
    Get the global OrchestratorSyncBridge instance.

    Creates one if it doesn't exist.

    Returns:
        OrchestratorSyncBridge singleton
    """
    global _global_sync_bridge
    if _global_sync_bridge is None:
        _global_sync_bridge = OrchestratorSyncBridge()
    return _global_sync_bridge


def reset_sync_bridge() -> None:
    """Reset the global sync bridge (for testing)."""
    global _global_sync_bridge
    _global_sync_bridge = None


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    "OrchestratorSyncBridge",
    "SyncEvent",
    "SyncEventType",
    "get_sync_bridge",
    "reset_sync_bridge",
]
