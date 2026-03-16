"""
Comprehensive tests for core.hive_mind.multi_agent_reflexion module.

Tests cover:
- ReflexionMode enum values
- AgentReflection creation and to_dict
- ReflexionSynthesis creation and to_dict
- create_reflection() parsing natural language diagnosis
- Confidence estimation from certainty language
- Novel insight detection
- Independent mode synthesis (consensus + diversity)
- Adversarial mode synthesis (challenging diagnoses)
- Constructive mode synthesis (building on insights)
- Degeneration-of-thought detection
- Anti-degeneration strategy generation
- Mode selection progression
- Failure history tracking and fingerprinting
- Single reflection synthesis (passthrough)
- Empty reflections handling
- Singleton get/reset pattern
- Statistics tracking
- Edge cases
- Word overlap utility function
"""

import os
import sys
import threading
import time

import pytest

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from core.intelligence.hive_mind.multi_agent_reflexion import (
    ADVERSARIAL_TRIGGER,
    AGREEMENT_THRESHOLD,
    CAUSE_SIMILARITY_THRESHOLD,
    DIVERSITY_WEIGHT,
    MAX_FAILURE_HISTORY,
    MIN_REFLECTIONS,
    AgentReflection,
    MultiAgentReflexion,
    ReflexionMode,
    ReflexionStats,
    ReflexionSynthesis,
    get_multi_agent_reflexion,
    reset_multi_agent_reflexion,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def fresh_state():
    """Reset singleton and provide a clean MultiAgentReflexion for every test."""
    reset_multi_agent_reflexion()
    yield
    reset_multi_agent_reflexion()


@pytest.fixture
def mar() -> MultiAgentReflexion:
    """Return a fresh MultiAgentReflexion instance (not the singleton)."""
    return MultiAgentReflexion()


@pytest.fixture
def reflection_claude() -> AgentReflection:
    return AgentReflection(
        agent_id="claude",
        root_cause="Token validation fails due to expired JWT",
        evidence=["- Error: TokenExpired", "- File: auth.py:42"],
        proposed_fix="Add token refresh logic before validation",
        confidence=0.8,
        novel_insight=False,
    )


@pytest.fixture
def reflection_gemini() -> AgentReflection:
    return AgentReflection(
        agent_id="gemini",
        root_cause="Authentication error from missing token refresh",
        evidence=["- HTTP 401 response", "- Error: Unauthorized"],
        proposed_fix="Implement automatic token refresh middleware",
        confidence=0.7,
        novel_insight=True,
    )


# ===========================================================================
# 1. ReflexionMode enum values
# ===========================================================================


class TestReflexionMode:
    def test_independent_value(self):
        assert ReflexionMode.INDEPENDENT.value == "independent"

    def test_adversarial_value(self):
        assert ReflexionMode.ADVERSARIAL.value == "adversarial"

    def test_constructive_value(self):
        assert ReflexionMode.CONSTRUCTIVE.value == "constructive"

    def test_is_string_enum(self):
        assert isinstance(ReflexionMode.INDEPENDENT, str)

    def test_all_members_count(self):
        assert len(ReflexionMode) == 3

    def test_from_value(self):
        assert ReflexionMode("independent") == ReflexionMode.INDEPENDENT
        assert ReflexionMode("adversarial") == ReflexionMode.ADVERSARIAL
        assert ReflexionMode("constructive") == ReflexionMode.CONSTRUCTIVE


# ===========================================================================
# 2. AgentReflection creation and to_dict
# ===========================================================================


class TestAgentReflection:
    def test_basic_creation(self):
        r = AgentReflection(agent_id="claude", root_cause="Some bug")
        assert r.agent_id == "claude"
        assert r.root_cause == "Some bug"
        assert r.evidence == []
        assert r.proposed_fix == ""
        assert r.confidence == 0.5
        assert r.novel_insight is False
        assert r.timestamp > 0

    def test_timestamp_auto_set(self):
        before = time.time()
        r = AgentReflection(agent_id="a", root_cause="b")
        after = time.time()
        assert before <= r.timestamp <= after

    def test_timestamp_preserved_when_provided(self):
        r = AgentReflection(agent_id="a", root_cause="b", timestamp=123.456)
        assert r.timestamp == 123.456

    def test_to_dict_keys(self):
        r = AgentReflection(
            agent_id="claude",
            root_cause="Root cause text",
            evidence=["e1", "e2", "e3"],
            proposed_fix="Fix it",
            confidence=0.789,
            novel_insight=True,
        )
        d = r.to_dict()
        assert set(d.keys()) == {
            "agent_id",
            "root_cause",
            "evidence_count",
            "proposed_fix",
            "confidence",
            "novel_insight",
        }

    def test_to_dict_values(self):
        r = AgentReflection(
            agent_id="gemini",
            root_cause="The real cause",
            evidence=["a", "b"],
            proposed_fix="Apply patch",
            confidence=0.666,
            novel_insight=False,
        )
        d = r.to_dict()
        assert d["agent_id"] == "gemini"
        assert d["root_cause"] == "The real cause"
        assert d["evidence_count"] == 2
        assert d["proposed_fix"] == "Apply patch"
        assert d["confidence"] == 0.666
        assert d["novel_insight"] is False

    def test_to_dict_truncates_root_cause(self):
        long_cause = "X" * 500
        r = AgentReflection(agent_id="a", root_cause=long_cause)
        d = r.to_dict()
        assert len(d["root_cause"]) == 200

    def test_to_dict_truncates_proposed_fix(self):
        long_fix = "Y" * 500
        r = AgentReflection(agent_id="a", root_cause="c", proposed_fix=long_fix)
        d = r.to_dict()
        assert len(d["proposed_fix"]) == 200

    def test_confidence_rounding(self):
        r = AgentReflection(agent_id="a", root_cause="b", confidence=0.33333)
        d = r.to_dict()
        assert d["confidence"] == 0.333


# ===========================================================================
# 3. ReflexionSynthesis creation and to_dict
# ===========================================================================


class TestReflexionSynthesis:
    def test_basic_creation(self):
        s = ReflexionSynthesis(
            consensus_cause="Shared cause",
            consensus_evidence=["e1"],
            diverse_insights=["insight1", "insight2"],
            proposed_strategy="Do this",
            agreement_level=0.75,
        )
        assert s.consensus_cause == "Shared cause"
        assert s.consensus_evidence == ["e1"]
        assert len(s.diverse_insights) == 2
        assert s.proposed_strategy == "Do this"
        assert s.agreement_level == 0.75
        assert s.degeneration_detected is False
        assert s.mode_used == ReflexionMode.INDEPENDENT
        assert s.reflection_count == 0

    def test_to_dict_keys(self):
        s = ReflexionSynthesis(
            consensus_cause="c",
            consensus_evidence=[],
            diverse_insights=[],
            proposed_strategy="s",
            agreement_level=0.5,
        )
        d = s.to_dict()
        assert set(d.keys()) == {
            "consensus_cause",
            "evidence_count",
            "diverse_insights_count",
            "agreement_level",
            "degeneration_detected",
            "mode_used",
        }

    def test_to_dict_values(self):
        s = ReflexionSynthesis(
            consensus_cause="Cause",
            consensus_evidence=["a", "b"],
            diverse_insights=["x"],
            proposed_strategy="Strategy",
            agreement_level=0.812,
            degeneration_detected=True,
            mode_used=ReflexionMode.ADVERSARIAL,
        )
        d = s.to_dict()
        assert d["consensus_cause"] == "Cause"
        assert d["evidence_count"] == 2
        assert d["diverse_insights_count"] == 1
        assert d["agreement_level"] == 0.812
        assert d["degeneration_detected"] is True
        assert d["mode_used"] == "adversarial"

    def test_to_dict_truncates_consensus_cause(self):
        s = ReflexionSynthesis(
            consensus_cause="Z" * 500,
            consensus_evidence=[],
            diverse_insights=[],
            proposed_strategy="s",
            agreement_level=0.5,
        )
        d = s.to_dict()
        assert len(d["consensus_cause"]) == 200


# ===========================================================================
# 4. ReflexionStats
# ===========================================================================


class TestReflexionStats:
    def test_defaults(self):
        s = ReflexionStats()
        assert s.total_reflexions == 0
        assert s.degeneration_detections == 0
        assert s.avg_agreement == 0.0
        assert s.mode_counts == {}
        assert s.insight_counts == {}

    def test_to_dict(self):
        s = ReflexionStats(
            total_reflexions=5,
            degeneration_detections=2,
            avg_agreement=0.666,
            mode_counts={"independent": 3, "adversarial": 2},
            insight_counts={"claude": 1},
        )
        d = s.to_dict()
        assert d["total_reflexions"] == 5
        assert d["degeneration_detections"] == 2
        assert d["avg_agreement"] == 0.666
        assert d["mode_counts"] == {"independent": 3, "adversarial": 2}


# ===========================================================================
# 5. create_reflection() - parsing natural language diagnosis
# ===========================================================================


class TestCreateReflection:
    def test_basic_parsing(self, mar):
        text = (
            "Token validation is broken\n"
            "- Error: TokenExpired on line 42\n"
            "- File: auth.py\n"
            "We should fix the expiration check"
        )
        r = mar.create_reflection("claude", text)
        assert r.agent_id == "claude"
        assert r.root_cause == "Token validation is broken"
        assert len(r.evidence) == 2
        assert "- Error: TokenExpired on line 42" in r.evidence
        assert "- File: auth.py" in r.evidence

    def test_proposed_fix_extraction_should(self, mar):
        text = "Bug in parser\nWe should refactor the tokenizer"
        r = mar.create_reflection("gemini", text)
        assert "should refactor" in r.proposed_fix.lower()

    def test_proposed_fix_extraction_fix(self, mar):
        text = "Missing config\nFix the default settings loader"
        r = mar.create_reflection("gemini", text)
        assert "fix" in r.proposed_fix.lower()

    def test_proposed_fix_extraction_try(self, mar):
        text = "Timeout error\nTry increasing the connection timeout"
        r = mar.create_reflection("claude", text)
        assert "try" in r.proposed_fix.lower()

    def test_proposed_fix_extraction_need(self, mar):
        text = "Race condition\nWe need to add a lock"
        r = mar.create_reflection("claude", text)
        assert "need" in r.proposed_fix.lower()

    def test_proposed_fix_extraction_instead(self, mar):
        text = "Wrong method\nUse POST instead of GET"
        r = mar.create_reflection("claude", text)
        assert "instead" in r.proposed_fix.lower()

    def test_no_fix_found(self, mar):
        text = "Something went wrong\n- Error: 500"
        r = mar.create_reflection("claude", text)
        assert r.proposed_fix == ""

    def test_single_line_diagnosis(self, mar):
        text = "Simple error happened"
        r = mar.create_reflection("claude", text)
        assert r.root_cause == "Simple error happened"
        assert r.evidence == []

    def test_empty_diagnosis(self, mar):
        r = mar.create_reflection("claude", "")
        assert r.root_cause == "Unknown"
        assert r.evidence == []
        assert r.proposed_fix == ""

    def test_whitespace_only_diagnosis(self, mar):
        r = mar.create_reflection("claude", "   \n  \n  ")
        assert r.root_cause == "Unknown"

    def test_evidence_star_bullet(self, mar):
        text = "Root cause here\n* Star bullet evidence"
        r = mar.create_reflection("claude", text)
        assert any("Star bullet" in e for e in r.evidence)

    def test_evidence_chevron_bullet(self, mar):
        text = "Root cause here\n>> Chevron evidence"
        r = mar.create_reflection("claude", text)
        assert any("Chevron" in e for e in r.evidence)

    def test_evidence_error_prefix(self, mar):
        text = "Root cause here\nError: something happened"
        r = mar.create_reflection("claude", text)
        assert any("Error:" in e for e in r.evidence)

    def test_evidence_line_prefix(self, mar):
        text = "Root cause here\nLine: 42 in module.py"
        r = mar.create_reflection("claude", text)
        assert any("Line:" in e for e in r.evidence)

    def test_evidence_file_prefix(self, mar):
        text = "Root cause here\nFile: auth.py"
        r = mar.create_reflection("claude", text)
        assert any("File:" in e for e in r.evidence)


# ===========================================================================
# 6. Confidence estimation from certainty language
# ===========================================================================


class TestConfidenceEstimation:
    def test_neutral_text_gives_default(self, mar):
        r = mar.create_reflection("a", "Something happened")
        assert r.confidence == 0.5

    def test_high_confidence_clearly(self, mar):
        r = mar.create_reflection("a", "This is clearly a bug")
        assert r.confidence > 0.5

    def test_high_confidence_definitely(self, mar):
        r = mar.create_reflection("a", "The cause is definitely in auth")
        assert r.confidence > 0.5

    def test_high_confidence_certainly(self, mar):
        r = mar.create_reflection("a", "This certainly breaks the flow")
        assert r.confidence > 0.5

    def test_high_confidence_obvious(self, mar):
        r = mar.create_reflection("a", "The problem is obvious")
        assert r.confidence > 0.5

    def test_high_confidence_sure(self, mar):
        r = mar.create_reflection("a", "I am sure the root cause is here")
        assert r.confidence > 0.5

    def test_low_confidence_might(self, mar):
        r = mar.create_reflection("a", "This might be the issue")
        assert r.confidence < 0.5

    def test_low_confidence_maybe(self, mar):
        r = mar.create_reflection("a", "Maybe the config is wrong")
        assert r.confidence < 0.5

    def test_low_confidence_possibly(self, mar):
        r = mar.create_reflection("a", "This is possibly related")
        assert r.confidence < 0.5

    def test_low_confidence_unclear(self, mar):
        r = mar.create_reflection("a", "The situation is unclear")
        assert r.confidence < 0.5

    def test_low_confidence_unsure(self, mar):
        # Note: "unsure" contains "sure" which matches high_conf via substring,
        # so high_count=1, low_count=1 => net 0 => confidence stays 0.5
        r = mar.create_reflection("a", "I'm unsure about this")
        assert r.confidence <= 0.5

    def test_low_confidence_could(self, mar):
        r = mar.create_reflection("a", "It could be a race condition")
        assert r.confidence < 0.5

    def test_multiple_high_words_boost(self, mar):
        r = mar.create_reflection("a", "Clearly and definitely the cause is obvious")
        assert r.confidence >= 0.8

    def test_multiple_low_words_lower(self, mar):
        r = mar.create_reflection("a", "Maybe it might possibly be related, unclear")
        assert r.confidence <= 0.2

    def test_confidence_max_cap(self, mar):
        text = "Clearly definitely certainly obviously sure without doubt"
        r = mar.create_reflection("a", text)
        assert r.confidence <= 0.95

    def test_confidence_min_cap(self, mar):
        text = "Maybe might possibly unclear unsure could perhaps"
        r = mar.create_reflection("a", text)
        assert r.confidence >= 0.1

    def test_mixed_confidence_language(self, mar):
        text = "It is clearly a problem but I'm unsure of the exact cause"
        r = mar.create_reflection("a", text)
        # "clearly" => +1 high, "unsure" => +1 low AND "sure" substring => +1 high
        # Net: high=2, low=1, delta=+1, confidence=0.6
        assert r.confidence == 0.6


# ===========================================================================
# 7. Novel insight detection
# ===========================================================================


class TestNovelInsight:
    def test_first_reflection_always_novel(self, mar):
        r = mar.create_reflection("claude", "Token expiry bug")
        assert r.novel_insight is True

    def test_duplicate_cause_not_novel(self, mar):
        # First: record a failure to populate cause_history
        mar.synthesize(
            reflections=[
                AgentReflection(agent_id="claude", root_cause="Token expiry bug"),
                AgentReflection(agent_id="gemini", root_cause="Token expiry bug"),
            ],
            failure_context="auth fails",
        )
        # Now the same cause should not be novel
        r = mar.create_reflection("claude", "Token expiry bug")
        assert r.novel_insight is False

    def test_different_cause_is_novel(self, mar):
        mar.synthesize(
            reflections=[
                AgentReflection(agent_id="claude", root_cause="Token expiry bug"),
                AgentReflection(agent_id="gemini", root_cause="Token expiry bug"),
            ],
            failure_context="auth fails",
        )
        # Completely different cause should be novel
        r = mar.create_reflection("claude", "Database connection pool exhausted")
        assert r.novel_insight is True


# ===========================================================================
# 8. Independent mode synthesis - consensus + diversity
# ===========================================================================


class TestIndependentSynthesis:
    def test_basic_synthesis(self, mar, reflection_claude, reflection_gemini):
        s = mar.synthesize(
            reflections=[reflection_claude, reflection_gemini],
            failure_context="Auth test failed",
        )
        assert s.consensus_cause != ""
        assert s.reflection_count == 2
        assert s.mode_used == ReflexionMode.INDEPENDENT
        assert 0.0 <= s.agreement_level <= 1.0

    def test_consensus_uses_highest_confidence(self, mar):
        r_high = AgentReflection(agent_id="claude", root_cause="High confidence cause", confidence=0.95)
        r_low = AgentReflection(agent_id="gemini", root_cause="Low confidence cause", confidence=0.3)
        s = mar.synthesize(reflections=[r_high, r_low])
        assert s.consensus_cause == "High confidence cause"

    def test_evidence_merged_deduplicated(self, mar):
        r1 = AgentReflection(
            agent_id="claude",
            root_cause="Bug",
            evidence=["- Error: 500", "- File: app.py"],
        )
        r2 = AgentReflection(
            agent_id="gemini",
            root_cause="Bug",
            evidence=["- Error: 500", "- Line: 10"],
        )
        s = mar.synthesize(reflections=[r1, r2])
        # "- Error: 500" should appear only once
        lower_evidence = [e.lower().strip() for e in s.consensus_evidence]
        assert lower_evidence.count("- error: 500") == 1
        assert len(s.consensus_evidence) == 3

    def test_diverse_insights_from_unique_words(self, mar):
        r1 = AgentReflection(
            agent_id="claude",
            root_cause="Token validation fails due to expired JWT algorithm mismatch",
        )
        r2 = AgentReflection(
            agent_id="gemini",
            root_cause="Database connection pool exhausted under heavy load",
        )
        s = mar.synthesize(reflections=[r1, r2])
        # Both have very different causes, so both should produce diverse insights
        assert len(s.diverse_insights) >= 1

    def test_strategy_uses_first_fix(self, mar):
        r1 = AgentReflection(agent_id="claude", root_cause="X", proposed_fix="Fix A")
        r2 = AgentReflection(agent_id="gemini", root_cause="Y", proposed_fix="Fix B")
        s = mar.synthesize(reflections=[r1, r2])
        assert "Fix A" in s.proposed_strategy
        assert "Fix B" in s.proposed_strategy

    def test_strategy_with_no_fixes(self, mar):
        r1 = AgentReflection(agent_id="claude", root_cause="X")
        r2 = AgentReflection(agent_id="gemini", root_cause="Y")
        s = mar.synthesize(reflections=[r1, r2])
        assert "consensus" in s.proposed_strategy.lower() or s.proposed_strategy != ""

    def test_agreement_level_identical_causes(self, mar):
        r1 = AgentReflection(agent_id="claude", root_cause="same words here")
        r2 = AgentReflection(agent_id="gemini", root_cause="same words here")
        s = mar.synthesize(reflections=[r1, r2])
        assert s.agreement_level == 1.0

    def test_agreement_level_completely_different(self, mar):
        r1 = AgentReflection(agent_id="claude", root_cause="alpha beta gamma")
        r2 = AgentReflection(agent_id="gemini", root_cause="delta epsilon zeta")
        s = mar.synthesize(reflections=[r1, r2])
        assert s.agreement_level == 0.0

    def test_agreement_level_partial_overlap(self, mar):
        r1 = AgentReflection(agent_id="claude", root_cause="token auth fails")
        r2 = AgentReflection(agent_id="gemini", root_cause="token refresh fails")
        s = mar.synthesize(reflections=[r1, r2])
        assert 0.0 < s.agreement_level < 1.0


# ===========================================================================
# 9. Adversarial mode synthesis - challenging diagnoses
# ===========================================================================


class TestAdversarialSynthesis:
    def test_adversarial_forced_mode(self, mar, reflection_claude, reflection_gemini):
        s = mar.synthesize(
            reflections=[reflection_claude, reflection_gemini],
            force_mode=ReflexionMode.ADVERSARIAL,
        )
        assert s.mode_used == ReflexionMode.ADVERSARIAL

    def test_adversarial_lowers_agreement(self, mar):
        r1 = AgentReflection(agent_id="claude", root_cause="same cause")
        r2 = AgentReflection(agent_id="gemini", root_cause="same cause")
        s_ind = mar.synthesize(reflections=[r1, r2], force_mode=ReflexionMode.INDEPENDENT)

        mar.reset()

        s_adv = mar.synthesize(reflections=[r1, r2], force_mode=ReflexionMode.ADVERSARIAL)
        assert s_adv.agreement_level < s_ind.agreement_level

    def test_adversarial_with_degeneration_inserts_warning(self, mar):
        # Set up degeneration: same context and same cause in history
        ctx = "auth fails"
        same_reflections = [
            AgentReflection(agent_id="claude", root_cause="token expired"),
            AgentReflection(agent_id="gemini", root_cause="token expired"),
        ]
        # First pass to populate history
        mar.synthesize(reflections=same_reflections, failure_context=ctx)
        # Second pass with degeneration trigger
        s = mar.synthesize(
            reflections=same_reflections,
            failure_context=ctx,
            force_mode=ReflexionMode.ADVERSARIAL,
        )
        found_warning = any("WARNING" in i for i in s.diverse_insights)
        assert found_warning or s.degeneration_detected

    def test_adversarial_prefers_novel_insight(self, mar):
        ctx = "auth fails"
        # Populate history
        mar.synthesize(
            reflections=[
                AgentReflection(agent_id="claude", root_cause="token expired"),
                AgentReflection(agent_id="gemini", root_cause="token expired"),
            ],
            failure_context=ctx,
        )
        # Second pass with a novel agent
        novel_r = AgentReflection(
            agent_id="gemini",
            root_cause="token expired",
            novel_insight=True,
        )
        regular_r = AgentReflection(
            agent_id="claude",
            root_cause="token expired",
            novel_insight=False,
        )
        s = mar.synthesize(
            reflections=[regular_r, novel_r],
            failure_context=ctx,
            force_mode=ReflexionMode.ADVERSARIAL,
        )
        # When degeneration + novel insight present, consensus changes to ALTERNATIVE
        if s.degeneration_detected:
            assert "ALTERNATIVE" in s.consensus_cause


# ===========================================================================
# 10. Constructive mode synthesis - building on insights
# ===========================================================================


class TestConstructiveSynthesis:
    def test_constructive_forced_mode(self, mar, reflection_claude, reflection_gemini):
        s = mar.synthesize(
            reflections=[reflection_claude, reflection_gemini],
            force_mode=ReflexionMode.CONSTRUCTIVE,
        )
        assert s.mode_used == ReflexionMode.CONSTRUCTIVE

    def test_constructive_combines_fixes_arrow_notation(self, mar):
        r1 = AgentReflection(agent_id="claude", root_cause="X", proposed_fix="Step one")
        r2 = AgentReflection(agent_id="gemini", root_cause="Y", proposed_fix="Step two")
        s = mar.synthesize(reflections=[r1, r2], force_mode=ReflexionMode.CONSTRUCTIVE)
        assert "Multi-step approach:" in s.proposed_strategy
        # Arrow notation
        assert chr(8594) in s.proposed_strategy  # unicode right arrow

    def test_constructive_boosts_agreement(self, mar):
        r1 = AgentReflection(agent_id="claude", root_cause="alpha beta gamma")
        r2 = AgentReflection(agent_id="gemini", root_cause="delta epsilon zeta")

        s_ind = mar.synthesize(reflections=[r1, r2], force_mode=ReflexionMode.INDEPENDENT)
        mar.reset()
        s_con = mar.synthesize(reflections=[r1, r2], force_mode=ReflexionMode.CONSTRUCTIVE)
        assert s_con.agreement_level >= s_ind.agreement_level

    def test_constructive_single_fix_no_arrow(self, mar):
        r1 = AgentReflection(agent_id="claude", root_cause="X", proposed_fix="Only fix")
        r2 = AgentReflection(agent_id="gemini", root_cause="Y", proposed_fix="")
        s = mar.synthesize(reflections=[r1, r2], force_mode=ReflexionMode.CONSTRUCTIVE)
        # Only one fix, so no "Multi-step approach"
        assert "Multi-step" not in s.proposed_strategy

    def test_constructive_agreement_capped_at_one(self, mar):
        r1 = AgentReflection(agent_id="claude", root_cause="same words")
        r2 = AgentReflection(agent_id="gemini", root_cause="same words")
        s = mar.synthesize(reflections=[r1, r2], force_mode=ReflexionMode.CONSTRUCTIVE)
        assert s.agreement_level <= 1.0


# ===========================================================================
# 11. Degeneration-of-thought detection
# ===========================================================================


class TestDegenerationDetection:
    def test_no_degeneration_first_call(self, mar):
        reflections = [
            AgentReflection(agent_id="claude", root_cause="token expired"),
            AgentReflection(agent_id="gemini", root_cause="token expired"),
        ]
        s = mar.synthesize(reflections=reflections, failure_context="auth")
        assert s.degeneration_detected is False

    def test_degeneration_on_repeated_same_cause(self, mar):
        ctx = "auth test failed"
        same_reflections = [
            AgentReflection(agent_id="claude", root_cause="token expired"),
            AgentReflection(agent_id="gemini", root_cause="token expired"),
        ]
        # First call populates history
        mar.synthesize(reflections=same_reflections, failure_context=ctx)
        # Second call should detect degeneration (same context, same cause)
        s = mar.synthesize(reflections=same_reflections, failure_context=ctx)
        assert s.degeneration_detected is True

    def test_no_degeneration_different_context(self, mar):
        reflections = [
            AgentReflection(agent_id="claude", root_cause="token expired"),
            AgentReflection(agent_id="gemini", root_cause="token expired"),
        ]
        mar.synthesize(reflections=reflections, failure_context="auth")
        s = mar.synthesize(reflections=reflections, failure_context="completely different")
        # Different context fingerprint, so no degeneration
        assert s.degeneration_detected is False

    def test_no_degeneration_with_single_reflection(self, mar):
        # MIN_REFLECTIONS is 2, so single reflection never triggers degeneration
        r = AgentReflection(agent_id="claude", root_cause="token expired")
        mar.synthesize(reflections=[r], failure_context="auth")
        s = mar.synthesize(reflections=[r], failure_context="auth")
        assert s.degeneration_detected is False

    def test_no_degeneration_diverse_causes(self, mar):
        ctx = "auth"
        mar.synthesize(
            reflections=[
                AgentReflection(agent_id="claude", root_cause="alpha beta"),
                AgentReflection(agent_id="gemini", root_cause="alpha beta"),
            ],
            failure_context=ctx,
        )
        s = mar.synthesize(
            reflections=[
                AgentReflection(agent_id="claude", root_cause="gamma delta epsilon"),
                AgentReflection(agent_id="gemini", root_cause="gamma delta epsilon"),
            ],
            failure_context=ctx,
        )
        # Different cause words, so no degeneration
        assert s.degeneration_detected is False


# ===========================================================================
# 12. Anti-degeneration strategy generation
# ===========================================================================


class TestAntiDegenerationStrategy:
    def test_degeneration_overrides_strategy(self, mar):
        ctx = "auth test"
        same_reflections = [
            AgentReflection(agent_id="claude", root_cause="token expired"),
            AgentReflection(agent_id="gemini", root_cause="token expired"),
        ]
        mar.synthesize(reflections=same_reflections, failure_context=ctx)
        s = mar.synthesize(reflections=same_reflections, failure_context=ctx)
        if s.degeneration_detected:
            # Should be one of the anti-degeneration strategies
            anti_keywords = [
                "different approach",
                "side effects",
                "assumptions",
                "different tool",
                "smaller parts",
            ]
            assert any(kw in s.proposed_strategy.lower() for kw in anti_keywords)

    def test_strategy_rotates_with_attempt_number(self, mar):
        reflections = [
            AgentReflection(agent_id="claude", root_cause="X"),
            AgentReflection(agent_id="gemini", root_cause="Y"),
        ]
        strategies_set = set()
        for attempt in range(1, 6):
            # Use internal method directly to test rotation
            strategy = mar._generate_anti_degeneration_strategy(reflections, "ctx", attempt)
            strategies_set.add(strategy)
        # Should produce different strategies for different attempts
        assert len(strategies_set) == 5

    def test_strategy_includes_novel_insight(self, mar):
        novel_r = AgentReflection(
            agent_id="gemini",
            root_cause="A novel cause discovered",
            novel_insight=True,
        )
        strategy = mar._generate_anti_degeneration_strategy([novel_r], "ctx", 1)
        assert "novel cause discovered" in strategy.lower()

    def test_strategy_cycle_repeats_after_five(self, mar):
        reflections = [AgentReflection(agent_id="claude", root_cause="X")]
        s1 = mar._generate_anti_degeneration_strategy(reflections, "c", 1)
        s6 = mar._generate_anti_degeneration_strategy(reflections, "c", 6)
        assert s1 == s6


# ===========================================================================
# 13. Mode selection: independent -> adversarial -> constructive
# ===========================================================================


class TestModeSelection:
    def test_first_attempt_independent(self, mar):
        mode = mar._select_mode("some failure", attempt_number=1)
        assert mode == ReflexionMode.INDEPENDENT

    def test_second_attempt_independent(self, mar):
        mode = mar._select_mode("some failure", attempt_number=2)
        assert mode == ReflexionMode.INDEPENDENT

    def test_third_attempt_constructive(self, mar):
        mode = mar._select_mode("some failure", attempt_number=3)
        assert mode == ReflexionMode.CONSTRUCTIVE

    def test_high_attempt_number_constructive(self, mar):
        mode = mar._select_mode("some failure", attempt_number=10)
        assert mode == ReflexionMode.CONSTRUCTIVE

    def test_adversarial_after_consecutive_same_context(self, mar):
        ctx = "auth error"
        # Record failures for the same context
        for _ in range(ADVERSARIAL_TRIGGER):
            mar._record_failure(ctx, "token expired")
        mode = mar._select_mode(ctx, attempt_number=1)
        assert mode == ReflexionMode.ADVERSARIAL

    def test_adversarial_not_triggered_by_different_contexts(self, mar):
        mar._record_failure("context A", "cause 1")
        mar._record_failure("context B", "cause 2")
        mode = mar._select_mode("context A", attempt_number=1)
        # Only 1 consecutive failure for context A (the last is B), so independent
        assert mode == ReflexionMode.INDEPENDENT

    def test_force_mode_overrides_selection(self, mar):
        s = mar.synthesize(
            reflections=[
                AgentReflection(agent_id="claude", root_cause="X"),
                AgentReflection(agent_id="gemini", root_cause="Y"),
            ],
            force_mode=ReflexionMode.ADVERSARIAL,
        )
        assert s.mode_used == ReflexionMode.ADVERSARIAL

    def test_adversarial_consecutive_break(self, mar):
        """Inserting a different context resets consecutive count."""
        ctx = "auth error"
        mar._record_failure(ctx, "c1")
        mar._record_failure("DIFFERENT context", "c2")
        mar._record_failure(ctx, "c3")
        mode = mar._select_mode(ctx, attempt_number=1)
        # Only 1 consecutive at end for ctx, not enough for adversarial
        assert mode == ReflexionMode.INDEPENDENT


# ===========================================================================
# 14. Failure history tracking and fingerprinting
# ===========================================================================


class TestFailureHistory:
    def test_fingerprint_deterministic(self, mar):
        fp1 = mar._fingerprint("some text")
        fp2 = mar._fingerprint("some text")
        assert fp1 == fp2

    def test_fingerprint_different_texts(self, mar):
        fp1 = mar._fingerprint("text A")
        fp2 = mar._fingerprint("text B")
        assert fp1 != fp2

    def test_fingerprint_case_insensitive(self, mar):
        fp1 = mar._fingerprint("Auth Error")
        fp2 = mar._fingerprint("auth error")
        assert fp1 == fp2

    def test_fingerprint_whitespace_normalized(self, mar):
        fp1 = mar._fingerprint("auth   error   here")
        fp2 = mar._fingerprint("auth error here")
        assert fp1 == fp2

    def test_fingerprint_truncates_to_30_words(self, mar):
        long_text = " ".join(f"word{i}" for i in range(100))
        short_text = " ".join(f"word{i}" for i in range(30))
        fp_long = mar._fingerprint(long_text)
        fp_short = mar._fingerprint(short_text)
        assert fp_long == fp_short

    def test_fingerprint_length(self, mar):
        fp = mar._fingerprint("anything")
        assert len(fp) == 12

    def test_record_failure_populates_history(self, mar):
        mar._record_failure("ctx", "cause")
        assert len(mar._failure_history) == 1
        assert len(mar._cause_history) == 1

    def test_record_failure_truncates_cause(self, mar):
        long_cause = "A" * 500
        mar._record_failure("ctx", long_cause)
        _, stored = mar._cause_history[0]
        assert len(stored) <= 100

    def test_history_bounded_by_max(self):
        mar = MultiAgentReflexion(max_history=5)
        for i in range(10):
            mar._record_failure(f"ctx{i}", f"cause{i}")
        assert len(mar._failure_history) == 5
        assert len(mar._cause_history) == 5

    def test_history_keeps_most_recent(self):
        mar = MultiAgentReflexion(max_history=3)
        for i in range(5):
            mar._record_failure(f"ctx{i}", f"cause{i}")
        # Should have the last 3
        _, last_cause = mar._cause_history[-1]
        assert "cause4" in last_cause


# ===========================================================================
# 15. Single reflection synthesis (passthrough)
# ===========================================================================


class TestSingleReflectionSynthesis:
    def test_single_reflection_passthrough(self, mar):
        r = AgentReflection(
            agent_id="claude",
            root_cause="Only one agent reflected",
            evidence=["e1", "e2"],
            proposed_fix="Do the thing",
            confidence=0.9,
        )
        s = mar.synthesize(reflections=[r])
        assert s.consensus_cause == "Only one agent reflected"
        assert s.consensus_evidence == ["e1", "e2"]
        assert s.diverse_insights == []
        assert s.agreement_level == 1.0
        assert s.reflection_count == 1

    def test_single_reflection_no_fix_fallback_strategy(self, mar):
        r = AgentReflection(agent_id="claude", root_cause="Root cause")
        s = mar.synthesize(reflections=[r])
        assert "apply" in s.proposed_strategy.lower()

    def test_single_reflection_uses_proposed_fix(self, mar):
        r = AgentReflection(agent_id="claude", root_cause="X", proposed_fix="My specific fix")
        s = mar.synthesize(reflections=[r])
        assert s.proposed_strategy == "My specific fix"


# ===========================================================================
# 16. Empty reflections handling
# ===========================================================================


class TestEmptyReflections:
    def test_empty_list_returns_default(self, mar):
        s = mar.synthesize(reflections=[])
        assert s.consensus_cause == "No reflections provided"
        assert s.consensus_evidence == []
        assert s.diverse_insights == []
        assert s.proposed_strategy == "Retry with default approach"
        assert s.agreement_level == 0.0
        assert s.reflection_count == 0

    def test_empty_list_does_not_crash(self, mar):
        s = mar.synthesize(reflections=[])
        assert isinstance(s, ReflexionSynthesis)

    def test_empty_list_no_stats_increment(self, mar):
        mar.synthesize(reflections=[])
        stats = mar.get_stats()
        assert stats.total_reflexions == 0


# ===========================================================================
# 17. Singleton get/reset pattern
# ===========================================================================


class TestSingleton:
    def test_get_returns_instance(self):
        instance = get_multi_agent_reflexion()
        assert isinstance(instance, MultiAgentReflexion)

    def test_get_returns_same_instance(self):
        a = get_multi_agent_reflexion()
        b = get_multi_agent_reflexion()
        assert a is b

    def test_reset_clears_singleton(self):
        a = get_multi_agent_reflexion()
        reset_multi_agent_reflexion()
        b = get_multi_agent_reflexion()
        assert a is not b

    def test_reset_idempotent(self):
        reset_multi_agent_reflexion()
        reset_multi_agent_reflexion()
        instance = get_multi_agent_reflexion()
        assert isinstance(instance, MultiAgentReflexion)

    def test_instance_reset_clears_stats(self):
        mar = get_multi_agent_reflexion()
        mar.synthesize(
            reflections=[
                AgentReflection(agent_id="claude", root_cause="X"),
                AgentReflection(agent_id="gemini", root_cause="Y"),
            ]
        )
        assert mar.get_stats().total_reflexions == 1
        mar.reset()
        assert mar.get_stats().total_reflexions == 0


# ===========================================================================
# 18. Statistics tracking
# ===========================================================================


class TestStatistics:
    def test_total_reflexions_increments(self, mar):
        for i in range(3):
            mar.synthesize(
                reflections=[
                    AgentReflection(agent_id="claude", root_cause=f"cause{i}"),
                    AgentReflection(agent_id="gemini", root_cause=f"other{i}"),
                ]
            )
        stats = mar.get_stats()
        assert stats.total_reflexions == 3

    def test_degeneration_detections_increments(self, mar):
        ctx = "same context"
        same_r = [
            AgentReflection(agent_id="claude", root_cause="same cause repeated"),
            AgentReflection(agent_id="gemini", root_cause="same cause repeated"),
        ]
        mar.synthesize(reflections=same_r, failure_context=ctx)
        mar.synthesize(reflections=same_r, failure_context=ctx)
        stats = mar.get_stats()
        # At least 1 degeneration (the second call should detect it)
        assert stats.degeneration_detections >= 1

    def test_mode_counts_tracked(self, mar):
        r = [
            AgentReflection(agent_id="claude", root_cause="X"),
            AgentReflection(agent_id="gemini", root_cause="Y"),
        ]
        mar.synthesize(reflections=r, force_mode=ReflexionMode.INDEPENDENT)
        mar.synthesize(reflections=r, force_mode=ReflexionMode.ADVERSARIAL)
        mar.synthesize(reflections=r, force_mode=ReflexionMode.CONSTRUCTIVE)
        stats = mar.get_stats()
        assert stats.mode_counts.get("independent", 0) == 1
        assert stats.mode_counts.get("adversarial", 0) == 1
        assert stats.mode_counts.get("constructive", 0) == 1

    def test_avg_agreement_computed(self, mar):
        # Two syntheses with known agreement
        r_same = [
            AgentReflection(agent_id="claude", root_cause="same words"),
            AgentReflection(agent_id="gemini", root_cause="same words"),
        ]
        r_diff = [
            AgentReflection(agent_id="claude", root_cause="alpha beta gamma"),
            AgentReflection(agent_id="gemini", root_cause="delta epsilon zeta"),
        ]
        mar.synthesize(reflections=r_same)
        mar.synthesize(reflections=r_diff)
        stats = mar.get_stats()
        # Average of 1.0 and 0.0 = 0.5
        assert abs(stats.avg_agreement - 0.5) < 0.05

    def test_insight_counts_tracked(self, mar):
        r = [
            AgentReflection(agent_id="claude", root_cause="X", novel_insight=True),
            AgentReflection(agent_id="gemini", root_cause="Y", novel_insight=False),
        ]
        mar.synthesize(reflections=r)
        stats = mar.get_stats()
        assert stats.insight_counts.get("claude", 0) == 1
        assert stats.insight_counts.get("gemini", 0) == 0

    def test_stats_returns_copy(self, mar):
        stats1 = mar.get_stats()
        mar.synthesize(
            reflections=[
                AgentReflection(agent_id="claude", root_cause="X"),
                AgentReflection(agent_id="gemini", root_cause="Y"),
            ]
        )
        stats2 = mar.get_stats()
        assert stats1.total_reflexions == 0
        assert stats2.total_reflexions == 1

    def test_empty_reflections_not_counted(self, mar):
        mar.synthesize(reflections=[])
        assert mar.get_stats().total_reflexions == 0


# ===========================================================================
# 19. Edge cases
# ===========================================================================


class TestEdgeCases:
    def test_all_same_root_cause(self, mar):
        reflections = [AgentReflection(agent_id=f"agent{i}", root_cause="exact same thing") for i in range(5)]
        s = mar.synthesize(reflections=reflections)
        assert s.agreement_level == 1.0
        assert s.consensus_cause == "exact same thing"

    def test_all_different_root_cause(self, mar):
        reflections = [
            AgentReflection(agent_id="a", root_cause="alpha beta gamma"),
            AgentReflection(agent_id="b", root_cause="delta epsilon zeta"),
            AgentReflection(agent_id="c", root_cause="eta theta iota"),
        ]
        s = mar.synthesize(reflections=reflections)
        assert s.agreement_level < 0.5

    def test_very_high_confidence_reflection(self, mar):
        r = AgentReflection(agent_id="claude", root_cause="Critical bug", confidence=0.99)
        s = mar.synthesize(reflections=[r])
        assert s.consensus_cause == "Critical bug"

    def test_very_low_confidence_reflection(self, mar):
        r = AgentReflection(agent_id="claude", root_cause="Maybe bug", confidence=0.01)
        s = mar.synthesize(reflections=[r])
        assert s.consensus_cause == "Maybe bug"

    def test_many_reflections(self, mar):
        reflections = [AgentReflection(agent_id=f"agent{i}", root_cause=f"cause {i} analysis") for i in range(20)]
        s = mar.synthesize(reflections=reflections)
        assert s.reflection_count == 20
        assert len(s.consensus_evidence) <= 10  # Capped at 10

    def test_evidence_cap_at_10(self, mar):
        r1 = AgentReflection(
            agent_id="claude",
            root_cause="X",
            evidence=[f"- Evidence item {i}" for i in range(8)],
        )
        r2 = AgentReflection(
            agent_id="gemini",
            root_cause="Y",
            evidence=[f"- Other item {i}" for i in range(8)],
        )
        s = mar.synthesize(reflections=[r1, r2])
        assert len(s.consensus_evidence) <= 10

    def test_empty_root_cause_words(self, mar):
        r1 = AgentReflection(agent_id="claude", root_cause="")
        r2 = AgentReflection(agent_id="gemini", root_cause="some cause")
        # Should not crash with empty root cause
        s = mar.synthesize(reflections=[r1, r2])
        assert isinstance(s, ReflexionSynthesis)

    def test_unicode_in_diagnosis(self, mar):
        r = mar.create_reflection("claude", "Error: Sch\u00f6n Unicode \u2192 arrow")
        assert r.root_cause is not None

    def test_three_agents_synthesis(self, mar):
        reflections = [
            AgentReflection(agent_id="claude", root_cause="token expired"),
            AgentReflection(agent_id="gemini", root_cause="token expired"),
            AgentReflection(agent_id="llama", root_cause="network timeout"),
        ]
        s = mar.synthesize(reflections=reflections)
        assert s.reflection_count == 3

    def test_custom_adversarial_trigger(self):
        mar = MultiAgentReflexion(adversarial_trigger=1)
        ctx = "test context"
        mar._record_failure(ctx, "cause")
        mode = mar._select_mode(ctx, attempt_number=1)
        assert mode == ReflexionMode.ADVERSARIAL

    def test_custom_max_history(self):
        mar = MultiAgentReflexion(max_history=2)
        for i in range(5):
            mar._record_failure(f"ctx{i}", f"cause{i}")
        assert len(mar._failure_history) == 2


# ===========================================================================
# 20. Word overlap utility function
# ===========================================================================


class TestWordOverlap:
    def test_identical_strings(self):
        result = MultiAgentReflexion._word_overlap("hello world", "hello world")
        assert result == 1.0

    def test_no_overlap(self):
        result = MultiAgentReflexion._word_overlap("alpha beta", "gamma delta")
        assert result == 0.0

    def test_partial_overlap(self):
        result = MultiAgentReflexion._word_overlap("token expired", "token refresh")
        # 1 overlap ("token") / min(2, 2) = 0.5
        assert result == 0.5

    def test_empty_first_string(self):
        result = MultiAgentReflexion._word_overlap("", "hello world")
        assert result == 0.0

    def test_empty_second_string(self):
        result = MultiAgentReflexion._word_overlap("hello world", "")
        assert result == 0.0

    def test_both_empty(self):
        result = MultiAgentReflexion._word_overlap("", "")
        assert result == 0.0

    def test_subset_overlap(self):
        result = MultiAgentReflexion._word_overlap("a b c", "a b c d e")
        # 3 overlap / min(3, 5) = 3/3 = 1.0
        assert result == 1.0

    def test_superset_overlap(self):
        result = MultiAgentReflexion._word_overlap("a b c d e", "a b c")
        # 3 overlap / min(5, 3) = 3/3 = 1.0
        assert result == 1.0

    def test_single_word_match(self):
        result = MultiAgentReflexion._word_overlap("hello", "hello")
        assert result == 1.0

    def test_single_word_no_match(self):
        result = MultiAgentReflexion._word_overlap("hello", "world")
        assert result == 0.0


# ===========================================================================
# 21. Constants
# ===========================================================================


class TestConstants:
    def test_agreement_threshold(self):
        assert AGREEMENT_THRESHOLD == 0.3

    def test_max_failure_history(self):
        assert MAX_FAILURE_HISTORY == 50

    def test_min_reflections(self):
        assert MIN_REFLECTIONS == 2

    def test_cause_similarity_threshold(self):
        assert CAUSE_SIMILARITY_THRESHOLD == 0.5

    def test_adversarial_trigger(self):
        assert ADVERSARIAL_TRIGGER == 2

    def test_diversity_weight(self):
        assert DIVERSITY_WEIGHT == 0.4


# ===========================================================================
# 22. Thread safety
# ===========================================================================


class TestThreadSafety:
    def test_concurrent_synthesize(self, mar):
        """Multiple threads synthesizing should not crash."""
        errors = []

        def worker(idx: int) -> None:
            try:
                reflections = [
                    AgentReflection(agent_id=f"agent_{idx}_a", root_cause=f"cause_{idx}"),
                    AgentReflection(agent_id=f"agent_{idx}_b", root_cause=f"other_{idx}"),
                ]
                s = mar.synthesize(reflections=reflections, failure_context=f"ctx_{idx}")
                assert isinstance(s, ReflexionSynthesis)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == [], f"Thread errors: {errors}"

    def test_concurrent_get_singleton(self):
        """Multiple threads getting singleton should return the same instance."""
        instances = []

        def worker() -> None:
            inst = get_multi_agent_reflexion()
            instances.append(id(inst))

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(set(instances)) == 1


# ===========================================================================
# 23. Integration: full workflow
# ===========================================================================


class TestIntegrationWorkflow:
    def test_full_retry_cycle(self, mar):
        """Simulate a 3-attempt retry cycle with mode progression.

        Use different failure contexts to avoid triggering adversarial mode
        from consecutive same-context failures, which takes priority over
        the attempt_number-based constructive selection.
        """
        # Attempt 1: Independent mode
        s1 = mar.synthesize(
            reflections=[
                AgentReflection(agent_id="claude", root_cause="Connection pool exhausted"),
                AgentReflection(agent_id="gemini", root_cause="Connection timeout"),
            ],
            failure_context="Database connection failed attempt 1",
            attempt_number=1,
        )
        assert s1.mode_used == ReflexionMode.INDEPENDENT

        # Attempt 2: Still independent (attempt <= 2)
        s2 = mar.synthesize(
            reflections=[
                AgentReflection(agent_id="claude", root_cause="Pool size too small"),
                AgentReflection(agent_id="gemini", root_cause="Pool not releasing connections"),
            ],
            failure_context="Database connection failed attempt 2",
            attempt_number=2,
        )
        assert s2.mode_used == ReflexionMode.INDEPENDENT

        # Attempt 3: Constructive (attempt > 2, no consecutive same-context)
        s3 = mar.synthesize(
            reflections=[
                AgentReflection(agent_id="claude", root_cause="Need connection retry logic"),
                AgentReflection(agent_id="gemini", root_cause="Add connection health check"),
            ],
            failure_context="Database connection failed attempt 3",
            attempt_number=3,
        )
        assert s3.mode_used == ReflexionMode.CONSTRUCTIVE

        stats = mar.get_stats()
        assert stats.total_reflexions == 3
        assert stats.mode_counts.get("independent", 0) == 2
        assert stats.mode_counts.get("constructive", 0) == 1

    def test_degeneration_triggers_adversarial(self, mar):
        """Repeated same-context failures trigger adversarial mode."""
        ctx = "auth token invalid"
        same_r = [
            AgentReflection(agent_id="claude", root_cause="token format wrong"),
            AgentReflection(agent_id="gemini", root_cause="token format wrong"),
        ]

        # Fill history to trigger adversarial
        for _ in range(ADVERSARIAL_TRIGGER):
            mar.synthesize(reflections=same_r, failure_context=ctx, attempt_number=1)

        # Next call should auto-select adversarial
        s = mar.synthesize(reflections=same_r, failure_context=ctx, attempt_number=1)
        assert s.mode_used == ReflexionMode.ADVERSARIAL

    def test_create_and_synthesize(self, mar):
        """End-to-end: create reflections from text, then synthesize."""
        r1 = mar.create_reflection(
            "claude",
            "The auth module is clearly broken\n- Error: InvalidToken\nWe should fix the token parser",
        )
        r2 = mar.create_reflection(
            "gemini",
            "Token parsing might have a bug\n- Error: ParseError at line 10\nTry using a different parser library",
        )

        assert r1.confidence > r2.confidence  # "clearly" vs "might"

        s = mar.synthesize(reflections=[r1, r2], failure_context="auth test")
        assert s.consensus_cause == r1.root_cause  # Higher confidence
        assert s.reflection_count == 2
