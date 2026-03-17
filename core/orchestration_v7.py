"""
Orchestrator V7 - FSM Persistent

Architecture FSM (Finite State Machine):
- État persistant en RAM (ne se détruit jamais)
- process_turn() appelé pour chaque user input
- Transitions explicites entre états
- Pas de while loop infini

États: IDLE -> BRAINSTORMING -> EXECUTING_TOOL -> VALIDATING_CFL -> IDLE
États spéciaux: EVOLUTION_BRAINSTORM (débat émergent 30 tours max)
"""

import asyncio
import json
import os
from collections.abc import Callable
from pathlib import Path

import tiktoken

from core.drivers.async_factory import create_driver_factory
from core.execution_pkg.execution.agent_tools import AgentToolRegistry  # V7.8 Phase 15: Agent-as-Tool
from core.execution_pkg.execution.tool_manager import ToolManager
from core.execution_pkg.orchestration import (  # V7.8 Phase 14c.2
    AgentInvoker,
    ContextBuilder,
    MutationDetector,
    SwarmBridge,
)
from core.execution_pkg.routing.model_router import ModelRouter
from core.foundation.agents.unified_registry import get_registry  # V8.4.0: Centralized agent registry
from core.fsm.context import TaskExecutionContext
from core.fsm.handlers import FSMHandlers  # V12.4 P1.3: Modular handlers
from core.fsm.panic_system import PanicSystem
from core.fsm.plan_health import PlanHealthMonitor
from core.fsm.stagnation_detector import StagnationDetector
from core.fsm.states import OrchestratorState
from core.infrastructure.bootstrap import SpawnedAgentLoader, discover_and_register_spawned_agents
from core.intelligence.hive_mind.swarm_bridge import (
    SwarmBridge as HiveMindSwarmBridge,  # V8.3.1: For swarm_delegate tool
)
from core.intelligence.swarm import (
    AgentInvocationResult,
    CollaborationMode,
    HybridSwarmEngine,
    TaskAnalysis,
    TaskAnalyzer,  # V7 FIX: For trivial input detection
    TaskComplexity,  # V7 FIX: For complexity-based routing
    create_default_pool,
)
from core.memory_pkg.memory import ProjectMemory, get_auto_memory  # V7.5 HIVE MIND + V7.8 Phase 10c
from core.observability.logging import get_logger, init_logger
from core.observability.telemetry import TelemetryCollector
from core.synapse.memory_v7 import MemoryManagerV7

# Legacy KERNEL hook kept only for explicitly opted-in internal runs.
if os.getenv("NEXUS_ENABLE_LEGACY_KERNEL_RUNTIME", "").lower() in ("true", "1"):
    try:
        from KERNEL import runtime_integrity_check

        KERNEL_AVAILABLE = True
    except ImportError:
        KERNEL_AVAILABLE = False
        runtime_integrity_check = None
else:
    KERNEL_AVAILABLE = False
    runtime_integrity_check = None

# P5.1 Phase 1: GuardPipeline extraction (replaces inline INPUT_GUARD calls)
from core.execution_pkg.orchestration.guard_pipeline import GuardPipeline


