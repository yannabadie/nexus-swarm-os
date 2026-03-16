"""Tests for Multi-Dimensional Evaluation Panel (CRM-inspired)."""

import pytest

from core.intelligence.reasoning.evaluation_panel import (
    DEFAULT_WEIGHTS,
    CoherenceEvaluator,
    DimensionScore,
    EvalDimension,
    EvaluationPanel,
    FactualEvaluator,
    HelpfulnessEvaluator,
    ReasoningEvaluator,
    get_evaluation_panel,
    reset_evaluation_panel,
)

# =============================================================================
# EvalDimension
# =============================================================================


class TestEvalDimension:
    def test_four_dimensions(self):
        assert len(EvalDimension) == 4

    def test_default_weights_sum_to_one(self):
        assert sum(DEFAULT_WEIGHTS.values()) == pytest.approx(1.0)

    def test_all_dimensions_have_weights(self):
        for dim in EvalDimension:
            assert dim in DEFAULT_WEIGHTS


# =============================================================================
# FactualEvaluator
# =============================================================================


class TestFactualEvaluator:
    def setup_method(self):
        self.evaluator = FactualEvaluator()

    def test_grounded_output_scores_high(self):
        output = "The bug is at file auth.py line 42. According to the documentation, version 2.0 added this."
        result = self.evaluator.evaluate(output)
        assert result.score > 0.6
        assert len(result.evidence) > 0

    def test_uncertain_output_penalized(self):
        output = "I think the error might be somewhere. Probably in auth. Not sure though."
        result = self.evaluator.evaluate(output)
        assert len(result.penalty_reasons) > 0

    def test_technical_specificity_bonus(self):
        output = "The issue is in token.validate_expiry which calls jwt.decode incorrectly"
        result = self.evaluator.evaluate(output)
        assert result.score > 0.5

    def test_dimension_is_factual(self):
        result = self.evaluator.evaluate("test")
        assert result.dimension == EvalDimension.FACTUAL


# =============================================================================
# ReasoningEvaluator
# =============================================================================


class TestReasoningEvaluator:
    def setup_method(self):
        self.evaluator = ReasoningEvaluator()

    def test_causal_reasoning_scores_high(self):
        output = "The timeout occurs because the API call takes too long. Therefore we should add a 10s limit. Since the retry logic was missing, it caused cascading failures."
        result = self.evaluator.evaluate(output)
        assert result.score > 0.6
        assert len(result.evidence) > 0

    def test_structured_argument_bonus(self):
        output = "First, analyze the error. Second, check the logs. Finally, apply the fix to prevent recurrence."
        result = self.evaluator.evaluate(output)
        assert result.score > 0.5

    def test_brief_output_penalized(self):
        output = "Fix it."
        result = self.evaluator.evaluate(output)
        assert result.score < 0.5
        assert len(result.penalty_reasons) > 0

    def test_dimension_is_reasoning(self):
        result = self.evaluator.evaluate("test")
        assert result.dimension == EvalDimension.REASONING


# =============================================================================
# HelpfulnessEvaluator
# =============================================================================


class TestHelpfulnessEvaluator:
    def setup_method(self):
        self.evaluator = HelpfulnessEvaluator()

    def test_actionable_output_scores_high(self):
        output = "I recommend fixing the auth bug by updating the token validation. First, change line 42. Then add the expiry check."
        result = self.evaluator.evaluate(output, context="Fix auth bug in token module")
        assert result.score > 0.6

    def test_context_alignment_bonus(self):
        output = "The auth module token validation needs fixing at line 42"
        result = self.evaluator.evaluate(output, context="auth module token validation line 42")
        assert len(result.evidence) > 0

    def test_vague_output_penalized(self):
        output = "It depends on many factors. Need more information to proceed."
        result = self.evaluator.evaluate(output)
        assert len(result.penalty_reasons) > 0

    def test_dimension_is_helpfulness(self):
        result = self.evaluator.evaluate("test")
        assert result.dimension == EvalDimension.HELPFULNESS


# =============================================================================
# CoherenceEvaluator
# =============================================================================


class TestCoherenceEvaluator:
    def setup_method(self):
        self.evaluator = CoherenceEvaluator()

    def test_well_structured_scores_high(self):
        output = "The analysis reveals three issues. First, the auth module has a bug. Second, the token validation is incomplete. Third, error handling is missing."
        result = self.evaluator.evaluate(output)
        assert result.score > 0.6

    def test_formatted_output_bonus(self):
        output = "Analysis:\n\n1. Bug in auth.py\n- Token expiry not checked\n- Fix: add validation"
        result = self.evaluator.evaluate(output)
        assert len(result.evidence) > 0

    def test_empty_output_scores_low(self):
        result = self.evaluator.evaluate("")
        assert result.score < 0.2

    def test_repetitive_output_penalized(self):
        output = "the the the the the the the the the the the the bug bug bug bug"
        result = self.evaluator.evaluate(output)
        assert len(result.penalty_reasons) > 0

    def test_dimension_is_coherence(self):
        result = self.evaluator.evaluate("test")
        assert result.dimension == EvalDimension.COHERENCE


