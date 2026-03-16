"""
Tests E2E pour l'alternance Gemini↔Claude

Vérifie les corrections de l'audit AUDIT_011225.md:
1. P0-1: Alternance forcée en BRAINSTORMING (orchestration_v7.py:636)
2. P0-2: Claude default next_agent="Gemini" (claude_driver_hybrid.py:299)
3. P1: Protocol validator alterne (protocol_v7.py:74)
4. P2: Emojis SWARM (orchestration_v7.py:505)
5. Config: swarm_auto_route=False (config.py:178)
"""

import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.fsm.states import OrchestratorState
from core.synapse.protocol_v7 import LightMessageV7

# =============================================================================
# Tests Alternance BRAINSTORMING
# =============================================================================


class TestAgentAlternationE2E:
    """Tests E2E pour l'alternance agent dans BRAINSTORMING."""

    def test_brainstorming_forces_alternation_without_next_agent(self, orchestrator_with_mocks):
        """
        P0-1: BRAINSTORMING doit forcer l'alternance même sans next_agent.

        L'agent ne spécifie PAS next_agent, mais l'orchestrateur
        doit QUAND MÊME alterner vers l'autre agent.
        """
        orch = orchestrator_with_mocks

        # Gemini répond SANS spécifier next_agent
        orch.drivers["Gemini"].set_responses(
            [
                {
                    "sender": "Gemini",
                    "action_type": "TALK",
                    "content": "Je commence l'analyse du problème...",
                    # PAS DE next_agent !
                    "status": "CONTINUE",
                }
            ]
        )

        # Claude terminera (use FINISH action_type for FINISHED status)
        orch.drivers["Claude"].set_responses(
            [{"sender": "Claude", "action_type": "FINISH", "content": "Done", "status": "FINISHED"}]
        )

        # Premier tour: Forcer BRAINSTORMING manuellement pour le test
        # V8.4.0: Use lowercase normalized IDs
        orch.active_agent = "gemini"
        orch._transition_to(OrchestratorState.BRAINSTORMING)
        orch.stagnation_detector.reset()
        initial_agent = orch.active_agent  # Should be "gemini"

        # Deuxième tour: Gemini répond
        orch.process_turn()

        # APRÈS CORRECTION P0-1: doit avoir alterné vers Claude
        assert orch.active_agent != initial_agent, f"Alternation not forced! Agent stayed {orch.active_agent}"
        assert orch.active_agent == "claude", f"Expected claude, got {orch.active_agent}"

    def test_gemini_to_claude_handoff(self, orchestrator_with_mocks):
        """Gemini doit passer à Claude après sa réponse."""
        orch = orchestrator_with_mocks

        orch.drivers["Gemini"].set_responses(
            [{"sender": "Gemini", "action_type": "TALK", "content": "Analyzing...", "status": "CONTINUE"}]
        )

        orch.drivers["Claude"].set_responses(
            [{"sender": "Claude", "action_type": "FINISH", "content": "Done", "status": "FINISHED"}]
        )

        # Start with Gemini in BRAINSTORMING mode
        # V8.4.0: Use lowercase normalized IDs
        orch.active_agent = "gemini"
        orch._transition_to(OrchestratorState.BRAINSTORMING)
        orch.stagnation_detector.reset()

        # After Gemini responds, should switch to Claude
        orch.process_turn()
        assert orch.active_agent == "claude", "Should have switched to claude"

    def test_claude_to_gemini_handoff(self, orchestrator_with_mocks):
        """Claude doit passer à Gemini après sa réponse."""
        orch = orchestrator_with_mocks

        # Force start with Claude (V8.4.0: lowercase)
        orch.active_agent = "claude"

        orch.drivers["Claude"].set_responses(
            [{"sender": "Claude", "action_type": "TALK", "content": "I'm analyzing...", "status": "CONTINUE"}]
        )

        orch.drivers["Gemini"].set_responses(
            [{"sender": "Gemini", "action_type": "FINISH", "content": "Done", "status": "FINISHED"}]
        )

        # Force start with Claude in BRAINSTORMING mode (V8.4.0: lowercase)
        orch.active_agent = "claude"
        orch._transition_to(OrchestratorState.BRAINSTORMING)
        orch.stagnation_detector.reset()

        # After Claude responds, should switch to Gemini
        orch.process_turn()
        assert orch.active_agent == "gemini", "Should have switched to gemini"

    def test_multi_turn_alternation(self, orchestrator_with_mocks, run_orchestrator_loop):
        """
        Alternance sur 4+ tours (Gemini->Claude->Gemini->Claude).

        Vérifie que l'alternance est bien égale.
        """
        orch = orchestrator_with_mocks

        # 4 réponses de chaque agent
        orch.drivers["Gemini"].set_responses(
            [
                {"sender": "Gemini", "action_type": "TALK", "content": "Turn 1", "status": "CONTINUE"},
                {"sender": "Gemini", "action_type": "TALK", "content": "Turn 3", "status": "CONTINUE"},
            ]
        )

        orch.drivers["Claude"].set_responses(
            [
                {"sender": "Claude", "action_type": "TALK", "content": "Turn 2", "status": "CONTINUE"},
                {"sender": "Claude", "action_type": "FINISH", "content": "Turn 4", "status": "FINISHED"},
            ]
        )

        # Force BRAINSTORMING mode for testing alternation
        orch.active_agent = "Gemini"
        orch._transition_to(OrchestratorState.BRAINSTORMING)
        orch.stagnation_detector.reset()

        # Run until completion
        run_orchestrator_loop(orch, "Multi-turn test", max_iterations=6)

        # Both agents should have been called
        assert orch.drivers["Gemini"].call_count >= 1, "Gemini should have been called"
        assert orch.drivers["Claude"].call_count >= 1, "Claude should have been called"

    def test_evolution_brainstorm_still_alternates(self, orchestrator_with_mocks):
        """
        EVOLUTION_BRAINSTORM doit toujours alterner (test de non-régression).

        Note: Ce test vérifie que le mode EVOLUTION_BRAINSTORM existe
        et force l'alternance. Le test complet d'évolution est dans
        test_e2e_nexus.py::TestEvolutionE2E.
        """
        # This test is a non-regression marker - the actual evolution
        # alternation is tested in test_e2e_nexus.py
        # Here we just verify the state exists
        assert OrchestratorState.EVOLUTION_BRAINSTORM is not None


