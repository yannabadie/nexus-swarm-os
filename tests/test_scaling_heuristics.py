"""
Tests for ScalingHeuristicEvaluator - V12.4 COGNITIVE BOOST

Comprehensive test suite for core/swarm/scaling_heuristics.py covering:
- Enum values and dataclass serialization
- Task classification (keywords and domains)
- Coordination recommendations for all task types
- Complexity-based overrides and threshold behavior
- Mode suggestion mapping to NEXUS swarm modes
- Historical outcome adjustment
- Confidence computation
- Reasoning string building
- Singleton get/reset pattern
- Statistics tracking
- Edge cases (empty text, unknown domains, mixed tasks)
"""

import sys
import threading
from pathlib import Path

import pytest

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.intelligence.swarm.scaling_heuristics import (
    CHARACTERISTIC_KEYWORDS,
    COMPLEXITY_AGENT_MAP,
    COORDINATION_MAP,
    DEGRADATION_RISK,
    SCALING_BENEFIT,
    SINGLE_AGENT_THRESHOLD,
    CoordinationType,
    ScalingHeuristicEvaluator,
    ScalingRecommendation,
    ScalingStats,
    TaskCharacteristic,
    get_scaling_heuristics,
    reset_scaling_heuristics,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the global singleton before and after each test."""
    reset_scaling_heuristics()
    yield
    reset_scaling_heuristics()


@pytest.fixture
def evaluator() -> ScalingHeuristicEvaluator:
    """Return a fresh ScalingHeuristicEvaluator instance."""
    return ScalingHeuristicEvaluator()


# ===========================================================================
# Section 1: Enum values
# ===========================================================================


class TestCoordinationType:
    """Tests for CoordinationType enum."""

    def test_centralized_value(self):
        assert CoordinationType.CENTRALIZED.value == "centralized"

    def test_decentralized_value(self):
        assert CoordinationType.DECENTRALIZED.value == "decentralized"

    def test_single_agent_value(self):
        assert CoordinationType.SINGLE_AGENT.value == "single_agent"

    def test_parallel_value(self):
        assert CoordinationType.PARALLEL.value == "parallel"

    def test_sequential_value(self):
        assert CoordinationType.SEQUENTIAL.value == "sequential"

    def test_all_members_count(self):
        assert len(CoordinationType) == 5

    def test_is_str_enum(self):
        assert isinstance(CoordinationType.CENTRALIZED, str)
        assert CoordinationType.CENTRALIZED == "centralized"


class TestTaskCharacteristic:
    """Tests for TaskCharacteristic enum."""

    def test_parallelizable_value(self):
        assert TaskCharacteristic.PARALLELIZABLE.value == "parallelizable"

    def test_sequential_reasoning_value(self):
        assert TaskCharacteristic.SEQUENTIAL_REASONING.value == "sequential"

    def test_web_navigation_value(self):
        assert TaskCharacteristic.WEB_NAVIGATION.value == "web_navigation"

    def test_code_generation_value(self):
        assert TaskCharacteristic.CODE_GENERATION.value == "code_generation"

    def test_code_review_value(self):
        assert TaskCharacteristic.CODE_REVIEW.value == "code_review"

    def test_creative_value(self):
        assert TaskCharacteristic.CREATIVE.value == "creative"

    def test_analytical_value(self):
        assert TaskCharacteristic.ANALYTICAL.value == "analytical"

    def test_mixed_value(self):
        assert TaskCharacteristic.MIXED.value == "mixed"

    def test_all_members_count(self):
        assert len(TaskCharacteristic) == 8

    def test_is_str_enum(self):
        assert isinstance(TaskCharacteristic.MIXED, str)
        assert TaskCharacteristic.MIXED == "mixed"


# ===========================================================================
# Section 2: ScalingRecommendation dataclass
# ===========================================================================


class TestScalingRecommendation:
    """Tests for ScalingRecommendation creation and serialization."""

    def test_default_values(self):
        rec = ScalingRecommendation(coordination=CoordinationType.CENTRALIZED)
        assert rec.coordination == CoordinationType.CENTRALIZED
        assert rec.max_agents == 2
        assert rec.confidence == 0.5
        assert rec.reasoning == ""
        assert rec.characteristic == TaskCharacteristic.MIXED
        assert rec.expected_benefit_pct == 0.0
        assert rec.degradation_risk == 0.0

    def test_custom_values(self):
        rec = ScalingRecommendation(
            coordination=CoordinationType.PARALLEL,
            max_agents=3,
            confidence=0.85,
            reasoning="Strong parallelism signal",
            characteristic=TaskCharacteristic.PARALLELIZABLE,
            expected_benefit_pct=80.8,
            degradation_risk=0.05,
        )
        assert rec.coordination == CoordinationType.PARALLEL
        assert rec.max_agents == 3
        assert rec.confidence == 0.85
        assert rec.reasoning == "Strong parallelism signal"
        assert rec.characteristic == TaskCharacteristic.PARALLELIZABLE
        assert rec.expected_benefit_pct == 80.8
        assert rec.degradation_risk == 0.05

    def test_to_dict_keys(self):
        rec = ScalingRecommendation(coordination=CoordinationType.CENTRALIZED)
        d = rec.to_dict()
        expected_keys = {
            "coordination",
            "max_agents",
            "confidence",
            "characteristic",
            "expected_benefit_pct",
            "degradation_risk",
            "reasoning",
        }
        assert set(d.keys()) == expected_keys

    def test_to_dict_values_serialized(self):
        rec = ScalingRecommendation(
            coordination=CoordinationType.PARALLEL,
            characteristic=TaskCharacteristic.PARALLELIZABLE,
            confidence=0.123456,
            expected_benefit_pct=80.75,
            degradation_risk=0.054321,
        )
        d = rec.to_dict()
        assert d["coordination"] == "parallel"
        assert d["characteristic"] == "parallelizable"
        assert d["confidence"] == 0.123  # rounded to 3 decimals
        assert d["expected_benefit_pct"] == 80.8  # rounded to 1 decimal
        assert d["degradation_risk"] == 0.054  # rounded to 3 decimals

    def test_to_dict_is_plain_dict(self):
        rec = ScalingRecommendation(coordination=CoordinationType.CENTRALIZED)
        d = rec.to_dict()
        assert isinstance(d, dict)
        # Enum values should be plain strings
        assert isinstance(d["coordination"], str)
        assert isinstance(d["characteristic"], str)


# ===========================================================================
# Section 3: ScalingStats dataclass
# ===========================================================================


class TestScalingStats:
    """Tests for ScalingStats creation and serialization."""

    def test_default_values(self):
        stats = ScalingStats()
        assert stats.total_recommendations == 0
        assert stats.coordination_counts == {}
        assert stats.single_agent_overrides == 0
        assert stats.avg_confidence == 0.0
        assert stats.outcomes == []

    def test_custom_values(self):
        stats = ScalingStats(
            total_recommendations=10,
            coordination_counts={"centralized": 5, "parallel": 5},
            single_agent_overrides=2,
            avg_confidence=0.75,
            outcomes=[("centralized", True), ("parallel", False)],
        )
        assert stats.total_recommendations == 10
        assert stats.coordination_counts["centralized"] == 5
        assert stats.single_agent_overrides == 2
        assert stats.avg_confidence == 0.75
        assert len(stats.outcomes) == 2

    def test_to_dict_keys(self):
        stats = ScalingStats()
        d = stats.to_dict()
        expected_keys = {
            "total_recommendations",
            "coordination_counts",
            "single_agent_overrides",
            "avg_confidence",
        }
        assert set(d.keys()) == expected_keys

    def test_to_dict_excludes_outcomes(self):
        stats = ScalingStats(outcomes=[("centralized", True)])
        d = stats.to_dict()
        assert "outcomes" not in d

    def test_to_dict_rounds_confidence(self):
        stats = ScalingStats(avg_confidence=0.777777)
        d = stats.to_dict()
        assert d["avg_confidence"] == 0.778

    def test_coordination_counts_default_factory(self):
        """Ensure default_factory creates independent dicts."""
        s1 = ScalingStats()
        s2 = ScalingStats()
        s1.coordination_counts["x"] = 1
        assert "x" not in s2.coordination_counts


# ===========================================================================
# Section 4: Task classification by keywords
# ===========================================================================


class TestClassifyByKeywords:
    """Tests for keyword-based task classification."""

    def test_parallelizable_keywords(self, evaluator):
        rec = evaluator.evaluate("Run these independent tasks in parallel simultaneously")
        assert rec.characteristic == TaskCharacteristic.PARALLELIZABLE

    def test_sequential_reasoning_keywords(self, evaluator):
        rec = evaluator.evaluate("Step by step, derive the proof and calculate the theorem using logic")
        assert rec.characteristic == TaskCharacteristic.SEQUENTIAL_REASONING

    def test_web_navigation_keywords(self, evaluator):
        rec = evaluator.evaluate("Search the web and browse online for the url")
        assert rec.characteristic == TaskCharacteristic.WEB_NAVIGATION

    def test_code_generation_keywords(self, evaluator):
        rec = evaluator.evaluate("Write and implement a class with a function to build this module")
        assert rec.characteristic == TaskCharacteristic.CODE_GENERATION

    def test_code_review_keywords(self, evaluator):
        rec = evaluator.evaluate("Review this code for security bugs, debug and validate the fix")
        assert rec.characteristic == TaskCharacteristic.CODE_REVIEW

    def test_creative_keywords(self, evaluator):
        rec = evaluator.evaluate("Brainstorm and design a creative innovative architecture")
        assert rec.characteristic == TaskCharacteristic.CREATIVE

    def test_analytical_keywords(self, evaluator):
        rec = evaluator.evaluate("Analyze performance, compare benchmarks, evaluate and assess results")
        assert rec.characteristic == TaskCharacteristic.ANALYTICAL

    def test_single_keyword_match(self, evaluator):
        """A single strong keyword should still trigger classification."""
        rec = evaluator.evaluate("brainstorm ideas")
        assert rec.characteristic == TaskCharacteristic.CREATIVE

    def test_case_insensitive(self, evaluator):
        """Keywords should match case-insensitively."""
        rec = evaluator.evaluate("PARALLEL INDEPENDENT SIMULTANEOUSLY")
        assert rec.characteristic == TaskCharacteristic.PARALLELIZABLE

    def test_highest_score_wins(self, evaluator):
        """When multiple keywords match, the characteristic with most matches wins."""
        # 3 parallel keywords vs 1 creative keyword
        text = "Run parallel independent concurrent tasks and brainstorm"
        rec = evaluator.evaluate(text)
        assert rec.characteristic == TaskCharacteristic.PARALLELIZABLE


# ===========================================================================
# Section 5: Task classification from domains
# ===========================================================================


class TestClassifyByDomains:
    """Tests for domain-based task classification."""

    def test_coding_domain_boosts_code_generation(self, evaluator):
        rec = evaluator.evaluate("do something", domains=["CODING"])
        assert rec.characteristic == TaskCharacteristic.CODE_GENERATION

    def test_research_domain_boosts_web_navigation(self, evaluator):
        rec = evaluator.evaluate("do something", domains=["RESEARCH"])
        assert rec.characteristic == TaskCharacteristic.WEB_NAVIGATION

    def test_security_domain_boosts_code_review(self, evaluator):
        rec = evaluator.evaluate("do something", domains=["SECURITY"])
        assert rec.characteristic == TaskCharacteristic.CODE_REVIEW

    def test_architecture_domain_boosts_creative(self, evaluator):
        rec = evaluator.evaluate("do something", domains=["ARCHITECTURE"])
        assert rec.characteristic == TaskCharacteristic.CREATIVE

    def test_analysis_domain_boosts_analytical(self, evaluator):
        rec = evaluator.evaluate("do something", domains=["ANALYSIS"])
        assert rec.characteristic == TaskCharacteristic.ANALYTICAL

    def test_domain_case_insensitive(self, evaluator):
        rec = evaluator.evaluate("do something", domains=["coding"])
        assert rec.characteristic == TaskCharacteristic.CODE_GENERATION

    def test_domain_overrides_weak_keywords(self, evaluator):
        """Domain boost (+2.0) should override a single keyword match (+1.0)."""
        rec = evaluator.evaluate("search for something", domains=["CODING"])
        # "search" gives +1 to WEB_NAVIGATION, but CODING domain gives +2 to CODE_GENERATION
        assert rec.characteristic == TaskCharacteristic.CODE_GENERATION

    def test_keywords_override_domain_when_stronger(self, evaluator):
        """Multiple strong keywords should override a single domain boost."""
        text = "search the web, browse online, find the url on the internet and google it"
        rec = evaluator.evaluate(text, domains=["CODING"])
        # 6 web keywords (6.0) vs domain boost (2.0)
        assert rec.characteristic == TaskCharacteristic.WEB_NAVIGATION

    def test_unknown_domain_ignored(self, evaluator):
        """Unknown domains should not cause errors."""
        rec = evaluator.evaluate("do something generic", domains=["UNKNOWN_DOMAIN"])
        assert rec.characteristic == TaskCharacteristic.MIXED

    def test_multiple_domains(self, evaluator):
        """Multiple domains should each contribute their boost."""
        rec = evaluator.evaluate("do something", domains=["SECURITY", "ANALYSIS"])
        # Both contribute +2.0 to their respective characteristics
        # CODE_REVIEW and ANALYTICAL both get 2.0, but CODE_REVIEW appears first in iteration
        assert rec.characteristic in (
            TaskCharacteristic.CODE_REVIEW,
            TaskCharacteristic.ANALYTICAL,
        )


# ===========================================================================
# Section 6: Sequential reasoning -> SINGLE_AGENT + degradation warning
# ===========================================================================


class TestSequentialReasoning:
    """Tests for sequential reasoning tasks."""

    def test_sequential_gets_single_agent(self, evaluator):
        rec = evaluator.evaluate("Step by step, derive and prove using logic and reason")
        assert rec.coordination == CoordinationType.SINGLE_AGENT

    def test_sequential_max_agents_is_one(self, evaluator):
        rec = evaluator.evaluate("Step by step, derive and prove using logic")
        assert rec.max_agents == 1

    def test_sequential_negative_benefit(self, evaluator):
        """Sequential tasks should show negative or zero benefit."""
        rec = evaluator.evaluate("Step by step calculate and derive the theorem")
        assert rec.expected_benefit_pct <= 0

    def test_sequential_high_degradation_risk(self, evaluator):
        rec = evaluator.evaluate("Step by step prove the theorem using logic")
        assert rec.degradation_risk >= 0.5

    def test_sequential_degradation_in_reasoning(self, evaluator):
        rec = evaluator.evaluate("Step by step derive and prove the theorem")
        assert "DEGRADE" in rec.reasoning or "single-agent" in rec.reasoning.lower()


# ===========================================================================
# Section 7: Parallelizable tasks -> PARALLEL + high benefit
# ===========================================================================


class TestParallelizableTasks:
    """Tests for parallelizable tasks."""

    def test_parallel_coordination_type(self, evaluator):
        rec = evaluator.evaluate("Run multiple independent tasks in parallel simultaneously")
        assert rec.coordination == CoordinationType.PARALLEL

    def test_parallel_high_benefit(self, evaluator):
        rec = evaluator.evaluate("Run independent tasks in parallel simultaneously")
        assert rec.expected_benefit_pct > 50.0

    def test_parallel_low_degradation_risk(self, evaluator):
        rec = evaluator.evaluate("Run independent tasks in parallel simultaneously")
        assert rec.degradation_risk <= 0.10

    def test_parallel_allows_two_agents(self, evaluator):
        rec = evaluator.evaluate("Run parallel independent tasks", complexity="moderate")
        assert rec.max_agents == 2


# ===========================================================================
# Section 8: Code review -> centralized (RED_BLUE mode suggestion)
# ===========================================================================


class TestCodeReview:
    """Tests for code review tasks."""

    def test_code_review_centralized(self, evaluator):
        rec = evaluator.evaluate("Review this code for security bugs and audit the fix")
        assert rec.coordination == CoordinationType.CENTRALIZED

    def test_code_review_red_blue_mode(self, evaluator):
        rec = evaluator.evaluate("Review and audit this security code for bugs")
        mode = evaluator.get_mode_suggestion(rec)
        assert mode == "RED_BLUE"

    def test_code_review_positive_benefit(self, evaluator):
        rec = evaluator.evaluate("Review this code for security bugs, debug and validate")
        assert rec.expected_benefit_pct > 0


# ===========================================================================
# Section 9: Creative tasks -> decentralized (PING_PONG suggestion)
# ===========================================================================


class TestCreativeTasks:
    """Tests for creative tasks."""

    def test_creative_decentralized(self, evaluator):
        rec = evaluator.evaluate("Brainstorm and design innovative creative ideas")
        assert rec.coordination == CoordinationType.DECENTRALIZED

    def test_creative_ping_pong_mode(self, evaluator):
        rec = evaluator.evaluate("Brainstorm creative innovative design ideas")
        mode = evaluator.get_mode_suggestion(rec)
        assert mode == "PING_PONG"

    def test_creative_positive_benefit(self, evaluator):
        rec = evaluator.evaluate("Brainstorm and ideate creative proposals")
        assert rec.expected_benefit_pct > 0


# ===========================================================================
# Section 10: Simple/trivial tasks -> single agent override
# ===========================================================================


class TestSimpleTrivialOverride:
    """Tests for complexity-based single agent override."""

    def test_trivial_complexity_overrides_to_single_agent(self, evaluator):
        """Trivial tasks with low benefit should be routed to single agent."""
        rec = evaluator.evaluate("Analyze this data", complexity="trivial")
        assert rec.coordination == CoordinationType.SINGLE_AGENT
        assert rec.max_agents == 1

    def test_simple_complexity_overrides_to_single_agent(self, evaluator):
        """Simple tasks with low benefit should be routed to single agent."""
        rec = evaluator.evaluate("Analyze this data", complexity="simple")
        assert rec.coordination == CoordinationType.SINGLE_AGENT
        assert rec.max_agents == 1

    def test_trivial_high_benefit_not_overridden(self, evaluator):
        """Trivial tasks with high benefit (>0.30) should NOT be overridden."""
        rec = evaluator.evaluate(
            "Run parallel independent simultaneous tasks",
            complexity="trivial",
        )
        # PARALLELIZABLE benefit is 0.808, > 0.30 threshold
        assert rec.coordination == CoordinationType.PARALLEL

    def test_simple_high_benefit_not_overridden(self, evaluator):
        """Simple tasks with high benefit (>0.30) keep their coordination."""
        rec = evaluator.evaluate(
            "Brainstorm creative innovative design ideas and imagine",
            complexity="simple",
        )
        # CREATIVE benefit is 0.35, > 0.30 threshold
        assert rec.coordination == CoordinationType.DECENTRALIZED

    def test_moderate_no_override(self, evaluator):
        """Moderate complexity should not trigger the simple/trivial override."""
        rec = evaluator.evaluate("Analyze this data", complexity="moderate")
        # ANALYTICAL benefit is 0.20, above SINGLE_AGENT_THRESHOLD (0.05)
        assert rec.coordination != CoordinationType.SINGLE_AGENT or rec.max_agents == 2

    def test_complex_no_override(self, evaluator):
        """Complex tasks should not trigger the simple/trivial override."""
        rec = evaluator.evaluate("Analyze this data", complexity="complex")
        assert rec.max_agents == 2


# ===========================================================================
# Section 11: SINGLE_AGENT_THRESHOLD behavior
# ===========================================================================


class TestSingleAgentThreshold:
    """Tests for the SINGLE_AGENT_THRESHOLD constant and its effect."""

    def test_threshold_value(self):
        assert SINGLE_AGENT_THRESHOLD == 0.05

    def test_below_threshold_becomes_single_agent(self, evaluator):
        """Benefits below 0.05 should force SINGLE_AGENT coordination."""
        # CODE_GENERATION + simple -> benefit = 0.10 but override sets it to 0.0
        # when complexity is simple and benefit < 0.30
        rec = evaluator.evaluate("Write a function", complexity="simple")
        assert rec.coordination == CoordinationType.SINGLE_AGENT

    def test_above_threshold_keeps_coordination(self, evaluator):
        """Benefits above 0.05 should keep original coordination."""
        rec = evaluator.evaluate(
            "Run parallel independent simultaneous concurrent batch tasks",
            complexity="moderate",
        )
        # PARALLELIZABLE benefit = 0.808, well above threshold
        assert rec.coordination == CoordinationType.PARALLEL

    def test_negative_benefit_forces_single_agent(self, evaluator):
        """Negative benefit (like sequential reasoning) forces SINGLE_AGENT."""
        rec = evaluator.evaluate(
            "Step by step calculate and derive using logic",
            complexity="moderate",
        )
        assert rec.coordination == CoordinationType.SINGLE_AGENT


# ===========================================================================
# Section 12: get_mode_suggestion() mapping to NEXUS swarm modes
# ===========================================================================


class TestGetModeSuggestion:
    """Tests for mapping recommendations to NEXUS swarm modes."""

    def test_centralized_maps_to_lead_support(self, evaluator):
        rec = ScalingRecommendation(
            coordination=CoordinationType.CENTRALIZED,
            characteristic=TaskCharacteristic.ANALYTICAL,
        )
        assert evaluator.get_mode_suggestion(rec) == "LEAD_SUPPORT"

    def test_decentralized_maps_to_ping_pong(self, evaluator):
        rec = ScalingRecommendation(
            coordination=CoordinationType.DECENTRALIZED,
            characteristic=TaskCharacteristic.WEB_NAVIGATION,
        )
        assert evaluator.get_mode_suggestion(rec) == "PING_PONG"

    def test_single_agent_maps_to_specialist(self, evaluator):
        rec = ScalingRecommendation(
            coordination=CoordinationType.SINGLE_AGENT,
            characteristic=TaskCharacteristic.SEQUENTIAL_REASONING,
        )
        assert evaluator.get_mode_suggestion(rec) == "SPECIALIST"

    def test_parallel_maps_to_parallel(self, evaluator):
        rec = ScalingRecommendation(
            coordination=CoordinationType.PARALLEL,
            characteristic=TaskCharacteristic.PARALLELIZABLE,
        )
        assert evaluator.get_mode_suggestion(rec) == "PARALLEL"

    def test_sequential_maps_to_sequential(self, evaluator):
        rec = ScalingRecommendation(
            coordination=CoordinationType.SEQUENTIAL,
            characteristic=TaskCharacteristic.MIXED,
        )
        assert evaluator.get_mode_suggestion(rec) == "SEQUENTIAL"

    def test_code_review_overrides_to_red_blue(self, evaluator):
        """CODE_REVIEW characteristic should always produce RED_BLUE."""
        rec = ScalingRecommendation(
            coordination=CoordinationType.CENTRALIZED,
            characteristic=TaskCharacteristic.CODE_REVIEW,
        )
        assert evaluator.get_mode_suggestion(rec) == "RED_BLUE"

    def test_creative_overrides_to_ping_pong(self, evaluator):
        """CREATIVE characteristic should always produce PING_PONG."""
        rec = ScalingRecommendation(
            coordination=CoordinationType.CENTRALIZED,
            characteristic=TaskCharacteristic.CREATIVE,
        )
        assert evaluator.get_mode_suggestion(rec) == "PING_PONG"

    def test_code_review_override_takes_priority(self, evaluator):
        """CODE_REVIEW override should work even with SINGLE_AGENT coordination."""
        rec = ScalingRecommendation(
            coordination=CoordinationType.SINGLE_AGENT,
            characteristic=TaskCharacteristic.CODE_REVIEW,
        )
        assert evaluator.get_mode_suggestion(rec) == "RED_BLUE"


# ===========================================================================
# Section 13: Historical outcome adjustment
# ===========================================================================


class TestHistoricalOutcomeAdjustment:
    """Tests for _get_historical_adjustment and record_outcome."""

    def test_no_history_returns_zero(self, evaluator):
        """With no history, adjustment should be 0.0."""
        adj = evaluator._get_historical_adjustment(TaskCharacteristic.PARALLELIZABLE)
        assert adj == 0.0

    def test_fewer_than_three_returns_zero(self, evaluator):
        """With fewer than 3 relevant outcomes, adjustment should be 0.0."""
        evaluator.record_outcome(TaskCharacteristic.PARALLELIZABLE, CoordinationType.PARALLEL, True)
        evaluator.record_outcome(TaskCharacteristic.PARALLELIZABLE, CoordinationType.PARALLEL, True)
        adj = evaluator._get_historical_adjustment(TaskCharacteristic.PARALLELIZABLE)
        assert adj == 0.0

    def test_three_successes_positive_adjustment(self, evaluator):
        """3 successes should give positive adjustment."""
        for _ in range(3):
            evaluator.record_outcome(TaskCharacteristic.PARALLELIZABLE, CoordinationType.PARALLEL, True)
        adj = evaluator._get_historical_adjustment(TaskCharacteristic.PARALLELIZABLE)
        # success_rate = 1.0, adjustment = (1.0 - 0.5) * 0.2 = 0.1
        assert adj == pytest.approx(0.1)

    def test_three_failures_negative_adjustment(self, evaluator):
        """3 failures should give negative adjustment."""
        for _ in range(3):
            evaluator.record_outcome(TaskCharacteristic.PARALLELIZABLE, CoordinationType.PARALLEL, False)
        adj = evaluator._get_historical_adjustment(TaskCharacteristic.PARALLELIZABLE)
        # success_rate = 0.0, adjustment = (0.0 - 0.5) * 0.2 = -0.1
        assert adj == pytest.approx(-0.1)

    def test_mixed_outcomes_moderate_adjustment(self, evaluator):
        """50/50 outcomes should give ~0.0 adjustment."""
        for _ in range(3):
            evaluator.record_outcome(TaskCharacteristic.CREATIVE, CoordinationType.DECENTRALIZED, True)
        for _ in range(3):
            evaluator.record_outcome(TaskCharacteristic.CREATIVE, CoordinationType.DECENTRALIZED, False)
        adj = evaluator._get_historical_adjustment(TaskCharacteristic.CREATIVE)
        # success_rate = 0.5, adjustment = (0.5 - 0.5) * 0.2 = 0.0
        assert adj == pytest.approx(0.0)

    def test_different_characteristics_independent(self, evaluator):
        """Outcomes for one characteristic should not affect another."""
        for _ in range(5):
            evaluator.record_outcome(TaskCharacteristic.PARALLELIZABLE, CoordinationType.PARALLEL, True)
        adj_parallel = evaluator._get_historical_adjustment(TaskCharacteristic.PARALLELIZABLE)
        adj_creative = evaluator._get_historical_adjustment(TaskCharacteristic.CREATIVE)
        assert adj_parallel > 0
        assert adj_creative == 0.0

    def test_history_trimming_at_100(self, evaluator):
        """History should be trimmed when exceeding 100 entries."""
        for _i in range(105):
            evaluator.record_outcome(TaskCharacteristic.PARALLELIZABLE, CoordinationType.PARALLEL, True)
        # After 101st entry, history is trimmed to last 50
        # Then entries 102-105 are added, total = 54
        assert len(evaluator._outcome_history) <= 55

    def test_record_outcome_updates_stats(self, evaluator):
        evaluator.record_outcome(TaskCharacteristic.CODE_REVIEW, CoordinationType.CENTRALIZED, True)
        evaluator.get_stats()
        assert len(evaluator._stats.outcomes) == 1

    def test_historical_adjustment_affects_evaluation(self, evaluator):
        """Historical successes should increase expected_benefit_pct."""
        rec_before = evaluator.evaluate("Run independent parallel tasks simultaneously")
        for _ in range(5):
            evaluator.record_outcome(TaskCharacteristic.PARALLELIZABLE, CoordinationType.PARALLEL, True)
        rec_after = evaluator.evaluate("Run independent parallel tasks simultaneously")
        assert rec_after.expected_benefit_pct > rec_before.expected_benefit_pct


# ===========================================================================
# Section 14: Confidence computation
# ===========================================================================


class TestConfidenceComputation:
    """Tests for _compute_confidence."""

    def test_confidence_bounded_above(self, evaluator):
        """Confidence should never exceed 0.95."""
        conf = evaluator._compute_confidence(TaskCharacteristic.PARALLELIZABLE, "expert", 10.0, 0.0)
        assert conf <= 0.95

    def test_confidence_bounded_below(self, evaluator):
        """Confidence should never go below 0.1."""
        conf = evaluator._compute_confidence(TaskCharacteristic.MIXED, "moderate", 0.0, 1.0)
        assert conf >= 0.1

    def test_high_benefit_high_confidence(self, evaluator):
        """Strong benefit signal should produce high confidence."""
        conf = evaluator._compute_confidence(TaskCharacteristic.PARALLELIZABLE, "complex", 0.808, 0.05)
        assert conf > 0.7

    def test_high_risk_reduces_confidence(self, evaluator):
        """High degradation risk should reduce confidence."""
        conf_low_risk = evaluator._compute_confidence(TaskCharacteristic.PARALLELIZABLE, "complex", 0.5, 0.05)
        conf_high_risk = evaluator._compute_confidence(TaskCharacteristic.PARALLELIZABLE, "complex", 0.5, 0.70)
        assert conf_high_risk < conf_low_risk

    def test_well_studied_boost(self, evaluator):
        """PARALLELIZABLE and SEQUENTIAL_REASONING get a +0.1 confidence boost."""
        conf_parallelizable = evaluator._compute_confidence(TaskCharacteristic.PARALLELIZABLE, "complex", 0.3, 0.1)
        conf_mixed = evaluator._compute_confidence(TaskCharacteristic.MIXED, "complex", 0.3, 0.1)
        assert conf_parallelizable > conf_mixed

    def test_sequential_well_studied_boost(self, evaluator):
        """SEQUENTIAL_REASONING should also get the well-studied boost."""
        conf_seq = evaluator._compute_confidence(TaskCharacteristic.SEQUENTIAL_REASONING, "complex", 0.3, 0.1)
        conf_analytical = evaluator._compute_confidence(TaskCharacteristic.ANALYTICAL, "complex", 0.3, 0.1)
        assert conf_seq > conf_analytical

    def test_moderate_complexity_reduces_confidence(self, evaluator):
        """Moderate complexity should reduce confidence by 0.05."""
        conf_moderate = evaluator._compute_confidence(TaskCharacteristic.CODE_GENERATION, "moderate", 0.3, 0.1)
        conf_complex = evaluator._compute_confidence(TaskCharacteristic.CODE_GENERATION, "complex", 0.3, 0.1)
        assert conf_moderate < conf_complex

    def test_confidence_in_recommendation_is_bounded(self, evaluator):
        """Confidence returned from evaluate() should be in [0.1, 0.95]."""
        rec = evaluator.evaluate("Step by step derive", complexity="expert")
        assert 0.1 <= rec.confidence <= 0.95


# ===========================================================================
# Section 15: Reasoning string building
# ===========================================================================


class TestReasoningStringBuilding:
    """Tests for _build_reasoning."""

    def test_contains_characteristic(self, evaluator):
        reasoning = evaluator._build_reasoning(
            TaskCharacteristic.PARALLELIZABLE,
            CoordinationType.PARALLEL,
            0.808,
            0.05,
            "moderate",
        )
        assert "parallelizable" in reasoning

    def test_positive_benefit_message(self, evaluator):
        reasoning = evaluator._build_reasoning(
            TaskCharacteristic.PARALLELIZABLE,
            CoordinationType.PARALLEL,
            0.808,
            0.05,
            "moderate",
        )
        assert "+80.8%" in reasoning
        assert "benefit" in reasoning.lower()

    def test_negative_benefit_degradation_message(self, evaluator):
        reasoning = evaluator._build_reasoning(
            TaskCharacteristic.SEQUENTIAL_REASONING,
            CoordinationType.SINGLE_AGENT,
            -0.50,
            0.70,
            "moderate",
        )
        assert "DEGRADE" in reasoning
        assert "50.0%" in reasoning

    def test_high_risk_warning(self, evaluator):
        reasoning = evaluator._build_reasoning(
            TaskCharacteristic.SEQUENTIAL_REASONING,
            CoordinationType.SINGLE_AGENT,
            -0.50,
            0.70,
            "moderate",
        )
        assert "High degradation risk" in reasoning
        assert "70%" in reasoning

    def test_low_risk_no_warning(self, evaluator):
        reasoning = evaluator._build_reasoning(
            TaskCharacteristic.PARALLELIZABLE,
            CoordinationType.PARALLEL,
            0.808,
            0.05,
            "moderate",
        )
        assert "High degradation risk" not in reasoning

    def test_single_agent_specialist_message(self, evaluator):
        reasoning = evaluator._build_reasoning(
            TaskCharacteristic.CODE_GENERATION,
            CoordinationType.SINGLE_AGENT,
            0.0,
            0.25,
            "simple",
        )
        assert "single-agent" in reasoning.lower() or "SPECIALIST" in reasoning

    def test_non_single_agent_shows_coordination(self, evaluator):
        reasoning = evaluator._build_reasoning(
            TaskCharacteristic.PARALLELIZABLE,
            CoordinationType.PARALLEL,
            0.808,
            0.05,
            "moderate",
        )
        assert "parallel" in reasoning.lower()

    def test_reasoning_is_nonempty_string(self, evaluator):
        rec = evaluator.evaluate("Do something")
        assert isinstance(rec.reasoning, str)
        assert len(rec.reasoning) > 10


# ===========================================================================
# Section 16: Singleton get/reset pattern
# ===========================================================================


class TestSingletonPattern:
    """Tests for get_scaling_heuristics and reset_scaling_heuristics."""

    def test_get_returns_instance(self):
        instance = get_scaling_heuristics()
        assert isinstance(instance, ScalingHeuristicEvaluator)

    def test_get_returns_same_instance(self):
        i1 = get_scaling_heuristics()
        i2 = get_scaling_heuristics()
        assert i1 is i2

    def test_reset_clears_instance(self):
        i1 = get_scaling_heuristics()
        reset_scaling_heuristics()
        i2 = get_scaling_heuristics()
        assert i1 is not i2

    def test_reset_does_not_error_when_none(self):
        reset_scaling_heuristics()
        reset_scaling_heuristics()  # Second reset should not raise

    def test_singleton_state_persists(self):
        instance = get_scaling_heuristics()
        instance.evaluate("Run parallel independent tasks", complexity="moderate")
        stats = instance.get_stats()
        assert stats.total_recommendations == 1
        # Same instance should have the same state
        instance2 = get_scaling_heuristics()
        stats2 = instance2.get_stats()
        assert stats2.total_recommendations == 1

    def test_reset_clears_state(self):
        instance = get_scaling_heuristics()
        instance.evaluate("Run parallel independent tasks")
        reset_scaling_heuristics()
        instance2 = get_scaling_heuristics()
        stats = instance2.get_stats()
        assert stats.total_recommendations == 0

    def test_thread_safe_singleton(self):
        """Ensure singleton is safe across threads."""
        instances = []
        barrier = threading.Barrier(4)

        def get_instance():
            barrier.wait()
            instances.append(get_scaling_heuristics())

        threads = [threading.Thread(target=get_instance) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All threads should get the same instance
        assert all(i is instances[0] for i in instances)


# ===========================================================================
# Section 17: Statistics tracking
# ===========================================================================


class TestStatisticsTracking:
    """Tests for coordination_counts, single_agent_overrides, and averages."""

    def test_initial_stats_empty(self, evaluator):
        stats = evaluator.get_stats()
        assert stats.total_recommendations == 0
        assert stats.coordination_counts == {}
        assert stats.single_agent_overrides == 0
        assert stats.avg_confidence == 0.0

    def test_single_evaluation_updates_count(self, evaluator):
        evaluator.evaluate("Run parallel independent tasks simultaneously")
        stats = evaluator.get_stats()
        assert stats.total_recommendations == 1

    def test_coordination_counts_tracked(self, evaluator):
        evaluator.evaluate("Run parallel independent tasks simultaneously")
        stats = evaluator.get_stats()
        assert "parallel" in stats.coordination_counts
        assert stats.coordination_counts["parallel"] == 1

    def test_multiple_evaluations_accumulate(self, evaluator):
        evaluator.evaluate("Run parallel independent tasks simultaneously")
        evaluator.evaluate("Run parallel independent batch concurrent tasks")
        stats = evaluator.get_stats()
        assert stats.total_recommendations == 2
        assert stats.coordination_counts.get("parallel", 0) == 2

    def test_single_agent_overrides_counted(self, evaluator):
        evaluator.evaluate("Step by step derive prove logic", complexity="moderate")
        stats = evaluator.get_stats()
        assert stats.single_agent_overrides >= 1

    def test_avg_confidence_computed(self, evaluator):
        evaluator.evaluate("Run parallel independent tasks simultaneously")
        stats = evaluator.get_stats()
        assert stats.avg_confidence > 0.0

    def test_avg_confidence_running_average(self, evaluator):
        evaluator.evaluate("Run parallel independent tasks simultaneously")
        evaluator.get_stats()
        evaluator.evaluate("Brainstorm creative innovative ideas")
        stats2 = evaluator.get_stats()
        # Average should reflect both evaluations
        assert stats2.avg_confidence > 0.0
        assert stats2.total_recommendations == 2

    def test_reset_clears_stats(self, evaluator):
        evaluator.evaluate("Run parallel independent tasks simultaneously")
        evaluator.reset()
        stats = evaluator.get_stats()
        assert stats.total_recommendations == 0
        assert stats.coordination_counts == {}
        assert stats.single_agent_overrides == 0

    def test_get_stats_returns_copy(self, evaluator):
        """get_stats should return a new ScalingStats, not the internal one."""
        evaluator.evaluate("Run parallel independent tasks simultaneously")
        stats1 = evaluator.get_stats()
        stats1.total_recommendations = 999
        stats2 = evaluator.get_stats()
        assert stats2.total_recommendations == 1

    def test_mixed_coordination_counts(self, evaluator):
        evaluator.evaluate("Run parallel independent tasks simultaneously")
        evaluator.evaluate("Brainstorm creative innovative design ideas")
        evaluator.evaluate("Step by step derive prove logic reason")
        stats = evaluator.get_stats()
        assert stats.total_recommendations == 3
        assert len(stats.coordination_counts) >= 2


# ===========================================================================
# Section 18: Edge cases
# ===========================================================================


class TestEdgeCases:
    """Tests for edge cases: empty text, unknown domains, mixed tasks."""

    def test_empty_text_returns_mixed(self, evaluator):
        rec = evaluator.evaluate("")
        assert rec.characteristic == TaskCharacteristic.MIXED

    def test_whitespace_only_returns_mixed(self, evaluator):
        rec = evaluator.evaluate("   \n\t  ")
        assert rec.characteristic == TaskCharacteristic.MIXED

    def test_no_matching_keywords_returns_mixed(self, evaluator):
        rec = evaluator.evaluate("hello world foo bar baz")
        assert rec.characteristic == TaskCharacteristic.MIXED

    def test_empty_domains_list(self, evaluator):
        rec = evaluator.evaluate("do something", domains=[])
        # No domain boost, no keyword match -> MIXED
        assert rec.characteristic == TaskCharacteristic.MIXED

    def test_none_domains(self, evaluator):
        rec = evaluator.evaluate("do something", domains=None)
        assert rec.characteristic == TaskCharacteristic.MIXED

    def test_unknown_complexity_defaults_to_two_agents(self, evaluator):
        """Unknown complexity string should default to 2 agents via dict.get."""
        rec = evaluator.evaluate(
            "Run parallel independent tasks simultaneously",
            complexity="legendary",
        )
        assert rec.max_agents == 2

    def test_case_variations_in_complexity(self, evaluator):
        """Complexity should be case-insensitive."""
        rec_lower = evaluator.evaluate("do something", complexity="trivial")
        rec_upper = evaluator.evaluate("do something", complexity="TRIVIAL")
        assert rec_lower.coordination == rec_upper.coordination
        assert rec_lower.max_agents == rec_upper.max_agents

    def test_very_long_text(self, evaluator):
        """Long text should not cause errors."""
        text = " ".join(["parallel independent"] * 500)
        rec = evaluator.evaluate(text)
        assert rec.characteristic == TaskCharacteristic.PARALLELIZABLE

    def test_special_characters_in_text(self, evaluator):
        """Special characters should not cause errors."""
        rec = evaluator.evaluate("!@#$%^&*() parallel tasks <>?/\\")
        # Should still detect "parallel"
        assert rec.characteristic == TaskCharacteristic.PARALLELIZABLE

    def test_evaluate_returns_scaling_recommendation(self, evaluator):
        """evaluate() should always return a ScalingRecommendation."""
        rec = evaluator.evaluate("")
        assert isinstance(rec, ScalingRecommendation)

    def test_mixed_characteristic_coordination(self, evaluator):
        """MIXED characteristic should get centralized coordination by default."""
        rec = evaluator.evaluate("hello world something generic")
        assert rec.coordination in (
            CoordinationType.CENTRALIZED,
            CoordinationType.SINGLE_AGENT,
        )

    def test_evaluate_thread_safe(self, evaluator):
        """Multiple concurrent evaluations should not cause errors."""
        results = []
        barrier = threading.Barrier(4)

        def run_eval():
            barrier.wait()
            r = evaluator.evaluate("Run parallel independent tasks simultaneously")
            results.append(r)

        threads = [threading.Thread(target=run_eval) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 4
        stats = evaluator.get_stats()
        assert stats.total_recommendations == 4


# ===========================================================================
# Section 19: Constants verification
# ===========================================================================


class TestConstants:
    """Tests for module-level constants."""

    def test_scaling_benefit_all_characteristics_covered(self):
        for char in TaskCharacteristic:
            assert char in SCALING_BENEFIT, f"Missing {char} in SCALING_BENEFIT"

    def test_degradation_risk_all_characteristics_covered(self):
        for char in TaskCharacteristic:
            assert char in DEGRADATION_RISK, f"Missing {char} in DEGRADATION_RISK"

    def test_coordination_map_all_characteristics_covered(self):
        for char in TaskCharacteristic:
            assert char in COORDINATION_MAP, f"Missing {char} in COORDINATION_MAP"

    def test_keyword_map_excludes_mixed(self):
        """MIXED should not have keywords (it's the fallback)."""
        assert TaskCharacteristic.MIXED not in CHARACTERISTIC_KEYWORDS

    def test_keyword_map_covers_all_except_mixed(self):
        for char in TaskCharacteristic:
            if char != TaskCharacteristic.MIXED:
                assert char in CHARACTERISTIC_KEYWORDS, f"Missing {char}"

    def test_complexity_agent_map_values(self):
        assert COMPLEXITY_AGENT_MAP["trivial"] == 1
        assert COMPLEXITY_AGENT_MAP["simple"] == 1
        assert COMPLEXITY_AGENT_MAP["moderate"] == 2
        assert COMPLEXITY_AGENT_MAP["complex"] == 2
        assert COMPLEXITY_AGENT_MAP["expert"] == 2

    def test_sequential_has_negative_benefit(self):
        assert SCALING_BENEFIT[TaskCharacteristic.SEQUENTIAL_REASONING] < 0

    def test_parallelizable_has_highest_benefit(self):
        max_char = max(SCALING_BENEFIT, key=SCALING_BENEFIT.get)
        assert max_char == TaskCharacteristic.PARALLELIZABLE

    def test_sequential_has_highest_risk(self):
        max_char = max(DEGRADATION_RISK, key=DEGRADATION_RISK.get)
        assert max_char == TaskCharacteristic.SEQUENTIAL_REASONING

    def test_all_keywords_are_lowercase(self):
        for char, keywords in CHARACTERISTIC_KEYWORDS.items():
            for kw in keywords:
                assert kw == kw.lower(), f"Keyword '{kw}' for {char} not lowercase"


# ===========================================================================
# Section 20: Integration / end-to-end flows
# ===========================================================================


class TestIntegrationFlows:
    """End-to-end tests combining multiple evaluator capabilities."""

    def test_full_flow_parallel_task(self, evaluator):
        """Full flow: evaluate -> mode suggestion -> record outcome -> stats."""
        rec = evaluator.evaluate(
            "Run independent parallel tasks simultaneously",
            complexity="moderate",
        )
        assert rec.characteristic == TaskCharacteristic.PARALLELIZABLE
        assert rec.coordination == CoordinationType.PARALLEL

        mode = evaluator.get_mode_suggestion(rec)
        assert mode == "PARALLEL"

        evaluator.record_outcome(rec.characteristic, rec.coordination, True)

        stats = evaluator.get_stats()
        assert stats.total_recommendations == 1
        assert "parallel" in stats.coordination_counts

    def test_full_flow_sequential_degradation(self, evaluator):
        """Sequential reasoning should warn about degradation and use SPECIALIST."""
        rec = evaluator.evaluate(
            "Step by step derive and prove the mathematical theorem using logic",
            complexity="complex",
        )
        assert rec.characteristic == TaskCharacteristic.SEQUENTIAL_REASONING
        assert rec.coordination == CoordinationType.SINGLE_AGENT
        assert rec.expected_benefit_pct < 0
        assert rec.degradation_risk >= 0.5

        mode = evaluator.get_mode_suggestion(rec)
        assert mode == "SPECIALIST"

        assert "DEGRADE" in rec.reasoning
        assert "High degradation risk" in rec.reasoning

    def test_full_flow_domain_override(self, evaluator):
        """Domain boost should correctly override weak keyword signals."""
        rec = evaluator.evaluate(
            "do this task well",
            complexity="complex",
            domains=["SECURITY"],
        )
        assert rec.characteristic == TaskCharacteristic.CODE_REVIEW
        mode = evaluator.get_mode_suggestion(rec)
        assert mode == "RED_BLUE"

    def test_multiple_evaluations_stats_accuracy(self, evaluator):
        """Stats should accurately reflect multiple evaluations."""
        evaluator.evaluate(
            "Run parallel independent tasks simultaneously",
            complexity="moderate",
        )
        evaluator.evaluate(
            "Step by step derive prove logic",
            complexity="complex",
        )
        evaluator.evaluate(
            "Brainstorm creative innovative design",
            complexity="moderate",
        )
        stats = evaluator.get_stats()
        assert stats.total_recommendations == 3
        total_counted = sum(stats.coordination_counts.values())
        assert total_counted == 3

    def test_reset_then_reuse(self, evaluator):
        """After reset, evaluator should work fresh."""
        evaluator.evaluate("Run parallel independent tasks")
        evaluator.reset()
        stats = evaluator.get_stats()
        assert stats.total_recommendations == 0

        # Should work fine after reset
        rec = evaluator.evaluate("Brainstorm creative ideas")
        assert rec.characteristic == TaskCharacteristic.CREATIVE
        stats = evaluator.get_stats()
        assert stats.total_recommendations == 1
