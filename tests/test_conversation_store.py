"""
Tests for V12.4 Conversation Store.

Validates:
- ConversationTurn creation, serialization, auto-estimation
- ConversationSession creation, serialization
- Session management (create, get, list, delete)
- Turn management (add, get, filter by role, last turn)
- Search (keyword matching, session filter, role filter)
- Summary generation
- Session eviction on max limit
- Turn limit enforcement
- Persistence (save/load sessions + turns)
- State export
- Module exports
"""

import tempfile
from pathlib import Path

from core.memory_pkg.memory.conversation_store import (
    ConversationSession,
    ConversationStore,
    ConversationSummary,
    ConversationTurn,
    SearchResult,
)

# =============================================================================
# ConversationTurn Tests
# =============================================================================


class TestConversationTurn:
    """Test ConversationTurn dataclass."""

    def test_basic_creation(self):
        turn = ConversationTurn(turn_id="", role="user", content="Hello")
        assert turn.role == "user"
        assert turn.content == "Hello"
        assert turn.turn_id  # auto-generated

    def test_auto_timestamp(self):
        turn = ConversationTurn(turn_id="t1", role="user", content="Hi")
        assert turn.timestamp  # auto-generated

    def test_auto_token_estimate(self):
        turn = ConversationTurn(turn_id="t1", role="user", content="x" * 400)
        assert turn.token_estimate == 100  # 400 / 4

    def test_explicit_token_estimate(self):
        turn = ConversationTurn(
            turn_id="t1",
            role="user",
            content="Hi",
            token_estimate=50,
        )
        assert turn.token_estimate == 50

    def test_to_dict(self):
        turn = ConversationTurn(
            turn_id="t1",
            role="assistant",
            content="Hello!",
            agent_id="claude",
            metadata={"key": "val"},
        )
        d = turn.to_dict()
        assert d["turn_id"] == "t1"
        assert d["role"] == "assistant"
        assert d["agent_id"] == "claude"
        assert d["metadata"] == {"key": "val"}

    def test_from_dict(self):
        data = {
            "turn_id": "t1",
            "role": "user",
            "content": "Hello",
            "agent_id": "",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "token_estimate": 5,
            "metadata": {},
        }
        turn = ConversationTurn.from_dict(data)
        assert turn.turn_id == "t1"
        assert turn.content == "Hello"

    def test_roundtrip(self):
        turn = ConversationTurn(
            turn_id="t1",
            role="user",
            content="Test roundtrip",
            agent_id="gemini",
        )
        d = turn.to_dict()
        restored = ConversationTurn.from_dict(d)
        assert restored.turn_id == turn.turn_id
        assert restored.content == turn.content
        assert restored.agent_id == turn.agent_id


# =============================================================================
# ConversationSession Tests
# =============================================================================


class TestConversationSession:
    """Test ConversationSession dataclass."""

    def test_basic_creation(self):
        session = ConversationSession(session_id="", title="Test")
        assert session.session_id  # auto-generated
        assert session.title == "Test"
        assert session.turn_count == 0

    def test_auto_timestamps(self):
        session = ConversationSession(session_id="s1")
        assert session.created_at
        assert session.updated_at

    def test_to_dict(self):
        session = ConversationSession(
            session_id="s1",
            title="Debug session",
            tags=["debug", "auth"],
        )
        d = session.to_dict()
        assert d["session_id"] == "s1"
        assert d["title"] == "Debug session"
        assert d["tags"] == ["debug", "auth"]

    def test_from_dict(self):
        data = {
            "session_id": "s1",
            "title": "Test",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "tags": [],
            "turn_count": 5,
            "total_tokens": 1000,
            "metadata": {},
        }
        session = ConversationSession.from_dict(data)
        assert session.session_id == "s1"
        assert session.turn_count == 5


# =============================================================================
# Session Management Tests
# =============================================================================


