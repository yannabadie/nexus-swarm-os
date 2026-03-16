"""
Tests for V12.4 Consensus Tracker.

Validates:
- Position creation and to_dict
- TopicConsensus scoring (simple, weighted, unanimous)
- Disagreement detection
- ConsensusReport generation
- Record positions
- Consensus queries (topic, phase, session)
- Phase conclusion readiness
- Should debate check
- Session cleanup
- State management
- Global singleton
- Module exports
"""

from core.intelligence.hive_mind.consensus_tracker import (
    ConsensusTracker,
    Disagreement,
    Position,
    TopicConsensus,
    get_consensus_tracker,
    reset_consensus_tracker,
)

# =============================================================================
# Position Tests
# =============================================================================


class TestPosition:
    """Test Position dataclass."""

    def test_basic(self):
        p = Position(agent_id="claude", stance="approach_A")
        assert p.agent_id == "claude"
        assert p.stance == "approach_A"

    def test_auto_timestamp(self):
        p = Position(agent_id="a", stance="x")
        assert p.timestamp > 0

    def test_defaults(self):
        p = Position(agent_id="a", stance="x")
        assert p.confidence == 1.0
        assert p.reasoning == ""

    def test_to_dict(self):
        p = Position(agent_id="claude", stance="A", confidence=0.9, reasoning="because")
        d = p.to_dict()
        assert d["agent_id"] == "claude"
        assert d["stance"] == "A"
        assert d["confidence"] == 0.9


# =============================================================================
# TopicConsensus Tests
# =============================================================================


class TestTopicConsensus:
    """Test TopicConsensus scoring."""

    def test_empty(self):
        tc = TopicConsensus(topic="t", phase="p")
        assert tc.consensus_score == 1.0
        assert tc.is_unanimous is True

    def test_single_position(self):
        tc = TopicConsensus(
            topic="t",
            phase="p",
            positions=[
                Position(agent_id="a", stance="X"),
            ],
        )
        assert tc.consensus_score == 1.0

    def test_unanimous(self):
        tc = TopicConsensus(
            topic="t",
            phase="p",
            positions=[
                Position(agent_id="claude", stance="A"),
                Position(agent_id="gemini", stance="A"),
            ],
        )
        assert tc.consensus_score == 1.0
        assert tc.is_unanimous is True

    def test_split(self):
        tc = TopicConsensus(
            topic="t",
            phase="p",
            positions=[
                Position(agent_id="claude", stance="A"),
                Position(agent_id="gemini", stance="B"),
            ],
        )
        assert tc.consensus_score == 0.5
        assert tc.is_unanimous is False

    def test_majority(self):
        tc = TopicConsensus(
            topic="t",
            phase="p",
            positions=[
                Position(agent_id="a", stance="X"),
                Position(agent_id="b", stance="X"),
                Position(agent_id="c", stance="Y"),
            ],
        )
        assert abs(tc.consensus_score - 2 / 3) < 0.01

    def test_weighted_consensus(self):
        tc = TopicConsensus(
            topic="t",
            phase="p",
            positions=[
                Position(agent_id="claude", stance="A", confidence=0.9),
                Position(agent_id="gemini", stance="B", confidence=0.1),
            ],
        )
        # Weighted: 0.9/(0.9+0.1) = 0.9
        assert tc.weighted_consensus == 0.9

    def test_unique_stances(self):
        tc = TopicConsensus(
            topic="t",
            phase="p",
            positions=[
                Position(agent_id="a", stance="X"),
                Position(agent_id="b", stance="Y"),
                Position(agent_id="c", stance="X"),
            ],
        )
        assert len(tc.unique_stances) == 2

    def test_to_dict(self):
        tc = TopicConsensus(
            topic="approach",
            phase="analysis",
            positions=[
                Position(agent_id="a", stance="X"),
            ],
        )
        d = tc.to_dict()
        assert d["topic"] == "approach"
        assert d["phase"] == "analysis"
        assert d["consensus_score"] == 1.0


# =============================================================================
# Disagreement Tests
# =============================================================================


class TestDisagreement:
    """Test Disagreement dataclass."""

    def test_to_dict(self):
        d = Disagreement(
            topic="approach",
            phase="analysis",
            stances={"claude": "A", "gemini": "B"},
            severity=0.5,
        )
        dd = d.to_dict()
        assert dd["topic"] == "approach"
        assert dd["severity"] == 0.5


# =============================================================================
# Record Tests
# =============================================================================