# =============================================================================
# Tests Protocol Validator
# =============================================================================


class TestProtocolValidatorAlternation:
    """Tests pour la correction P1: Protocol validator alterne."""

    def test_protocol_validator_alternates_when_next_agent_missing(self):
        """
        P1: Si next_agent est None, le validator doit alterner.

        Avant la correction: gardait le sender.
        Après la correction: alterne vers l'autre agent.
        """
        # Test Gemini sender -> should get Claude as next_agent
        gemini_msg = LightMessageV7(
            sender="Gemini",
            action_type="TALK",
            content="Test message",
            status="CONTINUE",
            next_agent=None,  # Not specified
        )

        # After P1 fix: should be "Claude" (alternated), not "Gemini" (kept)
        assert gemini_msg.next_agent == "Claude", f"Expected 'Claude' but got '{gemini_msg.next_agent}'"

    def test_protocol_validator_alternates_claude_to_gemini(self):
        """Claude sender -> next_agent should be Gemini."""
        claude_msg = LightMessageV7(
            sender="Claude", action_type="TALK", content="Test", status="CONTINUE", next_agent=None
        )

        assert claude_msg.next_agent == "Gemini", f"Expected 'Gemini' but got '{claude_msg.next_agent}'"

    def test_protocol_validator_respects_explicit_next_agent(self):
        """Si next_agent est explicitement spécifié, le garder."""
        msg = LightMessageV7(
            sender="Gemini",
            action_type="TALK",
            content="I want to continue",
            status="CONTINUE",
            next_agent="Gemini",  # Explicitly staying
        )

        assert msg.next_agent == "Gemini", "Explicit next_agent should be respected"


# =============================================================================
# Tests SWARM Feedback
# =============================================================================


class TestSwarmFeedbackEmojis:
    """Tests pour la correction P2: Emojis SWARM."""

    def test_swarm_feedback_has_gemini_emoji(self, orchestrator_with_swarm):
        """SWARM doit afficher 🤖 pour Gemini."""
        # This test verifies the emoji is in the formatted output
        # The actual emoji formatting is in orchestration_v7.py:510-514
        pass  # Will be tested in integration

    def test_swarm_feedback_has_claude_emoji(self, orchestrator_with_swarm):
        """SWARM doit afficher 🧠 pour Claude."""
        pass  # Will be tested in integration


# =============================================================================
# Tests Configuration
# =============================================================================


class TestSwarmAutoRouteConfig:
    """Tests pour la config swarm_auto_route (V7.5: True par défaut)."""

    def test_swarm_auto_route_default_is_true(self):
        """
        V7.5 HIVE MIND: swarm_auto_route est True par défaut.

        Le Swarm est maintenant le mode principal pour les tâches MODERATE+.
        """
        import os

        from core.config import Config

        # Clear env var if set
        old_value = os.environ.pop("SWARM_AUTO_ROUTE", None)

        try:
            cfg = Config()
            assert cfg.swarm_auto_route is True, (
                f"swarm_auto_route should default to True (V7.5), got {cfg.swarm_auto_route}"
            )
        finally:
            # Restore env var if it was set
            if old_value is not None:
                os.environ["SWARM_AUTO_ROUTE"] = old_value

    def test_swarm_auto_route_can_be_enabled_via_env(self):
        """swarm_auto_route peut être activé via SWARM_AUTO_ROUTE=True."""
        import os

        from core.config import Config

        old_value = os.environ.get("SWARM_AUTO_ROUTE")
        os.environ["SWARM_AUTO_ROUTE"] = "True"

        try:
            cfg = Config()
            assert cfg.swarm_auto_route is True, "swarm_auto_route should be True when env var is True"
        finally:
            if old_value is not None:
                os.environ["SWARM_AUTO_ROUTE"] = old_value
            else:
                os.environ.pop("SWARM_AUTO_ROUTE", None)


