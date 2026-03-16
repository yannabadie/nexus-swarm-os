"""
NEXUS V7.8 - Agent Invoker Module (Phase 14c)

Extracted from orchestration_v7.py to follow Single Responsibility Principle.

This module handles all agent invocation operations:
- get_claude_driver(): Task-aware Claude driver creation
- invoke_agent(): Main agent invocation with model routing
- invoke_for_swarm(): Swarm-specific invocation
- invoke_spawned_agent(): Invoke custom spawned agents
- invoke_agent_direct(): Thread-safe direct invocation
- record_invocation(): DyLAN metrics recording
- calculate_quality_score(): Quality scoring for invocations

Usage:
    invoker = AgentInvoker(orchestrator)
    response = invoker.invoke_agent(TaskType.BRAINSTORM, context)
"""

import logging
from typing import TYPE_CHECKING

import tiktoken

from core.execution_pkg.routing.model_router import TaskType
from core.foundation.agents.unified_registry import get_registry
from core.fsm.states import OrchestratorState
from core.intelligence.swarm import AgentInvocationResult

# V13.0: Real-time telemetry for CEREBRO UI
from core.observability.events.telemetry_bridge import _resolve_tenant_workspace, get_telemetry_bridge
from core.observability.events.types import CerebroEventType
from core.observability.telemetry import BudgetExceededError

if TYPE_CHECKING:
    from core.orchestration_v7 import OrchestratorV7


