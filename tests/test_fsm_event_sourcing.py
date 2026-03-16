"""
Tests for FSM Event Sourcing (V12.4).

Validates:
- TransitionEvent creation and serialization
- Append-only event store (JSONL backend)
- Replay for crash recovery
- Interrupted session detection
- Event trimming
"""

import json

import pytest

from core.fsm.event_sourcing import (
    FSMEventStore,
    TransitionEvent,
    record_transition,
)


@pytest.fixture
def tmp_workspace(tmp_path):
    """Create a temporary workspace for event store."""
    nexus_dir = tmp_path / ".nexus"
    nexus_dir.mkdir()
    return tmp_path


@pytest.fixture
def store(tmp_workspace):
    """Create an FSMEventStore with temp workspace."""
    return FSMEventStore(workspace_path=tmp_workspace)


class TestTransitionEvent:
    """Test TransitionEvent dataclass."""

    def test_create_event(self):
        event = TransitionEvent(
            from_state="IDLE",
            to_state="BRAINSTORMING",
            trigger="user_input",
        )
        assert event.from_state == "IDLE"
        assert event.to_state == "BRAINSTORMING"
        assert event.trigger == "user_input"
        assert event.event_id  # auto-generated
        assert event.timestamp  # auto-generated

    def test_to_dict(self):
        event = TransitionEvent(
            from_state="IDLE",
            to_state="BRAINSTORMING",
            trigger="user_input",
            session_id="sess_123",
        )
        d = event.to_dict()
        assert d["from_state"] == "IDLE"
        assert d["to_state"] == "BRAINSTORMING"
        assert d["session_id"] == "sess_123"

    def test_to_json(self):
        event = TransitionEvent(
            from_state="IDLE",
            to_state="BRAINSTORMING",
            trigger="user_input",
        )
        j = event.to_json()
        parsed = json.loads(j)
        assert parsed["from_state"] == "IDLE"
        assert parsed["to_state"] == "BRAINSTORMING"

    def test_from_dict(self):
        data = {
            "from_state": "BRAINSTORMING",
            "to_state": "EXECUTING_TOOL",
            "trigger": "tool_request",
            "session_id": "sess_456",
            "event_id": "abc123",
            "timestamp": "2026-02-15T12:00:00+00:00",
        }
        event = TransitionEvent.from_dict(data)
        assert event.from_state == "BRAINSTORMING"
        assert event.to_state == "EXECUTING_TOOL"
        assert event.session_id == "sess_456"

    def test_from_dict_ignores_extra_fields(self):
        data = {
            "from_state": "A",
            "to_state": "B",
            "trigger": "test",
            "unknown_field": "ignored",
        }
        event = TransitionEvent.from_dict(data)
        assert event.from_state == "A"

    def test_metadata(self):
        event = TransitionEvent(
            from_state="IDLE",
            to_state="BRAINSTORMING",
            trigger="user_input",
            metadata={"task": "analyze code", "turn": 1},
        )
        assert event.metadata["task"] == "analyze code"
        assert event.metadata["turn"] == 1


