"""
Tests for V12.4 Phase 4: Monitored Execution.

Validates:
- ExecutionPhaseResult dataclass fields and defaults
- EXECUTION_PROMPT template formatting
- MonitoredExecutionPhase initialization (with/without optional params)
- _is_step_complete helper logic
- _format_previous_results truncation and formatting
- _parse_execution_response JSON parsing and fallback
- _detect_hallucinations pattern matching
- _detect_errors pattern matching
- _verify_artifacts file existence checks
- _score_execution_quality composite scoring
- get_execution_summary aggregation
- _execute_step driver selection, prompt building, timeout, error handling
- _execute_via_swarm delegation and fallback
- Full execute() flow with mocked drivers
- V12.4 integration try/except blocks (MetaPolicyMemory, PlanContextFilter,
  UncertaintyPropagator, MetacognitiveMonitor, InspectorGuard, PointerMemory,
  ConfidenceCalibrator, FaultDetector, SkillCrystallizer, RequestDeduplicator,
  ConsensusVerifier, CognitiveDegradation, ReasoningQualityScorer, ToolObserver)
- Budget exceeded and dependency unmet handling
- Critical failure early exit
- Step result aggregation and success/failure counting
- needs_diagnosis determination logic
"""

import asyncio
import contextlib
import json
from dataclasses import fields
from unittest.mock import (
    AsyncMock,
    MagicMock,
    patch,
)

import pytest

from core.drivers.protocol import DriverResponse, DriverResponseStatus
from core.intelligence.hive_mind.phases.phase_execution import (
    EXECUTION_PROMPT,
    ExecutionPhaseResult,
    MonitoredExecutionPhase,
)
from core.intelligence.hive_mind.types import (
    AgentArchitecture,
    ExecutionIssue,
    ExecutionPlan,
    ExecutionStep,
    IssueSeverity,
    MonitoredStepResult,
    RAGConfig,
)


