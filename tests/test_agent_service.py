"""
Tests for AgentService (V9.1 Service Layer)

These tests verify the AgentService extracted from repl.py works correctly.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestAgentService:
    """Test AgentService functionality."""

    @pytest.fixture
    def mock_orchestrator(self):
        """Create a mock orchestrator."""
        orchestrator = MagicMock()
        orchestrator.telemetry = None
        orchestrator.config = MagicMock()
        orchestrator.config.redteam_spawn_enabled = False
        orchestrator.agent_pool = None
        return orchestrator

    @pytest.fixture
    def mock_console(self):
        """Create a mock console."""
        console = MagicMock()
        console.print = MagicMock()
        console.print_error = MagicMock()
        return console

    @pytest.fixture
    def temp_workspace(self):
        """Create a temporary workspace directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            yield workspace

    @pytest.fixture
    def agent_service(self, mock_orchestrator, temp_workspace, mock_console):
        """Create an AgentService instance."""
        from core.foundation.agents.service import AgentService

        return AgentService(orchestrator=mock_orchestrator, workspace_path=temp_workspace, console=mock_console)

    def test_detect_domains_python(self, agent_service):
        """Test domain detection for Python role."""
        domains = agent_service._detect_domains_from_role("Python Expert")
        assert "coding" in domains

    def test_detect_domains_sql(self, agent_service):
        """Test domain detection for SQL role."""
        domains = agent_service._detect_domains_from_role("SQL Database Analyst")
        assert "data" in domains

    def test_detect_domains_devops(self, agent_service):
        """Test domain detection for DevOps role."""
        domains = agent_service._detect_domains_from_role("Kubernetes DevOps Engineer")
        assert "devops" in domains

    def test_detect_domains_multiple(self, agent_service):
        """Test detection of multiple domains."""
        domains = agent_service._detect_domains_from_role("Python ML Security Expert")
        assert "coding" in domains
        assert "ml" in domains
        assert "security" in domains

    def test_detect_domains_empty(self, agent_service):
        """Test domain detection returns empty for unknown role."""
        domains = agent_service._detect_domains_from_role("Random Expert")
        assert domains == []

    def test_validate_prompt_tools_valid(self, agent_service):
        """Test validation passes for valid tools."""
        prompt = "Use `read` and `write` and `bash` for file operations."
        hallucinated = agent_service._validate_prompt_tools(prompt)
        assert hallucinated == []

    def test_validate_prompt_tools_hallucinated(self, agent_service):
        """Test validation detects hallucinated tools."""
        prompt = "Use `execute_code` and `run_python` to execute scripts."
        hallucinated = agent_service._validate_prompt_tools(prompt)
        assert "execute_code" in hallucinated
        assert "run_python" in hallucinated

    def test_validate_prompt_tools_mcp_allowed(self, agent_service):
        """Test MCP tools are allowed."""
        prompt = "Use `mcp_github` and `mcp_slack` for integrations."
        hallucinated = agent_service._validate_prompt_tools(prompt)
        assert hallucinated == []

    def test_validate_prompt_tools_agent_allowed(self, agent_service):
        """Test agent_ tools are allowed."""
        prompt = "Use `agent_sql_expert` for database queries."
        hallucinated = agent_service._validate_prompt_tools(prompt)
        assert hallucinated == []

    def test_static_template_includes_role(self, agent_service):
        """Test static template includes role."""
        template = agent_service._static_agent_template("SQL Expert", "uuid-1234", ["data"])
        assert "SQL Expert" in template
        assert "uuid-1234" in template
        assert "data" in template

    def test_static_template_markdown_format(self, agent_service):
        """Test static template is valid markdown."""
        template = agent_service._static_agent_template("Test Agent", "uuid-5678", [])
        assert template.startswith("# Test Agent")
        assert "## Identity" in template
        assert "## Mission" in template

    def test_list_agents_empty(self, agent_service, temp_workspace, mock_console):
        """Test listing agents when none exist."""
        agents = agent_service.list_agents()
        assert agents == []
        mock_console.print.assert_any_call("\nNo agents spawned yet.")

    def test_list_agents_with_agents(self, agent_service, temp_workspace, mock_console):
        """Test listing agents when some exist."""
        # Create a mock agent
        agents_dir = temp_workspace / "agents"
        agents_dir.mkdir()
        agent_dir = agents_dir / "test_agent"
        agent_dir.mkdir()

        cert = {
            "agent_id": "test_agent",
            "role": "Test Agent",
            "created_at": "2025-01-01T00:00:00",
            "uuid": "test-uuid-1234",
        }
        (agent_dir / "BIRTH_CERTIFICATE.json").write_text(json.dumps(cert))

        agents = agent_service.list_agents()
        assert len(agents) == 1
        assert agents[0].agent_id == "test_agent"
        assert agents[0].role == "Test Agent"

    def test_get_pool_stats_disabled(self, agent_service, mock_orchestrator, mock_console):
        """Test pool stats when agent pool is disabled."""
        mock_orchestrator.agent_pool = None
        stats = agent_service.get_pool_stats()
        assert stats is None
        mock_console.print.assert_any_call("   Set AGENT_METRICS=True in .env to enable")

    def test_get_pool_stats_enabled(self, agent_service, mock_orchestrator, mock_console):
        """Test pool stats when agent pool is enabled."""
        mock_pool = MagicMock()
        mock_pool.get_pool_stats.return_value = {
            "agents": 2,
            "total_invocations": 10,
            "average_pool_importance": 0.5,
            "agents_detail": {},
        }
        mock_orchestrator.agent_pool = mock_pool

        stats = agent_service.get_pool_stats()
        assert stats is not None
        assert stats.total_agents == 2
        assert stats.total_invocations == 10

    def test_spawn_budget_exceeded(self, agent_service, mock_orchestrator, mock_console):
        """Test spawn fails when budget exceeded."""
        from core.observability.telemetry import BudgetExceededError

        mock_telemetry = MagicMock()
        mock_telemetry.enforce_budget.side_effect = BudgetExceededError(10.0, 5.0)
        mock_orchestrator.telemetry = mock_telemetry

        result = agent_service.spawn("Test Role")
        assert not result.success
        assert "Budget exceeded" in result.error

    def test_spawn_agent_exists(self, agent_service, temp_workspace, mock_console):
        """Test spawn fails when agent already exists."""
        # Create existing agent
        agents_dir = temp_workspace / "agents"
        agents_dir.mkdir()
        (agents_dir / "test_role").mkdir()

        result = agent_service.spawn("Test Role")
        assert not result.success
        assert "already exists" in result.error

    def test_spawn_agent_exists_force(self, agent_service, temp_workspace, mock_console):
        """Test spawn with force overwrites existing agent."""
        # Create existing agent
        agents_dir = temp_workspace / "agents"
        agents_dir.mkdir()
        (agents_dir / "test_role").mkdir()
        (agents_dir / "test_role" / "old_file.txt").write_text("old")

        # Mock brainstorm to return None (use static template)
        with patch.object(agent_service, "_brainstorm_agent_prompt", return_value=None):
            result = agent_service.spawn("Test Role", force=True)

        assert result.success
        assert result.agent_id == "test_role"
        # Old file should be gone
        assert not (agents_dir / "test_role" / "old_file.txt").exists()

    def test_create_agent_config(self, agent_service):
        """Test agent config creation."""
        config = agent_service._create_agent_config(
            role_slug="test_agent",
            agent_uuid="uuid-1234",
            role="Test Agent",
            domains=["coding"],
            inference_config={"provider": "claude", "model": "sonnet"},
            generated_prompt="# Test Prompt",
        )

        assert config["agent_id"] == "test_agent"
        assert config["uuid"] == "uuid-1234"
        assert config["role"] == "Test Agent"
        assert config["inference"]["provider"] == "claude"
        assert "coding" in config["specialization"]["domains"]

    def test_extract_inference_config_found(self, agent_service):
        """Test extracting inference config from prompt."""
        prompt = """
# Test Agent

## Inference Configuration
provider: gemini
model: gemini-2.0-flash
reasoning: Fast for simple tasks
"""
        with patch("core.foundation.agents.get_registry") as mock_registry:
            mock_registry.return_value.get.return_value = MagicMock()  # Provider exists
            config = agent_service._extract_inference_config(prompt)

        assert config is not None
        assert config["provider"] == "gemini"
        assert config["model"] == "gemini-2.0-flash"
        assert "Fast" in config["reasoning"]

    def test_extract_inference_config_not_found(self, agent_service):
        """Test extracting inference config when not present."""
        prompt = "# Test Agent\n\nNo inference section here."
        config = agent_service._extract_inference_config(prompt)
        assert config is None


class TestAgentServiceIntegration:
    """Integration tests for AgentService with commands."""

    def test_command_uses_service(self):
        """Test that AgentCommand uses AgentService."""
        from core.interface_pkg.interface.commands.agents import _get_agent_service
        from core.interface_pkg.interface.commands.registry import CommandContext

        mock_orchestrator = MagicMock()
        mock_console = MagicMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            context = CommandContext(
                orchestrator=mock_orchestrator, console=mock_console, config={}, extras={"workspace_path": Path(tmpdir)}
            )

            service = _get_agent_service(context)
            from core.foundation.agents.service import AgentService

            assert isinstance(service, AgentService)
