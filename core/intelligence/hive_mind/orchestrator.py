"""
NEXUS V8.0 - TRUE HIVE MIND Orchestrator

Main coordinator for the 7-phase Hive Mind pipeline.
Entry point called by FSMHandlers when complexity >= MODERATE.

Usage:
    hive_mind = TrueHiveMind(
        workspace_path=workspace_path,
        config=config,
        gemini_driver=gemini_driver,
        claude_driver=claude_driver,
        agent_pool=agent_pool,  # Existing V7 AgentPool
        budget_tracker=budget_tracker,  # Existing V7 BudgetTracker
        project_memory=project_memory  # Existing V7 ProjectMemory
    )

    result = await hive_mind.process_task("Complex task here")
"""

import contextlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.intelligence.swarm.hybrid_swarm_engine import HybridSwarmEngine
    from core.memory_pkg.memory import SuccessMemory

# V9.4 ISSUE-003: Sync bridge for HiveMind/Swarm state synchronization
from core.execution_pkg.orchestration.sync_bridge import OrchestratorSyncBridge, get_sync_bridge

# V8.0.1: Hot-Swap Lead Agent
from core.fsm.stagnation_detector import StagnationDetector

# V10 SYNAPSE: Telemetry instrumentation
from core.observability.events.telemetry_bridge import get_telemetry_bridge
from core.observability.events.types import CerebroEventType

from .adaptive_debate import AdaptiveDebateConfig, TaskComplexity
from .agent_registry import AgentRegistry

# V12.4: Phase budget allocation (TALE, arxiv:2412.18547)
from .budget_allocator import PhaseBudgetAllocator

# V12.4: Stepwise confidence monitoring (arxiv:2511.07364)
from .confidence_monitor import StepwiseConfidenceMonitor
from .context_manager import HiveMindContextManager
from .cost_estimator import CostEstimator

# V12.4: Phase audit logging for decision tracking
from .phase_audit_logger import get_phase_audit_logger
from .phases import (
    AdaptiveRetryPhase,
    ArchitectureGenerationPhase,
    FailureDiagnosisPhase,
    IndependentAnalysisPhase,
    KnowledgeConsolidationPhase,
    MonitoredExecutionPhase,
    StrategicDebatePhase,
)

# V8.4.4b: SagaManager for checkpoint/rollback
from .saga_manager import SagaManager
from .strategy_blacklist import StrategyBlacklist
from .types import HiveMindState
from .user_interaction import UserInteractionHandler

if TYPE_CHECKING:
    from core.drivers.protocol import BaseAsyncDriver
    from core.intelligence.swarm import AgentPool
    from core.memory_pkg.memory import ProjectMemory
    from core.observability.telemetry import BudgetTracker

logger = logging.getLogger(__name__)


@dataclass
class HiveMindResult:
    """Result of a Hive Mind task execution."""

    success: bool
    output: str
    state: HiveMindState
    phases_completed: list
    total_duration: float
    total_tokens: int
    agents_used: list
    agents_spawned: list
    artifacts_created: list
    knowledge_archived: int
    error: str | None = None


