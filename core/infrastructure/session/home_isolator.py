"""
HomeIsolator - Session Isolation via HOME Environment Spoofing.

NEXUS V9.7.1 - Context Bleeding Fix (Improved)

Problem with V9.7 CWD Isolation:
- Gemini CLI sandboxes file operations to CWD
- Changing CWD causes "ghost files" - written to isolated dir, not project root

Solution (V9.7.1 HOME Spoofing):
- Keep CWD at project root (file operations work correctly)
- Change HOME env var (session storage is isolated)
- Gemini CLI stores sessions in ~/.gemini/tmp/<hash(cwd)>/chats/
- Different HOME = Different session storage = Isolation without ghost files

Cross-platform:
- Linux/macOS: $HOME environment variable
- Windows: %USERPROFILE%, %HOMEDRIVE%, %HOMEPATH%

Node.js os.homedir() (used by Gemini CLI):
"On POSIX, it uses the $HOME environment variable if defined"
"On Windows, it uses the USERPROFILE environment variable"

Author: Claude (NEXUS V9.7.1)
Date: 2025-12-13
"""

import contextlib
import logging
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from threading import Lock

# V11 FIX F27: Logger for security warnings
logger = logging.getLogger(__name__)


class HomeIsolator:
    """
    Creates isolated HOME environments for subprocess session isolation.

    Key Insight:
    - Gemini CLI uses os.homedir() which respects $HOME / %USERPROFILE%
    - By setting a different HOME per agent, sessions are isolated
    - CWD stays at project root, so file operations work correctly

    Usage:
        isolator = HomeIsolator(workspace_path)

        # Get isolated environment for a session
        env = isolator.get_isolated_env("task_001_lead")

        # Pass to subprocess
        subprocess.Popen(cmd, env=env, cwd=workspace_path)

        # Cleanup after task completion
        isolator.cleanup_home("task_001_lead")
    """

    # V11 FIX F27: Regex pattern for session_id sanitization
    _SESSION_ID_PATTERN = re.compile(r"[^a-zA-Z0-9_-]")

    # V12.4 FIX F24: Enable workspace prefix by default for collision prevention
    def __init__(self, base_path: Path, use_workspace_prefix: bool = True):
        """
        Initialize HomeIsolator.

        Args:
            base_path: Base workspace path (project root)
            use_workspace_prefix: V11 F24 - Add workspace hash prefix to mitigate collisions
                                  V12.4: Enabled by default for safety
        """
        self.base_path = Path(base_path)
        self.homes_dir = self.base_path / ".session_homes"
        self.homes_dir.mkdir(parents=True, exist_ok=True)

        # V11 FIX F24: Workspace prefix for collision mitigation (V12.4: enabled by default)
        self._use_workspace_prefix = use_workspace_prefix

        # Thread safety for concurrent session creation
        self._lock = Lock()

        # Track creation times for cleanup
        self._creation_times: dict[str, datetime] = {}

        # V11 FIX F26: Reference counting for safe cleanup
        self._active_refs: dict[str, int] = {}

    def _sanitize_session_id(self, session_id: str) -> str:
        """
        V11 FIX F27: Sanitize session_id to prevent path traversal (CWE-22).
        V11 FIX F24: Add unique prefix to mitigate hash collisions.

        Removes any characters that could be used for path injection:
        - Path separators (/, \\)
        - Parent directory references (..)
        - Special characters

        Args:
            session_id: Raw session identifier

        Returns:
            Sanitized session_id safe for filesystem use
        """
        if not session_id:
            logger.warning("[SECURITY] Empty session_id provided, generating safe fallback")
            return f"nx_{hash('empty') % 10**8:08d}"

        # Replace any non-alphanumeric (except _ and -) with underscore
        sanitized = self._SESSION_ID_PATTERN.sub("_", session_id)

        # Ensure reasonable length (prevent DoS via very long names)
        if len(sanitized) > 64:
            logger.warning(f"[SECURITY] session_id too long ({len(session_id)}), truncating")
            sanitized = sanitized[:64]

        # Ensure not empty after sanitization
        if not sanitized or sanitized == "_" * len(sanitized):
            logger.warning(f"[SECURITY] session_id '{session_id[:20]}...' sanitized to empty, using hash")
            sanitized = f"nx_{hash(session_id) % 10**8:08d}"

        # V11 FIX F24: Optionally add workspace-unique prefix to mitigate hash collisions
        # Enable with use_workspace_prefix=True for multi-workspace deployments
        if self._use_workspace_prefix:
            workspace_hash = hash(str(self.base_path)) % 10**6
            return f"nx{workspace_hash:06d}_{sanitized}"

        return sanitized

    def get_isolated_env(self, session_id: str) -> dict[str, str]:
        """
        Get environment dict with isolated HOME for a session.

        The returned environment is a COPY of the current environment
        with HOME/USERPROFILE modified to point to an isolated directory.
        This ensures subprocess inherits all necessary env vars (PATH, etc.)
        while having isolated session storage.

        Args:
            session_id: Unique session identifier (e.g., "task_001_lead")

        Returns:
            Environment dict with HOME/USERPROFILE pointing to isolated directory
        """
        with self._lock:
            # V11 FIX F27: Sanitize session_id to prevent path traversal
            safe_session_id = self._sanitize_session_id(session_id)

            # Start with FULL current environment (critical for subprocess to work)
            env = os.environ.copy()

            # Create isolated home directory
            isolated_home = self.homes_dir / safe_session_id
            isolated_home.mkdir(parents=True, exist_ok=True)

            # Track creation time (use sanitized ID for consistency)
            if safe_session_id not in self._creation_times:
                self._creation_times[safe_session_id] = datetime.now()

            # Override HOME based on platform
            if sys.platform == "win32":
                # Windows: Set all HOME-related variables
                env["USERPROFILE"] = str(isolated_home)

                # Also set HOMEDRIVE and HOMEPATH for full Windows compat
                # Some tools use these instead of USERPROFILE
                drive = isolated_home.drive
                if drive:
                    env["HOMEDRIVE"] = drive
                    # HOMEPATH is relative to HOMEDRIVE
                    try:
                        homepath = str(isolated_home)[len(drive) :]
                        env["HOMEPATH"] = homepath
                    except Exception:
                        env["HOMEPATH"] = str(isolated_home)
                else:
                    env["HOMEDRIVE"] = "C:"
                    env["HOMEPATH"] = str(isolated_home)

                # V9.7.1-fix: Also override HOME on Windows
                # HOME may be inherited from Git Bash, WSL, or MSYS2
                # Node.js checks USERPROFILE, but Python/others may check HOME
                env["HOME"] = str(isolated_home)

                # V11 FIX F28: Isolate Windows app data directories
                appdata_dir = isolated_home / "AppData" / "Roaming"
                localappdata_dir = isolated_home / "AppData" / "Local"
                appdata_dir.mkdir(parents=True, exist_ok=True)
                localappdata_dir.mkdir(parents=True, exist_ok=True)
                env["APPDATA"] = str(appdata_dir)
                env["LOCALAPPDATA"] = str(localappdata_dir)
            else:
                # Linux/macOS: Just set HOME
                env["HOME"] = str(isolated_home)

                # V11 FIX F28: Isolate XDG Base Directory paths (Linux)
                # https://specifications.freedesktop.org/basedir-spec/basedir-spec-latest.html
                xdg_config = isolated_home / ".config"
                xdg_data = isolated_home / ".local" / "share"
                xdg_cache = isolated_home / ".cache"
                xdg_state = isolated_home / ".local" / "state"

                # Create directories
                for xdg_dir in [xdg_config, xdg_data, xdg_cache, xdg_state]:
                    xdg_dir.mkdir(parents=True, exist_ok=True)

                env["XDG_CONFIG_HOME"] = str(xdg_config)
                env["XDG_DATA_HOME"] = str(xdg_data)
                env["XDG_CACHE_HOME"] = str(xdg_cache)
                env["XDG_STATE_HOME"] = str(xdg_state)

            return env

    def get_home_path(self, session_id: str) -> Path | None:
        """
        Get the isolated home path for a session.

        Args:
            session_id: Session identifier

        Returns:
            Path to isolated home, or None if not created
        """
        # V11 FIX F27: Sanitize session_id to prevent path traversal
        safe_session_id = self._sanitize_session_id(session_id)
        isolated_home = self.homes_dir / safe_session_id
        if isolated_home.exists():
            return isolated_home
        return None

    # =========================================================================
    # V11 FIX F26: Reference Counting for Safe Cleanup
    # =========================================================================

    def acquire_env(self, session_id: str) -> dict[str, str]:
        """
        V11 FIX F26: Acquire isolated environment with reference counting.

        Increments the reference count for this session, preventing cleanup
        while the environment is in use. Call release_env() when done.

        Args:
            session_id: Session identifier

        Returns:
            Environment dict with isolated HOME
        """
        with self._lock:
            safe_session_id = self._sanitize_session_id(session_id)
            self._active_refs[safe_session_id] = self._active_refs.get(safe_session_id, 0) + 1
            logger.debug(f"[F26] Acquired env for {safe_session_id}, refs={self._active_refs[safe_session_id]}")

        return self.get_isolated_env(session_id)

    def release_env(self, session_id: str) -> int:
        """
        V11 FIX F26: Release isolated environment reference.

        Decrements the reference count. Cleanup is safe when count reaches 0.

        Args:
            session_id: Session identifier

        Returns:
            Remaining reference count (0 means safe to cleanup)
        """
        with self._lock:
            safe_session_id = self._sanitize_session_id(session_id)
            if safe_session_id in self._active_refs:
                self._active_refs[safe_session_id] = max(0, self._active_refs[safe_session_id] - 1)
                remaining = self._active_refs[safe_session_id]
                logger.debug(f"[F26] Released env for {safe_session_id}, refs={remaining}")
                return remaining
            return 0

    def get_ref_count(self, session_id: str) -> int:
        """
        V11 FIX F26: Get current reference count for a session.

        Args:
            session_id: Session identifier

        Returns:
            Current reference count
        """
        safe_session_id = self._sanitize_session_id(session_id)
        return self._active_refs.get(safe_session_id, 0)

    def cleanup_home(self, session_id: str, force: bool = False) -> bool:
        """
        Remove isolated home directory after session completion.

        V11 FIX F26: Now checks reference count before cleanup.
        Use force=True to cleanup regardless of reference count.

        Args:
            session_id: Session identifier to cleanup
            force: If True, cleanup even if references exist (use with caution)

        Returns:
            True if cleanup succeeded, False if directory didn't exist or still in use
        """
        with self._lock:
            # V11 FIX F27: Sanitize session_id to prevent path traversal
            safe_session_id = self._sanitize_session_id(session_id)

            # V11 FIX F26: Check reference count before cleanup
            ref_count = self._active_refs.get(safe_session_id, 0)
            if ref_count > 0 and not force:
                logger.warning(
                    f"[F26] Cannot cleanup {safe_session_id}: "
                    f"still in use (refs={ref_count}). Use force=True to override."
                )
                return False

            isolated_home = self.homes_dir / safe_session_id

            if isolated_home.exists():
                try:
                    shutil.rmtree(isolated_home, ignore_errors=True)
                    self._creation_times.pop(safe_session_id, None)
                    self._active_refs.pop(safe_session_id, None)  # V11 F26: Clean ref count too
                    logger.debug(f"[F26] Cleaned up home for {safe_session_id}")
                    return True
                except Exception as e:
                    logger.error(f"[F26] Failed to cleanup {safe_session_id}: {e}")
                    return False

            return False

    def cleanup_old_homes(self, max_age_hours: float = 24.0) -> int:
        """
        Cleanup old isolated home directories.

        Args:
            max_age_hours: Maximum age in hours before cleanup

        Returns:
            Number of directories cleaned up
        """
        with self._lock:
            removed = 0
            now = datetime.now()

            for session_id, created_at in list(self._creation_times.items()):
                age_hours = (now - created_at).total_seconds() / 3600

                if age_hours > max_age_hours:
                    isolated_home = self.homes_dir / session_id

                    if isolated_home.exists():
                        try:
                            shutil.rmtree(isolated_home, ignore_errors=True)
                            removed += 1
                        except Exception:
                            pass

                    self._creation_times.pop(session_id, None)

            return removed

    def list_active_homes(self) -> list[str]:
        """
        List all active isolated home directories.

        Returns:
            List of session IDs with active isolated homes
        """
        if not self.homes_dir.exists():
            return []

        return [d.name for d in self.homes_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]

    def get_stats(self) -> dict[str, any]:
        """
        Get statistics about isolated homes.

        Returns:
            Dict with active_count and total_size_mb
        """
        active = self.list_active_homes()
        total_size = 0

        for session_id in active:
            home_path = self.homes_dir / session_id
            if home_path.exists():
                for f in home_path.rglob("*"):
                    if f.is_file():
                        with contextlib.suppress(Exception):
                            total_size += f.stat().st_size

        return {"active_count": len(active), "total_size_mb": round(total_size / (1024 * 1024), 2)}

    # =========================================================================
    # V11 FIX F29: Disk Quota Monitoring
    # =========================================================================

    def check_disk_quota(self, quota_mb: float = 500.0, warn_threshold: float = 0.8) -> dict[str, any]:
        """
        V11 FIX F29: Check disk usage against quota.

        Monitors session home directories to prevent disk exhaustion
        in long-running production deployments.

        Args:
            quota_mb: Maximum allowed size in MB (default 500MB)
            warn_threshold: Fraction of quota to trigger warning (default 0.8 = 80%)

        Returns:
            Dict with:
                - current_mb: Current usage in MB
                - quota_mb: Configured quota
                - usage_percent: Current usage as percentage
                - status: "ok", "warning", or "exceeded"
                - message: Human-readable status message
        """
        stats = self.get_stats()
        current_mb = stats["total_size_mb"]
        usage_percent = (current_mb / quota_mb * 100) if quota_mb > 0 else 0

        if current_mb >= quota_mb:
            status = "exceeded"
            message = f"DISK QUOTA EXCEEDED: {current_mb:.1f}MB / {quota_mb:.1f}MB"
            logger.error(f"[F29] {message}")
        elif current_mb >= quota_mb * warn_threshold:
            status = "warning"
            message = f"Disk usage high: {current_mb:.1f}MB / {quota_mb:.1f}MB ({usage_percent:.1f}%)"
            logger.warning(f"[F29] {message}")
        else:
            status = "ok"
            message = f"Disk usage normal: {current_mb:.1f}MB / {quota_mb:.1f}MB ({usage_percent:.1f}%)"

        return {
            "current_mb": current_mb,
            "quota_mb": quota_mb,
            "usage_percent": round(usage_percent, 1),
            "status": status,
            "message": message,
            "active_sessions": stats["active_count"],
        }

    def enforce_quota(self, quota_mb: float = 500.0) -> int:
        """
        V11 FIX F29: Enforce disk quota by cleaning oldest sessions.

        Called when quota is exceeded to automatically cleanup
        oldest session homes until under quota.

        Args:
            quota_mb: Maximum allowed size in MB

        Returns:
            Number of sessions cleaned up
        """
        cleaned = 0
        quota_check = self.check_disk_quota(quota_mb)

        if quota_check["status"] != "exceeded":
            return 0

        logger.warning("[F29] Enforcing quota: cleaning old sessions...")

        # Sort sessions by creation time (oldest first)
        with self._lock:
            sorted_sessions = sorted(self._creation_times.items(), key=lambda x: x[1])

        # Clean oldest sessions until under quota
        for session_id, _ in sorted_sessions:
            # Skip if session is in use
            if self._active_refs.get(session_id, 0) > 0:
                continue

            if self.cleanup_home(session_id, force=False):
                cleaned += 1
                logger.info(f"[F29] Cleaned session {session_id[:20]}... to enforce quota")

            # Check if we're under quota now
            new_check = self.check_disk_quota(quota_mb)
            if new_check["status"] != "exceeded":
                break

        logger.info(f"[F29] Quota enforcement complete: cleaned {cleaned} sessions")
        return cleaned
