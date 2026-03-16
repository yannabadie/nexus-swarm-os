"""
SwarmSessionManager - Session Isolation for Parallel Task Execution.

NEXUS V7.5 HIVE MIND - Phase 7: Session Isolation & Context Management

This module manages isolated sessions for Swarm tasks to prevent "Context Bleeding"
where multiple parallel tasks would share and corrupt each other's context.

Architecture:
- Each task gets a unique task_id
- Each agent-role combination in a task gets a unique session_uuid
- Sessions are persisted via AtomicJsonStore for crash recovery
- UUIDs can be passed to CLI drivers for session resumption

Author: Claude (NEXUS V7.5)
Date: 2025-12-04
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from threading import RLock
from typing import Any

from core.utils.atomic_store import AtomicJsonStore

# V10 FIX F9: Explicit logging for session operations
logger = logging.getLogger(__name__)


class SessionStatus(str, Enum):
    """Status of a session or task."""

    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SessionMode(str, Enum):
    """How a session should be initialized."""

    FRESH = "fresh"  # New session, no prior context
    CONTINUE = "continue"  # Resume from existing session
    BRANCH = "branch"  # Fork from existing session
    EPHEMERAL = "ephemeral"  # V7.8.2 Phase 7b: Memory-only, no persistence (for TRIVIAL tasks)


@dataclass
class AgentSession:
    """
    Represents a single agent's session within a task.

    Attributes:
        agent_id: The agent identifier (e.g., "gemini", "claude")
        session_uuid: Unique UUID for this session
        role: The role in the task (e.g., "lead", "worker", "support")
        created_at: ISO timestamp of session creation
        status: Current session status
        mode: How the session was initialized
        parent_session_uuid: For BRANCH mode, the session this was forked from
        workspace_path: V9.7 - Isolated workspace path for context bleeding fix
    """

    agent_id: str
    session_uuid: str
    role: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    status: SessionStatus = SessionStatus.ACTIVE
    mode: SessionMode = SessionMode.FRESH
    parent_session_uuid: str | None = None
    workspace_path: str | None = None  # V9.7: Isolated workspace for Gemini CLI

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "agent_id": self.agent_id,
            "session_uuid": self.session_uuid,
            "role": self.role,
            "created_at": self.created_at,
            "status": self.status.value if isinstance(self.status, SessionStatus) else self.status,
            "mode": self.mode.value if isinstance(self.mode, SessionMode) else self.mode,
            "parent_session_uuid": self.parent_session_uuid,
            "workspace_path": self.workspace_path,  # V9.7
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentSession:
        """Create from dictionary."""
        return cls(
            agent_id=data["agent_id"],
            session_uuid=data["session_uuid"],
            role=data["role"],
            created_at=data.get("created_at", datetime.now().isoformat()),
            status=SessionStatus(data.get("status", "active")),
            mode=SessionMode(data.get("mode", "fresh")),
            parent_session_uuid=data.get("parent_session_uuid"),
            workspace_path=data.get("workspace_path"),  # V9.7
        )


@dataclass
class TaskSession:
    """
    Represents a complete task with all its agent sessions.

    Attributes:
        task_id: Unique identifier for this task
        swarm_mode: The collaboration mode (PARALLEL, SEQUENTIAL, etc.)
        status: Current task status
        created_at: ISO timestamp of task creation
        completed_at: ISO timestamp of task completion (if completed)
        roles: Mapping of role names to AgentSession objects
        metadata: Additional task metadata
        is_ephemeral: V7.8.2 Phase 7b - If True, task is memory-only (no persistence)
    """

    task_id: str
    swarm_mode: str
    status: SessionStatus = SessionStatus.ACTIVE
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: str | None = None
    roles: dict[str, AgentSession] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    is_ephemeral: bool = False  # V7.8.2 Phase 7b: Memory-only task (no file persistence)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "task_id": self.task_id,
            "swarm_mode": self.swarm_mode,
            "status": self.status.value if isinstance(self.status, SessionStatus) else self.status,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "roles": {role: session.to_dict() for role, session in self.roles.items()},
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskSession:
        """Create from dictionary."""
        roles = {}
        for role, session_data in data.get("roles", {}).items():
            roles[role] = AgentSession.from_dict(session_data)

        return cls(
            task_id=data["task_id"],
            swarm_mode=data["swarm_mode"],
            status=SessionStatus(data.get("status", "active")),
            created_at=data.get("created_at", datetime.now().isoformat()),
            completed_at=data.get("completed_at"),
            roles=roles,
            metadata=data.get("metadata", {}),
        )


class SwarmSessionManager:
    """
    Manages session isolation for Swarm tasks.

    Prevents "Context Bleeding" by assigning unique session UUIDs to each
    agent-role combination within a task. Sessions are persisted via
    AtomicJsonStore for crash recovery.

    Attributes:
        workspace_path: Path to the workspace directory
        registry_path: Path to the session registry JSON file

    Example:
        >>> manager = SwarmSessionManager(Path("workspace"))
        >>> manager.create_task("task_001", "PARALLEL")
        >>> uuid = manager.get_or_create_session("task_001", "lead", "gemini")
        >>> # Pass uuid to gemini CLI: gemini --resume {uuid}
    """

    def __init__(self, workspace_path: Path) -> None:
        """
        Initialize the session manager.

        Args:
            workspace_path: Path to the workspace directory.
                           Registry will be stored at workspace/.nexus/session_registry.json
        """
        self.workspace_path = Path(workspace_path)
        self.registry_path = self.workspace_path / ".nexus" / "session_registry.json"
        self._store = AtomicJsonStore(self.registry_path)
        self._lock = RLock()

        # In-memory cache for fast access
        self._tasks: dict[str, TaskSession] = {}

        # V9.7: Workspace isolation for context bleeding fix
        from core.infrastructure.session import SessionWorkspaceManager

        self._workspace_manager = SessionWorkspaceManager(workspace_path)

        # Load existing registry
        self._load_registry()

    def _load_registry(self) -> None:
        """Load the session registry from disk."""
        with self._lock:
            try:
                data = self._store.load_safe()
                tasks_data = data.get("tasks", {})

                for task_id, task_data in tasks_data.items():
                    self._tasks[task_id] = TaskSession.from_dict(task_data)

                # V10 FIX F9: Log successful load
                if tasks_data:
                    logger.debug(f"Loaded {len(tasks_data)} tasks from registry")
            except Exception as e:
                # V10 FIX F9: Explicit logging fallback
                logger.error(f"Failed to load session registry: {e}")
                logger.warning("Starting with empty session registry (data may be lost)")
                self._tasks = {}

    def _save_registry(self) -> None:
        """Save the session registry to disk atomically."""
        with self._lock:
            data = {
                "version": "1.0",
                "updated_at": datetime.now().isoformat(),
                "tasks": {task_id: task.to_dict() for task_id, task in self._tasks.items()},
            }
            try:
                self._store.save(data)
                logger.debug(f"Saved {len(self._tasks)} tasks to registry")
            except Exception as e:
                # V10 FIX F9: Explicit logging fallback - continue in memory
                logger.error(f"Failed to save session registry: {e}")
                logger.warning("Session data is in memory only - will be lost on restart")

    def create_task(
        self, task_id: str, swarm_mode: str, metadata: dict[str, Any] | None = None, is_ephemeral: bool = False
    ) -> TaskSession:
        """
        Create a new task session.

        Args:
            task_id: Unique identifier for the task
            swarm_mode: Collaboration mode (PARALLEL, SEQUENTIAL, etc.)
            metadata: Optional additional metadata
            is_ephemeral: V7.8.2 Phase 7b - If True, task is memory-only (no file I/O)

        Returns:
            The created TaskSession

        Raises:
            ValueError: If task_id already exists
        """
        with self._lock:
            if task_id in self._tasks:
                raise ValueError(f"Task '{task_id}' already exists")

            task = TaskSession(
                task_id=task_id,
                swarm_mode=swarm_mode,
                status=SessionStatus.ACTIVE,
                metadata=metadata or {},
                is_ephemeral=is_ephemeral,
            )

            self._tasks[task_id] = task

            # V10 FIX F9: Log task creation
            logger.info(f"Created task {task_id} (mode={swarm_mode}, ephemeral={is_ephemeral})")

            # V7.8.2 Phase 7b: Skip persistence for ephemeral tasks
            if not is_ephemeral:
                self._save_registry()

            return task

    def get_task(self, task_id: str) -> TaskSession | None:
        """
        Get a task by ID.

        Args:
            task_id: The task identifier

        Returns:
            TaskSession if found, None otherwise
        """
        with self._lock:
            return self._tasks.get(task_id)

    def get_or_create_task(self, task_id: str, swarm_mode: str, metadata: dict[str, Any] | None = None) -> TaskSession:
        """
        Get existing task or create new one.

        Args:
            task_id: Unique identifier for the task
            swarm_mode: Collaboration mode (only used if creating)
            metadata: Optional metadata (only used if creating)

        Returns:
            The TaskSession (existing or newly created)
        """
        with self._lock:
            if task_id in self._tasks:
                return self._tasks[task_id]
            return self.create_task(task_id, swarm_mode, metadata)

    def get_or_create_session(
        self,
        task_id: str,
        role: str,
        agent_id: str,
        mode: SessionMode = SessionMode.FRESH,
        parent_session_uuid: str | None = None,
    ) -> str:
        """
        Get or create a session UUID for an agent-role combination in a task.

        This is the main method used by HybridSwarmEngine to obtain unique
        session UUIDs for passing to CLI drivers.

        V9.7: Also creates isolated workspace. Use get_workspace_path() to retrieve it.

        Args:
            task_id: The task identifier
            role: The role in the task (e.g., "lead", "worker")
            agent_id: The agent identifier (e.g., "gemini", "claude")
            mode: Session initialization mode
            parent_session_uuid: For BRANCH mode, the session to fork from

        Returns:
            Session UUID string

        Raises:
            ValueError: If task doesn't exist
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise ValueError(f"Task '{task_id}' not found. Create it first with create_task()")

            # Check if session already exists for this role
            if role in task.roles:
                return task.roles[role].session_uuid

            # V9.7: Create isolated workspace for this session
            workspace_path = self._workspace_manager.get_or_create_workspace(
                session_id=f"{task_id}_{role}", session_type="swarm"
            )

            # Create new session
            session_uuid = str(uuid.uuid4())
            session = AgentSession(
                agent_id=agent_id,
                session_uuid=session_uuid,
                role=role,
                mode=mode,
                parent_session_uuid=parent_session_uuid,
                workspace_path=str(workspace_path),  # V9.7: Store workspace path
            )

            task.roles[role] = session

            # V10 FIX F9: Log session creation
            logger.info(f"Created session for {agent_id}/{role} in task {task_id} (uuid={session_uuid[:8]}...)")

            # V7.8.2 Phase 7b: Skip persistence for ephemeral tasks
            if not task.is_ephemeral:
                self._save_registry()

            return session_uuid

    def get_session(self, task_id: str, role: str) -> AgentSession | None:
        """
        Get a specific session by task and role.

        Args:
            task_id: The task identifier
            role: The role to get

        Returns:
            AgentSession if found, None otherwise
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            return task.roles.get(role)

    def get_workspace_path(self, task_id: str, role: str) -> Path | None:
        """
        Get the isolated workspace path for a session.

        V9.7: Context Bleeding Fix - Returns the isolated workspace path.
        DEPRECATED in V9.7.1: Use get_isolated_env() instead for HOME spoofing.

        Args:
            task_id: The task identifier
            role: The role in the task

        Returns:
            Path to isolated workspace if session exists, None otherwise
        """
        session = self.get_session(task_id, role)
        if session and session.workspace_path:
            return Path(session.workspace_path)
        return None

    def get_isolated_env(self, task_id: str, role: str) -> dict[str, str] | None:
        """
        V9.7.1: Get isolated environment for Gemini subprocess.

        Uses HOME spoofing instead of CWD isolation to prevent ghost files.
        The subprocess will have:
        - Same CWD (project root) - file operations work correctly
        - Different HOME - session storage is isolated

        Args:
            task_id: The task identifier
            role: The role in the task

        Returns:
            Environment dict with isolated HOME/USERPROFILE, or None if no session

        Example:
            >>> env = manager.get_isolated_env("task_001", "lead")
            >>> subprocess.Popen(cmd, env=env, cwd=workspace_path)
        """
        session = self.get_session(task_id, role)
        if session is None:
            # V11 FIX F25: Log warning instead of silent None
            logger.warning(
                f"[ISOLATION] No session for task={task_id}, role={role} - "
                f"isolation disabled! Context may bleed between agents."
            )
            return None

        # Use workspace_manager's HOME spoofing
        return self._workspace_manager.get_isolated_env(session_id=f"{task_id}_{role}", session_type="swarm")

    def get_session_by_uuid(self, session_uuid: str) -> AgentSession | None:
        """
        Find a session by its UUID across all tasks.

        Args:
            session_uuid: The session UUID to find

        Returns:
            AgentSession if found, None otherwise
        """
        with self._lock:
            for task in self._tasks.values():
                for session in task.roles.values():
                    if session.session_uuid == session_uuid:
                        return session
            return None

    def list_active_sessions(self) -> list[dict[str, Any]]:
        """
        List all active sessions across all tasks.

        Returns:
            List of session info dictionaries with task context
        """
        with self._lock:
            sessions = []
            for task_id, task in self._tasks.items():
                if task.status == SessionStatus.ACTIVE:
                    for role, session in task.roles.items():
                        if session.status == SessionStatus.ACTIVE:
                            sessions.append(
                                {
                                    "task_id": task_id,
                                    "swarm_mode": task.swarm_mode,
                                    "role": role,
                                    "agent_id": session.agent_id,
                                    "session_uuid": session.session_uuid,
                                    "created_at": session.created_at,
                                }
                            )
            return sessions

    def list_active_tasks(self) -> list[TaskSession]:
        """
        List all active tasks.

        Returns:
            List of active TaskSession objects
        """
        with self._lock:
            return [task for task in self._tasks.values() if task.status == SessionStatus.ACTIVE]

    def complete_task(
        self, task_id: str, status: SessionStatus = SessionStatus.COMPLETED, cleanup_workspaces: bool = True
    ) -> bool:
        """
        Mark a task and all its sessions as completed.

        V9.7.1: Also cleans up isolated HOME directories by default.

        Args:
            task_id: The task to complete
            status: Final status (COMPLETED, FAILED, CANCELLED)
            cleanup_workspaces: V9.7.1 - Whether to cleanup isolated environments

        Returns:
            True if task was found and updated
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False

            task.status = status
            task.completed_at = datetime.now().isoformat()

            # Mark all sessions as completed and cleanup
            for role, session in task.roles.items():
                session.status = status
                # V9.7.1: Cleanup isolated HOME and workspace
                if cleanup_workspaces:
                    # Cleanup legacy workspace (V9.7)
                    self._workspace_manager.cleanup_workspace(session_id=f"{task_id}_{role}", session_type="swarm")
                    # Cleanup isolated HOME (V9.7.1)
                    self._workspace_manager.cleanup_isolated_env(session_id=f"{task_id}_{role}", session_type="swarm")

            self._save_registry()
            return True

    def complete_session(self, task_id: str, role: str, status: SessionStatus = SessionStatus.COMPLETED) -> bool:
        """
        Mark a specific session as completed.

        Args:
            task_id: The task identifier
            role: The role to complete
            status: Final status

        Returns:
            True if session was found and updated
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or role not in task.roles:
                return False

            task.roles[role].status = status
            self._save_registry()
            return True

    def cleanup_completed(self, max_age_hours: int = 24) -> int:
        """
        Remove completed tasks older than max_age_hours.

        Args:
            max_age_hours: Maximum age in hours for completed tasks

        Returns:
            Number of tasks removed
        """
        from datetime import timedelta

        with self._lock:
            cutoff = datetime.now() - timedelta(hours=max_age_hours)
            to_remove = []

            for task_id, task in self._tasks.items():
                if (
                    task.status in (SessionStatus.COMPLETED, SessionStatus.FAILED, SessionStatus.CANCELLED)
                    and task.completed_at
                ):
                    try:
                        completed_time = datetime.fromisoformat(task.completed_at)
                        if completed_time < cutoff:
                            to_remove.append(task_id)
                    except ValueError:
                        pass

            for task_id in to_remove:
                del self._tasks[task_id]

            if to_remove:
                self._save_registry()
                # V10 FIX F9: Log cleanup
                logger.info(f"Cleaned up {len(to_remove)} completed tasks older than {max_age_hours}h")

            return len(to_remove)

    def get_stats(self) -> dict[str, Any]:
        """
        Get session manager statistics.

        Returns:
            Dictionary with stats
        """
        with self._lock:
            active_tasks = sum(1 for t in self._tasks.values() if t.status == SessionStatus.ACTIVE)
            completed_tasks = sum(1 for t in self._tasks.values() if t.status == SessionStatus.COMPLETED)
            total_sessions = sum(len(t.roles) for t in self._tasks.values())
            active_sessions = sum(
                sum(1 for s in t.roles.values() if s.status == SessionStatus.ACTIVE) for t in self._tasks.values()
            )

            return {
                "total_tasks": len(self._tasks),
                "active_tasks": active_tasks,
                "completed_tasks": completed_tasks,
                "total_sessions": total_sessions,
                "active_sessions": active_sessions,
            }

    # ===== V7.5 Phase 8: Checkpoint Support for Self-Healing =====

    def create_checkpoint(self, task_id: str) -> str | None:
        """
        Create a checkpoint for a task's current state.

        V7.5 Phase 8: Self-Healing Swarm - enables rollback on mode failure.

        Args:
            task_id: The task to checkpoint

        Returns:
            Checkpoint ID string, or None if task not found
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None

            # Generate checkpoint ID
            checkpoint_id = f"cp_{task_id}_{datetime.now().strftime('%H%M%S')}"

            # Store checkpoint in task metadata
            if "checkpoints" not in task.metadata:
                task.metadata["checkpoints"] = {}

            # Snapshot current state
            checkpoint_data = {
                "checkpoint_id": checkpoint_id,
                "created_at": datetime.now().isoformat(),
                "swarm_mode": task.swarm_mode,
                "status": task.status.value,
                "roles_snapshot": {role: session.to_dict() for role, session in task.roles.items()},
                "metadata_snapshot": {
                    k: v
                    for k, v in task.metadata.items()
                    if k != "checkpoints"  # Don't nest checkpoints
                },
            }

            task.metadata["checkpoints"][checkpoint_id] = checkpoint_data
            self._save_registry()

            return checkpoint_id

    def restore_checkpoint(self, task_id: str, checkpoint_id: str) -> bool:
        """
        Restore a task to a previous checkpoint state.

        V7.5 Phase 8: Self-Healing Swarm - rollback on mode failure.

        Args:
            task_id: The task to restore
            checkpoint_id: The checkpoint to restore to

        Returns:
            True if restore succeeded, False otherwise
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False

            checkpoints = task.metadata.get("checkpoints", {})
            checkpoint = checkpoints.get(checkpoint_id)
            if checkpoint is None:
                return False

            # Restore swarm mode
            task.swarm_mode = checkpoint["swarm_mode"]

            # Restore status
            task.status = SessionStatus(checkpoint["status"])

            # Restore roles
            task.roles = {}
            for role, session_data in checkpoint["roles_snapshot"].items():
                task.roles[role] = AgentSession.from_dict(session_data)

            # Restore metadata (preserving checkpoints)
            preserved_checkpoints = task.metadata.get("checkpoints", {})
            task.metadata = checkpoint["metadata_snapshot"].copy()
            task.metadata["checkpoints"] = preserved_checkpoints
            task.metadata["restored_from"] = checkpoint_id
            task.metadata["restored_at"] = datetime.now().isoformat()

            self._save_registry()
            return True

    def get_checkpoint(self, task_id: str, checkpoint_id: str) -> dict[str, Any] | None:
        """
        Get checkpoint data.

        Args:
            task_id: The task ID
            checkpoint_id: The checkpoint ID

        Returns:
            Checkpoint data dict or None
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None

            return task.metadata.get("checkpoints", {}).get(checkpoint_id)

    def list_checkpoints(self, task_id: str) -> list[str]:
        """
        List all checkpoint IDs for a task.

        Args:
            task_id: The task ID

        Returns:
            List of checkpoint IDs
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return []

            return list(task.metadata.get("checkpoints", {}).keys())

    def __repr__(self) -> str:
        stats = self.get_stats()
        return f"SwarmSessionManager(tasks={stats['total_tasks']}, active={stats['active_tasks']})"


def generate_task_id(prefix: str = "task") -> str:
    """
    Generate a unique task ID.

    Args:
        prefix: Prefix for the task ID

    Returns:
        Unique task ID string (e.g., "task_20251204_151800_abc123")
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    short_uuid = str(uuid.uuid4())[:8]
    return f"{prefix}_{timestamp}_{short_uuid}"
