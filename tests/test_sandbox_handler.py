"""
Tests for V12.4 Sandboxed Code Execution.

Validates:
- SandboxHandler builds correct Docker commands
- Security constraints are enforced (no network, read-only, memory limit)
- Handles missing Docker gracefully
- BashHandler delegates to sandbox when feature flag is on
- Fallback to host execution when Docker unavailable
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from core.execution_pkg.execution.handlers.sandbox_handler import DEFAULT_SANDBOX_IMAGE, SandboxHandler


@pytest.fixture
def sandbox(tmp_path):
    """Create a sandbox handler for testing."""
    return SandboxHandler(
        workspace_path=tmp_path,
        memory_limit="128m",
        cpu_limit=0.5,
        timeout=30.0,
    )


class TestSandboxHandlerConstruction:
    """Test SandboxHandler initialization."""

    def test_default_image(self, tmp_path):
        """Should use Python 3.13 slim as default image."""
        handler = SandboxHandler(tmp_path)
        assert handler._image == DEFAULT_SANDBOX_IMAGE

    def test_custom_image(self, tmp_path):
        """Should accept custom Docker image."""
        handler = SandboxHandler(tmp_path, image="alpine:latest")
        assert handler._image == "alpine:latest"

    def test_tool_name(self, sandbox):
        """Tool name should be 'sandbox'."""
        assert sandbox.tool_name == "sandbox"


class TestDockerCommandBuilder:
    """Test the Docker command construction."""

    def test_has_rm_flag(self, sandbox):
        """Container should be ephemeral."""
        cmd = sandbox._build_docker_command("echo hello")
        assert "--rm" in cmd

    def test_has_no_network(self, sandbox):
        """Container should have no network access."""
        cmd = sandbox._build_docker_command("echo hello")
        assert "--network=none" in cmd

    def test_has_read_only(self, sandbox):
        """Container root should be read-only."""
        cmd = sandbox._build_docker_command("echo hello")
        assert "--read-only" in cmd

    def test_has_memory_limit(self, sandbox):
        """Container should have memory cap."""
        cmd = sandbox._build_docker_command("echo hello")
        assert "--memory=128m" in cmd

    def test_has_cpu_limit(self, sandbox):
        """Container should have CPU cap."""
        cmd = sandbox._build_docker_command("echo hello")
        assert "--cpus=0.5" in cmd

    def test_has_no_new_privileges(self, sandbox):
        """Container should prevent privilege escalation."""
        cmd = sandbox._build_docker_command("echo hello")
        assert "--security-opt=no-new-privileges" in cmd

    def test_has_pids_limit(self, sandbox):
        """Container should limit process count."""
        cmd = sandbox._build_docker_command("echo hello")
        assert "--pids-limit=128" in cmd

    def test_has_tmpfs(self, sandbox):
        """Container should have writable /tmp."""
        cmd = sandbox._build_docker_command("echo hello")
        tmpfs_args = [arg for arg in cmd if "/tmp" in arg]
        assert len(tmpfs_args) > 0

    def test_workspace_mounted_readonly(self, sandbox):
        """Workspace should be mounted as read-only."""
        cmd = sandbox._build_docker_command("echo hello")
        # Find the -v argument
        for i, arg in enumerate(cmd):
            if arg == "-v" and i + 1 < len(cmd):
                volume_mount = cmd[i + 1]
                assert volume_mount.endswith(":ro")
                assert "/workspace" in volume_mount
                break
        else:
            pytest.fail("No volume mount found")

    def test_command_passed_to_shell(self, sandbox):
        """Command should be passed via /bin/sh -c."""
        cmd = sandbox._build_docker_command("python -c 'print(42)'")
        assert "/bin/sh" in cmd
        assert "-c" in cmd
        assert "python -c 'print(42)'" in cmd

    def test_image_in_command(self, sandbox):
        """Docker image should be in the command."""
        cmd = sandbox._build_docker_command("echo hello")
        assert DEFAULT_SANDBOX_IMAGE in cmd


class TestSandboxExecution:
    """Test execution behavior."""

    def test_empty_command_rejected(self, sandbox):
        """Empty commands should be rejected."""
        result = sandbox.execute({"command": ""})
        assert result.status == "ERROR"

    @patch("shutil.which", return_value=None)
    def test_docker_not_available(self, mock_which, sandbox):
        """Should error when Docker is not available."""
        sandbox._docker_available = None  # Reset cache
        result = sandbox.execute({"command": "echo hello"})
        assert result.status == "ERROR"
        assert "Docker" in result.error

    @patch("subprocess.run")
    def test_successful_execution(self, mock_run, sandbox):
        """Should return SUCCESS for zero exit code."""
        sandbox._docker_available = True
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="hello\n",
            stderr="",
        )
        result = sandbox.execute({"command": "echo hello"})
        assert result.status == "SUCCESS"
        assert result.output == "hello\n"

    @patch("subprocess.run")
    def test_failed_execution(self, mock_run, sandbox):
        """Should return FAILURE for non-zero exit code."""
        sandbox._docker_available = True
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="error occurred",
        )
        result = sandbox.execute({"command": "false"})
        assert result.status == "FAILURE"

    @patch("subprocess.run")
    def test_oom_killed(self, mock_run, sandbox):
        """Should detect OOM-killed containers (exit 137)."""
        sandbox._docker_available = True
        mock_run.return_value = MagicMock(
            returncode=137,
            stdout="",
            stderr="",
        )
        result = sandbox.execute({"command": "stress --vm 1"})
        assert result.status == "KILLED"
        assert "OOM" in result.error

    @patch("subprocess.run", side_effect=FileNotFoundError)
    def test_docker_not_found(self, mock_run, sandbox):
        """Should handle missing Docker binary."""
        sandbox._docker_available = True
        result = sandbox.execute({"command": "echo hello"})
        assert result.status == "ERROR"
        assert "not found" in result.error


class TestSandboxPythonExecution:
    """Test execute_python convenience method."""

    @patch("subprocess.run")
    def test_execute_python(self, mock_run, sandbox):
        """execute_python should wrap code in python -c."""
        sandbox._docker_available = True
        mock_run.return_value = MagicMock(returncode=0, stdout="42\n", stderr="")
        result = sandbox.execute_python("print(42)")
        assert result.status == "SUCCESS"
        # Verify python -c was used
        call_args = mock_run.call_args[0][0]
        assert "python -c" in " ".join(call_args)


class TestBashHandlerSandboxDelegation:
    """Test BashHandler delegating to sandbox."""

    def test_bash_handler_without_sandbox(self, tmp_path):
        """Disabling sandbox keeps the handler in validated host mode."""
        from core.execution_pkg.execution.handlers.bash_handler import BashHandler

        with patch.dict(os.environ, {"NEXUS_FF_SANDBOX_ENABLED": "false"}):
            handler = BashHandler(tmp_path)
            assert handler._sandbox is None
            assert handler.effective_mode() == "validated_host"

    def test_bash_handler_blocks_host_execution_when_not_opted_in(self, tmp_path):
        """Validated host execution is deny-by-default when no sandbox is available."""
        from core.execution_pkg.execution.handlers.bash_handler import BashHandler

        with patch.dict(
            os.environ,
            {"NEXUS_FF_SANDBOX_ENABLED": "false", "NEXUS_FF_HOST_EXECUTION_ALLOWED": "false"},
        ):
            handler = BashHandler(tmp_path)
            result = handler.execute({"command": "echo hello"})

        assert result.status == "BLOCKED"
        assert "Validated host execution is disabled" in result.error

    @patch("shutil.which", return_value="/usr/bin/docker")
    @patch("subprocess.run")
    def test_bash_handler_with_sandbox_flag(self, mock_run, mock_which, tmp_path):
        """BashHandler should create sandbox when flag is on and Docker available."""
        mock_run.return_value = MagicMock(returncode=0)
        from core.execution_pkg.execution.handlers.bash_handler import BashHandler

        with patch.dict(os.environ, {"NEXUS_FF_SANDBOX_ENABLED": "true"}):
            handler = BashHandler(tmp_path)
            assert handler._sandbox is not None
            assert handler.effective_mode() == "sandboxed"