class TrueHiveMind:
    """
    TRUE HIVE MIND V8.0 Orchestrator

    Coordinates the 7-phase pipeline for complex tasks.
    Integrates with existing V7 components.
    """

    def __init__(
        self,
        workspace_path: Path,
        config: Any,
        gemini_driver: "BaseAsyncDriver",
        claude_driver: "BaseAsyncDriver",
        agent_pool: "AgentPool" = None,
        budget_tracker: "BudgetTracker" = None,
        project_memory: "ProjectMemory" = None,
        success_memory: "SuccessMemory" = None,  # V8.2.0
        on_state_change: callable = None,
        auto_breakpoints: bool = True,
        swarm_engine: "HybridSwarmEngine" = None,  # V8.4.5: SwarmBridge wiring fix
        saga_enabled: bool = True,  # V8.4.4b: Enable Saga checkpointing
    ):
        """
        Initialize TRUE HIVE MIND.

        Args:
            workspace_path: NEXUS workspace path
            config: NEXUS configuration
            gemini_driver: Gemini driver instance
            claude_driver: Claude driver instance
            agent_pool: Existing V7 AgentPool (for DyLAN metrics)
            budget_tracker: Existing V7 BudgetTracker (for USD limits)
            project_memory: Existing V7 ProjectMemory (for RAG)
            success_memory: V8.2.0 SuccessMemory (for learning from successes)
            on_state_change: Callback for state changes
            auto_breakpoints: Enable user breakpoints
            swarm_engine: V8.4.5 - Optional Swarm Engine for Phase 4 delegation
        """
        self.workspace_path = Path(workspace_path)
        self.config = config
        self.gemini = gemini_driver
        self.claude = claude_driver
        self.agent_pool = agent_pool
        self.budget_tracker = budget_tracker
        self.project_memory = project_memory
        self.success_memory = success_memory  # V8.2.0
        self.on_state_change = on_state_change
        self.auto_breakpoints = auto_breakpoints
        self.swarm_engine = swarm_engine  # V8.4.5: SwarmBridge wiring
        self.saga_enabled = saga_enabled  # V8.4.4b: Must set BEFORE _init_components()

        # Current state
        self.state = HiveMindState.HIVE_GATING
        self._current_task: str = ""

        # Initialize V8 components
        self._init_components()

        logger.info(
            "TrueHiveMind V8.0 initialized",
            extra={"workspace": str(workspace_path), "breakpoints_enabled": auto_breakpoints},
        )

    def _init_components(self):
        """Initialize Hive Mind components."""
        # Budget: Get limit from config or default
        budget_limit = getattr(self.config, "hive_mind_budget_limit", 50000)

        # Core components
        self.cost_estimator = CostEstimator(budget_limit=budget_limit)
        self.context_manager = HiveMindContextManager(max_tokens=budget_limit)
        self.agent_registry = AgentRegistry(self.workspace_path)
        self.strategy_blacklist = StrategyBlacklist(self.workspace_path)
        self.debate_config = AdaptiveDebateConfig()

        # V8.0.1: Hot-Swap Lead Agent support
        self.stagnation_detector = StagnationDetector(
            similarity_threshold=0.8, window_size=3, strategy_blacklist=self.strategy_blacklist
        )
        self._current_lead = "gemini"  # Default lead agent
        self._lead_swap_count = 0

        # User interaction
        self.user_handler = UserInteractionHandler(
            default_timeout=getattr(self.config, "hive_mind_breakpoint_timeout", 60),
            enable_rich=True,
            auto_accept=not self.auto_breakpoints,
        )

        # V8.4.4b: SagaManager for checkpoint/rollback (saga_enabled set in __init__)
        self._saga: SagaManager | None = None
        self._spawned_agents: list[str] = []

        # V9.4 ISSUE-003: Sync bridge for HiveMind/Swarm state synchronization
        self._sync_bridge: OrchestratorSyncBridge = get_sync_bridge()
        self._sync_bridge._workspace = self.workspace_path
        # Wire up swarm session manager if available
        if self.swarm_engine and hasattr(self.swarm_engine, "session_manager"):
            self._sync_bridge.set_session_manager(self.swarm_engine.session_manager)

        # V12.4: Stepwise confidence monitor
        self.confidence_monitor = StepwiseConfidenceMonitor()

        # V12.4: Phase budget allocator (TALE-inspired dynamic budgeting)
        self.budget_allocator = PhaseBudgetAllocator(
            total_budget=budget_limit,
        )

        # V12.4: System introspector - register HiveMind components
        try:
            from core.meta.system_introspector import get_introspector

            self._introspector = get_introspector()
            self._introspector.register_component(
                "hive_mind_orchestrator",
                category="orchestration",
                version="12.4",
                description="TRUE HIVE MIND 7-phase pipeline orchestrator",
                capabilities=["analysis", "debate", "architecture", "execution", "diagnosis", "retry", "consolidation"],
            )
        except Exception:
            self._introspector = None

        # V12.4: FailoverManager - register drivers for resilient routing
        self._failover = None
        try:
            from core.drivers.failover_manager import get_failover_manager

            self._failover = get_failover_manager()
            if not self._failover._configs:  # Only register once
                self._failover.register_driver("gemini", priority=0)
                self._failover.register_driver("claude", priority=1)
        except Exception:
            pass

        # V12.4: ResourceOptimizer - register models for cost-aware routing
        self._resource_optimizer = None
        try:
            from core.execution_pkg.routing.resource_optimizer import get_resource_optimizer

            self._resource_optimizer = get_resource_optimizer()
            if not self._resource_optimizer._models:
                self._resource_optimizer.register_model(
                    "gemini-3-pro",
                    cost_per_1k_input=0.00125,
                    cost_per_1k_output=0.005,
                    avg_latency_ms=800,
                    quality_score=0.85,
                )
                self._resource_optimizer.register_model(
                    "claude-opus-4",
                    cost_per_1k_input=0.015,
                    cost_per_1k_output=0.075,
                    avg_latency_ms=1200,
                    quality_score=0.95,
                )
                self._resource_optimizer.register_model(
                    "claude-sonnet-4",
                    cost_per_1k_input=0.003,
                    cost_per_1k_output=0.015,
                    avg_latency_ms=600,
                    quality_score=0.88,
                )
        except Exception:
            pass

        # Initialize phases
        self._init_phases()

    def _init_phases(self):
        """Initialize all 7 phases."""
        # Phase 1: Independent Analysis
        # V12.4.1 Epic 1.4: Pass workspace_path for V2 memory access
        self.phase_analysis = IndependentAnalysisPhase(
            gemini_driver=self.gemini,
            claude_driver=self.claude,
            cost_estimator=self.cost_estimator,
            context_manager=self.context_manager,
            workspace_path=self.workspace_path,
        )

        # Phase 2: Strategic Debate
        self.phase_debate = StrategicDebatePhase(
            gemini_driver=self.gemini,
            claude_driver=self.claude,
            cost_estimator=self.cost_estimator,
            context_manager=self.context_manager,
            debate_config=self.debate_config,
        )

        # Phase 3: Architecture Generation
        self.phase_architecture = ArchitectureGenerationPhase(
            gemini_driver=self.gemini,
            claude_driver=self.claude,
            cost_estimator=self.cost_estimator,
            context_manager=self.context_manager,
            agent_registry=self.agent_registry,
            user_handler=self.user_handler,
            workspace_path=self.workspace_path,
        )

        # Phase 4: Monitored Execution
        # V8.4.5: Pass swarm_engine for SwarmBridge delegation (Dictator Mode)
        self.phase_execution = MonitoredExecutionPhase(
            gemini_driver=self.gemini,
            claude_driver=self.claude,
            cost_estimator=self.cost_estimator,
            context_manager=self.context_manager,
            swarm_engine=self.swarm_engine,
        )

        # Phase 5: Failure Diagnosis
        self.phase_diagnosis = FailureDiagnosisPhase(
            gemini_driver=self.gemini,
            claude_driver=self.claude,
            cost_estimator=self.cost_estimator,
            context_manager=self.context_manager,
            user_handler=self.user_handler,
        )

        # Phase 6: Adaptive Retry
        self.phase_retry = AdaptiveRetryPhase(
            cost_estimator=self.cost_estimator, context_manager=self.context_manager, blacklist=self.strategy_blacklist
        )

        # Phase 7: Knowledge Consolidation
        # V12.4.1 Epic 1.4: Pass workspace_path for V2 memory recording
        self.phase_consolidation = KnowledgeConsolidationPhase(
            gemini_driver=self.gemini,
            claude_driver=self.claude,
            cost_estimator=self.cost_estimator,
            context_manager=self.context_manager,
            agent_registry=self.agent_registry,
            user_handler=self.user_handler,
            project_memory=self.project_memory,
            workspace_path=self.workspace_path,
        )

    def _set_state(self, new_state: HiveMindState):
        """Change state and notify."""
        old_state = self.state
        self.state = new_state
        logger.debug(f"State: {old_state.value} -> {new_state.value}")

        # V10 SYNAPSE: Emit state change telemetry
        get_telemetry_bridge().emit_sync(
            CerebroEventType.HIVE_STATE_CHANGE, {"old_state": old_state.value, "new_state": new_state.value}
        )

        if self.on_state_change:
            self.on_state_change(old_state, new_state)

    async def process_task(
        self,
        task: str,
        complexity: TaskComplexity = TaskComplexity.MODERATE,
        task_id: str | None = None,  # V8.4.4b: For saga resume
    ) -> HiveMindResult:
        """
        Process a task through the Hive Mind pipeline.

        Args:
            task: Task description
            complexity: Task complexity level
            task_id: Optional task ID for saga resume support

        Returns:
            HiveMindResult with outcome
        """
        logger.info(f"Processing task: {task[:100]}...")
        self._current_task = task
        start_time = time.time()
        phases_completed = []
        agents_spawned = []

        # V10 SYNAPSE: Start correlation trace for this task
        _telemetry_bridge = get_telemetry_bridge()
        trace_id = _telemetry_bridge.start_trace()

        try:
            # V10 SYNAPSE: Emit process_task start event
            await _telemetry_bridge.emit(
                CerebroEventType.HIVE_PHASE_START,
                {"phase": "process_task", "task_preview": task[:100], "trace_id": trace_id},
            )

            # V12.0 RETINA: Spawn graph nodes for visualization
            await _telemetry_bridge.emit(
                CerebroEventType.GRAPH_NODE_SPAWN,
                {
                    "node_id": "gemini",
                    "type": "agent",
                    "data": {"name": "Gemini", "status": "idle", "role": "analyst"},
                    "position": {"x": 100, "y": 50},
                },
            )
            await _telemetry_bridge.emit(
                CerebroEventType.GRAPH_NODE_SPAWN,
                {
                    "node_id": "claude",
                    "type": "agent",
                    "data": {"name": "Claude", "status": "idle", "role": "analyst"},
                    "position": {"x": 300, "y": 50},
                },
            )
            await _telemetry_bridge.emit(
                CerebroEventType.GRAPH_NODE_SPAWN,
                {
                    "node_id": "task",
                    "type": "task",
                    "data": {"name": task[:50], "status": "pending", "phase": "starting"},
                    "position": {"x": 200, "y": 200},
                },
            )

            # Reset for new task
            self.cost_estimator.start_task()
            self.phase_retry.reset_retry_count()
            self.context_manager.clear(keep_critical=False)
            self.confidence_monitor.reset()

            # V12.4: Reset echo chamber guard for new task
            try:
                from .echo_chamber_guard import get_echo_chamber_guard

                get_echo_chamber_guard().reset()
            except Exception:
                pass

            # V12.4: Allocate phase budgets based on complexity
            self.budget_allocator.reset()
            phase_budgets = self.budget_allocator.allocate(
                complexity.value if hasattr(complexity, "value") else str(complexity)
            )
            logger.info(f"[HiveMind] Phase budgets allocated: execution={phase_budgets.get('execution', 0)}")

            # V12.4: Phase coordinator - start session and track transitions
            _phase_coord = None
            try:
                from .phase_coordinator import get_phase_coordinator

                _phase_coord = get_phase_coordinator()
                _phase_coord.start_session(task_id or f"hive_{int(start_time)}")
            except Exception:
                pass

            # V12.4: Checkpoint manager - lightweight checkpoints per phase
            _ckpt_mgr = None
            try:
                from core.infrastructure.resilience.checkpoint_manager import get_checkpoint_manager

                _ckpt_mgr = get_checkpoint_manager()
            except Exception:
                pass

            # V12.4: Resilience event tracker for retry/failure observability
            _resilience = None
            try:
                from core.infrastructure.resilience.resilience_event_tracker import get_resilience_tracker

                _resilience = get_resilience_tracker()
            except Exception:
                pass

            _coord_session = task_id or f"hive_{int(start_time)}"

            # V12.4: CapabilityProfiler - register agents for data-driven routing (arxiv:2505.16303)
            try:
                from core.foundation.agents.capability_profiler import get_capability_profiler

                _cap_profiler = get_capability_profiler()
                if _cap_profiler.agent_count == 0:
                    _cap_profiler.register_agent(
                        "gemini",
                        capabilities=["research", "web_search", "brainstorming", "analysis", "coding"],
                        initial_proficiency={
                            "research": 0.85,
                            "web_search": 0.9,
                            "brainstorming": 0.8,
                            "analysis": 0.8,
                            "coding": 0.7,
                        },
                    )
                    _cap_profiler.register_agent(
                        "claude",
                        capabilities=["coding", "debugging", "architecture", "security_analysis", "documentation"],
                        initial_proficiency={
                            "coding": 0.9,
                            "debugging": 0.85,
                            "architecture": 0.85,
                            "security_analysis": 0.8,
                            "documentation": 0.8,
                        },
                    )
            except Exception:
                _cap_profiler = None

            # V8.4.4b: Initialize SagaManager for checkpoint/rollback
            if self.saga_enabled:
                from core.intelligence.swarm import generate_task_id

                task_id = task_id or generate_task_id(prefix="hive")
                sagas_dir = self.workspace_path / ".nexus" / "sagas"
                sagas_dir.mkdir(parents=True, exist_ok=True)

                # Check for resume
                self._saga = await SagaManager.resume_from(sagas_dir, task_id)
                if self._saga:
                    logger.info(f"[Saga] Resumed: {task_id}, recovery={self._saga.recovery_point}")
                else:
                    self._saga = SagaManager(sagas_dir, task_id)
                    self._saga.register_default_compensations(self)
                    logger.info(f"[Saga] Started: {task_id}")

                # V9.4 ISSUE-003: Wire saga manager to sync bridge
                self._sync_bridge.set_saga_manager(self._saga)

            # Check budget before starting
            if self.budget_tracker:
                # Integration with V7 BudgetTracker
                estimated_cost = self.cost_estimator.estimate_full_hive_mind()
                estimated_usd = self.cost_estimator.tokens_to_usd(estimated_cost)
                logger.info(f"[HiveMind] Estimated execution cost: ~{estimated_cost:,} tokens (~${estimated_usd:.4f})")
                # Check if we can afford it
                if not self.cost_estimator.check_usd_budget(estimated_cost):
                    logger.warning("[HiveMind] Execution may exceed USD budget")

            # =========================================================
            # PHASE 1: Independent Analysis
            # =========================================================
            if _phase_coord:
                _phase_coord.transition(_coord_session, "analysis", reason="task_start")
            self._set_state(HiveMindState.HIVE_ANALYZING_GEMINI)

            # V12.0 RETINA: Update nodes - agents analyzing
            await _telemetry_bridge.emit(
                CerebroEventType.GRAPH_NODE_UPDATE,
                {"node_id": "gemini", "data": {"status": "working", "phase": "analysis"}},
            )
            await _telemetry_bridge.emit(
                CerebroEventType.GRAPH_NODE_UPDATE,
                {"node_id": "claude", "data": {"status": "working", "phase": "analysis"}},
            )
            await _telemetry_bridge.emit(
                CerebroEventType.GRAPH_NODE_UPDATE,
                {"node_id": "task", "data": {"status": "in_progress", "phase": "analysis"}},
            )

            analysis_result = await self.phase_analysis.execute(task)
            phases_completed.append("analysis")

            # V12.4: Record analysis confidence
            self.confidence_monitor.record(
                "analysis",
                analysis_result.comparison.agreement_score,
                needs_debate=analysis_result.needs_debate,
            )

            # V12.4: Report actual analysis cost to budget allocator
            self.budget_allocator.report_actual("analysis", self.cost_estimator.spent)

            # V12.4: Audit log analysis decision
            _audit = get_phase_audit_logger()
            _audit.record_decision(
                session_id=task_id or "unknown",
                phase="ANALYSIS",
                decision="debate_needed" if analysis_result.needs_debate else "skip_debate",
                options_considered=["debate", "skip_debate"],
                reasoning=analysis_result.skip_reason or "Disagreement requires debate",
                agent_id="both",
                agreement_score=analysis_result.comparison.agreement_score,
            )

            # V12.0 RETINA: Update nodes - analysis complete
            await _telemetry_bridge.emit(
                CerebroEventType.GRAPH_NODE_UPDATE,
                {"node_id": "gemini", "data": {"status": "done", "phase": "analysis"}},
            )
            await _telemetry_bridge.emit(
                CerebroEventType.GRAPH_NODE_UPDATE,
                {"node_id": "claude", "data": {"status": "done", "phase": "analysis"}},
            )

            # V8.4.4b: Checkpoint after analysis
            if self._saga:
                await self._saga.checkpoint_phase(
                    phase="analysis",
                    result={"task": task, "needs_debate": analysis_result.needs_debate},
                    state=self.state.value,
                    context_index=len(self.context_manager._items),
                )
                self._saga.update_context(analysis_complete=True)
                # V9.4 ISSUE-003: Propagate checkpoint to Swarm
                await self._sync_bridge.sync_checkpoint(
                    source="hivemind",
                    task_id=self._saga.task_id,
                    phase_or_mode="analysis",
                    checkpoint_data={"context_index": len(self.context_manager._items)},
                )

            # V12.4: Checkpoint after analysis
            if _ckpt_mgr:
                with contextlib.suppress(Exception):
                    _ckpt_mgr.create(
                        _coord_session,
                        "analysis_complete",
                        state={
                            "needs_debate": analysis_result.needs_debate,
                            "agreement": analysis_result.comparison.agreement_score,
                        },
                    )

            # =========================================================
            # PHASE 2: Strategic Debate (if needed)
            # =========================================================
            if analysis_result.needs_debate:
                if _phase_coord:
                    _phase_coord.transition(_coord_session, "debate", reason="disagreement")
                self._set_state(HiveMindState.HIVE_DEBATING)
                debate_result = await self.phase_debate.execute(
                    task=task, comparison=analysis_result.comparison, complexity=complexity
                )
                phases_completed.append("debate")

                # User breakpoint after debate
                if self.auto_breakpoints and not debate_result.was_skipped:
                    self._set_state(HiveMindState.HIVE_BREAKPOINT_DEBATE)
                    response = self.user_handler.after_debate(
                        debate_summary=str(debate_result.debate_result.debate_history[-3:])
                        if debate_result.debate_result.debate_history
                        else "No debate history",
                        final_approach=debate_result.final_approach,
                        consensus_score=debate_result.debate_result.consensus_confidence,
                    )
                    if response.chosen_option == "cancel":
                        return self._create_cancelled_result(
                            phases_completed, start_time, "User cancelled after debate"
                        )
            else:
                # Skip debate - use analysis consensus
                debate_result = self.phase_debate._create_skipped_result(analysis_result.comparison)
                phases_completed.append("debate_skipped")

            # V12.4: Record debate confidence
            debate_confidence = (
                debate_result.debate_result.consensus_confidence
                if not debate_result.was_skipped
                else analysis_result.comparison.agreement_score
            )
            self.confidence_monitor.record(
                "debate",
                debate_confidence,
                was_skipped=debate_result.was_skipped,
            )

            # V12.4: Report actual debate cost to budget allocator
            self.budget_allocator.report_actual("debate", self.cost_estimator.spent)

            # V12.4: Audit log debate decision
            _audit.record_decision(
                session_id=task_id or "unknown",
                phase="DEBATE",
                decision="skipped" if debate_result.was_skipped else "completed",
                options_considered=["debate", "skip"],
                reasoning=debate_result.skip_reason or f"Consensus: {debate_confidence:.0%}",
                agent_id="both",
                consensus_confidence=debate_confidence,
            )

            # V8.4.4b: Checkpoint after debate
            if self._saga:
                await self._saga.checkpoint_phase(
                    phase="debate",
                    result={"was_skipped": debate_result.was_skipped},
                    state=self.state.value,
                    context_index=len(self.context_manager._items),
                )
                self._saga.update_context(debate_complete=True)
                # V9.4 ISSUE-003: Propagate checkpoint to Swarm
                await self._sync_bridge.sync_checkpoint(
                    source="hivemind",
                    task_id=self._saga.task_id,
                    phase_or_mode="debate",
                    checkpoint_data={"context_index": len(self.context_manager._items)},
                )

            # V12.4: Checkpoint after debate
            if _ckpt_mgr:
                with contextlib.suppress(Exception):
                    _ckpt_mgr.create(
                        _coord_session,
                        "debate_complete",
                        state={
                            "was_skipped": debate_result.was_skipped,
                            "consensus": debate_confidence,
                        },
                    )

            # =========================================================
            # PHASE 3: Architecture Generation
            # =========================================================
            if _phase_coord:
                _phase_coord.transition(_coord_session, "architecture", reason="debate_resolved")
            self._set_state(HiveMindState.HIVE_ARCHITECTING)
            arch_result = await self.phase_architecture.execute(task=task, debate_result=debate_result.debate_result)
            phases_completed.append("architecture")
            agents_spawned = arch_result.agents_spawned
            self._spawned_agents = agents_spawned  # V8.4.4b: Track for compensation

            # V12.4: Record architecture confidence (based on status)
            arch_confidence = 0.80 if arch_result.architecture.status == "READY" else 0.60
            self.confidence_monitor.record(
                "architecture",
                arch_confidence,
                agents_spawned=len(agents_spawned),
            )

            # V12.4: Report actual architecture cost to budget allocator
            self.budget_allocator.report_actual("architecture", self.cost_estimator.spent)

            # V12.4: Audit log architecture decision
            _audit.record_decision(
                session_id=task_id or "unknown",
                phase="ARCHITECTURE",
                decision=arch_result.architecture.status,
                options_considered=["READY", "SPAWN_REQUIRED"],
                reasoning=arch_result.architecture.reasoning or "Architecture generated",
                agent_id="both",
                agents_spawned=len(agents_spawned),
            )

            # V12.4: Check confidence trajectory before expensive execution
            abort_rec = self.confidence_monitor.should_abort()
            if abort_rec.should_abort:
                logger.warning(f"[HiveMind] Confidence abort: {abort_rec.reason}")
                return self._create_cancelled_result(
                    phases_completed, start_time, f"Low confidence: {abort_rec.reason}"
                )

            # V8.4.4b: Checkpoint after architecture
            if self._saga:
                await self._saga.checkpoint_phase(
                    phase="architecture",
                    result={"agents_spawned": agents_spawned},
                    state=self.state.value,
                    context_index=len(self.context_manager._items),
                )
                self._saga.update_context(architecture_approved=True)
                # V9.4 ISSUE-003: Propagate checkpoint to Swarm
                await self._sync_bridge.sync_checkpoint(
                    source="hivemind",
                    task_id=self._saga.task_id,
                    phase_or_mode="architecture",
                    checkpoint_data={"context_index": len(self.context_manager._items)},
                )

            # V12.4: Checkpoint after architecture
            if _ckpt_mgr:
                with contextlib.suppress(Exception):
                    _ckpt_mgr.create(
                        _coord_session,
                        "architecture_complete",
                        state={
                            "agents_spawned": agents_spawned,
                            "status": arch_result.architecture.status,
                        },
                    )

            # =========================================================
            # PHASE 4-6: Execution Loop (with retry)
            # =========================================================
            execution_success = False
            execution_result = None
            max_attempts = 4  # 1 initial + 3 retries

            for attempt in range(max_attempts):
                # PHASE 4: Monitored Execution
                if _phase_coord:
                    _phase_coord.transition(_coord_session, "execution", reason=f"attempt_{attempt + 1}")
                self._set_state(HiveMindState.HIVE_EXECUTING)
                execution_result = await self.phase_execution.execute(task=task, architecture=arch_result.architecture)

                # V12.4: Record execution confidence
                exec_confidence = 0.90 if execution_result.success else 0.30
                self.confidence_monitor.record(
                    "execution",
                    exec_confidence,
                    success=execution_result.success,
                    attempt=attempt + 1,
                )

                if execution_result.success:
                    execution_success = True
                    phases_completed.append(f"execution_success_attempt_{attempt + 1}")
                    # V8.4.4b: Checkpoint execution success
                    if self._saga:
                        await self._saga.checkpoint_phase(
                            phase="execution",
                            result={"success": True, "attempt": attempt + 1},
                            state=self.state.value,
                            context_index=len(self.context_manager._items),
                        )
                        self._saga.update_context(execution_complete=True)
                        # V9.4 ISSUE-003: Propagate checkpoint to Swarm
                        await self._sync_bridge.sync_checkpoint(
                            source="hivemind",
                            task_id=self._saga.task_id,
                            phase_or_mode="execution",
                            checkpoint_data={"context_index": len(self.context_manager._items)},
                        )
                    break

                phases_completed.append(f"execution_failed_attempt_{attempt + 1}")
                # V8.4.4b: Mark execution failed in saga context
                if self._saga:
                    self._saga.update_context(execution_failed=True, attempt=attempt + 1)

                # Check if diagnosis needed
                if not execution_result.needs_diagnosis:
                    break

                # V12.4: Record execution failure as resilience event
                if _resilience:
                    with contextlib.suppress(Exception):
                        _resilience.record_event(
                            event_type="retry",
                            component="hive_mind_execution",
                            description=f"Execution failed attempt {attempt + 1}: {execution_result.failure_step or 'unknown step'}",
                            severity="warning" if attempt < 2 else "critical",
                        )

                # PHASE 5: Failure Diagnosis
                if _phase_coord:
                    _phase_coord.transition(_coord_session, "diagnosis", reason="execution_failed")
                self._set_state(HiveMindState.HIVE_DIAGNOSING)
                diagnosis_result = await self.phase_diagnosis.execute(
                    task=task,
                    step_results=execution_result.step_results,
                    issues=execution_result.issues,
                    failure_step=execution_result.failure_step,
                )
                phases_completed.append("diagnosis")

                # V12.4: Record diagnosis confidence
                self.confidence_monitor.record(
                    "diagnosis",
                    diagnosis_result.diagnosis.confidence,
                    user_decision=diagnosis_result.user_decision,
                )

                # V8.4.4b: Checkpoint after diagnosis
                if self._saga:
                    await self._saga.checkpoint_phase(
                        phase="diagnosis",
                        result={"user_decision": diagnosis_result.user_decision},
                        state=self.state.value,
                        context_index=len(self.context_manager._items),
                    )
                    self._saga.update_context(diagnosis_complete=True)
                    # V9.4 ISSUE-003: Propagate checkpoint to Swarm
                    await self._sync_bridge.sync_checkpoint(
                        source="hivemind",
                        task_id=self._saga.task_id,
                        phase_or_mode="diagnosis",
                        checkpoint_data={"context_index": len(self.context_manager._items)},
                    )

                # Check user decision
                if diagnosis_result.user_decision in ("abort", "escalate"):
                    return self._create_failed_result(
                        phases_completed=phases_completed,
                        start_time=start_time,
                        error=f"User chose to {diagnosis_result.user_decision}",
                        execution_result=execution_result,
                    )

                # V12.4: Checkpoint after diagnosis
                if _ckpt_mgr:
                    with contextlib.suppress(Exception):
                        _ckpt_mgr.create(
                            _coord_session,
                            f"diagnosis_attempt_{attempt + 1}",
                            state={
                                "failure_type": diagnosis_result.diagnosis.failure_type.value,
                                "user_decision": diagnosis_result.user_decision,
                                "confidence": diagnosis_result.diagnosis.confidence,
                            },
                        )

                # PHASE 6: Adaptive Retry
                if _phase_coord:
                    _phase_coord.transition(_coord_session, "retry", reason=f"retry_attempt_{attempt + 1}")
                self._set_state(HiveMindState.HIVE_APPLYING_CHANGES)
                retry_recommendations = self.phase_diagnosis.get_retry_recommendations(diagnosis_result)
                retry_result = self.phase_retry.execute(
                    diagnosis=diagnosis_result.diagnosis,
                    current_architecture=arch_result.architecture,
                    recommendations=retry_recommendations,
                    user_decision=diagnosis_result.user_decision,
                )

                if retry_result.decision.action != "RETRY":
                    # Can't retry - escalate
                    return self._create_failed_result(
                        phases_completed=phases_completed,
                        start_time=start_time,
                        error=retry_result.decision.reason,
                        execution_result=execution_result,
                    )

                # =========================================================
                # V8.0.1: Hot-Swap Lead Agent Check
                # =========================================================
                swap_result = self._check_and_swap_lead(diagnosis_result.diagnosis, arch_result.architecture)
                if swap_result["swapped"]:
                    phases_completed.append(f"lead_swapped_{swap_result['new_lead']}")
                    logger.info(f"Hot-Swap: Lead changed to {swap_result['new_lead']}")
                    # Update architecture to use new lead
                    if hasattr(arch_result.architecture, "lead_agent"):
                        arch_result.architecture.lead_agent = swap_result["new_lead"]

                # Update architecture for retry
                if retry_result.modified_architecture:
                    arch_result.architecture = retry_result.modified_architecture

                phases_completed.append(f"retry_attempt_{attempt + 1}")

            # =========================================================
            # PHASE 7: Knowledge Consolidation
            # =========================================================
            if _phase_coord:
                _phase_coord.transition(_coord_session, "consolidation", reason="execution_complete")
            self._set_state(HiveMindState.HIVE_REFLECTING)
            consolidation_result = await self.phase_consolidation.execute(
                task=task,
                success=execution_success,
                duration=time.time() - start_time,
                steps_completed=len(execution_result.step_results) if execution_result else 0,
                issues_count=len(execution_result.issues) if execution_result else 0,
                approach=debate_result.final_approach,
                agents_used=arch_result.architecture.agents_to_use,
                agents_spawned=agents_spawned,
            )
            phases_completed.append("consolidation")

            # V12.4: Report consolidation cost and log budget summary
            self.budget_allocator.report_actual("consolidation", self.cost_estimator.spent)
            budget_stats = self.budget_allocator.get_stats()
            logger.info(
                f"[HiveMind] Budget: spent={budget_stats['total_spent']}, "
                f"redistributed={budget_stats['redistributed']}, "
                f"utilization={budget_stats['utilization']:.1%}"
            )

            # V12.4: Record consolidation confidence and log trajectory
            self.confidence_monitor.record(
                "consolidation",
                consolidation_result.consolidation.confidence_in_decisions,
                success=execution_success,
            )
            trajectory = self.confidence_monitor.get_trajectory()
            logger.info(
                f"[HiveMind] Confidence trajectory: trend={trajectory.trend}, "
                f"avg={trajectory.average:.2f}, min={trajectory.minimum:.2f}"
            )

            # V12.4: System health snapshot via introspector
            if self._introspector:
                try:
                    snapshot = self._introspector.get_snapshot()
                    if snapshot.degraded_components > 0:
                        logger.warning(
                            f"[HiveMind] System health: {snapshot.degraded_components} degraded, "
                            f"{snapshot.inactive_components} inactive of {snapshot.total_components} components"
                        )
                    else:
                        logger.debug(
                            f"[HiveMind] System health: {snapshot.active_components}/{snapshot.total_components} active"
                        )
                except Exception:
                    pass

            # V12.4: Audit log consolidation and detect patterns
            _audit.record_decision(
                session_id=task_id or "unknown",
                phase="CONSOLIDATION",
                decision="success" if execution_success else "failure",
                options_considered=["success", "failure"],
                reasoning=f"Trajectory: {trajectory.trend}, avg confidence: {trajectory.average:.2f}",
                agent_id="both",
                confidence_trend=trajectory.trend,
            )
            patterns = _audit.detect_patterns()
            if patterns:
                logger.info(f"[HiveMind] Audit patterns: {[p.pattern_type for p in patterns[:3]]}")

            # Mark success in retry system
            if execution_success:
                self.phase_retry.mark_success(
                    arch_result.architecture, diagnosis_result.diagnosis if "diagnosis_result" in dir() else None
                )

            # Archive context insights to RAG
            if self.project_memory:
                archived = self.context_manager.archive_to_rag(
                    self.project_memory, session_id=f"hive_mind_{int(start_time)}"
                )
                logger.info(f"Archived {archived} insights to RAG")

            # V12.4: Final checkpoint and end coordinator session
            if _ckpt_mgr:
                with contextlib.suppress(Exception):
                    _ckpt_mgr.create(
                        _coord_session,
                        "task_complete",
                        state={
                            "success": execution_success,
                            "phases": phases_completed,
                            "tokens": self.cost_estimator.spent,
                        },
                    )
            if _phase_coord:
                _phase_coord.transition(_coord_session, "idle", reason="task_complete")
                _phase_coord.end_session(_coord_session)

            # =========================================================
            # SUCCESS
            # =========================================================
            self._set_state(HiveMindState.HIVE_SUCCESS)

            # V8.2.0: Record success to SuccessMemory for learning
            if self.success_memory and execution_success:
                try:
                    from .success_adapter import create_hive_mind_adapters

                    analysis_adapter, result_adapter = create_hive_mind_adapters(
                        task=task,
                        duration=time.time() - start_time,
                        success=execution_success,
                        phases_completed=len(phases_completed),
                        agents_used=arch_result.architecture.agents_to_use if arch_result else ["gemini", "claude"],
                    )

                    self.success_memory.record_success(
                        task_id=f"hive_{int(start_time)}",
                        analysis=analysis_adapter,
                        result=result_adapter,
                        quality_score=0.8 if execution_success else 0.3,
                    )
                    logger.debug("Recorded HiveMind success to memory")
                except Exception as mem_err:
                    logger.warning(f"Failed to record HiveMind success: {mem_err}")

            # V12.4: Record task outcome to CapabilityProfiler for routing learning
            if _cap_profiler is not None:
                try:
                    agents_used = arch_result.architecture.agents_to_use if arch_result else ["gemini", "claude"]
                    quality = (
                        execution_result.quality_score
                        if execution_result and hasattr(execution_result, "quality_score")
                        else 0.5
                    )
                    for agent_id in agents_used:
                        _cap_profiler.record_outcome(
                            agent_id,
                            "general",
                            success=execution_success,
                            quality=quality,
                        )
                except Exception:
                    pass

            # V12.4: FailoverManager - record driver outcomes for circuit breaker learning
            if self._failover:
                try:
                    agents_used = arch_result.architecture.agents_to_use if arch_result else ["gemini", "claude"]
                    for agent_id in agents_used:
                        if execution_success:
                            self._failover.record_success(agent_id)
                        else:
                            self._failover.record_failure(agent_id)
                except Exception:
                    pass

            # V8.4.4b: Cleanup saga on success (remove checkpoint files)
            if self._saga and execution_success:
                self._saga.cleanup()
                logger.info(f"[Saga] Completed and cleaned up: {task_id}")

            # V10 SYNAPSE: Emit process_task end event and end trace
            await _telemetry_bridge.emit(
                CerebroEventType.HIVE_PHASE_END,
                {"phase": "process_task", "success": execution_success, "duration": time.time() - start_time},
            )
            _telemetry_bridge.end_trace()

            return HiveMindResult(
                success=execution_success,
                output=self._format_output(execution_result, consolidation_result),
                state=HiveMindState.HIVE_SUCCESS,
                phases_completed=phases_completed,
                total_duration=time.time() - start_time,
                total_tokens=self.cost_estimator.spent,
                agents_used=arch_result.architecture.agents_to_use,
                agents_spawned=agents_spawned,
                artifacts_created=execution_result.artifacts_created if execution_result else [],
                knowledge_archived=consolidation_result.archived_to_rag,
            )

        except Exception as e:
            logger.error(f"Hive Mind error: {e}", exc_info=True)
            self._set_state(HiveMindState.HIVE_FAILED)

            # V10 SYNAPSE: Emit failure event and end trace
            _telemetry_bridge.emit_sync(
                CerebroEventType.HIVE_PHASE_END, {"phase": "process_task", "success": False, "error": str(e)[:200]}
            )
            _telemetry_bridge.end_trace()

            return HiveMindResult(
                success=False,
                output=f"Hive Mind failed: {e}",
                state=HiveMindState.HIVE_FAILED,
                phases_completed=phases_completed,
                total_duration=time.time() - start_time,
                total_tokens=self.cost_estimator.spent,
                agents_used=[],
                agents_spawned=agents_spawned,
                artifacts_created=[],
                knowledge_archived=0,
                error=str(e),
            )

    def _format_output(self, execution_result, consolidation_result) -> str:
        """Format the final output."""
        lines = []

        if execution_result:
            lines.append("## Execution Results")
            for step_result in execution_result.step_results:
                status = "[OK]" if step_result.status == "success" else "[NO]"
                lines.append(f"{status} {step_result.step_name}: {step_result.output[:200]}")

            if execution_result.artifacts_created:
                lines.append("\n## Artifacts Created")
                for artifact in execution_result.artifacts_created:
                    lines.append(f"- {artifact}")

        if consolidation_result and consolidation_result.consolidation.learned_patterns:
            lines.append("\n## Learned Patterns")
            for pattern in consolidation_result.consolidation.learned_patterns[:5]:
                lines.append(f"- {pattern}")

        return "\n".join(lines) if lines else "Task completed"

    def _create_cancelled_result(self, phases_completed: list, start_time: float, reason: str) -> HiveMindResult:
        """Create result for user-cancelled task."""
        return HiveMindResult(
            success=False,
            output=f"Task cancelled: {reason}",
            state=HiveMindState.HIVE_ESCALATE,
            phases_completed=phases_completed,
            total_duration=time.time() - start_time,
            total_tokens=self.cost_estimator.spent,
            agents_used=[],
            agents_spawned=[],
            artifacts_created=[],
            knowledge_archived=0,
            error=reason,
        )

    def _create_failed_result(
        self, phases_completed: list, start_time: float, error: str, execution_result=None
    ) -> HiveMindResult:
        """Create result for failed task."""
        return HiveMindResult(
            success=False,
            output=f"Task failed: {error}",
            state=HiveMindState.HIVE_FAILED,
            phases_completed=phases_completed,
            total_duration=time.time() - start_time,
            total_tokens=self.cost_estimator.spent,
            agents_used=[],
            agents_spawned=[],
            artifacts_created=execution_result.artifacts_created if execution_result else [],
            knowledge_archived=0,
            error=error,
        )

    def get_stats(self) -> dict[str, Any]:
        """Get Hive Mind statistics."""
        return {
            "current_state": self.state.value,
            "cost_stats": self.cost_estimator.get_stats(),
            "context_stats": self.context_manager.get_stats(),
            "registry_stats": self.agent_registry.get_stats(),
            "blacklist_stats": self.strategy_blacklist.get_stats(),
            "debate_stats": self.debate_config.get_stats(),
            "hot_swap_stats": {
                "current_lead": self._current_lead,
                "swap_count": self._lead_swap_count,
                "stagnation": self.stagnation_detector.get_stats(),
            },
        }

    # =========================================================================
    # V8.0.1: Hot-Swap Lead Agent
    # =========================================================================

    def _check_and_swap_lead(self, diagnosis: str, architecture: Any) -> dict[str, Any]:
        """
        V8.0.1: Check if lead agent should be swapped due to repeated failures.

        Called after failure diagnosis to determine if swapping lead might help.
        Uses StagnationDetector to track failure patterns.

        Args:
            diagnosis: Diagnosis text from failure analysis
            architecture: Current task architecture

        Returns:
            Dict with swap decision:
            - swapped: bool - Whether swap occurred
            - new_lead: str - New lead agent (if swapped)
            - reason: str - Reason for decision
        """
        # Record this failure for stagnation tracking
        self.stagnation_detector.add_message(diagnosis)
        self.stagnation_detector.record_agent_failure(self._current_lead)

        # Check if swap is recommended
        recommendation = self.stagnation_detector.get_swap_recommendation(self._current_lead)

        if recommendation["should_swap"]:
            # Perform the swap
            old_lead = self._current_lead
            self._current_lead = recommendation["new_lead"]
            self._lead_swap_count += 1

            # Report to blacklist for future reference
            self.stagnation_detector.report_to_blacklist(task_context=f"Task failed with {old_lead} as lead")

            # Reset stagnation detector for fresh start with new lead
            self.stagnation_detector.reset()

            logger.info(f"Hot-Swap Lead: {old_lead} -> {self._current_lead} (reason: {recommendation['reason']})")

            return {
                "swapped": True,
                "old_lead": old_lead,
                "new_lead": self._current_lead,
                "reason": recommendation["reason"],
                "swap_count": self._lead_swap_count,
            }

        return {"swapped": False, "new_lead": None, "reason": "No swap needed - stagnation threshold not reached"}

    def force_lead_swap(self, new_lead: str) -> dict[str, Any]:
        """
        V8.0.1: Manually force a lead agent swap.

        Useful for testing or when user wants to try different lead.

        Args:
            new_lead: New lead agent ("gemini" or "claude")

        Returns:
            Dict with swap result
        """
        if new_lead.lower() not in ("gemini", "claude"):
            return {"swapped": False, "error": f"Invalid lead agent: {new_lead}. Must be 'gemini' or 'claude'"}

        old_lead = self._current_lead
        self._current_lead = new_lead.lower()
        self._lead_swap_count += 1
        self.stagnation_detector.reset()

        logger.info(f"Manual Lead Swap: {old_lead} -> {self._current_lead}")

        return {
            "swapped": True,
            "old_lead": old_lead,
            "new_lead": self._current_lead,
            "reason": "Manual swap requested",
            "swap_count": self._lead_swap_count,
        }

    def get_current_lead(self) -> str:
        """V8.0.1: Get current lead agent."""
        return self._current_lead