class OrchestratorV7:
    """
    FSM Orchestrator - Persistent in RAM

    Cycle de vie:
    1. Créé UNE FOIS au démarrage du REPL
    2. process_turn() appelé pour chaque user input
    3. Ne se détruit JAMAIS (sauf panic ou user quit)
    """

    def __init__(self, workspace_path: Path, config, gemini_info: dict, claude_info: dict):
        # Configuration
        self.workspace_path = workspace_path
        self.config = config

        # Initialize Logger (FIRST!)
        init_logger(workspace_path, config.log_level)
        self.logger = get_logger()

        self.logger.debug(
            "Initializing OrchestratorV7", {"workspace": str(workspace_path), "log_level": config.log_level}
        )

        # État FSM (en RAM !)
        self.state = OrchestratorState.IDLE
        self._registry = get_registry()  # V8.4.0: Centralized agent registry
        self.iteration = 0

        # V9.3: Immutable TaskExecutionContext for thread-safe active_agent tracking
        # Replaces mutable self.active_agent string to prevent race conditions in PARALLEL mode
        self._task_context: TaskExecutionContext = TaskExecutionContext.create(
            objective="",
            initial_agent="gemini",  # V8.4.0: lowercase normalized
        )

        # Memory Manager (charge blackboard UNE FOIS)
        self.memory = MemoryManagerV7(workspace_path, config)
        self.blackboard = self.memory.load_initial_state()

        # Stagnation detector
        self.stagnation_detector = StagnationDetector(
            similarity_threshold=config.stagnation_similarity_threshold, window_size=3
        )

        # Plan Health Monitor (NEW!)
        self.plan_health = PlanHealthMonitor(warning_threshold=10, stagnant_threshold=20, zombie_threshold=30)

        # Panic System (NEW!)
        self.panic_system = PanicSystem(workspace_path=workspace_path, max_stalemate=config.max_stalemate_count)

        # V7: Model Router for intelligent model selection
        self.model_router = ModelRouter(config)

        # V12.4 COGNITIVE BOOST: AsyncDriverFactory for SDK-first architecture
        # Uses SDK drivers when API keys available, falls back to CLI otherwise
        self._driver_factory = create_driver_factory(config, workspace_path)

        # Primary Gemini driver (SDK or CLI based on config)
        self.gemini_driver = self._driver_factory.get_best_gemini()

        # Legacy drivers dict for backwards compatibility
        # V8.4.0: Register drivers in unified registry
        self._registry.register_driver("gemini", self.gemini_driver)
        self.drivers = {
            "gemini": self.gemini_driver,  # V8.4.0: lowercase keys
            "claude": None,  # Created dynamically via AgentInvoker.get_claude_driver()
        }

        # Tool manager
        self.tool_manager = ToolManager(workspace_path)

        # État CFL
        self.pending_tool_result = None

        # Circuit breakers
        self.json_parse_failures = 0
        self.max_parse_failures = 3

        # V7.7 Phase 15: Streaming callback
        # Set by REPL to receive real-time tokens during agent invocations
        self.on_token: Callable[[str], None] | None = None
        self.on_agent_status: Callable[[dict[str, str]], None] | None = None

        # Stalemate counter
        self.stalemate_counter = 0

        # V7.7 Phase 14e: Force Chain-of-Thought for EXPERT tasks
        self._current_complexity: TaskComplexity | None = None

        # Metrics
        self.gemini_info = gemini_info
        self.claude_info = claude_info

        # V7 Sprint 3: Agent Pool for DyLAN-style metrics
        if self.config.agent_metrics_enabled:
            self.agent_pool = create_default_pool(self.config)

            # V7 Enhancement: Enable DyLAN score persistence
            dylan_persistence_path = self.workspace_path / ".nexus" / "dylan_scores.json"
            self.agent_pool.enable_persistence(
                path=str(dylan_persistence_path),
                auto_save=True,
                save_interval=5,  # Save every 5 invocations
            )

            self.logger.debug(
                "AgentPool initialized",
                {"agents": list(self.agent_pool.agents.keys()), "persistence": str(dylan_persistence_path)},
            )

            # V7.5 HIVE MIND: Discover and register spawned agents from workspace/agents/
            self.spawned_agent_loader = SpawnedAgentLoader(self.workspace_path)
            spawned_count = discover_and_register_spawned_agents(
                workspace_path=self.workspace_path, agent_pool=self.agent_pool
            )
            if spawned_count > 0:
                self.logger.info(
                    "Spawned agents registered",
                    {"count": spawned_count, "agents": [a.agent_id for a in self.agent_pool.get_spawned_agents()]},
                )
        else:
            self.agent_pool = None
            self.spawned_agent_loader = None

        # V7 FIX: Task Analyzer for trivial input detection
        self.task_analyzer = TaskAnalyzer()

        # V7.8 Phase 14c.2: AgentInvoker must be created BEFORE SwarmEngine (P5.1 fix)
        # Moved here from line 245 to fix initialization order
        self.context_builder = ContextBuilder(self)
        self.mutation_detector = MutationDetector()
        self.agent_invoker = AgentInvoker(self)
        self.swarm_bridge = SwarmBridge(self)
        self.fsm_handlers = FSMHandlers(self)

        # V7 Sprint 9: Hybrid Swarm Engine for dynamic multi-agent collaboration
        if getattr(self.config, "swarm_enabled", False):
            # P5.1 Phase 5: Use agent_invoker directly (delegation wrappers removed)
            self.swarm_engine = HybridSwarmEngine(
                agent_pool=self.agent_pool,
                model_router=self.model_router,
                config=self.config,
                invoke_agent=self.agent_invoker.invoke_for_swarm,
            )
            self.logger.debug(
                "HybridSwarmEngine initialized",
                {
                    "negotiation_enabled": getattr(self.config, "swarm_negotiation_enabled", True),
                    "default_mode": getattr(self.config, "swarm_default_mode", "ping_pong"),
                },
            )

            # V8.3.1: Wire SwarmBridge to ToolManager for swarm_delegate tool
            self.tool_manager.swarm_bridge = HiveMindSwarmBridge(
                swarm_engine=self.swarm_engine,
                context_manager=None,  # Context manager is per-task, set dynamically
            )
            self.logger.debug("SwarmBridge wired to ToolManager for swarm_delegate tool")
        else:
            self.swarm_engine = None

        # V7 Sprint 10: Telemetry for metrics tracking
        if getattr(self.config, "telemetry_enabled", True):
            self.telemetry = TelemetryCollector(self.config)
            self.logger.debug("TelemetryCollector initialized", {"output_file": str(self.telemetry.output_file)})
        else:
            self.telemetry = None

        # V7.5 HIVE MIND: Auto-Memory for learning from task history
        self.auto_memory = get_auto_memory(workspace_path)
        self._current_task_start: float = 0
        self._current_task_type: str = "unknown"
        self._current_task_description: str = ""
        self._current_swarm_mode: str = "brainstorming"
        self.logger.debug("AutoMemory initialized", {"memory_dir": str(self.auto_memory.memory_dir)})

        # P5.1 Phase 1: GuardPipeline for security validation
        self.guard_pipeline = GuardPipeline()

        # P5.1 Phase 2: TaskRouter for routing logic
        from core.execution_pkg.orchestration.task_router import TaskRouter

        self.task_router = TaskRouter()

        # P5.1 Phase 3: ResultHandler for result creation and validation
        from core.execution_pkg.orchestration.result_handler import ResultHandler

        self.result_handler = ResultHandler(self)

        # P5.1 Phase 4: StateHandler for FSM state management
        from core.execution_pkg.orchestration.state_handler import StateHandler

        self.state_handler = StateHandler(self)

        # V9.4 ISSUE-003: Sync bridge for HiveMind/Swarm state synchronization
        from core.execution_pkg.orchestration.sync_bridge import get_sync_bridge

        self._sync_bridge = get_sync_bridge()
        self._sync_bridge._workspace = self.workspace_path
        # Wire up swarm session manager if available
        if self.swarm_engine and hasattr(self.swarm_engine, "session_manager"):
            self._sync_bridge.set_session_manager(self.swarm_engine.session_manager)

        # V7.8 Phase 10c: Project Memory RAG
        # Stored at NEXUS_ROOT/.nexus/ (persists across /workspace new)
        nexus_root = workspace_path.parent if workspace_path.name == "workspace" else workspace_path
        self.project_memory = ProjectMemory(nexus_root)

        # V12.4.1: FSM Snapshot Manager for fast crash recovery (<500ms)
        # Creates periodic snapshots of FSM state every 100 events
        # Recovery: Load snapshot + replay delta events (vs replaying all events)
        from core.fsm.event_sourcing import get_event_store
        from core.fsm.snapshot_manager import get_snapshot_manager

        self._event_store = get_event_store(workspace_path)
        self._snapshot_manager = get_snapshot_manager(
            workspace_path,
            snapshot_interval=100,  # Snapshot every 100 FSM transitions
        )
        self._event_count = len(self._event_store.replay())  # Count existing events
        self.logger.debug(
            "FSM Snapshot Manager initialized",
            {
                "event_count": self._event_count,
                "snapshot_interval": 100,
                "snapshot_stats": self._snapshot_manager.get_snapshot_stats(),
            },
        )

        # V7.8 Phase 15: Agent-as-Tool Registry (Vision Fractale)
        # Exposes spawned agents as callable tools for fractal invocation
        self.agent_tool_registry = AgentToolRegistry(
            workspace_path=self.workspace_path,
            agent_pool=self.agent_pool,
            agent_invoker=self.agent_invoker,
            agent_loader=self.spawned_agent_loader,
        )
        # Refresh to discover existing spawned agents
        agent_tools_count = self.agent_tool_registry.refresh()
        if agent_tools_count > 0:
            # Register agent tools with ToolManager
            self.agent_tool_registry.register_with_tool_manager(self.tool_manager)
            self.logger.info(
                "Agent-as-Tool enabled",
                {
                    "agent_tools": agent_tools_count,
                    "tools": [t.tool_name for t in self.agent_tool_registry.list_agent_tools()],
                },
            )

        self.logger.debug(
            "OrchestratorV7 initialized",
            {
                "gemini_model": gemini_info.get("model"),
                "claude_model": claude_info.get("model"),
                "agent_metrics": self.config.agent_metrics_enabled,
                "swarm_enabled": self.swarm_engine is not None,
                "telemetry_enabled": self.telemetry is not None,
                "auto_memory": True,
                "project_memory": self.project_memory.get_stats().total_chunks,
            },
        )

    # =========================================================================
    # V9.3: Thread-Safe Agent Tracking via Immutable Context
    # =========================================================================
    # CRITICAL FIX (ISSUE-001): Replaced mutable self.active_agent string with
    # immutable TaskExecutionContext to prevent race conditions in PARALLEL mode.
    #
    # Before V9.3:
    #   self.active_agent = "gemini"  # Mutable! Race condition in parallel!
    #   self.active_agent = self._registry.get_alternate(...)  # No lock!
    #
    # After V9.3:
    #   self._task_context.current_agent  # Immutable read
    #   self._task_context = self._task_context.with_agent(...)  # New immutable copy
    #
    # The @property below provides backward compatibility - existing code using
    # `self.active_agent` continues to work but is now thread-safe.
    # =========================================================================

    @property
    def active_agent(self) -> str:
        """
        V9.3: Thread-safe read of current agent via immutable context.

        Returns:
            Current agent ID (lowercase: "gemini" or "claude")
        """
        return self._task_context.current_agent

    @active_agent.setter
    def active_agent(self, agent: str):
        """
        V9.3: Thread-safe agent swap via immutable context replacement.

        Creates a new immutable context with the new agent.
        This is atomic - no intermediate state where agent is undefined.

        Args:
            agent: New agent ID (will be normalized to lowercase)
        """
        normalized = agent.lower() if agent else "gemini"
        self._task_context = self._task_context.with_agent(normalized)

    def _build_execution_context(self, objective: str = "") -> TaskExecutionContext:
        """
        Build a TaskExecutionContext from current orchestrator state.

        V7.5 Phase 0d: Creates immutable context for thread-safe execution.
        Use this in parallel/swarm modes instead of self.active_agent.

        Args:
            objective: Task objective for the context

        Returns:
            Immutable TaskExecutionContext
        """
        return TaskExecutionContext.create(
            objective=objective or self.blackboard.get("objective", ""), initial_agent=self.active_agent
        )

    @property
    def current_context(self) -> TaskExecutionContext:
        """
        Get current task context.

        V9.3: Now always returns the internal context (never None).
        """
        return self._task_context

    def _sync_context_agent(self, context: TaskExecutionContext):
        """
        Replace current context with new one.

        V9.3: Simply replaces the immutable context reference.
        The active_agent property now reads from this context.

        Args:
            context: New TaskExecutionContext to use
        """
        self._task_context = context

    # =========================================================================
    # Model Routing & Agent Drivers
    # =========================================================================

    # === Project Context Methods (Sprint 11) ===

    def check_project_context(self, project_path: Path | None = None) -> dict:
        """
        Check project context and suggest bootstrap if NEXUS.md is missing.

        V7 Sprint 11: AutoBootstrap integration

        Args:
            project_path: Path to check (defaults to workspace parent)

        Returns:
            {
                "has_nexus_md": bool,
                "project_path": str,
                "suggestion": Optional[str],
                "tech_hint": Optional[str]  # Quick detected stack
            }
        """
        # Default to parent of workspace (typically project root)
        if project_path is None:
            project_path = self.workspace_path.parent

        nexus_md_path = project_path / "NEXUS.md"
        has_nexus_md = nexus_md_path.exists()

        result = {
            "has_nexus_md": has_nexus_md,
            "project_path": str(project_path),
            "suggestion": None,
            "tech_hint": None,
        }

        if not has_nexus_md:
            result["suggestion"] = (
                f"No NEXUS.md found in {project_path}. Use /bootstrap to auto-generate project context."
            )

            # Quick tech detection
            tech_hints = []
            if (project_path / "pyproject.toml").exists() or (project_path / "requirements.txt").exists():
                tech_hints.append("Python")
            if (project_path / "package.json").exists():
                tech_hints.append("JavaScript/Node")
            if (project_path / "Cargo.toml").exists():
                tech_hints.append("Rust")
            if (project_path / "go.mod").exists():
                tech_hints.append("Go")

            if tech_hints:
                result["tech_hint"] = f"Detected: {', '.join(tech_hints)}"

        self.logger.debug("Project context check", result)
        return result

    def get_startup_hints(self) -> list:
        """
        Get startup hints for REPL display.

        Returns list of hint strings to show user on startup.
        """
        hints = []

        # Check project context
        ctx = self.check_project_context()
        if not ctx["has_nexus_md"]:
            if ctx["tech_hint"]:
                hints.append(f"📦 {ctx['tech_hint']}")
            hints.append("💡 Tip: Use /bootstrap to generate project context (NEXUS.md)")

        # Swarm status
        if self.swarm_engine:
            hints.append("🐝 Hybrid Swarm Engine: enabled")

        return hints

    def process_turn(self, user_input: str | None = None) -> dict:
        """
        Process un tour de l'orchestration

        Args:
            user_input: Input utilisateur (si état == IDLE)

        Returns:
            {
                "state": str,
                "output": str,
                "agent": str,
                "finished": bool,
                "error": Optional[str]
            }
        """
        self.iteration += 1

        # KERNEL RUNTIME INTEGRITY CHECK (every 100 iterations)
        # As per KERNEL.py specification: verify invariants haven't been tampered in memory
        if KERNEL_AVAILABLE and self.iteration % 100 == 0:
            self.logger.info("Running KERNEL runtime integrity check", {"iteration": self.iteration})
            if not runtime_integrity_check():
                self.logger.critical("KERNEL INTEGRITY VIOLATION - Shutting down!")
                self.state_handler.transition_to(OrchestratorState.PANIC)
                return self.result_handler.make_result(
                    "PANIC",
                    "[SECURITY VIOLATION] KERNEL runtime integrity check FAILED. "
                    "Invariants may have been modified in memory. Immediate shutdown required.",
                    None,
                    True,
                    error="KERNEL_INTEGRITY_VIOLATION",
                )

        # V12.4: Memory pressure monitoring (periodic, every 25 iterations)
        if self.iteration % 25 == 0:
            try:
                from core.memory_pkg.memory.memory_pressure_monitor import get_pressure_monitor

                monitor = get_pressure_monitor()
                history_len = len(self.blackboard.get("recent_history", []))
                bb_bytes = len(json.dumps(self.blackboard, default=str))
                monitor.record_snapshot(
                    cache_items=0,
                    cache_bytes=0,
                    blackboard_bytes=bb_bytes,
                    conversation_turns=history_len,
                    total_bytes=bb_bytes,
                    max_bytes=4_000_000,  # ~4MB soft limit
                )
                level = monitor.get_pressure_level()
                if level.level == "critical":
                    self.logger.warning(
                        "Memory pressure critical",
                        {"utilization": level.utilization, "recommendation": level.recommendation},
                    )
                elif level.level == "warning":
                    self.logger.info("Memory pressure elevated", {"utilization": level.utilization})
            except Exception:
                pass  # Non-blocking advisory check

        # P5.1: INPUT GUARD - Prompt Injection Prevention (OWASP LLM01:2025)
        # Extracted to GuardPipeline for modularity
        guard_result = self.guard_pipeline.validate_input(user_input, self.state)
        if self.guard_pipeline.should_block(guard_result):
            return self.result_handler.make_result(
                self.state.name,
                f"[SECURITY] Input blocked: {guard_result.reason}. "
                "Your request was flagged as a potential prompt injection attack.",
                None,
                False,
                error="PROMPT_INJECTION_BLOCKED",
            )

        # V7.8 Phase 14c.2d: FSM State Dispatcher
        state_handlers = {
            OrchestratorState.IDLE: lambda: self.fsm_handlers.handle_idle(user_input),
            OrchestratorState.WAITING_USER: lambda: self.fsm_handlers.handle_waiting_user(user_input),
            OrchestratorState.BRAINSTORMING: self.fsm_handlers.handle_brainstorming,
            OrchestratorState.EXECUTING_TOOL: self.fsm_handlers.handle_executing_tool,
            OrchestratorState.VALIDATING_CFL: self.fsm_handlers.handle_validating_cfl,
            OrchestratorState.EVOLUTION_BRAINSTORM: lambda: self.fsm_handlers.handle_evolution_brainstorm(user_input),
            OrchestratorState.SWARM_ANALYZING: self.fsm_handlers.handle_swarm_analyzing,
            OrchestratorState.SWARM_NEGOTIATING: self.fsm_handlers.handle_swarm_negotiating,
            OrchestratorState.SWARM_EXECUTING: self.fsm_handlers.handle_swarm_executing,
            OrchestratorState.ERROR: self.fsm_handlers.handle_error,
            OrchestratorState.PANIC: self.fsm_handlers.handle_panic,
        }

        handler = state_handlers.get(self.state)
        if handler:
            return handler()

        return self.result_handler.make_result(
            "ERROR", f"Unknown state: {self.state}", None, False, error="UNKNOWN_STATE"
        )

    # =========================================================================
    # V9 CYBORG: Async Process Turn
    # =========================================================================

    async def process_turn_async(self, user_input: str | None = None) -> dict:
        """
        V9 Cyborg Async version of process_turn().

        Uses async drivers for LLM calls, enabling:
        - Non-blocking I/O (event loop free during generation)
        - Streaming token output
        - Graceful cancellation via CancellationToken

        Falls back to sync handlers for non-LLM operations.

        Args:
            user_input: Input utilisateur (si état == IDLE)

        Returns:
            Same result dict as process_turn()
        """
        self.iteration += 1

        # KERNEL RUNTIME INTEGRITY CHECK (every 100 iterations) - sync is OK, fast
        if KERNEL_AVAILABLE and self.iteration % 100 == 0:
            self.logger.info("Running KERNEL runtime integrity check", {"iteration": self.iteration})
            if not runtime_integrity_check():
                self.logger.critical("KERNEL INTEGRITY VIOLATION - Shutting down!")
                self.state_handler.transition_to(OrchestratorState.PANIC)
                return self.result_handler.make_result(
                    "PANIC",
                    "[SECURITY VIOLATION] KERNEL runtime integrity check FAILED.",
                    None,
                    True,
                    error="KERNEL_INTEGRITY_VIOLATION",
                )

        # P5.1: INPUT GUARD - Prompt Injection Prevention (async path)
        # Extracted to GuardPipeline for modularity
        guard_result = self.guard_pipeline.validate_input(user_input, self.state)
        if self.guard_pipeline.should_block(guard_result):
            return self.result_handler.make_result(
                self.state.name,
                f"[SECURITY] Input blocked: {guard_result.reason}",
                None,
                False,
                error="PROMPT_INJECTION_BLOCKED",
            )

        # P5.1 Phase 2: FAST PATH - Bypass HiveMind for trivial inputs
        # Extracted to TaskRouter for modularity
        if (
            user_input
            and self.state in (OrchestratorState.IDLE, OrchestratorState.WAITING_USER)
            and self.task_router.is_fast_path(user_input)
        ):
            self.logger.debug("Fast path activated (trivial input)", {"input_length": len(user_input)})

            # Get direct response from TaskRouter
            response = self.task_router.handle_fast_path(user_input)
            self.state_handler.transition_to(OrchestratorState.WAITING_USER)

            return self.result_handler.make_result(self.state.name, response, None, False, metadata={"fast_path": True})

        # States that benefit from async LLM calls
        async_states = {
            OrchestratorState.BRAINSTORMING,
            OrchestratorState.VALIDATING_CFL,
        }

        if self.state in async_states:
            return await self._handle_async_state(user_input)
        else:
            # Non-LLM states: use sync handlers (fast, no I/O blocking)
            return self.process_turn(user_input)

    async def _handle_async_state(self, user_input: str | None = None) -> dict:
        """
        Handle states that require async LLM invocation.

        Uses AsyncDriverFactory to get async drivers with streaming.
        Falls back to sync if factory not available.
        """
        try:
            from core.drivers.async_factory import get_driver_factory

            factory = get_driver_factory()
        except ImportError:
            factory = None

        if not factory:
            # Fallback: no async factory, use sync path
            return self.process_turn(user_input)

        if self.state == OrchestratorState.BRAINSTORMING:
            return await self._handle_brainstorming_async(factory, user_input)
        elif self.state == OrchestratorState.VALIDATING_CFL:
            return await self._handle_cfl_async(factory)
        else:
            return self.process_turn(user_input)

    async def _handle_brainstorming_async(self, factory, user_input: str | None) -> dict:
        """
        Async brainstorming with streaming output.

        Streams tokens in real-time to console while building response.
        """
        # Build context using sync method (fast, no I/O)
        context = self.context_builder.build_context(
            history=self.memory.history,
            blackboard=self.blackboard,
            active_agent=self.active_agent,
            current_task=self.current_task,
            objective=self.objective,
        )

        session_uuid = f"brain_{self.iteration}"

        try:
            if self.active_agent == "claude":  # V9.3: lowercase normalized
                # V12.4: Use SDK-first driver (auto-selects SDK or CLI)
                driver = factory.get_best_claude()
                response_parts = []

                # V9: Stream tokens in real-time
                async for token in driver.invoke_stream(
                    context, session_uuid=session_uuid, on_token=lambda t: print(t, end="", flush=True)
                ):
                    response_parts.append(token)

                print()  # Newline after streaming
                full_response = "".join(response_parts)
                response = driver._parse_hybrid_response(full_response)
            else:
                # Gemini - V12.4: Use SDK-first driver
                driver = factory.get_best_gemini()
                response_parts = []

                async for token in driver.invoke_stream(
                    context, session_uuid=session_uuid, on_token=lambda t: print(t, end="", flush=True)
                ):
                    response_parts.append(token)

                print()
                full_response = "".join(response_parts)
                response = driver._parse_response(full_response)

            # Process response with existing FSM logic
            return self.fsm_handlers._process_brainstorming_response(response)

        except asyncio.CancelledError:
            self.logger.warning("Brainstorming cancelled by user")
            return self.result_handler.make_result("IDLE", "Task cancelled by user", self.active_agent, True)

        except Exception as e:
            self.logger.error(f"Async brainstorming error: {e}")
            # Fallback to sync on error
            return self.fsm_handlers.handle_brainstorming()

    async def _handle_cfl_async(self, factory) -> dict:
        """
        Async CFL (Cognitive Feedback Loop) validation.

        Uses shorter timeout for CFL validation responses.
        """
        # Build CFL context
        context = self.context_builder.build_cfl_context(
            history=self.memory.history,
            blackboard=self.blackboard,
            active_agent=self.active_agent,
            tool_result=self.blackboard.get("last_tool_result"),
        )

        session_uuid = f"cfl_{self.iteration}"

        try:
            if self.active_agent == "claude":  # V9.3: lowercase normalized
                # V12.4: Use SDK-first driver (auto-selects SDK or CLI)
                driver = factory.get_best_claude()
                # CFL needs faster response - use non-streaming
                response = await asyncio.wait_for(driver.invoke(context, session_uuid=session_uuid), timeout=30.0)
            else:
                # V12.4: Use SDK-first driver
                driver = factory.get_best_gemini()
                response = await asyncio.wait_for(driver.invoke(context, session_uuid=session_uuid), timeout=30.0)

            return self.fsm_handlers._process_cfl_response(response)

        except TimeoutError:
            self.logger.warning("CFL validation timed out, falling back to sync")
            return self.fsm_handlers.handle_validating_cfl()

        except asyncio.CancelledError:
            self.logger.warning("CFL cancelled by user")
            return self.result_handler.make_result("IDLE", "Task cancelled by user", self.active_agent, True)

        except Exception as e:
            self.logger.error(f"Async CFL error: {e}")
            # Fallback to sync on error
            return self.fsm_handlers.handle_validating_cfl()

    # =========================================================================
    # Helper Methods (Called by FSMHandlers via self._orch)
    # =========================================================================
    # DELETED ~660 lines of inline state handling code
    # Now delegated to FSMHandlers (core/orchestration/fsm_handlers.py)

    def _build_simple_context(self, user_input: str, task_analysis: TaskAnalysis) -> str:
        """Build lightweight context for SIMPLE task. V7.8: Delegates to ContextBuilder."""
        return self.context_builder.build_simple_context(user_input, task_analysis)

    def _detect_mutation_complete(self, content: str) -> bool:
        """Detect valid mutation proposal. V7.8: Delegates to MutationDetector."""
        return self.mutation_detector.detect_mutation_complete(content)

    def _handle_stagnation(self) -> dict:
        """Handle stagnation détectée"""
        stagnation_msg = self.stagnation_detector.get_stagnation_message()

        # Force Gemini to decide (V8.4.0: use normalized ID)
        self.active_agent = "gemini"
        self.stagnation_detector.reset()

        return self.result_handler.make_result(
            "BRAINSTORMING", stagnation_msg, "Gemini", False, error="STAGNATION"
        )

    def _handle_error(self, error_msg: str) -> dict:
        """Handle recoverable error"""
        self.state_handler.transition_to(OrchestratorState.ERROR)
        return self.result_handler.make_result("ERROR", f"[ERROR] {error_msg}", None, False, error=error_msg)

    def _trigger_panic(self, reason: str) -> dict:
        """Trigger panic state"""
        self.state_handler.transition_to(OrchestratorState.PANIC)
        return self.result_handler.make_result("PANIC", f"[PANIC] {reason}", None, True, error=reason)

    def _calculate_quality_score(self, message: dict, validation_ok: bool, is_stagnant: bool) -> float:
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

    def _record_invocation(
        self,
        agent_name: str,
        task_type: str,
        success: bool,
        duration: float,
        quality_score: float = 0.5,
        response_text: str | None = None,
    ):
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
        if not self.agent_pool:
            return

        # V8.4.0: Use registry for agent identification
        agent_id = "gemini_primary" if self._registry.is_gemini(agent_name) else "claude_opus"

        # Count tokens using tiktoken (accurate) or fallback to estimate
        estimated_tokens = 500  # Default estimate
        if response_text:
            try:
                encoding = tiktoken.get_encoding("cl100k_base")
                estimated_tokens = len(encoding.encode(response_text))
            except Exception as e:
                # Fallback: rough estimate (1 token ≈ 4 chars)
                self.logger.debug("tiktoken encoding failed, using estimate: %s", e)
                estimated_tokens = len(response_text) // 4

        invocation = AgentInvocationResult(
            agent_id=agent_id,
            task_type=task_type,
            success=success,
            quality_score=quality_score,
            tokens_used=estimated_tokens,
            time_seconds=duration,
        )
        self.agent_pool.record_invocation(invocation)

        self.logger.debug(
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

    def _build_context(self) -> str:
        """Build context markdown for agent. V7.8: Delegates to ContextBuilder."""
        return self.context_builder.build_context()

    def _build_context_with_tool_result(self) -> str:
        """Build CFL validation context. V7.8: Delegates to ContextBuilder."""
        return self.context_builder.build_context_with_tool_result()

    def _format_tool_result(self, result) -> str:
        """Format tool result for display. P5.1: Delegates to ResultHandler."""
        return self.result_handler.format_tool_result(result)

    def _validate_message(self, response: dict, expect_heavy: bool = False) -> dict:
        """Validate and parse message with Pydantic V2. P5.1: Delegates to ResultHandler."""
        return self.result_handler.validate_message(response, expect_heavy)

    def reset_to_idle(self, clear_task: bool = True):
        """Reset orchestrator to IDLE. P5.1: Delegates to StateHandler."""
        return self.state_handler.reset_to_idle(clear_task)

    def _transition_to(self, new_state):
        """Transition to new FSM state. P5.1: Delegates to StateHandler for backward compatibility."""
        return self.state_handler.transition_to(new_state)

    def _make_result(
        self,
        state: str,
        output: str | None,
        agent: str | None,
        finished: bool,
        error: str | None = None,
        tool: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        """Create result dict. P5.1: Delegates to ResultHandler for backward compatibility."""
        return self.result_handler.make_result(state, output, agent, finished, error, tool, metadata)

    def get_system_status(self) -> dict:
        """Get comprehensive system status (for /status command)"""
        current_plan = self.blackboard.get("strategic_plan", [])
        plan_health = self.plan_health.check_health(current_plan, self.iteration)
        panic_status = self.panic_system.get_status()

        return {
            "state": self.state.name,  # V9.1: Use "state" for consistency with process_turn()
            "fsm_state": self.state.name,  # V9.1: Keep for backward compatibility
            "active_agent": self.active_agent,
            "iteration": self.iteration,
            "stalemate_counter": self.stalemate_counter,
            "json_parse_failures": self.json_parse_failures,
            "plan_health": plan_health,
            "panic_system": panic_status,
            "stagnation": {
                "is_stagnant": self.stagnation_detector.is_stagnant(),
                "window_size": self.stagnation_detector.window_size,
            },
            "backups": {
                "available": len(self.memory.list_backups()),
                "latest": self.memory.list_backups()[0] if self.memory.list_backups() else None,
            },
            "swarm": {
                "enabled": self.swarm_engine is not None,
                "stats": self.swarm_engine.get_stats() if self.swarm_engine else None,
            },
        }

    def rollback_to_backup(self, backup_file: Path = None) -> bool:
        """
        Rollback to previous state (for /rollback command)

        Args:
            backup_file: Specific backup to restore (None = latest)

        Returns:
            True if successful
        """
        # Create backup before rollback (in case user wants to undo)
        self.memory.create_backup(reason="before_rollback")

        # Restore from backup
        if self.memory.restore_from_backup(backup_file):
            # Reload blackboard reference
            self.blackboard = self.memory.blackboard

            # Reset to IDLE but keep restored task
            self.reset_to_idle(clear_task=False)

            return True
        return False

    # =========================================================================
    # V11.2 MEMORIA: Memory Consolidation
    # =========================================================================

    def consolidate_memory(self) -> dict:
        """
        V11.2 MEMORIA: Consolidate episodic patterns into procedural memory.

        Scans SuccessMemory for recurring patterns by domain and logs
        insights that can be used to improve AutoMemory suggestions.

        Should be called periodically (e.g., end of session or every N tasks).

        Returns:
            Dict with consolidation results
        """
        results = {"success": False, "patterns_found": 0, "message": ""}

        # Try to access MemoryCoordinator through SwarmEngine's ModeSelector
        coordinator = None
        if self.swarm_engine and hasattr(self.swarm_engine, "mode_selector"):
            mode_selector = self.swarm_engine.mode_selector
            if hasattr(mode_selector, "memory_coordinator") and mode_selector.memory_coordinator:
                coordinator = mode_selector.memory_coordinator

        if not coordinator:
            results["message"] = "MemoryCoordinator not available (cold start or disabled)"
            self.logger.debug("[MEMORIA] Consolidation skipped - no coordinator")
            return results

        try:
            patterns = coordinator.consolidate()
            results["success"] = True
            results["patterns_found"] = patterns
            results["message"] = f"Consolidated {patterns} patterns from episodic to procedural memory"
            self.logger.info("[MEMORIA] Memory consolidation completed", {"patterns": patterns})
        except Exception as e:
            results["message"] = f"Consolidation failed: {e}"
            self.logger.warning(f"[MEMORIA] Consolidation error: {e}")

        return results

    def start_swarm_mode(self, objective: str, force_mode: CollaborationMode | None = None) -> dict:
        """Start Hybrid Swarm mode. V7.8: Delegates to SwarmBridge."""
        return self.swarm_bridge.start_swarm_mode(objective, force_mode)

    def process_with_swarm(
        self,
        task_input: str,
        force_mode: CollaborationMode | None = None,
        skip_negotiation: bool = False,
        on_negotiation_turn: Callable | None = None,
        on_execution_round: Callable | None = None,
    ) -> dict:
        """Process task with swarm. V7.8: Delegates to SwarmBridge."""
        return self.swarm_bridge.process_with_swarm(
            task_input, force_mode, skip_negotiation, on_negotiation_turn, on_execution_round
        )
