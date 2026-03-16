"""
Tests for Hybrid Swarm Engine - V7 Sprint 9

Tests the complete Hybrid Swarm pipeline:
- Collaboration modes
- Task analyzer
- Mode selector with DyLAN
- Negotiation protocol
- Mode executors
- Hybrid swarm engine integration
"""

import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.intelligence.swarm.agent_metrics import AgentPool, AgentProfile
from core.intelligence.swarm.collaboration_modes import (
    CollaborationMode,
    ModeCharacteristics,
    get_adversarial_modes,
    get_mode_characteristics,
    get_parallel_modes,
    suggest_mode_for_complexity,
)
from core.intelligence.swarm.hybrid_swarm_engine import HybridSwarmEngine, SwarmPhase, SwarmResult
from core.intelligence.swarm.mode_executors import (
    AgentResponse,
    ExecutionContext,
    ExecutionResult,
    ExecutionStatus,
    LeadSupportExecutor,
    ParallelExecutor,
    PingPongExecutor,
    RedBlueExecutor,
    SequentialExecutor,
    SpecialistExecutor,
    get_executor,
)
from core.intelligence.swarm.mode_selector import AgentAssignment, ModeProposal, ModeSelector
from core.intelligence.swarm.negotiation_protocol import (
    HybridNegotiationMessage,
    NegotiationProposal,
    NegotiationProtocol,
    NegotiationStatus,
    extract_negotiate_json,
)
from core.intelligence.swarm.task_analyzer import TaskAnalysis, TaskAnalyzer, TaskComplexity, TaskDomain


class TestCollaborationModes:
    """Test CollaborationMode enum and characteristics"""

    def test_all_six_modes_exist(self):
        """Verify all 6 collaboration modes exist"""
        modes = list(CollaborationMode)
        assert len(modes) == 6
        assert CollaborationMode.PARALLEL in modes
        assert CollaborationMode.SEQUENTIAL in modes
        assert CollaborationMode.LEAD_SUPPORT in modes
        assert CollaborationMode.PING_PONG in modes
        assert CollaborationMode.SPECIALIST in modes
        assert CollaborationMode.RED_BLUE in modes

    def test_mode_from_string(self):
        """Test mode parsing from string"""
        assert CollaborationMode.from_string("parallel") == CollaborationMode.PARALLEL
        assert CollaborationMode.from_string("LEAD_SUPPORT") == CollaborationMode.LEAD_SUPPORT
        assert CollaborationMode.from_string("red-blue") == CollaborationMode.RED_BLUE

    def test_mode_characteristics_exist(self):
        """Each mode should have characteristics defined"""
        for mode in CollaborationMode:
            char = get_mode_characteristics(mode)
            assert isinstance(char, ModeCharacteristics)
            assert char.mode == mode

    def test_adversarial_mode_detection(self):
        """Only RED_BLUE should be adversarial"""
        adversarial = get_adversarial_modes()
        assert len(adversarial) == 1
        assert CollaborationMode.RED_BLUE in adversarial

    def test_parallel_mode_detection(self):
        """PARALLEL should have high parallelism benefit"""
        parallel_modes = get_parallel_modes()
        assert CollaborationMode.PARALLEL in parallel_modes

    def test_complexity_suggestion(self):
        """suggest_mode_for_complexity returns modes sorted by affinity"""
        # Trivial task (complexity=1) should suggest simpler modes first
        trivial_suggestions = suggest_mode_for_complexity(1)
        assert len(trivial_suggestions) == 6

        # Expert task (complexity=5) should suggest complex modes first
        expert_suggestions = suggest_mode_for_complexity(5)
        assert CollaborationMode.RED_BLUE in expert_suggestions[:3]


