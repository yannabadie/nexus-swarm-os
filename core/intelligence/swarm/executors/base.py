"""
Base Executor Classes - V9.5 Refactored

Foundation for all mode executors:
- ExecutionStatus: Enum for execution states
- AgentResponse: Response from agent invocation
- ExecutionContext: Context for mode execution
- ExecutionResult: Result of mode execution
- ModeExecutor: Abstract base class for executors
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Any

from core.foundation.agents.unified_registry import get_registry
from core.utils.artifact_verifier import ArtifactVerifier

from ..collaboration_modes import CollaborationMode
from ..mode_selector import AgentAssignment

# Lazy imports to avoid circular dependency: core.api -> infrastructure -> intelligence -> core.api
# Imported at runtime in methods that need them
_rate_limiter_mod = None
_concurrency_limiter_mod = None


def _get_rate_limiter_imports():
    global _rate_limiter_mod
    if _rate_limiter_mod is None:
        from core.api import rate_limiter as _mod

        _rate_limiter_mod = _mod
    return _rate_limiter_mod


def _get_concurrency_limiter_imports():
    global _concurrency_limiter_mod
    if _concurrency_limiter_mod is None:
        from core.api import concurrency_limiter as _mod

        _concurrency_limiter_mod = _mod
    return _concurrency_limiter_mod


def get_concurrency_limiter():
    """Public accessor for the concurrency limiter singleton. Used in tests."""
    return _get_concurrency_limiter_imports().get_concurrency_limiter()


if TYPE_CHECKING:
    pass

# Thread-safe blackboard access lock for PARALLEL mode
_blackboard_lock = Lock()

# Completion detection pattern (word boundaries)
COMPLETION_PATTERN = re.compile(r"\b(FINISHED|TASK\s+COMPLETE|COMPLETED|ALL\s+DONE)\b", re.IGNORECASE)


class ExecutionStatus(Enum):
    """Status of mode execution."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CONVERGED = "converged"
    # V10 FIX F14: Max rounds reached without convergence
    INCOMPLETE = "incomplete"


@dataclass
class AgentResponse:
    """Response from a single agent invocation."""

    agent_id: str
    content: str
    status: str = "success"
    tool_results: list[dict] = field(default_factory=list)
    tokens_used: int = 0
    time_seconds: float = 0.0
    error: str | None = None

    @property
    def is_finished(self) -> bool:
        """
        Check if agent signals completion.

        Uses regex with word boundaries to avoid false positives.
        Rejects if ongoing work indicators are present.
        """
        completion_signals = COMPLETION_PATTERN.search(self.content) is not None or self.status == "finished"

        if not completion_signals:
            return False

        # Check for ongoing work indicators
        content_lower = self.content.lower()
        ongoing_indicators = [
            "will ",
            "going to",
            "next step",
            "todo",
            "remaining",
            "need to",
            "should ",
            "plan to",
            "working on",
            "then we",
        ]

        has_ongoing = any(indicator in content_lower for indicator in ongoing_indicators)
        return not has_ongoing

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "content": self.content,
            "status": self.status,
            "tool_results_count": len(self.tool_results),
            "tokens_used": self.tokens_used,
            "time_seconds": round(self.time_seconds, 2),
            "error": self.error,
        }