class TestSessionManagement:
    """Test session creation and management."""

    def test_create_session(self):
        store = ConversationStore(persist=False)
        session = store.create_session(title="Test")
        assert session.title == "Test"
        assert store.session_count == 1

    def test_create_session_with_tags(self):
        store = ConversationStore(persist=False)
        session = store.create_session(title="Debug", tags=["debug", "auth"])
        assert session.tags == ["debug", "auth"]

    def test_get_session(self):
        store = ConversationStore(persist=False)
        session = store.create_session(title="Test")
        retrieved = store.get_session(session.session_id)
        assert retrieved is not None
        assert retrieved.title == "Test"

    def test_get_session_not_found(self):
        store = ConversationStore(persist=False)
        assert store.get_session("nonexistent") is None

    def test_list_sessions(self):
        store = ConversationStore(persist=False)
        store.create_session(title="Session A")
        store.create_session(title="Session B")
        store.create_session(title="Session C")
        sessions = store.list_sessions()
        assert len(sessions) == 3

    def test_list_sessions_limit(self):
        store = ConversationStore(persist=False)
        for i in range(5):
            store.create_session(title=f"Session {i}")
        sessions = store.list_sessions(limit=2)
        assert len(sessions) == 2

    def test_list_sessions_by_tag(self):
        store = ConversationStore(persist=False)
        store.create_session(title="Debug", tags=["debug"])
        store.create_session(title="Feature", tags=["feature"])
        store.create_session(title="Debug 2", tags=["debug"])
        sessions = store.list_sessions(tag="debug")
        assert len(sessions) == 2

    def test_delete_session(self):
        store = ConversationStore(persist=False)
        session = store.create_session(title="To Delete")
        assert store.delete_session(session.session_id) is True
        assert store.session_count == 0

    def test_delete_session_not_found(self):
        store = ConversationStore(persist=False)
        assert store.delete_session("nonexistent") is False

    def test_session_eviction(self):
        store = ConversationStore(persist=False, max_sessions=3)
        ids = []
        for i in range(5):
            s = store.create_session(title=f"Session {i}")
            ids.append(s.session_id)
        assert store.session_count == 3
        # Oldest sessions should be evicted
        assert store.get_session(ids[0]) is None
        assert store.get_session(ids[1]) is None
        assert store.get_session(ids[4]) is not None


# =============================================================================
# Turn Management Tests
# =============================================================================


class TestTurnManagement:
    """Test turn addition and retrieval."""

    def test_add_turn(self):
        store = ConversationStore(persist=False)
        session = store.create_session(title="Test")
        turn = store.add_turn(session.session_id, "user", "Hello")
        assert turn is not None
        assert turn.role == "user"
        assert turn.content == "Hello"

    def test_add_turn_invalid_session(self):
        store = ConversationStore(persist=False)
        turn = store.add_turn("nonexistent", "user", "Hello")
        assert turn is None

    def test_add_turn_with_agent_id(self):
        store = ConversationStore(persist=False)
        session = store.create_session()
        turn = store.add_turn(session.session_id, "assistant", "Hi", agent_id="claude")
        assert turn.agent_id == "claude"

    def test_turn_count_updates(self):
        store = ConversationStore(persist=False)
        session = store.create_session()
        store.add_turn(session.session_id, "user", "A")
        store.add_turn(session.session_id, "assistant", "B")
        assert session.turn_count == 2

    def test_total_tokens_updates(self):
        store = ConversationStore(persist=False)
        session = store.create_session()
        store.add_turn(session.session_id, "user", "x" * 400)  # ~100 tokens
        assert session.total_tokens >= 100

    def test_get_turns(self):
        store = ConversationStore(persist=False)
        session = store.create_session()
        store.add_turn(session.session_id, "user", "A")
        store.add_turn(session.session_id, "assistant", "B")
        store.add_turn(session.session_id, "user", "C")
        turns = store.get_turns(session.session_id)
        assert len(turns) == 3
        assert turns[0].content == "A"
        assert turns[2].content == "C"

    def test_get_turns_limit(self):
        store = ConversationStore(persist=False)
        session = store.create_session()
        for i in range(10):
            store.add_turn(session.session_id, "user", f"Message {i}")
        turns = store.get_turns(session.session_id, limit=3)
        assert len(turns) == 3
        assert turns[0].content == "Message 7"  # last 3

    def test_get_turns_by_role(self):
        store = ConversationStore(persist=False)
        session = store.create_session()
        store.add_turn(session.session_id, "user", "Q1")
        store.add_turn(session.session_id, "assistant", "A1")
        store.add_turn(session.session_id, "user", "Q2")
        turns = store.get_turns(session.session_id, role="user")
        assert len(turns) == 2

    def test_get_last_turn(self):
        store = ConversationStore(persist=False)
        session = store.create_session()
        store.add_turn(session.session_id, "user", "First")
        store.add_turn(session.session_id, "assistant", "Last")
        last = store.get_last_turn(session.session_id)
        assert last.content == "Last"

    def test_get_last_turn_empty(self):
        store = ConversationStore(persist=False)
        session = store.create_session()
        assert store.get_last_turn(session.session_id) is None

    def test_turn_limit_enforcement(self):
        store = ConversationStore(persist=False, max_turns_per_session=5)
        session = store.create_session()
        for i in range(5):
            assert store.add_turn(session.session_id, "user", f"Msg {i}") is not None
        # 6th turn should be rejected
        assert store.add_turn(session.session_id, "user", "Overflow") is None

    def test_get_turns_empty_session(self):
        store = ConversationStore(persist=False)
        assert store.get_turns("nonexistent") == []


