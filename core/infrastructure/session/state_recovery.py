"""
State Recovery Manager - Session state capture and recovery.

V12.4 COGNITIVE BOOST - Task #57

Captures session state snapshots and enables recovery from failures.
Supports automatic snapshots, manual savepoints, and rollback.

Usage:
    from core.infrastructure.session.state_recovery import get_recovery_manager

    manager = get_recovery_manager()

    # Capture state snapshot
    snapshot_id = manager.capture(
        session_id="sess_001",
        state={"phase": "EXECUTING", "step": 3},
        metadata={"agent": "claude"},
    )

    # List snapshots
    snapshots = manager.list_snapshots("sess_001")

    # Recover from latest
    result = manager.recover("sess_001")

    # Recover from specific snapshot
    result = manager.recover("sess_001", snapshot_id=snapshot_id)
"""

from __future__ import annotations

import copy
import logging
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

MAX_SNAPSHOTS_PER_SESSION = 100
DEFAULT_AUTO_INTERVAL = 60.0  # seconds


# =============================================================================
# Types
# =============================================================================


class SnapshotReason(Enum):
    """Why a snapshot was taken."""

    MANUAL = "manual"
    AUTO = "auto"
    PRE_EXECUTION = "pre_execution"
    POST_EXECUTION = "post_execution"
    ERROR = "error"
    SAVEPOINT = "savepoint"


@dataclass
class StateSnapshot:
    """A captured state snapshot."""

    snapshot_id: str
    session_id: str
    state: dict[str, Any]
    reason: SnapshotReason = SnapshotReason.MANUAL
    label: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.monotonic()

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "session_id": self.session_id,
            "state_keys": list(self.state.keys()),
            "reason": self.reason.value,
            "label": self.label,
            "metadata": self.metadata,
        }


@dataclass
class RecoveryResult:
    """Result of a recovery attempt."""

    success: bool
    snapshot_id: str = ""
    session_id: str = ""
    state: dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "snapshot_id": self.snapshot_id,
            "session_id": self.session_id,
            "state_keys": list(self.state.keys()),
            "reason": self.reason,
        }


@dataclass
class RecoveryStats:
    """Statistics about recovery operations."""

    total_snapshots: int
    total_recoveries: int
    successful_recoveries: int
    failed_recoveries: int
    sessions_tracked: int

    @property
    def success_rate(self) -> float:
        if self.total_recoveries == 0:
            return 0.0
        return self.successful_recoveries / self.total_recoveries

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_snapshots": self.total_snapshots,
            "total_recoveries": self.total_recoveries,
            "successful_recoveries": self.successful_recoveries,
            "failed_recoveries": self.failed_recoveries,
            "sessions_tracked": self.sessions_tracked,
            "success_rate": round(self.success_rate, 4),
        }


# =============================================================================
# State Recovery Manager
# =============================================================================


