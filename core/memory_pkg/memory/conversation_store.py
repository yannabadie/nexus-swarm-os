"""
Conversation Store - Persistent conversation history for multi-session memory.

V12.4 COGNITIVE BOOST - Task #43

Stores conversation turns (user, assistant, system, tool) across sessions.
Enables conversation replay, cross-session search, and history summarization.

Fills the gap between:
- SuccessMemory (stores task outcomes, not conversation content)
- ProjectMemory (stores code/docs, not dialogue)
- AutoMemory (stores task patterns, not message exchanges)

Usage:
    from core.memory_pkg.memory.conversation_store import ConversationStore

    store = ConversationStore()
    session = store.create_session(title="Debug auth module")
    store.add_turn(session.session_id, role="user", content="Fix the login bug")
    store.add_turn(session.session_id, role="assistant", content="Found the issue...")

    # Search across all sessions
    results = store.search("login bug")

    # Get full conversation
    turns = store.get_turns(session.session_id)
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

MAX_SESSIONS = 1000
MAX_TURNS_PER_SESSION = 10000
DEFAULT_STORAGE_DIR = "workspace/memory/conversations"


# =============================================================================
# Types
# =============================================================================


@dataclass
class ConversationTurn:
    """A single turn in a conversation."""

    turn_id: str
    role: str  # "user", "assistant", "system", "tool"
    content: str
    agent_id: str = ""  # "gemini", "claude", etc.
    timestamp: str = ""  # ISO format
    token_estimate: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.turn_id:
            self.turn_id = uuid.uuid4().hex[:12]
        if not self.timestamp:
            self.timestamp = datetime.now(UTC).isoformat()
        if self.token_estimate == 0 and self.content:
            self.token_estimate = max(1, len(self.content) // 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "role": self.role,
            "content": self.content,
            "agent_id": self.agent_id,
            "timestamp": self.timestamp,
            "token_estimate": self.token_estimate,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConversationTurn:
        return cls(
            turn_id=data.get("turn_id", ""),
            role=data["role"],
            content=data["content"],
            agent_id=data.get("agent_id", ""),
            timestamp=data.get("timestamp", ""),
            token_estimate=data.get("token_estimate", 0),
            metadata=data.get("metadata", {}),
        )


@dataclass
class ConversationSession:
    """A conversation session containing multiple turns."""

    session_id: str
    title: str = ""
    created_at: str = ""
    updated_at: str = ""
    tags: list[str] = field(default_factory=list)
    turn_count: int = 0
    total_tokens: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.session_id:
            self.session_id = uuid.uuid4().hex[:16]
        now = datetime.now(UTC).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "tags": self.tags,
            "turn_count": self.turn_count,
            "total_tokens": self.total_tokens,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConversationSession:
        return cls(
            session_id=data["session_id"],
            title=data.get("title", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            tags=data.get("tags", []),
            turn_count=data.get("turn_count", 0),
            total_tokens=data.get("total_tokens", 0),
            metadata=data.get("metadata", {}),
        )


@dataclass
class SearchResult:
    """A search result from conversation history."""

    session_id: str
    session_title: str
    turn: ConversationTurn
    score: float  # 0.0 to 1.0
    context_before: list[ConversationTurn] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "session_title": self.session_title,
            "turn": self.turn.to_dict(),
            "score": round(self.score, 4),
        }


@dataclass
class ConversationSummary:
    """Summary metadata for a conversation session."""

    session_id: str
    title: str
    turn_count: int
    total_tokens: int
    agents_involved: list[str]
    duration_seconds: float
    first_message: str
    last_message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "title": self.title,
            "turn_count": self.turn_count,
            "total_tokens": self.total_tokens,
            "agents_involved": self.agents_involved,
            "duration_seconds": round(self.duration_seconds, 1),
            "first_message": self.first_message[:200],
            "last_message": self.last_message[:200],
        }


# =============================================================================
# Conversation Store
# =============================================================================


class ConversationStore:
    """
    Persistent conversation history store.

    Stores conversation sessions with turns, supports search
    across history, and provides session summaries.

    Storage format:
        workspace/memory/conversations/
        +-- sessions.json          # Session index
        +-- turns/
            +-- {session_id}.jsonl  # Turns per session (JSONL)
            +-- ...
    """

    def __init__(
        self,
        storage_dir: str | None = None,
        *,
        max_sessions: int = MAX_SESSIONS,
        max_turns_per_session: int = MAX_TURNS_PER_SESSION,
        persist: bool = True,
    ):
        """
        Initialize conversation store.

        Args:
            storage_dir: Directory for persistent storage
            max_sessions: Maximum number of sessions to retain
            max_turns_per_session: Maximum turns per session
            persist: Whether to persist to disk
        """
        self._storage_dir = Path(storage_dir) if storage_dir else Path(DEFAULT_STORAGE_DIR)
        self._max_sessions = max_sessions
        self._max_turns = max_turns_per_session
        self._persist = persist

        # In-memory state
        self._sessions: dict[str, ConversationSession] = {}
        self._turns: dict[str, list[ConversationTurn]] = {}

        if self._persist:
            self._ensure_dirs()
            self._load_sessions()

    # =========================================================================
    # Session Management
    # =========================================================================

    def create_session(
        self,
        title: str = "",
        *,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ConversationSession:
        """
        Create a new conversation session.

        Args:
            title: Session title
            tags: Optional tags for categorization
            metadata: Optional metadata

        Returns:
            The created ConversationSession
        """
        session = ConversationSession(
            session_id="",  # auto-generated
            title=title,
            tags=tags or [],
            metadata=metadata or {},
        )
        self._sessions[session.session_id] = session
        self._turns[session.session_id] = []

        # Evict oldest if over limit
        self._evict_oldest_sessions()

        if self._persist:
            self._save_sessions()

        return session

    def get_session(self, session_id: str) -> ConversationSession | None:
        """Get a session by ID."""
        return self._sessions.get(session_id)

    def list_sessions(
        self,
        *,
        limit: int = 50,
        tag: str | None = None,
    ) -> list[ConversationSession]:
        """
        List sessions, most recent first.

        Args:
            limit: Maximum sessions to return
            tag: Filter by tag

        Returns:
            List of sessions sorted by updated_at descending
        """
        sessions = list(self._sessions.values())

        if tag:
            sessions = [s for s in sessions if tag in s.tags]

        sessions.sort(key=lambda s: s.updated_at, reverse=True)
        return sessions[:limit]

    def delete_session(self, session_id: str) -> bool:
        """
        Delete a session and its turns.

        Returns:
            True if deleted, False if not found
        """
        if session_id not in self._sessions:
            return False

        del self._sessions[session_id]
        self._turns.pop(session_id, None)

        if self._persist:
            self._save_sessions()
            turns_file = self._storage_dir / "turns" / f"{session_id}.jsonl"
            if turns_file.exists():
                turns_file.unlink()

        return True

    # =========================================================================
    # Turn Management
    # =========================================================================

    def add_turn(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        agent_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ConversationTurn | None:
        """
        Add a turn to a session.

        Args:
            session_id: Target session
            role: Message role ("user", "assistant", "system", "tool")
            content: Message content
            agent_id: Agent that produced this turn
            metadata: Optional metadata

        Returns:
            The created ConversationTurn, or None if session not found
        """
        session = self._sessions.get(session_id)
        if session is None:
            return None

        turns = self._turns.get(session_id, [])
        if len(turns) >= self._max_turns:
            return None

        turn = ConversationTurn(
            turn_id="",  # auto-generated
            role=role,
            content=content,
            agent_id=agent_id,
            metadata=metadata or {},
        )

        turns.append(turn)
        self._turns[session_id] = turns

        # Update session metadata
        session.turn_count = len(turns)
        session.total_tokens += turn.token_estimate
        session.updated_at = datetime.now(UTC).isoformat()

        if self._persist:
            self._append_turn(session_id, turn)
            self._save_sessions()

        return turn

    def get_turns(
        self,
        session_id: str,
        *,
        limit: int | None = None,
        role: str | None = None,
    ) -> list[ConversationTurn]:
        """
        Get turns for a session.

        Args:
            session_id: Target session
            limit: Max turns to return (most recent)
            role: Filter by role

        Returns:
            List of turns
        """
        turns = self._turns.get(session_id, [])

        if role:
            turns = [t for t in turns if t.role == role]

        if limit:
            turns = turns[-limit:]

        return list(turns)

    def get_last_turn(self, session_id: str) -> ConversationTurn | None:
        """Get the most recent turn in a session."""
        turns = self._turns.get(session_id, [])
        return turns[-1] if turns else None

    # =========================================================================
    # Search
    # =========================================================================

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        session_id: str | None = None,
        role: str | None = None,
    ) -> list[SearchResult]:
        """
        Search conversation history using keyword matching.

        Simple word-overlap scoring (Jaccard-like).

        Args:
            query: Search query
            limit: Max results
            session_id: Restrict to one session
            role: Filter by role

        Returns:
            List of SearchResults sorted by score descending
        """
        query_words = set(query.lower().split())
        if not query_words:
            return []

        results = []
        sessions_to_search = (
            {session_id: self._sessions.get(session_id)}
            if session_id and session_id in self._sessions
            else self._sessions
        )

        for sid, session in sessions_to_search.items():
            if session is None:
                continue
            turns = self._turns.get(sid, [])
            for turn in turns:
                if role and turn.role != role:
                    continue

                content_words = set(turn.content.lower().split())
                if not content_words:
                    continue

                overlap = query_words & content_words
                if not overlap:
                    continue

                # Jaccard similarity
                score = len(overlap) / len(query_words | content_words)

                results.append(
                    SearchResult(
                        session_id=sid,
                        session_title=session.title,
                        turn=turn,
                        score=score,
                    )
                )

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    # =========================================================================
    # Summaries
    # =========================================================================

    def get_summary(self, session_id: str) -> ConversationSummary | None:
        """
        Get a summary of a conversation session.

        Returns:
            ConversationSummary or None if session not found
        """
        session = self._sessions.get(session_id)
        if session is None:
            return None

        turns = self._turns.get(session_id, [])
        agents = sorted(set(t.agent_id for t in turns if t.agent_id))

        # Calculate duration from timestamps
        duration = 0.0
        if len(turns) >= 2:
            try:
                first_dt = datetime.fromisoformat(turns[0].timestamp)
                last_dt = datetime.fromisoformat(turns[-1].timestamp)
                duration = (last_dt - first_dt).total_seconds()
            except (ValueError, TypeError):
                pass

        return ConversationSummary(
            session_id=session_id,
            title=session.title,
            turn_count=session.turn_count,
            total_tokens=session.total_tokens,
            agents_involved=agents,
            duration_seconds=max(0.0, duration),
            first_message=turns[0].content if turns else "",
            last_message=turns[-1].content if turns else "",
        )

    # =========================================================================
    # State
    # =========================================================================

    @property
    def session_count(self) -> int:
        return len(self._sessions)

    @property
    def total_turns(self) -> int:
        return sum(len(t) for t in self._turns.values())

    def clear(self) -> int:
        """
        Clear all sessions and turns.

        Returns:
            Number of sessions cleared
        """
        count = len(self._sessions)
        self._sessions.clear()
        self._turns.clear()

        if self._persist:
            self._save_sessions()
            turns_dir = self._storage_dir / "turns"
            if turns_dir.exists():
                for f in turns_dir.glob("*.jsonl"):
                    f.unlink()

        return count

    def to_dict(self) -> dict[str, Any]:
        """Export store state."""
        return {
            "session_count": self.session_count,
            "total_turns": self.total_turns,
            "max_sessions": self._max_sessions,
            "storage_dir": str(self._storage_dir),
            "persist": self._persist,
        }

    # =========================================================================
    # Persistence (Internal)
    # =========================================================================

    def _ensure_dirs(self) -> None:
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        (self._storage_dir / "turns").mkdir(exist_ok=True)

    def _save_sessions(self) -> None:
        """Save session index to disk."""
        if not self._persist:
            return
        data = {sid: s.to_dict() for sid, s in self._sessions.items()}
        path = self._storage_dir / "sessions.json"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _load_sessions(self) -> None:
        """Load session index from disk."""
        path = self._storage_dir / "sessions.json"
        if not path.exists():
            return

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for sid, sdata in data.items():
                self._sessions[sid] = ConversationSession.from_dict(sdata)
                # Load turns for this session
                self._load_turns(sid)
        except (json.JSONDecodeError, KeyError) as e:
            _logger.warning("Failed to load sessions: %s", e)

    def _load_turns(self, session_id: str) -> None:
        """Load turns for a session from JSONL file."""
        path = self._storage_dir / "turns" / f"{session_id}.jsonl"
        if not path.exists():
            self._turns[session_id] = []
            return

        turns = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    turns.append(ConversationTurn.from_dict(json.loads(line)))
        except (json.JSONDecodeError, KeyError) as e:
            _logger.warning("Failed to load turns for %s: %s", session_id, e)

        self._turns[session_id] = turns

    def _append_turn(self, session_id: str, turn: ConversationTurn) -> None:
        """Append a single turn to the session's JSONL file."""
        if not self._persist:
            return
        path = self._storage_dir / "turns" / f"{session_id}.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(turn.to_dict()) + "\n")

    def _evict_oldest_sessions(self) -> None:
        """Evict oldest sessions if over the limit."""
        while len(self._sessions) > self._max_sessions:
            # Find oldest session
            oldest_id = min(
                self._sessions,
                key=lambda sid: self._sessions[sid].created_at,
            )
            self.delete_session(oldest_id)
