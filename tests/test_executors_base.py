"""
Tests for core/swarm/executors/base.py - V9.5

Validates executor base classes and patterns.
"""

import pytest

from core.intelligence.swarm.collaboration_modes import CollaborationMode
from core.intelligence.swarm.executors.base import (
    COMPLETION_PATTERN,
    AgentResponse,
    ExecutionContext,
    ExecutionError,
    ExecutionResult,
    ExecutionStatus,
)
from core.intelligence.swarm.mode_selector import AgentAssignment


class TestExecutionStatus:
    """Test ExecutionStatus enum."""

    def test_status_values_exist(self):
        """All expected status values should exist."""
        assert ExecutionStatus.PENDING
        assert ExecutionStatus.IN_PROGRESS
        assert ExecutionStatus.COMPLETED
        assert ExecutionStatus.FAILED
        assert ExecutionStatus.CONVERGED

    def test_status_string_values(self):
        """Status should have correct string values."""
        assert ExecutionStatus.PENDING.value == "pending"
        assert ExecutionStatus.COMPLETED.value == "completed"


class TestAgentResponse:
    """Test AgentResponse dataclass."""

    def test_create_response(self):
        """Should create response with required fields."""
        response = AgentResponse(agent_id="gemini", content="Hello world")
        assert response.agent_id == "gemini"
        assert response.content == "Hello world"
        assert response.status == "success"

    def test_response_with_error(self):
        """Should create error response."""
        response = AgentResponse(agent_id="claude", content="", status="error", error="Something went wrong")
        assert response.status == "error"
        assert response.error == "Something went wrong"

    def test_is_finished_completion_signal(self):
        """Should detect completion signals."""
        response = AgentResponse(agent_id="test", content="Task COMPLETED successfully.")
        assert response.is_finished is True

    def test_is_finished_with_ongoing(self):
        """Should reject completion if ongoing work detected."""
        response = AgentResponse(agent_id="test", content="COMPLETED first part. Will continue with next step.")
        assert response.is_finished is False

    def test_is_finished_no_signal(self):
        """Should return False without completion signal."""
        response = AgentResponse(agent_id="test", content="Working on the task...")
        assert response.is_finished is False

    def test_to_dict(self):
        """Should convert to dictionary."""
        response = AgentResponse(agent_id="gemini", content="Result", tokens_used=100, time_seconds=1.5)
        data = response.to_dict()
        assert data["agent_id"] == "gemini"
        assert data["content"] == "Result"
        assert data["tokens_used"] == 100


class TestExecutionContext:
    """Test ExecutionContext dataclass."""

    def test_create_context(self):
        """Should create context with required fields."""
        assignments = [
            AgentAssignment(agent_id="gemini", role="lead"),
            AgentAssignment(agent_id="claude", role="support"),
        ]
        context = ExecutionContext(
            task_input="Do something",
            agent_assignments=assignments,
        )
        assert context.task_input == "Do something"
        assert len(context.agent_assignments) == 2
        assert context.max_rounds == 6  # Default

    def test_get_agent_by_role(self):
        """Should find agent by role."""
        assignments = [
            AgentAssignment(agent_id="gemini", role="lead"),
            AgentAssignment(agent_id="claude", role="support"),
        ]
        context = ExecutionContext(
            task_input="task",
            agent_assignments=assignments,
        )
        lead = context.get_agent_by_role("lead")
        assert lead is not None
        assert lead.agent_id == "gemini"

    def test_get_agent_by_role_not_found(self):
        """Should return None for unknown role."""
        context = ExecutionContext(
            task_input="task",
            agent_assignments=[],
        )
        result = context.get_agent_by_role("unknown")
        assert result is None

    def test_get_all_agents(self):
        """Should return all agents."""
        assignments = [
            AgentAssignment(agent_id="gemini", role="lead"),
            AgentAssignment(agent_id="claude", role="support"),
        ]
        context = ExecutionContext(
            task_input="task",
            agent_assignments=assignments,
        )
        all_agents = context.get_all_agents()
        assert len(all_agents) == 2


