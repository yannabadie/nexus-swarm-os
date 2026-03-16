"""Tests for EchoChamberGuard - sycophantic debate detection."""

from core.intelligence.hive_mind.echo_chamber_guard import (
    DEVIL_ADVOCATE_PROMPT,
    INDEPENDENCE_PROMPT,
    AgentPositionHistory,
    EchoChamberGuard,
    GuardActionType,
    get_echo_chamber_guard,
    reset_echo_chamber_guard,
)

# =============================================================================
# AgentPositionHistory
# =============================================================================


class TestAgentPositionHistory:
    def test_record_position(self):
        h = AgentPositionHistory(agent_id="gemini")
        h.record("OPPOSE", 2, 1)
        assert h.last_position == "OPPOSE"
        assert h.positions == ["OPPOSE"]

    def test_flip_count_no_flips(self):
        h = AgentPositionHistory(agent_id="gemini")
        h.record("OPPOSE", 2, 1)
        h.record("OPPOSE", 1, 2)
        assert h.flip_count == 0

    def test_flip_count_one_flip(self):
        h = AgentPositionHistory(agent_id="gemini")
        h.record("OPPOSE", 2, 1)
        h.record("SUPPORT", 0, 2)
        assert h.flip_count == 1

    def test_flip_count_concede_counts(self):
        h = AgentPositionHistory(agent_id="claude")
        h.record("OPPOSE", 1, 1)
        h.record("CONCEDE", 0, 2)
        assert h.flip_count == 1

    def test_flip_count_multiple(self):
        h = AgentPositionHistory(agent_id="gemini")
        h.record("OPPOSE", 2, 1)
        h.record("SUPPORT", 0, 2)
        h.record("OPPOSE", 1, 3)
        h.record("CONCEDE", 0, 4)
        assert h.flip_count == 2

    def test_last_position_empty(self):
        h = AgentPositionHistory(agent_id="gemini")
        assert h.last_position is None

    def test_support_to_oppose_not_a_flip(self):
        h = AgentPositionHistory(agent_id="gemini")
        h.record("SUPPORT", 0, 1)
        h.record("OPPOSE", 2, 2)
        assert h.flip_count == 0


# =============================================================================
# EchoChamberGuard - Sycophantic Flip Detection
# =============================================================================


class TestFlipDetection:
    def test_oppose_to_support_without_evidence_flagged(self):
        guard = EchoChamberGuard()
        # First turn: OPPOSE
        guard.check_turn("gemini", "OPPOSE", ["evidence1", "evidence2"], 1)
        # Second turn: flip to SUPPORT with no evidence
        action = guard.check_turn("gemini", "SUPPORT", [], 2)
        assert action.action_type == GuardActionType.FLAG_SYCOPHANCY
        assert "flipped" in action.reason

    def test_oppose_to_concede_without_evidence_flagged(self):
        guard = EchoChamberGuard()
        guard.check_turn("claude", "OPPOSE", ["e1"], 1)
        action = guard.check_turn("claude", "CONCEDE", [], 2)
        assert action.action_type == GuardActionType.FLAG_SYCOPHANCY

    def test_oppose_to_support_with_evidence_allowed(self):
        guard = EchoChamberGuard()
        guard.check_turn("gemini", "OPPOSE", ["e1"], 1)
        action = guard.check_turn("gemini", "SUPPORT", ["new_e1", "new_e2"], 3)
        # Turn 3 is odd, not a checkpoint turn, so should be ALLOW
        assert action.action_type == GuardActionType.ALLOW

    def test_support_to_support_not_flagged(self):
        guard = EchoChamberGuard()
        guard.check_turn("gemini", "SUPPORT", [], 1)
        action = guard.check_turn("gemini", "SUPPORT", [], 3)
        assert action.action_type == GuardActionType.ALLOW

    def test_first_turn_always_allowed(self):
        guard = EchoChamberGuard()
        action = guard.check_turn("gemini", "OPPOSE", [], 1)
        assert action.action_type == GuardActionType.ALLOW

    def test_prompt_injection_on_sycophancy(self):
        guard = EchoChamberGuard()
        guard.check_turn("gemini", "OPPOSE", ["e1"], 1)
        action = guard.check_turn("gemini", "SUPPORT", [], 2)
        assert action.prompt_injection == INDEPENDENCE_PROMPT


# =============================================================================
# EchoChamberGuard - Independence Checkpoints
# =============================================================================


class TestIndependenceCheckpoints:
    def test_checkpoint_at_interval(self):
        guard = EchoChamberGuard(checkpoint_interval=2)
        guard.check_turn("gemini", "OPPOSE", ["e1"], 1)
        # Turn 2 is a checkpoint interval
        action = guard.check_turn("claude", "OPPOSE", ["e1"], 2)
        assert action.action_type == GuardActionType.INJECT_INDEPENDENCE

    def test_no_checkpoint_at_turn_1(self):
        guard = EchoChamberGuard(checkpoint_interval=1)
        action = guard.check_turn("gemini", "OPPOSE", ["e1"], 1)
        # Turn 1 is skipped even if interval matches
        assert action.action_type == GuardActionType.ALLOW

    def test_checkpoint_every_3_turns(self):
        guard = EchoChamberGuard(checkpoint_interval=3)
        # Turn 2: no checkpoint
        guard.check_turn("gemini", "OPPOSE", ["e1"], 1)
        action = guard.check_turn("claude", "OPPOSE", ["e1"], 2)
        assert action.action_type == GuardActionType.ALLOW
        # Turn 3: checkpoint
        action = guard.check_turn("gemini", "OPPOSE", ["e1"], 3)
        assert action.action_type == GuardActionType.INJECT_INDEPENDENCE

    def test_checkpoint_prompt_injected(self):
        guard = EchoChamberGuard(checkpoint_interval=2)
        guard.check_turn("gemini", "OPPOSE", ["e1"], 1)
        action = guard.check_turn("claude", "OPPOSE", ["e1"], 2)
        assert action.prompt_injection == INDEPENDENCE_PROMPT