class StateRecoveryManager:
    """
    Manages session state snapshots and recovery.

    Features:
    - State snapshot capture with metadata
    - Named savepoints
    - Recovery from latest or specific snapshot
    - Rollback to previous state
    - Per-session snapshot history
    - Max snapshot limit with oldest eviction
    - Recovery statistics
    """

    def __init__(
        self,
        *,
        max_snapshots: int = MAX_SNAPSHOTS_PER_SESSION,
    ):
        self._snapshots: dict[str, list[StateSnapshot]] = defaultdict(list)
        self._snapshot_index: dict[str, StateSnapshot] = {}  # id -> snapshot
        self._max_snapshots = max_snapshots
        self._total_recoveries = 0
        self._successful_recoveries = 0
        self._failed_recoveries = 0
        self._lock = threading.Lock()

    # =========================================================================
    # Capture
    # =========================================================================

    def capture(
        self,
        session_id: str,
        state: dict[str, Any],
        *,
        reason: SnapshotReason = SnapshotReason.MANUAL,
        label: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        Capture a state snapshot.

        Args:
            session_id: Session identifier
            state: State data to capture (deep-copied)
            reason: Why this snapshot is being taken
            label: Optional human-readable label
            metadata: Optional additional metadata

        Returns:
            Snapshot ID
        """
        snapshot_id = uuid.uuid4().hex[:16]
        snapshot = StateSnapshot(
            snapshot_id=snapshot_id,
            session_id=session_id,
            state=copy.deepcopy(state),
            reason=reason,
            label=label,
            metadata=metadata or {},
        )

        with self._lock:
            session_snaps = self._snapshots[session_id]
            session_snaps.append(snapshot)
            self._snapshot_index[snapshot_id] = snapshot

            # Evict oldest if over limit
            while len(session_snaps) > self._max_snapshots:
                oldest = session_snaps.pop(0)
                self._snapshot_index.pop(oldest.snapshot_id, None)

        return snapshot_id

    def savepoint(
        self,
        session_id: str,
        state: dict[str, Any],
        label: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Create a named savepoint (convenience for capture with SAVEPOINT reason)."""
        return self.capture(
            session_id,
            state,
            reason=SnapshotReason.SAVEPOINT,
            label=label,
            metadata=metadata,
        )

    # =========================================================================
    # Query
    # =========================================================================

    def get_snapshot(self, snapshot_id: str) -> StateSnapshot | None:
        """Get a snapshot by ID."""
        return self._snapshot_index.get(snapshot_id)

    def latest(self, session_id: str) -> StateSnapshot | None:
        """Get the latest snapshot for a session."""
        with self._lock:
            snaps = self._snapshots.get(session_id, [])
            return snaps[-1] if snaps else None

    def list_snapshots(
        self,
        session_id: str,
        *,
        reason: SnapshotReason | None = None,
    ) -> list[StateSnapshot]:
        """List snapshots for a session, optionally filtered by reason."""
        with self._lock:
            snaps = list(self._snapshots.get(session_id, []))
        if reason is not None:
            snaps = [s for s in snaps if s.reason == reason]
        return snaps

    def find_savepoint(self, session_id: str, label: str) -> StateSnapshot | None:
        """Find a savepoint by label."""
        with self._lock:
            snaps = self._snapshots.get(session_id, [])
            for snap in reversed(snaps):
                if snap.reason == SnapshotReason.SAVEPOINT and snap.label == label:
                    return snap
        return None

    # =========================================================================
    # Recovery
    # =========================================================================

    def recover(
        self,
        session_id: str,
        *,
        snapshot_id: str | None = None,
        label: str | None = None,
    ) -> RecoveryResult:
        """
        Recover state from a snapshot.

        Priority: snapshot_id > label > latest.

        Args:
            session_id: Session to recover
            snapshot_id: Specific snapshot to recover from
            label: Savepoint label to recover from

        Returns:
            RecoveryResult with recovered state
        """
        with self._lock:
            self._total_recoveries += 1

            snapshot = None
            if snapshot_id:
                snapshot = self._snapshot_index.get(snapshot_id)
                if snapshot and snapshot.session_id != session_id:
                    snapshot = None  # Wrong session
            elif label:
                snaps = self._snapshots.get(session_id, [])
                for s in reversed(snaps):
                    if s.reason == SnapshotReason.SAVEPOINT and s.label == label:
                        snapshot = s
                        break
            else:
                snaps = self._snapshots.get(session_id, [])
                snapshot = snaps[-1] if snaps else None

            if snapshot is None:
                self._failed_recoveries += 1
                return RecoveryResult(
                    success=False,
                    session_id=session_id,
                    reason="No snapshot found",
                )

            self._successful_recoveries += 1
            return RecoveryResult(
                success=True,
                snapshot_id=snapshot.snapshot_id,
                session_id=session_id,
                state=copy.deepcopy(snapshot.state),
                reason=f"Recovered from {snapshot.reason.value} snapshot",
            )

    def rollback(self, session_id: str, steps: int = 1) -> RecoveryResult:
        """
        Roll back N snapshots.

        Args:
            session_id: Session to roll back
            steps: Number of snapshots to roll back (1 = previous)

        Returns:
            RecoveryResult with the state at that point
        """
        with self._lock:
            self._total_recoveries += 1
            snaps = self._snapshots.get(session_id, [])

            if len(snaps) < steps + 1:
                # Not enough snapshots
                if snaps:
                    # Use oldest available
                    target = snaps[0]
                else:
                    self._failed_recoveries += 1
                    return RecoveryResult(
                        success=False,
                        session_id=session_id,
                        reason=f"Not enough snapshots (have {len(snaps)}, need {steps + 1})",
                    )
            else:
                target = snaps[-(steps + 1)]

            self._successful_recoveries += 1
            return RecoveryResult(
                success=True,
                snapshot_id=target.snapshot_id,
                session_id=session_id,
                state=copy.deepcopy(target.state),
                reason=f"Rolled back {steps} step(s)",
            )

    # =========================================================================
    # Cleanup
    # =========================================================================

    def delete_snapshot(self, snapshot_id: str) -> bool:
        """Delete a specific snapshot."""
        with self._lock:
            snapshot = self._snapshot_index.pop(snapshot_id, None)
            if snapshot is None:
                return False
            snaps = self._snapshots.get(snapshot.session_id, [])
            self._snapshots[snapshot.session_id] = [s for s in snaps if s.snapshot_id != snapshot_id]
            return True

    def delete_session(self, session_id: str) -> int:
        """Delete all snapshots for a session. Returns count deleted."""
        with self._lock:
            snaps = self._snapshots.pop(session_id, [])
            for s in snaps:
                self._snapshot_index.pop(s.snapshot_id, None)
            return len(snaps)

    def cleanup_old(self, max_age_seconds: float) -> int:
        """Remove snapshots older than max_age. Returns count removed."""
        now = time.monotonic()
        removed = 0
        with self._lock:
            for session_id in list(self._snapshots.keys()):
                snaps = self._snapshots[session_id]
                keep = []
                for s in snaps:
                    if now - s.timestamp > max_age_seconds:
                        self._snapshot_index.pop(s.snapshot_id, None)
                        removed += 1
                    else:
                        keep.append(s)
                if keep:
                    self._snapshots[session_id] = keep
                else:
                    del self._snapshots[session_id]
        return removed

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> RecoveryStats:
        """Get recovery statistics."""
        with self._lock:
            total_snaps = sum(len(v) for v in self._snapshots.values())
            return RecoveryStats(
                total_snapshots=total_snaps,
                total_recoveries=self._total_recoveries,
                successful_recoveries=self._successful_recoveries,
                failed_recoveries=self._failed_recoveries,
                sessions_tracked=len(self._snapshots),
            )

    # =========================================================================
    # State
    # =========================================================================

    @property
    def session_count(self) -> int:
        return len(self._snapshots)

    @property
    def snapshot_count(self) -> int:
        return len(self._snapshot_index)

    def session_snapshot_count(self, session_id: str) -> int:
        """Get snapshot count for a specific session."""
        return len(self._snapshots.get(session_id, []))

    def clear(self) -> None:
        """Clear all data."""
        with self._lock:
            self._snapshots.clear()
            self._snapshot_index.clear()
            self._total_recoveries = 0
            self._successful_recoveries = 0
            self._failed_recoveries = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_count": self.session_count,
            "snapshot_count": self.snapshot_count,
            "stats": self.get_stats().to_dict(),
        }


# =============================================================================
# Global Instance
# =============================================================================

_manager: StateRecoveryManager | None = None
_manager_lock = threading.Lock()


def get_recovery_manager() -> StateRecoveryManager:
    """Get or create the global state recovery manager."""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = StateRecoveryManager()
    return _manager


def reset_recovery_manager() -> None:
    """Reset the global state recovery manager (for testing)."""
    global _manager
    _manager = None