# =============================================================================
# EvaluationPanel - Aggregation
# =============================================================================


class TestPanelAggregation:
    def setup_method(self):
        self.panel = EvaluationPanel()

    def test_evaluate_returns_all_dimensions(self):
        result = self.panel.evaluate("The auth bug is at line 42 because the token check is missing")
        assert len(result.dimension_scores) == 4
        for dim in EvalDimension:
            assert dim in result.dimension_scores

    def test_composite_score_is_weighted_average(self):
        result = self.panel.evaluate("Test output for evaluation")
        # Composite should be between min and max dimension scores
        scores = [ds.score for ds in result.dimension_scores.values()]
        assert min(scores) <= result.composite_score <= max(scores)

    def test_high_quality_output_scores_high(self):
        output = (
            "The bug is at file auth.py line 42. Because the token.validate_expiry function "
            "does not check for None values, it causes a KeyError. Therefore, I recommend "
            "adding a None check before accessing token.exp. First, update the validation. "
            "Then add a test case. Finally, verify the fix resolves the issue."
        )
        result = self.panel.evaluate(output, context="Find and fix auth bug in token module")
        assert result.composite_score > 0.55

    def test_low_quality_output_scores_low(self):
        result = self.panel.evaluate("ok")
        assert result.composite_score < 0.55

    def test_agreement_level_between_0_and_1(self):
        result = self.panel.evaluate("The issue is X because of Y. Fix by doing Z.")
        assert 0.0 <= result.agreement_level <= 1.0

    def test_weakest_and_strongest_identified(self):
        result = self.panel.evaluate("Test output")
        assert result.weakest_dimension in EvalDimension
        assert result.strongest_dimension in EvalDimension

    def test_to_dict(self):
        result = self.panel.evaluate("Test output for dict conversion")
        d = result.to_dict()
        assert "composite_score" in d
        assert "dimensions" in d
        assert "weakest" in d
        assert "agreement_level" in d


# =============================================================================
# EvaluationPanel - Custom Weights
# =============================================================================


class TestCustomWeights:
    def test_factual_heavy_weighting(self):
        heavy_factual = EvaluationPanel(
            weights={
                EvalDimension.FACTUAL: 0.7,
                EvalDimension.REASONING: 0.1,
                EvalDimension.HELPFULNESS: 0.1,
                EvalDimension.COHERENCE: 0.1,
            }
        )
        # Grounded output should score higher with factual-heavy weights
        output = "At file auth.py line 42. According to version 2.0 documentation."
        result = heavy_factual.evaluate(output)
        factual_score = result.dimension_scores[EvalDimension.FACTUAL].score
        # Composite should be closer to factual score due to weight
        assert abs(result.composite_score - factual_score) < 0.3


# =============================================================================
# EvaluationPanel - History & Stats
# =============================================================================


class TestPanelHistory:
    def test_evaluation_count(self):
        panel = EvaluationPanel()
        assert panel.evaluation_count == 0
        panel.evaluate("test 1")
        panel.evaluate("test 2")
        assert panel.evaluation_count == 2

    def test_get_stats_empty(self):
        panel = EvaluationPanel()
        stats = panel.get_stats()
        assert stats.evaluations_run == 0

    def test_get_stats_with_data(self):
        panel = EvaluationPanel()
        panel.evaluate("test output one")
        panel.evaluate("another test output")
        stats = panel.get_stats()
        assert stats.evaluations_run == 2
        assert stats.avg_composite > 0
        assert len(stats.dimension_averages) == 4

    def test_reset_clears_history(self):
        panel = EvaluationPanel()
        panel.evaluate("test")
        panel.reset()
        assert panel.evaluation_count == 0
        stats = panel.get_stats()
        assert stats.evaluations_run == 0

    def test_stats_to_dict(self):
        panel = EvaluationPanel()
        panel.evaluate("test")
        d = panel.get_stats().to_dict()
        assert "evaluations_run" in d
        assert "avg_composite" in d


# =============================================================================
# DimensionScore
# =============================================================================


class TestDimensionScore:
    def test_to_dict(self):
        ds = DimensionScore(
            dimension=EvalDimension.FACTUAL,
            score=0.85,
            evidence=["ev1", "ev2"],
            penalty_reasons=["pen1"],
        )
        d = ds.to_dict()
        assert d["dimension"] == "factual"
        assert d["score"] == 0.85
        assert d["evidence_count"] == 2
        assert d["penalties"] == 1


# =============================================================================
# Singleton
# =============================================================================


class TestSingleton:
    def test_get_returns_same(self):
        reset_evaluation_panel()
        p1 = get_evaluation_panel()
        p2 = get_evaluation_panel()
        assert p1 is p2

    def test_reset_creates_new(self):
        reset_evaluation_panel()
        p1 = get_evaluation_panel()
        reset_evaluation_panel()
        p2 = get_evaluation_panel()
        assert p1 is not p2
