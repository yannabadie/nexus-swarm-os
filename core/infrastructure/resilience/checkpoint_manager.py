"""
Checkpoint Manager - Deterministic checkpoints for pause/resume.

V12.4 COGNITIVE BOOST - Task #50

Creates checkpoints at phase boundaries for long-running tasks.
Enables pause/resume, rewind-to-checkpoint, and replay for debugging.

Usage:
    from core.infrastructure.resilience.checkpoint_manager import get_checkpoint_manager

    mgr = get_checkpoint_manager()

    # Create checkpoint
    cp_id = mgr.create("session_1", "analysis_complete",
                        state={"findings": [...], "phase": 3})

    # List checkpoints
    checkpoints = mgr.list("session_1")

    # Restore from checkpoint
    state = mgr.restore(cp_id)

    # Rewind to checkpoint (removes later checkpoints)
    mgr.rewind("session_1", cp_id)
"""

from __future__ import annotations

import builtins
import json
import logging
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

DEFAULT_CHECKPOINT_DIR = "workspace/.nexus/checkpoints"
MAX_CHECKPOINTS_PER_SESSION = 50


# =============================================================================
# Types
# =============================================================================


@dataclass
class Checkpoint:
    """A saved checkpoint."""

    checkpoint_id: str
    session_id: str
    label: str
    state: dict[str, Any]
    created_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    sequence: int = 0  # Order within session

    def __post_init__(self):
        if self.created_at == 0.0:
            self.created_at = time.monotonic()

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "session_id": self.session_id,
            "label": self.label,
            "state": self.state,
            "created_at": self.created_at,
            "metadata": self.metadata,
            "sequence": self.sequence,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Checkpoint:
        return cls(
            checkpoint_id=data["checkpoint_id"],
            session_id=data["session_id"],
            label=data.get("label", ""),
            state=data.get("state", {}),
            created_at=data.get("created_at", 0.0),
            metadata=data.get("metadata", {}),
            sequence=data.get("sequence", 0),
        )


@dataclass
class CheckpointInfo:
    """Lightweight checkpoint summary (without full state)."""

    checkpoint_id: str
    session_id: str
    label: str
    sequence: int
    created_at: float
    state_keys: list[str]
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "session_id": self.session_id,
            "label": self.label,
            "sequence": self.sequence,
            "created_at": self.created_at,
            "state_keys": self.state_keys,
            "metadata": self.metadata,
        }


@dataclass
class RestoreResult:
    """Result of restoring from a checkpoint."""

    checkpoint_id: str
    session_id: str
    label: str
    state: dict[str, Any]
    sequence: int
    success: bool = True
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "session_id": self.session_id,
            "label": self.label,
            "sequence": self.sequence,
            "success": self.success,
            "error": self.error,
            "state_keys": list(self.state.keys()),
        }


# =============================================================================
# Checkpoint Manager
# =============================================================================


