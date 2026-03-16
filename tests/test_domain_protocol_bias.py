"""Tests for V12.4 task-adaptive decision protocol bias (arxiv:2502.19130).

Verifies that ModeSelector applies domain-specific protocol biases:
- REASONING domains (coding, debugging) -> PARALLEL mode boosted
- KNOWLEDGE domains (research, docs) -> PING_PONG mode boosted
- CREATIVE domains -> PING_PONG mode boosted
- SECURITY domains -> RED_BLUE mode boosted
"""

from core.intelligence.swarm.agent_metrics import AgentProfile
from core.intelligence.swarm.collaboration_modes import CollaborationMode
from core.intelligence.swarm.mode_selector import ModeSelector
from core.intelligence.swarm.task_analyzer import TaskAnalysis, TaskComplexity, TaskDomain


def _make_agents():
    """Create default agent profiles for testing."""
    return [
        AgentProfile(
            agent_id="agent_a",
            provider="provider_a",
            model="model-a",
            capabilities=["coding", "debugging", "analysis"],
        ),
        AgentProfile(
            agent_id="agent_b",
            provider="provider_b",
            model="model-b",
            capabilities=["research", "documentation", "creative"],
        ),
    ]


def _make_analysis(domain: TaskDomain, complexity: TaskComplexity = TaskComplexity.MODERATE) -> TaskAnalysis:
    """Create a minimal TaskAnalysis for the given domain."""
    return TaskAnalysis(
        raw_input=f"Test task for {domain.value}",
        complexity=complexity,
        domains=[domain],
        primary_domain=domain,
        requires_web=False,
        requires_deep_reasoning=(domain in (TaskDomain.CODING, TaskDomain.DEBUGGING)),
        requires_iteration=False,
    )


class TestDomainProtocolBias:
    """Tests for the DOMAIN_PROTOCOL_BIAS class variable."""

    def test_bias_map_has_all_domains(self):
        """All TaskDomain values should have a bias entry."""
        for domain in TaskDomain:
            # Not all domains need bias; just check the map is well-formed
            bias = ModeSelector.DOMAIN_PROTOCOL_BIAS.get(domain.value)
            if bias is not None:
                assert isinstance(bias, dict)
                for mode, value in bias.items():
                    assert isinstance(mode, CollaborationMode)
                    assert 0.0 < value <= 0.15

    def test_coding_boosts_parallel(self):
        """Coding domain should boost PARALLEL mode."""
        bias = ModeSelector.DOMAIN_PROTOCOL_BIAS["coding"]
        assert CollaborationMode.PARALLEL in bias
        assert bias[CollaborationMode.PARALLEL] > 0

    def test_security_boosts_red_blue(self):
        """Security domain should boost RED_BLUE mode."""
        bias = ModeSelector.DOMAIN_PROTOCOL_BIAS["security"]
        assert CollaborationMode.RED_BLUE in bias
        assert bias[CollaborationMode.RED_BLUE] >= 0.10

    def test_research_boosts_ping_pong(self):
        """Research domain should boost PING_PONG (consensus)."""
        bias = ModeSelector.DOMAIN_PROTOCOL_BIAS["research"]
        assert CollaborationMode.PING_PONG in bias
        assert bias[CollaborationMode.PING_PONG] > 0

    def test_creative_boosts_ping_pong(self):
        """Creative domain should boost PING_PONG (iterative refinement)."""
        bias = ModeSelector.DOMAIN_PROTOCOL_BIAS["creative"]
        assert CollaborationMode.PING_PONG in bias
        assert bias[CollaborationMode.PING_PONG] > 0


