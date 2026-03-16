"""
ValidationService - Path and Security Validation for Tool Execution.

NEXUS V9.5 Refactoring - Sprint 2

Extracted from tool_manager.py (God Class decomposition).
Handles:
- Path validation (evolution mode)
- Security checks (PathGuardian integration)
- ExecutionPolicy validation

Usage:
    validator = ValidationService(workspace_path)

    if validator.is_evolution_safe_read(path):
        # Safe to read during evolution

    if validator.validate_path(path, operation="write"):
        # Safe to write
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from core.security_pkg.security import PathGuardian
from core.security_pkg.security.execution_policy import ExecutionPolicy

logger = logging.getLogger(__name__)

OperationType = Literal["read", "write", "edit", "list", "execute"]


class ValidationService:
    """
    Centralized validation for tool execution.

    Security layers:
    1. ExecutionPolicy - Command-level validation
    2. PathGuardian - Path-level validation
    3. Evolution safety - Context-aware permissions
    """

    def __init__(
        self,
        workspace_path: Path,
        parent_path: Path | None = None,
        generation_active: Path | None = None,
    ):
        """
        Initialize validation service.

        Args:
            workspace_path: Current workspace root
            parent_path: Parent project path (for evolution reads)
            generation_active: GENERATION_ACTIVE path (for evolution writes)
        """
        self.workspace_path = Path(workspace_path)
        self.parent_path = parent_path or self.workspace_path.parent
        self.generation_active = generation_active or self.parent_path.parent / "GENERATION_ACTIVE"

        # Initialize security layers
        self.path_guardian = PathGuardian(
            workspace_path=self.workspace_path, parent_path=self.parent_path, generation_active=self.generation_active
        )
        self.execution_policy = ExecutionPolicy(self.workspace_path)

        # Evolution mode flag (controlled externally)
        self.evolution_mode = False

        # Forbidden patterns (universal)
        self._forbidden_patterns = [
            "NEXUS_V5_PRAGMATIC",
            "__pycache__",
            ".git",
            ".pyc",
        ]

        # Allowed prefixes for evolution reads
        self._evolution_read_prefixes = [
            "core/",
            "prompts/",
            "benchmarks/",
        ]

        # Allowed root files for evolution reads
        # V9 SECURITY: .env REMOVED - credentials must not be readable
        self._evolution_root_files = [
            "README.md",
            "nexus6.py",
            "LINEAGE.json",
        ]

        # Allowed directories for evolution list
        self._evolution_list_prefixes = [
            "core",
            "prompts",
            "benchmarks",
        ]

    def is_evolution_safe_read(self, path: Path) -> bool:
        """
        Check if path is allowed for evolution READ operations.

        Whitelist:
        - ../core/**/*.py (parent project code)
        - ../prompts/**/*.md (parent prompts)
        - ../benchmarks/** (benchmark scripts)
        - ../README.md, ../nexus6.py, ../LINEAGE.json

        Forbidden:
        - NEXUS_V5_PRAGMATIC
        - .env, .git, __pycache__

        Args:
            path: Path to validate

        Returns:
            True if safe to read during evolution
        """
        try:
            relative = path.relative_to(self.parent_path)
            path_str = str(relative).replace("\\", "/")

            # Check forbidden first
            if any(forb in path_str for forb in self._forbidden_patterns):
                return False

            # Check allowed prefixes
            if any(path_str.startswith(prefix) for prefix in self._evolution_read_prefixes):
                return True

            # Check allowed root files
            return path_str in self._evolution_root_files

        except ValueError:
            return False

    def is_evolution_safe_list(self, path: Path) -> bool:
        """
        Check if path is allowed for evolution LIST operations.

        Whitelist:
        - ../core/ (parent project code)
        - ../prompts/ (parent prompts)
        - ../benchmarks/ (benchmark scripts)

        Args:
            path: Path to validate

        Returns:
            True if safe to list during evolution
        """
        try:
            relative = path.relative_to(self.parent_path)
            path_str = str(relative).replace("\\", "/")

            # Check forbidden first
            if any(forb in path_str for forb in self._forbidden_patterns):
                return False

            # Check allowed prefixes (directory listing)
            return bool(
                any(path_str.startswith(prefix) or path_str == prefix for prefix in self._evolution_list_prefixes)
            )

        except ValueError:
            return False

    def is_evolution_safe_write(self, path: Path) -> bool:
        """
        Check if path is allowed for evolution WRITE/EDIT operations.

        Whitelist:
        - ../../GENERATION_ACTIVE/** (children only)

        Everything else is FORBIDDEN (including parent project).

        Args:
            path: Path to validate

        Returns:
            True if safe to write during evolution
        """
        try:
            path.relative_to(self.generation_active)
            return True
        except ValueError:
            return False

    def validate_path(
        self,
        path: Path,
        operation: OperationType,
        *,
        allow_parent_read: bool = False,
    ) -> bool:
        """
        Unified path validation for any operation.

        Args:
            path: Path to validate
            operation: Type of operation ("read", "write", "edit", "list", "execute")
            allow_parent_read: Allow reading from parent (evolution mode)

        Returns:
            True if path is valid for the operation
        """
        path = Path(path).resolve()

        # Handle evolution mode
        if self.evolution_mode or allow_parent_read:
            if operation == "read":
                if self.is_evolution_safe_read(path):
                    return True
            elif operation == "list":
                if self.is_evolution_safe_list(path):
                    return True
            elif operation in ("write", "edit") and self.is_evolution_safe_write(path):
                return True

        # Standard validation via PathGuardian
        try:
            if operation in ("read", "list"):
                return self.path_guardian.validate_read(path)
            elif operation in ("write", "edit"):
                return self.path_guardian.validate_write(path)
            else:
                return self.path_guardian.validate_read(path)
        except Exception as e:
            logger.warning(f"Path validation failed for {path}: {e}")
            return False

    def validate_command(self, command: str) -> tuple[bool, str | None]:
        """
        Validate a shell command using ExecutionPolicy.

        Args:
            command: Shell command to validate

        Returns:
            Tuple of (is_allowed, error_message)
        """
        try:
            result = self.execution_policy.evaluate(command)
            if result.allowed:
                return True, None
            return False, result.reason
        except Exception as e:
            return False, str(e)

    def set_evolution_mode(self, enabled: bool) -> None:
        """Enable or disable evolution mode."""
        self.evolution_mode = enabled
        logger.debug(f"Evolution mode {'enabled' if enabled else 'disabled'}")
