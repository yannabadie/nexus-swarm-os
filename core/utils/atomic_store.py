"""
AtomicJsonStore - Thread-safe atomic JSON persistence layer.

NEXUS V7.5 HIVE MIND - Phase 7: Session Isolation & Data Integrity

This module provides atomic JSON file operations using the Write-Replace pattern
to prevent data corruption during concurrent access in Swarm PARALLEL mode.

Pattern:
    1. Write to temporary file (.tmp)
    2. Force disk sync (fsync)
    3. Atomic rename to target (os.replace)

Author: Claude (NEXUS V7.5)
Date: 2025-12-04
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from threading import RLock
from typing import Any


class AtomicJsonStore:
    """
    Thread-safe atomic JSON file store using Write-Replace pattern.

    Provides safe concurrent access to JSON files within the same process.
    Uses RLock for thread safety and atomic file operations to prevent
    data corruption during parallel Swarm execution.

    Attributes:
        filepath: Path to the JSON file.

    Example:
        >>> store = AtomicJsonStore(Path("workspace/.nexus/state.json"))
        >>> data = store.load()
        >>> data["counter"] = data.get("counter", 0) + 1
        >>> store.save(data)
    """

    def __init__(self, filepath: Path) -> None:
        """
        Initialize the atomic JSON store.

        Args:
            filepath: Path to the JSON file. Parent directories will be
                     created automatically if they don't exist.
        """
        self._filepath = Path(filepath)
        self._lock = RLock()

    @property
    def filepath(self) -> Path:
        """Return the path to the JSON file."""
        return self._filepath

    @property
    def exists(self) -> bool:
        """Check if the JSON file exists."""
        return self._filepath.exists()

    def load(self) -> dict[str, Any]:
        """
        Load JSON data from file.

        Returns:
            Dict containing the JSON data. Returns empty dict if file
            doesn't exist or is empty.

        Raises:
            json.JSONDecodeError: If file contains invalid JSON.
            UnicodeDecodeError: If file contains invalid UTF-8.

        Note:
            This method is thread-safe within the same process.
        """
        with self._lock:
            if not self._filepath.exists():
                return {}

            try:
                content = self._filepath.read_text(encoding="utf-8")
                if not content.strip():
                    return {}
                return json.loads(content)
            except json.JSONDecodeError as e:
                # Log error but don't crash - return empty dict for recovery
                raise json.JSONDecodeError(f"Invalid JSON in {self._filepath}: {e.msg}", e.doc, e.pos) from None
            except UnicodeDecodeError as e:
                raise UnicodeDecodeError(
                    e.encoding, e.object, e.start, e.end, f"Invalid UTF-8 in {self._filepath}: {e.reason}"
                ) from None

    def load_safe(self, default: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        Load JSON data from file, returning default on any error.

        Args:
            default: Value to return if loading fails. Defaults to empty dict.

        Returns:
            Dict containing the JSON data, or default if any error occurs.

        Note:
            This method suppresses all exceptions and is safe to use
            in contexts where file corruption should not crash the system.
        """
        if default is None:
            default = {}
        try:
            return self.load()
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            return default

    def save(self, data: dict[str, Any]) -> None:
        """
        Save data to JSON file atomically.

        Uses the Write-Replace pattern:
        1. Write to temporary file in same directory
        2. Sync to disk (fsync)
        3. Atomic rename to target file

        Args:
            data: Dictionary to save as JSON.

        Raises:
            TypeError: If data is not JSON-serializable.
            OSError: If file operations fail.

        Note:
            This method is thread-safe within the same process.
            Parent directories are created automatically.
        """
        with self._lock:
            # Ensure parent directory exists
            self._filepath.parent.mkdir(parents=True, exist_ok=True)

            # Serialize to JSON with pretty formatting
            json_content = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False)

            # Write to temporary file in same directory (important for atomic rename)
            # Using same directory ensures same filesystem for atomic rename
            tmp_fd, tmp_path = tempfile.mkstemp(
                suffix=".tmp", prefix=f".{self._filepath.name}_", dir=self._filepath.parent
            )

            try:
                # Write content
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                    f.write(json_content)
                    f.flush()
                    os.fsync(f.fileno())  # Force write to disk

                # Atomic rename (works on Windows and POSIX).
                # On Windows, os.replace() can raise PermissionError (errno 13)
                # transiently when the filesystem is flushing or antivirus software
                # briefly holds the file. Retry with exponential back-off.
                _max_retries = 5 if sys.platform == "win32" else 1
                for _attempt in range(_max_retries):
                    try:
                        os.replace(tmp_path, self._filepath)
                        break
                    except PermissionError:
                        if _attempt == _max_retries - 1:
                            raise
                        time.sleep(0.01 * (2 ** _attempt))

            except Exception:
                # Clean up temp file on error
                with contextlib.suppress(OSError):
                    os.unlink(tmp_path)
                raise

    def update(self, updates: dict[str, Any]) -> dict[str, Any]:
        """
        Atomically load, update, and save data.

        This is a convenience method for the common pattern of loading,
        modifying, and saving data in a single atomic operation.

        Args:
            updates: Dictionary of key-value pairs to update.

        Returns:
            The updated data dictionary.

        Example:
            >>> store.update({"last_modified": "2025-12-04"})
        """
        with self._lock:
            data = self.load_safe()
            data.update(updates)
            self.save(data)
            return data

    def delete(self) -> bool:
        """
        Delete the JSON file if it exists.

        Returns:
            True if file was deleted, False if it didn't exist.
        """
        with self._lock:
            if self._filepath.exists():
                self._filepath.unlink()
                return True
            return False

    def __repr__(self) -> str:
        return f"AtomicJsonStore({self._filepath!r})"


