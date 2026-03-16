"""
NEXUS V7.9 - Task Completion Validator Tests

Tests for the TaskCompletionValidator that prevents premature FINISHED signals.
"""

import tempfile
from pathlib import Path

import pytest

from core.intelligence.swarm.task_analyzer import TaskAnalysis, TaskComplexity, TaskDomain
from core.intelligence.swarm.task_completion_validator import (
    CompletionCriteria,
    TaskCompletionValidator,
    ValidationResult,
    get_adaptive_max_rounds,
)


class TestAdaptiveMaxRounds:
    """Test adaptive max_rounds based on complexity."""

    def test_trivial_gets_few_rounds(self):
        """Trivial tasks should have few rounds."""
        rounds = get_adaptive_max_rounds(TaskComplexity.TRIVIAL)
        assert rounds == 3

    def test_moderate_gets_standard_rounds(self):
        """Moderate tasks should have standard rounds."""
        rounds = get_adaptive_max_rounds(TaskComplexity.MODERATE)
        assert rounds == 6

    def test_complex_gets_more_rounds(self):
        """Complex tasks should have more rounds."""
        rounds = get_adaptive_max_rounds(TaskComplexity.COMPLEX)
        assert rounds == 10

    def test_expert_gets_most_rounds(self):
        """Expert tasks should have most rounds."""
        rounds = get_adaptive_max_rounds(TaskComplexity.EXPERT)
        assert rounds == 15

    def test_rounds_increase_with_complexity(self):
        """Rounds should increase with complexity level."""
        complexities = [TaskComplexity.TRIVIAL, TaskComplexity.MODERATE, TaskComplexity.COMPLEX, TaskComplexity.EXPERT]
        rounds = [get_adaptive_max_rounds(c) for c in complexities]
        # Not strictly increasing because SIMPLE == MODERATE, but generally
        assert rounds[-1] > rounds[0]


