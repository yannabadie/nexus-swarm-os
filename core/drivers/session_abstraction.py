"""
Session Abstraction Layer - V11 CLI/API Independent Sessions.

F32 Fix: Decouples session management from CLI-specific features.

Problem (F32):
- Gemini CLI: Sessions via --resume latest, stored in ~/.gemini/tmp/<hash>/
- Claude CLI: Session via claude code session management
- API: Sessions via conversation_id in request body
- Current code is tightly coupled to CLI session mechanisms

Solution:
- SessionManager abstract class defines session operations
- CLISessionManager: Implements sessions for CLI drivers
- APISessionManager: (Future) Implements sessions for API drivers
- SessionRegistry: Tracks all active sessions across drivers

Benefits:
1. Orchestration code doesn't know about --resume flags
2. Can switch CLI to API without session code changes
3. Centralized session lifecycle management
4. Enables session handoff between CLI and API

Architecture:
```
        +--------------------+
        |  SessionProtocol   |
        +---------+----------+
      +-----------+-----------+
      v           v           v
+-----------+ +-----------+ +-----------+
| CLISession| | APISession| |MockSession|
|  Manager  | |  Manager  | |  (tests)  |
+-----------+ +-----------+ +-----------+
      |             |
      v             v
 --resume       conversation_id
 ~/.gemini/     in API request
```

Author: Claude (NEXUS V11)
Date: 2025-12-15
"""

from __future__ import annotations

import abc
import contextlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# =============================================================================
# Session Types
# =============================================================================


class SessionMode(Enum):
    """How to handle session context."""

    FRESH = auto()  # Start new session, no history
    CONTINUE = auto()  # Resume existing session
    BRANCH = auto()  # Fork from existing session


class SessionState(Enum):
    """Session lifecycle state."""

    CREATED = auto()  # Session created, not yet started
    ACTIVE = auto()  # Session is active
    PAUSED = auto()  # Session paused (resumable)
    ENDED = auto()  # Session ended (archived)
    ERROR = auto()  # Session in error state


@dataclass
class SessionMetadata:
    """Metadata about a session."""

    session_id: str
    provider: str  # "gemini" or "claude"
    state: SessionState = SessionState.CREATED
    created_at: datetime = field(default_factory=datetime.now)
    last_active: datetime = field(default_factory=datetime.now)
    message_count: int = 0
    total_tokens: int = 0
    parent_session_id: str | None = None  # For branched sessions
    tags: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "provider": self.provider,
            "state": self.state.name,
            "created_at": self.created_at.isoformat(),
            "last_active": self.last_active.isoformat(),
            "message_count": self.message_count,
            "total_tokens": self.total_tokens,
            "parent_session_id": self.parent_session_id,
            "tags": self.tags,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionMetadata:
        return cls(
            session_id=data["session_id"],
            provider=data["provider"],
            state=SessionState[data["state"]],
            created_at=datetime.fromisoformat(data["created_at"]),
            last_active=datetime.fromisoformat(data["last_active"]),
            message_count=data.get("message_count", 0),
            total_tokens=data.get("total_tokens", 0),
            parent_session_id=data.get("parent_session_id"),
            tags=data.get("tags", []),
            extra=data.get("extra", {}),
        )


# =============================================================================
# Abstract Session Manager
# =============================================================================


class SessionManager(abc.ABC):
    """
    Abstract base class for session management.

    Implementations handle the details of:
    - CLI: --resume flags, ~/.gemini/tmp/ storage
    - API: conversation_id, server-side storage
    """

    @abc.abstractmethod
    def create_session(
        self,
        provider: str,
        mode: SessionMode = SessionMode.FRESH,
        parent_id: str | None = None,
        tags: list[str] | None = None,
    ) -> SessionMetadata:
        """
        Create a new session.

        Args:
            provider: "gemini" or "claude"
            mode: Session mode (FRESH, CONTINUE, BRANCH)
            parent_id: Parent session ID for BRANCH mode
            tags: Optional tags for categorization

        Returns:
            SessionMetadata for the new session
        """
        ...

    @abc.abstractmethod
    def get_session(self, session_id: str) -> SessionMetadata | None:
        """Get session metadata by ID."""
        ...

    @abc.abstractmethod
    def update_session(
        self,
        session_id: str,
        state: SessionState | None = None,
        message_count_delta: int = 0,
        tokens_delta: int = 0,
    ) -> bool:
        """
        Update session state and metrics.

        Returns:
            True if session was found and updated
        """
        ...

    @abc.abstractmethod
    def end_session(self, session_id: str) -> bool:
        """
        End a session.

        Returns:
            True if session was ended successfully
        """
        ...

    @abc.abstractmethod
    def get_driver_context(
        self,
        session_id: str,
    ) -> dict[str, Any]:
        """
        Get session context in driver-appropriate format.

        For CLI: Returns {"session_uuid": "...", "isolated_env": {...}}
        For API: Returns {"conversation_id": "..."}

        This is the bridge between abstract sessions and driver-specific args.
        """
        ...

    @abc.abstractmethod
    def list_sessions(
        self,
        provider: str | None = None,
        state: SessionState | None = None,
    ) -> list[SessionMetadata]:
        """
        List sessions matching filters.

        Args:
            provider: Filter by provider
            state: Filter by state
        """
        ...


