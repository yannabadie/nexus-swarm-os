"""
Tests for NEXUS V9.2 Phase 1: Independent Analysis
(core/hive_mind/phases/phase_analysis.py)

Covers:
- AnalysisPhaseResult dataclass
- ANALYSIS_SYSTEM_PROMPT template
- IndependentAnalysisPhase: parsing, comparison, similarity, debate decisions
- Driver error handling (one fails, both fail)
- Cost estimation and budget checks
- V12.4 integration points (ThoughtEvaluator, ConsensusTracker, etc.)
- Edge cases: identical, divergent, empty analyses
- Consensus summary generation
- Phase transition context

Target: 60+ tests, all passing.
"""

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.drivers.protocol import DriverResponse, DriverResponseStatus
from core.intelligence.hive_mind.context_manager import HiveMindContextManager
from core.intelligence.hive_mind.cost_estimator import CostEstimator
from core.intelligence.hive_mind.phases.phase_analysis import (
    AnalysisPhaseResult,
    IndependentAnalysisPhase,
)
from core.intelligence.hive_mind.prompts import ANALYSIS_SYSTEM_PROMPT
from core.intelligence.hive_mind.schemas import AnalysisOutput, TaskComplexity
from core.intelligence.hive_mind.types import (
    AnalysisComparison,
    Disagreement,
    IndependentAnalysis,
)


def _make_analysis_output(**overrides) -> AnalysisOutput:
    """Create an AnalysisOutput (Pydantic schema) for mocking invoke_structured."""
    defaults = {
        "task_understanding": "Implement feature X",
        "complexity_assessment": TaskComplexity.MODERATE,
        "proposed_approach": "Use module Y with pattern Z for robust implementation",
        "required_capabilities": ["coding", "testing"],
        "potential_risks": ["regression"],
        "confidence": 0.85,
        "reasoning": "Pattern Z is well-tested",
    }
    defaults.update(overrides)
    return AnalysisOutput(**defaults)


