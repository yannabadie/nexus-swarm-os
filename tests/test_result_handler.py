"""
Tests for ResultHandler - P5.1 Phase 3 Extraction

Validates result handling logic extracted from OrchestratorV7.
"""

import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.execution_pkg.orchestration.result_handler import ResultHandler


class TestResultHandler:
    """Test ResultHandler result creation and validation."""

    @pytest.fixture
    def mock_orch(self):
        """Create mock orchestrator."""
        orch = Mock()
        orch._current_task_start = 0
        orch._current_task_type = "test"
        orch._current_task_description = "test task"
        orch._current_swarm_mode = "ping_pong"
        orch.auto_memory = Mock()
        return orch

    @pytest.fixture
    def handler(self, mock_orch):
        """Create ResultHandler instance."""
        return ResultHandler(mock_orch)

    # =========================================================================
    # make_result() tests
    # =========================================================================

    def test_make_result_basic(self, handler):
        """make_result should create result dict with basic fields."""
        result = handler.make_result(state="IDLE", output="Hello", agent="claude", finished=False)

        assert result["state"] == "IDLE"
        assert result["output"] == "Hello"
        assert result["agent"] == "claude"
        assert result["finished"] is False

    def test_make_result_with_error(self, handler):
        """make_result should include error field if provided."""
        result = handler.make_result(
            state="ERROR", output="Error occurred", agent=None, finished=False, error="TEST_ERROR"
        )

        assert result["error"] == "TEST_ERROR"

    def test_make_result_with_tool(self, handler):
        """make_result should include tool field if provided."""
        result = handler.make_result(
            state="EXECUTING_TOOL", output="Tool executed", agent="gemini", finished=False, tool="read_file"
        )

        assert result["tool"] == "read_file"

    def test_make_result_with_metadata(self, handler):
        """make_result should include metadata if provided."""
        result = handler.make_result(
            state="WAITING_USER",
            output="Done",
            agent="claude",
            finished=True,
            metadata={"fast_path": True, "latency": 0.5},
        )

        assert result["metadata"]["fast_path"] is True
        assert result["metadata"]["latency"] == 0.5

    def test_make_result_finished_no_recording(self, handler, mock_orch):
        """make_result should not record if task_start not set."""
        mock_orch._current_task_start = 0  # Not started

        handler.make_result(state="FINISHED", output="Task complete", agent="gemini", finished=True)

        # Should not call auto_memory
        mock_orch.auto_memory.record_success.assert_not_called()
        mock_orch.auto_memory.record_failure.assert_not_called()

    def test_make_result_finished_success_recording(self, handler, mock_orch):
        """make_result should record success when task finishes."""
        import time

        mock_orch._current_task_start = time.time() - 5.0  # 5 seconds ago

        handler.make_result(state="FINISHED", output="Task complete", agent="claude", finished=True)

        # Should call record_success
        mock_orch.auto_memory.record_success.assert_called_once()
        call_kwargs = mock_orch.auto_memory.record_success.call_args.kwargs
        assert call_kwargs["task_type"] == "test"
        assert call_kwargs["lead_agent"] == "claude"
        assert call_kwargs["score"] == 1.0

    def test_make_result_finished_failure_recording(self, handler, mock_orch):
        """make_result should record failure when task finishes with error."""
        import time

        mock_orch._current_task_start = time.time() - 3.0  # 3 seconds ago

        handler.make_result(state="FINISHED", output="Task failed", agent="gemini", finished=True, error="TIMEOUT")

        # Should call record_failure
        mock_orch.auto_memory.record_failure.assert_called_once()
        call_kwargs = mock_orch.auto_memory.record_failure.call_args.kwargs
        assert call_kwargs["task_type"] == "test"
        assert call_kwargs["lead_agent"] == "gemini"
        assert call_kwargs["reason"] == "TIMEOUT"

    def test_make_result_resets_task_start(self, handler, mock_orch):
        """make_result should reset task_start after recording."""
        import time

        mock_orch._current_task_start = time.time()

        handler.make_result(state="FINISHED", output="Done", agent="claude", finished=True)

        assert mock_orch._current_task_start == 0

    # =========================================================================
    # validate_message() tests
    # =========================================================================

    def test_validate_message_light(self, handler):
        """validate_message should accept valid LightMessageV7."""
        response = {"action_type": "TALK", "content": "Test message", "sender": "claude", "agent_id": "claude"}

        validated = handler.validate_message(response)

        assert validated["action_type"] == "TALK"
        assert validated["content"] == "Test message"

    def test_validate_message_heavy(self, handler):
        """validate_message should accept valid HeavyMessageV7."""
        response = {
            "action_type": "TOOL_USE",
            "content": "Using tool",
            "sender": "gemini",
            "agent_id": "gemini",
            "tool_uses": [{"tool_name": "read", "tool_args": {"file_path": "test.py"}}],
        }

        validated = handler.validate_message(response, expect_heavy=True)

        assert validated["action_type"] == "TOOL_USE"

    def test_validate_message_auto_detect_heavy(self, handler):
        """validate_message should auto-detect TOOL_USE."""
        response = {
            "action_type": "TOOL_USE",
            "content": "Using tool",
            "sender": "claude",
            "agent_id": "claude",
            "tool_uses": [{"tool_name": "write", "tool_args": {"file_path": "output.txt", "content": "data"}}],
        }

        # Don't pass expect_heavy, should auto-detect from action_type
        validated = handler.validate_message(response)

        assert validated["action_type"] == "TOOL_USE"

    def test_validate_message_invalid_schema(self, handler):
        """validate_message should raise ValueError for invalid schema."""
        response = {"action_type": "INVALID_ACTION", "content": "Test"}

        with pytest.raises(ValueError, match="Invalid message schema"):
            handler.validate_message(response)

    def test_validate_message_missing_required(self, handler):
        """validate_message should raise ValueError for missing fields."""
        response = {
            "action_type": "TALK"
            # Missing required fields: content, agent_id
        }

        with pytest.raises(ValueError, match="Invalid message schema"):
            handler.validate_message(response)

    # =========================================================================
    # format_tool_result() tests
    # =========================================================================

    def test_format_tool_result(self, handler):
        """format_tool_result should format result for display."""
        result = Mock()
        result.tool_name = "read"
        result.status = "SUCCESS"
        result.output = "File contents: Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua."

        formatted = handler.format_tool_result(result)

        assert "[Tool: read]" in formatted
        assert "SUCCESS" in formatted
        assert len(formatted) < 200  # Output truncated to 100 chars

    def test_format_tool_result_short_output(self, handler):
        """format_tool_result should handle short output."""
        result = Mock()
        result.tool_name = "write"
        result.status = "SUCCESS"
        result.output = "File written"

        formatted = handler.format_tool_result(result)

        assert "[Tool: write]" in formatted
        assert "SUCCESS" in formatted
        assert "File written" in formatted


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
