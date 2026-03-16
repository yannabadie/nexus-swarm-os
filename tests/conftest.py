"""
Pytest Configuration and Fixtures for NEXUS V12.4 Tests

Provides:
- MockDriver: Reusable mock for GeminiDriverV7 and ClaudeDriverHybrid
- orchestrator_with_mocks: OrchestratorV7 with mocked drivers (no API calls)
- orchestrator_with_swarm: OrchestratorV7 with swarm_enabled=True
- run_orchestrator_loop: Helper to run process_turn until completion
"""

import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import Config
from core.fsm.states import OrchestratorState
from core.version import NEXUS_CODENAME, NEXUS_VERSION


class MockDriver:
    """
    Mock driver for Gemini and Claude that returns predefined responses.

    Usage:
        driver = MockDriver("Gemini")
        driver.set_responses([
            {"sender": "Gemini", "action_type": "TALK", "content": "...", "status": "CONTINUE"},
            {"sender": "Gemini", "action_type": "FINISH", "content": "...", "status": "FINISHED"},
        ])
        response = driver.invoke("context")  # Returns first response, then second, etc.
    """

    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self._responses: list[dict] = []
        self._response_index = 0
        self.call_count = 0
        self.call_history: list[str] = []

    def set_responses(self, responses: list[dict]) -> None:
        """Set the list of responses to return on successive invoke() calls."""
        self._responses = responses
        self._response_index = 0

    def invoke(self, context: Any = None, **kwargs) -> dict:
        """Return the next predefined response."""
        self.call_count += 1
        if context:
            self.call_history.append(str(context)[:200])

        if not self._responses:
            # Default response if none set
            return {
                "sender": self.agent_name,
                "action_type": "TALK",
                "content": f"Mock response from {self.agent_name}",
                "status": "CONTINUE",
            }

        # Return current response and advance index (with wrap-around)
        response = self._responses[self._response_index]
        if self._response_index < len(self._responses) - 1:
            self._response_index += 1
        # Stay on last response if called more times than responses available

        return response.copy()

    def reset(self) -> None:
        """Reset call count and response index."""
        self.call_count = 0
        self._response_index = 0
        self.call_history = []


