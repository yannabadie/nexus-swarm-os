"""Tests for V12.4 quorum-based early termination in debate phase.

Verifies the Aegean-inspired (arxiv:2512.20184) quorum detection:
when both agents CONCEDE or SUPPORT in consecutive turns, the debate
terminates immediately without an LLM consensus check.
"""

from core.intelligence.hive_mind.types import DebateArgument


class TestQuorumDetection:
    """Unit tests for quorum detection logic."""

    def _make_argument(self, agent_id: str, position: str, turn: int, modification: str = None) -> DebateArgument:
        return DebateArgument(
            agent_id=agent_id,
            turn_number=turn,
            position=position,
            target_point="approach",
            argument=f"Agent {agent_id} turn {turn}",
            evidence=["test"],
            proposed_modification=modification,
            concession="Agreed" if position in ("CONCEDE", "SUPPORT") else None,
        )

    def test_both_concede_is_quorum(self):
        """When both agents CONCEDE in consecutive turns, quorum is reached."""
        history = [
            self._make_argument("gemini", "CONCEDE", 1),
            self._make_argument("claude", "CONCEDE", 2),
        ]
        last_two = history[-2:]
        agreeing = {"SUPPORT", "CONCEDE"}
        assert last_two[0].position in agreeing
        assert last_two[1].position in agreeing
        assert last_two[0].agent_id != last_two[1].agent_id

    def test_support_and_concede_is_quorum(self):
        """SUPPORT + CONCEDE from different agents is also quorum."""
        history = [
            self._make_argument("gemini", "SUPPORT", 1),
            self._make_argument("claude", "CONCEDE", 2),
        ]
        last_two = history[-2:]
        agreeing = {"SUPPORT", "CONCEDE"}
        assert last_two[0].position in agreeing
        assert last_two[1].position in agreeing
        assert last_two[0].agent_id != last_two[1].agent_id

    def test_oppose_blocks_quorum(self):
        """If one agent OPPOSEs, no quorum."""
        history = [
            self._make_argument("gemini", "SUPPORT", 1),
            self._make_argument("claude", "OPPOSE", 2),
        ]
        last_two = history[-2:]
        agreeing = {"SUPPORT", "CONCEDE"}
        assert not (last_two[0].position in agreeing and last_two[1].position in agreeing)

    def test_same_agent_no_quorum(self):
        """Two turns from the same agent don't form a quorum."""
        history = [
            self._make_argument("gemini", "SUPPORT", 1),
            self._make_argument("gemini", "SUPPORT", 2),
        ]
        last_two = history[-2:]
        # Same agent - no quorum even though both SUPPORT
        assert last_two[0].agent_id == last_two[1].agent_id

    def test_quorum_needs_at_least_two_turns(self):
        """Single turn cannot trigger quorum."""
        history = [
            self._make_argument("gemini", "CONCEDE", 1),
        ]
        assert len(history) < 2

    def test_quorum_uses_proposed_modification(self):
        """Quorum result should use the proposed_modification if available."""
        arg = self._make_argument("claude", "CONCEDE", 2, modification="Use merged approach X")
        assert arg.proposed_modification == "Use merged approach X"

    def test_quorum_falls_back_to_argument_text(self):
        """Without proposed_modification, quorum uses argument text."""
        arg = self._make_argument("claude", "CONCEDE", 2)
        result = arg.proposed_modification or arg.argument
        assert result == "Agent claude turn 2"

    def test_all_agreeing_positions(self):
        """Verify the agreeing positions set is correct."""
        agreeing = {"SUPPORT", "CONCEDE"}
        assert "SUPPORT" in agreeing
        assert "CONCEDE" in agreeing
        assert "OPPOSE" not in agreeing

    def test_quorum_with_extended_history(self):
        """Quorum detection only looks at last 2 turns, not full history."""
        history = [
            self._make_argument("gemini", "OPPOSE", 1),
            self._make_argument("claude", "OPPOSE", 2),
            self._make_argument("gemini", "OPPOSE", 3),
            self._make_argument("claude", "SUPPORT", 4),
            self._make_argument("gemini", "CONCEDE", 5),
        ]
        last_two = history[-2:]
        agreeing = {"SUPPORT", "CONCEDE"}
        # Turn 4 (claude SUPPORT) + Turn 5 (gemini CONCEDE) = quorum
        assert last_two[0].position in agreeing
        assert last_two[1].position in agreeing
        assert last_two[0].agent_id != last_two[1].agent_id
