"""
Comprehensive tests for NegotiationProtocol - Hybrid Swarm Engine

Tests the full negotiation lifecycle:
- NegotiationStatus enum values
- NegotiationProposal dataclass and from_dict/to_dict
- HybridNegotiationMessage dataclass, properties, and to_dict
- NegotiationResult dataclass and to_dict
- NegotiationProtocol constructor and configuration
- extract_negotiate_json() utility function
- skip_trivial logic (trivial tasks bypass negotiation)
- Single-turn negotiation (immediate consensus)
- Multi-turn negotiation with disagreement
- Max turns enforcement (adaptive and fixed)
- Timeout handling
- Negotiation message parsing (_parse_response)
- Agent role assignment from negotiation (_finalize_assignments)
- Mode selection from negotiation outcome (_update_proposal)
- Edge cases: empty proposals, malformed JSON, driver errors
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.intelligence.swarm.collaboration_modes import CollaborationMode
from core.intelligence.swarm.mode_selector import AgentAssignment, ModeProposal
from core.intelligence.swarm.negotiation_protocol import (
    HybridNegotiationMessage,
    NegotiationProposal,
    NegotiationProtocol,
    NegotiationResult,
    NegotiationStatus,
    extract_negotiate_json,
)
from core.intelligence.swarm.task_analyzer import TaskAnalysis, TaskComplexity, TaskDomain

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_task_analysis(
    complexity: TaskComplexity = TaskComplexity.MODERATE,
    domains: list[TaskDomain] | None = None,
    primary_domain: TaskDomain = TaskDomain.CODING,
    gemini_fit: float = 0.7,
    claude_fit: float = 0.8,
) -> TaskAnalysis:
    """Helper to build a TaskAnalysis with sensible defaults."""
    if domains is None:
        domains = [primary_domain]
    return TaskAnalysis(
        complexity=complexity,
        domains=domains,
        primary_domain=primary_domain,
        gemini_fit_score=gemini_fit,
        claude_fit_score=claude_fit,
        raw_input="test task input",
        confidence=0.75,
    )


def _make_mode_proposal(
    mode: CollaborationMode = CollaborationMode.PARALLEL,
    confidence: float = 0.8,
    reasoning: str = "test reasoning",
) -> ModeProposal:
    """Helper to build a ModeProposal with default assignments."""
    return ModeProposal(
        mode=mode,
        confidence=confidence,
        agent_assignments=[
            AgentAssignment(agent_id="gemini_primary", role="equal", confidence=0.8),
            AgentAssignment(agent_id="claude_opus", role="equal", confidence=0.7),
        ],
        reasoning=reasoning,
    )


def _make_consensus_response(
    mode: str = "parallel",
    lead: str | None = None,
    conf: float = 0.9,
) -> str:
    """Build a mock agent response that signals consensus."""
    proposal = {
        "proposed_mode": mode,
        "confidence": conf,
        "agrees_with_partner": True,
        "consensus_reached": True,
    }
    if lead:
        proposal["proposed_lead"] = lead
    return f"I agree with this approach.\n\n<negotiate>\n{json.dumps(proposal)}\n</negotiate>"


def _make_counter_response(
    mode: str = "lead_support",
    lead: str | None = "claude",
    conf: float = 0.7,
) -> str:
    """Build a mock agent response with a counter-proposal (no consensus)."""
    proposal = {
        "proposed_mode": mode,
        "proposed_lead": lead,
        "confidence": conf,
        "my_role": "lead" if lead == "claude" else "support",
        "agrees_with_partner": False,
        "consensus_reached": False,
    }
    return f"I disagree. I think {mode} is better.\n\n<negotiate>\n{json.dumps(proposal)}\n</negotiate>"


def _make_no_tag_response() -> str:
    """Build a mock agent response with no <negotiate> tag."""
    return "I think we should discuss further. No formal proposal yet."


# ===================================================================
# 1. NegotiationStatus enum
# ===================================================================


class TestNegotiationStatus:
    def test_all_status_values_exist(self):
        statuses = list(NegotiationStatus)
        assert len(statuses) == 5

    def test_pending_value(self):
        assert NegotiationStatus.PENDING.value == "pending"

    def test_in_progress_value(self):
        assert NegotiationStatus.IN_PROGRESS.value == "in_progress"

    def test_consensus_value(self):
        assert NegotiationStatus.CONSENSUS.value == "consensus"

    def test_timeout_value(self):
        assert NegotiationStatus.TIMEOUT.value == "timeout"

    def test_forced_value(self):
        assert NegotiationStatus.FORCED.value == "forced"


# ===================================================================
# 2. NegotiationProposal dataclass
# ===================================================================


class TestNegotiationProposal:
    def test_defaults(self):
        p = NegotiationProposal()
        assert p.proposed_mode is None
        assert p.proposed_lead is None
        assert p.confidence == 0.5
        assert p.my_role is None
        assert p.justification is None
        assert p.agrees_with_partner is False
        assert p.consensus_reached is False
        assert p.subtasks is None
        assert p.counter_proposal is None

    def test_from_dict_full(self):
        data = {
            "proposed_mode": "parallel",
            "proposed_lead": "gemini",
            "confidence": 0.9,
            "my_role": "lead",
            "justification": "I have web search",
            "agrees_with_partner": True,
            "consensus_reached": True,
            "subtasks": {"gemini": "search", "claude": "code"},
            "counter_proposal": None,
        }
        p = NegotiationProposal.from_dict(data)
        assert p.proposed_mode == "parallel"
        assert p.proposed_lead == "gemini"
        assert p.confidence == 0.9
        assert p.agrees_with_partner is True
        assert p.consensus_reached is True
        assert p.subtasks == {"gemini": "search", "claude": "code"}

    def test_from_dict_minimal(self):
        p = NegotiationProposal.from_dict({})
        assert p.proposed_mode is None
        assert p.confidence == 0.5
        assert p.agrees_with_partner is False

    def test_from_dict_subtasks_list_of_dicts(self):
        data = {
            "subtasks": [
                {"agent": "gemini", "task": "research"},
                {"agent": "claude", "task": "code"},
            ]
        }
        p = NegotiationProposal.from_dict(data)
        assert isinstance(p.subtasks, dict)
        assert p.subtasks["gemini"] == "research"
        assert p.subtasks["claude"] == "code"

    def test_from_dict_subtasks_list_of_strings(self):
        data = {"subtasks": ["do research", "write code"]}
        p = NegotiationProposal.from_dict(data)
        assert isinstance(p.subtasks, dict)
        assert p.subtasks["agent_0"] == "do research"
        assert p.subtasks["agent_1"] == "write code"

    def test_from_dict_subtasks_none(self):
        data = {"subtasks": None}
        p = NegotiationProposal.from_dict(data)
        assert p.subtasks is None

    def test_from_dict_subtasks_unsupported_type(self):
        data = {"subtasks": 42}
        p = NegotiationProposal.from_dict(data)
        assert p.subtasks is None

    def test_to_dict_roundtrip(self):
        original = NegotiationProposal(
            proposed_mode="red_blue",
            proposed_lead="claude",
            confidence=0.85,
            my_role="blue",
            justification="security task",
            agrees_with_partner=False,
            consensus_reached=False,
            subtasks={"claude": "defend", "gemini": "attack"},
            counter_proposal="specialist",
        )
        d = original.to_dict()
        restored = NegotiationProposal.from_dict(d)
        assert restored.proposed_mode == original.proposed_mode
        assert restored.confidence == original.confidence
        assert restored.subtasks == original.subtasks

    def test_to_dict_keys(self):
        d = NegotiationProposal().to_dict()
        expected_keys = {
            "proposed_mode",
            "proposed_lead",
            "confidence",
            "my_role",
            "justification",
            "agrees_with_partner",
            "consensus_reached",
            "subtasks",
            "counter_proposal",
        }
        assert set(d.keys()) == expected_keys


# ===================================================================
# 3. HybridNegotiationMessage dataclass and to_dict
# ===================================================================


class TestHybridNegotiationMessage:
    def test_basic_construction(self):
        msg = HybridNegotiationMessage(
            sender="gemini",
            natural_content="Let us use parallel mode.",
        )
        assert msg.sender == "gemini"
        assert msg.natural_content == "Let us use parallel mode."
        assert msg.structured_proposal is None
        assert msg.turn_number == 0
        assert isinstance(msg.timestamp, datetime)

    def test_agrees_with_partner_no_proposal(self):
        msg = HybridNegotiationMessage(sender="claude", natural_content="ok")
        assert msg.agrees_with_partner is False

    def test_agrees_with_partner_with_proposal(self):
        proposal = NegotiationProposal(agrees_with_partner=True)
        msg = HybridNegotiationMessage(
            sender="claude",
            natural_content="ok",
            structured_proposal=proposal,
        )
        assert msg.agrees_with_partner is True

    def test_consensus_reached_no_proposal(self):
        msg = HybridNegotiationMessage(sender="gemini", natural_content="x")
        assert msg.consensus_reached is False

    def test_consensus_reached_with_proposal(self):
        proposal = NegotiationProposal(consensus_reached=True)
        msg = HybridNegotiationMessage(
            sender="gemini",
            natural_content="agreed",
            structured_proposal=proposal,
        )
        assert msg.consensus_reached is True

    def test_proposed_mode_none_without_proposal(self):
        msg = HybridNegotiationMessage(sender="claude", natural_content="x")
        assert msg.proposed_mode is None

    def test_proposed_mode_valid(self):
        proposal = NegotiationProposal(proposed_mode="lead_support")
        msg = HybridNegotiationMessage(
            sender="claude",
            natural_content="x",
            structured_proposal=proposal,
        )
        assert msg.proposed_mode == CollaborationMode.LEAD_SUPPORT

    def test_proposed_mode_invalid_returns_none(self):
        proposal = NegotiationProposal(proposed_mode="nonexistent_mode")
        msg = HybridNegotiationMessage(
            sender="claude",
            natural_content="x",
            structured_proposal=proposal,
        )
        assert msg.proposed_mode is None

    def test_proposed_mode_none_string(self):
        proposal = NegotiationProposal(proposed_mode=None)
        msg = HybridNegotiationMessage(
            sender="gemini",
            natural_content="x",
            structured_proposal=proposal,
        )
        assert msg.proposed_mode is None

    def test_to_dict_without_proposal(self):
        msg = HybridNegotiationMessage(
            sender="claude",
            natural_content="test",
            turn_number=2,
        )
        d = msg.to_dict()
        assert d["sender"] == "claude"
        assert d["natural_content"] == "test"
        assert d["structured_proposal"] is None
        assert d["turn_number"] == 2
        assert "timestamp" in d

    def test_to_dict_with_proposal(self):
        proposal = NegotiationProposal(proposed_mode="parallel", confidence=0.9)
        msg = HybridNegotiationMessage(
            sender="gemini",
            natural_content="Agreed",
            structured_proposal=proposal,
            turn_number=1,
        )
        d = msg.to_dict()
        assert d["structured_proposal"] is not None
        assert d["structured_proposal"]["proposed_mode"] == "parallel"
        assert d["structured_proposal"]["confidence"] == 0.9


# ===================================================================
# 4. NegotiationResult dataclass
# ===================================================================


class TestNegotiationResult:
    def test_basic_construction(self):
        result = NegotiationResult(
            status=NegotiationStatus.CONSENSUS,
            selected_mode=CollaborationMode.PARALLEL,
            agent_assignments=[
                AgentAssignment(agent_id="gemini_primary", role="equal"),
            ],
            negotiation_history=[],
            total_turns=1,
            consensus_confidence=0.9,
        )
        assert result.status == NegotiationStatus.CONSENSUS
        assert result.selected_mode == CollaborationMode.PARALLEL
        assert result.total_turns == 1
        assert result.final_subtasks is None

    def test_to_dict_keys(self):
        result = NegotiationResult(
            status=NegotiationStatus.TIMEOUT,
            selected_mode=CollaborationMode.SPECIALIST,
            agent_assignments=[],
            negotiation_history=[],
            total_turns=4,
            consensus_confidence=0.55,
            final_subtasks={"gemini": "analyze"},
        )
        d = result.to_dict()
        assert d["status"] == "timeout"
        assert d["selected_mode"] == "specialist"
        assert d["total_turns"] == 4
        assert d["consensus_confidence"] == 0.55
        assert d["final_subtasks"] == {"gemini": "analyze"}

    def test_to_dict_with_history(self):
        msg = HybridNegotiationMessage(
            sender="claude",
            natural_content="ok",
            turn_number=0,
        )
        result = NegotiationResult(
            status=NegotiationStatus.CONSENSUS,
            selected_mode=CollaborationMode.PING_PONG,
            agent_assignments=[],
            negotiation_history=[msg],
            total_turns=1,
            consensus_confidence=0.85,
        )
        d = result.to_dict()
        assert len(d["negotiation_history"]) == 1
        assert d["negotiation_history"][0]["sender"] == "claude"

    def test_to_dict_agent_assignments(self):
        assignments = [
            AgentAssignment(agent_id="gemini_primary", role="lead", subtask="research"),
            AgentAssignment(agent_id="claude_opus", role="support", subtask="code"),
        ]
        result = NegotiationResult(
            status=NegotiationStatus.FORCED,
            selected_mode=CollaborationMode.LEAD_SUPPORT,
            agent_assignments=assignments,
            negotiation_history=[],
            total_turns=0,
            consensus_confidence=1.0,
        )
        d = result.to_dict()
        assert len(d["agent_assignments"]) == 2
        assert d["agent_assignments"][0]["role"] == "lead"
        assert d["agent_assignments"][1]["subtask"] == "code"


# ===================================================================
# 5. NegotiationProtocol constructor and configuration
# ===================================================================


class TestNegotiationProtocolInit:
    def test_default_constructor(self):
        proto = NegotiationProtocol()
        assert proto.base_max_turns == 4
        assert proto.max_turns == 4
        assert proto.consensus_threshold == 0.6
        assert proto.skip_trivial is True
        assert proto.timeout_seconds == 60.0
        assert proto.adaptive_turns is True
        assert proto.negotiation_log == []

    def test_custom_constructor(self):
        proto = NegotiationProtocol(
            max_turns=8,
            consensus_threshold=0.9,
            skip_trivial=False,
            timeout_seconds=120.0,
            adaptive_turns=False,
        )
        assert proto.base_max_turns == 8
        assert proto.max_turns == 8
        assert proto.consensus_threshold == 0.9
        assert proto.skip_trivial is False
        assert proto.timeout_seconds == 120.0
        assert proto.adaptive_turns is False

    def test_no_timeout(self):
        proto = NegotiationProtocol(timeout_seconds=None)
        assert proto.timeout_seconds is None

    def test_negotiate_pattern_compiled(self):
        proto = NegotiationProtocol()
        assert proto.NEGOTIATE_PATTERN is not None
        # Verify pattern matches expected text
        text = '<negotiate>\n{"key": "val"}\n</negotiate>'
        m = proto.NEGOTIATE_PATTERN.search(text)
        assert m is not None

    def test_adaptive_max_turns_map(self):
        expected = {1: 2, 2: 3, 3: 4, 4: 6, 5: 8}
        assert expected == NegotiationProtocol.ADAPTIVE_MAX_TURNS


# ===================================================================
# 6. extract_negotiate_json() utility function
# ===================================================================


class TestExtractNegotiateJson:
    def test_valid_json(self):
        text = 'Some text.\n<negotiate>\n{"mode": "parallel"}\n</negotiate>\nMore text.'
        result = extract_negotiate_json(text)
        assert result == {"mode": "parallel"}

    def test_no_tag(self):
        result = extract_negotiate_json("Plain text with no negotiate tags.")
        assert result is None

    def test_invalid_json(self):
        text = "<negotiate>\nnot valid json\n</negotiate>"
        result = extract_negotiate_json(text)
        assert result is None

    def test_empty_tag(self):
        text = "<negotiate>\n{}\n</negotiate>"
        result = extract_negotiate_json(text)
        assert result == {}

    def test_complex_json(self):
        payload = {
            "proposed_mode": "red_blue",
            "confidence": 0.95,
            "subtasks": {"gemini": "attack", "claude": "defend"},
        }
        text = f"Discussion here.\n<negotiate>\n{json.dumps(payload)}\n</negotiate>"
        result = extract_negotiate_json(text)
        assert result == payload

    def test_case_insensitive_tags(self):
        text = '<NEGOTIATE>\n{"ok": true}\n</NEGOTIATE>'
        result = extract_negotiate_json(text)
        assert result == {"ok": True}

    def test_multiline_json(self):
        text = '<negotiate>\n{\n  "proposed_mode": "sequential",\n  "confidence": 0.8\n}\n</negotiate>'
        result = extract_negotiate_json(text)
        assert result["proposed_mode"] == "sequential"

    def test_extra_whitespace_around_json(self):
        text = '<negotiate>   \n  {"x": 1}  \n  </negotiate>'
        result = extract_negotiate_json(text)
        assert result == {"x": 1}


# ===================================================================
# 7. skip_trivial logic
# ===================================================================


class TestSkipTrivial:
    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_exchange")
    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_speak")
    def test_trivial_task_skips_negotiation(self, mock_speak, mock_exchange):
        proto = NegotiationProtocol(skip_trivial=True)
        analysis = _make_task_analysis(complexity=TaskComplexity.TRIVIAL)
        proposal = _make_mode_proposal()
        invoke = MagicMock()

        result = proto.run_negotiation(analysis, proposal, invoke)

        assert result.status == NegotiationStatus.FORCED
        assert result.selected_mode == proposal.mode
        assert result.total_turns == 0
        assert result.negotiation_history == []
        invoke.assert_not_called()

    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_exchange")
    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_speak")
    def test_trivial_task_does_not_skip_when_disabled(self, mock_speak, mock_exchange):
        proto = NegotiationProtocol(skip_trivial=False, max_turns=1)
        analysis = _make_task_analysis(complexity=TaskComplexity.TRIVIAL)
        proposal = _make_mode_proposal()
        invoke = MagicMock(return_value=_make_consensus_response())

        result = proto.run_negotiation(analysis, proposal, invoke)

        # Should NOT skip; invoke was called
        invoke.assert_called()
        assert result.total_turns >= 1

    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_exchange")
    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_speak")
    def test_non_trivial_never_skips(self, mock_speak, mock_exchange):
        proto = NegotiationProtocol(skip_trivial=True, max_turns=1)
        analysis = _make_task_analysis(complexity=TaskComplexity.MODERATE)
        proposal = _make_mode_proposal()
        invoke = MagicMock(return_value=_make_consensus_response())

        proto.run_negotiation(analysis, proposal, invoke)
        invoke.assert_called()

    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_exchange")
    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_speak")
    def test_skip_returns_initial_assignments(self, mock_speak, mock_exchange):
        proto = NegotiationProtocol(skip_trivial=True)
        analysis = _make_task_analysis(complexity=TaskComplexity.TRIVIAL)
        proposal = _make_mode_proposal()
        invoke = MagicMock()

        result = proto.run_negotiation(analysis, proposal, invoke)
        assert result.agent_assignments == proposal.agent_assignments
        assert result.consensus_confidence == proposal.confidence


# ===================================================================
# 8. Single-turn negotiation (immediate agreement)
# ===================================================================


class TestSingleTurnNegotiation:
    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_exchange")
    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_speak")
    def test_immediate_consensus_on_first_turn(self, mock_speak, mock_exchange):
        proto = NegotiationProtocol(max_turns=4, adaptive_turns=False)
        analysis = _make_task_analysis(complexity=TaskComplexity.MODERATE)
        proposal = _make_mode_proposal(mode=CollaborationMode.PARALLEL)
        invoke = MagicMock(return_value=_make_consensus_response("parallel"))

        result = proto.run_negotiation(analysis, proposal, invoke)

        assert result.status == NegotiationStatus.CONSENSUS
        assert result.selected_mode == CollaborationMode.PARALLEL
        assert result.total_turns == 1
        assert len(result.negotiation_history) == 1
        assert result.negotiation_history[0].sender == "gemini"

    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_exchange")
    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_speak")
    def test_consensus_confidence_calculated(self, mock_speak, mock_exchange):
        proto = NegotiationProtocol(adaptive_turns=False)
        analysis = _make_task_analysis()
        proposal = _make_mode_proposal()
        invoke = MagicMock(return_value=_make_consensus_response(conf=0.95))

        result = proto.run_negotiation(analysis, proposal, invoke)
        assert result.consensus_confidence > 0.0

    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_exchange")
    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_speak")
    def test_on_turn_callback_called(self, mock_speak, mock_exchange):
        proto = NegotiationProtocol(adaptive_turns=False)
        analysis = _make_task_analysis()
        proposal = _make_mode_proposal()
        invoke = MagicMock(return_value=_make_consensus_response())
        on_turn = MagicMock()

        proto.run_negotiation(analysis, proposal, invoke, on_turn=on_turn)
        on_turn.assert_called_once()
        arg = on_turn.call_args[0][0]
        assert isinstance(arg, HybridNegotiationMessage)


# ===================================================================
# 9. Multi-turn negotiation with disagreement
# ===================================================================


class TestMultiTurnNegotiation:
    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_exchange")
    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_speak")
    def test_two_turn_negotiation(self, mock_speak, mock_exchange):
        """Turn 0 (gemini): counter-propose. Turn 1 (claude): agree."""
        proto = NegotiationProtocol(max_turns=4, adaptive_turns=False)
        analysis = _make_task_analysis()
        proposal = _make_mode_proposal(mode=CollaborationMode.PARALLEL)

        responses = [
            _make_counter_response("lead_support", "claude", 0.7),
            _make_consensus_response("lead_support", "claude", 0.85),
        ]
        invoke = MagicMock(side_effect=responses)

        result = proto.run_negotiation(analysis, proposal, invoke)

        assert result.status == NegotiationStatus.CONSENSUS
        assert result.selected_mode == CollaborationMode.LEAD_SUPPORT
        assert result.total_turns == 2
        assert len(result.negotiation_history) == 2
        assert result.negotiation_history[0].sender == "gemini"
        assert result.negotiation_history[1].sender == "claude"

    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_exchange")
    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_speak")
    def test_three_turn_with_counter_proposals(self, mock_speak, mock_exchange):
        proto = NegotiationProtocol(max_turns=4, adaptive_turns=False)
        analysis = _make_task_analysis()
        proposal = _make_mode_proposal(mode=CollaborationMode.PARALLEL)

        responses = [
            _make_counter_response("lead_support"),
            _make_counter_response("ping_pong"),
            _make_consensus_response("ping_pong"),
        ]
        invoke = MagicMock(side_effect=responses)

        result = proto.run_negotiation(analysis, proposal, invoke)
        assert result.status == NegotiationStatus.CONSENSUS
        assert result.selected_mode == CollaborationMode.PING_PONG
        assert result.total_turns == 3

    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_exchange")
    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_speak")
    def test_agent_alternation_pattern(self, mock_speak, mock_exchange):
        proto = NegotiationProtocol(max_turns=6, adaptive_turns=False)
        analysis = _make_task_analysis()
        proposal = _make_mode_proposal()

        responses = [
            _make_counter_response("sequential"),
            _make_counter_response("parallel"),
            _make_counter_response("lead_support"),
            _make_consensus_response("lead_support"),
        ]
        invoke = MagicMock(side_effect=responses)

        result = proto.run_negotiation(analysis, proposal, invoke)
        senders = [m.sender for m in result.negotiation_history]
        # Gemini starts, then alternates
        assert senders == ["gemini", "claude", "gemini", "claude"]


# ===================================================================
# 10. Max turns enforcement
# ===================================================================


class TestMaxTurnsEnforcement:
    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_exchange")
    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_speak")
    def test_max_turns_timeout(self, mock_speak, mock_exchange):
        proto = NegotiationProtocol(max_turns=3, adaptive_turns=False)
        analysis = _make_task_analysis()
        proposal = _make_mode_proposal(mode=CollaborationMode.PARALLEL)

        # Never reach consensus
        invoke = MagicMock(return_value=_make_counter_response("sequential"))

        result = proto.run_negotiation(analysis, proposal, invoke)

        assert result.status == NegotiationStatus.TIMEOUT
        assert result.total_turns == 3
        # Falls back to initial proposal
        assert result.selected_mode == CollaborationMode.PARALLEL

    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_exchange")
    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_speak")
    def test_max_turns_exactly_reached(self, mock_speak, mock_exchange):
        proto = NegotiationProtocol(max_turns=2, adaptive_turns=False)
        analysis = _make_task_analysis()
        proposal = _make_mode_proposal()

        invoke = MagicMock(return_value=_make_counter_response())

        result = proto.run_negotiation(analysis, proposal, invoke)
        assert result.total_turns == 2
        assert invoke.call_count == 2

    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_exchange")
    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_speak")
    def test_adaptive_turns_trivial(self, mock_speak, mock_exchange):
        proto = NegotiationProtocol(max_turns=4, adaptive_turns=True, skip_trivial=False)
        analysis = _make_task_analysis(complexity=TaskComplexity.TRIVIAL)
        proposal = _make_mode_proposal()
        invoke = MagicMock(return_value=_make_counter_response())

        result = proto.run_negotiation(analysis, proposal, invoke)
        # TRIVIAL complexity => ADAPTIVE_MAX_TURNS[1] = 2
        assert result.total_turns == 2

    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_exchange")
    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_speak")
    def test_adaptive_turns_expert(self, mock_speak, mock_exchange):
        proto = NegotiationProtocol(max_turns=4, adaptive_turns=True)
        analysis = _make_task_analysis(complexity=TaskComplexity.EXPERT)
        proposal = _make_mode_proposal()
        invoke = MagicMock(return_value=_make_counter_response())

        result = proto.run_negotiation(analysis, proposal, invoke)
        # EXPERT complexity => ADAPTIVE_MAX_TURNS[5] = 8
        assert result.total_turns == 8

    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_exchange")
    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_speak")
    def test_adaptive_turns_moderate(self, mock_speak, mock_exchange):
        proto = NegotiationProtocol(max_turns=4, adaptive_turns=True)
        analysis = _make_task_analysis(complexity=TaskComplexity.MODERATE)
        proposal = _make_mode_proposal()
        invoke = MagicMock(return_value=_make_counter_response())

        result = proto.run_negotiation(analysis, proposal, invoke)
        # MODERATE complexity => ADAPTIVE_MAX_TURNS[3] = 4
        assert result.total_turns == 4

    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_exchange")
    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_speak")
    def test_adaptive_turns_disabled_uses_base(self, mock_speak, mock_exchange):
        proto = NegotiationProtocol(max_turns=3, adaptive_turns=False)
        analysis = _make_task_analysis(complexity=TaskComplexity.EXPERT)
        proposal = _make_mode_proposal()
        invoke = MagicMock(return_value=_make_counter_response())

        result = proto.run_negotiation(analysis, proposal, invoke)
        # adaptive disabled => base_max_turns = 3 (not 8)
        assert result.total_turns == 3

    def test_get_adaptive_max_turns_all_levels(self):
        proto = NegotiationProtocol(max_turns=4, adaptive_turns=True)
        for complexity_val, expected in NegotiationProtocol.ADAPTIVE_MAX_TURNS.items():
            analysis = _make_task_analysis(complexity=TaskComplexity(complexity_val))
            assert proto._get_adaptive_max_turns(analysis) == expected

    def test_get_adaptive_max_turns_disabled(self):
        proto = NegotiationProtocol(max_turns=7, adaptive_turns=False)
        analysis = _make_task_analysis(complexity=TaskComplexity.EXPERT)
        assert proto._get_adaptive_max_turns(analysis) == 7


# ===================================================================
# 11. Timeout handling
# ===================================================================


class TestTimeoutHandling:
    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_exchange")
    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_speak")
    @patch("core.intelligence.swarm.negotiation_protocol.time")
    def test_time_based_timeout(self, mock_time, mock_speak, mock_exchange):
        """Simulate time exceeding timeout_seconds mid-negotiation."""
        proto = NegotiationProtocol(
            max_turns=10,
            timeout_seconds=5.0,
            adaptive_turns=False,
        )
        analysis = _make_task_analysis()
        proposal = _make_mode_proposal()

        # Time progression: start=0, then 2, 4, 6 (exceeds 5.0 on turn 2 check)
        mock_time.time.side_effect = [0.0, 2.0, 4.0, 6.0]
        invoke = MagicMock(return_value=_make_counter_response())

        result = proto.run_negotiation(analysis, proposal, invoke)

        assert result.status == NegotiationStatus.TIMEOUT
        # Should have completed turns before the timeout check at 6.0
        assert result.total_turns <= 3

    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_exchange")
    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_speak")
    @patch("core.intelligence.swarm.negotiation_protocol.time")
    def test_no_timeout_when_none(self, mock_time, mock_speak, mock_exchange):
        """timeout_seconds=None means no time limit."""
        proto = NegotiationProtocol(
            max_turns=2,
            timeout_seconds=None,
            adaptive_turns=False,
        )
        analysis = _make_task_analysis()
        proposal = _make_mode_proposal()
        mock_time.time.return_value = 0.0
        invoke = MagicMock(return_value=_make_counter_response())

        result = proto.run_negotiation(analysis, proposal, invoke)
        # Should run all turns without time-based abort
        assert result.total_turns == 2

    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_exchange")
    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_speak")
    @patch("core.intelligence.swarm.negotiation_protocol.time")
    def test_timeout_returns_current_proposal(self, mock_time, mock_speak, mock_exchange):
        proto = NegotiationProtocol(
            max_turns=10,
            timeout_seconds=1.0,
            adaptive_turns=False,
        )
        analysis = _make_task_analysis()
        proposal = _make_mode_proposal(mode=CollaborationMode.RED_BLUE)

        # Immediate timeout on second check
        mock_time.time.side_effect = [0.0, 2.0]
        invoke = MagicMock(return_value=_make_counter_response())

        result = proto.run_negotiation(analysis, proposal, invoke)
        assert result.status == NegotiationStatus.TIMEOUT
        # Falls back to current proposal (which may have been updated by first turn)


# ===================================================================
# 12. Negotiation message parsing (_parse_response)
# ===================================================================


class TestParseResponse:
    def test_response_with_negotiate_tag(self):
        proto = NegotiationProtocol()
        response = (
            "I think parallel mode is best here.\n\n"
            '<negotiate>\n{"proposed_mode": "parallel", "confidence": 0.9, '
            '"agrees_with_partner": true, "consensus_reached": true}\n</negotiate>'
        )
        msg = proto._parse_response(response, "gemini", 0)
        assert msg.sender == "gemini"
        assert msg.turn_number == 0
        assert "parallel mode" in msg.natural_content
        assert msg.structured_proposal is not None
        assert msg.structured_proposal.proposed_mode == "parallel"
        assert msg.structured_proposal.confidence == 0.9
        assert msg.consensus_reached is True

    def test_response_without_negotiate_tag(self):
        proto = NegotiationProtocol()
        msg = proto._parse_response("Just some discussion.", "claude", 3)
        assert msg.sender == "claude"
        assert msg.turn_number == 3
        assert msg.natural_content == "Just some discussion."
        assert msg.structured_proposal is None

    def test_response_with_malformed_json(self):
        proto = NegotiationProtocol()
        response = "<negotiate>\n{broken json here}\n</negotiate>"
        msg = proto._parse_response(response, "gemini", 1)
        assert msg.structured_proposal is None
        assert msg.natural_content == ""

    def test_natural_content_strips_negotiate_block(self):
        proto = NegotiationProtocol()
        response = (
            "First part of discussion.\n"
            '<negotiate>\n{"proposed_mode": "sequential"}\n</negotiate>\n'
            "Second part after tag."
        )
        msg = proto._parse_response(response, "claude", 0)
        assert "<negotiate>" not in msg.natural_content
        assert "First part" in msg.natural_content
        assert "Second part" in msg.natural_content

    def test_parse_preserves_turn_number(self):
        proto = NegotiationProtocol()
        for turn in range(5):
            msg = proto._parse_response("text", "gemini", turn)
            assert msg.turn_number == turn


# ===================================================================
# 13. Agent role assignment from negotiation
# ===================================================================


class TestFinalizeAssignments:
    @patch("core.intelligence.swarm.negotiation_protocol.get_registry")
    def test_assignments_from_subtasks(self, mock_get_registry):
        mock_registry = MagicMock()
        mock_registry.is_gemini.side_effect = lambda x: "gemini" in x.lower()
        mock_get_registry.return_value = mock_registry

        proto = NegotiationProtocol()
        proposal = NegotiationProposal(
            proposed_lead="gemini",
            subtasks={"gemini": "research the topic", "claude": "write code"},
        )
        msg = HybridNegotiationMessage(
            sender="claude",
            natural_content="agreed",
            structured_proposal=proposal,
        )
        defaults = [
            AgentAssignment(agent_id="gemini_primary", role="equal"),
            AgentAssignment(agent_id="claude_opus", role="equal"),
        ]

        assignments = proto._finalize_assignments(
            CollaborationMode.LEAD_SUPPORT,
            msg,
            defaults,
        )
        assert len(assignments) == 2
        # gemini should be lead, claude support
        gemini_assignment = next(a for a in assignments if a.agent_id == "gemini_primary")
        claude_assignment = next(a for a in assignments if a.agent_id == "claude_opus")
        assert gemini_assignment.role == "lead"
        assert claude_assignment.role == "support"

    def test_fallback_to_defaults_when_no_subtasks(self):
        proto = NegotiationProtocol()
        proposal = NegotiationProposal()
        msg = HybridNegotiationMessage(
            sender="claude",
            natural_content="agreed",
            structured_proposal=proposal,
        )
        defaults = [
            AgentAssignment(agent_id="gemini_primary", role="equal"),
        ]

        assignments = proto._finalize_assignments(
            CollaborationMode.PARALLEL,
            msg,
            defaults,
        )
        assert assignments == defaults

    def test_fallback_when_no_proposal(self):
        proto = NegotiationProtocol()
        msg = HybridNegotiationMessage(
            sender="gemini",
            natural_content="ok",
            structured_proposal=None,
        )
        defaults = [
            AgentAssignment(agent_id="claude_opus", role="specialist"),
        ]

        assignments = proto._finalize_assignments(
            CollaborationMode.SPECIALIST,
            msg,
            defaults,
        )
        assert assignments == defaults

    @patch("core.intelligence.swarm.negotiation_protocol.get_registry")
    def test_equal_roles_when_no_lead(self, mock_get_registry):
        mock_registry = MagicMock()
        mock_registry.is_gemini.return_value = True
        mock_get_registry.return_value = mock_registry

        proto = NegotiationProtocol()
        proposal = NegotiationProposal(
            proposed_lead=None,
            subtasks={"gemini": "part A"},
        )
        msg = HybridNegotiationMessage(
            sender="claude",
            natural_content="ok",
            structured_proposal=proposal,
        )
        defaults = []

        assignments = proto._finalize_assignments(
            CollaborationMode.PARALLEL,
            msg,
            defaults,
        )
        assert len(assignments) == 1
        assert assignments[0].role == "equal"

    def test_fallback_when_subtasks_not_dict(self):
        """If subtasks is somehow a non-dict, should fall back to defaults."""
        proto = NegotiationProtocol()
        proposal = NegotiationProposal(subtasks=None)
        msg = HybridNegotiationMessage(
            sender="gemini",
            natural_content="ok",
            structured_proposal=proposal,
        )
        defaults = [AgentAssignment(agent_id="claude_opus", role="equal")]
        assignments = proto._finalize_assignments(
            CollaborationMode.PARALLEL,
            msg,
            defaults,
        )
        assert assignments == defaults


# ===================================================================
# 14. Mode selection from negotiation outcome (_update_proposal)
# ===================================================================


class TestUpdateProposal:
    def test_counter_proposal_updates_mode(self):
        proto = NegotiationProtocol()
        current = _make_mode_proposal(mode=CollaborationMode.PARALLEL)
        proposal = NegotiationProposal(
            proposed_mode="lead_support",
            proposed_lead="claude",
            confidence=0.85,
        )
        msg = HybridNegotiationMessage(
            sender="gemini",
            natural_content="I suggest lead_support",
            structured_proposal=proposal,
        )

        updated = proto._update_proposal(current, msg)
        assert updated.mode == CollaborationMode.LEAD_SUPPORT
        assert updated.confidence == 0.85
        assert "Counter-proposed by gemini" in updated.reasoning

    def test_no_update_when_no_proposed_mode(self):
        proto = NegotiationProtocol()
        current = _make_mode_proposal(mode=CollaborationMode.PARALLEL)
        msg = HybridNegotiationMessage(
            sender="claude",
            natural_content="unsure",
            structured_proposal=None,
        )

        updated = proto._update_proposal(current, msg)
        assert updated.mode == CollaborationMode.PARALLEL
        assert updated is current  # Same object returned

    def test_update_proposal_sets_lead_roles(self):
        proto = NegotiationProtocol()
        current = _make_mode_proposal(mode=CollaborationMode.PARALLEL)
        proposal = NegotiationProposal(
            proposed_mode="lead_support",
            proposed_lead="claude",
            confidence=0.75,
        )
        msg = HybridNegotiationMessage(
            sender="gemini",
            natural_content="you lead",
            structured_proposal=proposal,
        )

        updated = proto._update_proposal(current, msg)
        # The assignment with "claude" in agent_id should be "lead"
        claude_a = next(
            (a for a in updated.agent_assignments if "claude" in a.agent_id),
            None,
        )
        gemini_a = next(
            (a for a in updated.agent_assignments if "gemini" in a.agent_id),
            None,
        )
        assert claude_a is not None
        assert claude_a.role == "lead"
        assert gemini_a is not None
        assert gemini_a.role == "support"

    def test_update_preserves_alternatives(self):
        proto = NegotiationProtocol()
        current = _make_mode_proposal(mode=CollaborationMode.PARALLEL)
        current.alternatives = [(CollaborationMode.SEQUENTIAL, 0.6)]

        proposal = NegotiationProposal(
            proposed_mode="specialist",
            confidence=0.7,
        )
        msg = HybridNegotiationMessage(
            sender="claude",
            natural_content="specialist better",
            structured_proposal=proposal,
        )

        updated = proto._update_proposal(current, msg)
        assert updated.alternatives == current.alternatives

    def test_update_default_confidence_without_proposal(self):
        """When structured_proposal is None but proposed_mode property returns something."""
        proto = NegotiationProtocol()
        current = _make_mode_proposal()

        # Create a message where proposed_mode returns None
        msg = HybridNegotiationMessage(
            sender="gemini",
            natural_content="hmm",
            structured_proposal=NegotiationProposal(proposed_mode=None),
        )
        updated = proto._update_proposal(current, msg)
        # No proposed_mode => returns current unchanged
        assert updated is current


# ===================================================================
# 15. Edge cases
# ===================================================================


class TestEdgeCases:
    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_exchange")
    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_speak")
    def test_invoke_returns_empty_string(self, mock_speak, mock_exchange):
        proto = NegotiationProtocol(max_turns=2, adaptive_turns=False)
        analysis = _make_task_analysis()
        proposal = _make_mode_proposal()
        invoke = MagicMock(return_value="")

        result = proto.run_negotiation(analysis, proposal, invoke)
        # Should time out with no consensus
        assert result.status == NegotiationStatus.TIMEOUT
        assert result.total_turns == 2

    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_exchange")
    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_speak")
    def test_invoke_raises_exception(self, mock_speak, mock_exchange):
        proto = NegotiationProtocol(max_turns=2, adaptive_turns=False)
        analysis = _make_task_analysis()
        proposal = _make_mode_proposal()
        invoke = MagicMock(side_effect=RuntimeError("Driver failure"))

        with pytest.raises(RuntimeError, match="Driver failure"):
            proto.run_negotiation(analysis, proposal, invoke)

    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_exchange")
    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_speak")
    def test_all_no_tag_responses(self, mock_speak, mock_exchange):
        """Agents that never include <negotiate> tags => timeout."""
        proto = NegotiationProtocol(max_turns=3, adaptive_turns=False)
        analysis = _make_task_analysis()
        proposal = _make_mode_proposal()
        invoke = MagicMock(return_value=_make_no_tag_response())

        result = proto.run_negotiation(analysis, proposal, invoke)
        assert result.status == NegotiationStatus.TIMEOUT
        for msg in result.negotiation_history:
            assert msg.structured_proposal is None

    def test_calculate_consensus_confidence_empty_history(self):
        proto = NegotiationProtocol()
        assert proto._calculate_consensus_confidence([]) == 0.5

    def test_calculate_consensus_confidence_all_agree(self):
        proto = NegotiationProtocol()
        msgs = [
            HybridNegotiationMessage(
                sender="gemini",
                natural_content="ok",
                structured_proposal=NegotiationProposal(
                    agrees_with_partner=True,
                    confidence=0.9,
                ),
            ),
            HybridNegotiationMessage(
                sender="claude",
                natural_content="agreed",
                structured_proposal=NegotiationProposal(
                    agrees_with_partner=True,
                    confidence=0.95,
                ),
            ),
        ]
        conf = proto._calculate_consensus_confidence(msgs)
        # agreement_factor = 2/2 = 1.0, avg_confidence = 0.925
        # consensus = 1.0 * 0.5 + 0.925 * 0.5 = 0.9625
        assert 0.9 <= conf <= 1.0

    def test_calculate_consensus_confidence_no_agreements(self):
        proto = NegotiationProtocol()
        msgs = [
            HybridNegotiationMessage(
                sender="gemini",
                natural_content="disagree",
                structured_proposal=NegotiationProposal(
                    agrees_with_partner=False,
                    confidence=0.4,
                ),
            ),
        ]
        conf = proto._calculate_consensus_confidence(msgs)
        # agreement_factor = 0/1 = 0.0, avg_confidence = 0.4
        # consensus = 0.0 * 0.5 + 0.4 * 0.5 = 0.2
        assert conf == pytest.approx(0.2)

    def test_calculate_consensus_confidence_no_proposals(self):
        proto = NegotiationProtocol()
        msgs = [
            HybridNegotiationMessage(
                sender="gemini",
                natural_content="hmm",
            ),
        ]
        conf = proto._calculate_consensus_confidence(msgs)
        # agreement_factor = 0/1, avg_confidence = 0.5 (default)
        # consensus = 0 * 0.5 + 0.5 * 0.5 = 0.25
        assert conf == pytest.approx(0.25)


# ===================================================================
# Additional: build context, create prompt, force mode
# ===================================================================


class TestBuildNegotiationContext:
    def test_context_contains_task_info(self):
        proto = NegotiationProtocol()
        analysis = _make_task_analysis(
            complexity=TaskComplexity.COMPLEX,
            primary_domain=TaskDomain.SECURITY,
        )
        proposal = _make_mode_proposal(mode=CollaborationMode.RED_BLUE)

        ctx = proto._build_negotiation_context(analysis, proposal, [], "gemini")
        assert "COMPLEX" in ctx
        assert "security" in ctx
        assert "RED_BLUE" in ctx
        assert "gemini" in ctx

    def test_context_includes_history_tail(self):
        proto = NegotiationProtocol()
        analysis = _make_task_analysis()
        proposal = _make_mode_proposal()
        history = [
            HybridNegotiationMessage(
                sender="gemini",
                natural_content=f"Turn {i}",
                turn_number=i,
            )
            for i in range(6)
        ]

        ctx = proto._build_negotiation_context(analysis, proposal, history, "claude")
        # Should include last 4 messages
        assert "Turn 2" in ctx
        assert "Turn 3" in ctx
        assert "Turn 4" in ctx
        assert "Turn 5" in ctx

    def test_context_no_history(self):
        proto = NegotiationProtocol()
        analysis = _make_task_analysis()
        proposal = _make_mode_proposal()

        ctx = proto._build_negotiation_context(analysis, proposal, [], "claude")
        assert "NEGOTIATION HISTORY" not in ctx
        assert "YOUR TURN" in ctx

    def test_context_includes_available_modes(self):
        proto = NegotiationProtocol()
        analysis = _make_task_analysis()
        proposal = _make_mode_proposal()

        ctx = proto._build_negotiation_context(analysis, proposal, [], "gemini")
        assert "parallel" in ctx
        assert "sequential" in ctx
        assert "lead_support" in ctx
        assert "ping_pong" in ctx
        assert "specialist" in ctx
        assert "red_blue" in ctx


class TestCreateNegotiationPrompt:
    def test_prompt_contains_agent_and_mode(self):
        proto = NegotiationProtocol()
        prompt = proto.create_negotiation_prompt(
            "claude",
            "Fix the auth bug",
            CollaborationMode.LEAD_SUPPORT,
        )
        assert "claude" in prompt
        assert "lead_support" in prompt
        assert "Fix the auth bug" in prompt

    def test_prompt_includes_negotiate_block_example(self):
        proto = NegotiationProtocol()
        prompt = proto.create_negotiation_prompt(
            "gemini",
            "Research task",
            CollaborationMode.PARALLEL,
        )
        assert "<negotiate>" in prompt
        assert "proposed_mode" in prompt
        assert "consensus_reached" in prompt


class TestForceMode:
    @patch("core.intelligence.swarm.mode_selector.ModeSelector.select_mode")
    def test_force_mode_returns_forced_status(self, mock_select_mode):
        mock_select_mode.return_value = _make_mode_proposal(
            mode=CollaborationMode.PARALLEL,
        )

        proto = NegotiationProtocol()
        analysis = _make_task_analysis()

        result = proto.force_mode(CollaborationMode.RED_BLUE, analysis, "user forced")

        assert result.status == NegotiationStatus.FORCED
        assert result.selected_mode == CollaborationMode.RED_BLUE
        assert result.total_turns == 0
        assert result.consensus_confidence == 1.0
        assert result.negotiation_history == []

    @patch("core.intelligence.swarm.mode_selector.ModeSelector.select_mode")
    def test_force_mode_uses_selector_assignments(self, mock_select_mode):
        assignments = [AgentAssignment(agent_id="claude_opus", role="specialist")]
        mock_proposal = ModeProposal(
            mode=CollaborationMode.SPECIALIST,
            confidence=0.9,
            agent_assignments=assignments,
            reasoning="auto",
        )
        mock_select_mode.return_value = mock_proposal

        proto = NegotiationProtocol()
        analysis = _make_task_analysis()

        result = proto.force_mode(CollaborationMode.SPECIALIST, analysis)
        assert result.agent_assignments == assignments


# ===================================================================
# Negotiation with final_subtasks
# ===================================================================


class TestNegotiationSubtasks:
    @patch("core.intelligence.swarm.negotiation_protocol.get_registry")
    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_exchange")
    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_speak")
    def test_consensus_with_subtasks(self, mock_speak, mock_exchange, mock_get_registry):
        mock_registry = MagicMock()
        mock_registry.is_gemini.side_effect = lambda x: "gemini" in x.lower()
        mock_get_registry.return_value = mock_registry

        proto = NegotiationProtocol(adaptive_turns=False)
        analysis = _make_task_analysis()
        proposal = _make_mode_proposal()

        response_payload = {
            "proposed_mode": "parallel",
            "confidence": 0.9,
            "agrees_with_partner": True,
            "consensus_reached": True,
            "subtasks": {"gemini": "web research", "claude": "implementation"},
        }
        response = f"Let us split work.\n<negotiate>\n{json.dumps(response_payload)}\n</negotiate>"
        invoke = MagicMock(return_value=response)

        result = proto.run_negotiation(analysis, proposal, invoke)
        assert result.status == NegotiationStatus.CONSENSUS
        assert result.final_subtasks == {"gemini": "web research", "claude": "implementation"}


# ===================================================================
# Telemetry emission verification
# ===================================================================


class TestTelemetryEmission:
    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_exchange")
    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_speak")
    def test_telemetry_emitted_each_turn(self, mock_speak, mock_exchange):
        proto = NegotiationProtocol(max_turns=2, adaptive_turns=False)
        analysis = _make_task_analysis()
        proposal = _make_mode_proposal()
        invoke = MagicMock(return_value=_make_counter_response())

        proto.run_negotiation(analysis, proposal, invoke)

        assert mock_speak.call_count == 2
        assert mock_exchange.call_count == 2

    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_exchange")
    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_speak")
    def test_telemetry_not_emitted_on_skip(self, mock_speak, mock_exchange):
        proto = NegotiationProtocol(skip_trivial=True)
        analysis = _make_task_analysis(complexity=TaskComplexity.TRIVIAL)
        proposal = _make_mode_proposal()
        invoke = MagicMock()

        proto.run_negotiation(analysis, proposal, invoke)

        mock_speak.assert_not_called()
        mock_exchange.assert_not_called()

    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_exchange")
    @patch("core.intelligence.swarm.negotiation_protocol.emit_agent_speak")
    def test_telemetry_speak_args(self, mock_speak, mock_exchange):
        proto = NegotiationProtocol(max_turns=1, adaptive_turns=False)
        analysis = _make_task_analysis()
        proposal = _make_mode_proposal()
        invoke = MagicMock(return_value=_make_counter_response())

        proto.run_negotiation(analysis, proposal, invoke)

        # First call is gemini (turn 0)
        call_args = mock_speak.call_args_list[0]
        assert call_args[0][0] == "gemini"  # agent_id
        assert call_args[1].get("action_type") == "NEGOTIATE" or call_args[0][2] == "NEGOTIATE"


# ===================================================================
# Regex pattern tests
# ===================================================================


class TestNegotiatePattern:
    def test_matches_standard_format(self):
        text = '<negotiate>\n{"key": "value"}\n</negotiate>'
        match = NegotiationProtocol.NEGOTIATE_PATTERN.search(text)
        assert match is not None

    def test_matches_with_extra_whitespace(self):
        text = '<negotiate>  \n  {"key": "value"}  \n  </negotiate>'
        match = NegotiationProtocol.NEGOTIATE_PATTERN.search(text)
        assert match is not None

    def test_matches_case_insensitive(self):
        text = '<Negotiate>\n{"key": "value"}\n</Negotiate>'
        match = NegotiationProtocol.NEGOTIATE_PATTERN.search(text)
        assert match is not None

    def test_no_match_without_tags(self):
        text = '{"key": "value"}'
        match = NegotiationProtocol.NEGOTIATE_PATTERN.search(text)
        assert match is None

    def test_no_match_partial_tag(self):
        text = '<negotiate>{"key": "value"}'
        match = NegotiationProtocol.NEGOTIATE_PATTERN.search(text)
        assert match is None

    def test_extracts_json_group(self):
        text = '<negotiate>\n{"mode": "parallel"}\n</negotiate>'
        match = NegotiationProtocol.NEGOTIATE_PATTERN.search(text)
        data = json.loads(match.group(1))
        assert data["mode"] == "parallel"
