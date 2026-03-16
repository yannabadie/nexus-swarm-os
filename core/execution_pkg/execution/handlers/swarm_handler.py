"""
Swarm Handler - Delegate subtasks to Swarm Engine.

NEXUS V9.6 Sprint 5.2b - Extracted from tool_manager.py

Provides:
- SwarmDelegateHandler: Delegate tasks to Swarm collaboration modes
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .base import BaseHandler, ToolResult


class SwarmDelegateHandler(BaseHandler):
    """
    Handler for delegating subtasks to the Swarm Engine.

    V8.3.1 SwarmTool - Allows agents to invoke Swarm collaboration modes
    at any HiveMind phase, not just Phase 4 (Execution). Enables debates,
    parallel analysis, etc.

    Includes anti-recursion protection (max depth = 2) to prevent
    "Inception Trap" infinite loops.
    """

    # Maximum Swarm recursion depth (prevents infinite loops)
    MAX_SWARM_DEPTH = 2

    def __init__(self, workspace_path: Path, validation_service: Any = None, swarm_bridge: Any | None = None):
        super().__init__(workspace_path, validation_service)
        self._swarm_bridge = swarm_bridge
        self._logger = logging.getLogger(__name__)

    @property
    def tool_name(self) -> str:
        return "swarm_delegate"

    @property
    def swarm_bridge(self) -> Any | None:
        """Get the configured SwarmBridge."""
        return self._swarm_bridge

    @swarm_bridge.setter
    def swarm_bridge(self, bridge: Any) -> None:
        """Set the SwarmBridge (for lazy initialization)."""
        self._swarm_bridge = bridge

    def execute(self, args: dict[str, Any]) -> ToolResult:
        """
        Delegate subtask to Swarm Engine.

        Args:
            args: {
                "task": "The subtask to delegate",
                "mode": "parallel|sequential|lead_support|ping_pong|specialist|red_blue",
                "phase": "analysis|debate|architecture|execution|diagnosis|consolidation" (optional),
                "context_categories": ["task", "architecture", ...] (optional),
                "_swarm_depth": int (internal - recursion tracking)
            }

        Returns:
            ToolResult with swarm execution output

        Examples:
            {"task": "Run security review", "mode": "red_blue", "phase": "debate"}
            {"task": "Analyze files in parallel", "mode": "parallel"}
            {"task": "Iterative refinement", "mode": "ping_pong", "phase": "architecture"}
        """
        # V8.3.1-hotfix: Anti-recursion depth guard ("Inception Trap" prevention)
        current_depth = args.get("_swarm_depth", 0)

        if current_depth >= self.MAX_SWARM_DEPTH:
            self._logger.warning(f"swarm_delegate blocked: depth {current_depth} >= max {self.MAX_SWARM_DEPTH}")
            return ToolResult(
                tool_name=self.tool_name,
                status="ERROR",
                output="",
                error=(
                    f"Max swarm recursion depth ({self.MAX_SWARM_DEPTH}) reached. "
                    f"Nested Swarm calls are limited to prevent infinite loops."
                ),
            )

        # Guard: SwarmBridge must be configured
        if self._swarm_bridge is None:
            return ToolResult(
                tool_name=self.tool_name,
                status="ERROR",
                output="",
                error="SwarmBridge not configured. Cannot delegate to Swarm.",
            )

        task = args.get("task")
        mode_str = args.get("mode", "specialist")
        phase_str = args.get("phase")
        context_categories = args.get("context_categories")

        # V8.3.1-hotfix: Propagate depth to nested calls
        next_depth = current_depth + 1

        # Validate task
        if not task:
            return ToolResult(
                tool_name=self.tool_name,
                status="ERROR",
                output="",
                error="Missing 'task' argument. Provide the subtask to delegate.",
            )

        try:
            # Import locally to avoid circular imports
            from core.intelligence.hive_mind.swarm_bridge import HivePhase
            from core.intelligence.swarm.collaboration_modes import CollaborationMode

            # Parse mode
            mode = self._parse_mode(mode_str, CollaborationMode)
            if isinstance(mode, ToolResult):
                return mode  # Error result

            # Parse phase (optional)
            phase = self._parse_phase(phase_str, HivePhase)
            if isinstance(phase, ToolResult):
                return phase  # Error result

            # Execute delegation (async -> sync wrapper)
            from core.utils.async_utils import run_sync

            result = run_sync(
                self._swarm_bridge.delegate(
                    task=task,
                    mode=mode,
                    phase=phase,
                    context_categories=context_categories,
                    config={"_swarm_depth": next_depth},
                )
            )

            # FEEDBACK LOOP: Inject results into HiveMind context
            if result.success and hasattr(self._swarm_bridge, "inject_results_into_context"):
                self._swarm_bridge.inject_results_into_context(result)

            # Build output with metadata
            output_parts = [result.summary] if result.summary else []
            if result.fallback_chain and len(result.fallback_chain) > 1:
                chain_str = " -> ".join(m.value for m in result.fallback_chain)
                output_parts.append(f"[Fallback chain: {chain_str}]")
            output_parts.append(f"[Mode: {result.mode_used.value}, Time: {result.execution_time:.2f}s]")

            return ToolResult(
                tool_name=self.tool_name,
                status="SUCCESS" if result.success else "FAILURE",
                output="\n".join(output_parts),
                error="; ".join(result.failure_diagnostics) if not result.success else "",
            )

        except Exception as e:
            self._logger.error(f"swarm_delegate failed: {e}")
            return ToolResult(
                tool_name=self.tool_name, status="ERROR", output="", error=f"Swarm delegation error: {str(e)}"
            )

    def _parse_mode(self, mode_str: str, CollaborationMode: Any) -> Any:
        """Parse collaboration mode string to enum."""
        try:
            return CollaborationMode.from_string(mode_str)
        except (ValueError, AttributeError):
            # Fallback: try direct enum access
            mode_upper = mode_str.upper()
            if hasattr(CollaborationMode, mode_upper):
                return CollaborationMode[mode_upper]
            else:
                valid_modes = [m.value for m in CollaborationMode]
                return ToolResult(
                    tool_name=self.tool_name,
                    status="ERROR",
                    output="",
                    error=f"Invalid mode: '{mode_str}'. Valid modes: {valid_modes}",
                )

    def _parse_phase(self, phase_str: str | None, HivePhase: Any) -> Any:
        """Parse HivePhase string to enum (or None)."""
        if not phase_str:
            return None

        try:
            return HivePhase(phase_str.lower())
        except ValueError:
            valid_phases = [p.value for p in HivePhase]
            return ToolResult(
                tool_name=self.tool_name,
                status="ERROR",
                output="",
                error=f"Invalid phase: '{phase_str}'. Valid phases: {valid_phases}",
            )


def create_swarm_handler(
    workspace_path: Path, validation_service: Any = None, swarm_bridge: Any = None
) -> SwarmDelegateHandler:
    """
    Factory function to create SwarmDelegateHandler.

    Args:
        workspace_path: Workspace root path
        validation_service: Optional validation service
        swarm_bridge: Optional SwarmBridge instance (can be set later)

    Returns:
        SwarmDelegateHandler instance
    """
    return SwarmDelegateHandler(workspace_path, validation_service, swarm_bridge)