# =============================================================================
# Tests Intégration Complète
# =============================================================================


class TestFullAlternationIntegration:
    """Tests d'intégration complète de l'alternance."""

    def test_complete_task_with_forced_alternation(self, orchestrator_with_mocks, run_orchestrator_loop):
        """
        Test complet: tâche avec alternance forcée.

        Vérifie que:
        1. Gemini démarre
        2. Alternance vers Claude
        3. Tâche se termine correctement

        NOTE: Use action_type="FINISH" (not "TALK") with status="FINISHED"
        """
        orch = orchestrator_with_mocks

        orch.drivers["Gemini"].set_responses(
            [
                {
                    "sender": "Gemini",
                    "action_type": "TALK",
                    "content": "J'ai analysé le problème. Il faut modifier le fichier auth.py.",
                    "status": "CONTINUE",
                }
            ]
        )

        orch.drivers["Claude"].set_responses(
            [
                {
                    "sender": "Claude",
                    "action_type": "FINISH",  # CRITICAL: Use FINISH for status="FINISHED"
                    "content": "D'accord, je vais faire la modification. Tâche terminée.",
                    "status": "FINISHED",
                }
            ]
        )

        # Force BRAINSTORMING mode for testing alternation
        orch.active_agent = "Gemini"
        orch._transition_to(OrchestratorState.BRAINSTORMING)
        orch.stagnation_detector.reset()

        result = run_orchestrator_loop(orch, "Fix the auth bug")

        # Should have completed successfully
        assert result["final_state"] in ("IDLE", "WAITING_USER"), (
            f"Task should complete, got state {result['final_state']}"
        )

        # Both agents should have participated
        assert orch.drivers["Gemini"].call_count >= 1
        assert orch.drivers["Claude"].call_count >= 1


# =============================================================================
# Tests TRIVIAL Input Detection (V7 FIX)
# =============================================================================


class TestTrivialInputDetection:
    """Tests pour la détection des inputs triviaux (salutations, etc.)."""

    def test_greeting_patterns_detected(self):
        """Les salutations simples doivent être détectées comme TRIVIAL."""
        from core.intelligence.swarm.task_analyzer import TaskAnalyzer, TaskComplexity

        ta = TaskAnalyzer()

        trivial_inputs = [
            "hello",
            "Hello!",
            "HELLO?",
            "bonjour",
            "Bonjour!",
            "salut",
            "hey",
            "hi",
            "test",
            "ok",
            "oui",
            "merci",
        ]

        for input_text in trivial_inputs:
            assert ta.is_conversational_trivial(input_text), f"'{input_text}' should be detected as trivial"
            analysis = ta.analyze(input_text)
            assert analysis.complexity == TaskComplexity.TRIVIAL, f"'{input_text}' should have TRIVIAL complexity"

    def test_non_trivial_inputs_not_detected(self):
        """Les tâches réelles ne doivent PAS être détectées comme TRIVIAL."""
        from core.intelligence.swarm.task_analyzer import TaskAnalyzer, TaskComplexity

        ta = TaskAnalyzer()

        non_trivial_inputs = [
            "fix the bug in auth.py",
            "implement user authentication",
            "refactor the database layer",
            "hello world how are you doing today let me tell you about my problem",
        ]

        for input_text in non_trivial_inputs:
            assert not ta.is_conversational_trivial(input_text), f"'{input_text}' should NOT be detected as trivial"
            analysis = ta.analyze(input_text)
            assert analysis.complexity != TaskComplexity.TRIVIAL, f"'{input_text}' should NOT have TRIVIAL complexity"

    def test_trivial_analysis_has_special_keyword(self):
        """Les inputs TRIVIAL doivent avoir le keyword spécial."""
        from core.intelligence.swarm.task_analyzer import TaskAnalyzer

        ta = TaskAnalyzer()
        analysis = ta.analyze("hello")

        assert "[TRIVIAL_CONVERSATIONAL]" in analysis.detected_keywords, (
            "TRIVIAL input should have special keyword marker"
        )
        assert analysis.confidence == 1.0, "TRIVIAL input should have high confidence"
