"""
SessionWorkspaceManager - Isolated Workspaces for Session Isolation.

NEXUS V9.7.1 - Context Bleeding Fix (Improved)

V9.7.1 HOME Spoofing (replaces V9.7 CWD Isolation):
- V9.7 CWD Isolation caused "ghost files" (writes to wrong directory)
- V9.7.1 uses HOME spoofing: CWD stays at project root, HOME is isolated
- Gemini CLI stores sessions in ~/.gemini/tmp/<hash(cwd)>/chats/
- Different HOME = Different session storage = Isolation without ghost files

The key insight:
- Gemini CLI uses os.homedir() which respects $HOME / %USERPROFILE%
- By setting a different HOME per agent, sessions are isolated
- CWD stays at project root, so file operations work correctly

Usage:
    manager = SessionWorkspaceManager(Path("workspace"))

    # V9.7.1: Get isolated environment for Gemini subprocess
    isolated_env = manager.get_isolated_env("task_123_lead", "swarm")

    # Pass to subprocess (CWD stays at project root!)
    subprocess.Popen(cmd, env=isolated_env, cwd=workspace_path)

Author: Claude (NEXUS V9.7 -> V9.7.1)
Date: 2025-12-13
"""

from __future__ import annotations

import contextlib
import logging
import shutil
from datetime import datetime
from pathlib import Path
from threading import RLock

from .home_isolator import HomeIsolator

logger = logging.getLogger(__name__)