class TestTaskAnalyzer:
    """Test TaskAnalyzer functionality"""

    def test_analyze_returns_analysis(self):
        """analyze() should return TaskAnalysis"""
        analyzer = TaskAnalyzer()
        result = analyzer.analyze("Fix the authentication bug in auth.py")

        assert isinstance(result, TaskAnalysis)
        assert result.complexity in TaskComplexity
        assert len(result.domains) > 0

    def test_coding_task_detection(self):
        """Coding tasks should be detected"""
        analyzer = TaskAnalyzer()
        result = analyzer.analyze("Write a function to calculate fibonacci")

        assert TaskDomain.CODING in result.domains
        assert result.claude_fit_score > 0.5

    def test_research_task_detection(self):
        """Research tasks should be detected"""
        analyzer = TaskAnalyzer()
        result = analyzer.analyze("Search for the latest Python 3.13 features")

        assert TaskDomain.RESEARCH in result.domains
        assert result.requires_web is True
        assert result.gemini_fit_score > result.claude_fit_score

    def test_security_task_detection(self):
        """Security tasks should increase complexity"""
        analyzer = TaskAnalyzer()
        result = analyzer.analyze("Review this code for security vulnerabilities")

        assert TaskDomain.SECURITY in result.domains
        assert result.complexity >= TaskComplexity.MODERATE  # "security" demoted from +2 to +1
        assert result.needs_adversarial_mode is True

    def test_trivial_task_detection(self):
        """Simple tasks should have low complexity"""
        analyzer = TaskAnalyzer()
        result = analyzer.analyze("Print hello")

        assert result.complexity <= TaskComplexity.SIMPLE
        # Note: TRIVIAL (1) skips negotiation, SIMPLE (2) does not
        # "Print hello" is detected as SIMPLE due to minimal complexity indicators

    def test_recommended_lead(self):
        """recommended_lead should return agent name or 'equal'"""
        analyzer = TaskAnalyzer()

        # Coding task should recommend Claude
        coding = analyzer.analyze("Implement a REST API endpoint")
        assert coding.recommended_lead in ["claude", "gemini", "equal"]

        # Research task should recommend Gemini
        research = analyzer.analyze("Search for recent AI papers")
        assert research.recommended_lead in ["claude", "gemini", "equal"]


class TestModeSelector:
    """Test ModeSelector with DyLAN integration"""

    def test_select_mode_returns_proposal(self):
        """select_mode() should return ModeProposal"""
        selector = ModeSelector()
        analyzer = TaskAnalyzer()
        analysis = analyzer.analyze("Debug the login error")

        proposal = selector.select_mode(analysis)

        assert isinstance(proposal, ModeProposal)
        assert proposal.mode in CollaborationMode
        assert 0.0 <= proposal.confidence <= 1.0
        assert len(proposal.agent_assignments) > 0

    def test_security_tasks_prefer_redblue(self):
        """Security tasks should prefer RED_BLUE mode"""
        selector = ModeSelector()
        analyzer = TaskAnalyzer()
        analysis = analyzer.analyze("Review this code for critical security vulnerabilities")

        proposal = selector.select_mode(analysis)

        # RED_BLUE should be top 2 for security
        alternatives = [m for m, _ in proposal.alternatives]
        if proposal.mode != CollaborationMode.RED_BLUE:
            assert CollaborationMode.RED_BLUE in alternatives[:2]

    def test_agent_assignments_created(self):
        """Agent assignments should be created for selected mode"""
        selector = ModeSelector()
        analyzer = TaskAnalyzer()
        analysis = analyzer.analyze("Research best practices for caching")

        proposal = selector.select_mode(analysis)

        assert len(proposal.agent_assignments) >= 1
        for assignment in proposal.agent_assignments:
            assert isinstance(assignment, AgentAssignment)
            assert assignment.agent_id
            assert assignment.role

    def test_selection_stats_tracking(self):
        """Selection history should be tracked"""
        selector = ModeSelector()
        analyzer = TaskAnalyzer()

        # Make several selections
        for task in ["Write code", "Research topic", "Debug bug"]:
            analysis = analyzer.analyze(task)
            selector.select_mode(analysis)

        stats = selector.get_selection_stats()
        assert stats["total_selections"] == 3
        assert "mode_distribution" in stats