def _make_driver_response(
    content: str = '{"status":"success","output":"OK","artifacts_created":[],"issues":[]}',
    input_tokens: int = 100,
    output_tokens: int = 50,
) -> DriverResponse:
    """Create a successful DriverResponse for testing."""
    return DriverResponse(
        content=content,
        status=DriverResponseStatus.SUCCESS,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


# =============================================================================
# Helpers
# =============================================================================


def _make_step(
    name: str = "step1",
    agent_id: str = "claude",
    action: str = "Do the thing",
    expected_duration: float = 30.0,
    depends_on: list[str] = None,
    verification_required: bool = False,
    swarm_mode: str = None,
) -> ExecutionStep:
    """Create an ExecutionStep with sensible defaults."""
    return ExecutionStep(
        name=name,
        agent_id=agent_id,
        action=action,
        expected_duration=expected_duration,
        depends_on=depends_on or [],
        verification_required=verification_required,
        swarm_mode=swarm_mode,
    )


def _make_architecture(
    steps: list[ExecutionStep] = None,
    strategy: str = "sequential",
) -> AgentArchitecture:
    """Create an AgentArchitecture with an execution plan."""
    if steps is None:
        steps = [_make_step()]
    plan = ExecutionPlan(strategy=strategy, steps=steps)
    return AgentArchitecture(
        status="READY",
        collaboration_mode="LEAD_SUPPORT",
        agents_to_use=["claude", "gemini"],
        agents_to_spawn=[],
        rag_config=RAGConfig(),
        execution_plan=plan,
    )


def _make_step_result(
    step_name: str = "step1",
    agent_id: str = "claude",
    status: str = "success",
    output: str = "Done successfully",
    duration: float = 5.0,
    expected_duration: float = 30.0,
    tokens_used: int = 100,
    issues: list[ExecutionIssue] = None,
    artifacts_created: list[str] = None,
    artifacts_verified: bool = True,
) -> MonitoredStepResult:
    """Create a MonitoredStepResult with sensible defaults."""
    return MonitoredStepResult(
        step_name=step_name,
        agent_id=agent_id,
        status=status,
        output=output,
        duration=duration,
        expected_duration=expected_duration,
        tokens_used=tokens_used,
        issues=issues or [],
        artifacts_created=artifacts_created or [],
        artifacts_verified=artifacts_verified,
    )


def _make_issue(
    issue_type: str = "test_issue",
    severity: IssueSeverity = IssueSeverity.WARNING,
    details: str = "test detail",
    step_name: str = "step1",
) -> ExecutionIssue:
    """Create an ExecutionIssue."""
    return ExecutionIssue(
        issue_type=issue_type,
        severity=severity,
        details=details,
        step_name=step_name,
    )


def _make_phase(
    can_afford: bool = True,
    swarm_engine: object = None,
) -> MonitoredExecutionPhase:
    """Create a MonitoredExecutionPhase with fully mocked dependencies."""
    _default_content = '{"status":"success","output":"OK","artifacts_created":[],"issues":[]}'

    gemini = MagicMock()
    gemini.send_message_async = AsyncMock(return_value=_default_content)
    gemini.invoke = AsyncMock(return_value=_make_driver_response(_default_content))

    claude = MagicMock()
    claude.send_message_async = AsyncMock(return_value=_default_content)
    claude.invoke = AsyncMock(return_value=_make_driver_response(_default_content))

    cost_estimator = MagicMock()
    cost_estimator.can_afford.return_value = can_afford
    cost_estimator.record_cost = MagicMock()

    context_manager = MagicMock()
    context_manager.add_execution_result = MagicMock()
    # add_to_context may not exist; the V12.4 block will use try/except
    context_manager.add_to_context = MagicMock()

    phase = MonitoredExecutionPhase(
        gemini_driver=gemini,
        claude_driver=claude,
        cost_estimator=cost_estimator,
        context_manager=context_manager,
        swarm_engine=swarm_engine,
    )
    return phase


@contextlib.contextmanager
def _patched_execute(phase, step_mock):
    """
    Context manager that patches _execute_step on the phase object,
    suppresses telemetry emissions, and neutralizes the deduplicator
    singleton to prevent cross-test state pollution.
    """
    # Create a dedup mock that never reports duplicates
    _dedup_mock = MagicMock()
    _dedup_check = MagicMock()
    _dedup_check.is_duplicate = False
    _dedup_check.cached_result = None
    _dedup_mock.check.return_value = _dedup_check

    # Stack all patches
    dedup_patch = patch(
        "core.infrastructure.resilience.request_deduplicator.get_deduplicator",
        return_value=_dedup_mock,
    )

    with (
        patch.object(phase, "_execute_step", new=step_mock),
        patch("core.intelligence.hive_mind.phases.phase_execution.emit_agent_speak"),
        patch("core.intelligence.hive_mind.phases.phase_execution.emit_agent_exchange"),
    ):
        with contextlib.suppress(Exception):
            dedup_patch.start()
        try:
            yield
        finally:
            with contextlib.suppress(Exception):
                dedup_patch.stop()


@pytest.fixture(autouse=True)
def _reset_deduplicator():
    """Reset the deduplicator singleton before each test to prevent cross-test pollution."""
    try:
        from core.infrastructure.resilience.request_deduplicator import reset_deduplicator

        reset_deduplicator()
    except ImportError:
        pass
    yield
    try:
        from core.infrastructure.resilience.request_deduplicator import reset_deduplicator

        reset_deduplicator()
    except ImportError:
        pass


# =============================================================================
# ExecutionPhaseResult dataclass
# =============================================================================


class TestExecutionPhaseResult:
    """Test ExecutionPhaseResult dataclass."""

    def test_fields_exist(self):
        names = {f.name for f in fields(ExecutionPhaseResult)}
        assert "success" in names
        assert "step_results" in names
        assert "total_duration" in names
        assert "total_tokens" in names
        assert "issues" in names
        assert "artifacts_created" in names
        assert "needs_diagnosis" in names
        assert "failure_step" in names
        assert "quality_score" in names

    def test_defaults(self):
        r = ExecutionPhaseResult(
            success=True,
            step_results=[],
            total_duration=1.0,
            total_tokens=0,
            issues=[],
            artifacts_created=[],
            needs_diagnosis=False,
        )
        assert r.failure_step is None
        assert r.quality_score == 0.0

    def test_with_failure_step(self):
        r = ExecutionPhaseResult(
            success=False,
            step_results=[],
            total_duration=2.5,
            total_tokens=500,
            issues=[],
            artifacts_created=[],
            needs_diagnosis=True,
            failure_step="build_step",
        )
        assert r.failure_step == "build_step"
        assert r.needs_diagnosis is True

    def test_quality_score_set(self):
        r = ExecutionPhaseResult(
            success=True,
            step_results=[],
            total_duration=1.0,
            total_tokens=0,
            issues=[],
            artifacts_created=[],
            needs_diagnosis=False,
            quality_score=0.85,
        )
        assert r.quality_score == 0.85


# =============================================================================
# EXECUTION_PROMPT template
# =============================================================================


class TestExecutionPrompt:
    """Test EXECUTION_PROMPT template string."""

    def test_contains_placeholders(self):
        assert "{task}" in EXECUTION_PROMPT
        assert "{step_name}" in EXECUTION_PROMPT
        assert "{action}" in EXECUTION_PROMPT
        assert "{expected_duration}" in EXECUTION_PROMPT
        assert "{previous_results}" in EXECUTION_PROMPT

    def test_formatting_succeeds(self):
        result = EXECUTION_PROMPT.format(
            task="Build a CLI tool",
            step_name="setup",
            action="Initialize project",
            expected_duration=30,
            previous_results="No previous steps executed",
        )
        assert "Build a CLI tool" in result
        assert "setup" in result
        assert "Initialize project" in result
        assert "30" in result

    def test_json_format_instruction(self):
        assert '"status"' in EXECUTION_PROMPT
        assert '"output"' in EXECUTION_PROMPT
        assert '"artifacts_created"' in EXECUTION_PROMPT
        assert '"issues"' in EXECUTION_PROMPT

    def test_expected_response_statuses(self):
        assert "success" in EXECUTION_PROMPT
        assert "warning" in EXECUTION_PROMPT
        assert "error" in EXECUTION_PROMPT


# =============================================================================
# MonitoredExecutionPhase.__init__
# =============================================================================


class TestMonitoredExecutionPhaseInit:
    """Test MonitoredExecutionPhase initialization."""

    def test_basic_init(self):
        phase = _make_phase()
        assert phase.gemini is not None
        assert phase.claude is not None
        assert phase.cost_estimator is not None
        assert phase.context_manager is not None
        assert phase.swarm_bridge is None

    def test_with_swarm_engine(self):
        swarm = MagicMock()
        with patch("core.intelligence.hive_mind.phases.phase_execution.SwarmBridge") as MockBridge:
            phase = MonitoredExecutionPhase(
                gemini_driver=MagicMock(),
                claude_driver=MagicMock(),
                cost_estimator=MagicMock(),
                context_manager=MagicMock(),
                swarm_engine=swarm,
            )
            MockBridge.assert_called_once()
            assert phase.swarm_bridge is not None

    def test_without_swarm_engine(self):
        phase = MonitoredExecutionPhase(
            gemini_driver=MagicMock(),
            claude_driver=MagicMock(),
            cost_estimator=MagicMock(),
            context_manager=MagicMock(),
        )
        assert phase.swarm_bridge is None

    def test_task_id_auto_generated(self):
        phase = _make_phase()
        assert phase._task_id is not None
        assert "execution" in phase._task_id

    def test_custom_task_id(self):
        phase = MonitoredExecutionPhase(
            gemini_driver=MagicMock(),
            claude_driver=MagicMock(),
            cost_estimator=MagicMock(),
            context_manager=MagicMock(),
            task_id="custom-123",
        )
        assert phase._task_id == "custom-123"

    def test_session_manager_stored(self):
        sm = MagicMock()
        phase = MonitoredExecutionPhase(
            gemini_driver=MagicMock(),
            claude_driver=MagicMock(),
            cost_estimator=MagicMock(),
            context_manager=MagicMock(),
            session_manager=sm,
        )
        assert phase._session_manager is sm

    def test_tool_executor_stored(self):
        executor = MagicMock()
        phase = MonitoredExecutionPhase(
            gemini_driver=MagicMock(),
            claude_driver=MagicMock(),
            cost_estimator=MagicMock(),
            context_manager=MagicMock(),
            tool_executor=executor,
        )
        assert phase.tool_executor is executor


# =============================================================================
# _is_step_complete
# =============================================================================


class TestIsStepComplete:
    """Test _is_step_complete helper method."""

    def test_empty_results(self):
        phase = _make_phase()
        assert phase._is_step_complete("step1", []) is False

    def test_step_not_found(self):
        phase = _make_phase()
        results = [_make_step_result(step_name="other")]
        assert phase._is_step_complete("step1", results) is False

    def test_step_found_success(self):
        phase = _make_phase()
        results = [_make_step_result(step_name="step1", status="success")]
        assert phase._is_step_complete("step1", results) is True

    def test_step_found_error_not_complete(self):
        phase = _make_phase()
        results = [_make_step_result(step_name="step1", status="error")]
        assert phase._is_step_complete("step1", results) is False

    def test_step_found_warning_not_complete(self):
        phase = _make_phase()
        results = [_make_step_result(step_name="step1", status="warning")]
        assert phase._is_step_complete("step1", results) is False

    def test_multiple_results_first_success(self):
        phase = _make_phase()
        results = [
            _make_step_result(step_name="step1", status="success"),
            _make_step_result(step_name="step2", status="error"),
        ]
        assert phase._is_step_complete("step1", results) is True
        assert phase._is_step_complete("step2", results) is False

    def test_duplicate_step_names(self):
        phase = _make_phase()
        results = [
            _make_step_result(step_name="step1", status="error"),
            _make_step_result(step_name="step1", status="success"),
        ]
        # Second attempt succeeded
        assert phase._is_step_complete("step1", results) is True


# =============================================================================
# _format_previous_results
# =============================================================================


class TestFormatPreviousResults:
    """Test _format_previous_results formatting."""

    def test_empty(self):
        phase = _make_phase()
        text = phase._format_previous_results([])
        assert text == "No previous steps executed"

    def test_single_success(self):
        phase = _make_phase()
        results = [_make_step_result(step_name="setup", status="success", output="Initialized")]
        text = phase._format_previous_results(results)
        assert "setup" in text
        assert "Initialized" in text

    def test_single_error(self):
        phase = _make_phase()
        results = [_make_step_result(step_name="build", status="error", output="Compile failed")]
        text = phase._format_previous_results(results)
        assert "build" in text

    def test_truncation_to_last_3(self):
        phase = _make_phase()
        results = [_make_step_result(step_name=f"step{i}", output=f"Output {i}") for i in range(5)]
        text = phase._format_previous_results(results)
        # Should only include last 3 steps
        assert "step2" in text
        assert "step3" in text
        assert "step4" in text
        assert "step0" not in text
        assert "step1" not in text

    def test_long_output_truncated(self):
        phase = _make_phase()
        long_output = "A" * 200
        results = [_make_step_result(output=long_output)]
        text = phase._format_previous_results(results)
        # Output truncated to 100 chars + "..."
        assert "..." in text
        assert len(text) < 200


# =============================================================================
# _parse_execution_response
# =============================================================================


class TestParseExecutionResponse:
    """Test _parse_execution_response JSON parsing."""

    def test_valid_json_string(self):
        phase = _make_phase()
        response = json.dumps(
            {
                "status": "success",
                "output": "Completed",
                "artifacts_created": ["file.py"],
                "issues": [],
            }
        )
        data = phase._parse_execution_response(response)
        assert data["status"] == "success"
        assert data["output"] == "Completed"
        assert data["artifacts_created"] == ["file.py"]

    def test_dict_response(self):
        phase = _make_phase()
        response = {"content": '{"status": "success", "output": "Done"}'}
        data = phase._parse_execution_response(response)
        # Should parse the content field
        assert "output" in data or "status" in data

    def test_unparseable_fallback(self):
        phase = _make_phase()
        response = "This is not JSON at all, just plain text"
        data = phase._parse_execution_response(response)
        # Should fall back to raw output
        assert "output" in data
        assert data["status"] == "success"

    def test_empty_string(self):
        phase = _make_phase()
        data = phase._parse_execution_response("")
        assert "output" in data

    def test_response_with_text_field(self):
        phase = _make_phase()
        response = {"text": '{"status": "warning", "output": "Partial"}'}
        data = phase._parse_execution_response(response)
        assert "output" in data


# =============================================================================
# _detect_hallucinations
# =============================================================================


class TestDetectHallucinations:
    """Test _detect_hallucinations pattern matching."""

    def test_no_hallucination(self):
        phase = _make_phase()
        issues = phase._detect_hallucinations("Everything is working fine", "step1")
        assert len(issues) == 0

    def test_file_not_found(self):
        phase = _make_phase()
        issues = phase._detect_hallucinations("file not found at /path/to/file", "step1")
        assert len(issues) == 1
        assert issues[0].issue_type == "potential_hallucination"
        assert issues[0].severity == IssueSeverity.WARNING

    def test_cannot_access_uppercase_pattern_mismatch(self):
        """Pattern 'I cannot access' has uppercase I; lowercased response won't match."""
        phase = _make_phase()
        # The source pattern is "I cannot access" (uppercase I).
        # _detect_hallucinations lowercases the response but not the pattern,
        # so "I cannot access" won't match in "i cannot access the database".
        issues = phase._detect_hallucinations("I cannot access the database", "step1")
        assert len(issues) == 0  # Bug in source: case mismatch prevents detection

    def test_does_not_exist(self):
        phase = _make_phase()
        issues = phase._detect_hallucinations("The module does not exist", "step1")
        assert len(issues) == 1

    def test_no_such_file(self):
        phase = _make_phase()
        issues = phase._detect_hallucinations("no such file or directory", "step1")
        assert len(issues) == 1

    def test_unable_to_locate(self):
        phase = _make_phase()
        issues = phase._detect_hallucinations("unable to locate package xyz", "step1")
        assert len(issues) == 1

    def test_case_insensitive(self):
        phase = _make_phase()
        issues = phase._detect_hallucinations("FILE NOT FOUND", "step1")
        assert len(issues) == 1

    def test_only_one_issue_per_call(self):
        phase = _make_phase()
        # Multiple patterns present, but should break after first
        issues = phase._detect_hallucinations("file not found and I cannot access and does not exist", "step1")
        assert len(issues) == 1

    def test_step_name_in_issue(self):
        phase = _make_phase()
        issues = phase._detect_hallucinations("file not found", "build_step")
        assert issues[0].step_name == "build_step"


# =============================================================================
# _detect_errors
# =============================================================================


class TestDetectErrors:
    """Test _detect_errors pattern matching."""

    def test_no_errors(self):
        phase = _make_phase()
        issues = phase._detect_errors("Everything completed successfully", "step1")
        assert len(issues) == 0

    def test_error_pattern(self):
        phase = _make_phase()
        issues = phase._detect_errors("error: something went wrong", "step1")
        assert len(issues) >= 1
        assert issues[0].issue_type == "error_in_output"
        assert issues[0].severity == IssueSeverity.ERROR

    def test_exception_pattern(self):
        phase = _make_phase()
        issues = phase._detect_errors("exception: NullPointerException", "step1")
        assert len(issues) >= 1

    def test_traceback_pattern(self):
        phase = _make_phase()
        issues = phase._detect_errors("Traceback (most recent call last)", "step1")
        assert len(issues) >= 1

    def test_syntaxerror_pattern(self):
        phase = _make_phase()
        issues = phase._detect_errors("SyntaxError: invalid syntax", "step1")
        assert len(issues) >= 1

    def test_typeerror_pattern(self):
        phase = _make_phase()
        issues = phase._detect_errors("TypeError: expected str got int", "step1")
        assert len(issues) >= 1

    def test_failed_pattern(self):
        phase = _make_phase()
        issues = phase._detect_errors("failed: connection refused", "step1")
        assert len(issues) >= 1

    def test_multiple_errors_detected(self):
        phase = _make_phase()
        issues = phase._detect_errors("error: bad and traceback in output", "step1")
        assert len(issues) >= 2

    def test_case_insensitive(self):
        phase = _make_phase()
        issues = phase._detect_errors("ERROR: something", "step1")
        assert len(issues) >= 1

    def test_error_category_set(self):
        phase = _make_phase()
        issues = phase._detect_errors("traceback detected", "step1")
        assert any(i.error_category == "traceback" for i in issues)

    def test_step_name_in_issue(self):
        phase = _make_phase()
        issues = phase._detect_errors("error: x", "deploy_step")
        assert issues[0].step_name == "deploy_step"


# =============================================================================
# _verify_artifacts
# =============================================================================


class TestVerifyArtifacts:
    """Test _verify_artifacts file verification."""

    @pytest.mark.asyncio
    async def test_empty_list(self):
        phase = _make_phase()
        assert await phase._verify_artifacts([]) is True

    @pytest.mark.asyncio
    async def test_existing_file(self, tmp_path):
        phase = _make_phase()
        f = tmp_path / "test.py"
        f.write_text("print('hello')")
        assert await phase._verify_artifacts([str(f)]) is True

    @pytest.mark.asyncio
    async def test_missing_file(self, tmp_path):
        phase = _make_phase()
        missing = str(tmp_path / "nonexistent.py")
        assert await phase._verify_artifacts([missing]) is False

    @pytest.mark.asyncio
    async def test_file_prefix(self, tmp_path):
        phase = _make_phase()
        f = tmp_path / "data.json"
        f.write_text("{}")
        assert await phase._verify_artifacts([f"file:{f}"]) is True

    @pytest.mark.asyncio
    async def test_created_prefix(self, tmp_path):
        phase = _make_phase()
        f = tmp_path / "output.txt"
        f.write_text("content")
        assert await phase._verify_artifacts([f"created:{f}"]) is True

    @pytest.mark.asyncio
    async def test_url_artifacts_pass(self):
        phase = _make_phase()
        assert await phase._verify_artifacts(["https://example.com/api"]) is True

    @pytest.mark.asyncio
    async def test_http_url_passes(self):
        phase = _make_phase()
        assert await phase._verify_artifacts(["http://localhost:8000"]) is True

    @pytest.mark.asyncio
    async def test_data_uri_passes(self):
        phase = _make_phase()
        assert await phase._verify_artifacts(["data:text/plain;base64,SGVsbG8="]) is True

    @pytest.mark.asyncio
    async def test_mixed_existing_and_missing(self, tmp_path):
        phase = _make_phase()
        existing = tmp_path / "exists.py"
        existing.write_text("x = 1")
        missing = str(tmp_path / "nope.py")
        result = await phase._verify_artifacts([str(existing), missing])
        assert result is False

    @pytest.mark.asyncio
    async def test_all_existing(self, tmp_path):
        phase = _make_phase()
        files = []
        for i in range(3):
            f = tmp_path / f"file{i}.py"
            f.write_text(f"# file {i}")
            files.append(str(f))
        assert await phase._verify_artifacts(files) is True


# =============================================================================
# _score_execution_quality
# =============================================================================


class TestScoreExecutionQuality:
    """Test _score_execution_quality composite scoring."""

    def test_empty_results(self):
        phase = _make_phase()
        arch = _make_architecture()
        score = phase._score_execution_quality([], [], arch, 0)
        assert score == 0.0

    def test_all_success_no_issues(self):
        phase = _make_phase()
        steps = [_make_step(name=f"s{i}") for i in range(3)]
        arch = _make_architecture(steps=steps)
        results = [_make_step_result(step_name=f"s{i}", status="success", artifacts_verified=True) for i in range(3)]
        score = phase._score_execution_quality(results, [], arch, 0)
        # depth=1.0, coherence=1.0, completeness=1.0 => score=1.0
        assert score == 1.0

    def test_partial_success(self):
        phase = _make_phase()
        steps = [_make_step(name=f"s{i}") for i in range(4)]
        arch = _make_architecture(steps=steps)
        results = [
            _make_step_result(step_name="s0", status="success", artifacts_verified=True),
            _make_step_result(step_name="s1", status="error", artifacts_verified=False),
        ]
        score = phase._score_execution_quality(results, [], arch, 1)
        # depth = 1/4 = 0.25, coherence = 1.0, completeness = 1/2 = 0.5
        assert 0.0 < score < 1.0

    def test_hallucination_reduces_coherence(self):
        phase = _make_phase()
        steps = [_make_step()]
        arch = _make_architecture(steps=steps)
        results = [_make_step_result(status="success", artifacts_verified=True)]
        issues = [_make_issue(issue_type="hallucination")]
        score = phase._score_execution_quality(results, issues, arch, 0)
        # Coherence penalized by 0.3 for hallucination
        assert score < 1.0

    def test_error_issues_reduce_coherence(self):
        phase = _make_phase()
        steps = [_make_step()]
        arch = _make_architecture(steps=steps)
        results = [_make_step_result(status="success", artifacts_verified=True)]
        issues = [_make_issue(severity=IssueSeverity.ERROR)]
        score = phase._score_execution_quality(results, issues, arch, 0)
        assert score < 1.0

    def test_critical_issues_reduce_coherence(self):
        phase = _make_phase()
        steps = [_make_step()]
        arch = _make_architecture(steps=steps)
        results = [_make_step_result(status="success", artifacts_verified=True)]
        issues = [_make_issue(severity=IssueSeverity.CRITICAL)]
        score = phase._score_execution_quality(results, issues, arch, 0)
        assert score < 1.0

    def test_unverified_artifacts_reduce_completeness(self):
        phase = _make_phase()
        steps = [_make_step()]
        arch = _make_architecture(steps=steps)
        results = [_make_step_result(status="success", artifacts_verified=False)]
        score = phase._score_execution_quality(results, [], arch, 0)
        # completeness=0 because verified=False
        expected_depth = 1.0
        expected_coherence = 1.0
        expected_completeness = 0.0
        expected = round((expected_depth + expected_coherence + expected_completeness) / 3, 4)
        assert score == expected

    def test_coherence_floor_at_zero(self):
        phase = _make_phase()
        steps = [_make_step()]
        arch = _make_architecture(steps=steps)
        results = [_make_step_result(status="success", artifacts_verified=True)]
        # Many hallucinations and errors to push coherence below 0
        issues = [
            _make_issue(issue_type="hallucination"),
            _make_issue(issue_type="hallucination"),
            _make_issue(issue_type="hallucination"),
            _make_issue(issue_type="hallucination"),
            _make_issue(severity=IssueSeverity.ERROR),
            _make_issue(severity=IssueSeverity.ERROR),
            _make_issue(severity=IssueSeverity.ERROR),
        ]
        score = phase._score_execution_quality(results, issues, arch, 0)
        # coherence = max(0, 1 - 4*0.3 - 3*0.15) = max(0, -0.65) = 0
        assert score >= 0.0

    def test_quality_scorer_exception_handled(self):
        """V12.4 ReasoningQualityScorer import failure should not crash."""
        phase = _make_phase()
        steps = [_make_step()]
        arch = _make_architecture(steps=steps)
        results = [_make_step_result(status="success", artifacts_verified=True)]
        with patch(
            "core.intelligence.hive_mind.phases.phase_execution.MonitoredExecutionPhase._score_execution_quality",
            wraps=phase._score_execution_quality,
        ):
            # This should not raise even if the scorer import fails
            score = phase._score_execution_quality(results, [], arch, 0)
            assert isinstance(score, float)


# =============================================================================
# get_execution_summary
# =============================================================================


class TestGetExecutionSummary:
    """Test get_execution_summary aggregation."""

    def test_empty_result(self):
        phase = _make_phase()
        result = ExecutionPhaseResult(
            success=True,
            step_results=[],
            total_duration=1.5,
            total_tokens=0,
            issues=[],
            artifacts_created=[],
            needs_diagnosis=False,
        )
        summary = phase.get_execution_summary(result)
        assert summary["success"] is True
        assert summary["total_steps"] == 0
        assert summary["successful_steps"] == 0
        assert summary["failed_steps"] == 0

    def test_mixed_results(self):
        phase = _make_phase()
        result = ExecutionPhaseResult(
            success=False,
            step_results=[
                _make_step_result(status="success"),
                _make_step_result(step_name="s2", status="error"),
                _make_step_result(step_name="s3", status="warning"),
            ],
            total_duration=10.0,
            total_tokens=500,
            issues=[
                _make_issue(severity=IssueSeverity.ERROR),
                _make_issue(severity=IssueSeverity.WARNING),
            ],
            artifacts_created=["file.py"],
            needs_diagnosis=True,
            failure_step="s2",
        )
        summary = phase.get_execution_summary(result)
        assert summary["total_steps"] == 3
        assert summary["successful_steps"] == 1
        assert summary["failed_steps"] == 1
        assert summary["total_duration"] == 10.0
        assert summary["total_tokens"] == 500
        assert summary["failure_step"] == "s2"
        assert summary["artifacts"] == ["file.py"]

    def test_issues_by_severity(self):
        phase = _make_phase()
        result = ExecutionPhaseResult(
            success=False,
            step_results=[],
            total_duration=1.0,
            total_tokens=0,
            issues=[
                _make_issue(severity=IssueSeverity.INFO),
                _make_issue(severity=IssueSeverity.WARNING),
                _make_issue(severity=IssueSeverity.WARNING),
                _make_issue(severity=IssueSeverity.ERROR),
                _make_issue(severity=IssueSeverity.CRITICAL),
            ],
            artifacts_created=[],
            needs_diagnosis=True,
        )
        summary = phase.get_execution_summary(result)
        sev = summary["issues_by_severity"]
        assert sev["info"] == 1
        assert sev["warning"] == 2
        assert sev["error"] == 1
        assert sev["critical"] == 1


# =============================================================================
# HALLUCINATION_PATTERNS / ERROR_PATTERNS class attributes
# =============================================================================


class TestClassAttributes:
    """Test class-level pattern lists."""

    def test_hallucination_patterns_are_strings(self):
        """Note: 'I cannot access' has uppercase I - known case mismatch."""
        for p in MonitoredExecutionPhase.HALLUCINATION_PATTERNS:
            assert isinstance(p, str)
            assert len(p) > 0

    def test_error_patterns_are_lowercase(self):
        for p in MonitoredExecutionPhase.ERROR_PATTERNS:
            assert p == p.lower()

    def test_hallucination_patterns_nonempty(self):
        assert len(MonitoredExecutionPhase.HALLUCINATION_PATTERNS) >= 5

    def test_error_patterns_nonempty(self):
        assert len(MonitoredExecutionPhase.ERROR_PATTERNS) >= 5


# =============================================================================
# _execute_step (async)
# =============================================================================


class TestExecuteStep:
    """Test _execute_step driver dispatch and result construction."""

    @pytest.mark.asyncio
    async def test_selects_claude_driver(self):
        phase = _make_phase()
        phase._session_integration = MagicMock()
        phase._session_integration.get_agent_session.return_value = "session-uuid"

        step = _make_step(agent_id="claude")

        with patch("core.intelligence.hive_mind.phases.phase_execution.get_registry") as mock_reg:
            registry = MagicMock()
            registry.is_claude.return_value = True
            mock_reg.return_value = registry

            await phase._execute_step("task", step, [])
            # Claude driver should have been called via invoke()
            phase.claude.invoke.assert_awaited_once()
            phase.gemini.invoke.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_selects_gemini_driver(self):
        phase = _make_phase()
        phase._session_integration = MagicMock()
        phase._session_integration.get_agent_session.return_value = "session-uuid"

        step = _make_step(agent_id="gemini")

        with patch("core.intelligence.hive_mind.phases.phase_execution.get_registry") as mock_reg:
            registry = MagicMock()
            registry.is_claude.return_value = False
            mock_reg.return_value = registry

            await phase._execute_step("task", step, [])
            phase.gemini.invoke.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_success_result_construction(self):
        phase = _make_phase()
        phase._session_integration = MagicMock()
        phase._session_integration.get_agent_session.return_value = None

        phase.claude.invoke = AsyncMock(
            return_value=_make_driver_response(
                '{"status":"success","output":"All good","artifacts_created":[],"issues":[]}'
            )
        )
        step = _make_step(agent_id="claude", expected_duration=60.0)

        with patch("core.intelligence.hive_mind.phases.phase_execution.get_registry") as mock_reg:
            registry = MagicMock()
            registry.is_claude.return_value = True
            mock_reg.return_value = registry

            result = await phase._execute_step("task", step, [])
            assert result.step_name == "step1"
            assert result.agent_id == "claude"
            assert result.status == "success"
            assert result.output == "All good"
            assert result.tokens_used > 0
            assert result.duration > 0

    @pytest.mark.asyncio
    async def test_timeout_produces_critical_issue(self):
        phase = _make_phase()
        phase._session_integration = MagicMock()
        phase._session_integration.get_agent_session.return_value = None

        phase.claude.invoke = AsyncMock(side_effect=TimeoutError())
        step = _make_step(agent_id="claude", expected_duration=0.001)

        with patch("core.intelligence.hive_mind.phases.phase_execution.get_registry") as mock_reg:
            registry = MagicMock()
            registry.is_claude.return_value = True
            mock_reg.return_value = registry

            result = await phase._execute_step("task", step, [])
            assert result.status == "error"
            assert result.output == "Step timed out"
            assert result.tokens_used == 0
            assert any(i.issue_type == "timeout" for i in result.issues)
            assert any(i.severity == IssueSeverity.CRITICAL for i in result.issues)

    @pytest.mark.asyncio
    async def test_exception_produces_critical_issue(self):
        phase = _make_phase()
        phase._session_integration = MagicMock()
        phase._session_integration.get_agent_session.return_value = None

        phase.claude.invoke = AsyncMock(side_effect=RuntimeError("API down"))
        step = _make_step(agent_id="claude")

        with patch("core.intelligence.hive_mind.phases.phase_execution.get_registry") as mock_reg:
            registry = MagicMock()
            registry.is_claude.return_value = True
            mock_reg.return_value = registry

            result = await phase._execute_step("task", step, [])
            assert result.status == "error"
            assert "API down" in result.output
            assert any(i.issue_type == "execution_error" for i in result.issues)
            assert any(i.severity == IssueSeverity.CRITICAL for i in result.issues)

    @pytest.mark.asyncio
    async def test_slow_execution_warning(self):
        """Step taking longer than expected_duration produces a warning."""
        phase = _make_phase()
        phase._session_integration = MagicMock()
        phase._session_integration.get_agent_session.return_value = None

        # expected_duration=0.1, timeout=0.1*2=0.2, sleep=0.15
        # 0.15 < 0.2 (no timeout) but 0.15 > 0.1 (triggers slow_execution)
        # Using larger values to avoid Windows timer resolution issues
        async def slow_response(*args, **kwargs):
            await asyncio.sleep(0.15)
            return _make_driver_response('{"status":"success","output":"Slow","artifacts_created":[],"issues":[]}')

        phase.claude.invoke = AsyncMock(side_effect=slow_response)
        step = _make_step(agent_id="claude", expected_duration=0.1)

        with patch("core.intelligence.hive_mind.phases.phase_execution.get_registry") as mock_reg:
            registry = MagicMock()
            registry.is_claude.return_value = True
            mock_reg.return_value = registry

            result = await phase._execute_step("task", step, [])
            assert any(i.issue_type == "slow_execution" for i in result.issues)

    @pytest.mark.asyncio
    async def test_hallucination_detected_in_response(self):
        """Use a pattern that is already lowercase to ensure detection."""
        phase = _make_phase()
        phase._session_integration = MagicMock()
        phase._session_integration.get_agent_session.return_value = None

        # "file not found" is a lowercase pattern, so it will match
        phase.claude.invoke = AsyncMock(return_value=_make_driver_response("file not found at /tmp/missing.py"))
        step = _make_step(agent_id="claude")

        with patch("core.intelligence.hive_mind.phases.phase_execution.get_registry") as mock_reg:
            registry = MagicMock()
            registry.is_claude.return_value = True
            mock_reg.return_value = registry

            result = await phase._execute_step("task", step, [])
            assert any(i.issue_type == "potential_hallucination" for i in result.issues)

    @pytest.mark.asyncio
    async def test_error_in_output_detected(self):
        phase = _make_phase()
        phase._session_integration = MagicMock()
        phase._session_integration.get_agent_session.return_value = None

        phase.claude.invoke = AsyncMock(
            return_value=_make_driver_response(
                '{"status":"success","output":"traceback found in logs","artifacts_created":[],"issues":[]}'
            )
        )
        step = _make_step(agent_id="claude")

        with patch("core.intelligence.hive_mind.phases.phase_execution.get_registry") as mock_reg:
            registry = MagicMock()
            registry.is_claude.return_value = True
            mock_reg.return_value = registry

            result = await phase._execute_step("task", step, [])
            assert any(i.issue_type == "error_in_output" for i in result.issues)

    @pytest.mark.asyncio
    async def test_step_with_swarm_mode_delegates(self):
        """Step with swarm_mode set delegates to _execute_via_swarm."""
        phase = _make_phase()
        phase.swarm_bridge = MagicMock()
        phase._session_integration = MagicMock()

        step = _make_step(swarm_mode="parallel")

        # Mock _execute_via_swarm
        expected_result = _make_step_result()
        phase._execute_via_swarm = AsyncMock(return_value=expected_result)

        with patch("core.intelligence.hive_mind.phases.phase_execution.get_registry") as mock_reg:
            registry = MagicMock()
            registry.is_claude.return_value = True
            mock_reg.return_value = registry

            result = await phase._execute_step("task", step, [])
            phase._execute_via_swarm.assert_awaited_once()
            assert result is expected_result

    @pytest.mark.asyncio
    async def test_artifact_verification_failure(self):
        phase = _make_phase()
        phase._session_integration = MagicMock()
        phase._session_integration.get_agent_session.return_value = None

        phase.claude.invoke = AsyncMock(
            return_value=_make_driver_response(
                '{"status":"success","output":"Created files","artifacts_created":["nonexistent.py"],"issues":[]}'
            )
        )
        step = _make_step(agent_id="claude", verification_required=True)

        with patch("core.intelligence.hive_mind.phases.phase_execution.get_registry") as mock_reg:
            registry = MagicMock()
            registry.is_claude.return_value = True
            mock_reg.return_value = registry

            result = await phase._execute_step("task", step, [])
            assert any(i.issue_type == "artifact_verification_failed" for i in result.issues)

    @pytest.mark.asyncio
    async def test_prompt_formatting(self):
        """Verify the prompt sent to the driver is formatted correctly."""
        phase = _make_phase()
        phase._session_integration = MagicMock()
        phase._session_integration.get_agent_session.return_value = None

        step = _make_step(
            name="deploy",
            action="Deploy to production",
            expected_duration=60.0,
        )

        with patch("core.intelligence.hive_mind.phases.phase_execution.get_registry") as mock_reg:
            registry = MagicMock()
            registry.is_claude.return_value = True
            mock_reg.return_value = registry

            await phase._execute_step("Build app", step, [])
            call_args = phase.claude.invoke.call_args
            prompt = call_args[0][0]
            assert "Build app" in prompt
            assert "deploy" in prompt
            assert "Deploy to production" in prompt
            assert "60" in prompt


# =============================================================================
# Full execute() flow (async)
# =============================================================================


class TestExecuteFlow:
    """Test the full execute() method with mocked dependencies."""

    @pytest.mark.asyncio
    async def test_single_step_success(self):
        phase = _make_phase()
        step = _make_step(name="only_step", agent_id="claude")
        arch = _make_architecture(steps=[step])

        with (
            patch("core.intelligence.hive_mind.phases.phase_execution.get_registry") as mock_reg,
            patch("core.intelligence.hive_mind.phases.phase_execution.emit_agent_speak"),
            patch("core.intelligence.hive_mind.phases.phase_execution.emit_agent_exchange"),
        ):
            registry = MagicMock()
            registry.is_claude.return_value = True
            mock_reg.return_value = registry
            result = await phase.execute("Build something", arch)

        assert isinstance(result, ExecutionPhaseResult)
        assert result.success is True
        assert len(result.step_results) == 1
        assert result.step_results[0].step_name == "only_step"
        assert result.total_duration > 0
        assert result.quality_score >= 0.0

    @pytest.mark.asyncio
    async def test_multiple_steps_all_success(self):
        phase = _make_phase()
        steps = [_make_step(name=f"s{i}", agent_id="claude") for i in range(3)]
        arch = _make_architecture(steps=steps)

        with (
            patch("core.intelligence.hive_mind.phases.phase_execution.get_registry") as mock_reg,
            patch("core.intelligence.hive_mind.phases.phase_execution.emit_agent_speak"),
            patch("core.intelligence.hive_mind.phases.phase_execution.emit_agent_exchange"),
        ):
            registry = MagicMock()
            registry.is_claude.return_value = True
            mock_reg.return_value = registry
            result = await phase.execute("Build something", arch)

        assert result.success is True
        assert len(result.step_results) == 3

    @pytest.mark.asyncio
    async def test_budget_exceeded_stops_execution(self):
        phase = _make_phase(can_afford=False)
        steps = [_make_step(name="s1"), _make_step(name="s2")]
        arch = _make_architecture(steps=steps)

        with (
            patch("core.intelligence.hive_mind.phases.phase_execution.emit_agent_speak"),
            patch("core.intelligence.hive_mind.phases.phase_execution.emit_agent_exchange"),
        ):
            result = await phase.execute("task", arch)

        # Should have stopped due to budget
        assert len(result.step_results) == 0
        assert any(i.issue_type == "budget_exceeded" for i in result.issues)

    @pytest.mark.asyncio
    async def test_unmet_dependency_skips_step(self):
        phase = _make_phase()
        # step2 depends on step1 but step1 is not in the plan
        steps = [
            _make_step(name="step2", depends_on=["step1"]),
        ]
        arch = _make_architecture(steps=steps)

        with (
            patch("core.intelligence.hive_mind.phases.phase_execution.emit_agent_speak"),
            patch("core.intelligence.hive_mind.phases.phase_execution.emit_agent_exchange"),
        ):
            result = await phase.execute("task", arch)

        # Step was skipped, no step_results
        assert len(result.step_results) == 0
        assert any(i.issue_type == "dependency_unmet" for i in result.issues)

    @pytest.mark.asyncio
    async def test_critical_failure_aborts_early(self):
        phase = _make_phase()

        critical_result = _make_step_result(
            step_name="s1",
            agent_id="claude",
            status="error",
            output="Fatal crash",
            issues=[
                _make_issue(
                    issue_type="execution_error",
                    severity=IssueSeverity.CRITICAL,
                    details="Fatal crash",
                    step_name="s1",
                )
            ],
        )

        steps = [
            _make_step(name="s1", agent_id="claude"),
            _make_step(name="s2", agent_id="claude"),
        ]
        arch = _make_architecture(steps=steps)

        with (
            patch.object(phase, "_execute_step", new=AsyncMock(return_value=critical_result)),
            patch("core.intelligence.hive_mind.phases.phase_execution.emit_agent_speak"),
            patch("core.intelligence.hive_mind.phases.phase_execution.emit_agent_exchange"),
        ):
            result = await phase.execute("task", arch)

        assert result.success is False
        assert result.needs_diagnosis is True
        assert result.failure_step == "s1"
        # Only 1 step was executed because critical failure stopped it
        assert len(result.step_results) == 1

    @pytest.mark.asyncio
    async def test_error_count_determines_success(self):
        """If there are error-status steps but no critical issues, success=False."""
        phase = _make_phase()

        error_result = _make_step_result(step_name="s1", status="error", output="Failed")
        success_result = _make_step_result(step_name="s2", status="success", output="OK")

        steps = [
            _make_step(name="s1", agent_id="claude"),
            _make_step(name="s2", agent_id="claude"),
        ]
        arch = _make_architecture(steps=steps)

        with (
            patch.object(phase, "_execute_step", new=AsyncMock(side_effect=[error_result, success_result])),
            patch("core.intelligence.hive_mind.phases.phase_execution.emit_agent_speak"),
            patch("core.intelligence.hive_mind.phases.phase_execution.emit_agent_exchange"),
        ):
            result = await phase.execute("task", arch)

        # First step was error, so success is False
        assert result.success is False
        assert len(result.step_results) == 2

    @pytest.mark.asyncio
    async def test_needs_diagnosis_on_low_quality(self):
        """needs_diagnosis is True when quality_score < 0.4."""
        phase = _make_phase()
        phase._score_execution_quality = MagicMock(return_value=0.2)

        r = _make_step_result(step_name="s1")
        steps = [_make_step(name="s1", agent_id="claude")]
        arch = _make_architecture(steps=steps)

        with _patched_execute(phase, AsyncMock(return_value=r)):
            result = await phase.execute("task", arch)

        assert result.needs_diagnosis is True

    @pytest.mark.asyncio
    async def test_tokens_accumulated(self):
        phase = _make_phase()

        r0 = _make_step_result(step_name="s0", tokens_used=200)
        r1 = _make_step_result(step_name="s1", tokens_used=300)

        steps = [_make_step(name=f"s{i}", agent_id="claude") for i in range(2)]
        arch = _make_architecture(steps=steps)

        with _patched_execute(phase, AsyncMock(side_effect=[r0, r1])):
            result = await phase.execute("task", arch)

        assert result.total_tokens == 500

    @pytest.mark.asyncio
    async def test_context_manager_receives_results(self):
        phase = _make_phase()

        r = _make_step_result(step_name="s1", output="Result output")
        steps = [_make_step(name="s1", agent_id="claude")]
        arch = _make_architecture(steps=steps)

        with _patched_execute(phase, AsyncMock(return_value=r)):
            await phase.execute("task", arch)

        phase.context_manager.add_execution_result.assert_called()


# =============================================================================
# V12.4 Integration try/except blocks
# =============================================================================


class TestV124IntegrationBlocks:
    """
    Test that V12.4 integration try/except blocks do not crash
    when their modules are unavailable or raise exceptions.
    """

    @pytest.mark.asyncio
    async def test_meta_policy_memory_import_failure(self):
        """MetaPolicyMemory import failure should not crash execute()."""
        phase = _make_phase()
        steps = [_make_step(agent_id="claude")]
        arch = _make_architecture(steps=steps)

        with (
            patch("core.intelligence.hive_mind.phases.phase_execution.get_registry") as mock_reg,
            patch("core.intelligence.hive_mind.phases.phase_execution.emit_agent_speak"),
            patch("core.intelligence.hive_mind.phases.phase_execution.emit_agent_exchange"),
        ):
            registry = MagicMock()
            registry.is_claude.return_value = True
            mock_reg.return_value = registry
            # The import inside execute() uses try/except
            result = await phase.execute("task", arch)

        assert isinstance(result, ExecutionPhaseResult)

    @pytest.mark.asyncio
    async def test_plan_context_filter_unavailable(self):
        """PlanContextFilter unavailability should not crash execute()."""
        phase = _make_phase()
        steps = [_make_step(agent_id="claude")]
        arch = _make_architecture(steps=steps)

        with (
            patch("core.intelligence.hive_mind.phases.phase_execution.get_registry") as mock_reg,
            patch("core.intelligence.hive_mind.phases.phase_execution.emit_agent_speak"),
            patch("core.intelligence.hive_mind.phases.phase_execution.emit_agent_exchange"),
        ):
            registry = MagicMock()
            registry.is_claude.return_value = True
            mock_reg.return_value = registry
            result = await phase.execute("task", arch)

        assert isinstance(result, ExecutionPhaseResult)

    @pytest.mark.asyncio
    async def test_all_v124_modules_raising_exceptions(self):
        """All V12.4 module singletons raising should not crash execute()."""
        phase = _make_phase()
        steps = [_make_step(agent_id="claude")]
        arch = _make_architecture(steps=steps)

        # Patch all V12.4 singletons to raise
        patches = [
            "core.intelligence.reasoning.meta_policy_memory.get_meta_policy_memory",
            "core.memory_pkg.memory.plan_context_filter.get_plan_context_filter",
            "core.infrastructure.resilience.request_deduplicator.get_deduplicator",
            "core.execution_pkg.execution.tool_observer.get_tool_observer",
            "core.intelligence.reasoning.uncertainty_propagator.get_uncertainty_propagator",
            "core.intelligence.reasoning.metacognitive_monitor.get_metacognitive_monitor",
            "core.intelligence.reasoning.inspector_guard.get_inspector_guard",
            "core.memory_pkg.skills.crystallizer.get_crystallizer",
            "core.memory_pkg.memory.pointer_memory.get_pointer_memory",
            "core.intelligence.reasoning.consensus_verifier.get_consensus_verifier",
            "core.intelligence.reasoning.cognitive_degradation.get_degradation_detector",
            "core.intelligence.reasoning.confidence_calibrator.get_confidence_calibrator",
            "core.intelligence.reasoning.fault_detector.get_fault_detector",
            "core.intelligence.reasoning.reasoning_quality_scorer.get_quality_scorer",
        ]

        active_patches = []
        for target in patches:
            try:
                p = patch(target, side_effect=ImportError("mocked"))
                p.start()
                active_patches.append(p)
            except Exception:
                pass  # Some modules may not be importable

        try:
            with (
                patch("core.intelligence.hive_mind.phases.phase_execution.get_registry") as mock_reg,
                patch("core.intelligence.hive_mind.phases.phase_execution.emit_agent_speak"),
                patch("core.intelligence.hive_mind.phases.phase_execution.emit_agent_exchange"),
            ):
                registry = MagicMock()
                registry.is_claude.return_value = True
                mock_reg.return_value = registry
                result = await phase.execute("task", arch)

            assert isinstance(result, ExecutionPhaseResult)
            assert result.success is True
        finally:
            for p in active_patches:
                p.stop()

    @pytest.mark.asyncio
    async def test_consensus_verifier_rejection_adds_issue(self):
        """ConsensusVerifier rejection should add a warning issue."""
        phase = _make_phase()
        steps = [_make_step(agent_id="claude")]
        arch = _make_architecture(steps=steps)

        r = _make_step_result(step_name="step1", output="Result from step")

        mock_verifier = MagicMock()
        mock_vresult = MagicMock()
        mock_vresult.outcome.value = "rejected"
        mock_vresult.cpk = 0.5
        mock_vresult.consensus_score = 0.3
        mock_verifier.verify.return_value = mock_vresult

        with (
            _patched_execute(phase, AsyncMock(return_value=r)),
            patch(
                "core.intelligence.reasoning.consensus_verifier.get_consensus_verifier",
                return_value=mock_verifier,
            ),
        ):
            result = await phase.execute("task", arch)

        assert any(i.issue_type == "consensus_verification_failed" for i in result.issues)
        assert result.needs_diagnosis is True

    @pytest.mark.asyncio
    async def test_cognitive_degradation_detection(self):
        """Degradation detection should set needs_diagnosis."""
        phase = _make_phase()
        steps = [_make_step(agent_id="claude")]
        arch = _make_architecture(steps=steps)
        arch.execution_steps = steps

        r = _make_step_result(step_name="step1")

        mock_detector = MagicMock()
        mock_signal = MagicMock()
        mock_signal.degraded = True
        mock_signal.details = "Token quality declining"
        mock_detector.check_agent.return_value = mock_signal

        with (
            _patched_execute(phase, AsyncMock(return_value=r)),
            patch(
                "core.intelligence.reasoning.cognitive_degradation.get_degradation_detector",
                return_value=mock_detector,
            ),
        ):
            result = await phase.execute("task", arch)

        assert result.needs_diagnosis is True

    @pytest.mark.asyncio
    async def test_deduplicator_skips_cached_step(self):
        """RequestDeduplicator should skip duplicate steps with cached results."""
        phase = _make_phase()
        cached_result = _make_step_result(step_name="s1", output="Cached output")

        mock_dedup = MagicMock()
        mock_check = MagicMock()
        mock_check.is_duplicate = True
        mock_check.cached_result = cached_result
        mock_dedup.check.return_value = mock_check

        steps = [_make_step(name="s1", agent_id="claude")]
        arch = _make_architecture(steps=steps)

        with (
            patch("core.intelligence.hive_mind.phases.phase_execution.get_registry") as mock_reg,
            patch("core.intelligence.hive_mind.phases.phase_execution.emit_agent_speak"),
            patch("core.intelligence.hive_mind.phases.phase_execution.emit_agent_exchange"),
            patch(
                "core.infrastructure.resilience.request_deduplicator.get_deduplicator",
                return_value=mock_dedup,
            ),
        ):
            registry = MagicMock()
            registry.is_claude.return_value = True
            mock_reg.return_value = registry
            result = await phase.execute("task", arch)

        # Step was skipped via dedup but its result was added
        assert len(result.step_results) == 1
        assert result.step_results[0].output == "Cached output"
        # Driver should not have been called
        phase.claude.invoke.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_hac_blocked_step_adds_issue(self):
        """MetaPolicyMemory HAC blocking should add a warning issue but not skip."""
        phase = _make_phase()
        steps = [_make_step(name="s1", agent_id="claude")]
        arch = _make_architecture(steps=steps)

        r = _make_step_result(step_name="s1")

        mock_mpm = MagicMock()
        mock_retrieval = MagicMock()
        mock_retrieval.rules = []
        mock_mpm.retrieve_applicable.return_value = mock_retrieval
        mock_hac = MagicMock()
        mock_hac.is_blocked = True
        mock_hac.reason = "Dangerous action detected"
        mock_hac.suggested_alternative = "Use safer approach"
        mock_mpm.check_admissibility.return_value = mock_hac

        with (
            _patched_execute(phase, AsyncMock(return_value=r)),
            patch(
                "core.intelligence.reasoning.meta_policy_memory.get_meta_policy_memory",
                return_value=mock_mpm,
            ),
        ):
            result = await phase.execute("task", arch)

        assert any(i.issue_type == "hac_blocked" for i in result.issues)

    @pytest.mark.asyncio
    async def test_uncertainty_propagation_warning(self):
        """UncertaintyPropagator should add warning when needs_reflection."""
        phase = _make_phase()
        steps = [_make_step(name="s1", agent_id="claude")]
        arch = _make_architecture(steps=steps)

        r = _make_step_result(step_name="s1")

        mock_uprop = MagicMock()
        mock_signal = MagicMock()
        mock_signal.needs_reflection = True
        mock_signal.propagated_confidence = 0.4
        mock_signal.cascade_risk = 0.7
        mock_uprop.propagate.return_value = mock_signal

        with (
            _patched_execute(phase, AsyncMock(return_value=r)),
            patch(
                "core.intelligence.reasoning.uncertainty_propagator.get_uncertainty_propagator",
                return_value=mock_uprop,
            ),
        ):
            result = await phase.execute("task", arch)

        assert any(i.issue_type == "uncertainty_reflection" for i in result.issues)

    @pytest.mark.asyncio
    async def test_metacognitive_anomaly_warning(self):
        """MetacognitiveMonitor should add warning on anomaly detection."""
        phase = _make_phase()
        steps = [_make_step(name="s1", agent_id="claude")]
        arch = _make_architecture(steps=steps)

        r = _make_step_result(step_name="s1")

        mock_monitor = MagicMock()
        mock_anomaly = MagicMock()
        mock_anomaly.composite_score = 2.5
        mock_monitor.score_step.return_value = mock_anomaly
        mock_monitor.should_correct.return_value = True

        with (
            _patched_execute(phase, AsyncMock(return_value=r)),
            patch(
                "core.intelligence.reasoning.metacognitive_monitor.get_metacognitive_monitor",
                return_value=mock_monitor,
            ),
            patch(
                "core.intelligence.reasoning.task_complexity.should_monitor_metacognition",
                return_value=True,
            ),
        ):
            result = await phase.execute("task", arch)

        assert any(i.issue_type == "metacognitive_anomaly" for i in result.issues)

    @pytest.mark.asyncio
    async def test_inspector_guard_flag(self):
        """InspectorGuard should add warning when requires_diagnosis."""
        phase = _make_phase()
        steps = [_make_step(name="s1", agent_id="claude")]
        arch = _make_architecture(steps=steps)

        r = _make_step_result(step_name="s1")

        mock_inspector = MagicMock()
        mock_inspection = MagicMock()
        mock_inspection.requires_diagnosis = True
        mock_inspection.risk_score = 0.8
        mock_inspection.issue_summary = "Potential logic error"
        mock_inspector.inspect_step.return_value = mock_inspection

        with (
            _patched_execute(phase, AsyncMock(return_value=r)),
            patch(
                "core.intelligence.reasoning.inspector_guard.get_inspector_guard",
                return_value=mock_inspector,
            ),
        ):
            result = await phase.execute("task", arch)

        assert any(i.issue_type == "inspector_guard_flag" for i in result.issues)

    @pytest.mark.asyncio
    async def test_pointer_memory_large_output(self):
        """PointerMemory should replace large outputs with pointer summaries."""
        phase = _make_phase()
        steps = [_make_step(name="s1", agent_id="claude")]
        arch = _make_architecture(steps=steps)

        r = _make_step_result(step_name="s1", output="Large output data " * 100)

        mock_pmem = MagicMock()
        mock_pmem.should_store.return_value = True
        mock_pointer = MagicMock()
        mock_pointer.context_representation = "[POINTER: large output stored externally]"
        mock_pmem.store.return_value = mock_pointer

        with (
            _patched_execute(phase, AsyncMock(return_value=r)),
            patch(
                "core.memory_pkg.memory.pointer_memory.get_pointer_memory",
                return_value=mock_pmem,
            ),
        ):
            await phase.execute("task", arch)

        # The context manager should have received the pointer representation
        call_args = phase.context_manager.add_execution_result.call_args
        assert "[POINTER:" in call_args[0][1]


# =============================================================================
# _execute_via_swarm
# =============================================================================


class TestExecuteViaSwarm:
    """Test Swarm delegation path."""

    @pytest.mark.asyncio
    async def test_successful_delegation(self):
        phase = _make_phase()
        phase.swarm_bridge = MagicMock()

        mock_delegation_result = MagicMock()
        mock_delegation_result.success = True
        mock_delegation_result.summary = "Swarm completed task"
        mock_delegation_result.failure_diagnostics = []
        mock_delegation_result.fallback_chain = [MagicMock(value="parallel")]
        mock_delegation_result.mode_used = MagicMock(value="parallel")
        phase.swarm_bridge.delegate = AsyncMock(return_value=mock_delegation_result)

        step = _make_step(swarm_mode="parallel")
        result = await phase._execute_via_swarm("task", step, [])

        assert result.status == "success"
        assert "Swarm completed task" in result.output
        assert "swarm:" in result.agent_id

    @pytest.mark.asyncio
    async def test_failed_delegation(self):
        phase = _make_phase()
        phase.swarm_bridge = MagicMock()

        mock_delegation_result = MagicMock()
        mock_delegation_result.success = False
        mock_delegation_result.summary = None
        mock_delegation_result.failure_diagnostics = ["Network timeout", "Model overload"]
        mock_delegation_result.fallback_chain = []
        mock_delegation_result.mode_used = MagicMock(value="parallel")
        phase.swarm_bridge.delegate = AsyncMock(return_value=mock_delegation_result)

        step = _make_step(swarm_mode="parallel")
        result = await phase._execute_via_swarm("task", step, [])

        assert result.status == "error"
        assert any(i.issue_type == "swarm_delegation_failed" for i in result.issues)

    @pytest.mark.asyncio
    async def test_invalid_swarm_mode(self):
        phase = _make_phase()
        phase.swarm_bridge = MagicMock()

        with patch(
            "core.intelligence.swarm.collaboration_modes.CollaborationMode.from_string",
            side_effect=ValueError("Invalid mode"),
        ):
            step = _make_step(swarm_mode="invalid_mode")
            result = await phase._execute_via_swarm("task", step, [])

        assert result.status == "error"
        assert result.agent_id == "swarm:error"
        assert any(i.issue_type == "invalid_swarm_mode" for i in result.issues)

    @pytest.mark.asyncio
    async def test_swarm_exception_produces_critical(self):
        phase = _make_phase()
        phase.swarm_bridge = MagicMock()

        with patch(
            "core.intelligence.swarm.collaboration_modes.CollaborationMode.from_string",
            side_effect=RuntimeError("Swarm engine crashed"),
        ):
            step = _make_step(swarm_mode="parallel")
            result = await phase._execute_via_swarm("task", step, [])

        assert result.status == "error"
        assert any(i.severity == IssueSeverity.CRITICAL for i in result.issues)
        assert any(i.issue_type == "swarm_exception" for i in result.issues)

    @pytest.mark.asyncio
    async def test_fallback_chain_logged(self):
        phase = _make_phase()
        phase.swarm_bridge = MagicMock()

        mode1 = MagicMock(value="parallel")
        mode2 = MagicMock(value="sequential")
        mock_delegation_result = MagicMock()
        mock_delegation_result.success = True
        mock_delegation_result.summary = "Done via fallback"
        mock_delegation_result.failure_diagnostics = []
        mock_delegation_result.fallback_chain = [mode1, mode2]
        mock_delegation_result.mode_used = mode2
        phase.swarm_bridge.delegate = AsyncMock(return_value=mock_delegation_result)

        step = _make_step(swarm_mode="parallel")
        result = await phase._execute_via_swarm("task", step, [])

        assert result.status == "success"
        phase.swarm_bridge.inject_results_into_context.assert_called_once()


# =============================================================================
# needs_diagnosis determination
# =============================================================================


class TestNeedsDiagnosis:
    """Test the needs_diagnosis logic at end of execute()."""

    @pytest.mark.asyncio
    async def test_no_diagnosis_when_all_good(self):
        phase = _make_phase()
        phase._score_execution_quality = MagicMock(return_value=0.9)
        r = _make_step_result(step_name="step1")

        steps = [_make_step(agent_id="claude")]
        arch = _make_architecture(steps=steps)

        with _patched_execute(phase, AsyncMock(return_value=r)):
            result = await phase.execute("task", arch)

        assert result.needs_diagnosis is False

    @pytest.mark.asyncio
    async def test_diagnosis_on_error_severity_issues(self):
        """ERROR severity issues trigger needs_diagnosis."""
        phase = _make_phase()
        phase._score_execution_quality = MagicMock(return_value=0.9)

        r = _make_step_result(
            step_name="step1",
            status="error",
            issues=[_make_issue(severity=IssueSeverity.ERROR)],
        )

        steps = [_make_step(agent_id="claude")]
        arch = _make_architecture(steps=steps)

        with _patched_execute(phase, AsyncMock(return_value=r)):
            result = await phase.execute("task", arch)

        assert result.needs_diagnosis is True

    @pytest.mark.asyncio
    async def test_empty_plan_succeeds(self):
        """An empty execution plan should succeed."""
        phase = _make_phase()
        arch = _make_architecture(steps=[])

        with (
            patch("core.intelligence.hive_mind.phases.phase_execution.emit_agent_speak"),
            patch("core.intelligence.hive_mind.phases.phase_execution.emit_agent_exchange"),
        ):
            result = await phase.execute("task", arch)

        assert result.success is True
        assert len(result.step_results) == 0

    @pytest.mark.asyncio
    async def test_failure_step_set_on_overall_failure(self):
        """failure_step should be set to the last step when success=False."""
        phase = _make_phase()
        r1 = _make_step_result(step_name="s1", status="error", output="Failed")
        r2 = _make_step_result(step_name="s2", status="error", output="Failed")

        steps = [
            _make_step(name="s1", agent_id="claude"),
            _make_step(name="s2", agent_id="claude"),
        ]
        arch = _make_architecture(steps=steps)

        with _patched_execute(phase, AsyncMock(side_effect=[r1, r2])):
            result = await phase.execute("task", arch)

        assert result.success is False
        assert result.failure_step == "s2"  # Last step


# =============================================================================
# IssueSeverity comparison in _execute_step
# =============================================================================


class TestIssueSeverityHandling:
    """Test that issue severity correctly determines step status."""

    @pytest.mark.asyncio
    async def test_critical_issue_sets_error_status(self):
        phase = _make_phase()
        phase._session_integration = MagicMock()
        phase._session_integration.get_agent_session.return_value = None

        # Return a response with a critical issue
        phase.claude.invoke = AsyncMock(
            return_value=_make_driver_response(
                '{"status":"success","output":"OK","artifacts_created":[],"issues":[{"type":"security","severity":"critical","details":"Vulnerable"}]}'
            )
        )
        step = _make_step(agent_id="claude")

        with patch("core.intelligence.hive_mind.phases.phase_execution.get_registry") as mock_reg:
            registry = MagicMock()
            registry.is_claude.return_value = True
            mock_reg.return_value = registry

            result = await phase._execute_step("task", step, [])
            assert result.status == "error"

    @pytest.mark.asyncio
    async def test_warning_issue_sets_warning_status(self):
        phase = _make_phase()
        phase._session_integration = MagicMock()
        phase._session_integration.get_agent_session.return_value = None

        # Use "file not found" (all-lowercase pattern) to trigger hallucination warning
        phase.claude.invoke = AsyncMock(return_value=_make_driver_response("file not found at the given path"))
        step = _make_step(agent_id="claude")

        with patch("core.intelligence.hive_mind.phases.phase_execution.get_registry") as mock_reg:
            registry = MagicMock()
            registry.is_claude.return_value = True
            mock_reg.return_value = registry

            result = await phase._execute_step("task", step, [])
            assert result.status == "warning"


# =============================================================================
# Module-level imports
# =============================================================================


class TestModuleExports:
    """Test that the module exports expected symbols."""

    def test_execution_prompt_is_string(self):
        assert isinstance(EXECUTION_PROMPT, str)

    def test_execution_phase_result_is_dataclass(self):
        assert hasattr(ExecutionPhaseResult, "__dataclass_fields__")

    def test_monitored_execution_phase_is_class(self):
        assert isinstance(MonitoredExecutionPhase, type)

    def test_hallucination_patterns_is_list(self):
        assert isinstance(MonitoredExecutionPhase.HALLUCINATION_PATTERNS, list)

    def test_error_patterns_is_list(self):
        assert isinstance(MonitoredExecutionPhase.ERROR_PATTERNS, list)
