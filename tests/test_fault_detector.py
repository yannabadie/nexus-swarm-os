"""
Comprehensive tests for the FaultDetector module.

Tests cover:
- AgentStatus enum values
- OutputRecord dataclass construction and defaults
- FaultStatus fields, is_faulty, is_trusted properties
- DetectorStats dataclass
- record_output: basic recording, confidence clamping
- check_agent: insufficient data (UNKNOWN), reliable (TRUSTED),
  unreliable (FAULTY), borderline (SUSPECT)
- Overconfidence escalation: SUSPECT + high overconfidence -> FAULTY
- Overconfidence computation: high confidence on wrong outputs
- Trust score computation and get_trust_score shorthand
- get_weighted_vote: trust-weighted voting
- get_stats: tracking counts, faulty agents list
- MAX_HISTORY: capped at 100
- Multiple agents tracked independently
- Singleton pattern (get_fault_detector / reset_fault_detector)
- Edge cases: all correct, all wrong, perfect calibration
"""

import threading
import time

import pytest

from core.intelligence.reasoning.fault_detector import (
    AgentStatus,
    DetectorStats,
    FaultDetector,
    FaultStatus,
    OutputRecord,
    get_fault_detector,
    reset_fault_detector,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def detector():
    """Fresh FaultDetector for each test."""
    return FaultDetector()


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the module-level singleton before and after every test."""
    reset_fault_detector()
    yield
    reset_fault_detector()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _record_n(
    detector: FaultDetector, agent_id: str, n: int, confidence: float = 0.8, was_correct: bool = True
) -> None:
    """Record *n* identical outputs for an agent."""
    for _ in range(n):
        detector.record_output(agent_id, confidence, was_correct)


def _record_mixed(
    detector: FaultDetector,
    agent_id: str,
    correct: int,
    incorrect: int,
    correct_conf: float = 0.8,
    incorrect_conf: float = 0.8,
) -> None:
    """Record a mix of correct and incorrect outputs."""
    for _ in range(correct):
        detector.record_output(agent_id, correct_conf, True)
    for _ in range(incorrect):
        detector.record_output(agent_id, incorrect_conf, False)


# ===========================================================================
# 1. AgentStatus enum
# ===========================================================================


class TestAgentStatus:
    def test_trusted_value(self):
        assert AgentStatus.TRUSTED.value == "trusted"

    def test_suspect_value(self):
        assert AgentStatus.SUSPECT.value == "suspect"

    def test_faulty_value(self):
        assert AgentStatus.FAULTY.value == "faulty"

    def test_unknown_value(self):
        assert AgentStatus.UNKNOWN.value == "unknown"

    def test_member_count(self):
        assert len(AgentStatus) == 4


# ===========================================================================
# 2. OutputRecord dataclass
# ===========================================================================


class TestOutputRecord:
    def test_fields(self):
        rec = OutputRecord(agent_id="a", confidence=0.9, was_correct=True)
        assert rec.agent_id == "a"
        assert rec.confidence == 0.9
        assert rec.was_correct is True

    def test_timestamp_default(self):
        before = time.time()
        rec = OutputRecord(agent_id="a", confidence=0.5, was_correct=False)
        after = time.time()
        assert before <= rec.timestamp <= after

    def test_explicit_timestamp(self):
        rec = OutputRecord(agent_id="a", confidence=0.5, was_correct=True, timestamp=1.0)
        assert rec.timestamp == 1.0


# ===========================================================================
# 3. FaultStatus fields and properties
# ===========================================================================


class TestFaultStatus:
    def test_fields(self):
        fs = FaultStatus(
            agent_id="x",
            status=AgentStatus.TRUSTED,
            trust_score=0.9,
            fault_rate=0.05,
            overconfidence_score=0.1,
            observations=10,
            reason="ok",
        )
        assert fs.agent_id == "x"
        assert fs.trust_score == 0.9
        assert fs.fault_rate == 0.05
        assert fs.overconfidence_score == 0.1
        assert fs.observations == 10
        assert fs.reason == "ok"

    def test_is_faulty_true(self):
        fs = FaultStatus("x", AgentStatus.FAULTY, 0.1, 0.5, 0.3, 10, "bad")
        assert fs.is_faulty is True

    def test_is_faulty_false_for_trusted(self):
        fs = FaultStatus("x", AgentStatus.TRUSTED, 0.9, 0.05, 0.0, 10, "ok")
        assert fs.is_faulty is False

    def test_is_faulty_false_for_suspect(self):
        fs = FaultStatus("x", AgentStatus.SUSPECT, 0.6, 0.3, 0.2, 10, "meh")
        assert fs.is_faulty is False

    def test_is_faulty_false_for_unknown(self):
        fs = FaultStatus("x", AgentStatus.UNKNOWN, 0.5, 0.0, 0.0, 2, "?")
        assert fs.is_faulty is False

    def test_is_trusted_true(self):
        fs = FaultStatus("x", AgentStatus.TRUSTED, 0.9, 0.05, 0.0, 10, "ok")
        assert fs.is_trusted is True

    def test_is_trusted_false_for_faulty(self):
        fs = FaultStatus("x", AgentStatus.FAULTY, 0.1, 0.5, 0.3, 10, "bad")
        assert fs.is_trusted is False

    def test_is_trusted_false_for_suspect(self):
        fs = FaultStatus("x", AgentStatus.SUSPECT, 0.6, 0.3, 0.2, 10, "meh")
        assert fs.is_trusted is False

    def test_is_trusted_false_for_unknown(self):
        fs = FaultStatus("x", AgentStatus.UNKNOWN, 0.5, 0.0, 0.0, 2, "?")
        assert fs.is_trusted is False


# ===========================================================================
# 4. DetectorStats dataclass
# ===========================================================================


class TestDetectorStats:
    def test_fields(self):
        ds = DetectorStats(
            total_observations=42,
            agents_tracked=["a", "b"],
            faulty_agents=["b"],
            avg_trust_score=0.75,
        )
        assert ds.total_observations == 42
        assert ds.agents_tracked == ["a", "b"]
        assert ds.faulty_agents == ["b"]
        assert ds.avg_trust_score == 0.75

    def test_empty_stats(self):
        ds = DetectorStats(0, [], [], 0.0)
        assert ds.total_observations == 0
        assert ds.agents_tracked == []


# ===========================================================================
# 5. record_output: basic recording and confidence clamping
# ===========================================================================


class TestRecordOutput:
    def test_basic_recording(self, detector):
        detector.record_output("agent1", 0.8, True)
        assert detector._total_observations == 1
        assert len(detector._history["agent1"]) == 1

    def test_multiple_recordings(self, detector):
        _record_n(detector, "agent1", 3)
        assert detector._total_observations == 3
        assert len(detector._history["agent1"]) == 3

    def test_confidence_clamped_above_one(self, detector):
        detector.record_output("a", 1.5, True)
        assert detector._history["a"][-1].confidence == 1.0

    def test_confidence_clamped_below_zero(self, detector):
        detector.record_output("a", -0.3, False)
        assert detector._history["a"][-1].confidence == 0.0

    def test_confidence_at_boundaries(self, detector):
        detector.record_output("a", 0.0, True)
        detector.record_output("a", 1.0, False)
        assert detector._history["a"][0].confidence == 0.0
        assert detector._history["a"][1].confidence == 1.0

    def test_records_correct_flag(self, detector):
        detector.record_output("a", 0.5, True)
        detector.record_output("a", 0.5, False)
        assert detector._history["a"][0].was_correct is True
        assert detector._history["a"][1].was_correct is False


# ===========================================================================
# 6. check_agent: insufficient data -> UNKNOWN
# ===========================================================================


class TestCheckAgentUnknown:
    def test_no_observations(self, detector):
        status = detector.check_agent("new_agent")
        assert status.status == AgentStatus.UNKNOWN
        assert status.observations == 0
        assert status.trust_score == 0.5
        assert "Insufficient" in status.reason

    def test_below_min_observations(self, detector):
        _record_n(detector, "a", FaultDetector.MIN_OBSERVATIONS - 1)
        status = detector.check_agent("a")
        assert status.status == AgentStatus.UNKNOWN
        assert status.observations == FaultDetector.MIN_OBSERVATIONS - 1

    def test_exactly_min_minus_one(self, detector):
        _record_n(detector, "a", 4)
        status = detector.check_agent("a")
        assert status.status == AgentStatus.UNKNOWN

    def test_unknown_fault_rate_zero(self, detector):
        _record_n(detector, "a", 3)
        status = detector.check_agent("a")
        assert status.fault_rate == 0.0

    def test_unknown_overconfidence_zero(self, detector):
        _record_n(detector, "a", 2)
        status = detector.check_agent("a")
        assert status.overconfidence_score == 0.0


# ===========================================================================
# 7. check_agent: reliable agent -> TRUSTED
# ===========================================================================


class TestCheckAgentTrusted:
    def test_all_correct(self, detector):
        _record_n(detector, "good", 10, confidence=0.8, was_correct=True)
        status = detector.check_agent("good")
        assert status.status == AgentStatus.TRUSTED
        assert status.fault_rate == 0.0

    def test_mostly_correct(self, detector):
        # 1 wrong out of 10 = 10% fault rate, below SUSPECT_THRESHOLD (25%)
        _record_mixed(detector, "good", correct=9, incorrect=1)
        status = detector.check_agent("good")
        assert status.status == AgentStatus.TRUSTED
        assert status.fault_rate == pytest.approx(0.1)

    def test_exactly_at_trusted_boundary(self, detector):
        # 24% fault rate (just below SUSPECT_THRESHOLD of 25%)
        # 24 out of 100 incorrect ~ tricky exact boundary; use 6 correct, 0 wrong out of 25
        # Instead: 5 correct + some incorrect to get below 0.25
        # Let's do 4 wrong out of 20 = 0.20
        _record_mixed(detector, "edge", correct=16, incorrect=4)
        status = detector.check_agent("edge")
        assert status.status == AgentStatus.TRUSTED
        assert status.fault_rate == pytest.approx(0.2)

    def test_trusted_has_high_trust_score(self, detector):
        _record_n(detector, "good", 10, confidence=0.8, was_correct=True)
        status = detector.check_agent("good")
        assert status.trust_score > 0.7

    def test_trusted_reason_mentions_acceptable(self, detector):
        _record_n(detector, "good", 10)
        status = detector.check_agent("good")
        assert "acceptable" in status.reason.lower()


# ===========================================================================
# 8. check_agent: unreliable -> FAULTY
# ===========================================================================


class TestCheckAgentFaulty:
    def test_all_wrong(self, detector):
        _record_n(detector, "bad", 10, confidence=0.8, was_correct=False)
        status = detector.check_agent("bad")
        assert status.status == AgentStatus.FAULTY
        assert status.fault_rate == 1.0

    def test_above_fault_threshold(self, detector):
        # 5 wrong out of 10 = 50% > 40% FAULT_THRESHOLD
        _record_mixed(detector, "bad", correct=5, incorrect=5)
        status = detector.check_agent("bad")
        assert status.status == AgentStatus.FAULTY
        assert status.fault_rate == pytest.approx(0.5)

    def test_exactly_at_fault_threshold(self, detector):
        # 40% fault rate = FAULT_THRESHOLD exactly, >=
        # 2 wrong out of 5 = 0.4
        _record_mixed(detector, "edge", correct=3, incorrect=2)
        status = detector.check_agent("edge")
        assert status.status == AgentStatus.FAULTY
        assert status.fault_rate == pytest.approx(0.4)

    def test_faulty_has_low_trust_score(self, detector):
        _record_n(detector, "bad", 10, confidence=0.9, was_correct=False)
        status = detector.check_agent("bad")
        assert status.trust_score < 0.3

    def test_faulty_reason_mentions_exceeds(self, detector):
        _record_mixed(detector, "bad", correct=3, incorrect=5)
        status = detector.check_agent("bad")
        assert "exceeds" in status.reason.lower()


# ===========================================================================
# 9. check_agent: borderline -> SUSPECT
# ===========================================================================


class TestCheckAgentSuspect:
    def test_suspect_range(self, detector):
        # 30% fault rate: between 25% and 40%
        # 3 wrong out of 10, low confidence on wrong to avoid overconfidence escalation
        _record_mixed(detector, "sus", correct=7, incorrect=3, correct_conf=0.8, incorrect_conf=0.5)
        status = detector.check_agent("sus")
        assert status.status == AgentStatus.SUSPECT
        assert status.fault_rate == pytest.approx(0.3)

    def test_exactly_at_suspect_threshold(self, detector):
        # 25% fault rate = SUSPECT_THRESHOLD exactly, >=
        # 5 wrong out of 20, low confidence on wrong to avoid overconfidence escalation
        _record_mixed(detector, "edge", correct=15, incorrect=5, correct_conf=0.8, incorrect_conf=0.5)
        status = detector.check_agent("edge")
        assert status.status == AgentStatus.SUSPECT
        assert status.fault_rate == pytest.approx(0.25)

    def test_suspect_reason_mentions_elevated(self, detector):
        _record_mixed(detector, "sus", correct=7, incorrect=3, correct_conf=0.8, incorrect_conf=0.5)
        status = detector.check_agent("sus")
        assert "elevated" in status.reason.lower()

    def test_suspect_trust_score_moderate(self, detector):
        _record_mixed(detector, "sus", correct=7, incorrect=3, correct_conf=0.7, incorrect_conf=0.3)
        status = detector.check_agent("sus")
        # Should be somewhere between faulty-low and trusted-high
        assert 0.2 < status.trust_score < 0.8


# ===========================================================================
# 10. Overconfidence escalation: SUSPECT + overconfidence -> FAULTY
# ===========================================================================


class TestOverconfidenceEscalation:
    def test_suspect_with_high_overconfidence_becomes_faulty(self, detector):
        # 30% fault rate -> would be SUSPECT
        # But wrong outputs at confidence 1.0 -> overconfidence = (1.0-0.5)*2 = 1.0
        _record_mixed(detector, "oc", correct=7, incorrect=3, correct_conf=0.8, incorrect_conf=1.0)
        status = detector.check_agent("oc")
        assert status.status == AgentStatus.FAULTY
        assert status.overconfidence_score > 0.5

    def test_suspect_with_low_overconfidence_stays_suspect(self, detector):
        # 30% fault rate + low confidence on wrong outputs
        _record_mixed(detector, "oc", correct=7, incorrect=3, correct_conf=0.8, incorrect_conf=0.5)
        status = detector.check_agent("oc")
        # overconfidence = (0.5 - 0.5) * 2 = 0.0, not > 0.5
        assert status.status == AgentStatus.SUSPECT

    def test_escalation_reason_mentions_overconfidence(self, detector):
        _record_mixed(detector, "oc", correct=7, incorrect=3, correct_conf=0.7, incorrect_conf=1.0)
        status = detector.check_agent("oc")
        assert "overconfidence" in status.reason.lower()

    def test_faulty_agent_not_double_escalated(self, detector):
        # Already FAULTY from fault_rate alone -> overconfidence irrelevant
        _record_mixed(detector, "f", correct=3, incorrect=7, correct_conf=0.5, incorrect_conf=1.0)
        status = detector.check_agent("f")
        assert status.status == AgentStatus.FAULTY
        # Reason should mention "exceeds", not "overconfidence" for the primary reason
        assert "exceeds" in status.reason.lower()

    def test_trusted_with_high_overconfidence_stays_trusted(self, detector):
        # Fault rate below SUSPECT_THRESHOLD so escalation condition never applies
        # Need some wrong outputs to generate overconfidence
        # 1 wrong out of 10 = 10% fault rate (TRUSTED) but that 1 output has conf=1.0
        _record_mixed(detector, "t", correct=9, incorrect=1, correct_conf=0.8, incorrect_conf=1.0)
        status = detector.check_agent("t")
        # Status should be TRUSTED because escalation only triggers from SUSPECT
        assert status.status == AgentStatus.TRUSTED


# ===========================================================================
# 11. Overconfidence computation
# ===========================================================================


class TestOverconfidenceComputation:
    def test_no_wrong_outputs(self, detector):
        _record_n(detector, "a", 10, confidence=0.9, was_correct=True)
        status = detector.check_agent("a")
        assert status.overconfidence_score == 0.0

    def test_high_confidence_wrong(self, detector):
        # All wrong at confidence 1.0 -> overconfidence = (1.0-0.5)*2 = 1.0
        _record_n(detector, "a", 10, confidence=1.0, was_correct=False)
        status = detector.check_agent("a")
        assert status.overconfidence_score == pytest.approx(1.0)

    def test_medium_confidence_wrong(self, detector):
        # All wrong at confidence 0.75 -> overconfidence = (0.75-0.5)*2 = 0.5
        _record_n(detector, "a", 10, confidence=0.75, was_correct=False)
        status = detector.check_agent("a")
        assert status.overconfidence_score == pytest.approx(0.5)

    def test_low_confidence_wrong(self, detector):
        # All wrong at confidence 0.3 -> (0.3-0.5)*2 = -0.4 -> clamped to 0.0
        _record_n(detector, "a", 10, confidence=0.3, was_correct=False)
        status = detector.check_agent("a")
        assert status.overconfidence_score == pytest.approx(0.0)

    def test_at_threshold_confidence(self, detector):
        # All wrong at confidence 0.5 -> (0.5-0.5)*2 = 0.0
        _record_n(detector, "a", 10, confidence=0.5, was_correct=False)
        status = detector.check_agent("a")
        assert status.overconfidence_score == pytest.approx(0.0)

    def test_mixed_wrong_confidences(self, detector):
        # 5 correct + 5 wrong at varying confidence
        for _ in range(5):
            detector.record_output("a", 0.8, True)
        # Wrong outputs: 0.6, 0.7, 0.8, 0.9, 1.0 -> avg = 0.8
        for conf in [0.6, 0.7, 0.8, 0.9, 1.0]:
            detector.record_output("a", conf, False)
        status = detector.check_agent("a")
        # overconfidence = (0.8 - 0.5) * 2.0 = 0.6
        assert status.overconfidence_score == pytest.approx(0.6)


# ===========================================================================
# 12. Trust score computation
# ===========================================================================


class TestTrustScoreComputation:
    def test_perfect_agent_high_trust(self, detector):
        _record_n(detector, "a", 10, confidence=0.9, was_correct=True)
        status = detector.check_agent("a")
        # base_trust=1.0, recency_factor=1.0, penalty=0
        # trust = 1.0*0.5 + 1.0*0.3 - 0 = 0.8
        assert status.trust_score == pytest.approx(0.8)

    def test_always_wrong_low_trust(self, detector):
        _record_n(detector, "a", 10, confidence=0.5, was_correct=False)
        status = detector.check_agent("a")
        # base_trust=0.0, recency_factor=0.0, overconfidence=0.0 => penalty=0
        # trust = 0.0*0.5 + 0.0*0.3 - 0 = 0.0
        assert status.trust_score == pytest.approx(0.0)

    def test_trust_score_clamped_to_zero(self, detector):
        # Very overconfident wrong outputs could push negative, should clamp to 0
        _record_n(detector, "a", 10, confidence=1.0, was_correct=False)
        status = detector.check_agent("a")
        assert status.trust_score >= 0.0

    def test_trust_score_clamped_to_one(self, detector):
        # Trust should never exceed 1.0
        _record_n(detector, "a", 10, confidence=0.9, was_correct=True)
        status = detector.check_agent("a")
        assert status.trust_score <= 1.0

    def test_recency_weighting(self, detector):
        # 5 wrong outputs first, then 5 correct outputs
        _record_n(detector, "a", 5, confidence=0.8, was_correct=False)
        _record_n(detector, "a", 5, confidence=0.8, was_correct=True)
        status_recent_good = detector.check_agent("a")

        # 5 correct outputs first, then 5 wrong outputs
        detector2 = FaultDetector()
        _record_n(detector2, "b", 5, confidence=0.8, was_correct=True)
        _record_n(detector2, "b", 5, confidence=0.8, was_correct=False)
        status_recent_bad = detector2.check_agent("b")

        # Same fault_rate (50%) but different recency -> different trust
        assert status_recent_good.fault_rate == status_recent_bad.fault_rate
        assert status_recent_good.trust_score > status_recent_bad.trust_score

    def test_overconfidence_penalty_lowers_trust(self, detector):
        # Compare two agents with same fault rate but different wrong-confidence
        _record_mixed(detector, "low_oc", correct=5, incorrect=5, correct_conf=0.8, incorrect_conf=0.3)
        _record_mixed(detector, "high_oc", correct=5, incorrect=5, correct_conf=0.8, incorrect_conf=1.0)
        trust_low = detector.check_agent("low_oc").trust_score
        trust_high = detector.check_agent("high_oc").trust_score
        assert trust_low > trust_high


# ===========================================================================
# 13. get_trust_score shorthand
# ===========================================================================


class TestGetTrustScore:
    def test_returns_same_as_check_agent(self, detector):
        _record_n(detector, "a", 10, confidence=0.8, was_correct=True)
        assert detector.get_trust_score("a") == detector.check_agent("a").trust_score

    def test_unknown_agent_returns_half(self, detector):
        assert detector.get_trust_score("nobody") == 0.5

    def test_faulty_agent_low_trust(self, detector):
        _record_n(detector, "bad", 10, confidence=0.9, was_correct=False)
        assert detector.get_trust_score("bad") < 0.3


# ===========================================================================
# 14. get_weighted_vote
# ===========================================================================


class TestGetWeightedVote:
    def test_basic_vote(self, detector):
        # Two unknown agents voting differently -> both get 0.5 trust
        result = detector.get_weighted_vote({"a": "yes", "b": "no"})
        assert result["yes"] == pytest.approx(0.5)
        assert result["no"] == pytest.approx(0.5)

    def test_trusted_agent_vote_weighs_more(self, detector):
        _record_n(detector, "good", 10, confidence=0.8, was_correct=True)
        # "good" has trust ~0.8, "new" has trust 0.5
        result = detector.get_weighted_vote({"good": "yes", "new": "yes"})
        # Both vote "yes", sum should be > 1.0
        assert result["yes"] > 1.0

    def test_faulty_agent_vote_weighs_less(self, detector):
        _record_n(detector, "bad", 10, confidence=0.9, was_correct=False)
        _record_n(detector, "good", 10, confidence=0.8, was_correct=True)
        result = detector.get_weighted_vote({"bad": "yes", "good": "no"})
        assert result["no"] > result["yes"]

    def test_empty_votes(self, detector):
        result = detector.get_weighted_vote({})
        assert result == {}

    def test_all_same_vote(self, detector):
        result = detector.get_weighted_vote({"a": "X", "b": "X", "c": "X"})
        # All unknown agents, each contributes 0.5
        assert result["X"] == pytest.approx(1.5)

    def test_single_voter(self, detector):
        result = detector.get_weighted_vote({"a": "yes"})
        assert "yes" in result
        assert result["yes"] == pytest.approx(0.5)


# ===========================================================================
# 15. get_stats
# ===========================================================================


class TestGetStats:
    def test_empty_detector(self, detector):
        stats = detector.get_stats()
        assert stats.total_observations == 0
        assert stats.agents_tracked == []
        assert stats.faulty_agents == []
        assert stats.avg_trust_score == 0.0

    def test_single_agent(self, detector):
        _record_n(detector, "a", 10, confidence=0.8, was_correct=True)
        stats = detector.get_stats()
        assert stats.total_observations == 10
        assert stats.agents_tracked == ["a"]
        assert stats.faulty_agents == []
        assert stats.avg_trust_score > 0.0

    def test_faulty_agents_listed(self, detector):
        _record_n(detector, "bad", 10, confidence=0.9, was_correct=False)
        _record_n(detector, "good", 10, confidence=0.8, was_correct=True)
        stats = detector.get_stats()
        assert "bad" in stats.faulty_agents
        assert "good" not in stats.faulty_agents

    def test_total_observations_accurate(self, detector):
        _record_n(detector, "a", 5)
        _record_n(detector, "b", 7)
        stats = detector.get_stats()
        assert stats.total_observations == 12

    def test_agents_tracked(self, detector):
        _record_n(detector, "alpha", 1)
        _record_n(detector, "beta", 1)
        _record_n(detector, "gamma", 1)
        stats = detector.get_stats()
        assert set(stats.agents_tracked) == {"alpha", "beta", "gamma"}

    def test_avg_trust_score_calculation(self, detector):
        # All correct = high trust, so avg_trust > 0.5
        _record_n(detector, "a", 10, confidence=0.8, was_correct=True)
        _record_n(detector, "b", 10, confidence=0.8, was_correct=True)
        stats = detector.get_stats()
        assert stats.avg_trust_score > 0.5


# ===========================================================================
# 16. MAX_HISTORY: capped at 100
# ===========================================================================


class TestMaxHistory:
    def test_history_capped(self, detector):
        _record_n(detector, "a", 150)
        assert len(detector._history["a"]) == FaultDetector.MAX_HISTORY

    def test_total_observations_not_capped(self, detector):
        _record_n(detector, "a", 150)
        assert detector._total_observations == 150

    def test_oldest_records_evicted(self, detector):
        # Record 100 correct, then 5 wrong; only last 100 remain
        _record_n(detector, "a", 100, confidence=0.8, was_correct=True)
        _record_n(detector, "a", 5, confidence=0.8, was_correct=False)
        assert len(detector._history["a"]) == 100
        # The 5 newest should be wrong
        wrong_count = sum(1 for r in list(detector._history["a"])[-5:] if not r.was_correct)
        assert wrong_count == 5

    def test_check_agent_uses_capped_history(self, detector):
        # 95 correct + 5 wrong in the window -> fault_rate = 5%
        _record_n(detector, "a", 200, confidence=0.8, was_correct=True)
        _record_n(detector, "a", 5, confidence=0.8, was_correct=False)
        # Window has 100 records: last 5 wrong, first 95 correct
        status = detector.check_agent("a")
        assert status.fault_rate == pytest.approx(5 / 100)


# ===========================================================================
# 17. Multiple agents tracked independently
# ===========================================================================


class TestMultipleAgents:
    def test_independent_histories(self, detector):
        _record_n(detector, "a", 10, confidence=0.8, was_correct=True)
        _record_n(detector, "b", 10, confidence=0.8, was_correct=False)
        assert detector.check_agent("a").status == AgentStatus.TRUSTED
        assert detector.check_agent("b").status == AgentStatus.FAULTY

    def test_recording_one_agent_doesnt_affect_other(self, detector):
        _record_n(detector, "a", 10)
        status_b = detector.check_agent("b")
        assert status_b.status == AgentStatus.UNKNOWN
        assert status_b.observations == 0

    def test_three_agents_different_statuses(self, detector):
        _record_n(detector, "good", 10, confidence=0.8, was_correct=True)
        _record_mixed(detector, "sus", correct=7, incorrect=3, correct_conf=0.8, incorrect_conf=0.4)
        _record_n(detector, "bad", 10, confidence=0.9, was_correct=False)

        assert detector.check_agent("good").status == AgentStatus.TRUSTED
        assert detector.check_agent("sus").status == AgentStatus.SUSPECT
        assert detector.check_agent("bad").status == AgentStatus.FAULTY


# ===========================================================================
# 18. Singleton pattern
# ===========================================================================


class TestSingleton:
    def test_get_returns_instance(self):
        d = get_fault_detector()
        assert isinstance(d, FaultDetector)

    def test_same_instance_returned(self):
        d1 = get_fault_detector()
        d2 = get_fault_detector()
        assert d1 is d2

    def test_reset_creates_new_instance(self):
        d1 = get_fault_detector()
        reset_fault_detector()
        d2 = get_fault_detector()
        assert d1 is not d2

    def test_reset_clears_data(self):
        d = get_fault_detector()
        d.record_output("a", 0.8, True)
        reset_fault_detector()
        d2 = get_fault_detector()
        assert d2._total_observations == 0

    def test_concurrent_get(self):
        """Multiple threads calling get_fault_detector get the same instance."""
        results = []

        def _get():
            results.append(get_fault_detector())

        threads = [threading.Thread(target=_get) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert all(r is results[0] for r in results)


# ===========================================================================
# 19. Edge cases
# ===========================================================================


class TestEdgeCases:
    def test_all_correct_outputs(self, detector):
        _record_n(detector, "perf", 20, confidence=0.9, was_correct=True)
        status = detector.check_agent("perf")
        assert status.status == AgentStatus.TRUSTED
        assert status.fault_rate == 0.0
        assert status.overconfidence_score == 0.0

    def test_all_wrong_outputs(self, detector):
        _record_n(detector, "fail", 20, confidence=0.9, was_correct=False)
        status = detector.check_agent("fail")
        assert status.status == AgentStatus.FAULTY
        assert status.fault_rate == 1.0

    def test_perfect_calibration_no_overconfidence(self, detector):
        # Agent says 0.5 confidence and is wrong 50% of time
        _record_mixed(detector, "cal", correct=5, incorrect=5, correct_conf=0.5, incorrect_conf=0.5)
        status = detector.check_agent("cal")
        assert status.overconfidence_score == pytest.approx(0.0)

    def test_zero_confidence_on_wrong(self, detector):
        _record_mixed(detector, "humble", correct=5, incorrect=5, correct_conf=0.8, incorrect_conf=0.0)
        status = detector.check_agent("humble")
        assert status.overconfidence_score == pytest.approx(0.0)

    def test_exactly_min_observations(self, detector):
        _record_n(detector, "a", FaultDetector.MIN_OBSERVATIONS, confidence=0.8, was_correct=True)
        status = detector.check_agent("a")
        assert status.status != AgentStatus.UNKNOWN

    def test_agent_id_special_characters(self, detector):
        _record_n(detector, "agent-1/v2@test", 10, confidence=0.8, was_correct=True)
        status = detector.check_agent("agent-1/v2@test")
        assert status.agent_id == "agent-1/v2@test"
        assert status.status == AgentStatus.TRUSTED

    def test_agent_id_empty_string(self, detector):
        _record_n(detector, "", 10, confidence=0.8, was_correct=True)
        status = detector.check_agent("")
        assert status.agent_id == ""
        assert status.status == AgentStatus.TRUSTED

    def test_observation_count_matches(self, detector):
        _record_n(detector, "a", 7)
        status = detector.check_agent("a")
        assert status.observations == 7

    def test_weighted_vote_with_mixed_trust(self, detector):
        _record_n(detector, "good", 10, confidence=0.8, was_correct=True)
        _record_n(detector, "bad", 10, confidence=0.9, was_correct=False)
        result = detector.get_weighted_vote({"good": "A", "bad": "B"})
        # Good agent's vote should carry more weight
        assert result["A"] > result["B"]

    def test_check_agent_returns_correct_agent_id(self, detector):
        _record_n(detector, "myagent", 10)
        status = detector.check_agent("myagent")
        assert status.agent_id == "myagent"

    def test_thread_safety_record_output(self, detector):
        """Concurrent record_output calls should not lose data."""

        def _record():
            for _ in range(50):
                detector.record_output("shared", 0.8, True)

        threads = [threading.Thread(target=_record) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert detector._total_observations == 200

    def test_stats_avg_trust_with_no_agents(self, detector):
        stats = detector.get_stats()
        # Division by max(0,1) prevents ZeroDivisionError
        assert stats.avg_trust_score == 0.0


# ===========================================================================
# 20. Constants verification
# ===========================================================================


class TestConstants:
    def test_min_observations(self):
        assert FaultDetector.MIN_OBSERVATIONS == 5

    def test_fault_threshold(self):
        assert FaultDetector.FAULT_THRESHOLD == 0.4

    def test_suspect_threshold(self):
        assert FaultDetector.SUSPECT_THRESHOLD == 0.25

    def test_overconfidence_penalty(self):
        assert FaultDetector.OVERCONFIDENCE_PENALTY == 0.3

    def test_max_history(self):
        assert FaultDetector.MAX_HISTORY == 100

    def test_trust_decay(self):
        assert FaultDetector.TRUST_DECAY == 0.95