class TestTaskCompletionValidator:
    """Test TaskCompletionValidator functionality."""

    @pytest.fixture
    def validator(self):
        """Create validator with temp workspace."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield TaskCompletionValidator(Path(tmpdir))

    @pytest.fixture
    def simple_analysis(self):
        """Create simple task analysis."""
        return TaskAnalysis(
            complexity=TaskComplexity.MODERATE,
            domains=[TaskDomain.CODING],
            primary_domain=TaskDomain.CODING,
            raw_input="Fix the auth bug",
        )

    @pytest.fixture
    def complex_analysis(self):
        """Create complex task analysis."""
        return TaskAnalysis(
            complexity=TaskComplexity.COMPLEX,
            domains=[TaskDomain.CODING, TaskDomain.SECURITY],
            primary_domain=TaskDomain.CODING,
            raw_input="Refactor the authentication system",
        )

    def test_validator_creation(self, validator):
        """Test validator can be created."""
        assert validator is not None

    def test_quick_validate_with_finished(self, validator):
        """Test quick_validate detects FINISHED signal."""
        is_valid, reason = validator.quick_validate("Task is complete. FINISHED.")
        assert is_valid is True
        assert "Completion signal found" in reason

    def test_quick_validate_rejects_ongoing_work(self, validator):
        """Test quick_validate rejects responses with ongoing work."""
        response = "FINISHED with part one. Now I will continue with part two."
        is_valid, reason = validator.quick_validate(response)
        assert is_valid is False
        assert "Mixed signals" in reason

    def test_quick_validate_no_signal(self, validator):
        """Test quick_validate when no completion signal."""
        is_valid, reason = validator.quick_validate("Still working on the task...")
        assert is_valid is False
        assert "No completion signal" in reason

    def test_validate_completion_basic(self, validator, simple_analysis):
        """Test full validation with basic response."""
        result = validator.validate_completion(
            task_input="Fix the auth bug",
            agent_response="I fixed the bug in auth.py. Created a new test. FINISHED.",
            task_analysis=simple_analysis,
            tool_results=[],
        )
        assert isinstance(result, ValidationResult)
        assert result.confidence > 0

    def test_validate_completion_rejects_ongoing(self, validator, simple_analysis):
        """Test validation rejects response with ongoing work indicators."""
        result = validator.validate_completion(
            task_input="Fix the auth bug",
            agent_response="I fixed one issue. FINISHED. But I still need to fix another issue.",
            task_analysis=simple_analysis,
            tool_results=[],
        )
        # Should have missing criteria due to ongoing work
        assert len(result.missing_criteria) > 0

    def test_validate_completion_needs_tool_calls_for_complex(self, validator, complex_analysis):
        """Test validation requires tool calls for complex tasks."""
        result = validator.validate_completion(
            task_input="Refactor the authentication system",
            agent_response="I refactored everything. DONE.",
            task_analysis=complex_analysis,
            tool_results=[],  # No tool calls!
        )
        # Should detect missing tool calls
        assert not result.is_valid or len(result.missing_criteria) > 0


class TestCompletionCriteria:
    """Test CompletionCriteria dataclass."""

    def test_default_criteria(self):
        """Test default criteria values."""
        criteria = CompletionCriteria()
        assert criteria.requires_file_changes is False
        assert criteria.min_tool_calls == 0
        assert criteria.expected_artifacts == []

    def test_custom_criteria(self):
        """Test custom criteria values."""
        criteria = CompletionCriteria(
            requires_file_changes=True, min_tool_calls=3, expected_artifacts=["file.py", "test.py"]
        )
        assert criteria.requires_file_changes is True
        assert criteria.min_tool_calls == 3
        assert len(criteria.expected_artifacts) == 2


class TestValidationResult:
    """Test ValidationResult dataclass."""

    def test_result_to_dict(self):
        """Test ValidationResult serialization."""
        result = ValidationResult(
            is_valid=True, confidence=0.85, reason="All checks passed", missing_criteria=[], warnings=["Minor warning"]
        )
        d = result.to_dict()
        assert d["is_valid"] is True
        assert d["confidence"] == 0.85
        assert d["reason"] == "All checks passed"
        assert len(d["warnings"]) == 1


class TestIsFinishedImproved:
    """Test the improved is_finished property in AgentResponse."""

    def test_clear_finished(self):
        """Test clear FINISHED signal is detected."""
        from core.intelligence.swarm.mode_executors import AgentResponse

        resp = AgentResponse(agent_id="test", content="All done. FINISHED.")
        assert resp.is_finished is True

    def test_done_signal(self):
        """Test DONE signal is detected."""
        from core.intelligence.swarm.mode_executors import AgentResponse

        resp = AgentResponse(agent_id="test", content="Task completed. DONE.")
        assert resp.is_finished is True

    def test_task_complete_signal(self):
        """Test TASK COMPLETE signal is detected."""
        from core.intelligence.swarm.mode_executors import AgentResponse

        resp = AgentResponse(agent_id="test", content="TASK COMPLETE. Everything is ready.")
        assert resp.is_finished is True

    def test_rejects_ongoing_will(self):
        """Test rejection when 'will' indicates future work."""
        from core.intelligence.swarm.mode_executors import AgentResponse

        resp = AgentResponse(agent_id="test", content="FINISHED with this part. I will continue with the next.")
        assert resp.is_finished is False

    def test_rejects_ongoing_next_step(self):
        """Test rejection when 'next step' indicates future work."""
        from core.intelligence.swarm.mode_executors import AgentResponse

        resp = AgentResponse(agent_id="test", content="DONE. The next step is to implement tests.")
        assert resp.is_finished is False

    def test_rejects_ongoing_need_to(self):
        """Test rejection when 'need to' indicates remaining work."""
        from core.intelligence.swarm.mode_executors import AgentResponse

        resp = AgentResponse(agent_id="test", content="FINISHED the refactoring but we need to update the docs.")
        assert resp.is_finished is False

    def test_rejects_ongoing_todo(self):
        """Test rejection when 'todo' indicates remaining work."""
        from core.intelligence.swarm.mode_executors import AgentResponse

        resp = AgentResponse(agent_id="test", content="DONE! TODO: add error handling later.")
        assert resp.is_finished is False

    def test_no_signal_returns_false(self):
        """Test no completion signal returns False."""
        from core.intelligence.swarm.mode_executors import AgentResponse

        resp = AgentResponse(agent_id="test", content="Working on the implementation...")
        assert resp.is_finished is False

    def test_status_finished(self):
        """Test status='finished' is detected."""
        from core.intelligence.swarm.mode_executors import AgentResponse

        resp = AgentResponse(agent_id="test", content="Task result here", status="finished")
        assert resp.is_finished is True