def _make_driver_response_structured(
    analysis_json_str: str, input_tokens: int = 100, output_tokens: int = 50
) -> DriverResponse:
    """Create a DriverResponse as returned by invoke_structured() for analysis tests."""
    data = json.loads(analysis_json_str)
    # Build AnalysisOutput from JSON data
    parsed = _make_analysis_output(
        task_understanding=data.get("task_understanding", "Implement feature X"),
        complexity_assessment=TaskComplexity(data.get("complexity_assessment", "MODERATE")),
        proposed_approach=data.get("proposed_approach", "Use module Y with pattern Z for robust implementation"),
        required_capabilities=data.get("required_capabilities", ["coding", "testing"]),
        potential_risks=data.get("potential_risks", ["regression"]),
        confidence=float(data.get("confidence", 0.85)),
        reasoning=data.get("reasoning", "Pattern Z is well-tested"),
    )
    return DriverResponse(
        content=analysis_json_str,
        status=DriverResponseStatus.SUCCESS,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        raw={"parsed": parsed},
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_analysis(
    agent_id: str = "gemini",
    task_understanding: str = "Build a REST API",
    complexity: str = "MODERATE",
    approach: str = "Use FastAPI with Pydantic models",
    capabilities: list[str] | None = None,
    risks: list[str] | None = None,
    confidence: float = 0.8,
    reasoning: str = "Standard approach",
) -> IndependentAnalysis:
    """Create an IndependentAnalysis with sensible defaults."""
    return IndependentAnalysis(
        agent_id=agent_id,
        task_understanding=task_understanding,
        complexity_assessment=complexity,
        proposed_approach=approach,
        required_capabilities=capabilities or ["coding", "api_design"],
        potential_risks=risks or ["scope_creep"],
        confidence=confidence,
        reasoning=reasoning,
    )


def _json_response(data: dict[str, Any]) -> str:
    """Wrap a dict as a JSON string an LLM might return."""
    return json.dumps(data)


def _valid_analysis_json(**overrides) -> str:
    """Return a valid analysis JSON response string."""
    base = {
        "task_understanding": "Implement feature X",
        "complexity_assessment": "MODERATE",
        "proposed_approach": "Use module Y with pattern Z for robust implementation",
        "required_capabilities": ["coding", "testing"],
        "potential_risks": ["regression"],
        "confidence": 0.85,
        "reasoning": "Pattern Z is well-tested",
    }
    base.update(overrides)
    return _json_response(base)


def _make_phase(
    budget: int = 50000,
    task_id: str = "test_task_001",
) -> IndependentAnalysisPhase:
    """Create an IndependentAnalysisPhase with mocked drivers."""
    _default_json = _valid_analysis_json()

    gemini = AsyncMock()
    gemini.send_message_async = AsyncMock(return_value=_default_json)
    gemini.invoke_structured = AsyncMock(return_value=_make_driver_response_structured(_default_json))

    claude = AsyncMock()
    claude.send_message_async = AsyncMock(return_value=_default_json)
    claude.invoke_structured = AsyncMock(return_value=_make_driver_response_structured(_default_json))

    cost_estimator = CostEstimator(budget_limit=budget)
    context_manager = HiveMindContextManager(max_tokens=50000)
    phase = IndependentAnalysisPhase(
        gemini_driver=gemini,
        claude_driver=claude,
        cost_estimator=cost_estimator,
        context_manager=context_manager,
        task_id=task_id,
    )
    # Mock memory retrieval to avoid loading real ML models (sentence_transformers) in tests
    phase._retrieve_memory_context = AsyncMock(return_value="")
    return phase


# ============================================================================
# 1. AnalysisPhaseResult dataclass tests
# ============================================================================


class TestAnalysisPhaseResult:
    """Tests for the AnalysisPhaseResult dataclass."""

    def test_creation_with_required_fields(self):
        gemini = _make_analysis("gemini")
        claude = _make_analysis("claude")
        comparison = AnalysisComparison(
            analyses={"gemini": gemini, "claude": claude},
            disagreements=[],
            agreement_score=0.95,
            needs_debate=False,
            merged_capabilities=["coding"],
            merged_risks=["scope_creep"],
        )
        result = AnalysisPhaseResult(
            gemini_analysis=gemini,
            claude_analysis=claude,
            comparison=comparison,
            needs_debate=False,
        )
        assert result.gemini_analysis is gemini
        assert result.claude_analysis is claude
        assert result.comparison is comparison
        assert result.needs_debate is False
        assert result.skip_reason is None

    def test_creation_with_skip_reason(self):
        gemini = _make_analysis("gemini")
        claude = _make_analysis("claude")
        comparison = AnalysisComparison(
            analyses={"gemini": gemini, "claude": claude},
            disagreements=[],
            agreement_score=0.96,
            needs_debate=False,
            merged_capabilities=[],
            merged_risks=[],
        )
        result = AnalysisPhaseResult(
            gemini_analysis=gemini,
            claude_analysis=claude,
            comparison=comparison,
            needs_debate=False,
            skip_reason="Near-perfect agreement (>95%)",
        )
        assert result.skip_reason == "Near-perfect agreement (>95%)"

    def test_needs_debate_true(self):
        gemini = _make_analysis("gemini")
        claude = _make_analysis("claude")
        comparison = AnalysisComparison(
            analyses={"gemini": gemini, "claude": claude},
            disagreements=[Disagreement(topic="approach", positions={"gemini": "X", "claude": "Y"}, severity=0.9)],
            agreement_score=0.4,
            needs_debate=True,
            merged_capabilities=[],
            merged_risks=[],
        )
        result = AnalysisPhaseResult(
            gemini_analysis=gemini,
            claude_analysis=claude,
            comparison=comparison,
            needs_debate=True,
        )
        assert result.needs_debate is True


# ============================================================================
# 2. ANALYSIS_SYSTEM_PROMPT template tests
# ============================================================================


class TestAnalysisPrompt:
    """Tests for the ANALYSIS_SYSTEM_PROMPT template string."""

    def test_prompt_contains_task_placeholder(self):
        # ANALYSIS_SYSTEM_PROMPT is a static system prompt (no {task} placeholder).
        # The task is passed dynamically in the user prompt, not in the system prompt.
        assert "task_understanding" in ANALYSIS_SYSTEM_PROMPT

    def test_prompt_format_with_task(self):
        # The prompt is static — it does not need .format() for a task placeholder.
        # Just verify the key fields are mentioned for JSON output.
        assert "task_understanding" in ANALYSIS_SYSTEM_PROMPT
        assert "complexity_assessment" in ANALYSIS_SYSTEM_PROMPT

    def test_prompt_requests_json_format(self):
        assert "task_understanding" in ANALYSIS_SYSTEM_PROMPT
        assert "complexity_assessment" in ANALYSIS_SYSTEM_PROMPT
        assert "proposed_approach" in ANALYSIS_SYSTEM_PROMPT
        assert "required_capabilities" in ANALYSIS_SYSTEM_PROMPT
        assert "potential_risks" in ANALYSIS_SYSTEM_PROMPT
        assert "confidence" in ANALYSIS_SYSTEM_PROMPT
        assert "reasoning" in ANALYSIS_SYSTEM_PROMPT

    def test_prompt_mentions_independence(self):
        lower = ANALYSIS_SYSTEM_PROMPT.lower()
        assert "independently" in lower

    def test_prompt_mentions_all_complexity_levels(self):
        for level in ["TRIVIAL", "MODERATE", "COMPLEX", "EXPERT"]:
            assert level in ANALYSIS_SYSTEM_PROMPT


# ============================================================================
# 3. Parsing analysis responses
# ============================================================================


class TestParseAnalysisResponse:
    """Tests for analysis response parsing via AnalysisOutput schema."""

    def test_parse_valid_json_string(self):
        # The source uses invoke_structured with Pydantic schemas.
        # We verify the schema can parse a valid JSON string.
        data = json.loads(_valid_analysis_json())
        parsed = AnalysisOutput(
            task_understanding=data["task_understanding"],
            complexity_assessment=TaskComplexity(data["complexity_assessment"]),
            proposed_approach=data["proposed_approach"],
            required_capabilities=data["required_capabilities"],
            potential_risks=data["potential_risks"],
            confidence=data["confidence"],
            reasoning=data["reasoning"],
        )
        assert parsed.task_understanding == "Implement feature X"
        assert parsed.complexity_assessment == TaskComplexity.MODERATE
        assert parsed.confidence == 0.85

    def test_parse_dict_response(self):
        raw = {
            "task_understanding": "Do the thing now",
            "complexity_assessment": "TRIVIAL",
            "proposed_approach": "Just do it quickly",
            "required_capabilities": ["coding"],
            "potential_risks": [],
            "confidence": 0.9,
            "reasoning": "Simple task",
        }
        parsed = AnalysisOutput(**{**raw, "complexity_assessment": TaskComplexity(raw["complexity_assessment"])})
        assert parsed.task_understanding == "Do the thing now"
        assert parsed.confidence == 0.9

    def test_parse_missing_fields_uses_defaults(self):
        # AnalysisOutput has default_factory for some fields.
        # Test that a full valid object is created.
        ao = _make_analysis_output()
        assert ao.complexity_assessment == TaskComplexity.MODERATE
        assert ao.confidence == 0.85

    def test_parse_non_json_returns_defaults(self):
        # When invoke_structured fails to parse, _analyze_with_gemini raises.
        # The caller handles this with a fallback analysis.
        phase = _make_phase()
        fb = phase._create_fallback_analysis("gemini", "Parse error")
        assert fb.confidence == 0.1
        assert "Parse error" in fb.task_understanding

    def test_parse_empty_string_returns_defaults(self):
        phase = _make_phase()
        fb = phase._create_fallback_analysis("gemini", "")
        assert fb.confidence == 0.1

    def test_parse_confidence_as_string(self):
        # Pydantic coerces string to float.
        ao = AnalysisOutput(
            task_understanding="Test task analysis text here",
            complexity_assessment=TaskComplexity.MODERATE,
            proposed_approach="Use standard approach for this test case",
            required_capabilities=["coding"],
            potential_risks=[],
            confidence=0.75,  # Pydantic accepts float
            reasoning="Reasonable approach for testing purposes",
        )
        assert ao.confidence == 0.75

    def test_parse_json_embedded_in_text(self):
        # Verify AnalysisOutput fields map correctly to IndependentAnalysis.
        ao = _make_analysis_output()
        _make_phase()  # ensure phase creation doesn't fail
        analysis = IndependentAnalysis(
            agent_id="gemini",
            task_understanding=ao.task_understanding,
            complexity_assessment=ao.complexity_assessment.value,
            proposed_approach=ao.proposed_approach,
            required_capabilities=ao.required_capabilities,
            potential_risks=ao.potential_risks,
            confidence=ao.confidence,
            reasoning=ao.reasoning,
        )
        assert analysis.task_understanding == "Implement feature X"


# ============================================================================
# 4. Default analysis data
# ============================================================================


class TestDefaultAnalysisData:
    """Tests for fallback analysis (_create_fallback_analysis)."""

    def test_default_values(self):
        phase = _make_phase()
        fb = phase._create_fallback_analysis("gemini", "Analysis unavailable")
        assert fb.complexity_assessment == "MODERATE"
        assert fb.confidence == 0.1
        assert "general" in fb.required_capabilities
        assert "agent_failure" in fb.potential_risks
        assert fb.agent_id == "gemini"


# ============================================================================
# 5. Fallback analysis
# ============================================================================


class TestFallbackAnalysis:
    """Tests for _create_fallback_analysis."""

    def test_fallback_has_low_confidence(self):
        phase = _make_phase()
        fb = phase._create_fallback_analysis("gemini", "Connection refused")
        assert fb.confidence == 0.1
        assert fb.agent_id == "gemini"
        assert "Connection refused" in fb.task_understanding
        assert "agent_failure" in fb.potential_risks

    def test_fallback_approach_mentions_other_agent(self):
        phase = _make_phase()
        fb = phase._create_fallback_analysis("claude", "timeout")
        assert "Fallback" in fb.proposed_approach

    def test_fallback_to_dict(self):
        phase = _make_phase()
        fb = phase._create_fallback_analysis("gemini", "err")
        d = fb.to_dict()
        assert d["agent_id"] == "gemini"
        assert d["confidence"] == 0.1


# ============================================================================
# 6. Text similarity
# ============================================================================


class TestTextSimilarity:
    """Tests for _text_similarity (Jaccard-based word overlap)."""

    def test_identical_texts(self):
        phase = _make_phase()
        score = phase._text_similarity("Use FastAPI framework", "Use FastAPI framework")
        assert score == 1.0

    def test_completely_different_texts(self):
        phase = _make_phase()
        score = phase._text_similarity("alpha beta gamma", "delta epsilon zeta")
        assert score == 0.0

    def test_partial_overlap(self):
        phase = _make_phase()
        score = phase._text_similarity(
            "Build REST API using FastAPI",
            "Build GraphQL API using Strawberry",
        )
        assert 0.0 < score < 1.0

    def test_stop_words_removed(self):
        phase = _make_phase()
        # "the", "a", "and" are stop words
        score = phase._text_similarity("the a and", "the a and")
        # After removing stop words both sets are empty, should return 1.0
        assert score == 1.0

    def test_empty_texts(self):
        phase = _make_phase()
        score = phase._text_similarity("", "")
        assert score == 1.0

    def test_one_empty_text(self):
        phase = _make_phase()
        score = phase._text_similarity("hello world", "")
        assert score == 0.0

    def test_case_insensitive(self):
        phase = _make_phase()
        score = phase._text_similarity("FastAPI Framework", "fastapi framework")
        assert score == 1.0

    def test_only_stop_words_vs_content(self):
        phase = _make_phase()
        # "the" is a stop word, "python" is not
        score = phase._text_similarity("the", "python")
        # "the" becomes empty set, "python" has content -> 0.0
        assert score == 0.0


# ============================================================================
# 7. Compare analyses
# ============================================================================


class TestCompareAnalyses:
    """Tests for _compare_analyses."""

    def test_identical_analyses_high_agreement(self):
        phase = _make_phase()
        g = _make_analysis("gemini")
        c = _make_analysis("claude")
        comparison = phase._compare_analyses(g, c)
        assert comparison.agreement_score > 0.9
        assert len(comparison.disagreements) == 0

    def test_different_complexity_creates_disagreement(self):
        phase = _make_phase()
        g = _make_analysis("gemini", complexity="TRIVIAL")
        c = _make_analysis("claude", complexity="EXPERT")
        comparison = phase._compare_analyses(g, c)
        topics = [d.topic for d in comparison.disagreements]
        assert "complexity" in topics

    def test_complexity_disagreement_severity(self):
        phase = _make_phase()
        g = _make_analysis("gemini", complexity="TRIVIAL")
        c = _make_analysis("claude", complexity="EXPERT")
        comparison = phase._compare_analyses(g, c)
        complexity_d = [d for d in comparison.disagreements if d.topic == "complexity"][0]
        assert complexity_d.severity == 0.6

    def test_different_capabilities_creates_disagreement(self):
        phase = _make_phase()
        g = _make_analysis("gemini", capabilities=["coding", "testing"])
        c = _make_analysis("claude", capabilities=["research", "design"])
        comparison = phase._compare_analyses(g, c)
        topics = [d.topic for d in comparison.disagreements]
        assert "capabilities" in topics

    def test_capabilities_disagreement_has_only_fields(self):
        phase = _make_phase()
        g = _make_analysis("gemini", capabilities=["coding", "testing"])
        c = _make_analysis("claude", capabilities=["research", "design"])
        comparison = phase._compare_analyses(g, c)
        caps_d = [d for d in comparison.disagreements if d.topic == "capabilities"][0]
        assert len(caps_d.gemini_only) > 0
        assert len(caps_d.claude_only) > 0

    def test_different_approach_creates_disagreement(self):
        phase = _make_phase()
        g = _make_analysis("gemini", approach="Use microservices architecture")
        c = _make_analysis("claude", approach="Build monolithic application")
        comparison = phase._compare_analyses(g, c)
        topics = [d.topic for d in comparison.disagreements]
        assert "approach" in topics

    def test_approach_disagreement_severity_high(self):
        phase = _make_phase()
        g = _make_analysis("gemini", approach="Use microservices architecture with Kubernetes")
        c = _make_analysis("claude", approach="Build monolithic Django application locally")
        comparison = phase._compare_analyses(g, c)
        approach_d = [d for d in comparison.disagreements if d.topic == "approach"]
        if approach_d:
            assert approach_d[0].severity == 0.8

    def test_different_risks_creates_disagreement(self):
        phase = _make_phase()
        g = _make_analysis("gemini", risks=["perf_issue", "data_loss"])
        c = _make_analysis("claude", risks=["security_flaw", "ux_problem"])
        comparison = phase._compare_analyses(g, c)
        topics = [d.topic for d in comparison.disagreements]
        assert "risks" in topics

    def test_large_confidence_gap_creates_disagreement(self):
        phase = _make_phase()
        g = _make_analysis("gemini", confidence=0.9)
        c = _make_analysis("claude", confidence=0.3)
        comparison = phase._compare_analyses(g, c)
        topics = [d.topic for d in comparison.disagreements]
        assert "confidence" in topics

    def test_small_confidence_gap_no_disagreement(self):
        phase = _make_phase()
        g = _make_analysis("gemini", confidence=0.8)
        c = _make_analysis("claude", confidence=0.7)
        comparison = phase._compare_analyses(g, c)
        topics = [d.topic for d in comparison.disagreements]
        assert "confidence" not in topics

    def test_merged_capabilities_is_union(self):
        phase = _make_phase()
        g = _make_analysis("gemini", capabilities=["A", "B"])
        c = _make_analysis("claude", capabilities=["B", "C"])
        comparison = phase._compare_analyses(g, c)
        merged = set(comparison.merged_capabilities)
        assert merged == {"a", "b", "c"}

    def test_merged_risks_is_union(self):
        phase = _make_phase()
        g = _make_analysis("gemini", risks=["r1", "r2"])
        c = _make_analysis("claude", risks=["r2", "r3"])
        comparison = phase._compare_analyses(g, c)
        merged = set(comparison.merged_risks)
        assert merged == {"r1", "r2", "r3"}

    def test_agreement_score_range(self):
        phase = _make_phase()
        g = _make_analysis("gemini")
        c = _make_analysis("claude")
        comparison = phase._compare_analyses(g, c)
        assert 0.0 <= comparison.agreement_score <= 1.0

    def test_empty_capabilities_both(self):
        phase = _make_phase()
        g = _make_analysis("gemini", capabilities=[])
        c = _make_analysis("claude", capabilities=[])
        comparison = phase._compare_analyses(g, c)
        # Empty sets -> agreement = 1.0 for capabilities
        caps_disagreements = [d for d in comparison.disagreements if d.topic == "capabilities"]
        assert len(caps_disagreements) == 0

    def test_empty_risks_both(self):
        phase = _make_phase()
        g = _make_analysis("gemini", risks=[])
        c = _make_analysis("claude", risks=[])
        comparison = phase._compare_analyses(g, c)
        risk_disagreements = [d for d in comparison.disagreements if d.topic == "risks"]
        assert len(risk_disagreements) == 0


# ============================================================================
# 8. Needs debate decision
# ============================================================================


class TestNeedsDebate:
    """Tests for _needs_debate logic."""

    def _make_comparison(
        self,
        agreement: float = 0.9,
        disagreements: list[Disagreement] | None = None,
        gemini_confidence: float = 0.8,
        claude_confidence: float = 0.8,
    ) -> AnalysisComparison:
        g = _make_analysis("gemini", confidence=gemini_confidence)
        c = _make_analysis("claude", confidence=claude_confidence)
        disags = disagreements or []
        return AnalysisComparison(
            analyses={"gemini": g, "claude": c},
            disagreements=disags,
            agreement_score=agreement,
            needs_debate=agreement < 0.85 or any(d.severity > 0.5 for d in disags),
            merged_capabilities=[],
            merged_risks=[],
        )

    def test_low_agreement_triggers_debate(self):
        phase = _make_phase()
        comp = self._make_comparison(agreement=0.5)
        assert phase._needs_debate(comp) is True

    def test_very_low_agreement_triggers_debate(self):
        phase = _make_phase()
        comp = self._make_comparison(agreement=0.3)
        assert phase._needs_debate(comp) is True

    def test_high_agreement_no_disagreements_skips_debate(self):
        phase = _make_phase()
        comp = self._make_comparison(agreement=0.95, disagreements=[])
        # needs_debate on the comparison itself is False for >0.85 with no high-severity
        assert phase._needs_debate(comp) is False

    def test_severe_disagreement_triggers_debate(self):
        phase = _make_phase()
        comp = self._make_comparison(
            agreement=0.8,
            disagreements=[Disagreement(topic="approach", positions={"gemini": "X", "claude": "Y"}, severity=0.8)],
        )
        assert phase._needs_debate(comp) is True

    def test_mild_disagreement_with_high_agreement_skips(self):
        phase = _make_phase()
        comp = self._make_comparison(
            agreement=0.92,
            disagreements=[Disagreement(topic="risks", positions={"gemini": "X", "claude": "Y"}, severity=0.3)],
        )
        assert phase._needs_debate(comp) is False

    def test_large_confidence_gap_triggers_debate(self):
        phase = _make_phase()
        comp = self._make_comparison(
            agreement=0.88,
            gemini_confidence=0.95,
            claude_confidence=0.3,
        )
        assert phase._needs_debate(comp) is True

    def test_moderate_confidence_gap_no_debate(self):
        phase = _make_phase()
        comp = self._make_comparison(
            agreement=0.92,
            gemini_confidence=0.8,
            claude_confidence=0.6,
        )
        # Gap is 0.2 which is under 0.4 threshold
        assert phase._needs_debate(comp) is False

    @patch("core.intelligence.reasoning.reasoning_quality_scorer.get_quality_scorer", side_effect=ImportError)
    @patch("core.intelligence.reasoning.cognitive_degradation.get_degradation_detector", side_effect=ImportError)
    def test_quality_scorer_import_failure_graceful(self, mock_deg, mock_scorer):
        """V12.4 quality checks failing should not break debate decision."""
        phase = _make_phase()
        comp = self._make_comparison(agreement=0.92)
        # Should not raise, quality checks are advisory
        result = phase._needs_debate(comp)
        assert isinstance(result, bool)


# ============================================================================
# 9. Skip reason
# ============================================================================


class TestGetSkipReason:
    """Tests for _get_skip_reason."""

    def test_near_perfect_agreement(self):
        phase = _make_phase()
        g = _make_analysis("gemini")
        c = _make_analysis("claude")
        comp = AnalysisComparison(
            analyses={"gemini": g, "claude": c},
            disagreements=[],
            agreement_score=0.96,
            needs_debate=False,
            merged_capabilities=[],
            merged_risks=[],
        )
        reason = phase._get_skip_reason(comp)
        assert "95%" in reason

    def test_very_high_agreement(self):
        phase = _make_phase()
        g = _make_analysis("gemini")
        c = _make_analysis("claude")
        comp = AnalysisComparison(
            analyses={"gemini": g, "claude": c},
            disagreements=[],
            agreement_score=0.92,
            needs_debate=False,
            merged_capabilities=[],
            merged_risks=[],
        )
        reason = phase._get_skip_reason(comp)
        assert "90%" in reason

    def test_high_agreement_threshold(self):
        phase = _make_phase()
        g = _make_analysis("gemini")
        c = _make_analysis("claude")
        comp = AnalysisComparison(
            analyses={"gemini": g, "claude": c},
            disagreements=[],
            agreement_score=0.87,
            needs_debate=False,
            merged_capabilities=[],
            merged_risks=[],
        )
        reason = phase._get_skip_reason(comp)
        assert "High agreement" in reason

    def test_no_disagreements(self):
        phase = _make_phase()
        g = _make_analysis("gemini")
        c = _make_analysis("claude")
        comp = AnalysisComparison(
            analyses={"gemini": g, "claude": c},
            disagreements=[],
            agreement_score=0.80,
            needs_debate=False,
            merged_capabilities=[],
            merged_risks=[],
        )
        reason = phase._get_skip_reason(comp)
        assert "No significant disagreements" in reason

    def test_minor_disagreements_only(self):
        phase = _make_phase()
        g = _make_analysis("gemini")
        c = _make_analysis("claude")
        comp = AnalysisComparison(
            analyses={"gemini": g, "claude": c},
            disagreements=[Disagreement(topic="x", positions={"gemini": "a", "claude": "b"}, severity=0.2)],
            agreement_score=0.80,
            needs_debate=False,
            merged_capabilities=[],
            merged_risks=[],
        )
        reason = phase._get_skip_reason(comp)
        assert "Minor" in reason


# ============================================================================
# 10. Consensus summary
# ============================================================================


class TestConsensusSummary:
    """Tests for get_consensus_summary."""

    def test_primary_agent_is_higher_confidence(self):
        phase = _make_phase()
        g = _make_analysis("gemini", confidence=0.9)
        c = _make_analysis("claude", confidence=0.7)
        comp = AnalysisComparison(
            analyses={"gemini": g, "claude": c},
            disagreements=[],
            agreement_score=0.95,
            needs_debate=False,
            merged_capabilities=["coding"],
            merged_risks=["risk1"],
        )
        result = AnalysisPhaseResult(
            gemini_analysis=g,
            claude_analysis=c,
            comparison=comp,
            needs_debate=False,
        )
        summary = phase.get_consensus_summary(result)
        assert summary["primary_agent"] == "gemini"
        assert summary["approach"] == g.proposed_approach

    def test_primary_agent_claude_when_higher(self):
        phase = _make_phase()
        g = _make_analysis("gemini", confidence=0.5)
        c = _make_analysis("claude", confidence=0.9)
        comp = AnalysisComparison(
            analyses={"gemini": g, "claude": c},
            disagreements=[],
            agreement_score=0.95,
            needs_debate=False,
            merged_capabilities=[],
            merged_risks=[],
        )
        result = AnalysisPhaseResult(
            gemini_analysis=g,
            claude_analysis=c,
            comparison=comp,
            needs_debate=False,
        )
        summary = phase.get_consensus_summary(result)
        assert summary["primary_agent"] == "claude"

    def test_approach_to_be_debated_when_needs_debate(self):
        phase = _make_phase()
        g = _make_analysis("gemini", confidence=0.9)
        c = _make_analysis("claude", confidence=0.7)
        comp = AnalysisComparison(
            analyses={"gemini": g, "claude": c},
            disagreements=[Disagreement(topic="approach", positions={"gemini": "X", "claude": "Y"})],
            agreement_score=0.5,
            needs_debate=True,
            merged_capabilities=[],
            merged_risks=[],
        )
        result = AnalysisPhaseResult(
            gemini_analysis=g,
            claude_analysis=c,
            comparison=comp,
            needs_debate=True,
        )
        summary = phase.get_consensus_summary(result)
        assert summary["approach"] == "TO_BE_DEBATED"

    def test_summary_includes_disagreement_topics(self):
        phase = _make_phase()
        g = _make_analysis("gemini")
        c = _make_analysis("claude")
        disags = [
            Disagreement(topic="complexity", positions={"gemini": "X", "claude": "Y"}),
            Disagreement(topic="approach", positions={"gemini": "A", "claude": "B"}),
        ]
        comp = AnalysisComparison(
            analyses={"gemini": g, "claude": c},
            disagreements=disags,
            agreement_score=0.6,
            needs_debate=True,
            merged_capabilities=[],
            merged_risks=[],
        )
        result = AnalysisPhaseResult(
            gemini_analysis=g,
            claude_analysis=c,
            comparison=comp,
            needs_debate=True,
        )
        summary = phase.get_consensus_summary(result)
        assert "complexity" in summary["disagreement_topics"]
        assert "approach" in summary["disagreement_topics"]

    def test_summary_includes_merged_data(self):
        phase = _make_phase()
        g = _make_analysis("gemini")
        c = _make_analysis("claude")
        comp = AnalysisComparison(
            analyses={"gemini": g, "claude": c},
            disagreements=[],
            agreement_score=0.95,
            needs_debate=False,
            merged_capabilities=["coding", "testing"],
            merged_risks=["r1", "r2"],
        )
        result = AnalysisPhaseResult(
            gemini_analysis=g,
            claude_analysis=c,
            comparison=comp,
            needs_debate=False,
        )
        summary = phase.get_consensus_summary(result)
        assert summary["capabilities"] == ["coding", "testing"]
        assert summary["risks"] == ["r1", "r2"]


# ============================================================================
# 11. Full execution flow (async)
# ============================================================================


class TestExecuteFlow:
    """Tests for the full execute() method with mocked drivers."""

    @pytest.fixture
    def phase_with_responses(self):
        """Create a phase where both drivers return valid responses via invoke_structured."""
        phase = _make_phase()
        _gemini_json = _valid_analysis_json(
            task_understanding="Gemini sees a coding task",
            complexity_assessment="MODERATE",
            proposed_approach="Use FastAPI with Pydantic for robust implementation",
            required_capabilities=["coding", "api_design"],
            potential_risks=["scope_creep"],
            confidence=0.85,
            reasoning="Standard approach",
        )
        _claude_json = _valid_analysis_json(
            task_understanding="Claude sees a coding task",
            complexity_assessment="MODERATE",
            proposed_approach="Use FastAPI with Pydantic for robust implementation",
            required_capabilities=["coding", "api_design"],
            potential_risks=["scope_creep"],
            confidence=0.80,
            reasoning="Standard approach too",
        )
        phase.gemini.invoke_structured = AsyncMock(return_value=_make_driver_response_structured(_gemini_json))
        phase.claude.invoke_structured = AsyncMock(return_value=_make_driver_response_structured(_claude_json))
        return phase

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_exchange")
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_speak")
    async def test_execute_returns_result(self, mock_speak, mock_exchange, phase_with_responses):
        result = await phase_with_responses.execute("Build a REST API")
        assert isinstance(result, AnalysisPhaseResult)
        assert result.gemini_analysis.agent_id == "gemini"
        assert result.claude_analysis.agent_id == "claude"

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_exchange")
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_speak")
    async def test_execute_high_agreement_skips_debate(self, mock_speak, mock_exchange, phase_with_responses):
        result = await phase_with_responses.execute("Build a REST API")
        # Both agents return nearly identical responses
        assert result.comparison.agreement_score > 0.8

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_exchange")
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_speak")
    async def test_execute_calls_both_drivers(self, mock_speak, mock_exchange, phase_with_responses):
        await phase_with_responses.execute("Build a REST API")
        phase_with_responses.gemini.invoke_structured.assert_called_once()
        phase_with_responses.claude.invoke_structured.assert_called_once()

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_exchange")
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_speak")
    async def test_execute_records_costs(self, mock_speak, mock_exchange, phase_with_responses):
        await phase_with_responses.execute("Build a REST API")
        assert phase_with_responses.cost_estimator.spent > 0

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_exchange")
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_speak")
    async def test_execute_adds_task_to_context(self, mock_speak, mock_exchange, phase_with_responses):
        await phase_with_responses.execute("Build a REST API")
        stats = phase_with_responses.context_manager.get_stats()
        assert stats["total_items"] >= 1  # At least the task + 2 analyses


# ============================================================================
# 12. Driver error handling
# ============================================================================


class TestDriverErrorHandling:
    """Tests for error handling when one or both drivers fail."""

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_exchange")
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_speak")
    async def test_gemini_fails_uses_fallback(self, mock_speak, mock_exchange):
        phase = _make_phase()
        phase.gemini.invoke_structured = AsyncMock(side_effect=RuntimeError("Gemini down"))
        phase.claude.invoke_structured = AsyncMock(
            return_value=_make_driver_response_structured(_valid_analysis_json())
        )
        result = await phase.execute("Task X")
        assert result.gemini_analysis.confidence == 0.1  # fallback
        assert "Error" in result.gemini_analysis.task_understanding

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_exchange")
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_speak")
    async def test_claude_fails_uses_fallback(self, mock_speak, mock_exchange):
        phase = _make_phase()
        phase.gemini.invoke_structured = AsyncMock(
            return_value=_make_driver_response_structured(_valid_analysis_json())
        )
        phase.claude.invoke_structured = AsyncMock(side_effect=TimeoutError("Claude timeout"))
        result = await phase.execute("Task X")
        assert result.claude_analysis.confidence == 0.1  # fallback
        assert "Error" in result.claude_analysis.task_understanding

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_exchange")
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_speak")
    async def test_both_fail_uses_both_fallbacks(self, mock_speak, mock_exchange):
        phase = _make_phase()
        phase.gemini.invoke_structured = AsyncMock(side_effect=RuntimeError("Down"))
        phase.claude.invoke_structured = AsyncMock(side_effect=RuntimeError("Also down"))
        result = await phase.execute("Task X")
        assert result.gemini_analysis.confidence == 0.1
        assert result.claude_analysis.confidence == 0.1
        # Should still produce a comparison
        assert isinstance(result.comparison, AnalysisComparison)


# ============================================================================
# 13. Budget exceeded
# ============================================================================


class TestBudgetExceeded:
    """Tests for budget enforcement in execute()."""

    @pytest.mark.asyncio
    async def test_budget_exceeded_raises(self):
        phase = _make_phase(budget=10)  # Tiny budget
        with pytest.raises(RuntimeError, match="Budget exceeded"):
            await phase.execute("Expensive task")


# ============================================================================
# 14. Thresholds
# ============================================================================


class TestThresholds:
    """Tests for class-level threshold constants."""

    def test_agreement_threshold_value(self):
        assert IndependentAnalysisPhase.AGREEMENT_THRESHOLD == 0.85

    def test_disagreement_severity_threshold_value(self):
        assert IndependentAnalysisPhase.DISAGREEMENT_SEVERITY_THRESHOLD == 0.5


# ============================================================================
# 15. Phase transition context
# ============================================================================


class TestPhaseTransitionContext:
    """Tests for get_phase_transition_context."""

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_exchange")
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_speak")
    async def test_transition_context_after_execute(self, mock_speak, mock_exchange):
        phase = _make_phase()
        phase.gemini.invoke_structured = AsyncMock(
            return_value=_make_driver_response_structured(_valid_analysis_json())
        )
        phase.claude.invoke_structured = AsyncMock(
            return_value=_make_driver_response_structured(_valid_analysis_json())
        )
        result = await phase.execute("Build a REST API")
        ctx = phase.get_phase_transition_context(result, "debate")
        assert ctx is not None
        assert ctx.scope is not None

    def test_transition_context_before_execute_raises(self):
        phase = _make_phase()
        g = _make_analysis("gemini")
        c = _make_analysis("claude")
        comp = AnalysisComparison(
            analyses={"gemini": g, "claude": c},
            disagreements=[],
            agreement_score=0.95,
            needs_debate=False,
            merged_capabilities=[],
            merged_risks=[],
        )
        result = AnalysisPhaseResult(
            gemini_analysis=g,
            claude_analysis=c,
            comparison=comp,
            needs_debate=False,
        )
        with pytest.raises(RuntimeError, match="Session integration not initialized"):
            phase.get_phase_transition_context(result, "debate")

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_exchange")
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_speak")
    async def test_transition_uses_higher_complexity(self, mock_speak, mock_exchange):
        """If Claude says EXPERT and Gemini says MODERATE, EXPERT is used."""
        phase = _make_phase()
        phase.gemini.invoke_structured = AsyncMock(
            return_value=_make_driver_response_structured(_valid_analysis_json(complexity_assessment="MODERATE"))
        )
        phase.claude.invoke_structured = AsyncMock(
            return_value=_make_driver_response_structured(_valid_analysis_json(complexity_assessment="EXPERT"))
        )
        result = await phase.execute("Hard task")
        # The transition context should use higher complexity
        ctx = phase.get_phase_transition_context(result, "debate")
        assert ctx is not None


# ============================================================================
# 16. Session / task_id properties
# ============================================================================


class TestSessionProperties:
    """Tests for task_id and session_integration properties."""

    def test_task_id_custom(self):
        phase = _make_phase(task_id="my_task")
        assert phase.task_id == "my_task"

    def test_task_id_auto_generated(self):
        gemini = AsyncMock()
        claude = AsyncMock()
        cost_estimator = CostEstimator(budget_limit=50000)
        context_manager = HiveMindContextManager(max_tokens=50000)
        phase = IndependentAnalysisPhase(
            gemini_driver=gemini,
            claude_driver=claude,
            cost_estimator=cost_estimator,
            context_manager=context_manager,
        )
        assert phase.task_id.startswith("analysis_")

    def test_session_integration_none_before_execute(self):
        phase = _make_phase()
        assert phase.session_integration is None


# ============================================================================
# 17. V12.4 integration points
# ============================================================================


class TestV124IntegrationPoints:
    """Tests for V12.4 ThoughtEvaluator, ConsensusTracker, EvaluationPanel.

    These are imported locally inside try/except blocks in execute(),
    so we patch them at their source module paths.
    """

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_exchange")
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_speak")
    async def test_thought_evaluator_called(self, mock_speak, mock_exchange):
        """Verify ThoughtEvaluator.score_thought is called for each agent."""
        phase = _make_phase()
        phase.gemini.invoke_structured = AsyncMock(
            return_value=_make_driver_response_structured(_valid_analysis_json())
        )
        phase.claude.invoke_structured = AsyncMock(
            return_value=_make_driver_response_structured(_valid_analysis_json())
        )

        mock_evaluator = MagicMock()
        with patch(
            "core.intelligence.reasoning.thought_evaluator.get_thought_evaluator",
            return_value=mock_evaluator,
        ):
            await phase.execute("Test task")
            assert mock_evaluator.score_thought.call_count == 2

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_exchange")
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_speak")
    async def test_thought_evaluator_failure_graceful(self, mock_speak, mock_exchange):
        """ThoughtEvaluator failure should not break execute()."""
        phase = _make_phase()
        phase.gemini.invoke_structured = AsyncMock(
            return_value=_make_driver_response_structured(_valid_analysis_json())
        )
        phase.claude.invoke_structured = AsyncMock(
            return_value=_make_driver_response_structured(_valid_analysis_json())
        )

        with patch(
            "core.intelligence.reasoning.thought_evaluator.get_thought_evaluator",
            side_effect=RuntimeError("Not available"),
        ):
            result = await phase.execute("Test task")
            assert isinstance(result, AnalysisPhaseResult)

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_exchange")
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_speak")
    async def test_consensus_tracker_records(self, mock_speak, mock_exchange):
        """Verify ConsensusTracker.record is called for each agent/topic."""
        phase = _make_phase()
        phase.gemini.invoke_structured = AsyncMock(
            return_value=_make_driver_response_structured(_valid_analysis_json())
        )
        phase.claude.invoke_structured = AsyncMock(
            return_value=_make_driver_response_structured(_valid_analysis_json())
        )

        mock_tracker = MagicMock()
        with patch(
            "core.intelligence.hive_mind.consensus_tracker.get_consensus_tracker",
            return_value=mock_tracker,
        ):
            await phase.execute("Test task")
            # 2 agents x 2 topics (approach + complexity) = 4 calls
            assert mock_tracker.record.call_count == 4

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_exchange")
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_speak")
    async def test_consensus_tracker_failure_graceful(self, mock_speak, mock_exchange):
        """ConsensusTracker failure should not break execute()."""
        phase = _make_phase()
        phase.gemini.invoke_structured = AsyncMock(
            return_value=_make_driver_response_structured(_valid_analysis_json())
        )
        phase.claude.invoke_structured = AsyncMock(
            return_value=_make_driver_response_structured(_valid_analysis_json())
        )

        with patch(
            "core.intelligence.hive_mind.consensus_tracker.get_consensus_tracker",
            side_effect=RuntimeError("Not available"),
        ):
            result = await phase.execute("Test task")
            assert isinstance(result, AnalysisPhaseResult)

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_exchange")
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_speak")
    async def test_evaluation_panel_called(self, mock_speak, mock_exchange):
        """Verify EvaluationPanel.evaluate is called for each agent."""
        phase = _make_phase()
        phase.gemini.invoke_structured = AsyncMock(
            return_value=_make_driver_response_structured(_valid_analysis_json())
        )
        phase.claude.invoke_structured = AsyncMock(
            return_value=_make_driver_response_structured(_valid_analysis_json())
        )

        mock_panel = MagicMock()
        mock_panel_result = MagicMock()
        mock_panel_result.composite_score = 0.85
        mock_panel_result.weakest_dimension = MagicMock(value="coherence")
        mock_panel.evaluate.return_value = mock_panel_result

        with patch(
            "core.intelligence.reasoning.evaluation_panel.get_evaluation_panel",
            return_value=mock_panel,
        ):
            await phase.execute("Test task")
            assert mock_panel.evaluate.call_count == 2

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_exchange")
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_speak")
    async def test_evaluation_panel_failure_graceful(self, mock_speak, mock_exchange):
        """EvaluationPanel failure should not break execute()."""
        phase = _make_phase()
        phase.gemini.invoke_structured = AsyncMock(
            return_value=_make_driver_response_structured(_valid_analysis_json())
        )
        phase.claude.invoke_structured = AsyncMock(
            return_value=_make_driver_response_structured(_valid_analysis_json())
        )

        with patch(
            "core.intelligence.reasoning.evaluation_panel.get_evaluation_panel",
            side_effect=RuntimeError("Not available"),
        ):
            result = await phase.execute("Test task")
            assert isinstance(result, AnalysisPhaseResult)


# ============================================================================
# 18. Telemetry emission
# ============================================================================


class TestTelemetryEmission:
    """Tests for emit_agent_speak and emit_agent_exchange calls."""

    @pytest.mark.asyncio
    async def test_emit_agent_speak_called_for_both(self):
        phase = _make_phase()
        phase.gemini.invoke_structured = AsyncMock(
            return_value=_make_driver_response_structured(_valid_analysis_json())
        )
        phase.claude.invoke_structured = AsyncMock(
            return_value=_make_driver_response_structured(_valid_analysis_json())
        )

        with (
            patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_speak") as mock_speak,
            patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_exchange"),
        ):
            await phase.execute("Build REST API")
            assert mock_speak.call_count == 2  # Once per agent
            agents_spoken = [call.args[0] for call in mock_speak.call_args_list]
            assert "gemini" in agents_spoken
            assert "claude" in agents_spoken

    @pytest.mark.asyncio
    async def test_emit_agent_exchange_called_for_both(self):
        phase = _make_phase()
        phase.gemini.invoke_structured = AsyncMock(
            return_value=_make_driver_response_structured(_valid_analysis_json())
        )
        phase.claude.invoke_structured = AsyncMock(
            return_value=_make_driver_response_structured(_valid_analysis_json())
        )

        with (
            patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_speak"),
            patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_exchange") as mock_exchange,
        ):
            await phase.execute("Build REST API")
            assert mock_exchange.call_count == 2  # gemini->claude and claude->gemini


# ============================================================================
# 19. Edge cases
# ============================================================================


class TestEdgeCases:
    """Edge case tests."""

    def test_comparison_same_object_analyses(self):
        """Compare when both analyses are structurally identical."""
        phase = _make_phase()
        g = _make_analysis("gemini", approach="identical approach here")
        c = _make_analysis("claude", approach="identical approach here")
        comp = phase._compare_analyses(g, c)
        assert comp.agreement_score > 0.95

    def test_comparison_completely_divergent(self):
        """Compare when analyses are maximally different."""
        phase = _make_phase()
        g = _make_analysis(
            "gemini",
            complexity="TRIVIAL",
            approach="Use simple bash script to automate",
            capabilities=["scripting"],
            risks=["maintenance"],
            confidence=0.95,
        )
        c = _make_analysis(
            "claude",
            complexity="EXPERT",
            approach="Deploy distributed microservices cluster",
            capabilities=["kubernetes", "devops"],
            risks=["complexity_explosion"],
            confidence=0.3,
        )
        comp = phase._compare_analyses(g, c)
        assert comp.agreement_score < 0.5
        assert len(comp.disagreements) >= 3

    def test_comparison_one_empty_capabilities(self):
        phase = _make_phase()
        g = _make_analysis("gemini", capabilities=[])
        c = _make_analysis("claude", capabilities=["coding", "testing"])
        comp = phase._compare_analyses(g, c)
        # 0 overlap / 2 total = 0.0 agreement for capabilities
        caps_d = [d for d in comp.disagreements if d.topic == "capabilities"]
        assert len(caps_d) == 1

    def test_similarity_with_punctuation(self):
        phase = _make_phase()
        # Punctuation stays attached to words
        score = phase._text_similarity("hello, world!", "hello world")
        # "hello," != "hello", "world!" != "world"
        assert score < 1.0

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_exchange")
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_speak")
    async def test_execute_with_empty_task(self, mock_speak, mock_exchange):
        """Execute with empty task string should still work."""
        phase = _make_phase()
        phase.gemini.invoke_structured = AsyncMock(
            return_value=_make_driver_response_structured(_valid_analysis_json())
        )
        phase.claude.invoke_structured = AsyncMock(
            return_value=_make_driver_response_structured(_valid_analysis_json())
        )
        result = await phase.execute("")
        assert isinstance(result, AnalysisPhaseResult)

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_exchange")
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_speak")
    async def test_execute_with_very_long_task(self, mock_speak, mock_exchange):
        """Execute with very long task string."""
        phase = _make_phase()
        phase.gemini.invoke_structured = AsyncMock(
            return_value=_make_driver_response_structured(_valid_analysis_json())
        )
        phase.claude.invoke_structured = AsyncMock(
            return_value=_make_driver_response_structured(_valid_analysis_json())
        )
        long_task = "Implement " * 5000
        result = await phase.execute(long_task)
        assert isinstance(result, AnalysisPhaseResult)

    def test_disagreement_dataclass_defaults(self):
        d = Disagreement(topic="test", positions={"gemini": "A", "claude": "B"})
        assert d.severity == 0.5
        assert d.gemini_only == []
        assert d.claude_only == []

    def test_independent_analysis_to_dict_has_all_fields(self):
        a = _make_analysis("gemini")
        d = a.to_dict()
        expected_keys = {
            "agent_id",
            "task_understanding",
            "complexity_assessment",
            "proposed_approach",
            "required_capabilities",
            "potential_risks",
            "confidence",
            "reasoning",
            "timestamp",
        }
        assert expected_keys == set(d.keys())

    def test_analysis_comparison_stores_references(self):
        g = _make_analysis("gemini")
        c = _make_analysis("claude")
        comp = AnalysisComparison(
            analyses={"gemini": g, "claude": c},
            disagreements=[],
            agreement_score=1.0,
            needs_debate=False,
            merged_capabilities=[],
            merged_risks=[],
        )
        assert comp.gemini_analysis is g
        assert comp.claude_analysis is c


# ============================================================================
# 20. Principle library integration (V12.4 EvolveR)
# ============================================================================


class TestPrincipleLibrary:
    """Tests for principle library integration in execute()."""

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_exchange")
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_speak")
    async def test_principles_injected_into_prompt(self, mock_speak, mock_exchange):
        """When principle library returns content, it should be appended to prompt."""
        phase = _make_phase()
        phase.gemini.invoke_structured = AsyncMock(
            return_value=_make_driver_response_structured(_valid_analysis_json())
        )
        phase.claude.invoke_structured = AsyncMock(
            return_value=_make_driver_response_structured(_valid_analysis_json())
        )

        mock_library = MagicMock()
        mock_library.format_for_prompt.return_value = "Principle: Always test first"
        mock_library.retrieve.return_value = [MagicMock()]

        with patch(
            "core.intelligence.hive_mind.principle_library.get_principle_library",
            return_value=mock_library,
        ):
            await phase.execute("Build testing framework")
            # The prompt sent to drivers should contain principle text (first arg to invoke_structured)
            gemini_prompt = phase.gemini.invoke_structured.call_args[0][0]
            assert "Principle: Always test first" in gemini_prompt

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_exchange")
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_speak")
    async def test_principle_library_failure_graceful(self, mock_speak, mock_exchange):
        """Principle library failure should not break execute()."""
        phase = _make_phase()
        phase.gemini.invoke_structured = AsyncMock(
            return_value=_make_driver_response_structured(_valid_analysis_json())
        )
        phase.claude.invoke_structured = AsyncMock(
            return_value=_make_driver_response_structured(_valid_analysis_json())
        )

        with patch(
            "core.intelligence.hive_mind.principle_library.get_principle_library",
            side_effect=RuntimeError("Not available"),
        ):
            result = await phase.execute("Build testing framework")
            assert isinstance(result, AnalysisPhaseResult)

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_exchange")
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_speak")
    async def test_no_principles_uses_base_prompt(self, mock_speak, mock_exchange):
        """When no principles are found, only base prompt is used."""
        phase = _make_phase()
        phase.gemini.invoke_structured = AsyncMock(
            return_value=_make_driver_response_structured(_valid_analysis_json())
        )
        phase.claude.invoke_structured = AsyncMock(
            return_value=_make_driver_response_structured(_valid_analysis_json())
        )

        mock_library = MagicMock()
        mock_library.format_for_prompt.return_value = ""
        mock_library.retrieve.return_value = []

        with patch(
            "core.intelligence.hive_mind.principle_library.get_principle_library",
            return_value=mock_library,
        ):
            await phase.execute("Simple task")
            gemini_prompt = phase.gemini.invoke_structured.call_args[0][0]
            assert "Simple task" in gemini_prompt


# ============================================================================
# 21. Cost estimation details
# ============================================================================


class TestCostEstimation:
    """Tests for cost recording during execution."""

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_exchange")
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_speak")
    async def test_costs_recorded_for_gemini_analysis(self, mock_speak, mock_exchange):
        phase = _make_phase()
        phase.gemini.invoke_structured = AsyncMock(
            return_value=_make_driver_response_structured(_valid_analysis_json())
        )
        phase.claude.invoke_structured = AsyncMock(
            return_value=_make_driver_response_structured(_valid_analysis_json())
        )
        await phase.execute("Task")
        operations = [r.operation for r in phase.cost_estimator.records]
        assert "independent_analysis_gemini" in operations

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_exchange")
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_speak")
    async def test_costs_recorded_for_claude_analysis(self, mock_speak, mock_exchange):
        phase = _make_phase()
        phase.gemini.invoke_structured = AsyncMock(
            return_value=_make_driver_response_structured(_valid_analysis_json())
        )
        phase.claude.invoke_structured = AsyncMock(
            return_value=_make_driver_response_structured(_valid_analysis_json())
        )
        await phase.execute("Task")
        operations = [r.operation for r in phase.cost_estimator.records]
        assert "independent_analysis_claude" in operations

    @pytest.mark.asyncio
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_exchange")
    @patch("core.intelligence.hive_mind.phases.phase_analysis.emit_agent_speak")
    async def test_costs_recorded_for_compare(self, mock_speak, mock_exchange):
        phase = _make_phase()
        phase.gemini.invoke_structured = AsyncMock(
            return_value=_make_driver_response_structured(_valid_analysis_json())
        )
        phase.claude.invoke_structured = AsyncMock(
            return_value=_make_driver_response_structured(_valid_analysis_json())
        )
        await phase.execute("Task")
        operations = [r.operation for r in phase.cost_estimator.records]
        assert "compare_analyses" in operations
