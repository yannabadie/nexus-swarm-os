"""Tests for MAST Failure Taxonomy + MARS Triple-Pathway Reflection."""

from core.intelligence.hive_mind.failure_taxonomy import (
    FAILURE_TYPE_MAST_MAP,
    MAST_CATEGORIES,
    MAST_PATTERNS,
    MastCategory,
    MastClassification,
    MastClassifier,
    MastCode,
    TriplePathwayReflector,
    TriplePathwayResult,
    get_mast_classifier,
    get_triple_reflector,
    reset_failure_taxonomy,
)

# =============================================================================
# MastCode & Category Mapping
# =============================================================================


class TestMastCodeMapping:
    def test_all_codes_have_category(self):
        for code in MastCode:
            assert code in MAST_CATEGORIES

    def test_all_codes_have_patterns(self):
        for code in MastCode:
            assert code in MAST_PATTERNS
            assert len(MAST_PATTERNS[code]) > 0

    def test_system_design_codes(self):
        system_codes = [c for c, cat in MAST_CATEGORIES.items() if cat == MastCategory.SYSTEM_DESIGN]
        assert len(system_codes) == 5

    def test_inter_agent_codes(self):
        inter_codes = [c for c, cat in MAST_CATEGORIES.items() if cat == MastCategory.INTER_AGENT]
        assert len(inter_codes) == 6

    def test_task_verification_codes(self):
        tv_codes = [c for c, cat in MAST_CATEGORIES.items() if cat == MastCategory.TASK_VERIFICATION]
        assert len(tv_codes) == 3

    def test_total_14_codes(self):
        assert len(MastCode) == 14

    def test_failure_type_map_covers_all_types(self):
        expected_types = [
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
        ]
        for ft in expected_types:
            assert ft in FAILURE_TYPE_MAST_MAP


# =============================================================================
# MastClassification Dataclass
# =============================================================================


class TestMastClassification:
    def test_get_categories(self):
        mc = MastClassification(
            codes=[MastCode.STEP_REPETITION, MastCode.IGNORED_INPUT],
            primary_category=MastCategory.SYSTEM_DESIGN,
            confidence=0.5,
            evidence=["test"],
        )
        cats = mc.get_categories()
        assert MastCategory.SYSTEM_DESIGN in cats
        assert MastCategory.INTER_AGENT in cats

    def test_has_inter_agent_issues(self):
        mc = MastClassification(
            codes=[MastCode.IGNORED_INPUT],
            primary_category=MastCategory.INTER_AGENT,
            confidence=0.5,
            evidence=["test"],
        )
        assert mc.has_inter_agent_issues()

    def test_no_inter_agent_issues(self):
        mc = MastClassification(
            codes=[MastCode.STEP_REPETITION],
            primary_category=MastCategory.SYSTEM_DESIGN,
            confidence=0.5,
            evidence=["test"],
        )
        assert not mc.has_inter_agent_issues()

    def test_to_dict(self):
        mc = MastClassification(
            codes=[MastCode.CONTEXT_LOSS],
            primary_category=MastCategory.SYSTEM_DESIGN,
            confidence=0.75,
            evidence=["matched pattern"],
        )
        d = mc.to_dict()
        assert d["codes"] == ["context_loss"]
        assert d["primary_category"] == "system_design"
        assert d["confidence"] == 0.75
        assert "matched pattern" in d["evidence"]


# =============================================================================
# MastClassifier - Pattern Detection
# =============================================================================


class TestMastClassifierPatterns:
    def setup_method(self):
        self.classifier = MastClassifier()

    def test_detects_step_repetition(self):
        result = self.classifier.classify("Agent got stuck in a loop repeating the same action")
        codes = [c.value for c in result.codes]
        assert "step_repetition" in codes

    def test_detects_context_loss(self):
        result = self.classifier.classify("Agent forgot the previous conversation context lost")
        codes = [c.value for c in result.codes]
        assert "context_loss" in codes

    def test_detects_ignored_input(self):
        result = self.classifier.classify("Agent ignored the other agent's analysis")
        codes = [c.value for c in result.codes]
        assert "ignored_input" in codes

    def test_detects_premature_termination(self):
        result = self.classifier.classify("Task ended too early with incomplete results")
        codes = [c.value for c in result.codes]
        assert "premature_termination" in codes

    def test_detects_no_verification(self):
        result = self.classifier.classify("Output was unverified and skipped check entirely")
        codes = [c.value for c in result.codes]
        assert "no_verification" in codes

    def test_detects_task_derailment(self):
        result = self.classifier.classify("The agent went off track and derailed from the task")
        codes = [c.value for c in result.codes]
        assert "task_derailment" in codes

    def test_detects_reasoning_mismatch(self):
        result = self.classifier.classify("Agent reasoning was inconsistent with its actions")
        codes = [c.value for c in result.codes]
        assert "reasoning_mismatch" in codes

    def test_multiple_patterns(self):
        result = self.classifier.classify("Agent got stuck in a loop, ignored input, went off track")
        assert len(result.codes) >= 3


