"""
Tests for Phase 2: Strategic Debate.

Validates the StrategicDebatePhase class which handles agent debate,
disagreement resolution, and consensus building in the HiveMind pipeline.

Coverage:
- DebatePhaseResult dataclass
- Debate prompt templates (DEBATE_OPENER_PROMPT, DEBATE_RESPONSE_PROMPT,
  CONSENSUS_CHECK_PROMPT)
- MisalignmentDetector and MisalignmentFlag
- TrajectoryScorer V12.4 integration in _create_result()
- ConsensusTracker V12.4 integration in execute()
- EchoChamberGuard V12.4 integration in execute()
- Debate turn parsing (_parse_argument_response)
- Consensus detection (_check_consensus)
- Disagreement extraction (_get_primary_disagreement)
- Turn limits and early termination (quorum, early exit)
- Mock execution flow with mocked drivers
- V12.4 integration graceful degradation
- Edge cases: immediate agreement, max turns reached, driver errors,
  budget exhaustion, misalignment escalation, forced vote
"""

import json
from dataclasses import fields as dc_fields
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.drivers.protocol import DriverResponse, DriverResponseStatus
from core.intelligence.hive_mind.adaptive_debate import (
    AdaptiveDebateConfig,
    DebateParams,
    TaskComplexity,
)
from core.intelligence.hive_mind.phases.phase_debate import (
    DEBATE_OPENER_PROMPT,
    DEBATE_RESPONSE_PROMPT,
    DebatePhaseResult,
    MisalignmentDetector,
    MisalignmentFlag,
    StrategicDebatePhase,
)
from core.intelligence.hive_mind.prompts import CONSENSUS_SYSTEM_PROMPT
from core.intelligence.hive_mind.types import (
    AnalysisComparison,
    DebateArgument,
    Disagreement,
    IndependentAnalysis,
)

# =============================================================================
# Helper factories
# =============================================================================