class TestFSMEventStore:
    """Test the event store."""

    def test_append_and_replay(self, store):
        """Basic append + replay cycle."""
        store.append(TransitionEvent("IDLE", "BRAINSTORMING", "user_input"))
        store.append(TransitionEvent("BRAINSTORMING", "EXECUTING_TOOL", "tool_request"))
        store.append(TransitionEvent("EXECUTING_TOOL", "IDLE", "tool_complete"))

        events = store.replay()
        assert len(events) == 3
        assert events[0].from_state == "IDLE"
        assert events[1].from_state == "BRAINSTORMING"
        assert events[2].to_state == "IDLE"

    def test_replay_empty_store(self, store):
        """Empty store returns empty list."""
        assert store.replay() == []

    def test_replay_with_session_filter(self, store):
        """Filter events by session_id."""
        store.append(TransitionEvent("IDLE", "BRAINSTORMING", "input", session_id="s1"))
        store.append(TransitionEvent("IDLE", "BRAINSTORMING", "input", session_id="s2"))
        store.append(TransitionEvent("BRAINSTORMING", "IDLE", "done", session_id="s1"))

        s1_events = store.replay(session_id="s1")
        assert len(s1_events) == 2

        s2_events = store.replay(session_id="s2")
        assert len(s2_events) == 1

    def test_get_last_state(self, store):
        """Get last known state."""
        assert store.get_last_state() is None

        store.append(TransitionEvent("IDLE", "BRAINSTORMING", "input"))
        store.append(TransitionEvent("BRAINSTORMING", "EXECUTING_TOOL", "tool"))

        assert store.get_last_state() == "EXECUTING_TOOL"

    def test_get_last_state_by_session(self, store):
        """Get last state for specific session."""
        store.append(TransitionEvent("IDLE", "BRAINSTORMING", "input", session_id="s1"))
        store.append(TransitionEvent("IDLE", "ERROR", "crash", session_id="s2"))

        assert store.get_last_state(session_id="s1") == "BRAINSTORMING"
        assert store.get_last_state(session_id="s2") == "ERROR"

    def test_interrupted_sessions(self, store):
        """Detect sessions that were interrupted mid-execution."""
        # Session 1: cleanly completed
        store.append(TransitionEvent("IDLE", "BRAINSTORMING", "input", session_id="clean"))
        store.append(TransitionEvent("BRAINSTORMING", "IDLE", "done", session_id="clean"))

        # Session 2: interrupted during execution
        store.append(TransitionEvent("IDLE", "BRAINSTORMING", "input", session_id="crash"))
        store.append(TransitionEvent("BRAINSTORMING", "EXECUTING_TOOL", "tool", session_id="crash"))

        interrupted = store.get_interrupted_sessions()
        assert len(interrupted) == 1
        assert interrupted[0]["session_id"] == "crash"
        assert interrupted[0]["last_state"] == "EXECUTING_TOOL"

    def test_trim(self, store):
        """Trim keeps only recent events."""
        for i in range(20):
            store.append(TransitionEvent(f"S{i}", f"S{i + 1}", "step"))

        trimmed = store.trim(keep_last=5)
        assert trimmed == 15

        events = store.replay()
        assert len(events) == 5
        assert events[0].from_state == "S15"

    def test_trim_noop_when_under_limit(self, store):
        """Trim does nothing when under limit."""
        store.append(TransitionEvent("IDLE", "BRAINSTORMING", "input"))
        trimmed = store.trim(keep_last=100)
        assert trimmed == 0

    def test_persistence_across_instances(self, tmp_workspace):
        """Events persist across store instances (same workspace)."""
        store1 = FSMEventStore(workspace_path=tmp_workspace)
        store1.append(TransitionEvent("IDLE", "BRAINSTORMING", "input"))

        store2 = FSMEventStore(workspace_path=tmp_workspace)
        events = store2.replay()
        assert len(events) == 1
        assert events[0].to_state == "BRAINSTORMING"

    def test_corrupted_lines_skipped(self, store):
        """Corrupted JSONL lines are silently skipped."""
        store.append(TransitionEvent("IDLE", "BRAINSTORMING", "input"))

        # Inject corrupted line
        events_file = store._events_file
        with open(events_file, "a", encoding="utf-8") as f:
            f.write("NOT VALID JSON\n")
            f.write('{"from_state": "BRAINSTORMING", "to_state": "IDLE", "trigger": "done"}\n')

        events = store.replay()
        assert len(events) == 2  # Corrupted line skipped
        assert events[0].to_state == "BRAINSTORMING"
        assert events[1].to_state == "IDLE"


class TestConvenienceFunctions:
    """Test module-level convenience functions."""

    def test_record_transition(self, tmp_workspace, monkeypatch):
        """record_transition() creates and appends event."""
        import core.fsm.event_sourcing as es

        monkeypatch.setattr(es, "_global_store", FSMEventStore(tmp_workspace))

        record_transition("IDLE", "BRAINSTORMING", "user_input", session_id="test")

        store = es._global_store
        events = store.replay()
        assert len(events) == 1
        assert events[0].from_state == "IDLE"
        assert events[0].session_id == "test"