# =============================================================================
# MastClassifier - FailureType Mapping
# =============================================================================


class TestMastClassifierFailureType:
    def setup_method(self):
        self.classifier = MastClassifier()

    def test_timeout_maps_to_repetition_and_termination(self):
        result = self.classifier.classify("generic failure", failure_type="timeout")
        code_values = [c.value for c in result.codes]
        assert "step_repetition" in code_values
        assert "unaware_termination" in code_values

    def test_hallucination_maps_correctly(self):
        result = self.classifier.classify("generic failure", failure_type="hallucination")
        code_values = [c.value for c in result.codes]
        assert "reasoning_mismatch" in code_values
        assert "incorrect_verification" in code_values

    def test_context_lost_maps_correctly(self):
        result = self.classifier.classify("generic failure", failure_type="context_lost")
        code_values = [c.value for c in result.codes]
        assert "context_loss" in code_values
        assert "conversation_reset" in code_values

    def test_unknown_type_has_fallback(self):
        result = self.classifier.classify("generic failure", failure_type="unknown")
        code_values = [c.value for c in result.codes]
        assert "no_verification" in code_values

    def test_combined_pattern_and_type(self):
        result = self.classifier.classify("Agent got stuck in a loop", failure_type="timeout")
        # Should have both pattern match (step_repetition) and type map codes
        code_values = [c.value for c in result.codes]
        assert "step_repetition" in code_values


# =============================================================================
# MastClassifier - Agent Diagnoses
# =============================================================================


class TestMastClassifierDiagnoses:
    def setup_method(self):
        self.classifier = MastClassifier()

    def test_uses_agent_diagnoses(self):
        result = self.classifier.classify(
            "something happened",
            agent_diagnoses=["The agent ignored the user's request"],
        )
        code_values = [c.value for c in result.codes]
        assert "ignored_input" in code_values

    def test_multiple_diagnoses(self):
        result = self.classifier.classify(
            "some issue",
            agent_diagnoses=["stuck in a loop", "forgot context"],
        )
        code_values = [c.value for c in result.codes]
        assert "step_repetition" in code_values
        assert "context_loss" in code_values


# =============================================================================
# MastClassifier - Confidence & Category
# =============================================================================


class TestMastClassifierConfidence:
    def setup_method(self):
        self.classifier = MastClassifier()

    def test_confidence_scales_with_evidence(self):
        # More matches = higher confidence
        result_few = self.classifier.classify("generic failure", failure_type="unknown")
        result_many = self.classifier.classify(
            "Agent got stuck in a loop, ignored input, went off track, premature ending",
            failure_type="timeout",
        )
        assert result_many.confidence >= result_few.confidence

    def test_confidence_capped_at_one(self):
        result = self.classifier.classify(
            "stuck in loop ignored input off track premature unverified mismatch forgot context reset",
            failure_type="timeout",
        )
        assert result.confidence <= 1.0

    def test_primary_category_is_most_frequent(self):
        # Provide multiple inter-agent patterns
        result = self.classifier.classify("Agent ignored input, went off track, and disregarded feedback")
        assert result.primary_category == MastCategory.INTER_AGENT

    def test_fallback_when_no_patterns(self):
        result = self.classifier.classify("xyzzy gibberish")
        # Should fall back to NO_VERIFICATION
        assert MastCode.NO_VERIFICATION in result.codes


# =============================================================================
# TriplePathwayResult Dataclass
# =============================================================================


class TestTriplePathwayResult:
    def test_to_dict(self):
        r = TriplePathwayResult(
            principle="test principle",
            procedure="1. step one. 2. step two.",
            synthesis="do step one",
            failure_type="timeout",
            mast_codes=["step_repetition"],
        )
        d = r.to_dict()
        assert d["principle"] == "test principle"
        assert d["failure_type"] == "timeout"
        assert "step_repetition" in d["mast_codes"]

    def test_default_mast_codes(self):
        r = TriplePathwayResult(
            principle="p",
            procedure="proc",
            synthesis="s",
            failure_type="unknown",
        )
        assert r.mast_codes == []


# =============================================================================
# TriplePathwayReflector - Principle Extraction
# =============================================================================