class SessionWorkspaceManager:
    """
    Manages isolated environments for session isolation.

    V9.7.1: Uses HOME spoofing instead of CWD isolation.
    - HOME spoofing: CWD stays at project root, HOME is isolated
    - Prevents "ghost files" issue from V9.7 CWD isolation
    - Gemini CLI stores sessions in ~/.gemini/tmp/<hash(cwd)>/chats/
    - Different HOME = Different session storage = Isolation

    Architecture:
    ```
    workspace/
    +-- .sessions/                     # Legacy CWD isolation (V9.7)
    |   +-- [deprecated]
    +-- .session_homes/                # V9.7.1 HOME spoofing
        +-- swarm_task_001_lead/       # Isolated HOME for lead agent
        +-- swarm_task_002_support/    # Isolated HOME for support agent
    ```

    Thread Safety:
    - All methods are protected by RLock for concurrent access
    - Safe to use from multiple Swarm executors in parallel

    Example:
        >>> manager = SessionWorkspaceManager(Path("workspace"))
        >>> # V9.7.1: Get isolated env (not workspace!)
        >>> isolated_env = manager.get_isolated_env("task_001_lead", "swarm")
        >>> # Pass to subprocess (CWD stays at project root)
        >>> subprocess.Popen(cmd, env=isolated_env, cwd=workspace_path)
    """

    def __init__(self, base_workspace: Path) -> None:
        """
        Initialize the workspace manager.

        Args:
            base_workspace: Path to the main workspace directory.
                           Session homes will be created under
                           base_workspace/.session_homes/
        """
        self.base_workspace = Path(base_workspace)
        self.sessions_dir = self.base_workspace / ".sessions"  # Legacy V9.7
        self._lock = RLock()
        self._active_workspaces: dict[str, Path] = {}
        self._creation_times: dict[str, datetime] = {}

        # V9.7.1: Initialize HOME isolator
        self._home_isolator = HomeIsolator(base_workspace)

        # Ensure sessions directory exists (legacy compat)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

        logger.debug(f"SessionWorkspaceManager initialized: {self.base_workspace}")

    def get_or_create_workspace(self, session_id: str, session_type: str = "swarm") -> Path:
        """
        Get or create an isolated workspace for a session.

        The workspace is a subdirectory under .sessions/ that provides
        isolation for Gemini CLI's session management. Each unique
        (session_type, session_id) combination gets its own directory.

        Args:
            session_id: Unique session identifier (e.g., "task_001_lead")
            session_type: Type of session - one of:
                - "fsm": FSM single-threaded mode
                - "hive": HiveMind per-task isolation
                - "swarm": Swarm parallel isolation (default)
                - "agent": Spawned agent isolation

        Returns:
            Path to the isolated workspace directory

        Example:
            >>> ws = manager.get_or_create_workspace("task_001_lead", "swarm")
            >>> # Returns: workspace/.sessions/swarm_task_001_lead/
        """
        with self._lock:
            workspace_key = f"{session_type}_{session_id}"

            # Return cached workspace if exists
            if workspace_key in self._active_workspaces:
                return self._active_workspaces[workspace_key]

            # Create new workspace directory
            workspace_path = self.sessions_dir / workspace_key
            workspace_path.mkdir(parents=True, exist_ok=True)

            # Setup any necessary links or structure
            self._setup_workspace(workspace_path)

            # Cache for fast access
            self._active_workspaces[workspace_key] = workspace_path
            self._creation_times[workspace_key] = datetime.now()

            logger.debug(f"Created isolated workspace: {workspace_path}")
            return workspace_path

    def _setup_workspace(self, workspace_path: Path) -> None:
        """
        Setup an isolated workspace with any necessary structure.

        Currently minimal - Gemini CLI uses --include-directories for
        parent code access, so no symlinks are needed.

        Args:
            workspace_path: Path to the workspace being set up
        """
        # Create _IO_BUFFER subdirectory for Gemini context files
        io_buffer = workspace_path / "_IO_BUFFER"
        io_buffer.mkdir(exist_ok=True)

        # No symlinks needed - Gemini uses --include-directories flag
        # to access parent NEXUS code

    def get_workspace(self, session_id: str, session_type: str = "swarm") -> Path | None:
        """
        Get an existing workspace without creating it.

        Args:
            session_id: Session identifier
            session_type: Type of session

        Returns:
            Path to workspace if it exists, None otherwise
        """
        with self._lock:
            workspace_key = f"{session_type}_{session_id}"
            return self._active_workspaces.get(workspace_key)

    def cleanup_workspace(self, session_id: str, session_type: str = "swarm") -> bool:
        """
        Remove an isolated workspace after session completion.

        Should be called when a task/session is complete to free disk space.
        Safe to call even if workspace doesn't exist.

        Args:
            session_id: Session identifier
            session_type: Type of session

        Returns:
            True if workspace was found and removed, False otherwise
        """
        with self._lock:
            workspace_key = f"{session_type}_{session_id}"
            workspace_path = self._active_workspaces.pop(workspace_key, None)
            self._creation_times.pop(workspace_key, None)

            if workspace_path and workspace_path.exists():
                try:
                    shutil.rmtree(workspace_path, ignore_errors=True)
                    logger.debug(f"Cleaned up workspace: {workspace_path}")
                    return True
                except Exception as e:
                    logger.warning(f"Failed to cleanup workspace {workspace_path}: {e}")
                    return False
            return False

    def cleanup_old_workspaces(self, max_age_hours: int = 24) -> int:
        """
        Remove workspaces older than max_age_hours.

        Called periodically to prevent disk space accumulation.

        Args:
            max_age_hours: Maximum age in hours for workspaces

        Returns:
            Number of workspaces removed
        """
        from datetime import timedelta

        with self._lock:
            cutoff = datetime.now() - timedelta(hours=max_age_hours)
            to_remove = []

            for workspace_key, created_at in self._creation_times.items():
                if created_at < cutoff:
                    to_remove.append(workspace_key)

            count = 0
            for workspace_key in to_remove:
                workspace_path = self._active_workspaces.pop(workspace_key, None)
                self._creation_times.pop(workspace_key, None)

                if workspace_path and workspace_path.exists():
                    try:
                        shutil.rmtree(workspace_path, ignore_errors=True)
                        count += 1
                    except Exception:
                        pass

            if count > 0:
                logger.info(f"Cleaned up {count} old session workspaces")

            return count

    def get_default_workspace(self) -> Path:
        """
        Get the default workspace (for FSM single-threaded mode).

        FSM doesn't need isolation - it's single-threaded and sequential.

        Returns:
            The base workspace path
        """
        return self.base_workspace

    def get_isolated_env(self, session_id: str, session_type: str = "swarm") -> dict[str, str]:
        """
        V9.7.1: Get isolated environment for Gemini subprocess.

        Uses HOME spoofing instead of CWD isolation to prevent ghost files.
        The subprocess will have:
        - Same CWD (project root) - file operations work correctly
        - Different HOME - session storage is isolated

        Args:
            session_id: Session identifier (e.g., "task_001_lead")
            session_type: Type of session ("swarm", "hive", "agent", etc.)

        Returns:
            Environment dict with isolated HOME/USERPROFILE

        Example:
            >>> env = manager.get_isolated_env("task_001_lead", "swarm")
            >>> subprocess.Popen(cmd, env=env, cwd=workspace_path)
        """
        workspace_key = f"{session_type}_{session_id}"
        return self._home_isolator.get_isolated_env(workspace_key)

    def cleanup_isolated_env(self, session_id: str, session_type: str = "swarm") -> bool:
        """
        V9.7.1: Cleanup isolated HOME directory.

        Should be called when a session completes to free disk space.

        Args:
            session_id: Session identifier
            session_type: Type of session

        Returns:
            True if cleanup succeeded
        """
        workspace_key = f"{session_type}_{session_id}"
        return self._home_isolator.cleanup_home(workspace_key)

    def list_active_workspaces(self) -> dict[str, Path]:
        """
        List all active session workspaces.

        Returns:
            Dictionary mapping workspace_key to Path
        """
        with self._lock:
            return dict(self._active_workspaces)

    def get_stats(self) -> dict[str, int]:
        """
        Get workspace manager statistics.

        Returns:
            Dictionary with stats:
            - active_count: Number of active workspaces
            - total_size_mb: Approximate total size in MB
        """
        with self._lock:
            active_count = len(self._active_workspaces)

            # Calculate approximate size
            total_size = 0
            for workspace_path in self._active_workspaces.values():
                if workspace_path.exists():
                    with contextlib.suppress(Exception):
                        total_size += sum(f.stat().st_size for f in workspace_path.rglob("*") if f.is_file())

            return {"active_count": active_count, "total_size_mb": round(total_size / (1024 * 1024), 2)}

    def __repr__(self) -> str:
        stats = self.get_stats()
        return f"SessionWorkspaceManager(base={self.base_workspace}, active={stats['active_count']})"