# =============================================================================
# Search Tests
# =============================================================================


class TestSearch:
    """Test conversation search."""

    def _setup_store(self):
        store = ConversationStore(persist=False)
        s1 = store.create_session(title="Auth Debugging")
        store.add_turn(s1.session_id, "user", "Fix the login authentication bug")
        store.add_turn(s1.session_id, "assistant", "Found the token validation issue")
        s2 = store.create_session(title="Feature Work")
        store.add_turn(s2.session_id, "user", "Add a new user profile page")
        store.add_turn(s2.session_id, "assistant", "Created the profile component")
        return store, s1, s2

    def test_basic_search(self):
        store, s1, s2 = self._setup_store()
        results = store.search("login authentication")
        assert len(results) > 0
        assert results[0].session_id == s1.session_id

    def test_search_returns_relevant(self):
        store, s1, s2 = self._setup_store()
        results = store.search("profile")
        assert any(r.session_id == s2.session_id for r in results)

    def test_search_no_results(self):
        store, s1, s2 = self._setup_store()
        results = store.search("completely unrelated query xyz123")
        assert len(results) == 0

    def test_search_by_session(self):
        store, s1, s2 = self._setup_store()
        results = store.search("the", session_id=s1.session_id)
        assert all(r.session_id == s1.session_id for r in results)

    def test_search_by_role(self):
        store, s1, s2 = self._setup_store()
        results = store.search("the", role="assistant")
        assert all(r.turn.role == "assistant" for r in results)

    def test_search_limit(self):
        store, s1, s2 = self._setup_store()
        results = store.search("the", limit=1)
        assert len(results) <= 1

    def test_search_empty_query(self):
        store, s1, s2 = self._setup_store()
        results = store.search("")
        assert len(results) == 0

    def test_search_score_range(self):
        store, s1, s2 = self._setup_store()
        results = store.search("login")
        for r in results:
            assert 0.0 <= r.score <= 1.0

    def test_search_result_to_dict(self):
        store, s1, s2 = self._setup_store()
        results = store.search("login")
        if results:
            d = results[0].to_dict()
            assert "session_id" in d
            assert "turn" in d
            assert "score" in d


# =============================================================================
# Summary Tests
# =============================================================================


class TestSummary:
    """Test conversation summaries."""

    def test_basic_summary(self):
        store = ConversationStore(persist=False)
        session = store.create_session(title="Test Session")
        store.add_turn(session.session_id, "user", "Hello", agent_id="user")
        store.add_turn(session.session_id, "assistant", "Hi there", agent_id="claude")
        summary = store.get_summary(session.session_id)
        assert summary is not None
        assert summary.title == "Test Session"
        assert summary.turn_count == 2
        assert "claude" in summary.agents_involved

    def test_summary_not_found(self):
        store = ConversationStore(persist=False)
        assert store.get_summary("nonexistent") is None

    def test_summary_first_last_message(self):
        store = ConversationStore(persist=False)
        session = store.create_session()
        store.add_turn(session.session_id, "user", "First message")
        store.add_turn(session.session_id, "assistant", "Last message")
        summary = store.get_summary(session.session_id)
        assert summary.first_message == "First message"
        assert summary.last_message == "Last message"

    def test_summary_to_dict(self):
        store = ConversationStore(persist=False)
        session = store.create_session(title="Test")
        store.add_turn(session.session_id, "user", "Hello")
        d = store.get_summary(session.session_id).to_dict()
        assert "session_id" in d
        assert "turn_count" in d
        assert "agents_involved" in d

    def test_summary_empty_session(self):
        store = ConversationStore(persist=False)
        session = store.create_session()
        summary = store.get_summary(session.session_id)
        assert summary.turn_count == 0
        assert summary.first_message == ""


