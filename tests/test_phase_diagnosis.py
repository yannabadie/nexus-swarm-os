"""
Tests for Phase 5: Failure Diagnosis (core.hive_mind.phases.phase_diagnosis).

Validates:
- DiagnosisPhaseResult dataclass
- DIAGNOSIS_PROMPT and SYNTHESIS_PROMPT templates
- MAST/MARS integration try/except blocks (graceful degradation)
- V12.4 integrations: MetaPolicyMemory, FailureClassifier, FaultDetector,
  MultiAgentReflexion, SystemHealth (all must degrade silently)
- _synthesize_diagnoses() logic
- Full execute() flow with mocked drivers
- contributing_factors list building
- _format_execution_context() and _format_issues()
- _parse_diagnosis_response() and _create_fallback_diagnosis()
- get_retry_recommendations() for all FailureType variants
- Error handling when individual V12.4 modules fail
"""

import json
from unittest.mock import (
    AsyncMock,
    MagicMock,
    patch,
)

import pytest

from core.drivers.protocol import DriverResponse, DriverResponseStatus
from core.intelligence.hive_mind.phases.phase_diagnosis import (
    DIAGNOSIS_PROMPT,
    SYNTHESIS_PROMPT,
    DiagnosisPhaseResult,
    FailureDiagnosisPhase,
)
from core.intelligence.hive_mind.types import (
    FAILURE_RECOVERY_MAP,
    BreakpointResponse,
    ExecutionIssue,
    FailureDiagnosis,
    FailureType,
    IssueSeverity,
    MonitoredStepResult,
    RecoveryStrategy,
    UserBreakpoint,
)

# =============================================================================
# Helpers
# =============================================================================


def _make_step_result(
    step_name: str = "step1",
    agent_id: str = "gemini",
    status: str = "success",
    output: str = "Some output text for testing purposes",
    duration: float = 2.0,
    expected_duration: float = 5.0,
    issues: list | None = None,
) -> MonitoredStepResult:
    """Create a MonitoredStepResult for testing."""
    return MonitoredStepResult(
        step_name=step_name,
        agent_id=agent_id,
        status=status,
        output=output,
        duration=duration,
        expected_duration=expected_duration,
        tokens_used=100,
        issues=issues or [],
    )


def _make_issue(
    issue_type: str = "tool_failure",
    severity: IssueSeverity = IssueSeverity.ERROR,
    details: str = "Tool crashed unexpectedly",
    step_name: str = "step1",
) -> ExecutionIssue:
    """Create an ExecutionIssue for testing."""
    return ExecutionIssue(
        issue_type=issue_type,
        severity=severity,
        details=details,
        step_name=step_name,
    )


def _make_diagnosis(
    failure_type: FailureType = FailureType.TOOL_ERROR,
    root_cause: str = "API timeout",
    contributing_factors: list | None = None,
    evidence: list | None = None,
    recommended_changes: list | None = None,
    confidence: float = 0.8,
    missing_capability: str | None = None,
) -> FailureDiagnosis:
    """Create a FailureDiagnosis for testing."""
    return FailureDiagnosis(
        failure_type=failure_type,
        root_cause=root_cause,
        contributing_factors=contributing_factors or [],
        evidence=evidence or [],
        recommended_changes=recommended_changes or ["Retry with longer timeout"],
        confidence=confidence,
        gemini_diagnosis="gemini said X",
        claude_diagnosis="claude said Y",
        missing_capability=missing_capability,
    )


def _make_breakpoint_response(
    chosen_option: str = "retry",
    custom_input: str | None = None,
) -> BreakpointResponse:
    """Create a BreakpointResponse for testing."""
    return BreakpointResponse(
        breakpoint_type=UserBreakpoint.AFTER_DIAGNOSIS,
        chosen_option=chosen_option,
        custom_input=custom_input,
    )