# =============================================================================
# V10 PRISM: Multi-Tenant Workspace Manager Access
# =============================================================================
_workspace_manager: SessionWorkspaceManager | None = None
# V11 FIX F30: Thread-safe singleton lock
_workspace_manager_lock = RLock()


def get_workspace_manager(base_workspace: Path | None = None) -> SessionWorkspaceManager:
    """
    Get the workspace manager for the current tenant context.

    V10 PRISM: Returns tenant-scoped manager via ServiceFactory.
    Falls back to global singleton if no context is active.

    Args:
        base_workspace: Base workspace path (required on first call in legacy mode)

    Returns:
        SessionWorkspaceManager instance scoped to current tenant
    """
    # V10: Try ServiceFactory first (tenant-scoped)
    try:
        from ..context import has_active_session

        if has_active_session():
            from ..factory import ServiceFactory

            return ServiceFactory.get_workspace_manager()
    except ImportError:
        pass  # context module not available, use legacy

    # Legacy fallback: global singleton
    # V11 FIX F30: Thread-safe singleton initialization
    global _workspace_manager
    if _workspace_manager is None:
        with _workspace_manager_lock:
            # Double-check locking pattern
            if _workspace_manager is None:
                if base_workspace is None:
                    raise ValueError("base_workspace required for first initialization")
                _workspace_manager = SessionWorkspaceManager(base_workspace)
    return _workspace_manager


def reset_workspace_manager() -> None:
    """
    Reset the global workspace manager (for testing).

    Note: In V10, also clears ServiceFactory cache for current tenant.
    """
    global _workspace_manager
    _workspace_manager = None

    # V10: Also clear factory cache
    try:
        from ..context import get_current_session_or_none
        from ..factory import ServiceFactory

        ctx = get_current_session_or_none()
        if ctx:
            ServiceFactory.clear_tenant_cache(ctx.tenant_id)
    except ImportError:
        pass