# =============================================================================
# EchoChamberGuard - Devil's Advocate
# =============================================================================


class TestDevilsAdvocate:
    def test_premature_consensus_forces_advocate(self):
        guard = EchoChamberGuard(min_turns_for_consensus=3)
        # Both agents agree on turn 1-2 (before min_turns=3)
        guard.check_turn("gemini", "SUPPORT", ["e1"], 1)
        action = guard.check_turn("claude", "SUPPORT", ["e1"], 2)
        assert action.action_type == GuardActionType.FORCE_DEVIL_ADVOCATE

    def test_devil_advocate_only_forced_once(self):
        guard = EchoChamberGuard(min_turns_for_consensus=4)
        guard.check_turn("gemini", "SUPPORT", ["e1"], 1)
        action = guard.check_turn("claude", "SUPPORT", ["e1"], 2)
        assert action.action_type == GuardActionType.FORCE_DEVIL_ADVOCATE
        # Next turn should not force again
        action = guard.check_turn("gemini", "SUPPORT", [], 3)
        assert action.action_type != GuardActionType.FORCE_DEVIL_ADVOCATE

    def test_no_advocate_when_disagreeing(self):
        guard = EchoChamberGuard(min_turns_for_consensus=3)
        guard.check_turn("gemini", "OPPOSE", ["e1"], 1)
        action = guard.check_turn("claude", "SUPPORT", ["e1"], 2)
        # Not all agents agreeing, so no devil's advocate
        assert action.action_type != GuardActionType.FORCE_DEVIL_ADVOCATE

    def test_advocate_prompt_injected(self):
        guard = EchoChamberGuard(min_turns_for_consensus=3)
        guard.check_turn("gemini", "SUPPORT", ["e1"], 1)
        action = guard.check_turn("claude", "SUPPORT", ["e1"], 2)
        assert action.prompt_injection == DEVIL_ADVOCATE_PROMPT

    def test_consensus_after_min_turns_allowed(self):
        guard = EchoChamberGuard(min_turns_for_consensus=2)
        guard.check_turn("gemini", "OPPOSE", ["e1"], 1)
        guard.check_turn("claude", "OPPOSE", ["e1"], 2)
        # Turn 3: both now agree (after min_turns=2, so OK)
        guard.check_turn("gemini", "SUPPORT", ["e1", "e2"], 3)
        action = guard.check_turn("claude", "SUPPORT", ["e1"], 4)
        # Should not force devil's advocate (past min_turns)
        assert action.action_type != GuardActionType.FORCE_DEVIL_ADVOCATE


# =============================================================================
# EchoChamberGuard - Scoring & Stats
# =============================================================================


class TestScoringAndStats:
    def test_sycophancy_score_zero_clean_debate(self):
        guard = EchoChamberGuard()
        guard.check_turn("gemini", "OPPOSE", ["e1"], 1)
        guard.check_turn("claude", "OPPOSE", ["e1"], 3)
        assert guard.get_sycophancy_score() == 0.0

    def test_sycophancy_score_positive_on_flip(self):
        guard = EchoChamberGuard()
        guard.check_turn("gemini", "OPPOSE", ["e1"], 1)
        guard.check_turn("gemini", "SUPPORT", [], 3)
        score = guard.get_sycophancy_score()
        assert score > 0.0

    def test_get_agent_flip_count(self):
        guard = EchoChamberGuard()
        guard.check_turn("gemini", "OPPOSE", ["e1"], 1)
        guard.check_turn("gemini", "SUPPORT", [], 3)
        assert guard.get_agent_flip_count("gemini") == 1
        assert guard.get_agent_flip_count("claude") == 0

    def test_get_all_actions(self):
        guard = EchoChamberGuard()
        guard.check_turn("gemini", "OPPOSE", ["e1"], 1)
        guard.check_turn("gemini", "SUPPORT", [], 3)
        actions = guard.get_all_actions()
        assert len(actions) == 1
        assert actions[0].action_type == GuardActionType.FLAG_SYCOPHANCY

    def test_get_stats(self):
        guard = EchoChamberGuard()
        guard.check_turn("gemini", "OPPOSE", ["e1"], 1)
        guard.check_turn("gemini", "SUPPORT", [], 3)
        stats = guard.get_stats()
        assert stats["agents_tracked"] == 1
        assert stats["sycophancy_flags"] == 1
        assert stats["agent_flips"]["gemini"] == 1

    def test_reset_clears_state(self):
        guard = EchoChamberGuard()
        guard.check_turn("gemini", "OPPOSE", ["e1"], 1)
        guard.check_turn("gemini", "SUPPORT", [], 3)
        guard.reset()
        assert guard.get_sycophancy_score() == 0.0
        assert guard.get_all_actions() == []
        assert guard.get_agent_flip_count("gemini") == 0


# =============================================================================
# Singleton
# =============================================================================


class TestSingleton:
    def test_get_returns_same_instance(self):
        reset_echo_chamber_guard()
        g1 = get_echo_chamber_guard()
        g2 = get_echo_chamber_guard()
        assert g1 is g2

    def test_reset_creates_new_instance(self):
        reset_echo_chamber_guard()
        g1 = get_echo_chamber_guard()
        reset_echo_chamber_guard()
        g2 = get_echo_chamber_guard()
        assert g1 is not g2