class TestRecord:
    """Test position recording."""

    def test_record_basic(self):
        t = ConsensusTracker()
        pos = t.record("s1", "analysis", "claude", "approach_A")
        assert pos.agent_id == "claude"
        assert pos.stance == "approach_A"

    def test_record_with_confidence(self):
        t = ConsensusTracker()
        pos = t.record("s1", "analysis", "claude", "A", confidence=0.8)
        assert pos.confidence == 0.8

    def test_record_clamped_confidence(self):
        t = ConsensusTracker()
        pos = t.record("s1", "p", "a", "X", confidence=1.5)
        assert pos.confidence == 1.0

    def test_record_replaces_same_agent(self):
        t = ConsensusTracker()
        t.record("s1", "analysis", "claude", "A")
        t.record("s1", "analysis", "claude", "B")
        tc = t.get_topic_consensus("s1", "analysis", "default")
        assert tc.agent_count == 1
        assert tc.positions[0].stance == "B"

    def test_record_custom_topic(self):
        t = ConsensusTracker()
        t.record("s1", "debate", "claude", "yes", topic="use_redis")
        tc = t.get_topic_consensus("s1", "debate", "use_redis")
        assert tc is not None


# =============================================================================
# Consensus Query Tests
# =============================================================================


class TestConsensusQueries:
    """Test consensus queries."""

    def test_topic_consensus_full_agreement(self):
        t = ConsensusTracker()
        t.record("s1", "analysis", "claude", "A")
        t.record("s1", "analysis", "gemini", "A")
        assert t.get_consensus_score("s1", "analysis") == 1.0

    def test_topic_consensus_disagreement(self):
        t = ConsensusTracker()
        t.record("s1", "analysis", "claude", "A")
        t.record("s1", "analysis", "gemini", "B")
        assert t.get_consensus_score("s1", "analysis") == 0.5

    def test_topic_consensus_missing(self):
        t = ConsensusTracker()
        assert t.get_consensus_score("s1", "analysis") == 0.0

    def test_phase_consensus(self):
        t = ConsensusTracker()
        t.record("s1", "analysis", "claude", "A", topic="t1")
        t.record("s1", "analysis", "gemini", "A", topic="t1")
        t.record("s1", "analysis", "claude", "X", topic="t2")
        t.record("s1", "analysis", "gemini", "Y", topic="t2")
        # t1 = 1.0, t2 = 0.5 => avg 0.75
        assert abs(t.get_phase_consensus("s1", "analysis") - 0.75) < 0.01

    def test_phase_consensus_empty(self):
        t = ConsensusTracker()
        assert t.get_phase_consensus("s1", "missing") == 0.0

    def test_session_consensus(self):
        t = ConsensusTracker()
        t.record("s1", "analysis", "claude", "A")
        t.record("s1", "analysis", "gemini", "A")
        t.record("s1", "debate", "claude", "X")
        t.record("s1", "debate", "gemini", "Y")
        # analysis = 1.0, debate = 0.5 => avg 0.75
        assert abs(t.get_session_consensus("s1") - 0.75) < 0.01

    def test_session_consensus_empty(self):
        t = ConsensusTracker()
        assert t.get_session_consensus("missing") == 0.0


# =============================================================================
# Disagreement Query Tests
# =============================================================================


class TestDisagreementQueries:
    """Test disagreement detection."""

    def test_no_disagreements(self):
        t = ConsensusTracker()
        t.record("s1", "analysis", "claude", "A")
        t.record("s1", "analysis", "gemini", "A")
        assert t.get_disagreements("s1") == []

    def test_disagreement_found(self):
        t = ConsensusTracker()
        t.record("s1", "analysis", "claude", "A")
        t.record("s1", "analysis", "gemini", "B")
        disputes = t.get_disagreements("s1")
        assert len(disputes) == 1
        assert disputes[0].stances["claude"] == "A"
        assert disputes[0].stances["gemini"] == "B"

    def test_disagreement_filtered_by_phase(self):
        t = ConsensusTracker()
        t.record("s1", "analysis", "claude", "A")
        t.record("s1", "analysis", "gemini", "B")
        t.record("s1", "debate", "claude", "X")
        t.record("s1", "debate", "gemini", "Y")
        disputes = t.get_disagreements("s1", phase="analysis")
        assert len(disputes) == 1
        assert disputes[0].phase == "analysis"

    def test_disagreement_severity(self):
        t = ConsensusTracker()
        t.record("s1", "analysis", "claude", "A")
        t.record("s1", "analysis", "gemini", "B")
        disputes = t.get_disagreements("s1")
        assert disputes[0].severity == 0.5  # 1.0 - 0.5 = 0.5

    def test_disagreements_sorted_by_severity(self):
        t = ConsensusTracker()
        # 3-way split = more severe
        t.record("s1", "p", "a", "X", topic="t1")
        t.record("s1", "p", "b", "Y", topic="t1")
        t.record("s1", "p", "c", "Z", topic="t1")
        # 2-way majority = less severe
        t.record("s1", "p", "a", "A", topic="t2")
        t.record("s1", "p", "b", "A", topic="t2")
        t.record("s1", "p", "c", "B", topic="t2")
        disputes = t.get_disagreements("s1")
        assert disputes[0].severity >= disputes[1].severity