class MockConfig(Config):
    """Mock configuration for tests with sensible defaults."""

    def __init__(self, **overrides):
        # Don't call super().__init__() to avoid loading .env
        # Feature flags with safe test defaults
        from core.config import FeatureFlags

        self.features = FeatureFlags()
        self.features.sandbox_enabled = False
        self.features.host_execution_allowed = True

        # Set minimal required attributes
        self.nexus_version = NEXUS_VERSION
        self.nexus_codename = NEXUS_CODENAME
        self.gemini_cli_path = "gemini"
        self.claude_cli_path = "claude"
        self.max_stalemate_count = 5
        self.timeout = 600
        self.cfl_timeout = 60
        self.stagnation_similarity_threshold = 0.8
        self.compression_threshold_tokens = 100000
        self.workspace_path = Path(tempfile.mkdtemp())
        self.log_level = "WARNING"  # Quiet for tests
        self.ui_verbose = False
        self.console_output_limit = 5000

        # Evolution parameters
        self.max_children_concurrent = 5
        self.max_children_stable = 10
        self.stable_mode_threshold = 5
        self.fitness_metrics = {"coding": 0.30, "reasoning": 0.30, "creativity": 0.25, "scalability": 0.15}
        self.max_generations_per_day = 10
        self.min_hours_between_gen = 0.1
        self.min_hours_between_generations = 0.1
        self.max_children_per_generation = 5
        self.min_eval_hours = 24
        self.recommended_eval_hours = 48
        self.critical_review_hours = 72
        self.repl_turns_trigger = 50
        self.red_team_mandatory = False
        self.red_team_min_score = 0.60

        # Notifications
        self.email_enabled = False
        self.desktop_notifications = False
        self.webhook_url = None

        # Security
        self.gcp_children_blocked = True
        self.gcp_approval_required = True
        self.red_team_frequency = 1
        self.red_team_fail_threshold = 2

        # Auto-promotion
        self.auto_promotion_enabled = False
        self.auto_promote_improvement_pct = 3.0
        self.auto_promote_min_confidence = 0.95
        self.auto_promote_min_red_team_score = 0.90

        # Model routing
        self.driver_mode = "auto"
        self.anthropic_api_key = None
        self.google_api_key = None
        self.deepseek_api_key = None
        self.kimi_api_key = None
        self.openai_api_key = None
        self.minimax_api_key = None
        self.claude_opus_model = "claude-opus-4-1-20250805"
        self.claude_sonnet_model = "claude-sonnet-4-20250514"
        self.gemini_default_model = "gemini-3-pro-preview"
        self.gemini_pro_model = "gemini-3-pro-preview"
        self.gemini_flash_model = "gemini-3-flash-preview"
        self.deepseek_model = "deepseek-chat"
        self.kimi_model = "kimi-k2-thinking"
        self.openai_model = "gpt-5.4"
        self.openai_fast_model = "gpt-5-mini"
        self.minimax_model = "MiniMax-M2.5"
        self.minimax_fast_model = "MiniMax-M2.5-HighSpeed"
        self.opus_task_types = ["brainstorm", "redteam", "architect", "evolution"]
        self.sonnet_task_types = ["tool", "validation", "simple", "format"]
        self.gemini_pro_tasks = ["reasoning", "research", "analysis", "brainstorm", "evolution"]
        self.gemini_flash_tasks = ["simple", "format", "validation", "tool"]
        self.provider_snapshot = {"driver_mode": self.driver_mode, "warnings": [], "selected": {}}

        # Optimization
        self.benchmark_mode = "standard"
        self.validation_tier_default = 4
        self.validation_use_tiered = True
        self.parallel_benchmark_workers = 4
        self.benchmark_task_timeout = 60
        self.agent_metrics_enabled = True
        self.agent_metrics_window = 100

        # Swarm
        self.swarm_enabled = True
        self.swarm_negotiation_enabled = True
        self.swarm_negotiation_max_turns = 4
        self.swarm_default_mode = "ping_pong"
        self.swarm_skip_trivial = True
        self.swarm_max_rounds = 6
        self.swarm_auto_route = False  # Default for tests

        # Fast Path
        self.fast_path_enabled = True

        # V8.0 TRUE HIVE MIND
        self.hive_mind_enabled = True
        self.hive_mind_moderate = True
        self.hive_mind_budget_limit = 50000
        self.hive_mind_max_debate_turns = 10
        self.hive_mind_min_debate_turns = 3
        self.hive_mind_breakpoints_enabled = False  # Disabled for tests
        self.hive_mind_max_retries = 3
        self.hive_mind_agreement_threshold = 0.85

        # Gemini persistence (PTY removed in V7.6)
        self.gemini_persistent_mode = True
        self.gemini_approval_mode = "yolo"
        self.gemini_stream_json = True
        self.gemini_persistent_timeout = 300

        # Telemetry
        self.telemetry_enabled = False
        self.telemetry_file = str(self.workspace_path / "telemetry.jsonl")

        # Apply overrides
        for key, value in overrides.items():
            setattr(self, key, value)


@pytest.fixture
def mock_config():
    """Provide a mock configuration."""
    return MockConfig()


@pytest.fixture(autouse=True)
def default_test_execution_env(monkeypatch):
    """Keep test execution deterministic without requiring Docker sandboxing."""
    monkeypatch.setenv("NEXUS_FF_SANDBOX_ENABLED", "false")
    monkeypatch.setenv("NEXUS_FF_HOST_EXECUTION_ALLOWED", "true")


@pytest.fixture
def mock_gemini_driver():
    """Provide a mock Gemini driver."""
    return MockDriver("Gemini")


@pytest.fixture
def mock_claude_driver():
    """Provide a mock Claude driver."""
    return MockDriver("Claude")