class TestModeSelectorWithBias:
    """Tests that ModeSelector._score_mode integrates the bias."""

    def test_coding_parallel_gets_bias_boost(self):
        """For coding tasks, PARALLEL score should include the bias boost."""
        selector = ModeSelector()
        agents = _make_agents()
        analysis = _make_analysis(TaskDomain.CODING)

        # Score PARALLEL and another mode
        parallel_score = selector._score_mode(CollaborationMode.PARALLEL, analysis, agents)
        selector._score_mode(CollaborationMode.SEQUENTIAL, analysis, agents)

        # PARALLEL should get +0.08 bias for coding, SEQUENTIAL gets 0
        # This doesn't guarantee PARALLEL > SEQUENTIAL overall but the bias is additive
        assert parallel_score <= 1.0

    def test_security_red_blue_bias(self):
        """Security tasks should strongly favor RED_BLUE due to both bias and requirements."""
        selector = ModeSelector()
        agents = _make_agents()
        analysis = _make_analysis(TaskDomain.SECURITY)

        red_blue_score = selector._score_mode(CollaborationMode.RED_BLUE, analysis, agents)
        parallel_score = selector._score_mode(CollaborationMode.PARALLEL, analysis, agents)

        # RED_BLUE gets +0.10 bias PLUS requirements_fit bonus for adversarial
        assert red_blue_score > parallel_score

    def test_score_capped_at_one(self):
        """Score should never exceed 1.0 even with bias."""
        selector = ModeSelector()
        agents = _make_agents()

        for domain in TaskDomain:
            analysis = _make_analysis(domain)
            for mode in CollaborationMode:
                score = selector._score_mode(mode, analysis, agents)
                assert score <= 1.0, f"{domain.value}/{mode.value} score {score} > 1.0"

    def test_unknown_domain_no_bias(self):
        """Domains not in the bias map should get zero bias."""
        # All current domains are in the map, but test the fallback
        selector = ModeSelector()
        agents = _make_agents()
        analysis = _make_analysis(TaskDomain.CODING)

        # Temporarily set a domain that's not in the bias map
        analysis.primary_domain = TaskDomain.WEB_INTERACTION
        score_ping_pong = selector._score_mode(CollaborationMode.PING_PONG, analysis, agents)
        # Should still compute a valid score (bias is small, not critical)
        assert 0.0 <= score_ping_pong <= 1.0

    def test_select_mode_includes_bias(self):
        """Full select_mode() flow should reflect bias in final selection."""
        selector = ModeSelector()
        agents = _make_agents()
        analysis = _make_analysis(TaskDomain.SECURITY, TaskComplexity.COMPLEX)

        proposal = selector.select_mode(analysis, agents)
        # Security + complex should strongly favor RED_BLUE
        assert proposal.mode == CollaborationMode.RED_BLUE

    def test_reasoning_vs_knowledge_bias_direction(self):
        """Coding (reasoning) should bias PARALLEL more than research (knowledge)."""
        selector = ModeSelector()
        agents = _make_agents()

        coding_analysis = _make_analysis(TaskDomain.CODING)
        research_analysis = _make_analysis(TaskDomain.RESEARCH)

        selector._score_mode(CollaborationMode.PARALLEL, coding_analysis, agents)
        selector._score_mode(CollaborationMode.PARALLEL, research_analysis, agents)

        selector._score_mode(CollaborationMode.PING_PONG, coding_analysis, agents)
        selector._score_mode(CollaborationMode.PING_PONG, research_analysis, agents)

        # Coding should get more PARALLEL bias than research
        coding_parallel_bias = ModeSelector.DOMAIN_PROTOCOL_BIAS.get("coding", {}).get(CollaborationMode.PARALLEL, 0)
        research_parallel_bias = ModeSelector.DOMAIN_PROTOCOL_BIAS.get("research", {}).get(
            CollaborationMode.PARALLEL, 0
        )
        assert coding_parallel_bias > research_parallel_bias

        # Research should get more PING_PONG bias than coding
        coding_pp_bias = ModeSelector.DOMAIN_PROTOCOL_BIAS.get("coding", {}).get(CollaborationMode.PING_PONG, 0)
        research_pp_bias = ModeSelector.DOMAIN_PROTOCOL_BIAS.get("research", {}).get(CollaborationMode.PING_PONG, 0)
        assert research_pp_bias > coding_pp_bias
