"""
NEXUS V12.4 COGNITIVE BOOST - Sandboxed Code Execution

Executes AI-generated code inside isolated Docker containers instead
of directly on the host OS. Critical security boundary for production.

Architecture:
    User/Agent Request
        -> BashHandler (validates command)
        -> SandboxHandler (if NEXUS_FF_SANDBOX_ENABLED=true)
        -> Docker container (ephemeral, no network, read-only root)
        -> Result returned to agent

Security Properties:
    1. Network isolation (--network=none)
    2. Read-only filesystem (--read-only)
    3. No privilege escalation (--security-opt=no-new-privileges)
    4. Memory limit (default 256MB)
    5. CPU limit (default 1 core)
    6. Timeout enforcement (default 60s)
    7. Workspace mounted as read-only /workspace

Feature Flag: NEXUS_FF_SANDBOX_ENABLED (default: false)

Usage:
    from core.execution_pkg.execution.handlers.sandbox_handler import SandboxHandler

    handler = SandboxHandler(workspace_path)
    result = handler.execute({"command": "python -c 'print(1+1)'"})

Requirements:
    Docker must be installed and accessible to the nexus user.

Author: Claude (NEXUS V12.4 COGNITIVE BOOST)
Date: 2026-02-15
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .base import BaseHandler, ToolResult

logger = logging.getLogger(__name__)

# Default sandbox image (slim Python with common tools)
DEFAULT_SANDBOX_IMAGE = "python:3.13-slim"


class SandboxHandler(BaseHandler):
    """
    Sandboxed code execution via Docker containers.

    Each command runs in an ephemeral container with:
    - No network access
    - Read-only filesystem (except /tmp)
    - Limited memory and CPU
    - Workspace mounted read-only at /workspace
    """

    def __init__(
        self,
        workspace_path: Path,
        validation_service: Any | None = None,
        image: str = DEFAULT_SANDBOX_IMAGE,
        memory_limit: str = "256m",
        cpu_limit: float = 1.0,
        timeout: float = 60.0,
    ):
        """
        Initialize sandbox handler.

        Args:
            workspace_path: Host workspace path (mounted read-only)
            validation_service: Optional validation service
            image: Docker image to use
            memory_limit: Container memory limit (e.g., "256m", "1g")
            cpu_limit: CPU cores limit (e.g., 1.0)
            timeout: Command timeout in seconds
        """
        super().__init__(workspace_path, validation_service)
        self._image = image
        self._memory_limit = memory_limit
        self._cpu_limit = cpu_limit
        self._timeout = timeout
        self._docker_available: bool | None = None

    @property
    def tool_name(self) -> str:
        return "sandbox"

    def is_available(self) -> bool:
        """Check if Docker is available on the system."""
        if self._docker_available is not None:
            return self._docker_available

        self._docker_available = shutil.which("docker") is not None
        if self._docker_available:
            try:
                result = subprocess.run(
                    ["docker", "info"],
                    capture_output=True,
                    timeout=10,
                )
                self._docker_available = result.returncode == 0
            except (subprocess.TimeoutExpired, FileNotFoundError):
                self._docker_available = False

        return self._docker_available

    def execute(self, args: dict[str, Any]) -> ToolResult:
        """
        Execute command inside a sandboxed Docker container.

        Args:
            args: {"command": str, "language": optional str}

        Returns:
            ToolResult with sandboxed output
        """
        command = args.get("command", "")

        if not command or not command.strip():
            return self._error("Empty command")

        if not self.is_available():
            return ToolResult(
                tool_name=self.tool_name,
                status="ERROR",
                output="",
                error="Docker is not available. Install Docker or disable sandbox mode.",
            )

        # Build docker run command
        docker_cmd = self._build_docker_command(command)

        try:
            result = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=self._timeout + 5,  # Extra buffer for Docker overhead
            )

            if result.returncode == 0:
                return ToolResult(
                    tool_name=self.tool_name,
                    status="SUCCESS",
                    output=result.stdout,
                    error=result.stderr,
                )
            elif result.returncode == 137:
                return ToolResult(
                    tool_name=self.tool_name,
                    status="KILLED",
                    output=result.stdout,
                    error="Container killed (OOM or timeout)",
                )
            else:
                return ToolResult(
                    tool_name=self.tool_name,
                    status="FAILURE",
                    output=result.stdout,
                    error=result.stderr,
                )

        except subprocess.TimeoutExpired:
            return self._error(f"Sandbox execution timed out ({self._timeout}s)")
        except FileNotFoundError:
            return self._error("Docker not found in PATH")
        except Exception as e:
            return self._error(f"Sandbox error: {e}")

    def _build_docker_command(self, command: str) -> list[str]:
        """
        Build the docker run command with security constraints.

        Args:
            command: Shell command to execute inside container

        Returns:
            List of command arguments for subprocess
        """
        docker_args = [
            "docker",
            "run",
            "--rm",  # Ephemeral (auto-cleanup)
            "--network=none",  # No network access
            "--read-only",  # Read-only root filesystem
            "--tmpfs=/tmp:rw,noexec,nosuid,size=64m",  # Writable /tmp (limited)
            f"--memory={self._memory_limit}",  # Memory cap
            f"--cpus={self._cpu_limit}",  # CPU cap
            "--security-opt=no-new-privileges",  # No privilege escalation
            "--pids-limit=128",  # Process count limit
            f"--stop-timeout={int(self._timeout)}",  # Graceful stop timeout
        ]

        # Mount workspace as read-only
        workspace_str = str(self.workspace_path.resolve())
        docker_args.extend(
            [
                "-v",
                f"{workspace_str}:/workspace:ro",
                "-w",
                "/workspace",
            ]
        )

        # Set the image and command
        docker_args.extend(
            [
                self._image,
                "/bin/sh",
                "-c",
                command,
            ]
        )

        return docker_args

    def execute_python(self, code: str) -> ToolResult:
        """
        Execute Python code in sandbox.

        Convenience method that wraps code in python -c.

        Args:
            code: Python code string

        Returns:
            ToolResult with execution output
        """
        # Escape single quotes in code for shell
        escaped = code.replace("'", "'\\''")
        return self.execute({"command": f"python -c '{escaped}'"})