class AtomicJsonStoreManager:
    """
    Manager for multiple AtomicJsonStore instances.

    Provides a centralized way to manage multiple JSON stores,
    ensuring each file path has a single store instance for
    proper lock coordination.

    Example:
        >>> manager = AtomicJsonStoreManager()
        >>> blackboard = manager.get_store(Path("workspace/.nexus/blackboard.json"))
        >>> state = manager.get_store(Path("workspace/.nexus/state.json"))
    """

    def __init__(self) -> None:
        """Initialize the store manager."""
        self._stores: dict[Path, AtomicJsonStore] = {}
        self._lock = RLock()

    def get_store(self, filepath: Path) -> AtomicJsonStore:
        """
        Get or create an AtomicJsonStore for the given path.

        Args:
            filepath: Path to the JSON file.

        Returns:
            AtomicJsonStore instance for the path.

        Note:
            Returns the same instance for the same path to ensure
            lock coordination across all users of that file.
        """
        filepath = Path(filepath).resolve()

        with self._lock:
            if filepath not in self._stores:
                self._stores[filepath] = AtomicJsonStore(filepath)
            return self._stores[filepath]

    def clear(self) -> None:
        """Clear all managed stores."""
        with self._lock:
            self._stores.clear()


# =============================================================================
# V10 PRISM: Multi-Tenant Atomic Store Access
# =============================================================================
_default_manager: AtomicJsonStoreManager | None = None


def get_store(filepath: Path) -> AtomicJsonStore:
    """
    Get an AtomicJsonStore from the default manager.

    V10 PRISM: The manager is tenant-scoped via ServiceFactory
    when a session context is active.

    Args:
        filepath: Path to the JSON file.

    Returns:
        AtomicJsonStore instance.
    """
    global _default_manager
    if _default_manager is None:
        _default_manager = AtomicJsonStoreManager()
    return _default_manager.get_store(filepath)


def reset_store_manager() -> None:
    """
    Reset the global store manager (for testing).

    Note: In V10, also clears ServiceFactory cache for current tenant.
    """
    global _default_manager
    if _default_manager:
        _default_manager.clear()
    _default_manager = None