@pytest.fixture
def orchestrator_with_mocks(tmp_path):
    """
    Create an OrchestratorV7 with mocked drivers.

    The orchestrator uses MockDriver instances instead of real API calls.
    Access drivers via: orch.drivers["Gemini"] and orch.drivers["Claude"]
    """
    from core.orchestration_v7 import OrchestratorV7

    # Create mock config
    config = MockConfig(
        workspace_path=tmp_path,
        swarm_auto_route=False,  # Use BRAINSTORMING by default
        swarm_enabled=True,
    )

    # Create workspace structure
    (tmp_path / ".nexus").mkdir(exist_ok=True)
    (tmp_path / "logs").mkdir(exist_ok=True)

    # Mock the drivers before creating orchestrator
    mock_gemini = MockDriver("Gemini")
    mock_claude = MockDriver("Claude")

    # V12.4: Drivers are created via AsyncDriverFactory, not imported directly
    with (
        patch("core.drivers.async_factory.AsyncDriverFactory.get_best_gemini") as mock_get_gemini,
        patch("core.execution_pkg.orchestration.agent_invoker.AgentInvoker.get_claude_driver") as mock_get_claude,
    ):
        mock_get_gemini.return_value = mock_gemini
        mock_get_claude.return_value = mock_claude

        # Create orchestrator with mocked drivers
        orch = OrchestratorV7(
            workspace_path=tmp_path,
            config=config,
            gemini_info={"name": "Gemini 3 Pro", "version": "mock"},
            claude_info={"name": "Claude Opus", "version": "mock"},
        )

    # Replace actual drivers with mocks
    orch.gemini_driver = mock_gemini

    # CRITICAL: Patch _get_claude_driver to return our mock
    # This is needed because _get_claude_driver() creates a NEW driver each time
    orch._get_claude_driver = lambda *args, **kwargs: mock_claude

    # V7.8 Phase 14c.2: Also patch agent_invoker.get_claude_driver since _get_claude_driver now delegates
    if hasattr(orch, "agent_invoker"):
        orch.agent_invoker.get_claude_driver = lambda *args, **kwargs: mock_claude

    # V12.4: Patch factory.get_driver for provider-agnostic dispatch
    _driver_map = {"gemini": mock_gemini, "claude": mock_claude}
    if hasattr(orch, "_driver_factory"):
        _original_get_driver = orch._driver_factory.get_driver

        def _mock_get_driver(agent_id, model=None, prefer_sdk=False):
            normalized = agent_id.lower()
            if normalized in _driver_map:
                return _driver_map[normalized]
            return _original_get_driver(agent_id, model=model, prefer_sdk=prefer_sdk)

        orch._driver_factory.get_driver = _mock_get_driver

    # Store drivers in a dict for easy access in tests
    # V8.4.0: Use lowercase normalized IDs (but keep titlecase aliases for backwards compat)
    orch.drivers = {
        "gemini": mock_gemini,
        "claude": mock_claude,
        "Gemini": mock_gemini,  # Alias for backwards compat
        "Claude": mock_claude,  # Alias for backwards compat
    }

    return orch