class CheckpointManager:
    """
    Manages deterministic checkpoints for pause/resume.

    Supports:
    - Creating checkpoints with state snapshots
    - Listing checkpoints per session
    - Restoring state from any checkpoint
    - Rewinding to a checkpoint (removing later ones)
    - Persistence to disk (optional)
    - Session-based organization
    """

    def __init__(
        self,
        *,
        checkpoint_dir: str | None = None,
        persist: bool = True,
        max_per_session: int = MAX_CHECKPOINTS_PER_SESSION,
    ):
        self._checkpoints: dict[str, Checkpoint] = {}  # id -> Checkpoint
        self._sessions: dict[str, list[str]] = defaultdict(list)  # session -> [ids]
        self._sequences: dict[str, int] = defaultdict(int)  # session -> next seq
        self._checkpoint_dir = Path(checkpoint_dir) if checkpoint_dir else Path(DEFAULT_CHECKPOINT_DIR)
        self._persist = persist
        self._max_per_session = max_per_session
        self._lock = threading.Lock()

        if self._persist:
            self._load()

    # =========================================================================
    # Create Checkpoint
    # =========================================================================

    def create(
        self,
        session_id: str,
        label: str,
        *,
        state: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        Create a checkpoint.

        Args:
            session_id: Session identifier
            label: Human-readable label (e.g. "analysis_complete")
            state: State snapshot to save
            metadata: Optional metadata

        Returns:
            Checkpoint ID
        """
        cp_id = uuid.uuid4().hex[:16]

        with self._lock:
            seq = self._sequences[session_id]
            self._sequences[session_id] = seq + 1

            cp = Checkpoint(
                checkpoint_id=cp_id,
                session_id=session_id,
                label=label,
                state=state or {},
                metadata=metadata or {},
                sequence=seq,
            )
            self._checkpoints[cp_id] = cp
            self._sessions[session_id].append(cp_id)

            # Enforce max checkpoints per session
            session_cps = self._sessions[session_id]
            while len(session_cps) > self._max_per_session:
                oldest_id = session_cps.pop(0)
                self._checkpoints.pop(oldest_id, None)

        if self._persist:
            self._save()

        return cp_id

    # =========================================================================
    # Query
    # =========================================================================

    def get(self, checkpoint_id: str) -> Checkpoint | None:
        """Get a checkpoint by ID."""
        with self._lock:
            return self._checkpoints.get(checkpoint_id)

    def list(self, session_id: str) -> builtins.list[CheckpointInfo]:
        """
        List all checkpoints for a session.

        Returns CheckpointInfo (lightweight, no state data).
        """
        with self._lock:
            cp_ids = self._sessions.get(session_id, [])
            results = []
            for cp_id in cp_ids:
                cp = self._checkpoints.get(cp_id)
                if cp:
                    results.append(
                        CheckpointInfo(
                            checkpoint_id=cp.checkpoint_id,
                            session_id=cp.session_id,
                            label=cp.label,
                            sequence=cp.sequence,
                            created_at=cp.created_at,
                            state_keys=list(cp.state.keys()),
                            metadata=cp.metadata,
                        )
                    )
        return results

    def latest(self, session_id: str) -> Checkpoint | None:
        """Get the most recent checkpoint for a session."""
        with self._lock:
            cp_ids = self._sessions.get(session_id, [])
            if not cp_ids:
                return None
            return self._checkpoints.get(cp_ids[-1])

    def exists(self, checkpoint_id: str) -> bool:
        """Check if a checkpoint exists."""
        return checkpoint_id in self._checkpoints

    # =========================================================================
    # Restore
    # =========================================================================

    def restore(self, checkpoint_id: str) -> RestoreResult:
        """
        Restore state from a checkpoint.

        Args:
            checkpoint_id: ID of checkpoint to restore

        Returns:
            RestoreResult with state data
        """
        with self._lock:
            cp = self._checkpoints.get(checkpoint_id)
            if cp is None:
                return RestoreResult(
                    checkpoint_id=checkpoint_id,
                    session_id="",
                    label="",
                    state={},
                    sequence=0,
                    success=False,
                    error="Checkpoint not found",
                )
            return RestoreResult(
                checkpoint_id=cp.checkpoint_id,
                session_id=cp.session_id,
                label=cp.label,
                state=dict(cp.state),  # Copy
                sequence=cp.sequence,
                success=True,
            )

    # =========================================================================
    # Rewind
    # =========================================================================

    def rewind(self, session_id: str, checkpoint_id: str) -> int:
        """
        Rewind to a checkpoint, removing all later checkpoints.

        Args:
            session_id: Session to rewind
            checkpoint_id: Checkpoint to rewind to

        Returns:
            Number of checkpoints removed
        """
        with self._lock:
            cp_ids = self._sessions.get(session_id, [])
            if checkpoint_id not in cp_ids:
                return 0

            idx = cp_ids.index(checkpoint_id)
            to_remove = cp_ids[idx + 1 :]  # Everything after target
            for rid in to_remove:
                self._checkpoints.pop(rid, None)
            self._sessions[session_id] = cp_ids[: idx + 1]

            # Reset sequence counter
            self._sequences[session_id] = idx + 1

        if self._persist:
            self._save()

        return len(to_remove)

    # =========================================================================
    # Delete
    # =========================================================================

    def delete(self, checkpoint_id: str) -> bool:
        """Delete a single checkpoint."""
        with self._lock:
            cp = self._checkpoints.pop(checkpoint_id, None)
            if cp is None:
                return False
            session_ids = self._sessions.get(cp.session_id, [])
            if checkpoint_id in session_ids:
                session_ids.remove(checkpoint_id)
        if self._persist:
            self._save()
        return True

    def delete_session(self, session_id: str) -> int:
        """Delete all checkpoints for a session."""
        with self._lock:
            cp_ids = self._sessions.pop(session_id, [])
            count = 0
            for cp_id in cp_ids:
                if self._checkpoints.pop(cp_id, None) is not None:
                    count += 1
            self._sequences.pop(session_id, None)
        if self._persist:
            self._save()
        return count

    # =========================================================================
    # Cleanup
    # =========================================================================

    def cleanup(self, *, max_age_seconds: float = 0) -> int:
        """
        Remove old checkpoints.

        Args:
            max_age_seconds: Remove checkpoints older than this (0 = remove all)

        Returns:
            Number of checkpoints removed
        """
        now = time.monotonic()
        to_remove = []

        with self._lock:
            for cp_id, cp in self._checkpoints.items():
                if max_age_seconds == 0 or (now - cp.created_at) > max_age_seconds:
                    to_remove.append(cp_id)

            for cp_id in to_remove:
                cp = self._checkpoints.pop(cp_id, None)
                if cp:
                    session_ids = self._sessions.get(cp.session_id, [])
                    if cp_id in session_ids:
                        session_ids.remove(cp_id)

        if self._persist and to_remove:
            self._save()

        return len(to_remove)

    # =========================================================================
    # State
    # =========================================================================

    @property
    def checkpoint_count(self) -> int:
        return len(self._checkpoints)

    @property
    def session_count(self) -> int:
        return len([s for s, ids in self._sessions.items() if ids])

    def get_sessions(self) -> builtins.list[str]:
        """List all sessions with checkpoints."""
        return sorted(s for s, ids in self._sessions.items() if ids)

    def clear(self) -> None:
        """Clear all checkpoints."""
        with self._lock:
            self._checkpoints.clear()
            self._sessions.clear()
            self._sequences.clear()

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_count": self.checkpoint_count,
            "session_count": self.session_count,
            "sessions": {sid: len(ids) for sid, ids in self._sessions.items() if ids},
        }

    # =========================================================================
    # Persistence
    # =========================================================================

    def _save(self) -> None:
        if not self._persist:
            return
        try:
            self._checkpoint_dir.mkdir(parents=True, exist_ok=True)
            index_file = self._checkpoint_dir / "index.json"
            data = {
                "checkpoints": {cp_id: cp.to_dict() for cp_id, cp in self._checkpoints.items()},
                "sessions": dict(self._sessions),
                "sequences": dict(self._sequences),
            }
            index_file.write_text(
                json.dumps(data, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as e:
            _logger.warning("Failed to save checkpoints: %s", e)

    def _load(self) -> None:
        index_file = self._checkpoint_dir / "index.json"
        if not index_file.exists():
            return
        try:
            data = json.loads(index_file.read_text(encoding="utf-8"))
            for cp_id, cp_data in data.get("checkpoints", {}).items():
                self._checkpoints[cp_id] = Checkpoint.from_dict(cp_data)
            for sid, ids in data.get("sessions", {}).items():
                self._sessions[sid] = ids
            for sid, seq in data.get("sequences", {}).items():
                self._sequences[sid] = seq
        except (json.JSONDecodeError, KeyError) as e:
            _logger.warning("Failed to load checkpoints: %s", e)


# =============================================================================
# Global Instance
# =============================================================================

_manager: CheckpointManager | None = None
_manager_lock = threading.Lock()


def get_checkpoint_manager() -> CheckpointManager:
    """Get or create the global checkpoint manager."""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = CheckpointManager()
    return _manager


def reset_checkpoint_manager() -> None:
    """Reset the global checkpoint manager (for testing)."""
    global _manager
    _manager = None