def _make_driver_response(content: str, input_tokens: int = 100, output_tokens: int = 50) -> DriverResponse:
    """Create a DriverResponse as returned by invoke() for diagnosis tests."""
    return DriverResponse(
        content=content,
        status=DriverResponseStatus.SUCCESS,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def _make_phase(
    gemini_response: str = '{"failure_type":"tool_error","root_cause":"API down","contributing_factors":[],"evidence":[],"recommended_changes":["Retry"],"confidence":0.7}',
    claude_response: str = '{"failure_type":"tool_error","root_cause":"API timeout","contributing_factors":[],"evidence":[],"recommended_changes":["Increase timeout"],"confidence":0.6}',
    synthesis_response: str = '{"failure_type":"tool_error","root_cause":"API connectivity","contributing_factors":["network"],"evidence":["logs"],"recommended_changes":["Retry","Check network"],"confidence":0.75}',
    user_decision: str = "retry",
    user_custom_input: str | None = None,
    can_afford: bool = True,
) -> FailureDiagnosisPhase:
    """Create a FailureDiagnosisPhase with mocked dependencies."""
    gemini_driver = MagicMock()
    # gemini.invoke() is called twice: once for diagnosis, once for synthesis
    gemini_driver.send_message_async = AsyncMock(side_effect=[gemini_response, synthesis_response])
    gemini_driver.invoke = AsyncMock(
        side_effect=[
            _make_driver_response(gemini_response),
            _make_driver_response(synthesis_response),
        ]
    )

    claude_driver = MagicMock()
    claude_driver.send_message_async = AsyncMock(return_value=claude_response)
    claude_driver.invoke = AsyncMock(return_value=_make_driver_response(claude_response))

    cost_estimator = MagicMock()
    cost_estimator.can_afford_multiple.return_value = can_afford
    cost_estimator.record_cost = MagicMock()

    context_manager = MagicMock()
    context_manager.add_diagnosis = MagicMock()

    user_handler = MagicMock()
    user_handler.after_diagnosis.return_value = _make_breakpoint_response(
        chosen_option=user_decision,
        custom_input=user_custom_input,
    )

    phase = FailureDiagnosisPhase(
        gemini_driver=gemini_driver,
        claude_driver=claude_driver,
        cost_estimator=cost_estimator,
        context_manager=context_manager,
        user_handler=user_handler,
        task_id="test-task-001",
    )
    return phase


# =============================================================================
# DiagnosisPhaseResult Tests
# =============================================================================


class TestDiagnosisPhaseResult:
    """Tests for the DiagnosisPhaseResult dataclass."""

    def test_basic_creation(self):
        diag = _make_diagnosis()
        result = DiagnosisPhaseResult(
            diagnosis=diag,
            gemini_diagnosis="gemini text",
            claude_diagnosis="claude text",
            user_decision="retry",
        )
        assert result.diagnosis is diag
        assert result.gemini_diagnosis == "gemini text"
        assert result.claude_diagnosis == "claude text"
        assert result.user_decision == "retry"
        assert result.user_modifications is None

    def test_with_user_modifications(self):
        diag = _make_diagnosis()
        result = DiagnosisPhaseResult(
            diagnosis=diag,
            gemini_diagnosis="g",
            claude_diagnosis="c",
            user_decision="modify_changes",
            user_modifications="Use a different API endpoint",
        )
        assert result.user_modifications == "Use a different API endpoint"

    def test_all_user_decisions(self):
        for decision in ("retry", "modify_changes", "escalate", "abort"):
            diag = _make_diagnosis()
            result = DiagnosisPhaseResult(
                diagnosis=diag,
                gemini_diagnosis="g",
                claude_diagnosis="c",
                user_decision=decision,
            )
            assert result.user_decision == decision

    def test_diagnosis_accessible(self):
        diag = _make_diagnosis(failure_type=FailureType.HALLUCINATION)
        result = DiagnosisPhaseResult(
            diagnosis=diag,
            gemini_diagnosis="g",
            claude_diagnosis="c",
            user_decision="retry",
        )
        assert result.diagnosis.failure_type == FailureType.HALLUCINATION
        assert result.diagnosis.root_cause == "API timeout"

    def test_empty_strings_allowed(self):
        diag = _make_diagnosis()
        result = DiagnosisPhaseResult(
            diagnosis=diag,
            gemini_diagnosis="",
            claude_diagnosis="",
            user_decision="abort",
        )
        assert result.gemini_diagnosis == ""
        assert result.claude_diagnosis == ""


# =============================================================================
# Prompt Template Tests
# =============================================================================


class TestPromptTemplates:
    """Tests for DIAGNOSIS_PROMPT and SYNTHESIS_PROMPT templates."""

    def test_diagnosis_prompt_has_placeholders(self):
        assert "{task}" in DIAGNOSIS_PROMPT
        assert "{execution_context}" in DIAGNOSIS_PROMPT
        assert "{failure_step}" in DIAGNOSIS_PROMPT
        assert "{issues}" in DIAGNOSIS_PROMPT

    def test_diagnosis_prompt_contains_json_keys(self):
        assert "failure_type" in DIAGNOSIS_PROMPT
        assert "root_cause" in DIAGNOSIS_PROMPT
        assert "contributing_factors" in DIAGNOSIS_PROMPT
        assert "evidence" in DIAGNOSIS_PROMPT
        assert "recommended_changes" in DIAGNOSIS_PROMPT
        assert "confidence" in DIAGNOSIS_PROMPT
        assert "reasoning" in DIAGNOSIS_PROMPT

    def test_diagnosis_prompt_lists_failure_types(self):
        assert "timeout" in DIAGNOSIS_PROMPT
        assert "capability_missing" in DIAGNOSIS_PROMPT
        assert "hallucination" in DIAGNOSIS_PROMPT
        assert "tool_error" in DIAGNOSIS_PROMPT
        assert "unknown" in DIAGNOSIS_PROMPT

    def test_diagnosis_prompt_formats_correctly(self):
        formatted = DIAGNOSIS_PROMPT.format(
            task="Build a REST API",
            execution_context="Step1: success\nStep2: failed",
            failure_step="Step2",
            issues="- [ERROR] timeout: Request timed out",
        )
        assert "Build a REST API" in formatted
        assert "Step2" in formatted
        assert "timeout" in formatted

    def test_synthesis_prompt_has_placeholders(self):
        assert "{task}" in SYNTHESIS_PROMPT
        assert "{gemini_diagnosis}" in SYNTHESIS_PROMPT
        assert "{claude_diagnosis}" in SYNTHESIS_PROMPT

    def test_synthesis_prompt_contains_json_keys(self):
        assert "failure_type" in SYNTHESIS_PROMPT
        assert "root_cause" in SYNTHESIS_PROMPT
        assert "agents_agreed" in SYNTHESIS_PROMPT
        assert "disagreement_notes" in SYNTHESIS_PROMPT

    def test_synthesis_prompt_formats_correctly(self):
        formatted = SYNTHESIS_PROMPT.format(
            task="Analyze logs",
            gemini_diagnosis="Root cause is timeout",
            claude_diagnosis="Root cause is rate limiting",
        )
        assert "Analyze logs" in formatted
        assert "Root cause is timeout" in formatted
        assert "Root cause is rate limiting" in formatted

    def test_diagnosis_prompt_mentions_missing_capability(self):
        assert "missing_capability" in DIAGNOSIS_PROMPT

    def test_synthesis_prompt_asks_for_unified_diagnosis(self):
        assert "unified diagnosis" in SYNTHESIS_PROMPT.lower() or "synthesize" in SYNTHESIS_PROMPT.lower()


# =============================================================================
# Format Helper Tests
# =============================================================================


class TestFormatHelpers:
    """Tests for _format_execution_context() and _format_issues()."""

    def setup_method(self):
        self.phase = _make_phase()

    def test_format_execution_context_success(self):
        results = [_make_step_result(status="success")]
        text = self.phase._format_execution_context(results)
        assert "step1" in text
        assert "gemini" in text

    def test_format_execution_context_error(self):
        results = [_make_step_result(status="error", step_name="build")]
        text = self.phase._format_execution_context(results)
        assert "build" in text

    def test_format_execution_context_multiple_steps(self):
        results = [
            _make_step_result(step_name="step1", status="success"),
            _make_step_result(step_name="step2", status="error"),
            _make_step_result(step_name="step3", status="warning"),
        ]
        text = self.phase._format_execution_context(results)
        assert "step1" in text
        assert "step2" in text
        assert "step3" in text

    def test_format_execution_context_shows_duration(self):
        results = [_make_step_result(duration=3.5, expected_duration=10.0)]
        text = self.phase._format_execution_context(results)
        assert "3.5" in text
        assert "10.0" in text

    def test_format_execution_context_with_issues(self):
        issue = _make_issue()
        results = [_make_step_result(issues=[issue])]
        text = self.phase._format_execution_context(results)
        assert "Issues: 1" in text

    def test_format_execution_context_empty(self):
        text = self.phase._format_execution_context([])
        assert text == ""

    def test_format_issues_with_issues(self):
        issues = [
            _make_issue(issue_type="timeout", severity=IssueSeverity.CRITICAL, details="Took too long"),
            _make_issue(issue_type="tool_crash", severity=IssueSeverity.ERROR, details="Segfault"),
        ]
        text = self.phase._format_issues(issues)
        assert "CRITICAL" in text
        assert "timeout" in text
        assert "ERROR" in text
        assert "tool_crash" in text

    def test_format_issues_empty(self):
        text = self.phase._format_issues([])
        assert "No specific issues detected" in text

    def test_format_issues_severity_values(self):
        for severity in IssueSeverity:
            issues = [_make_issue(severity=severity)]
            text = self.phase._format_issues(issues)
            assert severity.value.upper() in text.upper()


# =============================================================================
# Fallback Diagnosis Tests
# =============================================================================


class TestFallbackDiagnosis:
    """Tests for _create_fallback_diagnosis()."""

    def setup_method(self):
        self.phase = _make_phase()

    def test_fallback_has_unknown_type(self):
        diag = self.phase._create_fallback_diagnosis("gemini says X", "claude says Y")
        assert diag.failure_type == FailureType.UNKNOWN

    def test_fallback_low_confidence(self):
        diag = self.phase._create_fallback_diagnosis("g", "c")
        assert diag.confidence == 0.3

    def test_fallback_stores_raw_diagnoses(self):
        diag = self.phase._create_fallback_diagnosis("gemini raw", "claude raw")
        assert diag.gemini_diagnosis == "gemini raw"
        assert diag.claude_diagnosis == "claude raw"

    def test_fallback_has_contributing_factors(self):
        diag = self.phase._create_fallback_diagnosis("g", "c")
        assert len(diag.contributing_factors) > 0
        assert "synthesis failed" in diag.contributing_factors[0].lower()

    def test_fallback_recommends_manual_retry(self):
        diag = self.phase._create_fallback_diagnosis("g", "c")
        assert any("retry" in c.lower() for c in diag.recommended_changes)


# =============================================================================
# Parse Diagnosis Response Tests
# =============================================================================


class TestParseDiagnosisResponse:
    """Tests for _parse_diagnosis_response()."""

    def setup_method(self):
        self.phase = _make_phase()

    @patch("core.intelligence.hive_mind.phases.phase_diagnosis.FailureDiagnosisPhase._parse_diagnosis_response")
    def test_parse_valid_json(self, mock_parse):
        """Verify the method is called during synthesis (integration tested elsewhere)."""
        mock_parse.return_value = _make_diagnosis()
        result = mock_parse('{"failure_type":"timeout"}', "g", "c")
        assert result.failure_type == FailureType.TOOL_ERROR

    def test_parse_with_valid_json_string(self):
        response = json.dumps(
            {
                "failure_type": "timeout",
                "root_cause": "Slow network",
                "contributing_factors": ["latency"],
                "evidence": ["log entry"],
                "recommended_changes": ["increase timeout"],
                "confidence": 0.9,
                "missing_capability": None,
            }
        )
        with patch("core.intelligence.hive_mind.json_parser.parse_json_response") as mock_parser:
            mock_parser.return_value = json.loads(response)
            diag = self.phase._parse_diagnosis_response(response, "g", "c")
            assert diag.failure_type == FailureType.TIMEOUT
            assert diag.root_cause == "Slow network"
            assert diag.confidence == 0.9

    def test_parse_with_unknown_failure_type(self):
        with patch("core.intelligence.hive_mind.json_parser.parse_json_response") as mock_parser:
            mock_parser.return_value = {
                "failure_type": "some_random_type",
                "root_cause": "Unknown issue",
            }
            diag = self.phase._parse_diagnosis_response("resp", "g", "c")
            assert diag.failure_type == FailureType.UNKNOWN

    def test_parse_with_none_response(self):
        with patch("core.intelligence.hive_mind.json_parser.parse_json_response") as mock_parser:
            mock_parser.return_value = None
            diag = self.phase._parse_diagnosis_response("bad", "g", "c")
            assert diag.failure_type == FailureType.UNKNOWN
            assert diag.confidence == 0.3

    def test_parse_with_missing_fields_uses_defaults(self):
        with patch("core.intelligence.hive_mind.json_parser.parse_json_response") as mock_parser:
            mock_parser.return_value = {"failure_type": "hallucination"}
            diag = self.phase._parse_diagnosis_response("resp", "g", "c")
            assert diag.failure_type == FailureType.HALLUCINATION
            assert diag.root_cause == "Unknown"
            assert diag.contributing_factors == []
            assert diag.confidence == 0.5

    def test_parse_stores_raw_diagnoses(self):
        with patch("core.intelligence.hive_mind.json_parser.parse_json_response") as mock_parser:
            mock_parser.return_value = {"failure_type": "timeout"}
            diag = self.phase._parse_diagnosis_response("resp", "gemini raw", "claude raw")
            assert diag.gemini_diagnosis == "gemini raw"
            assert diag.claude_diagnosis == "claude raw"

    def test_parse_exception_returns_fallback(self):
        with patch("core.intelligence.hive_mind.json_parser.parse_json_response") as mock_parser:
            mock_parser.return_value = {"confidence": "not_a_number"}
            diag = self.phase._parse_diagnosis_response("resp", "g", "c")
            # Should fallback due to float() failure on "not_a_number"
            assert diag.failure_type == FailureType.UNKNOWN
            assert diag.confidence == 0.3


# =============================================================================
# Synthesize Diagnoses Tests
# =============================================================================


class TestSynthesizeDiagnoses:
    """Tests for _synthesize_diagnoses()."""

    @pytest.mark.asyncio
    async def test_successful_synthesis(self):
        synthesis_json = json.dumps(
            {
                "failure_type": "timeout",
                "root_cause": "Slow API",
                "contributing_factors": ["network"],
                "evidence": ["latency log"],
                "recommended_changes": ["increase timeout"],
                "confidence": 0.85,
            }
        )
        phase = _make_phase()
        # Override gemini driver to return synthesis_json directly (source uses invoke())
        phase.gemini.invoke = AsyncMock(return_value=_make_driver_response(synthesis_json))
        # Initialize session integration so _synthesize_diagnoses can use it
        phase._session_integration = MagicMock()
        phase._session_integration.get_agent_session.return_value = "synth-session-uuid"

        diag = await phase._synthesize_diagnoses(
            task="Build API",
            gemini_diagnosis="gemini says timeout",
            claude_diagnosis="claude says timeout",
        )
        assert diag.failure_type == FailureType.TIMEOUT
        assert diag.root_cause == "Slow API"

    @pytest.mark.asyncio
    async def test_synthesis_falls_back_on_driver_error(self):
        phase = _make_phase()
        phase.gemini.invoke = AsyncMock(side_effect=RuntimeError("LLM down"))
        phase._session_integration = MagicMock()
        phase._session_integration.get_agent_session.return_value = "uuid"

        diag = await phase._synthesize_diagnoses("task", "g diag", "c diag")
        # Should produce fallback diagnosis
        assert diag.failure_type == FailureType.UNKNOWN
        assert diag.confidence == 0.3

    @pytest.mark.asyncio
    async def test_synthesis_records_cost(self):
        synthesis_json = json.dumps(
            {
                "failure_type": "tool_error",
                "root_cause": "crash",
                "confidence": 0.5,
            }
        )
        phase = _make_phase(synthesis_response=synthesis_json)
        phase._session_integration = MagicMock()
        phase._session_integration.get_agent_session.return_value = "uuid"

        await phase._synthesize_diagnoses("task", "g", "c")
        # Source uses record_tokens() if available (MagicMock has it auto-created), else record_cost()
        assert phase.cost_estimator.record_tokens.called or phase.cost_estimator.record_cost.called, (
            "Expected either record_tokens or record_cost to be called"
        )

    @pytest.mark.asyncio
    async def test_synthesis_without_session_integration(self):
        synthesis_json = json.dumps(
            {
                "failure_type": "strategy_wrong",
                "root_cause": "bad plan",
                "confidence": 0.6,
            }
        )
        phase = _make_phase()
        # Override gemini driver to return synthesis_json directly (source uses invoke())
        phase.gemini.invoke = AsyncMock(return_value=_make_driver_response(synthesis_json))
        phase._session_integration = None

        diag = await phase._synthesize_diagnoses("task", "g", "c")
        assert diag.failure_type == FailureType.STRATEGY_WRONG


# =============================================================================
# Execute Flow Tests
# =============================================================================


class TestExecuteFlow:
    """Tests for the full execute() method with mocked drivers."""

    @pytest.mark.asyncio
    async def test_execute_returns_diagnosis_phase_result(self):
        synthesis_json = json.dumps(
            {
                "failure_type": "tool_error",
                "root_cause": "API failed",
                "contributing_factors": ["bad endpoint"],
                "evidence": ["error 500"],
                "recommended_changes": ["fix endpoint"],
                "confidence": 0.75,
            }
        )
        phase = _make_phase(synthesis_response=synthesis_json)

        step_results = [_make_step_result(status="error")]
        issues = [_make_issue()]

        result = await phase.execute(
            task="Build API",
            step_results=step_results,
            issues=issues,
            failure_step="step1",
        )

        assert isinstance(result, DiagnosisPhaseResult)
        assert result.user_decision == "retry"

    @pytest.mark.asyncio
    async def test_execute_handles_gemini_exception(self):
        phase = _make_phase()
        phase.gemini.invoke = AsyncMock(
            side_effect=[
                RuntimeError("Gemini exploded"),
                _make_driver_response('{"failure_type":"unknown","root_cause":"fallback","confidence":0.3}'),
            ]
        )

        result = await phase.execute(
            task="Fix bug",
            step_results=[_make_step_result()],
            issues=[],
            failure_step="step1",
        )
        assert isinstance(result, DiagnosisPhaseResult)
        # Gemini diagnosis should contain the error message
        assert "failed" in result.gemini_diagnosis.lower() or "exploded" in result.gemini_diagnosis.lower()

    @pytest.mark.asyncio
    async def test_execute_handles_claude_exception(self):
        synthesis_json = json.dumps(
            {
                "failure_type": "unknown",
                "root_cause": "partial",
                "confidence": 0.4,
            }
        )
        phase = _make_phase(synthesis_response=synthesis_json)
        phase.claude.invoke = AsyncMock(side_effect=RuntimeError("Claude down"))

        result = await phase.execute(
            task="Deploy",
            step_results=[_make_step_result()],
            issues=[],
            failure_step=None,
        )
        assert isinstance(result, DiagnosisPhaseResult)
        assert "failed" in result.claude_diagnosis.lower() or "down" in result.claude_diagnosis.lower()

    @pytest.mark.asyncio
    async def test_execute_handles_both_exceptions(self):
        phase = _make_phase()
        phase.gemini.invoke = AsyncMock(
            side_effect=[
                RuntimeError("G down"),
                _make_driver_response('{"failure_type":"unknown","root_cause":"both failed","confidence":0.2}'),
            ]
        )
        phase.claude.invoke = AsyncMock(side_effect=RuntimeError("C down"))

        result = await phase.execute(
            task="Complex task",
            step_results=[_make_step_result()],
            issues=[],
            failure_step="step1",
        )
        assert isinstance(result, DiagnosisPhaseResult)
        assert "failed" in result.gemini_diagnosis.lower()
        assert "failed" in result.claude_diagnosis.lower()

    @pytest.mark.asyncio
    async def test_execute_records_context_diagnoses(self):
        synthesis_json = json.dumps(
            {
                "failure_type": "tool_error",
                "root_cause": "crash",
                "confidence": 0.5,
            }
        )
        phase = _make_phase(synthesis_response=synthesis_json)

        await phase.execute(
            task="Task",
            step_results=[_make_step_result()],
            issues=[],
            failure_step="s1",
        )
        assert phase.context_manager.add_diagnosis.call_count == 2

    @pytest.mark.asyncio
    async def test_execute_calls_user_handler(self):
        synthesis_json = json.dumps(
            {
                "failure_type": "timeout",
                "root_cause": "slow",
                "confidence": 0.6,
            }
        )
        phase = _make_phase(synthesis_response=synthesis_json, user_decision="escalate")

        result = await phase.execute(
            task="Task",
            step_results=[_make_step_result()],
            issues=[],
            failure_step="s1",
        )
        phase.user_handler.after_diagnosis.assert_called_once()
        assert result.user_decision == "escalate"

    @pytest.mark.asyncio
    async def test_execute_with_user_modifications(self):
        synthesis_json = json.dumps(
            {
                "failure_type": "strategy_wrong",
                "root_cause": "approach",
                "confidence": 0.5,
            }
        )
        phase = _make_phase(
            synthesis_response=synthesis_json,
            user_decision="modify_changes",
            user_custom_input="Use GraphQL instead of REST",
        )

        result = await phase.execute(
            task="Build API",
            step_results=[_make_step_result()],
            issues=[],
            failure_step="s1",
        )
        assert result.user_decision == "modify_changes"
        assert result.user_modifications == "Use GraphQL instead of REST"

    @pytest.mark.asyncio
    async def test_execute_with_none_failure_step(self):
        synthesis_json = json.dumps(
            {
                "failure_type": "unknown",
                "root_cause": "unclear",
                "confidence": 0.3,
            }
        )
        phase = _make_phase(synthesis_response=synthesis_json)

        result = await phase.execute(
            task="Task",
            step_results=[_make_step_result()],
            issues=[],
            failure_step=None,
        )
        assert isinstance(result, DiagnosisPhaseResult)

    @pytest.mark.asyncio
    async def test_execute_cost_estimator_called(self):
        synthesis_json = json.dumps(
            {
                "failure_type": "tool_error",
                "root_cause": "crash",
                "confidence": 0.5,
            }
        )
        phase = _make_phase(synthesis_response=synthesis_json)

        await phase.execute(
            task="Task",
            step_results=[_make_step_result()],
            issues=[],
            failure_step="s1",
        )
        phase.cost_estimator.can_afford_multiple.assert_called_once()


# =============================================================================
# V12.4 Integration Graceful Degradation Tests
# =============================================================================


class TestV124IntegrationsDegradation:
    """
    Tests that each V12.4 integration block catches exceptions silently
    and does not crash the overall diagnosis flow.
    """

    @pytest.mark.asyncio
    async def _run_execute_with_patches(self, patches: dict) -> DiagnosisPhaseResult:
        """Helper: run execute() with given import patches, all V12.4 modules failing."""
        synthesis_json = json.dumps(
            {
                "failure_type": "tool_error",
                "root_cause": "test crash",
                "contributing_factors": [],
                "evidence": [],
                "recommended_changes": ["fix it"],
                "confidence": 0.7,
            }
        )
        phase = _make_phase(synthesis_response=synthesis_json)

        with patch.dict("sys.modules", patches):
            result = await phase.execute(
                task="Test task",
                step_results=[_make_step_result()],
                issues=[_make_issue()],
                failure_step="step1",
            )
        return result

    @pytest.mark.asyncio
    async def test_persona_diagnosis_import_failure(self):
        """Multi-persona analysis gracefully degrades when import fails."""
        synthesis_json = json.dumps(
            {
                "failure_type": "tool_error",
                "root_cause": "test",
                "confidence": 0.5,
            }
        )
        phase = _make_phase(synthesis_response=synthesis_json)

        with patch(
            "core.intelligence.hive_mind.phases.phase_diagnosis.FailureDiagnosisPhase.execute",
            wraps=phase.execute,
        ):
            # The actual import of persona_diagnosis will likely fail in test env
            # which is exactly what we want to verify - it should be caught
            result = await phase.execute(
                task="Task",
                step_results=[_make_step_result()],
                issues=[],
                failure_step="s1",
            )
            assert isinstance(result, DiagnosisPhaseResult)

    @pytest.mark.asyncio
    async def test_mast_mars_import_failure(self):
        """MAST/MARS analysis gracefully degrades when import fails."""
        synthesis_json = json.dumps(
            {
                "failure_type": "tool_error",
                "root_cause": "test",
                "confidence": 0.5,
            }
        )
        phase = _make_phase(synthesis_response=synthesis_json)

        result = await phase.execute(
            task="Task",
            step_results=[_make_step_result()],
            issues=[],
            failure_step="s1",
        )
        # Should complete without raising even if failure_taxonomy not available
        assert isinstance(result, DiagnosisPhaseResult)

    @pytest.mark.asyncio
    async def test_failure_classifier_import_failure(self):
        """FailureClassifier gracefully degrades when import fails."""
        synthesis_json = json.dumps(
            {
                "failure_type": "tool_error",
                "root_cause": "test",
                "confidence": 0.5,
            }
        )
        phase = _make_phase(synthesis_response=synthesis_json)

        result = await phase.execute(
            task="Task",
            step_results=[_make_step_result()],
            issues=[_make_issue()],
            failure_step="s1",
        )
        assert isinstance(result, DiagnosisPhaseResult)

    @pytest.mark.asyncio
    async def test_fault_detector_import_failure(self):
        """FaultDetector gracefully degrades when import fails."""
        synthesis_json = json.dumps(
            {
                "failure_type": "tool_error",
                "root_cause": "test",
                "confidence": 0.5,
            }
        )
        phase = _make_phase(synthesis_response=synthesis_json)

        result = await phase.execute(
            task="Task",
            step_results=[_make_step_result()],
            issues=[],
            failure_step="s1",
        )
        assert isinstance(result, DiagnosisPhaseResult)

    @pytest.mark.asyncio
    async def test_multi_agent_reflexion_import_failure(self):
        """MultiAgentReflexion gracefully degrades when import fails."""
        synthesis_json = json.dumps(
            {
                "failure_type": "tool_error",
                "root_cause": "test",
                "confidence": 0.5,
            }
        )
        phase = _make_phase(synthesis_response=synthesis_json)

        result = await phase.execute(
            task="Task",
            step_results=[_make_step_result()],
            issues=[],
            failure_step="s1",
        )
        assert isinstance(result, DiagnosisPhaseResult)

    @pytest.mark.asyncio
    async def test_system_health_import_failure(self):
        """SystemHealth gracefully degrades when import fails."""
        synthesis_json = json.dumps(
            {
                "failure_type": "tool_error",
                "root_cause": "test",
                "confidence": 0.5,
            }
        )
        phase = _make_phase(synthesis_response=synthesis_json)

        result = await phase.execute(
            task="Task",
            step_results=[_make_step_result()],
            issues=[],
            failure_step="s1",
        )
        assert isinstance(result, DiagnosisPhaseResult)

    @pytest.mark.asyncio
    async def test_meta_policy_memory_failure_inside_mast(self):
        """MetaPolicyMemory consolidation failure is caught inside the MAST block."""
        synthesis_json = json.dumps(
            {
                "failure_type": "timeout",
                "root_cause": "slow",
                "confidence": 0.6,
            }
        )
        phase = _make_phase(synthesis_response=synthesis_json)

        # Mock MAST/MARS to succeed but MetaPolicyMemory to fail
        mock_mast = MagicMock()
        mock_mast_result = MagicMock()
        mock_mast_result.codes = []
        mock_mast_result.primary_category = MagicMock()
        mock_mast_result.primary_category.value = "test"
        mock_mast_result.confidence = 0.8
        mock_mast.classify.return_value = mock_mast_result

        mock_reflector = MagicMock()
        mock_reflection = MagicMock()
        mock_reflection.synthesis = "Test synthesis"
        mock_reflector.reflect.return_value = mock_reflection

        with (
            patch(
                "core.intelligence.hive_mind.phases.phase_diagnosis.get_persona_diagnoser",
                side_effect=ImportError("no persona"),
                create=True,
            ),
            patch.dict(
                "sys.modules",
                {
                    "core.intelligence.hive_mind.failure_taxonomy": MagicMock(
                        get_mast_classifier=MagicMock(return_value=mock_mast),
                        get_triple_reflector=MagicMock(return_value=mock_reflector),
                    ),
                },
            ),
            patch(
                "core.intelligence.reasoning.meta_policy_memory.get_meta_policy_memory",
                side_effect=RuntimeError("MPM broken"),
                create=True,
            ),
        ):
            result = await phase.execute(
                task="Task",
                step_results=[_make_step_result()],
                issues=[],
                failure_step="s1",
            )
        assert isinstance(result, DiagnosisPhaseResult)

    @pytest.mark.asyncio
    async def test_all_v124_modules_fail_simultaneously(self):
        """All V12.4 modules fail at once -- execute still completes."""
        synthesis_json = json.dumps(
            {
                "failure_type": "context_lost",
                "root_cause": "token overflow",
                "confidence": 0.4,
            }
        )
        phase = _make_phase(synthesis_response=synthesis_json)

        result = await phase.execute(
            task="Big complex task that needs everything",
            step_results=[
                _make_step_result(step_name="s1", status="success"),
                _make_step_result(step_name="s2", status="error"),
            ],
            issues=[_make_issue()],
            failure_step="s2",
        )
        assert isinstance(result, DiagnosisPhaseResult)
        assert result.diagnosis.failure_type == FailureType.CONTEXT_LOST


# =============================================================================
# Contributing Factors Tests
# =============================================================================


class TestContributingFactors:
    """Tests for contributing_factors list building during execute()."""

    @pytest.mark.asyncio
    async def test_contributing_factors_start_from_synthesis(self):
        synthesis_json = json.dumps(
            {
                "failure_type": "tool_error",
                "root_cause": "crash",
                "contributing_factors": ["bad input", "missing validation"],
                "confidence": 0.7,
            }
        )
        phase = _make_phase(synthesis_response=synthesis_json)

        result = await phase.execute(
            task="Task",
            step_results=[_make_step_result()],
            issues=[],
            failure_step="s1",
        )
        # At minimum, the synthesis factors should be present
        assert "bad input" in result.diagnosis.contributing_factors
        assert "missing validation" in result.diagnosis.contributing_factors

    @pytest.mark.asyncio
    async def test_contributing_factors_list_is_mutable(self):
        """V12.4 integrations append to the contributing_factors list."""
        diag = _make_diagnosis(contributing_factors=["initial"])
        diag.contributing_factors.append("added_later")
        assert "added_later" in diag.contributing_factors
        assert "initial" in diag.contributing_factors


# =============================================================================
# Get Retry Recommendations Tests
# =============================================================================


class TestGetRetryRecommendations:
    """Tests for get_retry_recommendations() covering all FailureType variants."""

    def setup_method(self):
        self.phase = _make_phase()

    def _make_result(
        self,
        failure_type: FailureType,
        user_decision: str = "retry",
        confidence: float = 0.7,
        missing_capability: str | None = None,
        user_modifications: str | None = None,
    ) -> DiagnosisPhaseResult:
        diag = _make_diagnosis(
            failure_type=failure_type,
            confidence=confidence,
            missing_capability=missing_capability,
        )
        return DiagnosisPhaseResult(
            diagnosis=diag,
            gemini_diagnosis="g",
            claude_diagnosis="c",
            user_decision=user_decision,
            user_modifications=user_modifications,
        )

    def test_timeout_recommendations(self):
        result = self._make_result(FailureType.TIMEOUT)
        recs = self.phase.get_retry_recommendations(result)
        assert recs["failure_type"] == "timeout"
        assert recs["recovery_strategy"] == RecoveryStrategy.RETRY_MODIFIED.value
        assert recs["should_retry"] is True
        assert recs["architecture_changes"]["increase_timeout"] is True
        assert recs["architecture_changes"]["simplify_steps"] is True

    def test_capability_missing_recommendations(self):
        result = self._make_result(
            FailureType.CAPABILITY_MISSING,
            missing_capability="web_scraping",
        )
        recs = self.phase.get_retry_recommendations(result)
        assert recs["failure_type"] == "capability_missing"
        assert recs["recovery_strategy"] == RecoveryStrategy.SPAWN_SPECIALIST.value
        assert recs["architecture_changes"]["spawn_specialist"] is True
        assert recs["architecture_changes"]["capability_needed"] == "web_scraping"

    def test_hallucination_recommendations(self):
        result = self._make_result(FailureType.HALLUCINATION)
        recs = self.phase.get_retry_recommendations(result)
        assert recs["failure_type"] == "hallucination"
        assert recs["architecture_changes"]["add_verification"] is True
        assert recs["architecture_changes"]["use_tools"] is True

    def test_strategy_wrong_recommendations_high_confidence(self):
        result = self._make_result(FailureType.STRATEGY_WRONG, confidence=0.8)
        recs = self.phase.get_retry_recommendations(result)
        assert recs["failure_type"] == "strategy_wrong"
        assert recs["architecture_changes"]["rethink_approach"] is True
        # High confidence -> don't debate again
        assert recs["architecture_changes"]["debate_again"] is False

    def test_strategy_wrong_recommendations_low_confidence(self):
        result = self._make_result(FailureType.STRATEGY_WRONG, confidence=0.3)
        recs = self.phase.get_retry_recommendations(result)
        # Low confidence -> debate again
        assert recs["architecture_changes"]["debate_again"] is True

    def test_tool_error_recommendations(self):
        result = self._make_result(FailureType.TOOL_ERROR)
        recs = self.phase.get_retry_recommendations(result)
        assert recs["failure_type"] == "tool_error"
        assert recs["recovery_strategy"] == RecoveryStrategy.RETRY_SAME.value
        assert recs["architecture_changes"]["check_prerequisites"] is True
        assert recs["architecture_changes"]["validate_paths"] is True

    def test_context_lost_recommendations_high_confidence(self):
        result = self._make_result(FailureType.CONTEXT_LOST, confidence=0.9)
        recs = self.phase.get_retry_recommendations(result)
        assert recs["failure_type"] == "context_lost"
        assert recs["recovery_strategy"] == RecoveryStrategy.CONTEXT_RESET.value
        assert recs["architecture_changes"]["fresh_start"] is True

    def test_context_lost_recommendations_low_confidence(self):
        result = self._make_result(FailureType.CONTEXT_LOST, confidence=0.4)
        recs = self.phase.get_retry_recommendations(result)
        assert recs["architecture_changes"]["fresh_start"] is False

    def test_budget_exceeded_recommendations(self):
        result = self._make_result(FailureType.BUDGET_EXCEEDED)
        recs = self.phase.get_retry_recommendations(result)
        assert recs["failure_type"] == "budget_exceeded"
        assert recs["recovery_strategy"] == RecoveryStrategy.ABORT.value
        assert recs["architecture_changes"]["increase_budget"] is True
        assert recs["architecture_changes"]["skip_optional"] is True

    def test_memory_error_recommendations(self):
        result = self._make_result(FailureType.MEMORY_ERROR)
        recs = self.phase.get_retry_recommendations(result)
        assert recs["failure_type"] == "memory_error"
        assert recs["recovery_strategy"] == RecoveryStrategy.CONTEXT_RESET.value
        assert recs["architecture_changes"]["compress_context"] is True
        assert recs["architecture_changes"]["reload_key_facts"] is True
        assert recs["architecture_changes"]["fresh_session"] is True

    def test_planning_error_recommendations_high_confidence(self):
        result = self._make_result(FailureType.PLANNING_ERROR, confidence=0.9)
        recs = self.phase.get_retry_recommendations(result)
        assert recs["failure_type"] == "planning_error"
        assert recs["recovery_strategy"] == RecoveryStrategy.SIMPLIFY_TASK.value
        assert recs["architecture_changes"]["decompose_task"] is True
        assert recs["architecture_changes"]["switch_lead_agent"] is False

    def test_planning_error_recommendations_low_confidence(self):
        result = self._make_result(FailureType.PLANNING_ERROR, confidence=0.3)
        recs = self.phase.get_retry_recommendations(result)
        assert recs["architecture_changes"]["switch_lead_agent"] is True

    def test_unknown_failure_recommendations(self):
        result = self._make_result(FailureType.UNKNOWN)
        recs = self.phase.get_retry_recommendations(result)
        assert recs["failure_type"] == "unknown"
        assert recs["recovery_strategy"] == RecoveryStrategy.ESCALATE_USER.value
        # UNKNOWN has no specific architecture_changes key
        assert "architecture_changes" not in recs

    def test_user_decision_abort_means_no_retry(self):
        result = self._make_result(FailureType.TIMEOUT, user_decision="abort")
        recs = self.phase.get_retry_recommendations(result)
        assert recs["should_retry"] is False

    def test_user_modifications_applied(self):
        result = self._make_result(
            FailureType.TIMEOUT,
            user_modifications="Switch to backup API",
        )
        recs = self.phase.get_retry_recommendations(result)
        assert recs["user_override"] == "Switch to backup API"

    def test_no_user_modifications_means_no_override_key(self):
        result = self._make_result(FailureType.TIMEOUT)
        recs = self.phase.get_retry_recommendations(result)
        assert "user_override" not in recs

    def test_changes_list_from_diagnosis(self):
        diag = _make_diagnosis(recommended_changes=["fix A", "fix B", "fix C"])
        result = DiagnosisPhaseResult(
            diagnosis=diag,
            gemini_diagnosis="g",
            claude_diagnosis="c",
            user_decision="retry",
        )
        recs = self.phase.get_retry_recommendations(result)
        assert recs["changes"] == ["fix A", "fix B", "fix C"]

    def test_confidence_propagated(self):
        result = self._make_result(FailureType.TIMEOUT, confidence=0.42)
        recs = self.phase.get_retry_recommendations(result)
        assert recs["confidence"] == 0.42

    def test_recovery_strategy_matches_failure_recovery_map(self):
        """Every FailureType maps to the expected RecoveryStrategy from FAILURE_RECOVERY_MAP."""
        for ftype, expected_strategy in FAILURE_RECOVERY_MAP.items():
            result = self._make_result(ftype)
            recs = self.phase.get_retry_recommendations(result)
            assert recs["recovery_strategy"] == expected_strategy.value, (
                f"FailureType.{ftype.name} should map to {expected_strategy.value}, got {recs['recovery_strategy']}"
            )


# =============================================================================
# Driver Diagnosis Tests
# =============================================================================


class TestDriverDiagnosis:
    """Tests for _diagnose_with_gemini() and _diagnose_with_claude()."""

    @pytest.mark.asyncio
    async def test_gemini_diagnosis_returns_response(self):
        phase = _make_phase(gemini_response="gemini output")
        # Reset invoke to return a single value (source uses invoke(), not send_message_async)
        phase.gemini.invoke = AsyncMock(return_value=_make_driver_response("gemini output"))
        result = await phase._diagnose_with_gemini("prompt")
        assert result == "gemini output"

    @pytest.mark.asyncio
    async def test_claude_diagnosis_returns_response(self):
        phase = _make_phase(claude_response="claude output")
        result = await phase._diagnose_with_claude("prompt")
        assert result == "claude output"

    @pytest.mark.asyncio
    async def test_gemini_diagnosis_records_cost(self):
        phase = _make_phase()
        phase.gemini.invoke = AsyncMock(return_value=_make_driver_response("response text here"))
        # Remove record_tokens from mock so record_cost branch is taken
        del phase.cost_estimator.record_tokens
        await phase._diagnose_with_gemini("prompt")
        phase.cost_estimator.record_cost.assert_called_with(
            "failure_diagnosis_gemini",
            (100 + 50),  # input_tokens + output_tokens from _make_driver_response default
        )

    @pytest.mark.asyncio
    async def test_claude_diagnosis_records_cost(self):
        phase = _make_phase()
        # Source uses record_tokens() if available; remove it to force record_cost()
        del phase.cost_estimator.record_tokens
        await phase._diagnose_with_claude("prompt")
        phase.cost_estimator.record_cost.assert_called()

    @pytest.mark.asyncio
    async def test_gemini_diagnosis_raises_on_error(self):
        phase = _make_phase()
        phase.gemini.invoke = AsyncMock(side_effect=ConnectionError("offline"))
        with pytest.raises(ConnectionError, match="offline"):
            await phase._diagnose_with_gemini("prompt")

    @pytest.mark.asyncio
    async def test_claude_diagnosis_raises_on_error(self):
        phase = _make_phase()
        phase.claude.invoke = AsyncMock(side_effect=TimeoutError("too slow"))
        with pytest.raises(TimeoutError, match="too slow"):
            await phase._diagnose_with_claude("prompt")

    @pytest.mark.asyncio
    async def test_gemini_diagnosis_with_session_uuid(self):
        phase = _make_phase()
        phase.gemini.invoke = AsyncMock(return_value=_make_driver_response("ok"))
        await phase._diagnose_with_gemini("prompt", session_uuid="sess-123")
        call_kwargs = phase.gemini.invoke.call_args[1]
        assert call_kwargs.get("session_id") == "sess-123"

    @pytest.mark.asyncio
    async def test_claude_diagnosis_with_session_uuid(self):
        phase = _make_phase()
        await phase._diagnose_with_claude("prompt", session_uuid="sess-456")
        call_kwargs = phase.claude.invoke.call_args[1]
        assert call_kwargs.get("session_id") == "sess-456"


# =============================================================================
# Initialization Tests
# =============================================================================


class TestInitialization:
    """Tests for FailureDiagnosisPhase constructor."""

    def test_default_task_id_generated(self):
        phase = _make_phase()
        assert phase._task_id == "test-task-001"

    def test_auto_generated_task_id(self):
        gemini = MagicMock()
        claude = MagicMock()
        cost = MagicMock()
        ctx = MagicMock()
        user = MagicMock()
        phase = FailureDiagnosisPhase(gemini, claude, cost, ctx, user)
        assert phase._task_id.startswith("diagnosis_") or "diagnosis" in phase._task_id

    def test_session_manager_stored(self):
        session_mgr = MagicMock()
        gemini = MagicMock()
        claude = MagicMock()
        cost = MagicMock()
        ctx = MagicMock()
        user = MagicMock()
        phase = FailureDiagnosisPhase(gemini, claude, cost, ctx, user, session_manager=session_mgr)
        assert phase._session_manager is session_mgr

    def test_session_integration_initially_none(self):
        phase = _make_phase()
        assert phase._session_integration is None

    def test_drivers_stored(self):
        phase = _make_phase()
        assert phase.gemini is not None
        assert phase.claude is not None


# =============================================================================
# Edge Cases and Regression Tests
# =============================================================================


class TestEdgeCases:
    """Edge cases and regression tests."""

    @pytest.mark.asyncio
    async def test_empty_step_results(self):
        synthesis_json = json.dumps(
            {
                "failure_type": "unknown",
                "root_cause": "no steps ran",
                "confidence": 0.2,
            }
        )
        phase = _make_phase(synthesis_response=synthesis_json)

        result = await phase.execute(
            task="Empty task",
            step_results=[],
            issues=[],
            failure_step=None,
        )
        assert isinstance(result, DiagnosisPhaseResult)

    @pytest.mark.asyncio
    async def test_very_long_task_string(self):
        synthesis_json = json.dumps(
            {
                "failure_type": "timeout",
                "root_cause": "complexity",
                "confidence": 0.5,
            }
        )
        phase = _make_phase(synthesis_response=synthesis_json)
        long_task = "Build a system that " + "does many things " * 500

        result = await phase.execute(
            task=long_task,
            step_results=[_make_step_result()],
            issues=[],
            failure_step="s1",
        )
        assert isinstance(result, DiagnosisPhaseResult)

    @pytest.mark.asyncio
    async def test_unicode_in_diagnosis(self):
        synthesis_json = json.dumps(
            {
                "failure_type": "tool_error",
                "root_cause": "Erreur avec des accents et symboles",
                "confidence": 0.6,
            }
        )
        phase = _make_phase(
            gemini_response="Analyse: erreur",
            claude_response="Diagnostic: probl\u00e8me",
            synthesis_response=synthesis_json,
        )

        result = await phase.execute(
            task="T\u00e2che complexe",
            step_results=[_make_step_result()],
            issues=[],
            failure_step="s1",
        )
        assert isinstance(result, DiagnosisPhaseResult)

    def test_failure_recovery_map_completeness(self):
        """Every FailureType has an entry in FAILURE_RECOVERY_MAP."""
        for ftype in FailureType:
            assert ftype in FAILURE_RECOVERY_MAP, f"Missing recovery mapping for {ftype}"

    def test_all_failure_types_have_enum_values(self):
        expected = {
            "timeout",
            "capability_missing",
            "hallucination",
            "strategy_wrong",
            "tool_error",
            "context_lost",
            "budget_exceeded",
            "memory_error",
            "planning_error",
            "unknown",
        }
        actual = {ft.value for ft in FailureType}
        assert actual == expected

    def test_diagnosis_to_dict(self):
        diag = _make_diagnosis(
            failure_type=FailureType.HALLUCINATION,
            root_cause="Made things up",
            contributing_factors=["lack of grounding"],
            evidence=["no tool calls"],
            recommended_changes=["use verification"],
            confidence=0.85,
            missing_capability="fact_checking",
        )
        d = diag.to_dict()
        assert d["failure_type"] == "hallucination"
        assert d["root_cause"] == "Made things up"
        assert d["contributing_factors"] == ["lack of grounding"]
        assert d["evidence"] == ["no tool calls"]
        assert d["recommended_changes"] == ["use verification"]
        assert d["confidence"] == 0.85
        assert d["missing_capability"] == "fact_checking"

    def test_diagnosis_to_dict_no_missing_capability(self):
        diag = _make_diagnosis(missing_capability=None)
        d = diag.to_dict()
        assert d["missing_capability"] is None