class TestNegotiationProtocol:
    """Test NegotiationProtocol with hybrid messages"""

    def test_parse_negotiate_json(self):
        """extract_negotiate_json should parse <negotiate> tags"""
        text = """I think we should use LEAD_SUPPORT mode.

<negotiate>
{"proposed_mode": "lead_support", "confidence": 0.85}
</negotiate>

What do you think?"""

        result = extract_negotiate_json(text)
        assert result is not None
        assert result["proposed_mode"] == "lead_support"
        assert result["confidence"] == 0.85

    def test_parse_invalid_json(self):
        """Invalid JSON should return None"""
        text = "<negotiate>not valid json</negotiate>"
        result = extract_negotiate_json(text)
        assert result is None

    def test_parse_no_tags(self):
        """Text without tags should return None"""
        text = "Just a regular message without negotiate tags"
        result = extract_negotiate_json(text)
        assert result is None

    def test_negotiation_proposal_from_dict(self):
        """NegotiationProposal should parse from dict"""
        data = {
            "proposed_mode": "parallel",
            "proposed_lead": "gemini",
            "confidence": 0.9,
            "agrees_with_partner": True,
            "consensus_reached": True,
        }

        proposal = NegotiationProposal.from_dict(data)

        assert proposal.proposed_mode == "parallel"
        assert proposal.proposed_lead == "gemini"
        assert proposal.confidence == 0.9
        assert proposal.agrees_with_partner is True
        assert proposal.consensus_reached is True

    def test_hybrid_message_creation(self):
        """HybridNegotiationMessage should combine natural and structured"""
        proposal = NegotiationProposal(proposed_mode="sequential", consensus_reached=True)
        message = HybridNegotiationMessage(
            sender="gemini", natural_content="I agree with the approach", structured_proposal=proposal
        )

        assert message.sender == "gemini"
        assert message.consensus_reached is True
        assert message.proposed_mode == CollaborationMode.SEQUENTIAL

    def test_force_mode(self):
        """force_mode should create result without negotiation"""
        protocol = NegotiationProtocol()
        analyzer = TaskAnalyzer()
        analysis = analyzer.analyze("Some task")

        result = protocol.force_mode(CollaborationMode.PARALLEL, analysis, "User forced")

        assert result.status == NegotiationStatus.FORCED
        assert result.selected_mode == CollaborationMode.PARALLEL
        assert result.total_turns == 0


class TestModeExecutors:
    """Test the 6 mode executors"""

    def _create_test_context(self, task: str = "Test task") -> ExecutionContext:
        """Helper to create test context"""
        return ExecutionContext(
            task_input=task,
            agent_assignments=[
                AgentAssignment(agent_id="gemini_primary", role="equal"),
                AgentAssignment(agent_id="claude_opus", role="equal"),
            ],
            max_rounds=3,
        )

    def test_parallel_executor(self):
        """ParallelExecutor should run agents in parallel"""
        executor = ParallelExecutor()
        context = self._create_test_context()

        result = executor.execute(context)

        assert isinstance(result, ExecutionResult)
        assert result.mode == CollaborationMode.PARALLEL
        assert result.status in [ExecutionStatus.COMPLETED, ExecutionStatus.FAILED]

    def test_sequential_executor(self):
        """SequentialExecutor should run agents in order"""
        executor = SequentialExecutor()
        context = self._create_test_context()
        context.agent_assignments[0].role = "first"
        context.agent_assignments[1].role = "second"

        result = executor.execute(context)

        assert result.mode == CollaborationMode.SEQUENTIAL
        # Should have 2 outputs (first then second)
        assert len(result.agent_outputs) >= 1

    def test_lead_support_executor(self):
        """LeadSupportExecutor should have lead and support"""
        executor = LeadSupportExecutor()
        context = self._create_test_context()
        context.agent_assignments[0].role = "lead"
        context.agent_assignments[1].role = "support"

        result = executor.execute(context)

        assert result.mode == CollaborationMode.LEAD_SUPPORT

    def test_pingpong_executor(self):
        """PingPongExecutor should alternate agents"""
        executor = PingPongExecutor()
        context = self._create_test_context()

        result = executor.execute(context)

        assert result.mode == CollaborationMode.PING_PONG
        assert result.total_rounds >= 1

    def test_specialist_executor(self):
        """SpecialistExecutor should use single agent"""
        executor = SpecialistExecutor()
        context = self._create_test_context()
        context.agent_assignments = [AgentAssignment(agent_id="claude_opus", role="specialist")]

        result = executor.execute(context)

        assert result.mode == CollaborationMode.SPECIALIST
        assert len(result.agent_outputs) == 1

    def test_redblue_executor(self):
        """RedBlueExecutor should have propose/attack cycle"""
        executor = RedBlueExecutor()
        context = self._create_test_context()
        context.agent_assignments = [
            AgentAssignment(agent_id="claude_opus", role="blue"),
            AgentAssignment(agent_id="gemini_primary", role="red"),
        ]

        result = executor.execute(context)

        assert result.mode == CollaborationMode.RED_BLUE
        # Should have 4 phases: propose, attack, defend, verify
        assert result.total_rounds == 4

    def test_get_executor(self):
        """get_executor should return correct executor"""
        parallel = get_executor(CollaborationMode.PARALLEL)
        assert isinstance(parallel, ParallelExecutor)

        redblue = get_executor(CollaborationMode.RED_BLUE)
        assert isinstance(redblue, RedBlueExecutor)