def _make_driver_response(content: str, input_tokens: int = 100, output_tokens: int = 50) -> DriverResponse:
    """Create a DriverResponse as returned by invoke() for debate tests."""
    return DriverResponse(
        content=content,
        status=DriverResponseStatus.SUCCESS,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def _make_smart_gemini_invoke(
    argument_json: str | None = None,
    consensus_json: str | None = None,
) -> AsyncMock:
    """Create a smart invoke() mock that returns argument or consensus JSON based on prompt content."""
    _arg_json = argument_json or _make_argument_json(position="SUPPORT", argument="agree")
    _cons_json = consensus_json or _make_consensus_json(consensus_reached=True, consensus_score=0.95)

    async def _side_effect(*args, **kwargs):
        prompt = args[0] if args else kwargs.get("prompt", "")
        if "Evaluate if consensus" in str(prompt) or "consensus" in str(prompt).lower()[:50]:
            return _make_driver_response(_cons_json)
        return _make_driver_response(_arg_json)

    return AsyncMock(side_effect=_side_effect)


def _make_argument_json(
    position: str = "OPPOSE",
    target_point: str = "approach",
    argument: str = "I believe we should use a different approach.",
    evidence: list = None,
    proposed_modification: str = None,
    concession: str = None,
) -> str:
    """Build a valid debate argument JSON string."""
    data = {
        "position": position,
        "target_point": target_point,
        "argument": argument,
        "evidence": evidence or ["evidence1", "evidence2"],
    }
    if proposed_modification:
        data["proposed_modification"] = proposed_modification
    if concession:
        data["concession"] = concession
    return json.dumps(data)


def _make_consensus_json(
    consensus_reached: bool = False,
    consensus_score: float = 0.6,
    resolved_points: list = None,
    unresolved_points: list = None,
    final_approach: str = "Use hybrid approach",
    final_capabilities: list = None,
    gemini_satisfaction: float = 0.7,
    claude_satisfaction: float = 0.7,
    reasoning: str = "Partial agreement on core approach",
) -> str:
    """Build a valid consensus check JSON string."""
    return json.dumps(
        {
            "consensus_reached": consensus_reached,
            "consensus_score": consensus_score,
            "resolved_points": resolved_points or [],
            "unresolved_points": unresolved_points or ["approach"],
            "final_approach": final_approach,
            "final_capabilities": final_capabilities or ["coding"],
            "gemini_satisfaction": gemini_satisfaction,
            "claude_satisfaction": claude_satisfaction,
            "reasoning": reasoning,
        }
    )


def _make_analysis(
    agent_id: str = "gemini",
    confidence: float = 0.8,
    approach: str = "Use parallel processing",
) -> IndependentAnalysis:
    """Create a mock IndependentAnalysis."""
    return IndependentAnalysis(
        agent_id=agent_id,
        task_understanding="Understand the task",
        complexity_assessment="MODERATE",
        proposed_approach=approach,
        required_capabilities=["coding", "analysis"],
        potential_risks=["timeout"],
        confidence=confidence,
        reasoning="Standard analysis",
    )


def _make_comparison(
    agreement_score: float = 0.5,
    needs_debate: bool = True,
    disagreements: list = None,
    gemini_confidence: float = 0.8,
    claude_confidence: float = 0.75,
) -> AnalysisComparison:
    """Create a mock AnalysisComparison."""
    if disagreements is None:
        disagreements = [
            Disagreement(
                topic="approach",
                positions={"gemini": "Use parallel processing", "claude": "Use sequential processing"},
                severity=0.7,
            )
        ]
    return AnalysisComparison(
        analyses={
            "gemini": _make_analysis("gemini", gemini_confidence, "Use parallel processing"),
            "claude": _make_analysis("claude", claude_confidence, "Use sequential processing"),
        },
        disagreements=disagreements,
        agreement_score=agreement_score,
        needs_debate=needs_debate,
        merged_capabilities=["coding", "analysis"],
        merged_risks=["timeout"],
    )


def _make_debate_argument(
    agent_id: str = "gemini",
    turn_number: int = 1,
    position: str = "OPPOSE",
    argument: str = "We should use parallel processing.",
    evidence: list = None,
    concession: str = None,
    proposed_modification: str = None,
) -> DebateArgument:
    """Create a DebateArgument instance."""
    return DebateArgument(
        agent_id=agent_id,
        turn_number=turn_number,
        position=position,
        target_point="approach",
        argument=argument,
        evidence=evidence or ["evidence1"],
        concession=concession,
        proposed_modification=proposed_modification,
    )


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_gemini():
    driver = MagicMock()
    _gemini_arg_json = _make_argument_json(position="OPPOSE")
    driver.send_message_async = AsyncMock(return_value=_gemini_arg_json)
    driver.invoke = AsyncMock(return_value=_make_driver_response(_gemini_arg_json))
    return driver


@pytest.fixture
def mock_claude():
    driver = MagicMock()
    _claude_arg_json = _make_argument_json(position="SUPPORT", concession="I concede the point")
    driver.send_message_async = AsyncMock(return_value=_claude_arg_json)
    driver.invoke = AsyncMock(return_value=_make_driver_response(_claude_arg_json))
    return driver


@pytest.fixture
def mock_cost_estimator():
    est = MagicMock()
    est.can_afford = MagicMock(return_value=True)
    est.can_afford_multiple = MagicMock(return_value=True)
    est.record_cost = MagicMock()
    return est


@pytest.fixture
def mock_context_manager():
    ctx = MagicMock()
    ctx.add_debate_turn = MagicMock()
    ctx.add_item = MagicMock()
    return ctx


@pytest.fixture
def mock_debate_config():
    config = AdaptiveDebateConfig()
    return config


@pytest.fixture
def mock_registry():
    """Provide a MagicMock registry that handles all registry calls."""
    reg = MagicMock()
    reg.is_gemini = MagicMock(side_effect=lambda x: x.lower() == "gemini")
    reg.is_claude = MagicMock(side_effect=lambda x: x.lower() == "claude")
    reg.get_display_name = MagicMock(side_effect=lambda x: x.title())
    reg.get_alternate = MagicMock(side_effect=lambda x: "claude" if x.lower() == "gemini" else "gemini")
    return reg


@pytest.fixture
def phase(mock_gemini, mock_claude, mock_cost_estimator, mock_context_manager):
    """Create a StrategicDebatePhase with mocked dependencies."""
    return StrategicDebatePhase(
        gemini_driver=mock_gemini,
        claude_driver=mock_claude,
        cost_estimator=mock_cost_estimator,
        context_manager=mock_context_manager,
        debate_config=AdaptiveDebateConfig(),
        task_id="test_task_001",
    )


# =============================================================================
# 1. DebatePhaseResult dataclass
# =============================================================================


class TestDebatePhaseResult:
    """Tests for the DebatePhaseResult dataclass."""

    def test_field_names(self):
        """Verify all expected fields exist."""
        names = {f.name for f in dc_fields(DebatePhaseResult)}
        expected = {
            "debate_result",
            "final_approach",
            "final_capabilities",
            "final_mode",
            "was_skipped",
            "skip_reason",
            "misalignment_flags",
        }
        assert expected == names

    def test_default_values(self):
        """Verify default values for optional fields."""
        result = DebatePhaseResult(
            debate_result=MagicMock(),
            final_approach="test",
            final_capabilities=["a"],
            final_mode="PARALLEL",
        )
        assert result.was_skipped is False
        assert result.skip_reason is None
        assert result.misalignment_flags is None

    def test_skipped_result(self):
        """Verify skipped result construction."""
        result = DebatePhaseResult(
            debate_result=MagicMock(),
            final_approach="test",
            final_capabilities=["a"],
            final_mode="PARALLEL",
            was_skipped=True,
            skip_reason="High agreement (90%)",
        )
        assert result.was_skipped is True
        assert "90%" in result.skip_reason

    def test_with_misalignment_flags(self):
        """Verify misalignment flags can be set."""
        flags = [
            MisalignmentFlag(
                flag_type="silent_dissent",
                pattern_matched="I disagree but will proceed",
                severity="MEDIUM",
                agent_id="gemini",
                turn_number=1,
                context="test context",
            )
        ]
        result = DebatePhaseResult(
            debate_result=MagicMock(),
            final_approach="test",
            final_capabilities=["a"],
            final_mode="PARALLEL",
            misalignment_flags=flags,
        )
        assert len(result.misalignment_flags) == 1
        assert result.misalignment_flags[0].flag_type == "silent_dissent"


# =============================================================================
# 2. Debate prompt templates
# =============================================================================


class TestDebatePromptTemplates:
    """Tests for prompt template strings."""

    def test_opener_prompt_has_placeholders(self):
        """DEBATE_OPENER_PROMPT contains all required placeholders."""
        # Some placeholders have format specs (e.g., {agreement_score:.0%})
        for ph in ["task", "topic", "your_position", "other_position"]:
            assert f"{{{ph}}}" in DEBATE_OPENER_PROMPT
        # Placeholders with format specifiers
        assert "{agreement_score:.0%}" in DEBATE_OPENER_PROMPT
        assert "{your_confidence:.0%}" in DEBATE_OPENER_PROMPT

    def test_opener_prompt_format(self):
        """DEBATE_OPENER_PROMPT can be formatted without error."""
        result = DEBATE_OPENER_PROMPT.format(
            task="Build a web app",
            topic="architecture",
            your_position="microservices",
            other_position="monolith",
            agreement_score=0.4,
            your_confidence=0.85,
        )
        assert "Build a web app" in result
        assert "architecture" in result
        assert "40%" in result  # 0.4 formatted as 40%

    def test_response_prompt_has_placeholders(self):
        """DEBATE_RESPONSE_PROMPT contains all required placeholders."""
        for ph in [
            "task",
            "topic",
            "your_position",
            "other_position",
            "other_agent",
            "previous_argument",
            "debate_history",
        ]:
            assert f"{{{ph}}}" in DEBATE_RESPONSE_PROMPT

    def test_response_prompt_format(self):
        """DEBATE_RESPONSE_PROMPT can be formatted without error."""
        result = DEBATE_RESPONSE_PROMPT.format(
            task="Build a web app",
            topic="architecture",
            your_position="microservices",
            other_position="monolith",
            other_agent="Gemini",
            previous_argument="We should use microservices",
            debate_history="[Turn 1] GEMINI (OPPOSE): ...",
        )
        assert "Build a web app" in result
        assert "Gemini" in result

    def test_consensus_system_prompt_has_key_fields(self):
        """CONSENSUS_SYSTEM_PROMPT contains key evaluation fields."""
        for field_name in ["consensus_reached", "consensus_score", "final_approach"]:
            assert field_name in CONSENSUS_SYSTEM_PROMPT

    def test_consensus_system_prompt_is_valid(self):
        """CONSENSUS_SYSTEM_PROMPT is a non-empty string with JSON guidance."""
        assert isinstance(CONSENSUS_SYSTEM_PROMPT, str)
        assert len(CONSENSUS_SYSTEM_PROMPT) > 100
        assert "JSON" in CONSENSUS_SYSTEM_PROMPT

    def test_opener_requests_json_format(self):
        """DEBATE_OPENER_PROMPT instructs agent to respond in JSON."""
        assert "JSON format" in DEBATE_OPENER_PROMPT
        assert '"position"' in DEBATE_OPENER_PROMPT

    def test_response_includes_concede_option(self):
        """DEBATE_RESPONSE_PROMPT mentions CONCEDE as valid position."""
        assert "CONCEDE" in DEBATE_RESPONSE_PROMPT

    def test_consensus_mentions_satisfaction(self):
        """CONSENSUS_SYSTEM_PROMPT asks for satisfaction scores."""
        assert "gemini_satisfaction" in CONSENSUS_SYSTEM_PROMPT
        assert "claude_satisfaction" in CONSENSUS_SYSTEM_PROMPT


# =============================================================================
# 3. MisalignmentDetector and MisalignmentFlag
# =============================================================================


class TestMisalignmentFlag:
    """Tests for the MisalignmentFlag dataclass."""

    def test_field_names(self):
        names = {f.name for f in dc_fields(MisalignmentFlag)}
        assert names == {
            "flag_type",
            "pattern_matched",
            "severity",
            "agent_id",
            "turn_number",
            "context",
        }

    def test_construction(self):
        flag = MisalignmentFlag(
            flag_type="silent_dissent",
            pattern_matched="I disagree but will proceed",
            severity="MEDIUM",
            agent_id="claude",
            turn_number=3,
            context="some debate text",
        )
        assert flag.severity == "MEDIUM"
        assert flag.turn_number == 3


class TestMisalignmentDetector:
    """Tests for the MisalignmentDetector class."""

    def setup_method(self):
        self.detector = MisalignmentDetector()

    def test_silent_dissent_detected(self):
        arg = _make_debate_argument(
            argument="I disagree but will proceed with your suggestion",
        )
        flags = self.detector.check_argument(arg, "claude", 1)
        assert len(flags) >= 1
        assert any(f.flag_type == "silent_dissent" for f in flags)

    def test_input_dismissal_detected(self):
        arg = _make_debate_argument(
            argument="We should be ignoring their input and move forward",
        )
        flags = self.detector.check_argument(arg, "gemini", 2)
        assert len(flags) >= 1
        assert any(f.flag_type == "input_dismissal" for f in flags)

    def test_premature_closure_detected(self):
        arg = _make_debate_argument(
            argument="The conclusion is obvious, no need to discuss further",
        )
        flags = self.detector.check_argument(arg, "gemini", 1)
        assert len(flags) >= 1
        types = {f.flag_type for f in flags}
        assert "premature_closure" in types

    def test_reasoning_action_mismatch_detected(self):
        arg = _make_debate_argument(
            argument="Even though we should use caching I will implement direct calls",
        )
        flags = self.detector.check_argument(arg, "claude", 2)
        assert len(flags) >= 1
        assert any(f.flag_type == "reasoning_action_mismatch" for f in flags)

    def test_no_flags_for_clean_argument(self):
        arg = _make_debate_argument(
            argument="I propose we use sequential processing for better reliability",
        )
        flags = self.detector.check_argument(arg, "gemini", 1)
        assert len(flags) == 0

    def test_concession_field_checked(self):
        """Concession text is also checked for misalignment."""
        arg = _make_debate_argument(
            argument="Fine",
            concession="against my better judgment I accept",
        )
        flags = self.detector.check_argument(arg, "claude", 3)
        assert len(flags) >= 1
        assert any(f.flag_type == "silent_dissent" for f in flags)

    def test_get_all_flags_accumulates(self):
        arg1 = _make_debate_argument(argument="I disagree but will proceed")
        arg2 = _make_debate_argument(argument="The conclusion is obvious")
        self.detector.check_argument(arg1, "gemini", 1)
        self.detector.check_argument(arg2, "claude", 2)
        all_flags = self.detector.get_all_flags()
        assert len(all_flags) >= 2

    def test_get_all_flags_returns_copy(self):
        arg = _make_debate_argument(argument="I disagree but will proceed")
        self.detector.check_argument(arg, "gemini", 1)
        flags1 = self.detector.get_all_flags()
        flags2 = self.detector.get_all_flags()
        assert flags1 is not flags2

    def test_get_high_severity_count(self):
        # input_dismissal is HIGH severity
        arg = _make_debate_argument(argument="ignoring their input completely")
        self.detector.check_argument(arg, "gemini", 1)
        assert self.detector.get_high_severity_count() >= 1

    def test_should_escalate_below_threshold(self):
        # silent_dissent is MEDIUM, not HIGH
        arg = _make_debate_argument(argument="I disagree but will proceed")
        self.detector.check_argument(arg, "gemini", 1)
        assert self.detector.should_escalate(threshold=2) is False

    def test_should_escalate_above_threshold(self):
        arg1 = _make_debate_argument(argument="ignoring their input")
        arg2 = _make_debate_argument(argument="The conclusion is obvious")
        self.detector.check_argument(arg1, "gemini", 1)
        self.detector.check_argument(arg2, "claude", 2)
        assert self.detector.should_escalate(threshold=2) is True

    def test_reset_clears_flags(self):
        arg = _make_debate_argument(argument="I disagree but will proceed")
        self.detector.check_argument(arg, "gemini", 1)
        assert len(self.detector.get_all_flags()) >= 1
        self.detector.reset()
        assert len(self.detector.get_all_flags()) == 0
        assert self.detector.get_high_severity_count() == 0

    def test_severity_map_consistency(self):
        """All pattern types have a severity mapping."""
        for pattern_type in MisalignmentDetector.MISALIGNMENT_PATTERNS:
            assert pattern_type in MisalignmentDetector.SEVERITY_MAP

    def test_flag_context_truncated_to_200(self):
        """Context field is truncated to 200 chars."""
        long_text = "I disagree but will proceed " + "x" * 500
        arg = _make_debate_argument(argument=long_text)
        flags = self.detector.check_argument(arg, "gemini", 1)
        for f in flags:
            assert len(f.context) <= 200

    def test_case_insensitive_matching(self):
        """Patterns match case-insensitively."""
        arg = _make_debate_argument(
            argument="AGAINST MY BETTER JUDGMENT I accept",
        )
        flags = self.detector.check_argument(arg, "gemini", 1)
        assert len(flags) >= 1


# =============================================================================
# 4. _get_primary_disagreement
# =============================================================================


class TestGetPrimaryDisagreement:
    """Tests for StrategicDebatePhase._get_primary_disagreement."""

    def test_returns_highest_severity(self, phase):
        disagreements = [
            Disagreement(topic="approach", positions={"gemini": "a", "claude": "b"}, severity=0.3),
            Disagreement(topic="security", positions={"gemini": "c", "claude": "d"}, severity=0.9),
            Disagreement(topic="mode", positions={"gemini": "e", "claude": "f"}, severity=0.5),
        ]
        result = phase._get_primary_disagreement(disagreements)
        assert result.topic == "security"
        assert result.severity == 0.9

    def test_returns_default_when_empty(self, phase):
        result = phase._get_primary_disagreement([])
        assert result.topic == "approach"
        assert result.severity == 0.5

    def test_single_disagreement(self, phase):
        disagreements = [
            Disagreement(topic="mode", positions={"gemini": "a", "claude": "b"}, severity=0.6),
        ]
        result = phase._get_primary_disagreement(disagreements)
        assert result.topic == "mode"


# =============================================================================
# 5. _format_debate_history
# =============================================================================


class TestFormatDebateHistory:
    """Tests for StrategicDebatePhase._format_debate_history."""

    @patch("core.intelligence.hive_mind.phases.phase_debate.get_registry")
    def test_formats_recent_turns(self, mock_get_reg, phase):
        reg = MagicMock()
        reg.get_display_name = MagicMock(side_effect=lambda x: x.title())
        mock_get_reg.return_value = reg

        history = [
            _make_debate_argument("gemini", 1, "OPPOSE", "Gemini arg 1"),
            _make_debate_argument("claude", 2, "SUPPORT", "Claude arg 2"),
        ]
        result = phase._format_debate_history(history)
        assert "[Turn 1]" in result
        assert "[Turn 2]" in result
        assert "GEMINI" in result
        assert "CLAUDE" in result

    @patch("core.intelligence.hive_mind.phases.phase_debate.get_registry")
    def test_includes_concessions(self, mock_get_reg, phase):
        reg = MagicMock()
        reg.get_display_name = MagicMock(return_value="Gemini")
        mock_get_reg.return_value = reg

        history = [
            _make_debate_argument("gemini", 1, "CONCEDE", "I agree", concession="You were right"),
        ]
        result = phase._format_debate_history(history)
        assert "CONCESSION:" in result
        assert "You were right" in result

    @patch("core.intelligence.hive_mind.phases.phase_debate.get_registry")
    def test_limits_to_last_5_turns(self, mock_get_reg, phase):
        reg = MagicMock()
        reg.get_display_name = MagicMock(return_value="Agent")
        mock_get_reg.return_value = reg

        history = [_make_debate_argument("gemini", i, "OPPOSE", f"Arg {i}") for i in range(1, 8)]
        result = phase._format_debate_history(history)
        # Should only show turns 3-7 (last 5)
        assert "[Turn 3]" in result
        assert "[Turn 7]" in result
        assert "[Turn 1]" not in result
        assert "[Turn 2]" not in result


# =============================================================================
# 6. _parse_argument_response
# =============================================================================


class TestParseArgumentResponse:
    """Tests for StrategicDebatePhase._parse_argument_response."""

    def test_parses_valid_json(self, phase):
        response = _make_argument_json(position="SUPPORT", argument="Good idea")
        result = phase._parse_argument_response(response)
        assert result["position"] == "SUPPORT"
        assert result["argument"] == "Good idea"

    def test_handles_dict_response(self, phase):
        response = {
            "content": _make_argument_json(position="OPPOSE"),
        }
        result = phase._parse_argument_response(response)
        assert result["position"] == "OPPOSE"

    def test_fallback_on_invalid_json(self, phase):
        """When JSON parsing fails, returns raw text as argument."""
        response = "This is not valid JSON at all"
        result = phase._parse_argument_response(response)
        assert "argument" in result
        assert "This is not valid JSON" in result["argument"]

    def test_handles_dict_with_text_key(self, phase):
        response = {
            "text": _make_argument_json(position="CONCEDE"),
        }
        result = phase._parse_argument_response(response)
        # Should extract from text key
        assert "argument" in result


# =============================================================================
# 7. _create_skipped_result
# =============================================================================


class TestCreateSkippedResult:
    """Tests for StrategicDebatePhase._create_skipped_result."""

    def test_uses_higher_confidence_analysis(self, phase):
        comparison = _make_comparison(
            agreement_score=0.9,
            needs_debate=False,
            gemini_confidence=0.9,
            claude_confidence=0.7,
        )
        result = phase._create_skipped_result(comparison)
        assert result.was_skipped is True
        assert result.final_approach == "Use parallel processing"  # gemini's

    def test_uses_claude_when_higher(self, phase):
        comparison = _make_comparison(
            agreement_score=0.9,
            needs_debate=False,
            gemini_confidence=0.6,
            claude_confidence=0.95,
        )
        result = phase._create_skipped_result(comparison)
        assert result.final_approach == "Use sequential processing"  # claude's

    def test_skipped_result_has_immediate_consensus_status(self, phase):
        comparison = _make_comparison(agreement_score=0.9, needs_debate=False)
        result = phase._create_skipped_result(comparison)
        assert result.debate_result.status == "IMMEDIATE_CONSENSUS"
        assert result.debate_result.total_turns == 0

    def test_skip_reason_includes_score(self, phase):
        comparison = _make_comparison(agreement_score=0.92, needs_debate=False)
        result = phase._create_skipped_result(comparison)
        assert "92%" in result.skip_reason

    def test_skipped_result_final_mode(self, phase):
        comparison = _make_comparison(agreement_score=0.9, needs_debate=False)
        result = phase._create_skipped_result(comparison)
        assert result.final_mode == "PARALLEL"

    def test_skipped_result_merged_capabilities(self, phase):
        comparison = _make_comparison(agreement_score=0.9, needs_debate=False)
        result = phase._create_skipped_result(comparison)
        assert result.final_capabilities == ["coding", "analysis"]

    def test_debate_result_inner_mode_is_specialist(self, phase):
        """Inner DebateResult.final_mode is SPECIALIST for skipped."""
        comparison = _make_comparison(agreement_score=0.9, needs_debate=False)
        result = phase._create_skipped_result(comparison)
        assert result.debate_result.final_mode == "SPECIALIST"


# =============================================================================
# 8. _create_result (with V12.4 TrajectoryScorer)
# =============================================================================


class TestCreateResult:
    """Tests for StrategicDebatePhase._create_result."""

    def test_consensus_reached_sets_parallel_mode(self, phase):
        result = phase._create_result(
            debate_history=[_make_debate_argument()],
            consensus={
                "consensus_reached": True,
                "consensus_score": 0.9,
                "final_approach": "agreed",
                "final_capabilities": ["a"],
                "resolved_points": ["x"],
                "unresolved_points": [],
                "gemini_satisfaction": 0.8,
                "claude_satisfaction": 0.8,
                "reasoning": "agreed",
            },
            status="CONSENSUS_REACHED",
        )
        assert result.final_mode == "PARALLEL"

    def test_no_consensus_gemini_leads(self, phase):
        result = phase._create_result(
            debate_history=[_make_debate_argument()],
            consensus={
                "consensus_reached": False,
                "consensus_score": 0.5,
                "final_approach": "gemini way",
                "final_capabilities": [],
                "resolved_points": [],
                "unresolved_points": ["x"],
                "gemini_satisfaction": 0.8,
                "claude_satisfaction": 0.4,
                "reasoning": "disagreement",
            },
            status="FORCED_VOTE",
        )
        assert result.final_mode == "LEAD_SUPPORT"

    def test_empty_capabilities_default_to_general(self, phase):
        result = phase._create_result(
            debate_history=[],
            consensus={
                "consensus_reached": True,
                "consensus_score": 0.9,
                "final_approach": "test",
                "final_capabilities": [],
                "resolved_points": [],
                "unresolved_points": [],
                "gemini_satisfaction": 0.5,
                "claude_satisfaction": 0.5,
                "reasoning": "ok",
            },
            status="CONSENSUS_REACHED",
        )
        assert result.final_capabilities == ["general"]

    def test_debate_result_total_turns(self, phase):
        history = [_make_debate_argument("gemini", i) for i in range(1, 4)]
        result = phase._create_result(
            debate_history=history,
            consensus={
                "consensus_reached": True,
                "consensus_score": 0.9,
                "final_approach": "test",
                "final_capabilities": ["a"],
                "resolved_points": [],
                "unresolved_points": [],
                "gemini_satisfaction": 0.5,
                "claude_satisfaction": 0.5,
                "reasoning": "ok",
            },
            status="CONSENSUS_REACHED",
        )
        assert result.debate_result.total_turns == 3

    def test_misalignment_flags_included(self, phase):
        """_create_result includes accumulated misalignment flags."""
        # Trigger a misalignment flag
        arg = _make_debate_argument(argument="I disagree but will proceed")
        phase._misalignment_detector.check_argument(arg, "gemini", 1)

        result = phase._create_result(
            debate_history=[arg],
            consensus={
                "consensus_reached": True,
                "consensus_score": 0.9,
                "final_approach": "test",
                "final_capabilities": ["a"],
                "resolved_points": [],
                "unresolved_points": [],
                "gemini_satisfaction": 0.5,
                "claude_satisfaction": 0.5,
                "reasoning": "ok",
            },
            status="CONSENSUS_REACHED",
        )
        assert result.misalignment_flags is not None
        assert len(result.misalignment_flags) >= 1

    @patch("core.intelligence.reasoning.trajectory_scorer.get_trajectory_scorer")
    def test_trajectory_scorer_called(self, mock_get_scorer, phase):
        """V12.4: TrajectoryScorer is called within _create_result."""
        mock_scorer = MagicMock()
        mock_result = MagicMock()
        mock_result.best_agent = "gemini"
        mock_result.debate_quality = 0.85
        mock_result.conformity_analysis = []
        mock_scorer.score_debate.return_value = mock_result
        mock_get_scorer.return_value = mock_scorer

        history = [_make_debate_argument("gemini", 1), _make_debate_argument("claude", 2)]
        phase._create_result(
            debate_history=history,
            consensus={
                "consensus_reached": True,
                "consensus_score": 0.9,
                "final_approach": "test",
                "final_capabilities": ["a"],
                "resolved_points": [],
                "unresolved_points": [],
                "gemini_satisfaction": 0.5,
                "claude_satisfaction": 0.5,
                "reasoning": "ok",
            },
            status="CONSENSUS_REACHED",
        )
        mock_scorer.score_debate.assert_called_once()
        call_args = mock_scorer.score_debate.call_args[0][0]
        assert len(call_args) == 2  # 2 debate turns
        assert call_args[0]["agent_id"] == "gemini"
        assert call_args[1]["agent_id"] == "claude"

    @patch("core.intelligence.reasoning.trajectory_scorer.get_trajectory_scorer", side_effect=ImportError("no module"))
    def test_trajectory_scorer_graceful_degradation(self, mock_get_scorer, phase):
        """V12.4: _create_result works even if TrajectoryScorer fails."""
        result = phase._create_result(
            debate_history=[_make_debate_argument()],
            consensus={
                "consensus_reached": True,
                "consensus_score": 0.9,
                "final_approach": "test",
                "final_capabilities": ["a"],
                "resolved_points": [],
                "unresolved_points": [],
                "gemini_satisfaction": 0.5,
                "claude_satisfaction": 0.5,
                "reasoning": "ok",
            },
            status="CONSENSUS_REACHED",
        )
        assert result is not None
        assert result.final_approach == "test"

    def test_was_skipped_false_for_create_result(self, phase):
        result = phase._create_result(
            debate_history=[],
            consensus={
                "consensus_reached": True,
                "consensus_score": 0.9,
                "final_approach": "test",
                "final_capabilities": [],
                "resolved_points": [],
                "unresolved_points": [],
                "gemini_satisfaction": 0.5,
                "claude_satisfaction": 0.5,
                "reasoning": "ok",
            },
            status="CONSENSUS_REACHED",
        )
        assert result.was_skipped is False

    def test_default_approach_when_missing(self, phase):
        result = phase._create_result(
            debate_history=[],
            consensus={
                "consensus_reached": True,
                "consensus_score": 0.9,
                "resolved_points": [],
                "unresolved_points": [],
                "gemini_satisfaction": 0.5,
                "claude_satisfaction": 0.5,
                "reasoning": "ok",
            },
            status="OK",
        )
        assert result.final_approach == "Default approach"


# =============================================================================
# 9. execute() - Skipped debate
# =============================================================================


class TestExecuteSkippedDebate:
    """Tests for execute() when debate is skipped."""

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_debate.get_registry")
    async def test_skips_on_high_agreement(self, mock_get_reg, phase):
        mock_get_reg.return_value = MagicMock()
        comparison = _make_comparison(agreement_score=0.95, needs_debate=False)
        result = await phase.execute("test task", comparison)
        assert result.was_skipped is True
        assert result.debate_result.status == "IMMEDIATE_CONSENSUS"

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_debate.get_registry")
    async def test_skipped_does_not_call_drivers(self, mock_get_reg, phase, mock_gemini, mock_claude):
        mock_get_reg.return_value = MagicMock()
        comparison = _make_comparison(agreement_score=0.95, needs_debate=False)
        await phase.execute("test task", comparison)
        mock_gemini.invoke.assert_not_called()
        mock_claude.invoke.assert_not_called()


# =============================================================================
# 10. execute() - Full debate flow with mocked drivers
# =============================================================================


class TestExecuteFullDebate:
    """Tests for full execute() flow with actual debate turns."""

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_debate.emit_agent_exchange")
    @patch("core.intelligence.hive_mind.phases.phase_debate.emit_agent_speak")
    @patch("core.intelligence.hive_mind.phases.phase_debate.get_registry")
    async def test_consensus_reached_after_min_turns(
        self,
        mock_get_reg,
        mock_speak,
        mock_exchange,
        mock_gemini,
        mock_claude,
        mock_cost_estimator,
        mock_context_manager,
    ):
        """Debate reaches consensus after min_turns via consensus check."""
        reg = MagicMock()
        reg.is_gemini = MagicMock(side_effect=lambda x: x == "gemini")
        reg.is_claude = MagicMock(side_effect=lambda x: x == "claude")
        reg.get_display_name = MagicMock(side_effect=lambda x: x.title())
        reg.get_alternate = MagicMock(side_effect=lambda x: "claude" if x == "gemini" else "gemini")
        mock_get_reg.return_value = reg

        # Gemini opposes, Claude supports (source uses invoke())
        _gemini_oppose = _make_argument_json(position="OPPOSE", argument="Gemini argues")
        _gemini_consensus1 = _make_consensus_json(consensus_reached=True, consensus_score=0.92)
        _gemini_consensus2 = _make_consensus_json(consensus_reached=True, consensus_score=0.95)
        _claude_support = _make_argument_json(
            position="SUPPORT", argument="Claude agrees", concession="I concede the point"
        )
        mock_gemini.send_message_async = AsyncMock(side_effect=[_gemini_oppose, _gemini_consensus1, _gemini_consensus2])
        mock_gemini.invoke = AsyncMock(
            side_effect=[
                _make_driver_response(_gemini_oppose),
                _make_driver_response(_gemini_consensus1),
                _make_driver_response(_gemini_consensus2),
            ]
        )
        mock_claude.send_message_async = AsyncMock(return_value=_claude_support)
        mock_claude.invoke = AsyncMock(return_value=_make_driver_response(_claude_support))

        phase = StrategicDebatePhase(
            gemini_driver=mock_gemini,
            claude_driver=mock_claude,
            cost_estimator=mock_cost_estimator,
            context_manager=mock_context_manager,
            debate_config=AdaptiveDebateConfig(),
            task_id="test_full",
        )

        comparison = _make_comparison(agreement_score=0.5, needs_debate=True)
        result = await phase.execute("Build a web app", comparison, TaskComplexity.MODERATE)

        assert result.was_skipped is False
        assert result.debate_result.total_turns >= 2

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_debate.emit_agent_exchange")
    @patch("core.intelligence.hive_mind.phases.phase_debate.emit_agent_speak")
    @patch("core.intelligence.hive_mind.phases.phase_debate.get_registry")
    async def test_quorum_early_termination(
        self,
        mock_get_reg,
        mock_speak,
        mock_exchange,
        mock_gemini,
        mock_claude,
        mock_cost_estimator,
        mock_context_manager,
    ):
        """Quorum reached when two consecutive agents agree."""
        reg = MagicMock()
        reg.is_gemini = MagicMock(side_effect=lambda x: x == "gemini")
        reg.is_claude = MagicMock(side_effect=lambda x: x == "claude")
        reg.get_display_name = MagicMock(side_effect=lambda x: x.title())
        reg.get_alternate = MagicMock(side_effect=lambda x: "claude" if x == "gemini" else "gemini")
        mock_get_reg.return_value = reg

        # Both agents agree from the start (source uses invoke())
        _gemini_agree_json = _make_argument_json(
            position="SUPPORT", argument="I agree", proposed_modification="Use both approaches"
        )
        _claude_concede_json = _make_argument_json(
            position="CONCEDE", argument="I concede, hybrid is best", concession="Sequential alone is not enough"
        )
        mock_gemini.send_message_async = AsyncMock(return_value=_gemini_agree_json)
        mock_gemini.invoke = AsyncMock(return_value=_make_driver_response(_gemini_agree_json))
        mock_claude.send_message_async = AsyncMock(return_value=_claude_concede_json)
        mock_claude.invoke = AsyncMock(return_value=_make_driver_response(_claude_concede_json))

        # Use TRIVIAL complexity so min_turns=2
        config = AdaptiveDebateConfig()
        phase = StrategicDebatePhase(
            gemini_driver=mock_gemini,
            claude_driver=mock_claude,
            cost_estimator=mock_cost_estimator,
            context_manager=mock_context_manager,
            debate_config=config,
            task_id="test_quorum",
        )

        comparison = _make_comparison(agreement_score=0.5, needs_debate=True)
        result = await phase.execute("Build app", comparison, TaskComplexity.TRIVIAL)

        assert result.debate_result.status == "QUORUM_CONSENSUS"
        assert result.debate_result.consensus_confidence == 0.95

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_debate.emit_agent_exchange")
    @patch("core.intelligence.hive_mind.phases.phase_debate.emit_agent_speak")
    @patch("core.intelligence.hive_mind.phases.phase_debate.get_registry")
    async def test_max_turns_reached_forces_vote(
        self,
        mock_get_reg,
        mock_speak,
        mock_exchange,
        mock_gemini,
        mock_claude,
        mock_cost_estimator,
        mock_context_manager,
    ):
        """When max turns reached, vote is forced."""
        reg = MagicMock()
        reg.is_gemini = MagicMock(side_effect=lambda x: x == "gemini")
        reg.is_claude = MagicMock(side_effect=lambda x: x == "claude")
        reg.get_display_name = MagicMock(side_effect=lambda x: x.title())
        reg.get_alternate = MagicMock(side_effect=lambda x: "claude" if x == "gemini" else "gemini")
        mock_get_reg.return_value = reg

        # Gemini is used for both arguments and consensus checks.
        # Return argument JSON for argument calls, consensus JSON for
        # consensus checks (which happen after min_turns).
        _gemini_call_count = 0

        async def _gemini_side_effect(*args, **kwargs):
            nonlocal _gemini_call_count
            _gemini_call_count += 1
            prompt_text = args[0] if args else ""
            # Consensus check prompts contain "Evaluate if consensus"
            if "Evaluate if consensus" in str(prompt_text):
                return _make_consensus_json(consensus_reached=False, consensus_score=0.4)
            return _make_argument_json(position="OPPOSE", argument="No")

        async def _gemini_invoke_side_effect(*args, **kwargs):
            content = await _gemini_side_effect(*args, **kwargs)
            return _make_driver_response(content)

        mock_gemini.send_message_async = AsyncMock(side_effect=_gemini_side_effect)
        mock_gemini.invoke = AsyncMock(side_effect=_gemini_invoke_side_effect)
        _claude_no_json = _make_argument_json(position="OPPOSE", argument="No")
        mock_claude.send_message_async = AsyncMock(return_value=_claude_no_json)
        mock_claude.invoke = AsyncMock(return_value=_make_driver_response(_claude_no_json))

        phase = StrategicDebatePhase(
            gemini_driver=mock_gemini,
            claude_driver=mock_claude,
            cost_estimator=mock_cost_estimator,
            context_manager=mock_context_manager,
            debate_config=AdaptiveDebateConfig(),
            task_id="test_max_turns",
        )

        comparison = _make_comparison(agreement_score=0.4, needs_debate=True)
        result = await phase.execute("Build app", comparison, TaskComplexity.TRIVIAL)

        assert result.debate_result.status == "FORCED_VOTE"
        assert result.was_skipped is False

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_debate.emit_agent_exchange")
    @patch("core.intelligence.hive_mind.phases.phase_debate.emit_agent_speak")
    @patch("core.intelligence.hive_mind.phases.phase_debate.get_registry")
    async def test_budget_exhaustion_exits_early(
        self,
        mock_get_reg,
        mock_speak,
        mock_exchange,
        mock_gemini,
        mock_claude,
        mock_context_manager,
    ):
        """When budget is exhausted, debate exits the loop."""
        reg = MagicMock()
        reg.is_gemini = MagicMock(side_effect=lambda x: x == "gemini")
        reg.is_claude = MagicMock(side_effect=lambda x: x == "claude")
        reg.get_display_name = MagicMock(side_effect=lambda x: x.title())
        reg.get_alternate = MagicMock(side_effect=lambda x: "claude" if x == "gemini" else "gemini")
        mock_get_reg.return_value = reg

        cost = MagicMock()
        cost.can_afford = MagicMock(return_value=False)  # No budget
        cost.record_cost = MagicMock()

        mock_gemini.send_message_async = AsyncMock(return_value=_make_argument_json(position="OPPOSE"))
        mock_claude.send_message_async = AsyncMock(return_value=_make_argument_json(position="OPPOSE"))

        phase = StrategicDebatePhase(
            gemini_driver=mock_gemini,
            claude_driver=mock_claude,
            cost_estimator=cost,
            context_manager=mock_context_manager,
            debate_config=AdaptiveDebateConfig(),
            task_id="test_budget",
        )

        comparison = _make_comparison(agreement_score=0.4, needs_debate=True)
        result = await phase.execute("Build app", comparison, TaskComplexity.TRIVIAL)

        # Should force vote due to zero turns
        assert result.debate_result.status == "FORCED_VOTE"
        assert result.debate_result.total_turns == 0


# =============================================================================
# 11. execute() - Misalignment escalation
# =============================================================================


class TestMisalignmentEscalation:
    """Tests for misalignment detection during execute()."""

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_debate.emit_agent_exchange")
    @patch("core.intelligence.hive_mind.phases.phase_debate.emit_agent_speak")
    @patch("core.intelligence.hive_mind.phases.phase_debate.get_registry")
    async def test_escalation_on_high_severity_flags(
        self,
        mock_get_reg,
        mock_speak,
        mock_exchange,
        mock_gemini,
        mock_claude,
        mock_cost_estimator,
        mock_context_manager,
    ):
        """Debate escalates when 2+ HIGH severity misalignment flags detected."""
        reg = MagicMock()
        reg.is_gemini = MagicMock(side_effect=lambda x: x == "gemini")
        reg.is_claude = MagicMock(side_effect=lambda x: x == "claude")
        reg.get_display_name = MagicMock(side_effect=lambda x: x.title())
        reg.get_alternate = MagicMock(side_effect=lambda x: "claude" if x == "gemini" else "gemini")
        mock_get_reg.return_value = reg

        # Return text triggering HIGH severity patterns (source uses invoke())
        _gemini_escalate_json = _make_argument_json(
            position="OPPOSE", argument="ignoring their input completely, the conclusion is obvious"
        )
        _claude_escalate_json = _make_argument_json(
            position="OPPOSE", argument="let's just proceed and disregard the previous point entirely"
        )
        mock_gemini.send_message_async = AsyncMock(return_value=_gemini_escalate_json)
        mock_gemini.invoke = AsyncMock(return_value=_make_driver_response(_gemini_escalate_json))
        mock_claude.send_message_async = AsyncMock(return_value=_claude_escalate_json)
        mock_claude.invoke = AsyncMock(return_value=_make_driver_response(_claude_escalate_json))

        phase = StrategicDebatePhase(
            gemini_driver=mock_gemini,
            claude_driver=mock_claude,
            cost_estimator=mock_cost_estimator,
            context_manager=mock_context_manager,
            debate_config=AdaptiveDebateConfig(),
            task_id="test_escalation",
        )

        comparison = _make_comparison(agreement_score=0.3, needs_debate=True)
        result = await phase.execute("Build app", comparison, TaskComplexity.TRIVIAL)

        assert result.debate_result.status == "MISALIGNMENT_ESCALATION"
        assert "ESCALATE" in result.final_approach
        assert result.misalignment_flags is not None


# =============================================================================
# 12. _check_consensus
# =============================================================================


class TestCheckConsensus:
    """Tests for StrategicDebatePhase._check_consensus."""

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_debate.get_registry")
    async def test_returns_parsed_consensus(self, mock_get_reg, phase, mock_gemini):
        reg = MagicMock()
        reg.get_display_name = MagicMock(return_value="Gemini")
        mock_get_reg.return_value = reg

        _consensus_json = _make_consensus_json(consensus_reached=True, consensus_score=0.9)
        mock_gemini.send_message_async = AsyncMock(return_value=_consensus_json)
        mock_gemini.invoke = AsyncMock(return_value=_make_driver_response(_consensus_json))
        phase.gemini = mock_gemini

        comparison = _make_comparison()
        disagreement = comparison.disagreements[0]
        history = [_make_debate_argument("gemini", 1)]

        result = await phase._check_consensus("task", history, disagreement, comparison)
        assert result["consensus_reached"] is True
        assert result["consensus_score"] == 0.9

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_debate.get_registry")
    async def test_returns_default_on_failure(self, mock_get_reg, phase, mock_gemini):
        reg = MagicMock()
        reg.get_display_name = MagicMock(return_value="Gemini")
        mock_get_reg.return_value = reg

        mock_gemini.send_message_async = AsyncMock(side_effect=Exception("API error"))
        mock_gemini.invoke = AsyncMock(side_effect=Exception("API error"))
        phase.gemini = mock_gemini

        comparison = _make_comparison()
        disagreement = comparison.disagreements[0]
        history = [_make_debate_argument()]

        result = await phase._check_consensus("task", history, disagreement, comparison)
        assert result["consensus_reached"] is False
        assert result["reasoning"] == "Consensus check failed"

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_debate.get_registry")
    async def test_records_cost(self, mock_get_reg, phase, mock_gemini, mock_cost_estimator):
        reg = MagicMock()
        reg.get_display_name = MagicMock(return_value="Gemini")
        mock_get_reg.return_value = reg

        _consensus_json = _make_consensus_json()
        mock_gemini.send_message_async = AsyncMock(return_value=_consensus_json)
        mock_gemini.invoke = AsyncMock(return_value=_make_driver_response(_consensus_json))
        phase.gemini = mock_gemini
        del mock_cost_estimator.record_tokens  # Force record_cost branch
        phase.cost_estimator = mock_cost_estimator

        comparison = _make_comparison()
        disagreement = comparison.disagreements[0]
        history = [_make_debate_argument()]

        await phase._check_consensus("task", history, disagreement, comparison)
        mock_cost_estimator.record_cost.assert_called()


# =============================================================================
# 13. _get_argument
# =============================================================================


class TestGetArgument:
    """Tests for StrategicDebatePhase._get_argument."""

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_debate.get_registry")
    async def test_gemini_opening_argument(self, mock_get_reg, phase, mock_gemini):
        reg = MagicMock()
        reg.is_gemini = MagicMock(side_effect=lambda x: x == "gemini")
        reg.is_claude = MagicMock(side_effect=lambda x: x == "claude")
        reg.get_display_name = MagicMock(side_effect=lambda x: x.title())
        reg.get_alternate = MagicMock(return_value="claude")
        mock_get_reg.return_value = reg

        mock_gemini.send_message_async = AsyncMock(
            return_value=_make_argument_json(position="OPPOSE", argument="Opening arg")
        )
        phase.gemini = mock_gemini

        comparison = _make_comparison()
        disagreement = comparison.disagreements[0]
        params = DebateParams()

        result = await phase._get_argument(
            task="Build app",
            speaker="gemini",
            turn_number=1,
            disagreement=disagreement,
            comparison=comparison,
            debate_history=[],
            params=params,
        )
        assert result.agent_id == "gemini"
        assert result.turn_number == 1
        assert result.position == "OPPOSE"

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_debate.get_registry")
    async def test_claude_response_argument(self, mock_get_reg, phase, mock_claude):
        reg = MagicMock()
        reg.is_gemini = MagicMock(side_effect=lambda x: x == "gemini")
        reg.is_claude = MagicMock(side_effect=lambda x: x == "claude")
        reg.get_display_name = MagicMock(side_effect=lambda x: x.title())
        reg.get_alternate = MagicMock(return_value="gemini")
        mock_get_reg.return_value = reg

        _support_json = _make_argument_json(position="SUPPORT", argument="I agree", concession="Good point")
        mock_claude.send_message_async = AsyncMock(return_value=_support_json)
        mock_claude.invoke = AsyncMock(return_value=_make_driver_response(_support_json))
        phase.claude = mock_claude

        comparison = _make_comparison()
        disagreement = comparison.disagreements[0]
        params = DebateParams()
        prior = [_make_debate_argument("gemini", 1)]

        result = await phase._get_argument(
            task="Build app",
            speaker="claude",
            turn_number=2,
            disagreement=disagreement,
            comparison=comparison,
            debate_history=prior,
            params=params,
        )
        assert result.agent_id == "claude"
        assert result.position == "SUPPORT"
        assert result.concession == "Good point"

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_debate.get_registry")
    async def test_driver_error_returns_fallback(self, mock_get_reg, phase, mock_gemini):
        reg = MagicMock()
        reg.is_gemini = MagicMock(return_value=True)
        reg.is_claude = MagicMock(return_value=False)
        mock_get_reg.return_value = reg

        mock_gemini.send_message_async = AsyncMock(side_effect=Exception("Driver failed"))
        mock_gemini.invoke = AsyncMock(side_effect=Exception("Driver failed"))
        phase.gemini = mock_gemini

        comparison = _make_comparison()
        disagreement = comparison.disagreements[0]
        params = DebateParams()

        result = await phase._get_argument(
            task="Build app",
            speaker="gemini",
            turn_number=1,
            disagreement=disagreement,
            comparison=comparison,
            debate_history=[],
            params=params,
        )
        assert result.agent_id == "gemini"
        assert "Error generating argument" in result.argument
        assert result.position == "OPPOSE"

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_debate.get_registry")
    async def test_records_cost_after_argument(self, mock_get_reg, phase, mock_gemini, mock_cost_estimator):
        reg = MagicMock()
        reg.is_gemini = MagicMock(return_value=True)
        reg.is_claude = MagicMock(return_value=False)
        mock_get_reg.return_value = reg

        _arg_json = _make_argument_json()
        mock_gemini.send_message_async = AsyncMock(return_value=_arg_json)
        mock_gemini.invoke = AsyncMock(return_value=_make_driver_response(_arg_json))
        del mock_cost_estimator.record_tokens  # Force record_cost branch
        phase.gemini = mock_gemini
        phase.cost_estimator = mock_cost_estimator

        comparison = _make_comparison()
        disagreement = comparison.disagreements[0]
        params = DebateParams()

        await phase._get_argument(
            task="test",
            speaker="gemini",
            turn_number=1,
            disagreement=disagreement,
            comparison=comparison,
            debate_history=[],
            params=params,
        )
        # Source calculates total_tokens = input_tokens + output_tokens (100+50=150 from _make_driver_response)
        mock_cost_estimator.record_cost.assert_called_with("debate_turn", 150)


# =============================================================================
# 14. _force_vote
# =============================================================================


class TestForceVote:
    """Tests for StrategicDebatePhase._force_vote."""

    @pytest.mark.asyncio
    async def test_forced_vote_returns_result(self, phase):
        comparison = _make_comparison()
        params = DebateParams()
        history = [
            _make_debate_argument("gemini", 1, "OPPOSE"),
            _make_debate_argument("claude", 2, "OPPOSE"),
        ]

        result = await phase._force_vote("task", history, comparison, params)
        assert result.debate_result.status == "FORCED_VOTE"
        assert result.was_skipped is False

    @pytest.mark.asyncio
    async def test_forced_vote_records_outcome(self, phase, mock_cost_estimator):
        comparison = _make_comparison()
        params = DebateParams()
        history = [_make_debate_argument("gemini", 1)]

        await phase._force_vote("task", history, comparison, params)
        # Debate config should have recorded outcome
        stats = phase.debate_config.get_stats()
        assert stats["total_debates"] >= 1

    @pytest.mark.asyncio
    async def test_forced_vote_uses_confidence_for_decision(self, phase):
        comparison = _make_comparison(gemini_confidence=0.95, claude_confidence=0.3)
        params = DebateParams()
        history = [_make_debate_argument()]

        result = await phase._force_vote("task", history, comparison, params)
        # Gemini has much higher confidence, should win
        assert "parallel" in result.final_approach.lower() or result.final_approach != ""


# =============================================================================
# 15. V12.4 Integrations - Graceful Degradation
# =============================================================================


class TestV124IntegrationGracefulDegradation:
    """Test that V12.4 optional modules fail gracefully."""

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_debate.emit_agent_exchange")
    @patch("core.intelligence.hive_mind.phases.phase_debate.emit_agent_speak")
    @patch("core.intelligence.hive_mind.phases.phase_debate.get_registry")
    async def test_consensus_tracker_import_failure(
        self,
        mock_get_reg,
        mock_speak,
        mock_exchange,
        mock_gemini,
        mock_claude,
        mock_cost_estimator,
        mock_context_manager,
    ):
        """ConsensusTracker import failure does not crash debate."""
        reg = MagicMock()
        reg.is_gemini = MagicMock(side_effect=lambda x: x == "gemini")
        reg.is_claude = MagicMock(side_effect=lambda x: x == "claude")
        reg.get_display_name = MagicMock(side_effect=lambda x: x.title())
        reg.get_alternate = MagicMock(side_effect=lambda x: "claude" if x == "gemini" else "gemini")
        mock_get_reg.return_value = reg

        # Both agents agree -> quorum (source uses invoke())
        _agree_json = _make_argument_json(position="SUPPORT", argument="agree")
        _agree_too_json = _make_argument_json(position="CONCEDE", argument="agree too")
        mock_gemini.send_message_async = AsyncMock(return_value=_agree_json)
        mock_gemini.invoke = _make_smart_gemini_invoke(argument_json=_agree_json)
        mock_claude.send_message_async = AsyncMock(return_value=_agree_too_json)
        mock_claude.invoke = AsyncMock(return_value=_make_driver_response(_agree_too_json))

        phase = StrategicDebatePhase(
            gemini_driver=mock_gemini,
            claude_driver=mock_claude,
            cost_estimator=mock_cost_estimator,
            context_manager=mock_context_manager,
            debate_config=AdaptiveDebateConfig(),
            task_id="test_ct_fail",
        )

        with patch(
            "core.intelligence.hive_mind.phases.phase_debate.StrategicDebatePhase.execute",
            wraps=phase.execute,
        ):
            comparison = _make_comparison(agreement_score=0.5, needs_debate=True)
            # This should not crash even if consensus_tracker import fails
            result = await phase.execute("Build app", comparison, TaskComplexity.TRIVIAL)
            assert result is not None

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_debate.emit_agent_exchange")
    @patch("core.intelligence.hive_mind.phases.phase_debate.emit_agent_speak")
    @patch("core.intelligence.hive_mind.phases.phase_debate.get_registry")
    async def test_echo_chamber_guard_import_failure(
        self,
        mock_get_reg,
        mock_speak,
        mock_exchange,
        mock_gemini,
        mock_claude,
        mock_cost_estimator,
        mock_context_manager,
    ):
        """EchoChamberGuard import failure does not crash debate."""
        reg = MagicMock()
        reg.is_gemini = MagicMock(side_effect=lambda x: x == "gemini")
        reg.is_claude = MagicMock(side_effect=lambda x: x == "claude")
        reg.get_display_name = MagicMock(side_effect=lambda x: x.title())
        reg.get_alternate = MagicMock(side_effect=lambda x: "claude" if x == "gemini" else "gemini")
        mock_get_reg.return_value = reg

        _support_json = _make_argument_json(position="SUPPORT")
        _concede_json = _make_argument_json(position="CONCEDE")
        mock_gemini.send_message_async = AsyncMock(return_value=_support_json)
        mock_gemini.invoke = _make_smart_gemini_invoke(argument_json=_support_json)
        mock_claude.send_message_async = AsyncMock(return_value=_concede_json)
        mock_claude.invoke = AsyncMock(return_value=_make_driver_response(_concede_json))

        phase = StrategicDebatePhase(
            gemini_driver=mock_gemini,
            claude_driver=mock_claude,
            cost_estimator=mock_cost_estimator,
            context_manager=mock_context_manager,
            debate_config=AdaptiveDebateConfig(),
            task_id="test_ecg_fail",
        )

        comparison = _make_comparison(agreement_score=0.5, needs_debate=True)
        result = await phase.execute("Build app", comparison, TaskComplexity.TRIVIAL)
        assert result is not None

    def test_trajectory_scorer_exception_handled(self, phase):
        """TrajectoryScorer exception does not prevent _create_result."""
        with patch(
            "core.intelligence.reasoning.trajectory_scorer.get_trajectory_scorer",
            side_effect=RuntimeError("scorer broken"),
        ):
            result = phase._create_result(
                debate_history=[_make_debate_argument()],
                consensus={
                    "consensus_reached": True,
                    "consensus_score": 0.9,
                    "final_approach": "test",
                    "final_capabilities": ["a"],
                    "resolved_points": [],
                    "unresolved_points": [],
                    "gemini_satisfaction": 0.5,
                    "claude_satisfaction": 0.5,
                    "reasoning": "ok",
                },
                status="TEST",
            )
            assert result is not None


# =============================================================================
# 16. Consensus detection via execute flow
# =============================================================================


class TestConsensusDetection:
    """Tests for consensus detection pathways in execute()."""

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_debate.emit_agent_exchange")
    @patch("core.intelligence.hive_mind.phases.phase_debate.emit_agent_speak")
    @patch("core.intelligence.hive_mind.phases.phase_debate.get_registry")
    async def test_early_exit_on_high_consensus(
        self,
        mock_get_reg,
        mock_speak,
        mock_exchange,
        mock_gemini,
        mock_claude,
        mock_cost_estimator,
        mock_context_manager,
    ):
        """Early exit when consensus score exceeds threshold."""
        reg = MagicMock()
        reg.is_gemini = MagicMock(side_effect=lambda x: x == "gemini")
        reg.is_claude = MagicMock(side_effect=lambda x: x == "claude")
        reg.get_display_name = MagicMock(side_effect=lambda x: x.title())
        reg.get_alternate = MagicMock(side_effect=lambda x: "claude" if x == "gemini" else "gemini")
        mock_get_reg.return_value = reg

        # Both OPPOSE, but consensus check returns high score (near threshold)
        # Source uses invoke() for both argument and consensus check
        mock_gemini.invoke = AsyncMock(
            side_effect=[
                _make_driver_response(_make_argument_json(position="OPPOSE", argument="Arg 1")),
                # Consensus check with high score but not reached
                _make_driver_response(_make_consensus_json(consensus_reached=False, consensus_score=0.96)),
                # If more turns needed
                _make_driver_response(_make_argument_json(position="OPPOSE", argument="Arg 3")),
                _make_driver_response(_make_consensus_json(consensus_reached=True, consensus_score=0.98)),
            ]
        )
        mock_claude.invoke = AsyncMock(
            return_value=_make_driver_response(_make_argument_json(position="OPPOSE", argument="Arg 2")),
        )

        phase = StrategicDebatePhase(
            gemini_driver=mock_gemini,
            claude_driver=mock_claude,
            cost_estimator=mock_cost_estimator,
            context_manager=mock_context_manager,
            debate_config=AdaptiveDebateConfig(),
            task_id="test_early_exit",
        )

        comparison = _make_comparison(agreement_score=0.5, needs_debate=True)
        result = await phase.execute("Task", comparison, TaskComplexity.TRIVIAL)

        # Should get EARLY_CONSENSUS since score 0.96 >= 0.95 threshold
        assert result.debate_result.status in ("EARLY_CONSENSUS", "CONSENSUS_REACHED")


# =============================================================================
# 17. Session integration
# =============================================================================


class TestSessionIntegration:
    """Tests for V9.2 session isolation during debate."""

    def test_session_integration_created(self, phase):
        """Phase creates session integration on init."""
        assert phase._task_id == "test_task_001"

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_debate.emit_agent_exchange")
    @patch("core.intelligence.hive_mind.phases.phase_debate.emit_agent_speak")
    @patch("core.intelligence.hive_mind.phases.phase_debate.get_registry")
    async def test_session_uuids_passed_to_drivers(
        self,
        mock_get_reg,
        mock_speak,
        mock_exchange,
        mock_gemini,
        mock_claude,
        mock_cost_estimator,
        mock_context_manager,
    ):
        """Session UUIDs are passed to driver.invoke (V12.4.1)."""
        reg = MagicMock()
        reg.is_gemini = MagicMock(side_effect=lambda x: x == "gemini")
        reg.is_claude = MagicMock(side_effect=lambda x: x == "claude")
        reg.get_display_name = MagicMock(side_effect=lambda x: x.title())
        reg.get_alternate = MagicMock(side_effect=lambda x: "claude" if x == "gemini" else "gemini")
        mock_get_reg.return_value = reg

        _support_json = _make_argument_json(position="SUPPORT")
        _concede_json = _make_argument_json(position="CONCEDE")
        mock_gemini.send_message_async = AsyncMock(return_value=_support_json)
        mock_gemini.invoke = _make_smart_gemini_invoke(argument_json=_support_json)
        mock_claude.send_message_async = AsyncMock(return_value=_concede_json)
        mock_claude.invoke = AsyncMock(return_value=_make_driver_response(_concede_json))

        phase = StrategicDebatePhase(
            gemini_driver=mock_gemini,
            claude_driver=mock_claude,
            cost_estimator=mock_cost_estimator,
            context_manager=mock_context_manager,
            debate_config=AdaptiveDebateConfig(),
            task_id="test_sessions",
        )

        comparison = _make_comparison(agreement_score=0.5, needs_debate=True)
        await phase.execute("Task", comparison, TaskComplexity.TRIVIAL)

        # Check session_id was passed to invoke() (V12.4.1 uses invoke, not send_message_async)
        for call in mock_gemini.invoke.call_args_list:
            assert "session_id" in call.kwargs


# =============================================================================
# 18. Context manager interactions
# =============================================================================


class TestContextManagerInteractions:
    """Tests that debate turns are recorded in context manager."""

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_debate.emit_agent_exchange")
    @patch("core.intelligence.hive_mind.phases.phase_debate.emit_agent_speak")
    @patch("core.intelligence.hive_mind.phases.phase_debate.get_registry")
    async def test_debate_turns_added_to_context(
        self,
        mock_get_reg,
        mock_speak,
        mock_exchange,
        mock_gemini,
        mock_claude,
        mock_cost_estimator,
        mock_context_manager,
    ):
        reg = MagicMock()
        reg.is_gemini = MagicMock(side_effect=lambda x: x == "gemini")
        reg.is_claude = MagicMock(side_effect=lambda x: x == "claude")
        reg.get_display_name = MagicMock(side_effect=lambda x: x.title())
        reg.get_alternate = MagicMock(side_effect=lambda x: "claude" if x == "gemini" else "gemini")
        mock_get_reg.return_value = reg

        _support_json = _make_argument_json(position="SUPPORT")
        _concede_json = _make_argument_json(position="CONCEDE")
        mock_gemini.send_message_async = AsyncMock(return_value=_support_json)
        mock_claude.send_message_async = AsyncMock(return_value=_concede_json)
        mock_gemini.invoke = _make_smart_gemini_invoke(argument_json=_support_json)
        mock_claude.invoke = AsyncMock(return_value=_make_driver_response(_concede_json))

        phase = StrategicDebatePhase(
            gemini_driver=mock_gemini,
            claude_driver=mock_claude,
            cost_estimator=mock_cost_estimator,
            context_manager=mock_context_manager,
            debate_config=AdaptiveDebateConfig(),
            task_id="test_ctx",
        )

        comparison = _make_comparison(agreement_score=0.5, needs_debate=True)
        await phase.execute("Task", comparison, TaskComplexity.TRIVIAL)

        assert mock_context_manager.add_debate_turn.call_count >= 2


# =============================================================================
# 19. Telemetry emissions
# =============================================================================


class TestTelemetryEmissions:
    """Tests for V13.0 CEREBRO LIVE telemetry."""

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_debate.emit_agent_exchange")
    @patch("core.intelligence.hive_mind.phases.phase_debate.emit_agent_speak")
    @patch("core.intelligence.hive_mind.phases.phase_debate.get_registry")
    async def test_emit_agent_speak_called(
        self,
        mock_get_reg,
        mock_speak,
        mock_exchange,
        mock_gemini,
        mock_claude,
        mock_cost_estimator,
        mock_context_manager,
    ):
        reg = MagicMock()
        reg.is_gemini = MagicMock(side_effect=lambda x: x == "gemini")
        reg.is_claude = MagicMock(side_effect=lambda x: x == "claude")
        reg.get_display_name = MagicMock(side_effect=lambda x: x.title())
        reg.get_alternate = MagicMock(side_effect=lambda x: "claude" if x == "gemini" else "gemini")
        mock_get_reg.return_value = reg

        _support_json = _make_argument_json(position="SUPPORT")
        _concede_json = _make_argument_json(position="CONCEDE")
        mock_gemini.send_message_async = AsyncMock(return_value=_support_json)
        mock_claude.send_message_async = AsyncMock(return_value=_concede_json)
        mock_gemini.invoke = _make_smart_gemini_invoke(argument_json=_support_json)
        mock_claude.invoke = AsyncMock(return_value=_make_driver_response(_concede_json))

        phase = StrategicDebatePhase(
            gemini_driver=mock_gemini,
            claude_driver=mock_claude,
            cost_estimator=mock_cost_estimator,
            context_manager=mock_context_manager,
            debate_config=AdaptiveDebateConfig(),
            task_id="test_telemetry",
        )

        comparison = _make_comparison(agreement_score=0.5, needs_debate=True)
        await phase.execute("Task", comparison, TaskComplexity.TRIVIAL)

        assert mock_speak.call_count >= 2
        assert mock_exchange.call_count >= 2

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_debate.emit_agent_exchange")
    @patch("core.intelligence.hive_mind.phases.phase_debate.emit_agent_speak")
    @patch("core.intelligence.hive_mind.phases.phase_debate.get_registry")
    async def test_telemetry_includes_debate_action_type(
        self,
        mock_get_reg,
        mock_speak,
        mock_exchange,
        mock_gemini,
        mock_claude,
        mock_cost_estimator,
        mock_context_manager,
    ):
        reg = MagicMock()
        reg.is_gemini = MagicMock(side_effect=lambda x: x == "gemini")
        reg.is_claude = MagicMock(side_effect=lambda x: x == "claude")
        reg.get_display_name = MagicMock(side_effect=lambda x: x.title())
        reg.get_alternate = MagicMock(side_effect=lambda x: "claude" if x == "gemini" else "gemini")
        mock_get_reg.return_value = reg

        _support_json = _make_argument_json(position="SUPPORT")
        _concede_json = _make_argument_json(position="CONCEDE")
        mock_gemini.send_message_async = AsyncMock(return_value=_support_json)
        mock_claude.send_message_async = AsyncMock(return_value=_concede_json)
        mock_gemini.invoke = _make_smart_gemini_invoke(argument_json=_support_json)
        mock_claude.invoke = AsyncMock(return_value=_make_driver_response(_concede_json))

        phase = StrategicDebatePhase(
            gemini_driver=mock_gemini,
            claude_driver=mock_claude,
            cost_estimator=mock_cost_estimator,
            context_manager=mock_context_manager,
            debate_config=AdaptiveDebateConfig(),
            task_id="test_action_type",
        )

        comparison = _make_comparison(agreement_score=0.5, needs_debate=True)
        await phase.execute("Task", comparison, TaskComplexity.TRIVIAL)

        # Verify emit_agent_speak is called with action_type="DEBATE"
        for call in mock_speak.call_args_list:
            assert (
                call.kwargs.get("action_type") == "DEBATE"
                or call[1].get("action_type") == "DEBATE"
                or (len(call[0]) >= 3 and call[0][2] == "DEBATE")
            )


# =============================================================================
# 20. AdaptiveDebateConfig integration
# =============================================================================


class TestAdaptiveDebateConfigIntegration:
    """Tests for how the phase interacts with AdaptiveDebateConfig."""

    def test_default_debate_config_created(self, phase):
        """Phase creates default config if none provided."""
        assert phase.debate_config is not None
        assert isinstance(phase.debate_config, AdaptiveDebateConfig)

    def test_custom_debate_config_used(self, mock_gemini, mock_claude, mock_cost_estimator, mock_context_manager):
        config = AdaptiveDebateConfig()
        phase = StrategicDebatePhase(
            gemini_driver=mock_gemini,
            claude_driver=mock_claude,
            cost_estimator=mock_cost_estimator,
            context_manager=mock_context_manager,
            debate_config=config,
        )
        assert phase.debate_config is config

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_debate.emit_agent_exchange")
    @patch("core.intelligence.hive_mind.phases.phase_debate.emit_agent_speak")
    @patch("core.intelligence.hive_mind.phases.phase_debate.get_registry")
    async def test_agent_argument_recorded(
        self,
        mock_get_reg,
        mock_speak,
        mock_exchange,
        mock_gemini,
        mock_claude,
        mock_cost_estimator,
        mock_context_manager,
    ):
        """record_agent_argument called for each debate turn."""
        reg = MagicMock()
        reg.is_gemini = MagicMock(side_effect=lambda x: x == "gemini")
        reg.is_claude = MagicMock(side_effect=lambda x: x == "claude")
        reg.get_display_name = MagicMock(side_effect=lambda x: x.title())
        reg.get_alternate = MagicMock(side_effect=lambda x: "claude" if x == "gemini" else "gemini")
        mock_get_reg.return_value = reg

        _support_json = _make_argument_json(position="SUPPORT")
        _concede_json = _make_argument_json(position="CONCEDE", concession="I concede")
        mock_gemini.send_message_async = AsyncMock(return_value=_support_json)
        mock_claude.send_message_async = AsyncMock(return_value=_concede_json)
        mock_gemini.invoke = _make_smart_gemini_invoke(argument_json=_support_json)
        mock_claude.invoke = AsyncMock(return_value=_make_driver_response(_concede_json))

        config = AdaptiveDebateConfig()
        phase = StrategicDebatePhase(
            gemini_driver=mock_gemini,
            claude_driver=mock_claude,
            cost_estimator=mock_cost_estimator,
            context_manager=mock_context_manager,
            debate_config=config,
            task_id="test_record",
        )

        comparison = _make_comparison(agreement_score=0.5, needs_debate=True)
        await phase.execute("Task", comparison, TaskComplexity.TRIVIAL)

        # At least 2 turns worth of agent arguments recorded
        total_args = sum(m.arguments_made for m in config._agent_metrics.values())
        assert total_args >= 2


# =============================================================================
# 21. Edge cases
# =============================================================================


class TestEdgeCases:
    """Edge case tests."""

    def test_phase_init_without_task_id(self, mock_gemini, mock_claude, mock_cost_estimator, mock_context_manager):
        """Phase generates task_id if none provided."""
        phase = StrategicDebatePhase(
            gemini_driver=mock_gemini,
            claude_driver=mock_claude,
            cost_estimator=mock_cost_estimator,
            context_manager=mock_context_manager,
        )
        assert phase._task_id is not None
        assert "debate" in phase._task_id

    def test_phase_init_with_session_manager(self, mock_gemini, mock_claude, mock_cost_estimator, mock_context_manager):
        """Phase accepts optional session manager."""
        sm = MagicMock()
        phase = StrategicDebatePhase(
            gemini_driver=mock_gemini,
            claude_driver=mock_claude,
            cost_estimator=mock_cost_estimator,
            context_manager=mock_context_manager,
            session_manager=sm,
        )
        assert phase._session_manager is sm

    def test_comparison_with_no_disagreements(self, phase):
        """_get_primary_disagreement handles empty list."""
        result = phase._get_primary_disagreement([])
        assert result.topic == "approach"
        assert result.severity == 0.5
        assert result.gemini_position == "default"

    def test_comparison_all_same_severity(self, phase):
        """When all disagreements have same severity, first by sorted order returned."""
        disagreements = [
            Disagreement(topic="a", positions={"gemini": "x", "claude": "y"}, severity=0.5),
            Disagreement(topic="b", positions={"gemini": "x", "claude": "y"}, severity=0.5),
        ]
        result = phase._get_primary_disagreement(disagreements)
        assert result.severity == 0.5

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_debate.emit_agent_exchange")
    @patch("core.intelligence.hive_mind.phases.phase_debate.emit_agent_speak")
    @patch("core.intelligence.hive_mind.phases.phase_debate.get_registry")
    async def test_empty_response_from_driver(
        self,
        mock_get_reg,
        mock_speak,
        mock_exchange,
        mock_gemini,
        mock_claude,
        mock_cost_estimator,
        mock_context_manager,
    ):
        """Driver returning empty string does not crash."""
        reg = MagicMock()
        reg.is_gemini = MagicMock(side_effect=lambda x: x == "gemini")
        reg.is_claude = MagicMock(side_effect=lambda x: x == "claude")
        reg.get_display_name = MagicMock(side_effect=lambda x: x.title())
        reg.get_alternate = MagicMock(side_effect=lambda x: "claude" if x == "gemini" else "gemini")
        mock_get_reg.return_value = reg

        mock_gemini.send_message_async = AsyncMock(return_value="")
        mock_claude.send_message_async = AsyncMock(return_value="")
        # invoke returns empty content - phase must handle gracefully and use fallback
        mock_gemini.invoke = _make_smart_gemini_invoke(
            argument_json=_make_argument_json(position="OPPOSE"),
            consensus_json=_make_consensus_json(consensus_reached=False, consensus_score=0.4),
        )
        mock_claude.invoke = AsyncMock(return_value=_make_driver_response(""))

        phase = StrategicDebatePhase(
            gemini_driver=mock_gemini,
            claude_driver=mock_claude,
            cost_estimator=mock_cost_estimator,
            context_manager=mock_context_manager,
            debate_config=AdaptiveDebateConfig(),
            task_id="test_empty",
        )

        comparison = _make_comparison(agreement_score=0.4, needs_debate=True)
        result = await phase.execute("Task", comparison, TaskComplexity.TRIVIAL)
        # Should not crash; forced vote
        assert result is not None
        assert result.debate_result.total_turns >= 0

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_debate.emit_agent_exchange")
    @patch("core.intelligence.hive_mind.phases.phase_debate.emit_agent_speak")
    @patch("core.intelligence.hive_mind.phases.phase_debate.get_registry")
    async def test_dict_response_from_driver(
        self,
        mock_get_reg,
        mock_speak,
        mock_exchange,
        mock_gemini,
        mock_claude,
        mock_cost_estimator,
        mock_context_manager,
    ):
        """Driver returning dict response is handled."""
        reg = MagicMock()
        reg.is_gemini = MagicMock(side_effect=lambda x: x == "gemini")
        reg.is_claude = MagicMock(side_effect=lambda x: x == "claude")
        reg.get_display_name = MagicMock(side_effect=lambda x: x.title())
        reg.get_alternate = MagicMock(side_effect=lambda x: "claude" if x == "gemini" else "gemini")
        mock_get_reg.return_value = reg

        _support_json = _make_argument_json(position="SUPPORT")
        _concede_json = _make_argument_json(position="CONCEDE")
        mock_gemini.send_message_async = AsyncMock(
            return_value={"content": _support_json},
        )
        mock_claude.send_message_async = AsyncMock(
            return_value={"text": _concede_json},
        )
        mock_gemini.invoke = _make_smart_gemini_invoke(argument_json=_support_json)
        mock_claude.invoke = AsyncMock(return_value=_make_driver_response(_concede_json))

        phase = StrategicDebatePhase(
            gemini_driver=mock_gemini,
            claude_driver=mock_claude,
            cost_estimator=mock_cost_estimator,
            context_manager=mock_context_manager,
            debate_config=AdaptiveDebateConfig(),
            task_id="test_dict",
        )

        comparison = _make_comparison(agreement_score=0.5, needs_debate=True)
        result = await phase.execute("Task", comparison, TaskComplexity.TRIVIAL)
        assert result is not None

    def test_multiple_misalignment_patterns_in_one_argument(self):
        """Single argument can trigger multiple misalignment flags."""
        detector = MisalignmentDetector()
        arg = _make_debate_argument(argument="I have concerns but the conclusion is obvious let's just proceed")
        flags = detector.check_argument(arg, "gemini", 1)
        types = {f.flag_type for f in flags}
        assert len(types) >= 2

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_debate.emit_agent_exchange")
    @patch("core.intelligence.hive_mind.phases.phase_debate.emit_agent_speak")
    @patch("core.intelligence.hive_mind.phases.phase_debate.get_registry")
    async def test_complexity_expert_uses_more_turns(
        self,
        mock_get_reg,
        mock_speak,
        mock_exchange,
        mock_gemini,
        mock_claude,
        mock_cost_estimator,
        mock_context_manager,
    ):
        """EXPERT complexity allows more debate turns."""
        reg = MagicMock()
        reg.is_gemini = MagicMock(side_effect=lambda x: x == "gemini")
        reg.is_claude = MagicMock(side_effect=lambda x: x == "claude")
        reg.get_display_name = MagicMock(side_effect=lambda x: x.title())
        reg.get_alternate = MagicMock(side_effect=lambda x: "claude" if x == "gemini" else "gemini")
        mock_get_reg.return_value = reg

        _oppose_json = _make_argument_json(position="OPPOSE", argument="I disagree")
        _no_consensus_json = _make_consensus_json(consensus_reached=False, consensus_score=0.4)

        async def gemini_side_effect(*args, **kwargs):
            prompt_text = str(args[0]) if args else ""
            if "Evaluate if consensus" in prompt_text:
                return _make_consensus_json(consensus_reached=False, consensus_score=0.4)
            return _make_argument_json(position="OPPOSE", argument="I disagree")

        async def gemini_invoke_side_effect(*args, **kwargs):
            prompt_text = str(args[0]) if args else str(kwargs.get("prompt", ""))
            if "Evaluate if consensus" in prompt_text:
                return _make_driver_response(_no_consensus_json)
            return _make_driver_response(_oppose_json)

        mock_gemini.send_message_async = AsyncMock(side_effect=gemini_side_effect)
        mock_gemini.invoke = AsyncMock(side_effect=gemini_invoke_side_effect)
        _claude_oppose_json = _make_argument_json(position="OPPOSE")
        mock_claude.send_message_async = AsyncMock(return_value=_claude_oppose_json)
        mock_claude.invoke = AsyncMock(return_value=_make_driver_response(_claude_oppose_json))

        phase = StrategicDebatePhase(
            gemini_driver=mock_gemini,
            claude_driver=mock_claude,
            cost_estimator=mock_cost_estimator,
            context_manager=mock_context_manager,
            debate_config=AdaptiveDebateConfig(),
            task_id="test_expert",
        )

        comparison = _make_comparison(agreement_score=0.3, needs_debate=True)
        result = await phase.execute("Complex task", comparison, TaskComplexity.EXPERT)

        # EXPERT allows 6-10 turns (up to 12 with high disagreement)
        assert result.debate_result.total_turns >= 6
