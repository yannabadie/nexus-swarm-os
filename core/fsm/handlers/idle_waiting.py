"""
NEXUS V12.4 - Idle and Waiting User State Handlers

Handles IDLE and WAITING_USER states with task routing logic.
"""

import time

from core.execution_pkg.routing.model_router import TaskType
from core.fsm.handlers.base import BaseHandler
from core.fsm.states import OrchestratorState
from core.intelligence.swarm import TaskComplexity

# V8.0 TRUE HIVE MIND
try:
    from core.intelligence.hive_mind import TaskComplexity as HiveComplexity
    from core.intelligence.hive_mind import TrueHiveMind

    HIVE_MIND_AVAILABLE = True
except ImportError:
    HIVE_MIND_AVAILABLE = False
    TrueHiveMind = None
    HiveComplexity = None


class IdleWaitingHandler(BaseHandler):
    """Handler for IDLE and WAITING_USER states."""

    def handle_idle(self, user_input: str | None) -> dict:
        """
        Handle IDLE state - process new user input.

        Routes by task complexity:
        - TRIVIAL: Fast Path (static or Gemini response)
        - SIMPLE: Single agent, direct execution
        - MODERATE+: Swarm or Brainstorming

        Args:
            user_input: User's input text

        Returns:
            Result dict
        """
        if not user_input:
            return self._make_result("IDLE", None, None, False)

        # Step 1: Analyze task complexity
        task_analysis = self._orch.task_analyzer.analyze(user_input)
        complexity = task_analysis.complexity

        # V7.7 Phase 14e: Store complexity for CoT enforcement
        self._orch._current_complexity = complexity

        # V7.5 HIVE MIND: Track task for Auto-Memory
        self._orch._current_task_start = time.time()
        self._orch._current_task_description = user_input[:200]
        self._orch._current_task_type = (
            task_analysis.primary_domain.value if task_analysis.primary_domain else "general"
        )

        # Check Auto-Memory for recommendations
        memory_rec = self._orch.auto_memory.get_recommendation(self._orch._current_task_type)
        if memory_rec["confidence"] > 0.5 and memory_rec["suggested_mode"]:
            self._logger.debug(
                "Auto-Memory recommendation",
                {
                    "suggested_mode": memory_rec["suggested_mode"],
                    "suggested_lead": memory_rec["suggested_lead"],
                    "confidence": memory_rec["confidence"],
                },
            )

        self._logger.debug(
            "Task complexity analysis",
            {
                "input": user_input[:100],
                "complexity": complexity.name,
                "domains": [d.value for d in task_analysis.domains[:3]],
                "recommended_lead": task_analysis.recommended_lead,
                "memory_confidence": memory_rec["confidence"],
            },
        )

        # Step 2: Route based on complexity

        # TRIVIAL -> Fast Path
        if complexity == TaskComplexity.TRIVIAL:
            return self._handle_trivial(user_input)

        # SIMPLE -> Single agent mode
        if complexity == TaskComplexity.SIMPLE:
            self._logger.debug(
                "SIMPLE task - single agent mode", {"input": user_input, "lead": task_analysis.recommended_lead}
            )
            return self._execute_simple_task(user_input, task_analysis)

        # MODERATE/COMPLEX/EXPERT -> Swarm or Brainstorming
        return self._handle_moderate_plus(user_input, task_analysis)

    def handle_waiting_user(self, user_input: str | None) -> dict:
        """
        Handle WAITING_USER state - task completed, awaiting new input.

        Args:
            user_input: New user input (if any)

        Returns:
            Result dict
        """
        if not user_input:
            # No new input - stay waiting
            return self._make_result("WAITING_USER", None, None, False)

        # New input received - reset and process as new task
        self._logger.debug("WAITING_USER -> new input received, transitioning to IDLE")
        self._orch.iteration = 0
        self._orch.stagnation_detector.reset()
        self._orch.stalemate_counter = 0
        self._orch.panic_system.reset_errors()
        self._orch._transition_to(OrchestratorState.IDLE)

        # Process the new input by recursing through IDLE state
        return self._orch.process_turn(user_input)

    def _handle_trivial(self, user_input: str) -> dict:
        """Handle TRIVIAL complexity tasks."""
        if getattr(self._orch.config, "fast_path_enabled", True):
            self._logger.debug("TRIVIAL task - Fast Path enabled", {"input": user_input})
            result = self._handle_fast_path(user_input)
            # V10 FIX F2: Fast Path can return None to escalate
            if result is not None:
                return result
            self._logger.debug("Fast Path escalated to normal flow")

        # Static fallback responses
        self._logger.debug("TRIVIAL task - static fallback", {"input": user_input})
        greeting_responses = {
            "hello": "Hello! How can I help you today?",
            "hi": "Hi! What would you like to work on?",
            "bonjour": "Bonjour ! Comment puis-je vous aider ?",
            "salut": "Salut ! Qu'est-ce que je peux faire pour vous ?",
            "hey": "Hey! What's up?",
            "test": "Test acknowledged. System operational.",
            "ok": "Understood. What's next?",
            "oui": "D'accord. Quelle est la prochaine étape ?",
            "merci": "De rien ! N'hésitez pas si vous avez d'autres questions.",
            "thanks": "You're welcome! Let me know if you need anything else.",
        }
        input_lower = user_input.strip().lower().rstrip("!?.")
        response = greeting_responses.get(input_lower, f"Acknowledged: '{user_input}'. What would you like to do?")
        return self._make_result("WAITING_USER", response, None, True)

    def _execute_simple_task(self, user_input: str, task_analysis) -> dict:
        """
        Handle SIMPLE complexity tasks - single agent mode.

        Delegates to _handle_moderate_plus without Hive Mind routing,
        as SIMPLE tasks don't require full multi-agent collaboration.

        Args:
            user_input: User task input
            task_analysis: TaskAnalysis object with routing recommendation

        Returns:
            Result dict
        """
        # SIMPLE tasks skip Hive Mind, go directly to Swarm or Brainstorm
        return self._handle_moderate_plus(user_input, task_analysis)

    def _handle_moderate_plus(self, user_input: str, task_analysis) -> dict:
        """Handle MODERATE/COMPLEX/EXPERT tasks."""
        complexity = task_analysis.complexity

        # V8.0 TRUE HIVE MIND: Check if should route to Hive Mind
        if self._should_use_hive_mind(complexity):
            return self._route_to_hive_mind(user_input, task_analysis)

        # Try Swarm first if enabled
        if self._orch.swarm_engine and getattr(self._orch.config, "swarm_auto_route", True):
            self._logger.debug("MODERATE+ task - Swarm mode", {"input": user_input[:100]})
            swarm_start = time.time()
            try:
                swarm_result = self._orch.process_with_swarm(user_input)
                swarm_duration = time.time() - swarm_start

                # Record telemetry
                if self._orch.telemetry and swarm_result:
                    swarm_result.get("analysis", {})
                    execution = swarm_result.get("execution", {})
                    self._orch.telemetry.record_swarm_task(
                        mode=swarm_result.get("mode", "unknown"),
                        rounds=execution.get("rounds", 0) if isinstance(execution, dict) else 0,
                        duration_seconds=swarm_duration,
                        success=swarm_result.get("finished", False),
                        agents_used=execution.get("agents", []) if isinstance(execution, dict) else [],
                    )

                # Check if completed
                if swarm_result.get("finished") or swarm_result.get("state") == "COMPLETED":
                    return self._format_swarm_result(swarm_result)

                elif swarm_result.get("error"):
                    self._logger.warn(
                        "Swarm failed, falling back to BRAINSTORMING", {"error": swarm_result.get("error")}
                    )
                    if self._orch.telemetry:
                        self._orch.telemetry.record_error("SWARM_ERROR", swarm_result.get("error"))

            except Exception as e:
                self._logger.warn(f"Swarm exception, falling back to BRAINSTORMING: {e}")
                if self._orch.telemetry:
                    self._orch.telemetry.record_error("SWARM_EXCEPTION", str(e))

        # Fallback to BRAINSTORMING (V8.4.0: use normalized agent ID)
        self._orch.blackboard["objective"] = user_input
        self._orch.blackboard["current_state"]["iteration"] = self._orch.iteration
        self._orch.active_agent = "gemini"  # V8.4.0: lowercase normalized
        self._orch.stagnation_detector.reset()
        self._orch.stalemate_counter = 0

        self._orch._transition_to(OrchestratorState.BRAINSTORMING)
        return self._make_result("BRAINSTORMING", f"[Task Started] {user_input}", "Gemini", False)

    # =========================================================================
    # V8.0 TRUE HIVE MIND Integration
    # =========================================================================

    def _should_use_hive_mind(self, complexity: TaskComplexity) -> bool:
        """
        Determine if task should be routed to V8 Hive Mind.

        Gating logic (per user decision Q1):
        - COMPLEX/EXPERT: Always use Hive Mind
        - MODERATE: Use Hive Mind if hive_mind_moderate=True (default)
        - TRIVIAL/SIMPLE: Never use Hive Mind (handled elsewhere)

        Returns:
            True if should use Hive Mind
        """
        if not HIVE_MIND_AVAILABLE:
            return False

        # Check if Hive Mind is enabled
        if not getattr(self._orch.config, "hive_mind_enabled", True):
            return False

        # COMPLEX/EXPERT: Always use Hive Mind
        if complexity in (TaskComplexity.COMPLEX, TaskComplexity.EXPERT):
            self._logger.info(f"Routing to Hive Mind (complexity: {complexity.name})")
            return True

        # MODERATE: Check config flag
        if complexity == TaskComplexity.MODERATE:
            use_for_moderate = getattr(self._orch.config, "hive_mind_moderate", True)
            if use_for_moderate:
                self._logger.info("Routing MODERATE task to Hive Mind (hive_mind_moderate=True)")
                return True

        return False

    def _route_to_hive_mind(self, user_input: str, task_analysis) -> dict:
        """
        Route task to V8 TRUE HIVE MIND pipeline.

        Initializes TrueHiveMind if needed and processes task through 7 phases.

        Args:
            user_input: User's task description
            task_analysis: Task analysis result

        Returns:
            Result dict compatible with FSM
        """
        import asyncio

        self._logger.info("🐝 Starting TRUE HIVE MIND V8.0 pipeline")

        try:
            # Initialize Hive Mind if not exists
            if not hasattr(self._orch, "_hive_mind") or self._orch._hive_mind is None:
                # V8.4.5: Pass swarm_engine for SwarmBridge delegation (Dictator Mode)
                self._orch._hive_mind = TrueHiveMind(
                    workspace_path=self._orch.workspace_path,
                    config=self._orch.config,
                    gemini_driver=self._orch.gemini_driver,
                    claude_driver=self._orch._get_claude_driver(TaskType.BRAINSTORM),
                    agent_pool=self._orch.agent_pool,
                    budget_tracker=getattr(self._orch.telemetry, "budget_tracker", None)
                    if self._orch.telemetry
                    else None,
                    project_memory=self._orch.project_memory,
                    auto_breakpoints=getattr(self._orch.config, "hive_mind_breakpoints_enabled", True),
                    swarm_engine=getattr(self._orch, "swarm_engine", None),
                )

            # Map TaskComplexity to HiveComplexity
            complexity_map = {
                TaskComplexity.TRIVIAL: HiveComplexity.TRIVIAL,
                TaskComplexity.SIMPLE: HiveComplexity.TRIVIAL,  # Map SIMPLE to TRIVIAL for Hive
                TaskComplexity.MODERATE: HiveComplexity.MODERATE,
                TaskComplexity.COMPLEX: HiveComplexity.COMPLEX,
                TaskComplexity.EXPERT: HiveComplexity.EXPERT,
            }
            hive_complexity = complexity_map.get(task_analysis.complexity, HiveComplexity.MODERATE)

            # Run Hive Mind (async in sync context)
            hive_start = time.time()

            # Run async HiveMind - handle already-running loops
            # V11.4 ASYNC: Use run_coroutine_threadsafe to preserve async context
            # This maintains: CancellationToken, TelemetryBridge, ProcessHandleRegistry
            try:
                # Try to get running loop - if it exists, we're in async context
                loop = asyncio.get_running_loop()
                # Loop is running - schedule coroutine on the SAME loop to preserve context
                future = asyncio.run_coroutine_threadsafe(
                    self._orch._hive_mind.process_task(user_input, hive_complexity), loop
                )
                result = future.result(timeout=300)  # 5 min timeout
            except RuntimeError:
                # No running loop - safe to use asyncio.run() directly
                result = asyncio.run(self._orch._hive_mind.process_task(user_input, hive_complexity))

            hive_duration = time.time() - hive_start

            # Record telemetry
            if self._orch.telemetry:
                self._orch.telemetry.record_swarm_task(
                    mode="hive_mind_v8",
                    rounds=len(result.phases_completed),
                    duration_seconds=hive_duration,
                    success=result.success,
                    agents_used=result.agents_used + result.agents_spawned,
                )

            # Format result
            if result.success:
                output = f"🐝 [Hive Mind V8.0] Task completed\n\n{result.output}"
                self._orch._transition_to(OrchestratorState.WAITING_USER)
                return self._make_result("FINISHED", output, "HiveMind", True)
            else:
                output = f"🐝 [Hive Mind V8.0] Task failed: {result.error}\n\nPhases completed: {', '.join(result.phases_completed)}"
                if result.state.value == "hive_escalate":
                    # User requested escalation
                    return self._make_result("WAITING_USER", output, "HiveMind", True)
                else:
                    # Error occurred
                    return self._make_result("ERROR", output, "HiveMind", False, error=result.error)

        except Exception as e:
            self._logger.error(f"Hive Mind error: {e}", exc_info=True)
            if self._orch.telemetry:
                self._orch.telemetry.record_error("HIVE_MIND_ERROR", str(e))

            # Fallback to Swarm/Brainstorming
            self._logger.warn("Falling back to Swarm/Brainstorming after Hive Mind error")
            return self._fallback_to_swarm_or_brainstorm(user_input, task_analysis)

    def _fallback_to_swarm_or_brainstorm(self, user_input: str, task_analysis) -> dict:
        """Fallback when Hive Mind fails."""
        # Try Swarm
        if self._orch.swarm_engine and getattr(self._orch.config, "swarm_auto_route", True):
            try:
                swarm_result = self._orch.process_with_swarm(user_input)
                if swarm_result.get("finished") or swarm_result.get("state") == "COMPLETED":
                    return self._format_swarm_result(swarm_result)
            except Exception as e:
                # V8.4.5: Log swarm failure instead of silent swallowing
                self._logger.warn(f"Swarm processing failed, falling back to brainstorming: {str(e)[:100]}")

        # Fallback to Brainstorming (V8.4.0: use normalized agent ID)
        self._orch.blackboard["objective"] = user_input
        self._orch.active_agent = "gemini"  # V8.4.0: lowercase normalized
        self._orch._transition_to(OrchestratorState.BRAINSTORMING)
        return self._make_result("BRAINSTORMING", f"[Task Started - Fallback] {user_input}", "Gemini", False)

    def _format_swarm_result(self, swarm_result: dict) -> dict:
        """Format successful swarm result."""
        execution = swarm_result.get("execution", {})
        agent_outputs = execution.get("agent_outputs", [])
        mode = swarm_result.get("mode", "unknown")

        if agent_outputs:
            formatted_output = f"[Swarm] Mode: {mode} | Agents: {len(agent_outputs)}\n"
            for agent_data in agent_outputs:
                agent_id = agent_data.get("agent_id", "")
                content = agent_data.get("content", "")
                status = agent_data.get("status", "success")

                # V8.4.0: Use registry for agent identification
                if self._registry.is_gemini(agent_id):
                    agent_name = "🤖 Gemini"
                else:
                    agent_name = "🧠 Claude"

                if status == "error" or content.startswith("Error:") or not content.strip():
                    error_msg = agent_data.get("error") or content or "[No response]"
                    formatted_output += f"\n{agent_name} [NO] ERREUR:\n{error_msg}\n{'-' * 40}\n"
                else:
                    formatted_output += f"\n{agent_name}:\n{content}\n{'-' * 40}\n"
        else:
            raw_output = swarm_result.get("output", "")
            if raw_output.startswith("[Swarm]"):
                raw_output = raw_output[7:].lstrip()
            formatted_output = f"[Swarm] Mode: {mode}\n\n{raw_output}"

        return {
            "state": "WAITING_USER",
            "output": formatted_output,
            "agent": "Swarm",
            "finished": True,
            "swarm_mode": mode,
            "swarm_analysis": swarm_result.get("analysis"),
        }