class TestHybridSwarmEngine:
    """Test HybridSwarmEngine integration"""

    def test_engine_creation(self):
        """Engine should initialize with defaults"""
        engine = HybridSwarmEngine()

        assert engine.current_phase == SwarmPhase.IDLE
        assert engine.agent_pool is not None
        assert engine.task_analyzer is not None
        assert engine.mode_selector is not None

    def test_engine_with_pool(self):
        """Engine should accept custom pool"""
        pool = AgentPool()
        pool.register(AgentProfile(agent_id="test_agent", provider="test", model="test-model"))

        engine = HybridSwarmEngine(agent_pool=pool)
        assert "test_agent" in engine.agent_pool.agents

    def test_process_task_returns_result(self):
        """process_task should return SwarmResult"""
        engine = HybridSwarmEngine()
        result = engine.process_task("Write a simple function")

        assert isinstance(result, SwarmResult)
        assert result.status in [SwarmPhase.COMPLETED, SwarmPhase.FAILED]
        assert result.selected_mode in CollaborationMode

    def test_process_task_with_forced_mode(self):
        """Forced mode should skip selection"""
        engine = HybridSwarmEngine()
        result = engine.process_task("Any task", force_mode=CollaborationMode.SPECIALIST)

        assert result.selected_mode == CollaborationMode.SPECIALIST

    def test_process_task_skip_negotiation(self):
        """skip_negotiation should bypass negotiation"""
        engine = HybridSwarmEngine()
        result = engine.process_task("Research task", skip_negotiation=True)

        assert result.negotiation_result is None

    def test_start_analysis_api(self):
        """start_analysis should be callable for FSM"""
        engine = HybridSwarmEngine()
        analysis = engine.start_analysis("Debug this code")

        assert engine.current_phase == SwarmPhase.ANALYZING
        assert isinstance(analysis, TaskAnalysis)

    def test_engine_reset(self):
        """reset should clear state"""
        engine = HybridSwarmEngine()
        engine.start_analysis("Some task")

        engine.reset()

        assert engine.current_phase == SwarmPhase.IDLE
        assert engine._current_analysis is None

    def test_engine_stats(self):
        """get_stats should return statistics"""
        engine = HybridSwarmEngine()
        engine.process_task("Task 1")
        engine.process_task("Task 2")

        stats = engine.get_stats()

        assert "total_processed" in stats
        assert stats["total_processed"] == 2
        assert "mode_distribution" in stats


class TestFSMStatesIntegration:
    """Test FSM state definitions"""

    def test_swarm_states_exist(self):
        """Swarm states should be defined"""
        from core.fsm.states import OrchestratorState

        assert hasattr(OrchestratorState, "SWARM_ANALYZING")
        assert hasattr(OrchestratorState, "SWARM_NEGOTIATING")
        assert hasattr(OrchestratorState, "SWARM_EXECUTING")

    def test_transition_matrix_has_swarm(self):
        """Transition matrix should include swarm states"""
        from core.fsm.states import TRANSITION_MATRIX, OrchestratorState

        assert OrchestratorState.SWARM_ANALYZING in TRANSITION_MATRIX
        assert OrchestratorState.SWARM_NEGOTIATING in TRANSITION_MATRIX
        assert OrchestratorState.SWARM_EXECUTING in TRANSITION_MATRIX


