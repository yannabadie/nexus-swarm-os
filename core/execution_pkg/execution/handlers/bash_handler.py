"""
Bash Handler - Shell command execution with security hardening.

NEXUS V9.5 Refactoring - Sprint 2

Extracted from tool_manager.py for Single Responsibility.

Security Layers:
1. ExecutionPolicy validation (patterns, executables)
2. Command analysis (SIMPLE vs COMPLEX)
3. Prefer shell=False for simple commands
4. Strict validation for complex commands
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

from core.constants import TIMEOUTS
from core.security_pkg.security.execution_policy import CommandType, ExecutionPolicy

from .base import BaseHandler, ToolResult

logger = logging.getLogger(__name__)


class BashHandler(BaseHandler):
    """
    Handler for executing shell commands.

    Security: ExecutionPolicy validation required.
    """

    def __init__(
        self,
        workspace_path: Path,
        validation_service: Any | None = None,
        execution_policy: ExecutionPolicy | None = None,
        timeout: float = None,
    ):
        """
        Initialize bash handler.

        Args:
            workspace_path: Workspace root
            validation_service: Optional ValidationService
            execution_policy: Optional ExecutionPolicy (created if None)
            timeout: Command timeout in seconds
        """
        super().__init__(workspace_path, validation_service)
        self.execution_policy = execution_policy or ExecutionPolicy(workspace_path)
        self.timeout = timeout or TIMEOUTS.BASH_COMMAND

        # V12.4 PHASE 3: Sandbox delegation with production enforcement
        self._sandbox = None
        self._sandbox_required = False
        self._host_execution_allowed = False
        self._effective_mode = "validated_host"
        try:
            import os

            sandbox_enabled = os.getenv("NEXUS_FF_SANDBOX_ENABLED", "true").lower() in ("true", "1")
            self._sandbox_required = os.getenv("NEXUS_FF_SANDBOX_REQUIRED", "false").lower() in ("true", "1")
            self._host_execution_allowed = os.getenv("NEXUS_FF_HOST_EXECUTION_ALLOWED", "false").lower() in (
                "true",
                "1",
            )

            if sandbox_enabled or self._sandbox_required:
                from .sandbox_handler import SandboxHandler

                self._sandbox = SandboxHandler(workspace_path)
                if self._sandbox.is_available():
                    self._effective_mode = "sandboxed"
                    logger.info("BashHandler: sandbox mode ENABLED (Docker)")
                else:
                    if self._sandbox_required:
                        # CRITICAL: Production mode requires sandbox
                        raise RuntimeError(
                            "Sandbox is REQUIRED (NEXUS_FF_SANDBOX_REQUIRED=true) but Docker is not available. "
                            "Cannot execute commands without sandbox in production mode."
                        )
                    elif self._host_execution_allowed:
                        logger.warning(
                            "BashHandler: sandbox requested but Docker not available, falling back to validated host execution"
                        )
                        self._sandbox = None
                        self._effective_mode = "validated_host"
                    else:
                        logger.warning(
                            "BashHandler: sandbox requested but Docker not available, host execution blocked"
                        )
                        self._sandbox = None
        except Exception as e:
            if self._sandbox_required:
                raise  # Re-raise if sandbox is required
            logger.debug(f"Sandbox initialization failed (optional): {e}")

    def effective_mode(self) -> str:
        """Return the active execution mode exposed to callers and MCP docs."""
        return self._effective_mode

    @property
    def tool_name(self) -> str:
        return "bash"

    def execute(self, args: dict[str, Any]) -> ToolResult:
        """
        Execute shell command.

        Args:
            args: {"command": str}

        Returns:
            ToolResult with command output or error
        """
        command = args.get("command", "")

        if not command or not command.strip():
            return self._error("Empty command")

        # V12.4 PHASE 3: Enforce sandbox in production mode
        if self._sandbox_required and self._sandbox is None:
            return ToolResult(
                tool_name=self.tool_name,
                status="ERROR",
                content="",
                error="Sandbox execution required but sandbox not available. "
                "Set NEXUS_FF_SANDBOX_REQUIRED=false to allow host execution (development only).",
            )

        # V12.4: Delegate to sandbox if enabled
        if self._sandbox is not None:
            logger.debug(f"Sandbox executing: {command[:80]}...")
            return self._sandbox.execute(args)

        if not self._host_execution_allowed:
            return ToolResult(
                tool_name=self.tool_name,
                status="BLOCKED",
                output="",
                error=(
                    "Validated host execution is disabled. Enable NEXUS_FF_HOST_EXECUTION_ALLOWED=true "
                    "for local development or provide a Docker sandbox."
                ),
            )

        # SECURITY LAYER 1: ExecutionPolicy validation
        is_valid, error = self.execution_policy.validate_command(command)
        if not is_valid:
            return ToolResult(
                tool_name=self.tool_name, status="BLOCKED", output="", error=f"{error}. Command: {command[:80]}..."
            )

        # SECURITY LAYER 2: Analyze command for safe execution
        analysis = self.execution_policy.analyze_command(command)

        if analysis.command_type == CommandType.BLOCKED:
            return ToolResult(
                tool_name=self.tool_name,
                status="BLOCKED",
                output="",
                error=f"[SECURITY] {analysis.blocked_reason}. Command: {command[:80]}...",
            )

        try:
            if analysis.command_type == CommandType.SIMPLE:
                # SAFE: Use shell=False with parsed arguments
                result = self._execute_simple(analysis.executable, analysis.arguments)
            else:
                # COMPLEX: Requires shell=True but was validated
                result = self._execute_complex(command)

            if result.returncode == 0:
                return ToolResult(tool_name=self.tool_name, status="SUCCESS", output=result.stdout, error=result.stderr)
            else:
                return ToolResult(tool_name=self.tool_name, status="FAILURE", output=result.stdout, error=result.stderr)

        except FileNotFoundError:
            return self._error(f"Command not found: {analysis.executable}")
        except subprocess.TimeoutExpired:
            return self._error(f"Command timed out ({self.timeout}s)")
        except Exception as e:
            return self._error(str(e))

    def _execute_simple(self, executable: str, arguments: list[str]) -> subprocess.CompletedProcess:
        """
        Execute simple command with shell=False.

        Args:
            executable: Command to run
            arguments: Command arguments

        Returns:
            CompletedProcess result
        """
        exec_args = [executable] + arguments
        return subprocess.run(
            exec_args,
            shell=False,
            cwd=str(self.workspace_path),
            capture_output=True,
            text=True,
            timeout=self.timeout,
            encoding="utf-8",
            errors="replace",
        )

    def _execute_complex(self, command: str) -> subprocess.CompletedProcess:
        """
        Execute complex command with shell=True.

        Args:
            command: Full command string

        Returns:
            CompletedProcess result
        """
        return subprocess.run(
            command,
            shell=True,  # nosec B602  # intentional: bash_handler executes user shell commands by design
            cwd=str(self.workspace_path),
            capture_output=True,
            text=True,
            timeout=self.timeout,
            encoding="utf-8",
            errors="replace",
        )


# Factory function
def create_bash_handler(
    workspace_path: Path,
    validation_service: Any | None = None,
    execution_policy: ExecutionPolicy | None = None,
) -> BashHandler:
    """
    Create bash handler.

    Args:
        workspace_path: Workspace root
        validation_service: Optional ValidationService
        execution_policy: Optional ExecutionPolicy

    Returns:
        Configured BashHandler
    """
    return BashHandler(
        workspace_path,
        validation_service,
        execution_policy,
    )