class TestTriplePathwayPrinciple:
    def setup_method(self):
        self.reflector = TriplePathwayReflector()

    def test_timeout_principle(self):
        result = self.reflector.reflect("Timed out", "API too slow", failure_type="timeout")
        assert "timeout" in result.principle.lower()

    def test_hallucination_principle(self):
        result = self.reflector.reflect("Wrong output", "Made up facts", failure_type="hallucination")
        assert "verification" in result.principle.lower() or "trust" in result.principle.lower()

    def test_unknown_principle(self):
        result = self.reflector.reflect("???", "unknown error", failure_type="unknown")
        assert "unclear" in result.principle.lower() or "diagnostic" in result.principle.lower()

    def test_enriches_with_agent_ignored(self):
        result = self.reflector.reflect(
            "Agent ignored the other agent's work",
            "Collaboration failed",
            failure_type="strategy_wrong",
        )
        assert "agent" in result.principle.lower()

    def test_enriches_with_loop_detection(self):
        result = self.reflector.reflect(
            "Got stuck in a repeated loop",
            "Infinite loop",
            failure_type="timeout",
        )
        assert "loop" in result.principle.lower() or "repetition" in result.principle.lower()


# =============================================================================
# TriplePathwayReflector - Procedure
# =============================================================================


class TestTriplePathwayProcedure:
    def setup_method(self):
        self.reflector = TriplePathwayReflector()

    def test_timeout_procedure_has_steps(self):
        result = self.reflector.reflect("Timed out", "slow", failure_type="timeout")
        assert "1." in result.procedure
        assert "2." in result.procedure

    def test_tool_error_procedure(self):
        result = self.reflector.reflect("Tool failed", "bad input", failure_type="tool_error")
        assert "tool" in result.procedure.lower() or "input" in result.procedure.lower()

    def test_procedure_has_multiple_steps(self):
        result = self.reflector.reflect("error", "cause", failure_type="planning_error")
        steps = result.procedure.split(". ")
        assert len(steps) >= 3


# =============================================================================
# TriplePathwayReflector - Synthesis
# =============================================================================


class TestTriplePathwaySynthesis:
    def setup_method(self):
        self.reflector = TriplePathwayReflector()

    def test_synthesis_contains_root_principle(self):
        result = self.reflector.reflect("Timed out", "slow API", failure_type="timeout")
        assert "Root principle" in result.synthesis

    def test_synthesis_contains_immediate_action(self):
        result = self.reflector.reflect("error", "cause", failure_type="tool_error")
        assert "Immediate action" in result.synthesis

    def test_synthesis_references_procedure_steps(self):
        result = self.reflector.reflect("error", "cause", failure_type="budget_exceeded")
        assert "step procedure" in result.synthesis

    def test_mast_codes_passed_through(self):
        result = self.reflector.reflect(
            "error",
            "cause",
            failure_type="timeout",
            mast_codes=["step_repetition", "unaware_termination"],
        )
        assert result.mast_codes == ["step_repetition", "unaware_termination"]

    def test_failure_type_stored(self):
        result = self.reflector.reflect("error", "cause", failure_type="hallucination")
        assert result.failure_type == "hallucination"


# =============================================================================
# All FailureTypes Covered
# =============================================================================


class TestAllFailureTypes:
    def setup_method(self):
        self.reflector = TriplePathwayReflector()

    def test_all_types_have_principle(self):
        for ft in [
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
        ]:
            result = self.reflector.reflect("failure", "cause", failure_type=ft)
            assert result.principle != ""
            assert result.procedure != ""
            assert result.synthesis != ""

    def test_unsupported_type_falls_back_to_unknown(self):
        result = self.reflector.reflect("failure", "cause", failure_type="nonexistent_type")
        assert result.principle == self.reflector.PRINCIPLE_MAP["unknown"]


# =============================================================================
# Singletons
# =============================================================================


class TestSingletons:
    def test_classifier_singleton(self):
        reset_failure_taxonomy()
        c1 = get_mast_classifier()
        c2 = get_mast_classifier()
        assert c1 is c2

    def test_reflector_singleton(self):
        reset_failure_taxonomy()
        r1 = get_triple_reflector()
        r2 = get_triple_reflector()
        assert r1 is r2

    def test_reset_creates_new_instances(self):
        reset_failure_taxonomy()
        c1 = get_mast_classifier()
        r1 = get_triple_reflector()
        reset_failure_taxonomy()
        c2 = get_mast_classifier()
        r2 = get_triple_reflector()
        assert c1 is not c2
        assert r1 is not r2
