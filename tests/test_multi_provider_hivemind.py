"""
Tests for multi-provider (N-agent) HiveMind data types.

Validates that Disagreement, AnalysisComparison, and DebateResult
support N agents via dict fields while maintaining backward-compatible
properties for the original 2-agent (gemini/claude) API.
"""

from datetime import datetime

import pytest

from core.intelligence.hive_mind.types import (
    AnalysisComparison,
    DebateArgument,
    DebateResult,
    Disagreement,
    IndependentAnalysis,
)


# =============================================================================
# Helpers
# =============================================================================


def _make_analysis(agent_id: str, confidence: float = 0.8) -> IndependentAnalysis:
    """Create a minimal IndependentAnalysis for testing."""
    return IndependentAnalysis(
        agent_id=agent_id,
        task_understanding="Understand the task",
        complexity_assessment="MODERATE",
        proposed_approach=f"Approach by {agent_id}",
        required_capabilities=["python", "testing"],
        potential_risks=["timeout"],
        confidence=confidence,
        reasoning=f"Reasoning from {agent_id}",
    )


# =============================================================================
# Disagreement tests
# =============================================================================


class TestDisagreement:
    """Tests for the N-agent Disagreement dataclass."""

    def test_two_agents_backward_compat(self) -> None:
        """Disagreement with 2 agents exposes backward-compat properties."""
        d = Disagreement(
            topic="approach",
            positions={"gemini": "use RAG", "claude": "use fine-tuning"},
            severity=0.7,
        )
        assert d.topic == "approach"
        assert d.severity == 0.7
        assert d.gemini_position == "use RAG"
        assert d.claude_position == "use fine-tuning"
        assert d.positions["gemini"] == "use RAG"
        assert d.positions["claude"] == "use fine-tuning"

    def test_three_agents(self) -> None:
        """Disagreement with 3 agents stores all positions."""
        d = Disagreement(
            topic="complexity",
            positions={
                "gemini": "SIMPLE",
                "claude": "MODERATE",
                "deepseek": "COMPLEX",
            },
            severity=0.9,
        )
        assert len(d.positions) == 3
        assert d.positions["deepseek"] == "COMPLEX"
        # Backward-compat still works for gemini/claude
        assert d.gemini_position == "SIMPLE"
        assert d.claude_position == "MODERATE"

    def test_missing_agent_returns_none(self) -> None:
        """Backward-compat properties return None for absent agents."""
        d = Disagreement(
            topic="risk",
            positions={"deepseek": "low risk"},
            severity=0.3,
        )
        assert d.gemini_position is None
        assert d.claude_position is None

    def test_empty_positions(self) -> None:
        """Default empty positions dict works."""
        d = Disagreement(topic="test")
        assert d.positions == {}
        assert d.gemini_position is None
        assert d.claude_position is None
        assert d.severity == 0.5  # default

    def test_gemini_only_claude_only_preserved(self) -> None:
        """The gemini_only / claude_only list fields still work."""
        d = Disagreement(
            topic="capabilities",
            positions={"gemini": ["python"], "claude": ["rust"]},
            severity=0.6,
            gemini_only=["python"],
            claude_only=["rust"],
        )
        assert d.gemini_only == ["python"]
        assert d.claude_only == ["rust"]

    def test_n_agents_varied_types(self) -> None:
        """Positions can hold any type (str, float, list, dict)."""
        d = Disagreement(
            topic="confidence",
            positions={
                "gemini": 0.9,
                "claude": 0.6,
                "openai": 0.75,
                "ollama": {"local": True, "confidence": 0.5},
            },
        )
        assert d.positions["openai"] == 0.75
        assert d.positions["ollama"]["local"] is True


# =============================================================================
# AnalysisComparison tests
# =============================================================================


