"""
NEXUS V9.2 - HiveMind Session Integration

Provides session management capabilities for HiveMind phases.
Ensures proper session isolation for parallel agents and
controlled context inheritance for sequential phases.

Key Features:
- Session UUID generation per agent per phase
- Model-change detection and session invalidation
- Scoped context creation for phase transitions
- Integration with SwarmSessionManager

Author: Claude (NEXUS V9.2)
Date: 2025-12-13
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from .context_scope import ContextScope, ScopedContext, get_scope_policy

if TYPE_CHECKING:
    from core.intelligence.swarm.session_manager import SwarmSessionManager

    from .context_manager import HiveMindContextManager

logger = logging.getLogger(__name__)


@dataclass
class PhaseSession:
    """
    Session state for a HiveMind phase.

    Tracks which agents have which sessions within a phase,
    and detects model changes for session invalidation.
    """

    phase_name: str
    task_id: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    # Agent sessions: agent_id -> session_uuid
    agent_sessions: dict[str, str] = field(default_factory=dict)

    # Track models used: agent_id -> model_id
    agent_models: dict[str, str] = field(default_factory=dict)

    def get_or_create_session(
        self, agent_id: str, model_id: str | None = None, invalidate_on_model_change: bool = True
    ) -> str:
        """
        Get or create session UUID for an agent.

        Handles model-change detection and session invalidation.

        Args:
            agent_id: The agent identifier (e.g., "gemini", "claude")
            model_id: Current model being used
            invalidate_on_model_change: Whether to create new session on model change

        Returns:
            Session UUID
        """
        # Check for model change
        if model_id and agent_id in self.agent_models:
            previous_model = self.agent_models[agent_id]
            if previous_model != model_id and invalidate_on_model_change:
                logger.info(
                    f"Model change detected for {agent_id}: {previous_model} -> {model_id}. Creating new session."
                )
                # Invalidate existing session
                if agent_id in self.agent_sessions:
                    del self.agent_sessions[agent_id]

        # Update model tracking
        if model_id:
            self.agent_models[agent_id] = model_id

        # Get or create session
        if agent_id not in self.agent_sessions:
            self.agent_sessions[agent_id] = str(uuid.uuid4())
            logger.debug(f"Created session for {agent_id} in phase {self.phase_name}: {self.agent_sessions[agent_id]}")

        return self.agent_sessions[agent_id]

    def get_session(self, agent_id: str) -> str | None:
        """Get existing session for agent."""
        return self.agent_sessions.get(agent_id)


class HiveMindSessionIntegration:
    """
    Mixin providing session management for HiveMind phases.

    Usage:
        class MyPhase(HiveMindSessionIntegration):
            def __init__(self, ...):
                super().__init__(
                    task_id="task_123",
                    phase_name="analysis",
                    context_manager=ctx_manager
                )

            async def execute(self, ...):
                session = self.get_agent_session("gemini")
                response = await self.gemini.send_message_async(prompt, session)
    """

    def __init__(
        self,
        task_id: str,
        phase_name: str,
        context_manager: HiveMindContextManager,
        session_manager: SwarmSessionManager | None = None,
        complexity: str = "MODERATE",
    ):
        """
        Initialize session integration.

        Args:
            task_id: Unique task identifier
            phase_name: Name of this phase (analysis, debate, etc.)
            context_manager: HiveMind context manager
            session_manager: Optional SwarmSessionManager for persistence
            complexity: Task complexity for scope policy selection
        """
        self._task_id = task_id
        self._phase_name = phase_name
        self._context_manager = context_manager
        self._session_manager = session_manager
        self._complexity = complexity
        self._scope_policy = get_scope_policy(complexity)

        # Create phase session
        self._phase_session = PhaseSession(phase_name=phase_name, task_id=task_id)

        # Track previous phase for inheritance
        self._previous_phase: str | None = None

    def set_previous_phase(self, phase_name: str):
        """Set the previous phase for context inheritance."""
        self._previous_phase = phase_name

    def get_agent_session(self, agent_id: str, model_id: str | None = None) -> str:
        """
        Get session UUID for an agent in this phase.

        Args:
            agent_id: Agent identifier
            model_id: Model being used (for change detection)

        Returns:
            Session UUID
        """
        return self._phase_session.get_or_create_session(
            agent_id=agent_id,
            model_id=model_id,
            invalidate_on_model_change=self._scope_policy.invalidate_on_model_change,
        )

    def get_parallel_sessions(self, agents: list[str], models: dict[str, str] | None = None) -> dict[str, str]:
        """
        Get isolated sessions for parallel agent execution.

        Ensures each agent gets a unique session for isolation.

        Args:
            agents: List of agent IDs
            models: Optional mapping of agent_id -> model_id

        Returns:
            Dict mapping agent_id -> session_uuid
        """
        sessions = {}
        for agent_id in agents:
            model_id = models.get(agent_id) if models else None
            sessions[agent_id] = self.get_agent_session(agent_id, model_id)
        return sessions

    def create_phase_context(
        self,
        scope: ContextScope | None = None,
        agent_id: str | None = None,
        model_id: str | None = None,
        relevant_files: list[str] | None = None,
    ) -> ScopedContext:
        """
        Create scoped context for this phase.

        Uses policy to determine appropriate scope if not specified.

        Args:
            scope: Override scope (uses policy default if None)
            agent_id: Agent to create context for
            model_id: Model being used
            relevant_files: Files relevant to this work

        Returns:
            ScopedContext for the agent
        """
        # Determine scope based on policy
        if scope is None:
            if self._previous_phase:
                scope = self._scope_policy.get_phase_scope(self._previous_phase, self._phase_name)
            else:
                scope = ContextScope.TASK_ONLY

        # Get session UUID
        session_uuid = None
        if agent_id:
            session_uuid = self.get_agent_session(agent_id, model_id)

        return self._context_manager.create_scoped_context(
            scope=scope,
            from_phase=self._previous_phase,
            session_uuid=session_uuid,
            relevant_files=relevant_files,
            model_id=model_id,
        )

    def create_spawn_context(
        self,
        task_description: str,
        agent_id: str,
        model_id: str | None = None,
        relevant_files: list[str] | None = None,
        parent_summary: str | None = None,
    ) -> ScopedContext:
        """
        Create context for a spawned agent.

        Uses spawn_scope from policy for appropriate isolation.

        Args:
            task_description: Specific task for spawned agent
            agent_id: Spawned agent identifier
            model_id: Model being used
            relevant_files: Files relevant to the task
            parent_summary: Optional custom parent summary

        Returns:
            ScopedContext for the spawned agent
        """
        # Create unique session for spawned agent
        spawn_session = str(uuid.uuid4())

        # Get parent summary if not provided
        if parent_summary is None:
            parent_summary = self._context_manager.summarize_for_inheritance(
                from_phase=self._phase_name,
                max_tokens=1000,  # Keep it concise for spawned agents
            )

        return ScopedContext(
            scope=self._scope_policy.spawn_scope,
            task_description=task_description,
            relevant_files=relevant_files or [],
            parent_summary=parent_summary if self._scope_policy.spawn_scope != ContextScope.MINIMAL else "",
            session_uuid=spawn_session,
            model_context=self._context_manager._get_model_context(model_id) if model_id else None,
            metadata={"spawned_from_phase": self._phase_name, "parent_task_id": self._task_id},
        )

    def get_scoped_prompt(
        self,
        instruction: str,
        agent_id: str,
        model_id: str | None = None,
        scope: ContextScope | None = None,
        relevant_files: list[str] | None = None,
    ) -> str:
        """
        Create a complete prompt with scoped context for an agent.

        Convenience method for direct use in phase execution.

        Args:
            instruction: The actual instruction
            agent_id: Agent to create prompt for
            model_id: Model being used
            scope: Optional scope override
            relevant_files: Relevant files

        Returns:
            Complete prompt with context prefix
        """
        scoped = self.create_phase_context(
            scope=scope, agent_id=agent_id, model_id=model_id, relevant_files=relevant_files
        )
        return f"{scoped.to_prompt_prefix()}{instruction}"

    def get_phase_stats(self) -> dict[str, Any]:
        """Get statistics for this phase's session management."""
        return {
            "task_id": self._task_id,
            "phase_name": self._phase_name,
            "complexity": self._complexity,
            "previous_phase": self._previous_phase,
            "active_sessions": len(self._phase_session.agent_sessions),
            "agents": list(self._phase_session.agent_sessions.keys()),
            "models_used": self._phase_session.agent_models.copy(),
        }


def generate_hivemind_task_id(prefix: str = "hm") -> str:
    """
    Generate a unique task ID for HiveMind.

    Args:
        prefix: Prefix for the task ID

    Returns:
        Unique task ID (e.g., "hm_20251213_151800_abc123")
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    short_uuid = str(uuid.uuid4())[:8]
    return f"{prefix}_{timestamp}_{short_uuid}"
