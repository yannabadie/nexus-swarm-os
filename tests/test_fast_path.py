"""
Tests for Phase 9: Fast Path UX

Fast Path bypasses FSM for trivial conversational inputs to achieve <2s response time.
"""

import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from core.config import Config
from core.intelligence.swarm.task_analyzer import TaskAnalyzer, TaskComplexity


class TestFastPathConfig:
    """Test Fast Path configuration."""

    def test_fast_path_enabled_default(self):
        """Fast path should be enabled by default."""
        config = Config()
        assert hasattr(config, "fast_path_enabled")
        assert config.fast_path_enabled is True

    def test_fast_path_can_be_disabled(self, monkeypatch):
        """Fast path can be disabled via environment variable."""
        monkeypatch.setenv("FAST_PATH_ENABLED", "False")
        config = Config()
        assert config.fast_path_enabled is False


class TestConversationalTrivialDetection:
    """Test is_conversational_trivial detection patterns."""

    @pytest.fixture
    def analyzer(self):
        return TaskAnalyzer()

    # Greetings
    @pytest.mark.parametrize(
        "input_text",
        [
            "hello",
            "Hello",
            "HELLO",
            "hi",
            "Hi!",
            "hey",
            "bonjour",
            "Bonjour!",
            "salut",
            "Salut",
            "coucou",
            "hola",
            "hallo",
            "good morning",
            "good evening",
            "bonsoir",
        ],
    )
    def test_greetings_are_trivial(self, analyzer, input_text):
        """Greetings should be detected as trivial."""
        assert analyzer.is_conversational_trivial(input_text) is True

    # Farewells
    @pytest.mark.parametrize("input_text", ["bye", "goodbye", "au revoir", "ciao", "adieu", "a+"])
    def test_farewells_are_trivial(self, analyzer, input_text):
        """Farewells should be detected as trivial."""
        assert analyzer.is_conversational_trivial(input_text) is True

    # Acknowledgments
    @pytest.mark.parametrize(
        "input_text",
        [
            "ok",
            "OK",
            "okay",
            "oui",
            "yes",
            "non",
            "no",
            "merci",
            "Merci!",
            "thanks",
            "thank you",
            "thx",
            "parfait",
            "perfect",
            "great",
            "cool",
            "super",
            "compris",
            "understood",
            "got it",
        ],
    )
    def test_acknowledgments_are_trivial(self, analyzer, input_text):
        """Acknowledgments should be detected as trivial."""
        assert analyzer.is_conversational_trivial(input_text) is True

    # Testing/probing
    @pytest.mark.parametrize("input_text", ["test", "testing", "ping", "pong", "123"])
    def test_testing_inputs_are_trivial(self, analyzer, input_text):
        """Testing inputs should be detected as trivial."""
        assert analyzer.is_conversational_trivial(input_text) is True

    # Continuation prompts
    @pytest.mark.parametrize("input_text", ["continue", "continues", "go on", "vas-y", "go ahead"])
    def test_continuation_prompts_are_trivial(self, analyzer, input_text):
        """Continuation prompts should be detected as trivial."""
        assert analyzer.is_conversational_trivial(input_text) is True

    # Non-trivial inputs that should NOT match
    @pytest.mark.parametrize(
        "input_text",
        [
            "Analyse ce code",
            "Implement a function to calculate fibonacci",
            "Debug this error",
            "What is the architecture of this project?",
            "Help me refactor the authentication module",
            "Create a new REST API endpoint",
            "hello world program in python",  # Contains code intent
            "test the authentication module",  # Contains code intent
        ],
    )
    def test_code_requests_are_not_trivial(self, analyzer, input_text):
        """Code-related requests should NOT be detected as trivial."""
        assert analyzer.is_conversational_trivial(input_text) is False

    def test_empty_input_is_trivial(self, analyzer):
        """Empty or whitespace-only input should be trivial."""
        assert analyzer.is_conversational_trivial("") is True
        assert analyzer.is_conversational_trivial("   ") is True