class AgentInvoker:
    """
    Agent invocation handler for NEXUS orchestrator.

    Manages all interactions with AI agents (Claude, Gemini, Spawned):
    - Model routing based on task type
    - Budget enforcement
    - Streaming support
    - DyLAN metrics recording
    - Thread-safe invocation for parallel execution

    Phase 14c: Extracted from OrchestratorV7 for better maintainability.
    """

    def __init__(self, orchestrator: "OrchestratorV7"):
        """
        Initialize agent invoker with orchestrator reference.

        Uses composition pattern - invoker accesses orchestrator state
        but doesn't own it.

        Args:
            orchestrator: Parent OrchestratorV7 instance
        """
        self._orch = orchestrator
        self._logger = logging.getLogger("nexus.agent_invoker")
        self._registry = get_registry()
        self._telemetry_bridge = get_telemetry_bridge()

    def _emit_agent_status(self, agent_name: str, status: str, task_type: str = "") -> None:
        """
        Emit GRAPH_NODE_UPDATE event for real-time UI updates.

        V13.0: Enables CEREBRO UI to show agent activity in real-time.

        Args:
            agent_name: "Claude" or "Gemini"
            status: "active", "idle", or "complete"
            task_type: Optional task type description
        """
        if callable(getattr(self._orch, "on_agent_status", None)):
            try:
                self._orch.on_agent_status(
                    {
                        "type": "agent_status",
                        "agent": agent_name.lower(),
                        "status": status,
                        "task_type": task_type,
                    }
                )
            except Exception as e:
                self._logger.debug(f"[TELEMETRY] Local runtime callback failed (non-blocking): {e}")

        try:
            # Node IDs match workflow.py spawn: "gemini" and "claude"
            node_id = agent_name.lower()

            # V13.0 FIX: Use centralized tenant resolution (checks subscribers first)
            tenant_id, workspace_id = _resolve_tenant_workspace()

            # Skip if no subscribers available
            if not tenant_id:
                self._logger.debug(f"[TELEMETRY] No subscribers for {node_id} -> {status}")
                return

            result = self._telemetry_bridge.emit_sync(
                CerebroEventType.GRAPH_NODE_UPDATE,
                {
                    "node_id": node_id,
                    "data": {"name": agent_name, "status": status, "task_type": task_type},
                },
                tenant_id=tenant_id,
                workspace_id=workspace_id,
            )
            self._logger.debug(f"[TELEMETRY] {node_id} -> {status}: {result}")
        except Exception as e:
            # Fire-and-forget: never block agent execution
            self._logger.debug(f"[TELEMETRY] Emit failed (non-blocking): {e}")

    def get_claude_driver(self, task_type: TaskType, timeout_override: int | None = None):
        """
        Get Claude driver with appropriate model for task type.

        V7 Sprint 8: Task-aware model selection
        - Opus for: BRAINSTORM, REDTEAM, ARCHITECT, EVOLUTION
        - Sonnet for: TOOL, VALIDATION, SIMPLE, FORMAT

        V12.4 COGNITIVE BOOST: Uses AsyncDriverFactory for SDK-first architecture.
        Returns SDK driver when API key available, falls back to CLI otherwise.

        Args:
            task_type: Type of task for model selection
            timeout_override: Optional timeout override (e.g., shorter for CFL)

        Returns:
            Driver instance (SDK or CLI based on factory configuration)
        """
        model = self._orch.model_router.select_claude_model(task_type)

        # V12.4: Use factory to get best available driver (SDK or CLI)
        driver = self._orch._driver_factory.get_best_claude(model)

        # Override timeout if specified (for CFL validation)
        # Note: SDK drivers and CLI drivers both support timeout attribute
        if timeout_override and hasattr(driver, "timeout"):
            driver.timeout = timeout_override

        return driver

    def invoke_agent(self, task_type: TaskType, context: str) -> dict:
        """
        Invoke the active agent with task-aware model selection.

        V7 Sprint 8: Routes Claude to Opus/Sonnet based on task type.
        V7.6 Phase 14d: Budget enforcement before invocation.
        Gemini always uses the same driver.

        Args:
            task_type: Type of task for model routing
            context: Full context to send

        Returns:
            Response dict with content
        """
        # Phase 14d: Enforce budget limit before API call
        try:
            if self._orch.telemetry:
                self._orch.telemetry.enforce_budget()
        except BudgetExceededError as e:
            self._logger.error(f"Budget exceeded: {e}")
            # Transition to ERROR state with budget message
            self._orch._transition_to(OrchestratorState.ERROR)
            return {
                "sender": "System",
                "action_type": "ERROR",
                "content": f"BUDGET EXCEEDED: Daily limit of ${e.limit:.2f} reached (spent: ${e.spent:.2f}). Use /budget reset to unlock.",
                "status": "ERROR",
            }

        # V7.7 Phase 15: Use streaming if enabled and callback is set
        use_streaming = getattr(self._orch.config, "streaming_enabled", False) and self._orch.on_token is not None

        # V8.4.0: Use registry for agent lookup
        if self._registry.is_claude(self._orch.active_agent):
            driver = self.get_claude_driver(task_type)
            # V13.0: Emit active status before invocation
            self._emit_agent_status("Claude", "active", task_type.value)
            try:
                if use_streaming:
                    result = driver.invoke_stream(context, self._orch.on_token)
                else:
                    result = driver.invoke(context)
                # V13.0: Emit idle status after invocation
                self._emit_agent_status("Claude", "idle", task_type.value)
                return result
            except Exception:
                self._emit_agent_status("Claude", "idle", task_type.value)
                raise
        else:
            # V13.0: Emit active status before invocation
            self._emit_agent_status("Gemini", "active", task_type.value)
            try:
                if use_streaming:
                    result = self._orch.gemini_driver.invoke_stream(context, self._orch.on_token)
                else:
                    result = self._orch.gemini_driver.invoke(context)
                # V13.0: Emit idle status after invocation
                self._emit_agent_status("Gemini", "idle", task_type.value)
                return result
            except Exception:
                self._emit_agent_status("Gemini", "idle", task_type.value)
                raise

    def invoke_for_swarm(
        self,
        agent_id: str,
        task_type: str,
        context: str,
        session_uuid: str | None = None,
        isolated_env: dict[str, str] | None = None,
    ) -> str:
        """
        Invoke agent for HybridSwarmEngine.

        V7 Sprint 9: Callback for swarm engine to invoke agents.
        V7.5 HIVE MIND: Extended to support spawned agents.
        V8.1.6: Added session_uuid for thread-safe parallel execution.
        V9.7.1: Added isolated_env for Gemini session isolation via HOME spoofing.
        Returns raw content string for negotiation/execution.

        Args:
            agent_id: "gemini_primary", "claude_opus", or spawned agent ID
            task_type: Task type string (negotiation, execution, etc.)
            context: Task context from swarm executor (will be enriched)
            session_uuid: Optional session UUID for file isolation (V8.1.6)
            isolated_env: V9.7.1 - Isolated environment for Gemini session isolation

        Returns:
            Agent response content as string
        """
        # V7.5 HIVE MIND: Check if this is a spawned agent
        if self.is_spawned_agent(agent_id):
            return self.invoke_spawned_agent(agent_id, task_type, context, isolated_env)

        # V8.4.0: Use registry for agent identification
        self._registry.is_claude(agent_id)
        # V7 FIX: Use local variable instead of shared self.active_agent to avoid race condition
        # in parallel execution mode. Each thread must know which agent it's invoking.
        target_agent = self._registry.get_display_name(agent_id)

        try:
            # Map task type string to TaskType enum
            task_type_enum = TaskType.BRAINSTORM  # Default
            if task_type == "negotiation":
                task_type_enum = TaskType.BRAINSTORM  # Use Opus for negotiation
            elif task_type == "execution":
                task_type_enum = TaskType.TOOL  # Use Sonnet for execution
            elif task_type == "validation":
                task_type_enum = TaskType.VALIDATION

            # V7 FIX: Build rich context for swarm execution
            # Use context_builder if available, otherwise use provided context
            if hasattr(self._orch, "context_builder"):
                enriched_context = self._orch.context_builder.build_swarm_context(context, task_type, target_agent)
            else:
                enriched_context = self._orch._build_swarm_context(context, task_type, target_agent)

            # V7 FIX: Pass target_agent explicitly to avoid race condition
            # V8.1.6: Pass session_uuid for thread-safe file access
            # V9.7.1: Pass isolated_env for Gemini session isolation
            response = self.invoke_agent_direct(
                task_type_enum, enriched_context, target_agent, session_uuid=session_uuid, isolated_env=isolated_env
            )
            return response.get("content", str(response))

        except Exception as e:
            self._logger.error(f"Swarm invocation failed: {e}")
            return f"Error: {e}"

    def is_spawned_agent(self, agent_id: str) -> bool:
        """
        Check if an agent_id refers to a spawned agent.

        V7.5 HIVE MIND: Spawned agents have provider == "spawned" in the AgentPool.

        Args:
            agent_id: Agent identifier to check

        Returns:
            True if agent is a spawned agent
        """
        if not self._orch.agent_pool:
            return False
        if agent_id not in self._orch.agent_pool.agents:
            return False
        return self._orch.agent_pool.agents[agent_id].provider == "spawned"

    def invoke_spawned_agent(
        self, agent_id: str, task_type: str, context: str, isolated_env: dict[str, str] | None = None
    ) -> str:
        """
        Invoke a spawned agent with its specialized system prompt.

        V7.5 HIVE MIND: Spawned agents are invoked via their configured provider
        with custom system_prompt.md prepended to the context.
        V8.1.8-B: Provider routing based on BIRTH_CERTIFICATE inference config.
        V9.7.1: Added isolated_env for Gemini session isolation via HOME spoofing.

        Args:
            agent_id: The spawned agent's ID
            task_type: Task type string (execution, etc.)
            context: Task context from swarm executor
            isolated_env: V9.7.1 - Isolated environment for Gemini session isolation

        Returns:
            Agent response content as string
        """
        try:
            # Load the agent's specialized system prompt
            system_prompt = None
            agent_config = None
            if self._orch.spawned_agent_loader:
                system_prompt = self._orch.spawned_agent_loader.load_system_prompt(agent_id)
                agent_config = self._orch.spawned_agent_loader.load_agent_config(agent_id)

            # V8.1.8-B: Determine target provider from inference config
            target_agent = "Claude"  # Default
            if agent_config and agent_config.inference:
                provider = agent_config.inference.provider.lower()
                target_agent = "Gemini" if provider == "gemini" else "Claude"

            # Build context with specialized prompt
            if system_prompt:
                enriched_context = f"""# SPAWNED AGENT: {agent_id}

## Specialized System Prompt
{system_prompt}

## Task
{context}
"""
            else:
                # Fallback: use agent capabilities as context
                agent_profile = self._orch.agent_pool.agents.get(agent_id)
                capabilities = agent_profile.capabilities if agent_profile else []
                enriched_context = f"""# SPAWNED AGENT: {agent_id}

## Capabilities
{", ".join(capabilities) if capabilities else "general"}

## Task
{context}
"""

            self._logger.debug(
                "Invoking spawned agent",
                {
                    "agent_id": agent_id,
                    "task_type": task_type,
                    "target_agent": target_agent,  # V8.1.8-B
                    "has_system_prompt": system_prompt is not None,
                },
            )

            # Map task type to TaskType enum
            task_type_enum = TaskType.TOOL  # Default for spawned agents
            if task_type == "brainstorm":
                task_type_enum = TaskType.BRAINSTORM

            # V8.1.8-B: Route to configured provider (Claude or Gemini)
            # V9.7.1: Pass isolated_env for session isolation
            response = self.invoke_agent_direct(
                task_type_enum, enriched_context, target_agent, isolated_env=isolated_env
            )
            return response.get("content", str(response))

        except Exception as e:
            self._logger.error(f"Spawned agent invocation failed: {e}", {"agent_id": agent_id})
            return f"Error invoking spawned agent {agent_id}: {e}"

    def invoke_agent_direct(
        self,
        task_type: TaskType,
        context: str,
        target_agent: str,
        session_uuid: str | None = None,
        isolated_env: dict[str, str] | None = None,
    ) -> dict:
        """
        Invoke a specific agent directly without using shared state.

        Thread-safe version for parallel execution.
        V7.6 Phase 14d: Budget enforcement before invocation.
        V8.1.6: Added session_uuid for thread-safe file access.
        V9.7.1: Added isolated_env for Gemini session isolation via HOME spoofing.

        Args:
            task_type: Type of task for model routing
            context: Full context to send
            target_agent: "Claude" or "Gemini"
            session_uuid: Optional session UUID for file isolation (V8.1.6)
            isolated_env: V9.7.1 - Isolated environment dict with HOME/USERPROFILE.
                         When provided, Gemini subprocess uses this env and --resume latest.
                         CWD stays at project root (no ghost files).

        Returns:
            Response dict with content
        """
        # Phase 14d: Enforce budget limit before API call
        try:
            if self._orch.telemetry:
                self._orch.telemetry.enforce_budget()
        except BudgetExceededError as e:
            self._logger.error(f"Budget exceeded in swarm: {e}")
            return {
                "sender": "System",
                "action_type": "ERROR",
                "content": f"BUDGET EXCEEDED: ${e.spent:.2f}/${e.limit:.2f}",
                "status": "ERROR",
            }

        # V7.7 Phase 15: Use streaming if enabled and callback is set
        use_streaming = getattr(self._orch.config, "streaming_enabled", False) and self._orch.on_token is not None

        # V8.4.0: Use registry for agent identification
        if self._registry.is_claude(target_agent):
            # Claude driver is stateless - no isolated_env needed
            driver = self.get_claude_driver(task_type)
            # V13.0: Emit active status before invocation
            self._emit_agent_status("Claude", "active", task_type.value)
            try:
                if use_streaming:
                    # V8.1.6: Pass session_uuid for thread-safe file access
                    result = driver.invoke_stream(context, self._orch.on_token, session_uuid=session_uuid)
                else:
                    result = driver.invoke(context, session_uuid=session_uuid)
                # V13.0: Emit idle status after invocation
                self._emit_agent_status("Claude", "idle", task_type.value)
                return result
            except Exception:
                self._emit_agent_status("Claude", "idle", task_type.value)
                raise
        else:
            # V9.7.1: Gemini driver uses isolated_env for session isolation (HOME spoofing)
            # V13.0: Emit active status before invocation
            self._emit_agent_status("Gemini", "active", task_type.value)
            try:
                if use_streaming:
                    result = self._orch.gemini_driver.invoke_stream(
                        context, self._orch.on_token, session_uuid=session_uuid, isolated_env=isolated_env
                    )
                else:
                    result = self._orch.gemini_driver.invoke(
                        context, session_uuid=session_uuid, isolated_env=isolated_env
                    )
                # V13.0: Emit idle status after invocation
                self._emit_agent_status("Gemini", "idle", task_type.value)
                return result
            except Exception:
                self._emit_agent_status("Gemini", "idle", task_type.value)
                raise

    def record_invocation(
        self,
        agent_name: str,
        task_type: str,
        success: bool,
        duration: float,
        quality_score: float = 0.5,
        response_text: str | None = None,
    ) -> None:
        """
        Record agent invocation for DyLAN-style metrics (V7 Sprint 3).

        Args:
            agent_name: "Gemini" or "Claude"
            task_type: Task type (brainstorm, tool, etc.)
            success: Whether invocation succeeded
            duration: Time in seconds
            quality_score: Quality score 0.0-1.0 (default 0.5)
            response_text: Optional response text for accurate token counting
        """
        if not self._orch.agent_pool:
            return

        # V8.4.0: Use registry for agent mapping
        agent_id = "gemini_primary" if self._registry.is_gemini(agent_name) else "claude_opus"

        # Count tokens using tiktoken (accurate) or fallback to estimate
        estimated_tokens = 500  # Default estimate
        if response_text:
            try:
                encoding = tiktoken.get_encoding("cl100k_base")
                estimated_tokens = len(encoding.encode(response_text))
            except Exception:
                # Fallback: rough estimate (1 token ≈ 4 chars)
                estimated_tokens = len(response_text) // 4

        invocation = AgentInvocationResult(
            agent_id=agent_id,
            task_type=task_type,
            success=success,
            quality_score=quality_score,
            tokens_used=estimated_tokens,
            time_seconds=duration,
        )
        self._orch.agent_pool.record_invocation(invocation)

        self._logger.debug(
            "Agent invocation recorded",
            {
                "agent_id": agent_id,
                "task_type": task_type,
                "success": success,
                "duration": f"{duration:.2f}s",
                "tokens": estimated_tokens,
                "importance": f"{invocation.importance_score:.4f}",
            },
        )

    def calculate_quality_score(self, message: dict, validation_ok: bool, is_stagnant: bool) -> float:
        """
        Calculate DyLAN quality score for agent invocation.

        Quality is based on multiple factors:
        - Message validation success (+0.2)
        - Response length appropriate (+0.1)
        - No stagnation detected (+0.2)
        - Task completion status (+0.2 FINISHED, +0.1 CONTINUE)

        Args:
            message: Parsed message dict from agent
            validation_ok: Whether message validation succeeded
            is_stagnant: Whether stagnation was detected

        Returns:
            Quality score between 0.0 and 1.0
        """
        score = 0.3  # Base score

        # Validation success
        if validation_ok:
            score += 0.2

        # Response length (neither too short nor too long)
        content = message.get("content", "")
        if 50 < len(content) < 5000:
            score += 0.1

        # No stagnation
        if not is_stagnant:
            score += 0.2

        # Task status
        status = message.get("status", "")
        if status == "FINISHED":
            score += 0.2
        elif status == "CONTINUE":
            score += 0.1

        return min(1.0, score)