@pytest.fixture
def orchestrator_with_swarm(tmp_path):
    """
    Create an OrchestratorV7 with swarm_enabled=True and mocked drivers.
    """
    from core.orchestration_v7 import OrchestratorV7

    config = MockConfig(
        workspace_path=tmp_path,
        swarm_enabled=True,
        swarm_auto_route=True,  # Enable swarm routing
    )

    # Create workspace structure
    (tmp_path / ".nexus").mkdir(exist_ok=True)
    (tmp_path / "logs").mkdir(exist_ok=True)

    mock_gemini = MockDriver("Gemini")
    mock_claude = MockDriver("Claude")

    # V12.4: Drivers are created via AsyncDriverFactory, not imported directly
    with (
        patch("core.drivers.async_factory.AsyncDriverFactory.get_best_gemini") as mock_get_gemini,
        patch("core.execution_pkg.orchestration.agent_invoker.AgentInvoker.get_claude_driver") as mock_get_claude,
    ):
        mock_get_gemini.return_value = mock_gemini
        mock_get_claude.return_value = mock_claude

        orch = OrchestratorV7(
            workspace_path=tmp_path,
            config=config,
            gemini_info={"name": "Gemini 3 Pro", "version": "mock"},
            claude_info={"name": "Claude Opus", "version": "mock"},
        )

    orch.gemini_driver = mock_gemini

    # CRITICAL: Patch _get_claude_driver to return our mock (if method still exists)
    if hasattr(orch, "_get_claude_driver"):
        orch._get_claude_driver = lambda *args, **kwargs: mock_claude

    # V7.8 Phase 14c.2: Also patch agent_invoker.get_claude_driver since _get_claude_driver now delegates
    if hasattr(orch, "agent_invoker"):
        orch.agent_invoker.get_claude_driver = lambda *args, **kwargs: mock_claude

    # V12.4: Patch factory.get_driver for provider-agnostic dispatch
    _driver_map = {"gemini": mock_gemini, "claude": mock_claude}
    if hasattr(orch, "_driver_factory"):
        _original_get_driver = orch._driver_factory.get_driver

        def _mock_get_driver(agent_id, model=None, prefer_sdk=False):
            normalized = agent_id.lower()
            if normalized in _driver_map:
                return _driver_map[normalized]
            return _original_get_driver(agent_id, model=model, prefer_sdk=prefer_sdk)

        orch._driver_factory.get_driver = _mock_get_driver

    orch.drivers = {"Gemini": mock_gemini, "Claude": mock_claude}

    return orch


@pytest.fixture
def run_orchestrator_loop():
    """
    Provide a helper function to run the orchestrator until completion.

    Usage:
        result = run_orchestrator_loop(orch, "Do something", max_iterations=10)
        assert result["final_state"] == "IDLE"
    """

    def _run_loop(
        orchestrator,
        initial_input: str | None = None,
        max_iterations: int = 10,
        terminal_states: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Run process_turn in a loop until a terminal state or max iterations.

        Args:
            orchestrator: The OrchestratorV7 instance
            initial_input: Optional first user input (only used if state is IDLE)
            max_iterations: Maximum number of turns to run
            terminal_states: States that stop the loop (default: IDLE, WAITING_USER, ERROR, PANIC)

        Returns:
            Dict with final_state, iterations, outputs, and finished flag
        """
        if terminal_states is None:
            terminal_states = ["IDLE", "WAITING_USER", "ERROR", "PANIC"]

        outputs = []
        iterations = 0
        finished = False

        for i in range(max_iterations):
            iterations += 1

            # Only pass input on first turn if in IDLE
            if i == 0 and initial_input and orchestrator.state == OrchestratorState.IDLE:
                result = orchestrator.process_turn(initial_input)
            else:
                result = orchestrator.process_turn()

            outputs.append(result)

            # Check for terminal state
            current_state = result.get("state", str(orchestrator.state))
            if current_state in terminal_states:
                finished = True
                break

            # Also check orchestrator state directly
            if orchestrator.state.name in terminal_states:
                finished = True
                break

            # Check for finished flag
            if result.get("finished", False):
                finished = True
                break

        return {
            "final_state": orchestrator.state.name,
            "iterations": iterations,
            "outputs": outputs,
            "finished": finished,
        }

    return _run_loop


# =============================================================================
# Additional Utility Fixtures
# =============================================================================


@pytest.fixture
def temp_workspace(tmp_path):
    """Create a temporary workspace with proper structure."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".nexus").mkdir()
    (workspace / "logs").mkdir()
    (workspace / "agents").mkdir()
    return workspace


@pytest.fixture
def sample_task_analysis():
    """Provide a sample TaskAnalysis for tests."""
    from core.intelligence.swarm.task_analyzer import TaskAnalysis, TaskComplexity, TaskDomain

    return TaskAnalysis(
        complexity=TaskComplexity.MODERATE,
        domains=[TaskDomain.CODING, TaskDomain.DEBUGGING],
        primary_domain=TaskDomain.CODING,
        requires_web=False,
        requires_code_execution=True,
        requires_deep_reasoning=False,
        requires_iteration=False,
        gemini_fit_score=0.7,
        claude_fit_score=0.85,
        raw_input="Fix the bug in auth.py",
        confidence=0.8,
        detected_keywords=["fix", "bug"],
    )