# =============================================================================
# Persistence Tests
# =============================================================================


class TestPersistence:
    """Test disk persistence."""

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create and populate
            store1 = ConversationStore(storage_dir=tmpdir)
            session = store1.create_session(title="Persistent")
            store1.add_turn(session.session_id, "user", "Hello world")
            store1.add_turn(session.session_id, "assistant", "Hi!")

            # Reload
            store2 = ConversationStore(storage_dir=tmpdir)
            assert store2.session_count == 1
            loaded = store2.get_session(session.session_id)
            assert loaded is not None
            assert loaded.title == "Persistent"
            turns = store2.get_turns(session.session_id)
            assert len(turns) == 2
            assert turns[0].content == "Hello world"

    def test_sessions_json_created(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ConversationStore(storage_dir=tmpdir)
            store.create_session(title="Test")
            assert (Path(tmpdir) / "sessions.json").exists()

    def test_turns_jsonl_created(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ConversationStore(storage_dir=tmpdir)
            session = store.create_session()
            store.add_turn(session.session_id, "user", "Hello")
            turns_file = Path(tmpdir) / "turns" / f"{session.session_id}.jsonl"
            assert turns_file.exists()

    def test_delete_removes_turns_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ConversationStore(storage_dir=tmpdir)
            session = store.create_session()
            store.add_turn(session.session_id, "user", "Hello")
            turns_file = Path(tmpdir) / "turns" / f"{session.session_id}.jsonl"
            assert turns_file.exists()
            store.delete_session(session.session_id)
            assert not turns_file.exists()

    def test_persist_false_no_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ConversationStore(storage_dir=tmpdir, persist=False)
            store.create_session(title="Ephemeral")
            assert not (Path(tmpdir) / "sessions.json").exists()


# =============================================================================
# State Management Tests
# =============================================================================


class TestStateManagement:
    """Test state management."""

    def test_session_count(self):
        store = ConversationStore(persist=False)
        assert store.session_count == 0
        store.create_session()
        assert store.session_count == 1

    def test_total_turns(self):
        store = ConversationStore(persist=False)
        s1 = store.create_session()
        s2 = store.create_session()
        store.add_turn(s1.session_id, "user", "A")
        store.add_turn(s1.session_id, "assistant", "B")
        store.add_turn(s2.session_id, "user", "C")
        assert store.total_turns == 3

    def test_clear(self):
        store = ConversationStore(persist=False)
        store.create_session()
        store.create_session()
        count = store.clear()
        assert count == 2
        assert store.session_count == 0

    def test_to_dict(self):
        store = ConversationStore(persist=False)
        store.create_session()
        d = store.to_dict()
        assert d["session_count"] == 1
        assert d["persist"] is False

    def test_to_dict_empty(self):
        store = ConversationStore(persist=False)
        d = store.to_dict()
        assert d["session_count"] == 0
        assert d["total_turns"] == 0


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_memory_package(self):
        from core.memory_pkg.memory import (
            ConversationSearchResult,
            ConversationSession,
            ConversationStore,
            ConversationSummary,
            ConversationTurn,
        )

        assert all(
            [ConversationStore, ConversationSession, ConversationTurn, ConversationSummary, ConversationSearchResult]
        )

    def test_from_module(self):
        from core.memory_pkg.memory.conversation_store import (
            ConversationSession,
            ConversationStore,
            ConversationTurn,
        )

        assert all([ConversationStore, ConversationSession, ConversationTurn, ConversationSummary, SearchResult])