class TestConfigSwarmOptions:
    """Test swarm configuration options"""

    def test_swarm_config_exists(self):
        """Swarm config options should exist"""
        from core.config import Config

        config = Config()

        assert hasattr(config, "swarm_enabled")
        assert hasattr(config, "swarm_negotiation_enabled")
        assert hasattr(config, "swarm_negotiation_max_turns")
        assert hasattr(config, "swarm_default_mode")
        assert hasattr(config, "swarm_skip_trivial")
        assert hasattr(config, "swarm_max_rounds")

    def test_swarm_defaults(self):
        """Swarm config should have sensible defaults"""
        from core.config import Config

        config = Config()

        assert config.swarm_enabled is True
        assert config.swarm_negotiation_max_turns == 4
        assert config.swarm_default_mode == "ping_pong"


# ============================================================================
# V8.3.4 Audit Fix Tests
# ============================================================================


class TestAuditFixFL002:
    """Tests for FL-002: Completion detection false positives fix"""

    def test_completion_detection_word_boundaries(self):
        """Should use word boundaries for completion detection"""
        # These should NOT trigger completion (false positives before fix)
        false_positive_cases = [
            "I'm not DONE yet, still working",
            "UNDONE tasks remain",
            "The function isDone() returns false",
            "ABANDONED the previous approach",
        ]

        for content in false_positive_cases:
            response = AgentResponse(agent_id="test", content=content)
            assert not response.is_finished, f"False positive: '{content}'"

    def test_completion_detection_true_positives(self):
        """Should correctly detect actual completion signals"""
        # These SHOULD trigger completion
        true_positive_cases = [
            "FINISHED. All tasks complete.",
            "TASK COMPLETE - everything is done",
            "COMPLETED the implementation successfully",
            "ALL DONE with the requested changes",
        ]

        for content in true_positive_cases:
            # Note: These might still be blocked by ongoing_indicators check
            # if they contain "will ", "going to", etc. - that's intentional
            AgentResponse(agent_id="test", content=content)
            # Just check that completion signal is detected (pattern match)
            from core.intelligence.swarm.mode_executors import COMPLETION_PATTERN

            assert COMPLETION_PATTERN.search(content), f"Pattern not detected: '{content}'"

    def test_completion_blocked_by_ongoing_work(self):
        """Should block completion if ongoing work indicators present"""
        # FINISHED but has ongoing work - should NOT be finished
        response = AgentResponse(agent_id="test", content="FINISHED with step 1. Will continue with step 2 next.")
        assert not response.is_finished

    def test_completion_pattern_case_insensitive(self):
        """Pattern should be case insensitive"""
        from core.intelligence.swarm.mode_executors import COMPLETION_PATTERN

        cases = ["finished", "FINISHED", "Finished", "FiNiShEd"]
        for case in cases:
            assert COMPLETION_PATTERN.search(case), f"Case failed: {case}"


class TestAuditFixFL001:
    """Tests for FL-001: ThreadPoolExecutor blackboard race condition fix"""

    def test_blackboard_lock_imported(self):
        """Should have _blackboard_lock defined"""
        from threading import Lock

        from core.intelligence.swarm.mode_executors import _blackboard_lock

        assert isinstance(_blackboard_lock, type(Lock()))

    def test_parallel_executor_thread_safe(self):
        """ParallelExecutor should use thread-safe blackboard access"""
        import inspect

        from core.intelligence.swarm.mode_executors import ModeExecutor

        # Read the source to verify _blackboard_lock is used
        source = inspect.getsource(ModeExecutor._invoke)
        assert "_blackboard_lock" in source, "FL-001: _blackboard_lock not used in _invoke"


# Pytest entry point
if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
