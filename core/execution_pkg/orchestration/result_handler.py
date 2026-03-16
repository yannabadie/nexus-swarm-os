"""
NEXUS V12.4 P5.1 - Result Handler Module

Extracted from orchestration_v7.py (Phase 3 of decomposition).

Centralizes result creation, validation, and formatting logic for the orchestrator.
Handles result dict construction, message validation, and tool result formatting.

Usage:
    handler = ResultHandler(orchestrator)
    result = handler.make_result(state, output, agent, finished)
    validated = handler.validate_message(response_dict)

Phase 3 extraction (medium risk, well-defined result structure).
"""

import time

from pydantic import ValidationError

# Deferred imports to avoid circular dependency
# These are imported at runtime when methods are called


class ResultHandler:
    """
    Result handling logic for orchestrator.

    Handles result dict creation, message validation, and formatting.

    Responsibilities:
    - Create standardized result dictionaries
    - Validate message schemas (LightMessageV7/HeavyMessageV7)
    - Format tool results for display
    - Record task outcomes to Auto-Memory

    V8.8: Extracted from OrchestratorV7 as part of P5.1 decomposition.
    """

    def __init__(self, orchestrator):
        """
        Initialize result handler with orchestrator reference.

        Args:
            orchestrator: OrchestratorV7 instance (for state access)
        """
        self._orch = orchestrator

    def make_result(
        self,
        state: str,
        output: str | None,
        agent: str | None,
        finished: bool,
        error: str | None = None,
        tool: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        """
        Create standardized result dictionary.

        Builds result dict and optionally records task outcome to Auto-Memory.

        Args:
            state: Current FSM state name
            output: Agent response or output message
            agent: Active agent name (gemini/claude)
            finished: Whether task is complete
            error: Optional error message
            tool: Optional tool name (for tool execution results)
            metadata: Optional additional metadata

        Returns:
            Result dict with standard fields

        Examples:
            >>> handler = ResultHandler(orch)
            >>> result = handler.make_result("WAITING_USER", "Task done!", "claude", True)
            >>> assert result["finished"] is True
        """
        result = {"state": state, "output": output, "agent": agent, "finished": finished}

        if error:
            result["error"] = error
        if tool:
            result["tool"] = tool
        if metadata:
            result["metadata"] = metadata

        # V7.5 HIVE MIND: Record to Auto-Memory when task finishes
        if finished and state == "FINISHED" and self._orch._current_task_start > 0:
            self._record_to_auto_memory(agent, error)

        return result

    def _record_to_auto_memory(self, agent: str | None, error: str | None):
        """
        Record task outcome to Auto-Memory for learning.

        Args:
            agent: Agent that completed the task
            error: Error message if task failed
        """
        duration = time.time() - self._orch._current_task_start
        lead_agent = agent.lower() if agent else "unknown"

        if error:
            # Record failure
            self._orch.auto_memory.record_failure(
                task_type=self._orch._current_task_type,
                task_description=self._orch._current_task_description,
                swarm_mode=self._orch._current_swarm_mode,
                lead_agent=lead_agent,
                duration_seconds=duration,
                reason=error,
            )
        else:
            # Record success
            self._orch.auto_memory.record_success(
                task_type=self._orch._current_task_type,
                task_description=self._orch._current_task_description,
                swarm_mode=self._orch._current_swarm_mode,
                lead_agent=lead_agent,
                duration_seconds=duration,
                score=1.0,
            )

        # Reset tracking
        self._orch._current_task_start = 0

    def validate_message(self, response: dict, expect_heavy: bool = False) -> dict:
        """
        Validate and parse message with Pydantic V2.

        Validates response against LightMessageV7 or HeavyMessageV7 schema.

        Args:
            response: Raw response dict from agent
            expect_heavy: If True, expect HeavyMessageV7 (with TOOL_USE)

        Returns:
            Validated message dict

        Raises:
            ValueError: If message schema is invalid

        Examples:
            >>> handler = ResultHandler(orch)
            >>> validated = handler.validate_message({"action_type": "TALK", ...})
        """
        from core.synapse.protocol_v7 import HeavyMessageV7, LightMessageV7

        try:
            if expect_heavy or response.get("action_type") == "TOOL_USE":
                return HeavyMessageV7(**response).model_dump()
            else:
                return LightMessageV7(**response).model_dump()
        except ValidationError as e:
            raise ValueError(f"Invalid message schema: {e}") from e

    def format_tool_result(self, result) -> str:
        """
        Format tool result for display.

        Args:
            result: Tool execution result object

        Returns:
            Formatted string representation

        Examples:
            >>> formatted = handler.format_tool_result(tool_result)
            >>> assert "[Tool:" in formatted
        """
        return f"[Tool: {result.tool_name}] {result.status} - {result.output[:100]}"


# Module exports
__all__ = [
    "ResultHandler",
]