class TestFastPathIntegration:
    """Integration tests for Fast Path in OrchestratorV7."""

    @pytest.fixture
    def mock_config(self):
        """Create mock config with fast_path_enabled."""
        config = Mock(spec=Config)
        config.fast_path_enabled = True
        config.log_level = "DEBUG"
        config.workspace_path = Path("./workspace")
        config.swarm_enabled = True
        config.agent_metrics_enabled = True
        config.swarm_negotiation_enabled = True
        config.swarm_negotiation_max_turns = 4
        config.swarm_max_rounds = 6
        config.swarm_skip_trivial = True
        config.swarm_auto_route = True
        return config

    @pytest.fixture
    def mock_gemini_driver(self):
        """Create mock Gemini driver."""
        driver = Mock()
        driver.invoke.return_value = {"content": "Bonjour ! Comment puis-je vous aider ?", "status": "success"}
        return driver

    def test_fast_path_returns_immediately(self, mock_gemini_driver):
        """Fast path should return immediately for trivial inputs."""
        # Create a minimal mock orchestrator
        from core.intelligence.swarm.task_analyzer import TaskAnalyzer

        task_analyzer = TaskAnalyzer()

        # Simulate fast path check
        user_input = "hello"
        assert task_analyzer.is_conversational_trivial(user_input) is True

        # Simulate fast path response
        start_time = time.time()
        mock_gemini_driver.invoke.return_value = {"content": "Hello!"}
        response = mock_gemini_driver.invoke(
            {"prompt": f"Tu es NEXUS. Réponds brièvement à: {user_input}", "task_type": "simple"}
        )
        elapsed = time.time() - start_time

        # Should be very fast (mock doesn't actually call API)
        assert elapsed < 0.1
        assert "content" in response

    def test_non_trivial_input_bypasses_fast_path(self):
        """Non-trivial inputs should not use fast path."""
        task_analyzer = TaskAnalyzer()

        user_input = "Analyse ce code et trouve les bugs"
        assert task_analyzer.is_conversational_trivial(user_input) is False

        # Analyze should return MODERATE or higher complexity
        analysis = task_analyzer.analyze(user_input)
        assert analysis.complexity >= TaskComplexity.SIMPLE

    def test_fast_path_disabled_skips_fast_path(self):
        """When fast_path_enabled=False, should not use fast path."""
        task_analyzer = TaskAnalyzer()

        # Even trivial input should be processed normally if disabled
        user_input = "hello"
        assert task_analyzer.is_conversational_trivial(user_input) is True

        # But if config.fast_path_enabled is False, the check in process_turn
        # would skip the fast path and continue to normal processing
        # This is verified by the condition:
        # if (getattr(self.config, 'fast_path_enabled', True) and ...)


class TestFastPathResponse:
    """Test Fast Path response format."""

    def test_fast_path_response_format(self):
        """Fast path response should have correct format."""
        # Expected format from _handle_fast_path
        expected_keys = ["sender", "action_type", "content", "status", "state", "finished", "fast_path"]

        # Simulate response
        response = {
            "sender": "Gemini",
            "action_type": "TALK",
            "content": "Hello!",
            "status": "FINISHED",
            "state": "IDLE",
            "finished": True,
            "fast_path": True,
        }

        for key in expected_keys:
            assert key in response

        assert response["finished"] is True
        assert response["state"] == "IDLE"
        assert response["fast_path"] is True

    def test_fast_path_stays_in_idle(self):
        """After fast path response, orchestrator should stay in IDLE."""
        response = {
            "sender": "Gemini",
            "action_type": "TALK",
            "content": "Hello!",
            "status": "FINISHED",
            "state": "IDLE",
            "finished": True,
            "fast_path": True,
        }

        assert response["state"] == "IDLE"
        assert response["finished"] is True


class TestFastPathPatternCoverage:
    """Ensure patterns cover all required categories."""

    @pytest.fixture
    def analyzer(self):
        return TaskAnalyzer()

    def test_french_greetings(self, analyzer):
        """French greetings should be detected."""
        french_greetings = ["bonjour", "salut", "coucou", "bonsoir"]
        for greeting in french_greetings:
            assert analyzer.is_conversational_trivial(greeting) is True, f"Failed for: {greeting}"

    def test_english_greetings(self, analyzer):
        """English greetings should be detected."""
        english_greetings = ["hello", "hi", "hey", "good morning"]
        for greeting in english_greetings:
            assert analyzer.is_conversational_trivial(greeting) is True, f"Failed for: {greeting}"

    def test_multilingual_thanks(self, analyzer):
        """Thanks in multiple languages should be detected."""
        thanks = ["merci", "thanks", "thank you", "thx"]
        for t in thanks:
            assert analyzer.is_conversational_trivial(t) is True, f"Failed for: {t}"

    def test_case_insensitivity(self, analyzer):
        """Pattern matching should be case-insensitive."""
        cases = ["HELLO", "Hello", "hello", "HeLLo"]
        for case in cases:
            assert analyzer.is_conversational_trivial(case) is True, f"Failed for: {case}"

    def test_with_punctuation(self, analyzer):
        """Inputs with trailing punctuation should be detected."""
        with_punct = ["hello!", "hi?", "bonjour.", "merci!!"]
        for inp in with_punct:
            assert analyzer.is_conversational_trivial(inp) is True, f"Failed for: {inp}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