@dataclass
class ExecutionContext:
    """
    Context for mode execution.

    Provides task input, agent assignments, and session management.
    """

    task_input: str
    agent_assignments: list[AgentAssignment]
    blackboard: dict = field(default_factory=dict)
    max_rounds: int = 6
    invoke_agent: Callable | None = None
    on_round: Callable[[int, AgentResponse], None] | None = None
    task_id: str | None = None
    session_manager: Any | None = None
    force_cot: bool = False

    def get_agent_by_role(self, role: str) -> AgentAssignment | None:
        """Get agent assignment by role."""
        for assignment in self.agent_assignments:
            if assignment.role == role:
                return assignment
        return None

    def get_all_agents(self) -> list[AgentAssignment]:
        """Get all agent assignments."""
        return self.agent_assignments

    def get_session_uuid(self, role: str, agent_id: str) -> str | None:
        """Get or create session UUID for an agent-role combination."""
        if self.session_manager is None or self.task_id is None:
            return None

        try:
            return self.session_manager.get_or_create_session(self.task_id, role, agent_id)
        except Exception:
            return None

    def get_workspace_path(self, role: str, agent_id: str) -> Path | None:
        """
        V9.7: Get isolated workspace path for an agent-role combination.

        DEPRECATED in V9.7.1: Use get_isolated_env() instead for HOME spoofing.
        Kept for backward compatibility.

        Args:
            role: Agent's role in the collaboration
            agent_id: Agent identifier

        Returns:
            Path to isolated workspace, or None if not using session isolation
        """
        if self.session_manager is None or self.task_id is None:
            return None

        try:
            return self.session_manager.get_workspace_path(self.task_id, role)
        except Exception:
            return None

    def get_isolated_env(self, role: str, agent_id: str) -> dict[str, str] | None:
        """
        V9.7.1: Get isolated environment for Gemini subprocess.

        Uses HOME spoofing instead of CWD isolation to prevent ghost files.
        The subprocess will have:
        - Same CWD (project root) - file operations work correctly
        - Different HOME - session storage is isolated

        Args:
            role: Agent's role in the collaboration
            agent_id: Agent identifier

        Returns:
            Environment dict with isolated HOME/USERPROFILE, or None
        """
        if self.session_manager is None or self.task_id is None:
            return None

        try:
            return self.session_manager.get_isolated_env(self.task_id, role)
        except Exception:
            return None


@dataclass
class ExecutionResult:
    """Result of mode execution."""

    mode: CollaborationMode
    status: ExecutionStatus
    final_output: str
    agent_outputs: list[AgentResponse]
    total_rounds: int
    total_tokens: int
    total_time_seconds: float
    metadata: dict = field(default_factory=dict)

    @property
    def finished(self) -> bool:
        return self.status in [ExecutionStatus.COMPLETED, ExecutionStatus.CONVERGED]

    def to_dict(self) -> dict:
        return {
            "mode": self.mode.value,
            "status": self.status.value,
            "final_output": self.final_output,
            "agent_outputs": [a.to_dict() for a in self.agent_outputs],
            "total_rounds": self.total_rounds,
            "total_tokens": self.total_tokens,
            "total_time_seconds": round(self.total_time_seconds, 2),
            "metadata": self.metadata,
        }


class ExecutionError(Exception):
    """Exception raised during mode execution."""

    pass