class TestExecutionResult:
    """Test ExecutionResult dataclass."""

    def test_create_result(self):
        """Should create result with required fields."""
        result = ExecutionResult(
            mode=CollaborationMode.PARALLEL,
            status=ExecutionStatus.COMPLETED,
            final_output="Done",
            agent_outputs=[],
            total_rounds=1,
            total_tokens=100,
            total_time_seconds=2.5,
        )
        assert result.mode == CollaborationMode.PARALLEL
        assert result.status == ExecutionStatus.COMPLETED
        assert result.finished is True

    def test_finished_property(self):
        """Should correctly report finished status."""
        completed = ExecutionResult(
            mode=CollaborationMode.SEQUENTIAL,
            status=ExecutionStatus.COMPLETED,
            final_output="",
            agent_outputs=[],
            total_rounds=1,
            total_tokens=0,
            total_time_seconds=0,
        )
        assert completed.finished is True

        converged = ExecutionResult(
            mode=CollaborationMode.PING_PONG,
            status=ExecutionStatus.CONVERGED,
            final_output="",
            agent_outputs=[],
            total_rounds=3,
            total_tokens=0,
            total_time_seconds=0,
        )
        assert converged.finished is True

        failed = ExecutionResult(
            mode=CollaborationMode.LEAD_SUPPORT,
            status=ExecutionStatus.FAILED,
            final_output="",
            agent_outputs=[],
            total_rounds=1,
            total_tokens=0,
            total_time_seconds=0,
        )
        assert failed.finished is False

    def test_to_dict(self):
        """Should convert to dictionary."""
        result = ExecutionResult(
            mode=CollaborationMode.PARALLEL,
            status=ExecutionStatus.COMPLETED,
            final_output="Result",
            agent_outputs=[],
            total_rounds=1,
            total_tokens=50,
            total_time_seconds=1.0,
        )
        data = result.to_dict()
        assert data["mode"] == "parallel"
        assert data["status"] == "completed"
        assert data["total_rounds"] == 1


class TestCompletionPattern:
    """Test completion detection regex."""

    def test_detects_finished(self):
        """Should detect FINISHED keyword."""
        assert COMPLETION_PATTERN.search("Task FINISHED") is not None

    def test_detects_completed(self):
        """Should detect COMPLETED keyword."""
        assert COMPLETION_PATTERN.search("COMPLETED successfully") is not None

    def test_detects_task_complete(self):
        """Should detect TASK COMPLETE phrase."""
        assert COMPLETION_PATTERN.search("TASK COMPLETE") is not None

    def test_word_boundary(self):
        """Should respect word boundaries."""
        # These should NOT match
        assert COMPLETION_PATTERN.search("unfinished") is None
        assert COMPLETION_PATTERN.search("incomplete") is None


class TestExecutionError:
    """Test ExecutionError exception."""

    def test_raise_error(self):
        """Should be raiseable."""
        with pytest.raises(ExecutionError):
            raise ExecutionError("Test error")

    def test_error_message(self):
        """Should preserve error message."""
        try:
            raise ExecutionError("Custom message")
        except ExecutionError as e:
            assert "Custom message" in str(e)


class TestBackwardCompatibility:
    """Test backward compatibility with mode_executors."""

    def test_import_from_mode_executors(self):
        """Should be importable from original location."""
        from core.intelligence.swarm.mode_executors import (
            AgentResponse,
            ExecutionStatus,
        )

        # Just verify imports work
        assert ExecutionStatus is not None
        assert AgentResponse is not None

    def test_parallel_executor_exists(self):
        """ParallelExecutor should be importable."""
        from core.intelligence.swarm.mode_executors import ParallelExecutor

        assert ParallelExecutor is not None