# =============================================================================
# CLI Session Manager
# =============================================================================


class CLISessionManager(SessionManager):
    """
    Session manager for CLI-based drivers.

    Maps abstract sessions to:
    - Gemini: --resume latest, isolated HOME directories
    - Claude: Session UUIDs

    Integrates with HomeIsolator for parallel session isolation.
    """

    def __init__(
        self,
        workspace_path: Path,
        home_isolator: Any | None = None,  # HomeIsolator from session module
    ):
        """
        Initialize CLI session manager.

        Args:
            workspace_path: Base workspace path
            home_isolator: Optional HomeIsolator for session isolation
        """
        self._workspace_path = Path(workspace_path)
        self._home_isolator = home_isolator
        self._sessions: dict[str, SessionMetadata] = {}
        self._lock = Lock()

        # Session storage directory
        self._session_store = self._workspace_path / ".nexus" / "sessions"
        self._session_store.mkdir(parents=True, exist_ok=True)

        # Load existing sessions
        self._load_sessions()

    def _load_sessions(self) -> None:
        """Load sessions from disk."""
        sessions_file = self._session_store / "registry.json"
        if sessions_file.exists():
            try:
                with open(sessions_file, encoding="utf-8") as f:
                    data = json.load(f)
                for session_data in data.get("sessions", []):
                    meta = SessionMetadata.from_dict(session_data)
                    self._sessions[meta.session_id] = meta
                logger.debug(f"Loaded {len(self._sessions)} sessions from registry")
            except Exception as e:
                logger.warning(f"Failed to load sessions: {e}")

    def _save_sessions(self) -> None:
        """Save sessions to disk."""
        sessions_file = self._session_store / "registry.json"
        try:
            data = {
                "version": "1.0",
                "updated_at": datetime.now().isoformat(),
                "sessions": [s.to_dict() for s in self._sessions.values()],
            }
            with open(sessions_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save sessions: {e}")

    def create_session(
        self,
        provider: str,
        mode: SessionMode = SessionMode.FRESH,
        parent_id: str | None = None,
        tags: list[str] | None = None,
    ) -> SessionMetadata:
        """Create a new CLI session."""
        with self._lock:
            session_id = f"{provider}_{uuid.uuid4().hex[:12]}"

            # For BRANCH mode, validate parent exists
            if mode == SessionMode.BRANCH and (not parent_id or parent_id not in self._sessions):
                raise ValueError(f"Parent session {parent_id} not found for BRANCH")

            meta = SessionMetadata(
                session_id=session_id,
                provider=provider,
                state=SessionState.ACTIVE,
                parent_session_id=parent_id if mode == SessionMode.BRANCH else None,
                tags=tags or [],
                extra={"mode": mode.name},
            )

            self._sessions[session_id] = meta
            self._save_sessions()

            logger.info(f"Created session {session_id} for {provider} (mode={mode.name})")
            return meta

    def get_session(self, session_id: str) -> SessionMetadata | None:
        """Get session by ID."""
        return self._sessions.get(session_id)

    def update_session(
        self,
        session_id: str,
        state: SessionState | None = None,
        message_count_delta: int = 0,
        tokens_delta: int = 0,
    ) -> bool:
        """Update session metrics."""
        with self._lock:
            if session_id not in self._sessions:
                return False

            meta = self._sessions[session_id]
            if state:
                meta.state = state
            meta.message_count += message_count_delta
            meta.total_tokens += tokens_delta
            meta.last_active = datetime.now()

            self._save_sessions()
            return True

    def end_session(self, session_id: str) -> bool:
        """End a session."""
        with self._lock:
            if session_id not in self._sessions:
                return False

            meta = self._sessions[session_id]
            meta.state = SessionState.ENDED
            meta.last_active = datetime.now()

            # Cleanup isolated HOME if applicable
            if self._home_isolator:
                try:
                    self._home_isolator.cleanup_home(session_id)
                except Exception as e:
                    logger.warning(f"Failed to cleanup HOME for {session_id}: {e}")

            self._save_sessions()
            logger.info(f"Ended session {session_id}")
            return True

    def get_driver_context(self, session_id: str) -> dict[str, Any]:
        """
        Get driver context for a CLI session.

        Returns kwargs that can be passed directly to driver.invoke():
        - session_uuid: For session tracking
        - isolated_env: For parallel isolation (if HomeIsolator available)
        """
        meta = self.get_session(session_id)
        if not meta:
            return {}

        context: dict[str, Any] = {
            "session_uuid": session_id,
        }

        # Add isolated environment if available
        if self._home_isolator:
            try:
                # Use acquire_env for reference counting (V11 F26)
                if hasattr(self._home_isolator, "acquire_env"):
                    context["isolated_env"] = self._home_isolator.acquire_env(session_id)
                else:
                    context["isolated_env"] = self._home_isolator.get_isolated_env(session_id)
            except Exception as e:
                logger.warning(f"Failed to get isolated env for {session_id}: {e}")

        # Provider-specific context
        mode = meta.extra.get("mode", "FRESH")
        if meta.provider == "gemini":
            # Gemini uses --resume latest for continuation
            if mode != "FRESH" and meta.message_count > 0:
                context["resume_session"] = True
        elif meta.provider == "claude":
            # Claude uses session UUID directly
            pass

        return context

    def release_driver_context(self, session_id: str) -> None:
        """
        Release driver context after use.

        Should be called after driver.invoke() completes to release
        reference-counted resources (V11 F26).
        """
        if self._home_isolator and hasattr(self._home_isolator, "release_env"):
            try:
                self._home_isolator.release_env(session_id)
            except Exception as e:
                logger.warning(f"Failed to release env for {session_id}: {e}")

    def list_sessions(
        self,
        provider: str | None = None,
        state: SessionState | None = None,
    ) -> list[SessionMetadata]:
        """List sessions matching filters."""
        results = []
        for meta in self._sessions.values():
            if provider and meta.provider != provider:
                continue
            if state and meta.state != state:
                continue
            results.append(meta)
        return sorted(results, key=lambda m: m.last_active, reverse=True)

    def cleanup_old_sessions(self, max_age_hours: float = 24.0) -> int:
        """
        Cleanup sessions older than max_age.

        Returns:
            Number of sessions cleaned up
        """
        with self._lock:
            now = datetime.now()
            to_remove = []

            for session_id, meta in self._sessions.items():
                age_hours = (now - meta.last_active).total_seconds() / 3600
                if age_hours > max_age_hours and meta.state != SessionState.ACTIVE:
                    to_remove.append(session_id)

            for session_id in to_remove:
                del self._sessions[session_id]
                # Cleanup HOME if applicable
                if self._home_isolator:
                    with contextlib.suppress(Exception):
                        self._home_isolator.cleanup_home(session_id)

            if to_remove:
                self._save_sessions()
                logger.info(f"Cleaned up {len(to_remove)} old sessions")

            return len(to_remove)


# =============================================================================
# Session Registry (Global)
# =============================================================================


class SessionRegistry:
    """
    Global registry for all session managers.

    Provides unified access to sessions across different drivers/providers.
    Used by orchestration code to manage sessions without knowing driver details.
    """

    _instance: SessionRegistry | None = None
    _lock = Lock()

    def __new__(cls) -> SessionRegistry:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._managers: dict[str, SessionManager] = {}
                cls._instance._default_manager: str | None = None
            return cls._instance

    def register_manager(
        self,
        name: str,
        manager: SessionManager,
        set_default: bool = False,
    ) -> None:
        """Register a session manager."""
        self._managers[name] = manager
        if set_default or self._default_manager is None:
            self._default_manager = name

    def get_manager(self, name: str | None = None) -> SessionManager | None:
        """Get a session manager by name, or default if not specified."""
        if name:
            return self._managers.get(name)
        if self._default_manager:
            return self._managers.get(self._default_manager)
        return None

    def create_session(
        self,
        provider: str,
        mode: SessionMode = SessionMode.FRESH,
        manager_name: str | None = None,
        **kwargs: Any,
    ) -> SessionMetadata | None:
        """Create session using specified or default manager."""
        manager = self.get_manager(manager_name)
        if manager:
            return manager.create_session(provider, mode, **kwargs)
        return None

    def get_session(
        self,
        session_id: str,
        manager_name: str | None = None,
    ) -> SessionMetadata | None:
        """Get session by ID."""
        manager = self.get_manager(manager_name)
        if manager:
            return manager.get_session(session_id)
        return None


def get_session_registry() -> SessionRegistry:
    """Get the global session registry singleton."""
    return SessionRegistry()


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Types
    "SessionMode",
    "SessionState",
    "SessionMetadata",
    # Managers
    "SessionManager",
    "CLISessionManager",
    # Registry
    "SessionRegistry",
    "get_session_registry",
]