class TestAnalysisComparison:
    """Tests for the N-agent AnalysisComparison dataclass."""

    def test_two_agents_backward_compat(self) -> None:
        """AnalysisComparison with 2 agents exposes backward-compat properties."""
        gemini = _make_analysis("gemini", confidence=0.9)
        claude = _make_analysis("claude", confidence=0.7)

        comp = AnalysisComparison(
            analyses={"gemini": gemini, "claude": claude},
            disagreements=[],
            agreement_score=0.85,
            needs_debate=False,
            merged_capabilities=["python", "testing"],
            merged_risks=["timeout"],
        )
        assert comp.gemini_analysis is gemini
        assert comp.claude_analysis is claude
        assert comp.gemini_analysis.confidence == 0.9
        assert comp.claude_analysis.confidence == 0.7

    def test_three_agents(self) -> None:
        """AnalysisComparison with 3 agents stores all analyses."""
        gemini = _make_analysis("gemini", confidence=0.9)
        claude = _make_analysis("claude", confidence=0.7)
        deepseek = _make_analysis("deepseek", confidence=0.8)

        comp = AnalysisComparison(
            analyses={"gemini": gemini, "claude": claude, "deepseek": deepseek},
            agreement_score=0.75,
            needs_debate=True,
        )
        assert len(comp.analyses) == 3
        assert comp.analyses["deepseek"] is deepseek
        # Backward compat still works
        assert comp.gemini_analysis is gemini
        assert comp.claude_analysis is claude

    def test_missing_agent_returns_none(self) -> None:
        """Backward-compat returns None when agent not present."""
        deepseek = _make_analysis("deepseek")
        comp = AnalysisComparison(
            analyses={"deepseek": deepseek},
            agreement_score=1.0,
        )
        assert comp.gemini_analysis is None
        assert comp.claude_analysis is None

    def test_empty_analyses(self) -> None:
        """Default empty analyses dict works."""
        comp = AnalysisComparison()
        assert comp.analyses == {}
        assert comp.gemini_analysis is None
        assert comp.claude_analysis is None
        assert comp.agreement_score == 0.0
        assert comp.needs_debate is False
        assert comp.disagreements == []

    def test_with_disagreements(self) -> None:
        """AnalysisComparison stores disagreements correctly."""
        d1 = Disagreement(topic="approach", positions={"gemini": "A", "claude": "B"}, severity=0.8)
        d2 = Disagreement(topic="risk", positions={"gemini": "low", "claude": "high"}, severity=0.5)

        comp = AnalysisComparison(
            analyses={"gemini": _make_analysis("gemini"), "claude": _make_analysis("claude")},
            disagreements=[d1, d2],
            agreement_score=0.6,
            needs_debate=True,
        )
        assert len(comp.disagreements) == 2
        assert comp.disagreements[0].topic == "approach"


# =============================================================================
# DebateResult tests
# =============================================================================


class TestDebateResult:
    """Tests for the N-agent DebateResult dataclass."""

    def test_two_agents_backward_compat(self) -> None:
        """DebateResult with 2 agents exposes backward-compat properties."""
        result = DebateResult(
            status="CONSENSUS_REACHED",
            final_approach="Combined approach",
            final_capabilities=["python"],
            final_mode="PARALLEL",
            debate_history=[],
            total_turns=3,
            resolved_disagreements=["approach"],
            unresolved_disagreements=[],
            consensus_confidence=0.9,
            satisfactions={"gemini": 0.85, "claude": 0.75},
        )
        assert result.gemini_satisfaction == 0.85
        assert result.claude_satisfaction == 0.75

    def test_n_agents(self) -> None:
        """DebateResult with N agents stores all satisfactions."""
        result = DebateResult(
            status="FORCED_VOTE",
            final_approach="Majority wins",
            final_capabilities=["code_review"],
            final_mode="LEAD_SUPPORT",
            debate_history=[],
            total_turns=5,
            resolved_disagreements=[],
            unresolved_disagreements=["complexity"],
            consensus_confidence=0.5,
            satisfactions={
                "gemini": 0.6,
                "claude": 0.4,
                "deepseek": 0.8,
                "openai": 0.7,
            },
        )
        assert len(result.satisfactions) == 4
        assert result.satisfactions["deepseek"] == 0.8
        assert result.satisfactions["openai"] == 0.7
        # Backward compat
        assert result.gemini_satisfaction == 0.6
        assert result.claude_satisfaction == 0.4

    def test_missing_agent_defaults_to_zero(self) -> None:
        """Backward-compat satisfaction returns 0.0 for absent agents."""
        result = DebateResult(
            status="TIMEOUT",
            final_approach="Default",
            final_capabilities=[],
            final_mode="SPECIALIST",
            debate_history=[],
            total_turns=0,
            resolved_disagreements=[],
            unresolved_disagreements=[],
            consensus_confidence=0.0,
            satisfactions={"deepseek": 0.9},
        )
        assert result.gemini_satisfaction == 0.0
        assert result.claude_satisfaction == 0.0

    def test_empty_satisfactions(self) -> None:
        """Default empty satisfactions dict works."""
        result = DebateResult(
            status="IMMEDIATE_CONSENSUS",
            final_approach="Quick",
            final_capabilities=[],
            final_mode="PARALLEL",
            debate_history=[],
            total_turns=0,
            resolved_disagreements=[],
            unresolved_disagreements=[],
            consensus_confidence=1.0,
        )
        assert result.satisfactions == {}
        assert result.gemini_satisfaction == 0.0
        assert result.claude_satisfaction == 0.0

    def test_with_debate_history(self) -> None:
        """DebateResult stores debate history alongside N-agent satisfactions."""
        arg = DebateArgument(
            agent_id="gemini",
            turn_number=1,
            position="SUPPORT",
            target_point="approach",
            argument="RAG is better for this use case",
            evidence=["paper_123"],
        )
        result = DebateResult(
            status="CONSENSUS_REACHED",
            final_approach="Use RAG",
            final_capabilities=["rag", "search"],
            final_mode="PARALLEL",
            debate_history=[arg],
            total_turns=1,
            resolved_disagreements=["approach"],
            unresolved_disagreements=[],
            consensus_confidence=0.95,
            satisfactions={"gemini": 0.95, "claude": 0.9, "deepseek": 0.85},
        )
        assert len(result.debate_history) == 1
        assert result.debate_history[0].agent_id == "gemini"
        assert result.satisfactions["deepseek"] == 0.85


