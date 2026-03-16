"""
Tests for TaskRouter - P5.1 Phase 2 Extraction

Validates task routing logic extracted from OrchestratorV7.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.execution_pkg.orchestration.task_router import RouteDecision, RouteType, TaskRouter
from core.fsm.states import OrchestratorState


class TestRouteDecision:
    """Test RouteDecision dataclass."""

    def test_fast_path_property(self):
        """is_fast_path property should work correctly."""
        decision = RouteDecision(route_type=RouteType.FAST_PATH)
        assert decision.is_fast_path

        decision = RouteDecision(route_type=RouteType.MODERATE)
        assert not decision.is_fast_path

    def test_metadata_default(self):
        """Metadata should default to empty dict."""
        decision = RouteDecision(route_type=RouteType.SIMPLE)
        assert decision.metadata == {}


class TestTaskRouter:
    """Test TaskRouter routing logic."""

    @pytest.fixture
    def router(self):
        """Create TaskRouter instance."""
        return TaskRouter()

    def test_init(self, router):
        """__init__ should initialize patterns."""
        assert router._instant_patterns is not None
        assert router._trivial_patterns is not None

    # =========================================================================
    # is_fast_path() tests
    # =========================================================================

    def test_is_fast_path_greeting(self, router):
        """Greetings should be fast path."""
        assert router.is_fast_path("hello")
        assert router.is_fast_path("Hi!")
        assert router.is_fast_path("bonjour")

    def test_is_fast_path_farewell(self, router):
        """Farewells should be fast path."""
        assert router.is_fast_path("bye")
        assert router.is_fast_path("goodbye")
        assert router.is_fast_path("au revoir")

    def test_is_fast_path_acknowledgment(self, router):
        """Acknowledgments should be fast path."""
        assert router.is_fast_path("ok")
        assert router.is_fast_path("thanks")
        assert router.is_fast_path("merci")

    def test_is_fast_path_instant_command(self, router):
        """Instant commands should be fast path."""
        assert router.is_fast_path("/help")
        assert router.is_fast_path("/status")
        assert router.is_fast_path("help")

    def test_is_fast_path_test_ping(self, router):
        """Test/ping should be fast path."""
        assert router.is_fast_path("test")
        assert router.is_fast_path("ping")

    def test_is_fast_path_complex_query(self, router):
        """Complex queries should NOT be fast path."""
        assert not router.is_fast_path("implement user authentication")
        assert not router.is_fast_path("analyze this code for bugs")
        assert not router.is_fast_path("write a function to parse JSON")

    def test_is_fast_path_long_input(self, router):
        """Long inputs should NOT be fast path even with trivial words."""
        long_input = "hello, I need help implementing a complex authentication system with OAuth2"
        assert not router.is_fast_path(long_input)  # >50 chars

    def test_is_fast_path_none_input(self, router):
        """None input should return False."""
        assert not router.is_fast_path(None)

    def test_is_fast_path_empty_input(self, router):
        """Empty input should return False."""
        assert not router.is_fast_path("")

    # =========================================================================
    # handle_fast_path() tests
    # =========================================================================

    def test_handle_fast_path_greeting(self, router):
        """Greeting should return welcome message."""
        response = router.handle_fast_path("hello")
        assert "NEXUS" in response
        assert "help" in response.lower()

    def test_handle_fast_path_farewell(self, router):
        """Farewell should return goodbye message."""
        response = router.handle_fast_path("bye")
        assert "Goodbye" in response

    def test_handle_fast_path_acknowledgment(self, router):
        """Acknowledgment should return confirmation."""
        response = router.handle_fast_path("thanks")
        assert "welcome" in response.lower()

    def test_handle_fast_path_test(self, router):
        """Test/ping should return pong."""
        response = router.handle_fast_path("ping")
        assert "Pong" in response

    def test_handle_fast_path_command(self, router):
        """Commands should return acknowledgment."""
        response = router.handle_fast_path("help")
        assert "Command" in response or "Processing" in response

    def test_handle_fast_path_default(self, router):
        """Unknown fast path input should return default."""
        response = router.handle_fast_path("xyz")
        assert "assist" in response.lower()

    # =========================================================================
    # determine_route() tests
    # =========================================================================

    def test_determine_route_no_input(self, router):
        """No input should return ERROR route."""
        decision = router.determine_route(None, OrchestratorState.IDLE)
        assert decision.route_type == RouteType.ERROR

    def test_determine_route_fast_path(self, router):
        """Trivial input should return FAST_PATH route."""
        decision = router.determine_route("hello", OrchestratorState.IDLE)
        assert decision.route_type == RouteType.FAST_PATH
        assert decision.is_fast_path

    def test_determine_route_complex_task(self, router):
        """Complex task should return MODERATE route (pending analysis)."""
        decision = router.determine_route("implement authentication", OrchestratorState.IDLE)
        assert decision.route_type == RouteType.MODERATE
        assert not decision.is_fast_path

    def test_determine_route_metadata(self, router):
        """Route decision should include metadata."""
        decision = router.determine_route("hello", OrchestratorState.IDLE)
        assert "input_length" in decision.metadata
        assert decision.metadata["input_length"] == 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