class ModeExecutor(ABC):
    """
    Abstract base class for mode executors.

    Provides common functionality for agent invocation, failover,
    and artifact verification.
    """

    mode: CollaborationMode

    @abstractmethod
    def execute(self, context: ExecutionContext) -> ExecutionResult:
        """Execute the mode with given context."""
        pass

    def _invoke(
        self, context: ExecutionContext, agent_id: str, task_context: str, role: str | None = None
    ) -> AgentResponse:
        """
        Invoke an agent with task context.

        Args:
            context: Execution context
            agent_id: Agent identifier
            task_context: Task context string
            role: Agent's role for session isolation

        V9.7.1: Now passes isolated_env for Gemini session isolation via HOME spoofing.
        """
        if context.invoke_agent is None:
            return AgentResponse(agent_id=agent_id, content=f"[Mock response from {agent_id}]", status="mock")

        start_time = datetime.now()

        # Get session UUID and isolated environment for session isolation
        session_uuid = None
        isolated_env = None
        if role:
            session_uuid = context.get_session_uuid(role, agent_id)
            isolated_env = context.get_isolated_env(role, agent_id)  # V9.7.1
            if session_uuid:
                with _blackboard_lock:
                    context.blackboard[f"_session_uuid_{agent_id}"] = session_uuid

        try:
            # Apply rate limiting
            registry = get_registry()
            provider = "gemini" if registry.is_gemini(agent_id) else "claude"
            _rl = _get_rate_limiter_imports()
            rate_limiter = _rl.get_rate_limiter(provider)

            try:
                rate_limiter.acquire_sync(timeout=60.0)
            except _rl.RateLimitExceeded as e:
                import sys

                print(f"[RATE LIMIT] {e}", file=sys.stderr)
                return AgentResponse(
                    agent_id=agent_id,
                    content="",
                    status="error",
                    error=f"Rate limit exceeded: {str(e)}",
                    time_seconds=(datetime.now() - start_time).total_seconds(),
                )

            # V11 SYNCHROTRON: Apply concurrency limiting to prevent resource starvation
            _cl = _get_concurrency_limiter_imports()
            concurrency_limiter = _cl.get_concurrency_limiter()
            if not concurrency_limiter.acquire_sync(timeout=60.0):
                return AgentResponse(
                    agent_id=agent_id,
                    content="",
                    status="error",
                    error="Concurrency limit reached: too many parallel agents",
                    time_seconds=(datetime.now() - start_time).total_seconds(),
                )

            try:
                # V9.7.1: Invoke agent with isolated_env for session isolation
                response = context.invoke_agent(agent_id, "execution", task_context, session_uuid, isolated_env)
            finally:
                concurrency_limiter.release_sync()

            if isinstance(response, str):
                response = AgentResponse(agent_id=agent_id, content=response, status="success")

            response.time_seconds = (datetime.now() - start_time).total_seconds()
            return response

        except Exception as e:
            return AgentResponse(
                agent_id=agent_id,
                content="",
                status="error",
                error=str(e),
                time_seconds=(datetime.now() - start_time).total_seconds(),
            )
        finally:
            if session_uuid:
                context.blackboard.pop(f"_session_uuid_{agent_id}", None)

    async def _invoke_async(
        self, context: ExecutionContext, agent_id: str, task_context: str, role: str | None = None
    ) -> AgentResponse:
        """
        Async invocation of an agent.

        Uses asyncio.to_thread() for sync driver compatibility.
        V9.7.1: Now passes isolated_env for Gemini session isolation via HOME spoofing.
        """
        if context.invoke_agent is None:
            return AgentResponse(agent_id=agent_id, content=f"[Mock response from {agent_id}]", status="mock")

        start_time = datetime.now()
        session_uuid = None
        isolated_env = None  # V9.7.1
        if role:
            session_uuid = context.get_session_uuid(role, agent_id)
            isolated_env = context.get_isolated_env(role, agent_id)  # V9.7.1

        try:
            # Async rate limiting
            registry = get_registry()
            provider = "gemini" if registry.is_gemini(agent_id) else "claude"
            _rl = _get_rate_limiter_imports()
            rate_limiter = _rl.get_rate_limiter(provider)

            try:
                await rate_limiter.acquire(timeout=60.0)
            except _rl.RateLimitExceeded as e:
                return AgentResponse(
                    agent_id=agent_id,
                    content="",
                    status="error",
                    error=f"Rate limit exceeded: {str(e)}",
                    time_seconds=(datetime.now() - start_time).total_seconds(),
                )

            # V11 SYNCHROTRON: Apply concurrency limiting to prevent resource starvation
            _cl = _get_concurrency_limiter_imports()
            concurrency_limiter = _cl.get_concurrency_limiter()
            async with concurrency_limiter.acquire_async(timeout=60.0):
                # V9.7.1: Try async invoke first, fallback to sync - both pass isolated_env
                if hasattr(context, "invoke_agent_async") and context.invoke_agent_async:
                    response = await context.invoke_agent_async(
                        agent_id, "execution", task_context, session_uuid, isolated_env
                    )
                else:
                    response = await asyncio.to_thread(
                        context.invoke_agent, agent_id, "execution", task_context, session_uuid, isolated_env
                    )

            if isinstance(response, str):
                response = AgentResponse(agent_id=agent_id, content=response, status="success")

            response.time_seconds = (datetime.now() - start_time).total_seconds()
            return response

        except Exception as e:
            return AgentResponse(
                agent_id=agent_id,
                content="",
                status="error",
                error=str(e),
                time_seconds=(datetime.now() - start_time).total_seconds(),
            )

    def _invoke_with_failover(
        self,
        context: ExecutionContext,
        primary_agent_id: str,
        backup_agent_id: str,
        task_context: str,
        primary_role: str | None = None,
        backup_role: str | None = None,
    ) -> AgentResponse:
        """Invoke primary agent, failover to backup if primary fails."""
        response = self._invoke(context, primary_agent_id, task_context, role=primary_role)

        if response.status == "error" or "timed out" in (response.error or "").lower():
            import sys

            print(f"[FAILOVER] {primary_agent_id} failed, trying {backup_agent_id}", file=sys.stderr)

            failover_context = (
                f"{task_context}\n\n[NOTE: {primary_agent_id} was unavailable. You are the failover agent.]"
            )

            backup_response = self._invoke(context, backup_agent_id, failover_context, role=backup_role)

            if backup_response.status != "error":
                backup_response.content = f"[Failover from {primary_agent_id}]\n\n{backup_response.content}"

            return backup_response

        return response

    def _get_backup_agent(self, agent_id: str) -> str:
        """Get the backup agent for a given agent."""
        registry = get_registry()
        if registry.is_gemini(agent_id):
            return "claude_opus"
        else:
            return "gemini_primary"

    def _verify_artifacts(self, content: str, context: ExecutionContext) -> dict[str, Any]:
        """Verify artifacts mentioned in agent output."""
        # V12.4: Handle None workspace_path explicitly (blackboard may have None value)
        workspace_path = context.blackboard.get("workspace_path")
        if workspace_path is None:
            workspace_path = Path.cwd()
        elif not isinstance(workspace_path, Path):
            workspace_path = Path(workspace_path)
        verifier = ArtifactVerifier(workspace_path)

        verified, successes, failures = verifier.verify_from_content(content)

        return {"verified": verified, "successes": successes, "failures": failures}

    def execute_with_fallback(self, context: ExecutionContext, max_fallbacks: int = 2) -> ExecutionResult:
        """
        Execute with automatic fallback to simpler modes on failure.

        V7.5 Phase 8: Self-Healing Swarm - Graceful Degradation

        Algorithm:
        1. Create checkpoint (if session_manager available)
        2. Try execute()
        3. If failure: restore checkpoint, get fallback mode, retry
        4. If success after fallback: mark status="RECOVERED"

        Args:
            context: Execution context
            max_fallbacks: Maximum number of fallback attempts (default 2)

        Returns:
            ExecutionResult with status potentially marked as RECOVERED
        """
        import sys

        # Lazy import to avoid circular dependency
        # Use mode_executors.EXECUTOR_REGISTRY for backward compat with tests
        from ..mode_executors import EXECUTOR_REGISTRY

        current_mode = self.mode
        checkpoint_id = None
        fallback_count = 0
        original_exception = None
        degradation_path = [current_mode.value]

        # Create checkpoint if session manager available
        if context.session_manager and context.task_id:
            with contextlib.suppress(Exception):
                checkpoint_id = context.session_manager.create_checkpoint(context.task_id)

        while fallback_count <= max_fallbacks:
            try:
                # Get appropriate executor from EXECUTOR_REGISTRY (allows test patching)
                executor = EXECUTOR_REGISTRY.get(current_mode, self)

                # Attempt execution
                result = executor.execute(context)

                # Check for failure status
                if result.status == ExecutionStatus.FAILED:
                    raise ExecutionError(
                        f"Mode {current_mode.value} returned FAILED status: "
                        f"{result.final_output[:200] if result.final_output else 'No output'}"
                    )

                # Success! Mark as recovered if we fell back
                if fallback_count > 0:
                    result.metadata["status"] = "RECOVERED"
                    result.metadata["original_mode"] = degradation_path[0]
                    result.metadata["fallback_path"] = degradation_path
                    result.metadata["fallback_count"] = fallback_count
                    print(
                        f"[SELF-HEALING] Recovered via {current_mode.value} after "
                        f"{fallback_count} fallback(s): {' -> '.join(degradation_path)}",
                        file=sys.stderr,
                    )

                return result

            except Exception as e:
                if original_exception is None:
                    original_exception = e

                # Log degradation
                error_msg = str(e)[:100] if str(e) else f"{type(e).__name__} (no message)"
                print(f"[SWARM DEGRADATION] Mode {current_mode.value} failed: {error_msg}", file=sys.stderr)

                # Restore checkpoint if available
                if checkpoint_id and context.session_manager and context.task_id:
                    with contextlib.suppress(Exception):
                        context.session_manager.restore_checkpoint(context.task_id, checkpoint_id)

                # Get fallback mode (static chain)
                fallback = current_mode.fallback_mode

                if fallback is None:
                    print(
                        f"[SWARM DEGRADATION] No fallback available for {current_mode.value}. "
                        f"Degradation path: {' -> '.join(degradation_path)}",
                        file=sys.stderr,
                    )
                    raise original_exception from e

                # Prepare for next iteration
                fallback_count += 1
                current_mode = fallback
                degradation_path.append(current_mode.value)

                print(
                    f"[SWARM DEGRADATION] Falling back to {current_mode.value} "
                    f"(attempt {fallback_count}/{max_fallbacks})",
                    file=sys.stderr,
                )

        # Exceeded max fallbacks
        raise original_exception or ExecutionError(f"Exceeded max fallbacks ({max_fallbacks}) without success")