# =============================================================================
# Phase Control Tests
# =============================================================================


class TestPhaseControl:
    """Test phase conclusion checks."""

    def test_can_conclude_full_consensus(self):
        t = ConsensusTracker()
        t.record("s1", "analysis", "claude", "A")
        t.record("s1", "analysis", "gemini", "A")
        assert t.can_conclude_phase("s1", "analysis") is True

    def test_cannot_conclude_low_consensus(self):
        t = ConsensusTracker()
        t.record("s1", "analysis", "claude", "A")
        t.record("s1", "analysis", "gemini", "B")
        assert t.can_conclude_phase("s1", "analysis") is False

    def test_can_conclude_custom_threshold(self):
        t = ConsensusTracker()
        t.record("s1", "p", "a", "X")
        t.record("s1", "p", "b", "Y")
        assert t.can_conclude_phase("s1", "p", min_consensus=0.4) is True

    def test_should_debate(self):
        t = ConsensusTracker()
        t.record("s1", "analysis", "claude", "A")
        t.record("s1", "analysis", "gemini", "B")
        assert t.should_debate("s1", "analysis") is True

    def test_should_not_debate(self):
        t = ConsensusTracker()
        t.record("s1", "analysis", "claude", "A")
        t.record("s1", "analysis", "gemini", "A")
        assert t.should_debate("s1", "analysis") is False


# =============================================================================
# Report Tests
# =============================================================================


class TestReport:
    """Test consensus reports."""

    def test_empty_report(self):
        t = ConsensusTracker()
        report = t.get_report("empty")
        assert report.total_topics == 0
        assert report.overall_consensus == 0.0

    def test_report_with_data(self):
        t = ConsensusTracker()
        t.record("s1", "analysis", "claude", "A")
        t.record("s1", "analysis", "gemini", "A")
        t.record("s1", "debate", "claude", "X")
        t.record("s1", "debate", "gemini", "Y")
        report = t.get_report("s1")
        assert report.total_topics == 2
        assert report.unanimous_topics == 1
        assert report.disputed_topics == 1
        assert "analysis" in report.phase_consensus
        assert "debate" in report.phase_consensus

    def test_report_to_dict(self):
        t = ConsensusTracker()
        t.record("s1", "p", "a", "X")
        report = t.get_report("s1")
        d = report.to_dict()
        assert "session_id" in d
        assert "overall_consensus" in d
        assert "phase_consensus" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_session_count(self):
        t = ConsensusTracker()
        t.record("s1", "p", "a", "X")
        t.record("s2", "p", "a", "X")
        assert t.session_count == 2

    def test_topic_count(self):
        t = ConsensusTracker()
        t.record("s1", "p1", "a", "X", topic="t1")
        t.record("s1", "p1", "a", "X", topic="t2")
        t.record("s1", "p2", "a", "X", topic="t3")
        assert t.topic_count("s1") == 3

    def test_clear_session(self):
        t = ConsensusTracker()
        t.record("s1", "p", "a", "X")
        assert t.clear_session("s1") is True
        assert t.session_count == 0

    def test_clear_session_not_found(self):
        t = ConsensusTracker()
        assert t.clear_session("missing") is False

    def test_clear(self):
        t = ConsensusTracker()
        t.record("s1", "p", "a", "X")
        t.record("s2", "p", "a", "X")
        t.clear()
        assert t.session_count == 0

    def test_to_dict(self):
        t = ConsensusTracker()
        d = t.to_dict()
        assert "session_count" in d
        assert "min_consensus" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global consensus tracker."""

    def test_get_consensus_tracker(self):
        reset_consensus_tracker()
        tracker = get_consensus_tracker()
        assert isinstance(tracker, ConsensusTracker)

    def test_singleton(self):
        reset_consensus_tracker()
        t1 = get_consensus_tracker()
        t2 = get_consensus_tracker()
        assert t1 is t2

    def test_reset(self):
        reset_consensus_tracker()
        t1 = get_consensus_tracker()
        reset_consensus_tracker()
        t2 = get_consensus_tracker()
        assert t1 is not t2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_hive_mind_package(self):
        from core.intelligence.hive_mind import (
            ConsensusReport,
            ConsensusTracker,
            TopicConsensus,
            get_consensus_tracker,
            reset_consensus_tracker,
        )

        assert all(
            [
                ConsensusTracker,
                TopicConsensus,
                ConsensusReport,
                get_consensus_tracker,
                reset_consensus_tracker,
            ]
        )

    def test_from_module(self):
        from core.intelligence.hive_mind.consensus_tracker import (
            DEFAULT_MIN_CONSENSUS,
        )

        assert DEFAULT_MIN_CONSENSUS == 0.8
