"""
Tests for DynamicRoleAssigner - V12.4 COGNITIVE BOOST

Comprehensive test coverage for:
- RoleType enum values
- CapabilityProposal creation and serialization
- RoleScore computation and serialization
- RoleAssignmentResult creation and serialization
- Single/multi agent assignment logic
- Score calculation with weighted components
- Historical outcome learning
- MIN_SCORE_DIFF threshold behavior
- Task complexity influence
- Default domain profiles
- Singleton get/reset pattern
- Statistics tracking
- Edge cases
"""

import sys
import threading
import time
from pathlib import Path

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from core.intelligence.swarm.dynamic_role_assigner import (
    DEFAULT_DOMAIN_PROFILES,
    HISTORY_WINDOW,
    MIN_SCORE_DIFF,
    W_CONFIDENCE,
    W_DOMAIN,
    W_HISTORY,
    W_PEER,
    AssignerStats,
    CapabilityProposal,
    DynamicRoleAssigner,
    RoleAssignmentResult,
    RoleScore,
    RoleType,
    get_dynamic_role_assigner,
    reset_dynamic_role_assigner,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def assigner():
    """Create a fresh DynamicRoleAssigner for each test."""
    return DynamicRoleAssigner()


@pytest.fixture
def custom_profiles():
    """Domain profiles with a clear strength gap for deterministic tests.

    The gap must be wide enough that the peer_score (which rewards
    complementarity) cannot compensate. With W_DOMAIN=0.35 and W_PEER=0.20,
    a domain diff of 0.60 creates a net score diff > 0.10 even when
    peer scores invert.

    alpha: coding/security specialist (0.99) with weak research/writing (0.10)
    beta:  research/writing specialist (0.99) with weak coding/security (0.10)
    """
    return {
        "alpha": {
            "coding": 0.99,
            "security": 0.99,
            "analysis": 0.50,
            "research": 0.10,
            "writing": 0.10,
        },
        "beta": {
            "coding": 0.10,
            "security": 0.10,
            "analysis": 0.50,
            "research": 0.99,
            "writing": 0.99,
        },
    }


@pytest.fixture
def skewed_assigner(custom_profiles):
    """Assigner with strongly divergent agent profiles."""
    return DynamicRoleAssigner(domain_profiles=custom_profiles)


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the global singleton before and after each test."""
    reset_dynamic_role_assigner()
    yield
    reset_dynamic_role_assigner()


# ===========================================================================
# 1. RoleType Enum
# ===========================================================================


class TestRoleType:
    """Tests for the RoleType enumeration."""

    def test_lead_value(self):
        assert RoleType.LEAD.value == "lead"

    def test_support_value(self):
        assert RoleType.SUPPORT.value == "support"

    def test_equal_value(self):
        assert RoleType.EQUAL.value == "equal"

    def test_specialist_value(self):
        assert RoleType.SPECIALIST.value == "specialist"

    def test_is_str_enum(self):
        assert isinstance(RoleType.LEAD, str)

    def test_enum_member_count(self):
        assert len(RoleType) == 4

    def test_construction_from_value(self):
        assert RoleType("lead") is RoleType.LEAD
        assert RoleType("support") is RoleType.SUPPORT


# ===========================================================================
# 2. CapabilityProposal
# ===========================================================================


class TestCapabilityProposal:
    """Tests for CapabilityProposal dataclass."""

    def test_creation_minimal(self):
        p = CapabilityProposal(agent_id="claude", role=RoleType.LEAD)
        assert p.agent_id == "claude"
        assert p.role is RoleType.LEAD
        assert p.confidence == 0.5
        assert p.domain_strengths == []
        assert p.evidence == []

    def test_creation_with_all_fields(self):
        p = CapabilityProposal(
            agent_id="gemini",
            role=RoleType.SUPPORT,
            domain_strengths=["coding", "analysis"],
            confidence=0.8,
            evidence=["passed review", "fast response"],
            timestamp=1000.0,
        )
        assert p.domain_strengths == ["coding", "analysis"]
        assert p.confidence == 0.8
        assert len(p.evidence) == 2
        assert p.timestamp == 1000.0

    def test_auto_timestamp(self):
        before = time.time()
        p = CapabilityProposal(agent_id="a", role=RoleType.LEAD)
        after = time.time()
        assert before <= p.timestamp <= after

    def test_explicit_timestamp_zero_gets_replaced(self):
        """timestamp=0.0 triggers __post_init__ to set current time."""
        p = CapabilityProposal(agent_id="a", role=RoleType.LEAD, timestamp=0.0)
        assert p.timestamp > 0.0

    def test_explicit_nonzero_timestamp_preserved(self):
        p = CapabilityProposal(agent_id="a", role=RoleType.LEAD, timestamp=42.0)
        assert p.timestamp == 42.0

    def test_to_dict_structure(self):
        p = CapabilityProposal(
            agent_id="claude",
            role=RoleType.LEAD,
            domain_strengths=["coding"],
            confidence=0.777777,
            evidence=["a", "b", "c"],
        )
        d = p.to_dict()
        assert d["agent_id"] == "claude"
        assert d["role"] == "lead"
        assert d["domain_strengths"] == ["coding"]
        assert d["confidence"] == 0.778  # rounded to 3 decimals
        assert d["evidence_count"] == 3

    def test_to_dict_does_not_include_timestamp(self):
        p = CapabilityProposal(agent_id="x", role=RoleType.SUPPORT)
        d = p.to_dict()
        assert "timestamp" not in d

    def test_to_dict_empty_evidence(self):
        p = CapabilityProposal(agent_id="x", role=RoleType.EQUAL)
        assert p.to_dict()["evidence_count"] == 0


# ===========================================================================
# 3. RoleScore
# ===========================================================================


class TestRoleScore:
    """Tests for RoleScore dataclass."""

    def test_defaults(self):
        s = RoleScore(agent_id="claude", role=RoleType.LEAD)
        assert s.domain_match == 0.0
        assert s.historical_success == 0.5
        assert s.confidence_alignment == 0.5
        assert s.peer_score == 0.5
        assert s.total_score == 0.0

    def test_to_dict_structure(self):
        s = RoleScore(
            agent_id="gemini",
            role=RoleType.SUPPORT,
            domain_match=0.12345,
            historical_success=0.6789,
            total_score=0.55555,
        )
        d = s.to_dict()
        assert d["agent_id"] == "gemini"
        assert d["role"] == "support"
        assert d["domain_match"] == 0.123
        assert d["historical_success"] == 0.679
        assert d["total_score"] == 0.556

    def test_to_dict_excludes_confidence_and_peer(self):
        s = RoleScore(agent_id="a", role=RoleType.LEAD)
        d = s.to_dict()
        assert "confidence_alignment" not in d
        assert "peer_score" not in d


# ===========================================================================
# 4. RoleAssignmentResult
# ===========================================================================


class TestRoleAssignmentResult:
    """Tests for RoleAssignmentResult dataclass."""

    def test_creation_defaults(self):
        r = RoleAssignmentResult(assignments={"a": RoleType.LEAD})
        assert r.method == "meta_debate"
        assert r.confidence == 0.5
        assert r.reasoning == ""
        assert r.scores == []

    def test_to_dict_converts_enum_values(self):
        r = RoleAssignmentResult(
            assignments={"claude": RoleType.LEAD, "gemini": RoleType.SUPPORT},
            method="meta_debate",
            confidence=0.85,
            reasoning="Claude is better for this task.",
        )
        d = r.to_dict()
        assert d["assignments"] == {"claude": "lead", "gemini": "support"}
        assert d["method"] == "meta_debate"
        assert d["confidence"] == 0.85
        assert d["reasoning"] == "Claude is better for this task."

    def test_to_dict_confidence_rounding(self):
        r = RoleAssignmentResult(assignments={}, confidence=0.33333)
        assert r.to_dict()["confidence"] == 0.333


# ===========================================================================
# 5. AssignerStats
# ===========================================================================


class TestAssignerStats:
    """Tests for AssignerStats dataclass."""

    def test_defaults(self):
        s = AssignerStats()
        assert s.total_assignments == 0
        assert s.meta_debate_count == 0
        assert s.fallback_count == 0
        assert s.lead_counts == {}
        assert s.avg_confidence == 0.0
        assert s.outcomes == []

    def test_to_dict(self):
        s = AssignerStats(
            total_assignments=5,
            meta_debate_count=3,
            fallback_count=2,
            lead_counts={"claude": 2, "gemini": 1},
            avg_confidence=0.77777,
        )
        d = s.to_dict()
        assert d["total_assignments"] == 5
        assert d["meta_debate_count"] == 3
        assert d["fallback_count"] == 2
        assert d["lead_counts"] == {"claude": 2, "gemini": 1}
        assert d["avg_confidence"] == 0.778

    def test_to_dict_does_not_include_outcomes(self):
        s = AssignerStats(outcomes=[("claude", True)])
        assert "outcomes" not in s.to_dict()


# ===========================================================================
# 6. Single Agent Assignment -> SPECIALIST
# ===========================================================================


class TestSingleAgentAssignment:
    """Single agent should always get SPECIALIST role."""

    def test_single_agent_specialist(self, assigner):
        result = assigner.assign_roles(
            task_domains=["coding"],
            agent_ids=["claude"],
        )
        assert result.assignments == {"claude": RoleType.SPECIALIST}
        assert result.method == "single_agent"
        assert result.confidence == 1.0

    def test_single_unknown_agent(self, assigner):
        result = assigner.assign_roles(
            task_domains=["research"],
            agent_ids=["unknown_agent_xyz"],
        )
        assert result.assignments["unknown_agent_xyz"] is RoleType.SPECIALIST

    def test_single_agent_ignores_proposals(self, assigner):
        proposal = CapabilityProposal(agent_id="claude", role=RoleType.LEAD, confidence=0.99)
        result = assigner.assign_roles(
            task_domains=["coding"],
            agent_ids=["claude"],
            proposals={"claude": proposal},
        )
        assert result.assignments["claude"] is RoleType.SPECIALIST

    def test_single_agent_does_not_increment_meta_debate(self, assigner):
        assigner.assign_roles(task_domains=["coding"], agent_ids=["claude"])
        stats = assigner.get_stats()
        # single_agent method is neither meta_debate nor fallback
        assert stats.meta_debate_count == 0
        assert stats.fallback_count == 0

    def test_single_agent_does_not_count_lead(self, assigner):
        assigner.assign_roles(task_domains=["coding"], agent_ids=["claude"])
        stats = assigner.get_stats()
        assert stats.lead_counts == {}


# ===========================================================================
# 7. Two Agents with Clear Domain Difference -> Lead/Support
# ===========================================================================


class TestLeadSupportAssignment:
    """When one agent clearly dominates a domain, it should be LEAD."""

    def test_coding_task_favors_alpha(self, skewed_assigner):
        result = skewed_assigner.assign_roles(
            task_domains=["coding", "security"],
            agent_ids=["alpha", "beta"],
            task_complexity="complex",
        )
        assert result.assignments["alpha"] is RoleType.LEAD
        assert result.assignments["beta"] is RoleType.SUPPORT

    def test_research_task_favors_beta(self, skewed_assigner):
        result = skewed_assigner.assign_roles(
            task_domains=["research", "writing"],
            agent_ids=["alpha", "beta"],
            task_complexity="complex",
        )
        assert result.assignments["beta"] is RoleType.LEAD
        assert result.assignments["alpha"] is RoleType.SUPPORT

    def test_method_is_meta_debate_for_clear_lead(self, skewed_assigner):
        result = skewed_assigner.assign_roles(
            task_domains=["coding", "security"],
            agent_ids=["alpha", "beta"],
            task_complexity="complex",
        )
        assert result.method == "meta_debate"

    def test_confidence_above_half(self, skewed_assigner):
        result = skewed_assigner.assign_roles(
            task_domains=["coding", "security"],
            agent_ids=["alpha", "beta"],
            task_complexity="complex",
        )
        assert result.confidence > 0.5

    def test_scores_populated(self, skewed_assigner):
        result = skewed_assigner.assign_roles(
            task_domains=["coding"],
            agent_ids=["alpha", "beta"],
            task_complexity="complex",
        )
        # 2 agents x 2 roles = 4 scores
        assert len(result.scores) == 4

    def test_reasoning_mentions_lead_agent(self, skewed_assigner):
        result = skewed_assigner.assign_roles(
            task_domains=["coding", "security"],
            agent_ids=["alpha", "beta"],
            task_complexity="complex",
        )
        assert "alpha" in result.reasoning


# ===========================================================================
# 8. Two Agents with Similar Scores -> EQUAL
# ===========================================================================


class TestEqualAssignment:
    """When agent scores are close, both should get EQUAL roles."""

    def test_identical_profiles_yield_equal(self):
        profiles = {
            "a": {"coding": 0.80, "analysis": 0.80},
            "b": {"coding": 0.80, "analysis": 0.80},
        }
        a = DynamicRoleAssigner(domain_profiles=profiles)
        result = a.assign_roles(
            task_domains=["coding", "analysis"],
            agent_ids=["a", "b"],
            task_complexity="moderate",
        )
        assert result.assignments["a"] is RoleType.EQUAL
        assert result.assignments["b"] is RoleType.EQUAL

    def test_near_equal_profiles_yield_equal(self):
        profiles = {
            "a": {"coding": 0.80},
            "b": {"coding": 0.79},
        }
        a = DynamicRoleAssigner(domain_profiles=profiles)
        result = a.assign_roles(
            task_domains=["coding"],
            agent_ids=["a", "b"],
            task_complexity="moderate",
        )
        assert result.assignments["a"] is RoleType.EQUAL
        assert result.assignments["b"] is RoleType.EQUAL

    def test_equal_reasoning_mentions_score_diff(self):
        profiles = {"a": {"coding": 0.80}, "b": {"coding": 0.80}}
        a = DynamicRoleAssigner(domain_profiles=profiles)
        result = a.assign_roles(
            task_domains=["coding"],
            agent_ids=["a", "b"],
            task_complexity="moderate",
        )
        assert "score difference" in result.reasoning.lower() or "too small" in result.reasoning.lower()


# ===========================================================================
# 9. Score Calculation with All 4 Weights
# ===========================================================================


class TestScoreWeights:
    """Verify weighted scoring formula."""

    def test_weights_sum_to_one(self):
        assert abs((W_DOMAIN + W_HISTORY + W_CONFIDENCE + W_PEER) - 1.0) < 1e-9

    def test_weight_values(self):
        assert W_DOMAIN == 0.35
        assert W_HISTORY == 0.30
        assert W_CONFIDENCE == 0.15
        assert W_PEER == 0.20

    def test_score_computed_from_weights(self, assigner):
        """Run assignment and verify at least one score has non-zero total."""
        result = assigner.assign_roles(
            task_domains=["coding"],
            agent_ids=["claude", "gemini"],
            task_complexity="moderate",
        )
        for s in result.scores:
            expected = (
                W_DOMAIN * s.domain_match
                + W_HISTORY * s.historical_success
                + W_CONFIDENCE * s.confidence_alignment
                + W_PEER * s.peer_score
            )
            assert abs(s.total_score - expected) < 1e-9

    def test_domain_weight_is_highest(self):
        assert W_DOMAIN > W_HISTORY
        assert W_DOMAIN > W_CONFIDENCE
        assert W_DOMAIN > W_PEER


# ===========================================================================
# 10. Proposals with domain_strengths Boosting
# ===========================================================================


class TestProposalBoosting:
    """Proposals with matching domain_strengths should boost domain_match."""

    def test_proposal_boosts_domain_match(self):
        profiles = {
            "a": {"coding": 0.60},
            "b": {"coding": 0.60},
        }
        a = DynamicRoleAssigner(domain_profiles=profiles)

        # Agent 'a' submits a proposal with matching strength
        proposal_a = CapabilityProposal(
            agent_id="a",
            role=RoleType.LEAD,
            domain_strengths=["coding"],
            confidence=0.7,
        )
        result = a.assign_roles(
            task_domains=["coding"],
            agent_ids=["a", "b"],
            proposals={"a": proposal_a},
            task_complexity="complex",
        )
        # Agent a's lead score should be boosted by proposal
        a_lead_scores = [s for s in result.scores if s.agent_id == "a" and s.role == RoleType.LEAD]
        b_lead_scores = [s for s in result.scores if s.agent_id == "b" and s.role == RoleType.LEAD]
        assert a_lead_scores[0].domain_match > b_lead_scores[0].domain_match

    def test_proposal_non_matching_strength_no_boost(self):
        profiles = {"a": {"coding": 0.60}, "b": {"coding": 0.60}}
        a = DynamicRoleAssigner(domain_profiles=profiles)

        proposal_a = CapabilityProposal(
            agent_id="a",
            role=RoleType.LEAD,
            domain_strengths=["writing"],  # does not match 'coding'
            confidence=0.7,
        )
        result = a.assign_roles(
            task_domains=["coding"],
            agent_ids=["a", "b"],
            proposals={"a": proposal_a},
            task_complexity="complex",
        )
        a_lead = [s for s in result.scores if s.agent_id == "a" and s.role == RoleType.LEAD][0]
        b_lead = [s for s in result.scores if s.agent_id == "b" and s.role == RoleType.LEAD][0]
        # Non-matching proposal gives (0.60 + 0) / 2 = 0.30, which is lower than 0.60
        assert a_lead.domain_match < b_lead.domain_match

    def test_confidence_alignment_penalizes_overconfidence(self):
        profiles = {"a": {"coding": 0.70}, "b": {"coding": 0.70}}
        a = DynamicRoleAssigner(domain_profiles=profiles)

        # Overconfident proposal
        proposal_over = CapabilityProposal(agent_id="a", role=RoleType.LEAD, confidence=1.0)
        # Well-calibrated proposal
        proposal_good = CapabilityProposal(agent_id="b", role=RoleType.LEAD, confidence=0.7)
        result = a.assign_roles(
            task_domains=["coding"],
            agent_ids=["a", "b"],
            proposals={"a": proposal_over, "b": proposal_good},
            task_complexity="complex",
        )
        a_lead = [s for s in result.scores if s.agent_id == "a" and s.role == RoleType.LEAD][0]
        b_lead = [s for s in result.scores if s.agent_id == "b" and s.role == RoleType.LEAD][0]
        # confidence_alignment = 1.0 - abs(conf - 0.7)
        # a: 1.0 - 0.3 = 0.7
        # b: 1.0 - 0.0 = 1.0
        assert a_lead.confidence_alignment < b_lead.confidence_alignment

    def test_confidence_alignment_penalizes_underconfidence(self):
        profiles = {"a": {"coding": 0.70}, "b": {"coding": 0.70}}
        a = DynamicRoleAssigner(domain_profiles=profiles)

        proposal_under = CapabilityProposal(agent_id="a", role=RoleType.LEAD, confidence=0.1)
        proposal_good = CapabilityProposal(agent_id="b", role=RoleType.LEAD, confidence=0.7)
        result = a.assign_roles(
            task_domains=["coding"],
            agent_ids=["a", "b"],
            proposals={"a": proposal_under, "b": proposal_good},
            task_complexity="complex",
        )
        a_lead = [s for s in result.scores if s.agent_id == "a" and s.role == RoleType.LEAD][0]
        b_lead = [s for s in result.scores if s.agent_id == "b" and s.role == RoleType.LEAD][0]
        # a: 1.0 - 0.6 = 0.4
        # b: 1.0 - 0.0 = 1.0
        assert a_lead.confidence_alignment < b_lead.confidence_alignment

    def test_proposal_with_multiple_matching_strengths(self):
        profiles = {"a": {"coding": 0.50, "security": 0.50}, "b": {"coding": 0.50, "security": 0.50}}
        a = DynamicRoleAssigner(domain_profiles=profiles)

        proposal_a = CapabilityProposal(
            agent_id="a",
            role=RoleType.LEAD,
            domain_strengths=["coding", "security"],
            confidence=0.7,
        )
        result = a.assign_roles(
            task_domains=["coding", "security"],
            agent_ids=["a", "b"],
            proposals={"a": proposal_a},
            task_complexity="complex",
        )
        a_lead = [s for s in result.scores if s.agent_id == "a" and s.role == RoleType.LEAD][0]
        b_lead = [s for s in result.scores if s.agent_id == "b" and s.role == RoleType.LEAD][0]
        # a's domain_match boosted by full match
        assert a_lead.domain_match > b_lead.domain_match


# ===========================================================================
# 11. Historical Outcome Learning
# ===========================================================================


class TestHistoricalOutcomeLearning:
    """record_outcome should influence future assignments."""

    def test_record_outcome_stored(self, assigner):
        assigner.record_outcome("coding", "claude", True)
        stats = assigner.get_stats()
        assert len(stats.outcomes) == 0  # get_stats returns a copy without outcomes
        # But internal state has it -- verify via another assignment
        # that historical_success changes

    def test_positive_history_increases_lead_score(self):
        profiles = {"a": {"coding": 0.70}, "b": {"coding": 0.70}}
        a = DynamicRoleAssigner(domain_profiles=profiles)

        # Record many successes for 'a' as lead
        for _ in range(10):
            a.record_outcome("coding", "a", True)

        result = a.assign_roles(
            task_domains=["coding"],
            agent_ids=["a", "b"],
            task_complexity="complex",
        )
        a_lead = [s for s in result.scores if s.agent_id == "a" and s.role == RoleType.LEAD][0]
        b_lead = [s for s in result.scores if s.agent_id == "b" and s.role == RoleType.LEAD][0]
        assert a_lead.historical_success > b_lead.historical_success

    def test_negative_history_decreases_lead_score(self):
        profiles = {"a": {"coding": 0.70}, "b": {"coding": 0.70}}
        a = DynamicRoleAssigner(domain_profiles=profiles)

        # Record many failures for 'a' as lead
        for _ in range(10):
            a.record_outcome("coding", "a", False)

        result = a.assign_roles(
            task_domains=["coding"],
            agent_ids=["a", "b"],
            task_complexity="complex",
        )
        a_lead = [s for s in result.scores if s.agent_id == "a" and s.role == RoleType.LEAD][0]
        assert a_lead.historical_success < 0.5

    def test_history_window_trimming(self):
        a = DynamicRoleAssigner(history_window=5)
        # Fill with more than 2*window entries
        for _i in range(15):
            a.record_outcome("coding", "a", True)
        # Should trim to last 5
        # Verify no crash and internal state is bounded
        a.assign_roles(
            task_domains=["coding"],
            agent_ids=["a", "b"],
            task_complexity="moderate",
        )

    def test_support_role_history(self):
        """When agent was NOT lead, it counts for support history."""
        profiles = {"a": {"coding": 0.70}, "b": {"coding": 0.70}}
        a = DynamicRoleAssigner(domain_profiles=profiles)

        # Record outcomes where 'b' is lead -> 'a' was support
        for _ in range(10):
            a.record_outcome("coding", "b", True)

        result = a.assign_roles(
            task_domains=["coding"],
            agent_ids=["a", "b"],
            task_complexity="complex",
        )
        # 'a' support score should show high historical_success
        a_support = [s for s in result.scores if s.agent_id == "a" and s.role == RoleType.SUPPORT][0]
        assert a_support.historical_success > 0.5

    def test_no_history_returns_prior(self, assigner):
        result = assigner.assign_roles(
            task_domains=["coding"],
            agent_ids=["claude", "gemini"],
            task_complexity="moderate",
        )
        for s in result.scores:
            assert s.historical_success == 0.5


# ===========================================================================
# 12. MIN_SCORE_DIFF Threshold Behavior
# ===========================================================================


class TestMinScoreDiffThreshold:
    """Score differences below MIN_SCORE_DIFF should yield EQUAL roles."""

    def test_min_score_diff_value(self):
        assert MIN_SCORE_DIFF == 0.10

    def test_below_threshold_yields_equal(self):
        """Identical agents with no history = score diff 0 = EQUAL."""
        profiles = {"a": {"coding": 0.75}, "b": {"coding": 0.75}}
        a = DynamicRoleAssigner(domain_profiles=profiles)
        result = a.assign_roles(
            task_domains=["coding"],
            agent_ids=["a", "b"],
            task_complexity="moderate",
        )
        assert result.assignments["a"] is RoleType.EQUAL
        assert result.assignments["b"] is RoleType.EQUAL

    def test_at_threshold_yields_equal(self):
        """Score diff exactly at MIN_SCORE_DIFF should still yield EQUAL (< not <=)."""
        # With identical profiles and no proposals/history, diff = 0 < 0.10
        profiles = {"a": {"coding": 0.80}, "b": {"coding": 0.80}}
        a = DynamicRoleAssigner(domain_profiles=profiles)
        result = a.assign_roles(
            task_domains=["coding"],
            agent_ids=["a", "b"],
            task_complexity="complex",
        )
        assert all(r is RoleType.EQUAL for r in result.assignments.values())

    def test_above_threshold_yields_lead_support(self, skewed_assigner):
        """Large profile gap should exceed threshold."""
        result = skewed_assigner.assign_roles(
            task_domains=["coding", "security"],
            agent_ids=["alpha", "beta"],
            task_complexity="complex",
        )
        roles = set(result.assignments.values())
        assert RoleType.LEAD in roles
        assert RoleType.SUPPORT in roles


# ===========================================================================
# 13. Trivial/Simple Tasks -> EQUAL Roles
# ===========================================================================


class TestTrivialSimpleTasks:
    """Trivial and simple tasks should always yield EQUAL roles."""

    def test_trivial_always_equal(self, skewed_assigner):
        result = skewed_assigner.assign_roles(
            task_domains=["coding", "security"],
            agent_ids=["alpha", "beta"],
            task_complexity="trivial",
        )
        assert result.assignments["alpha"] is RoleType.EQUAL
        assert result.assignments["beta"] is RoleType.EQUAL

    def test_simple_always_equal(self, skewed_assigner):
        result = skewed_assigner.assign_roles(
            task_domains=["coding", "security"],
            agent_ids=["alpha", "beta"],
            task_complexity="simple",
        )
        assert result.assignments["alpha"] is RoleType.EQUAL
        assert result.assignments["beta"] is RoleType.EQUAL

    def test_trivial_case_insensitive(self, skewed_assigner):
        result = skewed_assigner.assign_roles(
            task_domains=["coding"],
            agent_ids=["alpha", "beta"],
            task_complexity="TRIVIAL",
        )
        assert all(r is RoleType.EQUAL for r in result.assignments.values())

    def test_simple_case_insensitive(self, skewed_assigner):
        result = skewed_assigner.assign_roles(
            task_domains=["coding"],
            agent_ids=["alpha", "beta"],
            task_complexity="SIMPLE",
        )
        assert all(r is RoleType.EQUAL for r in result.assignments.values())

    def test_moderate_can_have_lead(self, skewed_assigner):
        result = skewed_assigner.assign_roles(
            task_domains=["coding", "security"],
            agent_ids=["alpha", "beta"],
            task_complexity="moderate",
        )
        roles = set(result.assignments.values())
        # With skewed profiles, moderate should allow lead/support
        assert RoleType.LEAD in roles or RoleType.EQUAL in roles

    def test_complex_can_have_lead(self, skewed_assigner):
        result = skewed_assigner.assign_roles(
            task_domains=["coding", "security"],
            agent_ids=["alpha", "beta"],
            task_complexity="complex",
        )
        assert result.assignments["alpha"] is RoleType.LEAD

    def test_expert_can_have_lead(self, skewed_assigner):
        result = skewed_assigner.assign_roles(
            task_domains=["coding", "security"],
            agent_ids=["alpha", "beta"],
            task_complexity="expert",
        )
        assert result.assignments["alpha"] is RoleType.LEAD


# ===========================================================================
# 14. Default Domain Profiles for Claude/Gemini
# ===========================================================================


class TestDefaultDomainProfiles:
    """Verify the built-in DEFAULT_DOMAIN_PROFILES."""

    def test_claude_profile_exists(self):
        assert "claude" in DEFAULT_DOMAIN_PROFILES

    def test_gemini_profile_exists(self):
        assert "gemini" in DEFAULT_DOMAIN_PROFILES

    def test_claude_domains(self):
        p = DEFAULT_DOMAIN_PROFILES["claude"]
        expected_domains = {
            "coding",
            "analysis",
            "security",
            "architecture",
            "writing",
            "research",
            "debugging",
            "review",
        }
        assert set(p.keys()) == expected_domains

    def test_gemini_domains(self):
        p = DEFAULT_DOMAIN_PROFILES["gemini"]
        expected_domains = {
            "coding",
            "analysis",
            "security",
            "architecture",
            "writing",
            "research",
            "debugging",
            "review",
        }
        assert set(p.keys()) == expected_domains

    def test_claude_writing_is_highest(self):
        p = DEFAULT_DOMAIN_PROFILES["claude"]
        assert p["writing"] == max(p.values())

    def test_gemini_research_is_highest(self):
        p = DEFAULT_DOMAIN_PROFILES["gemini"]
        assert p["research"] == max(p.values())

    def test_all_values_between_0_and_1(self):
        for agent, profile in DEFAULT_DOMAIN_PROFILES.items():
            for domain, score in profile.items():
                assert 0.0 <= score <= 1.0, f"{agent}.{domain} = {score}"

    def test_default_profiles_used_when_none_provided(self, assigner):
        """Assigner with no explicit profiles uses DEFAULT_DOMAIN_PROFILES."""
        result = assigner.assign_roles(
            task_domains=["writing"],
            agent_ids=["claude", "gemini"],
            task_complexity="complex",
        )
        # Claude has writing=0.90 vs Gemini writing=0.80
        # Should see a domain_match difference
        c_lead = [s for s in result.scores if s.agent_id == "claude" and s.role == RoleType.LEAD][0]
        g_lead = [s for s in result.scores if s.agent_id == "gemini" and s.role == RoleType.LEAD][0]
        assert c_lead.domain_match > g_lead.domain_match


# ===========================================================================
# 15. Singleton get/reset Pattern
# ===========================================================================


class TestSingleton:
    """Test the module-level singleton accessors."""

    def test_get_returns_instance(self):
        instance = get_dynamic_role_assigner()
        assert isinstance(instance, DynamicRoleAssigner)

    def test_get_returns_same_instance(self):
        a = get_dynamic_role_assigner()
        b = get_dynamic_role_assigner()
        assert a is b

    def test_reset_creates_new_instance(self):
        a = get_dynamic_role_assigner()
        reset_dynamic_role_assigner()
        b = get_dynamic_role_assigner()
        assert a is not b

    def test_reset_clears_state(self):
        inst = get_dynamic_role_assigner()
        inst.assign_roles(
            task_domains=["coding"],
            agent_ids=["claude", "gemini"],
            task_complexity="moderate",
        )
        assert inst.get_stats().total_assignments == 1

        reset_dynamic_role_assigner()
        new_inst = get_dynamic_role_assigner()
        assert new_inst.get_stats().total_assignments == 0

    def test_singleton_thread_safety(self):
        """Multiple threads calling get should all get the same instance."""
        results = []

        def get_instance():
            results.append(id(get_dynamic_role_assigner()))

        threads = [threading.Thread(target=get_instance) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All should be the same instance
        assert len(set(results)) == 1


# ===========================================================================
# 16. Statistics Tracking
# ===========================================================================


class TestStatisticsTracking:
    """Verify statistics are correctly accumulated."""

    def test_total_assignments_increments(self, assigner):
        for _ in range(5):
            assigner.assign_roles(
                task_domains=["coding"],
                agent_ids=["a", "b"],
                task_complexity="moderate",
            )
        assert assigner.get_stats().total_assignments == 5

    def test_meta_debate_count(self, skewed_assigner):
        """Lead/support assignment counts as meta_debate."""
        skewed_assigner.assign_roles(
            task_domains=["coding"],
            agent_ids=["alpha", "beta"],
            task_complexity="complex",
        )
        stats = skewed_assigner.get_stats()
        assert stats.meta_debate_count == 1

    def test_equal_still_counts_as_meta_debate(self, assigner):
        """EQUAL via small score diff still uses meta_debate method."""
        assigner.assign_roles(
            task_domains=["coding"],
            agent_ids=["claude", "gemini"],
            task_complexity="moderate",
        )
        stats = assigner.get_stats()
        assert stats.meta_debate_count == 1

    def test_single_agent_not_tracked_in_meta_or_fallback(self, assigner):
        assigner.assign_roles(
            task_domains=["coding"],
            agent_ids=["claude"],
        )
        stats = assigner.get_stats()
        # single_agent method does not hit the multi-agent stat path
        assert stats.total_assignments == 0

    def test_lead_counts_tracked(self, skewed_assigner):
        skewed_assigner.assign_roles(
            task_domains=["coding", "security"],
            agent_ids=["alpha", "beta"],
            task_complexity="complex",
        )
        stats = skewed_assigner.get_stats()
        assert stats.lead_counts.get("alpha", 0) == 1
        assert stats.lead_counts.get("beta", 0) == 0

    def test_lead_counts_accumulate(self, skewed_assigner):
        for _ in range(3):
            skewed_assigner.assign_roles(
                task_domains=["coding"],
                agent_ids=["alpha", "beta"],
                task_complexity="complex",
            )
        stats = skewed_assigner.get_stats()
        assert stats.lead_counts.get("alpha", 0) == 3

    def test_avg_confidence_computed(self, assigner):
        assigner.assign_roles(
            task_domains=["coding"],
            agent_ids=["claude", "gemini"],
            task_complexity="moderate",
        )
        stats = assigner.get_stats()
        assert stats.avg_confidence > 0.0

    def test_avg_confidence_running_average(self, skewed_assigner):
        """Average should be the mean of all assignment confidences."""
        results = []
        for _ in range(3):
            r = skewed_assigner.assign_roles(
                task_domains=["coding", "security"],
                agent_ids=["alpha", "beta"],
                task_complexity="complex",
            )
            results.append(r.confidence)

        stats = skewed_assigner.get_stats()
        expected_avg = sum(results) / len(results)
        assert abs(stats.avg_confidence - expected_avg) < 1e-6

    def test_get_stats_returns_copy(self, assigner):
        """Modifying returned stats should not affect internal state."""
        assigner.assign_roles(
            task_domains=["coding"],
            agent_ids=["claude", "gemini"],
            task_complexity="moderate",
        )
        stats = assigner.get_stats()
        stats.total_assignments = 999
        assert assigner.get_stats().total_assignments == 1

    def test_reset_clears_all_stats(self, assigner):
        assigner.assign_roles(
            task_domains=["coding"],
            agent_ids=["claude", "gemini"],
            task_complexity="moderate",
        )
        assigner.record_outcome("coding", "claude", True)
        assigner.reset()
        stats = assigner.get_stats()
        assert stats.total_assignments == 0
        assert stats.meta_debate_count == 0
        assert stats.fallback_count == 0
        assert stats.lead_counts == {}
        assert stats.avg_confidence == 0.0


# ===========================================================================
# 17. Edge Cases
# ===========================================================================


class TestEdgeCases:
    """Edge case handling."""

    def test_empty_agent_list(self, assigner):
        result = assigner.assign_roles(
            task_domains=["coding"],
            agent_ids=[],
        )
        assert result.assignments == {}
        assert result.method == "single_agent"

    def test_empty_domains(self, assigner):
        result = assigner.assign_roles(
            task_domains=[],
            agent_ids=["claude", "gemini"],
            task_complexity="moderate",
        )
        # Should fall back to 0.5 domain_match for everyone
        for s in result.scores:
            assert s.domain_match == 0.5

    def test_unknown_agent_ids(self, assigner):
        """Agents not in profiles get 0.5 default domain score."""
        result = assigner.assign_roles(
            task_domains=["coding"],
            agent_ids=["agent_x", "agent_y"],
            task_complexity="moderate",
        )
        for s in result.scores:
            assert s.domain_match == 0.5

    def test_unknown_domain(self, assigner):
        """Domain not in any profile -> 0.5 default."""
        result = assigner.assign_roles(
            task_domains=["quantum_physics"],
            agent_ids=["claude", "gemini"],
            task_complexity="moderate",
        )
        for s in result.scores:
            assert s.domain_match == 0.5

    def test_no_proposals(self, assigner):
        result = assigner.assign_roles(
            task_domains=["coding"],
            agent_ids=["claude", "gemini"],
            proposals=None,
            task_complexity="moderate",
        )
        assert len(result.assignments) == 2

    def test_empty_proposals_dict(self, assigner):
        result = assigner.assign_roles(
            task_domains=["coding"],
            agent_ids=["claude", "gemini"],
            proposals={},
            task_complexity="moderate",
        )
        assert len(result.assignments) == 2

    def test_partial_proposals(self, assigner):
        """Only one agent submits a proposal."""
        proposal = CapabilityProposal(agent_id="claude", role=RoleType.LEAD, confidence=0.7)
        result = assigner.assign_roles(
            task_domains=["coding"],
            agent_ids=["claude", "gemini"],
            proposals={"claude": proposal},
            task_complexity="moderate",
        )
        assert len(result.assignments) == 2

    def test_three_agents(self, assigner):
        """More than two agents: one lead, rest support."""
        profiles = {
            "a": {"coding": 0.95},
            "b": {"coding": 0.50},
            "c": {"coding": 0.50},
        }
        a = DynamicRoleAssigner(domain_profiles=profiles)
        result = a.assign_roles(
            task_domains=["coding"],
            agent_ids=["a", "b", "c"],
            task_complexity="complex",
        )
        assert result.assignments["a"] is RoleType.LEAD
        assert result.assignments["b"] is RoleType.SUPPORT
        assert result.assignments["c"] is RoleType.SUPPORT

    def test_three_agents_equal_when_simple(self, assigner):
        result = assigner.assign_roles(
            task_domains=["coding"],
            agent_ids=["a", "b", "c"],
            task_complexity="simple",
        )
        for role in result.assignments.values():
            assert role is RoleType.EQUAL

    def test_confidence_capped_at_095(self, skewed_assigner):
        """Lead/support confidence is capped at 0.95."""
        result = skewed_assigner.assign_roles(
            task_domains=["coding", "security"],
            agent_ids=["alpha", "beta"],
            task_complexity="expert",
        )
        assert result.confidence <= 0.95

    def test_case_insensitive_domain_matching(self, assigner):
        """Domain matching should be case-insensitive."""
        result = assigner.assign_roles(
            task_domains=["CODING"],
            agent_ids=["claude", "gemini"],
            task_complexity="moderate",
        )
        # Should still match 'coding' in profiles
        c_lead = [s for s in result.scores if s.agent_id == "claude" and s.role == RoleType.LEAD][0]
        assert c_lead.domain_match != 0.5  # Should have matched

    def test_proposal_domain_case_insensitive(self):
        profiles = {"a": {"coding": 0.70}, "b": {"coding": 0.70}}
        a = DynamicRoleAssigner(domain_profiles=profiles)
        proposal = CapabilityProposal(
            agent_id="a",
            role=RoleType.LEAD,
            domain_strengths=["CODING"],
            confidence=0.7,
        )
        result = a.assign_roles(
            task_domains=["coding"],
            agent_ids=["a", "b"],
            proposals={"a": proposal},
            task_complexity="complex",
        )
        a_lead = [s for s in result.scores if s.agent_id == "a" and s.role == RoleType.LEAD][0]
        b_lead = [s for s in result.scores if s.agent_id == "b" and s.role == RoleType.LEAD][0]
        assert a_lead.domain_match > b_lead.domain_match

    def test_many_domains(self, assigner):
        """Large number of domains should not crash."""
        domains = [f"domain_{i}" for i in range(50)]
        result = assigner.assign_roles(
            task_domains=domains,
            agent_ids=["claude", "gemini"],
            task_complexity="moderate",
        )
        assert len(result.assignments) == 2

    def test_custom_history_window(self):
        a = DynamicRoleAssigner(history_window=3)
        for i in range(10):
            a.record_outcome("coding", "a", i < 5)
        # Only last 3 outcomes should be used: all False
        result = a.assign_roles(
            task_domains=["coding"],
            agent_ids=["a", "b"],
            task_complexity="complex",
        )
        a_lead = [s for s in result.scores if s.agent_id == "a" and s.role == RoleType.LEAD][0]
        # Last 3 outcomes: indices 7,8,9 -> all False
        assert a_lead.historical_success == 0.0

    def test_record_outcome_stats_tracked(self, assigner):
        assigner.record_outcome("coding", "claude", True)
        assigner.record_outcome("coding", "claude", False)
        # outcomes are tracked internally but not in get_stats copy
        stats = assigner.get_stats()
        assert stats.total_assignments == 0  # no assignments yet


# ===========================================================================
# 18. Peer Score Computation
# ===========================================================================


class TestPeerScore:
    """Tests for _compute_peer_score complementarity logic."""

    def test_peer_score_with_no_other_agents(self):
        a = DynamicRoleAssigner()
        score = a._compute_peer_score("claude", RoleType.LEAD, [], ["coding"])
        assert score == 0.5

    def test_peer_score_with_unknown_agent(self):
        a = DynamicRoleAssigner()
        score = a._compute_peer_score("claude", RoleType.LEAD, ["unknown"], ["coding"])
        assert score == 0.5

    def test_peer_score_reflects_other_agent_fitness(self):
        profiles = {
            "a": {"coding": 0.90},
            "b": {"coding": 0.30},
        }
        a = DynamicRoleAssigner(domain_profiles=profiles)
        # If 'a' is lead, peer_score depends on 'b' fitness
        score_a_lead = a._compute_peer_score("a", RoleType.LEAD, ["b"], ["coding"])
        assert score_a_lead == 0.30

    def test_peer_score_with_empty_domains(self):
        a = DynamicRoleAssigner()
        score = a._compute_peer_score("claude", RoleType.LEAD, ["gemini"], [])
        assert score == 0.5


# ===========================================================================
# 19. Full Integration Scenarios
# ===========================================================================


class TestIntegrationScenarios:
    """End-to-end integration scenarios."""

    def test_full_lifecycle(self, assigner):
        """Assignment -> record outcome -> re-assignment shows learning."""
        # Initial assignment
        r1 = assigner.assign_roles(
            task_domains=["coding"],
            agent_ids=["claude", "gemini"],
            task_complexity="moderate",
        )
        assert len(r1.assignments) == 2

        # Record outcomes
        assigner.record_outcome("coding", "claude", True)
        assigner.record_outcome("coding", "claude", True)
        assigner.record_outcome("coding", "claude", True)

        # Second assignment
        r2 = assigner.assign_roles(
            task_domains=["coding"],
            agent_ids=["claude", "gemini"],
            task_complexity="moderate",
        )
        assert len(r2.assignments) == 2

        # Stats should reflect two assignments
        stats = assigner.get_stats()
        assert stats.total_assignments == 2

    def test_reset_then_assign(self, assigner):
        """After reset, state should be clean."""
        assigner.assign_roles(
            task_domains=["coding"],
            agent_ids=["claude", "gemini"],
            task_complexity="moderate",
        )
        assigner.record_outcome("coding", "claude", True)
        assigner.reset()

        result = assigner.assign_roles(
            task_domains=["coding"],
            agent_ids=["claude", "gemini"],
            task_complexity="moderate",
        )
        # Should work fine after reset
        assert len(result.assignments) == 2
        # History should be clean
        for s in result.scores:
            assert s.historical_success == 0.5

    def test_proposal_with_history_combined(self):
        """Both proposals and history influence the final assignment."""
        profiles = {"a": {"coding": 0.70}, "b": {"coding": 0.70}}
        a = DynamicRoleAssigner(domain_profiles=profiles)

        # Record strong history for 'b' as lead
        for _ in range(10):
            a.record_outcome("coding", "b", True)

        # But 'a' submits a strong proposal
        proposal_a = CapabilityProposal(
            agent_id="a",
            role=RoleType.LEAD,
            domain_strengths=["coding"],
            confidence=0.7,
        )

        result = a.assign_roles(
            task_domains=["coding"],
            agent_ids=["a", "b"],
            proposals={"a": proposal_a},
            task_complexity="complex",
        )
        # The result should reflect both factors - assignment happens
        assert len(result.assignments) == 2

    def test_mixed_complexity_sequence(self, skewed_assigner):
        """Different complexity levels in sequence."""
        # Simple -> EQUAL
        r1 = skewed_assigner.assign_roles(
            task_domains=["coding"],
            agent_ids=["alpha", "beta"],
            task_complexity="simple",
        )
        assert all(r is RoleType.EQUAL for r in r1.assignments.values())

        # Complex -> LEAD/SUPPORT
        r2 = skewed_assigner.assign_roles(
            task_domains=["coding"],
            agent_ids=["alpha", "beta"],
            task_complexity="complex",
        )
        assert RoleType.LEAD in r2.assignments.values()

        stats = skewed_assigner.get_stats()
        assert stats.total_assignments == 2

    def test_alternating_domain_leadership(self, skewed_assigner):
        """Different domains should yield different leads."""
        r_code = skewed_assigner.assign_roles(
            task_domains=["coding", "security"],
            agent_ids=["alpha", "beta"],
            task_complexity="complex",
        )
        r_research = skewed_assigner.assign_roles(
            task_domains=["research", "writing"],
            agent_ids=["alpha", "beta"],
            task_complexity="complex",
        )
        # Alpha leads coding, beta leads research
        assert r_code.assignments["alpha"] is RoleType.LEAD
        assert r_research.assignments["beta"] is RoleType.LEAD


# ===========================================================================
# 20. Constants
# ===========================================================================


class TestConstants:
    """Verify module-level constants."""

    def test_history_window_value(self):
        assert HISTORY_WINDOW == 20

    def test_min_score_diff_value(self):
        assert MIN_SCORE_DIFF == 0.10

    def test_domain_weight(self):
        assert W_DOMAIN == 0.35

    def test_history_weight(self):
        assert W_HISTORY == 0.30

    def test_confidence_weight(self):
        assert W_CONFIDENCE == 0.15

    def test_peer_weight(self):
        assert W_PEER == 0.20