# =============================================================================
# Integration / cross-type tests
# =============================================================================


class TestCrossTypeIntegration:
    """Tests that the refactored types work together correctly."""

    def test_full_pipeline_two_agents(self) -> None:
        """Simulate a 2-agent pipeline: analyses -> comparison -> debate result."""
        gemini = _make_analysis("gemini", confidence=0.9)
        claude = _make_analysis("claude", confidence=0.6)

        d = Disagreement(
            topic="confidence",
            positions={"gemini": 0.9, "claude": 0.6},
            severity=0.4,
        )

        comp = AnalysisComparison(
            analyses={"gemini": gemini, "claude": claude},
            disagreements=[d],
            agreement_score=0.7,
            needs_debate=True,
        )

        # Backward-compat access chain works
        gap = abs(comp.gemini_analysis.confidence - comp.claude_analysis.confidence)
        assert gap == pytest.approx(0.3)

        result = DebateResult(
            status="CONSENSUS_REACHED",
            final_approach=comp.gemini_analysis.proposed_approach,
            final_capabilities=["python", "testing"],
            final_mode="PARALLEL",
            debate_history=[],
            total_turns=2,
            resolved_disagreements=["confidence"],
            unresolved_disagreements=[],
            consensus_confidence=0.85,
            satisfactions={"gemini": 0.8, "claude": 0.75},
        )
        assert result.gemini_satisfaction > result.claude_satisfaction

    def test_full_pipeline_three_agents(self) -> None:
        """Simulate a 3-agent pipeline."""
        agents = {aid: _make_analysis(aid, c) for aid, c in [
            ("gemini", 0.9), ("claude", 0.7), ("deepseek", 0.85)
        ]}

        d = Disagreement(
            topic="approach",
            positions={aid: a.proposed_approach for aid, a in agents.items()},
            severity=0.6,
        )

        comp = AnalysisComparison(
            analyses=agents,
            disagreements=[d],
            agreement_score=0.65,
            needs_debate=True,
        )

        assert len(comp.analyses) == 3
        assert comp.analyses["deepseek"].confidence == 0.85

        result = DebateResult(
            status="FORCED_VOTE",
            final_approach="Majority approach",
            final_capabilities=["python", "testing"],
            final_mode="LEAD_SUPPORT",
            debate_history=[],
            total_turns=4,
            resolved_disagreements=[],
            unresolved_disagreements=["approach"],
            consensus_confidence=0.55,
            satisfactions={"gemini": 0.7, "claude": 0.5, "deepseek": 0.8},
        )

        # Highest satisfaction from deepseek
        assert max(result.satisfactions, key=result.satisfactions.get) == "deepseek"
        # Backward compat still works
        assert result.gemini_satisfaction == 0.7
        assert result.claude_satisfaction == 0.5
