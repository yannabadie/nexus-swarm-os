"""
Hybrid Swarm Engine - Sprint 9 Main Orchestration

The central engine that coordinates:
1. Task analysis
2. Mode selection (DyLAN-based)
3. Agent negotiation (optional)
4. Mode execution
5. Result merging and metrics update

Entry point for dynamic multi-agent collaboration where
agents negotiate the optimal mode for each task.

Usage:
    from core.intelligence.swarm import HybridSwarmEngine

    engine = HybridSwarmEngine(agent_pool, model_router, config)
    result = engine.process_task("Fix the auth bug", blackboard)
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from .agent_metrics import AgentInvocationResult, AgentPool, AgentProfile, create_default_pool
from .collaboration_modes import CollaborationMode
from .mode_selector import ModeProposal, ModeSelector
from .session_manager import SwarmSessionManager, generate_task_id
from .task_analyzer import TaskAnalysis, TaskAnalyzer

logger = logging.getLogger(__name__)

# V7.9: Spawned Agent Integration
_AGENT_LOADER_AVAILABLE = False
try:
    from ..bootstrap.agent_loader import SpawnedAgentLoader, discover_and_register_spawned_agents

    _AGENT_LOADER_AVAILABLE = True
except ImportError:
    SpawnedAgentLoader = None
    discover_and_register_spawned_agents = None

# V7.6 Phase 10a: Success Memory (lazy import at usage site to avoid circular deps)
_SUCCESS_MEMORY_AVAILABLE = True  # Will attempt lazy import
SuccessMemory = None  # Populated lazily
# V10 SYNAPSE: Telemetry instrumentation
from core.observability.events.telemetry_bridge import (  # noqa: E402  # after optional dependency blocks
    emit_agent_exchange,
    emit_agent_speak,  # noqa: F401  # used by tests via mock.patch()
    get_telemetry_bridge,
)
from core.observability.events.types import CerebroEventType  # noqa: E402

from .mode_executors import (  # noqa: E402
    AgentResponse,
    ExecutionContext,
    ExecutionResult,
    ExecutionStatus,
    get_executor,
)
from .negotiation_protocol import NegotiationProtocol, NegotiationResult, NegotiationStatus  # noqa: E402
from .task_analyzer import TaskComplexity  # noqa: E402
from .task_completion_validator import get_adaptive_max_rounds  # noqa: E402


class SwarmPhase(Enum):
    """Current phase of swarm processing"""

    IDLE = "idle"
    ANALYZING = "analyzing"
    SELECTING = "selecting"
    NEGOTIATING = "negotiating"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class SwarmResult:
    """
    Final result from Hybrid Swarm processing.

    Contains the output, metrics, and full processing history.
    """

    status: SwarmPhase
    final_output: str
    selected_mode: CollaborationMode
    task_analysis: TaskAnalysis
    mode_proposal: ModeProposal
    negotiation_result: NegotiationResult | None
    execution_result: ExecutionResult
    total_time_seconds: float
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "final_output": self.final_output,  # Full output (no truncation)
            "selected_mode": self.selected_mode.value,
            "task_analysis": self.task_analysis.to_dict(),
            "mode_proposal": self.mode_proposal.to_dict(),
            "negotiation_result": (self.negotiation_result.to_dict() if self.negotiation_result else None),
            "execution_result": self.execution_result.to_dict(),
            "total_time_seconds": round(self.total_time_seconds, 2),
            "timestamp": self.timestamp.isoformat(),
        }


class HybridSwarmEngine:
    """
    Main Hybrid Swarm Engine for dynamic multi-agent collaboration.

    Coordinates the full pipeline:
    Task -> Analysis -> Mode Selection -> Negotiation -> Execution -> Result

    The engine can operate in different modes:
    - Full: Analysis + Selection + Negotiation + Execution
    - Fast: Analysis + Selection + Execution (skip negotiation)
    - Forced: User-specified mode + Execution
    """

    def __init__(
        self,
        agent_pool: AgentPool | None = None,
        model_router: Any | None = None,
        config: Any | None = None,
        invoke_agent: Callable | None = None,
        workspace_path: Path | None = None,
    ):
        """
        Initialize Hybrid Swarm Engine.

        Args:
            agent_pool: AgentPool for DyLAN metrics
            model_router: ModelRouter for agent selection
            config: Configuration object
            invoke_agent: Callable to invoke agents
            workspace_path: Path to workspace for session persistence (Phase 7)
        """
        self.agent_pool = agent_pool or create_default_pool()
        self.model_router = model_router
        self.config = config
        self.invoke_agent = invoke_agent
        self.workspace_path = workspace_path

        # V7.5 Phase 7: Session isolation manager
        if workspace_path:
            self.session_manager = SwarmSessionManager(workspace_path)
        else:
            self.session_manager = None

        # V7.6 Phase 10a: Success Memory (lazy import to avoid circular deps)
        self.success_memory = None
        if workspace_path and _SUCCESS_MEMORY_AVAILABLE:
            try:
                from core.memory_pkg.memory.success_memory_v2 import SuccessMemoryV2

                self.success_memory = SuccessMemoryV2(workspace_path)
            except Exception:
                pass

        # V7.9: Spawned Agent Loader
        self.spawned_agent_loader = None
        if workspace_path and _AGENT_LOADER_AVAILABLE and SpawnedAgentLoader:
            self.spawned_agent_loader = SpawnedAgentLoader(workspace_path)
            # Auto-discover and register spawned agents
            self._discover_spawned_agents()

        # Components
        self.task_analyzer = TaskAnalyzer()
        # V7.6 Phase 10b: Pass SuccessMemory to ModeSelector
        self.mode_selector = ModeSelector(agent_pool=self.agent_pool, success_memory=self.success_memory)
        self.negotiation = NegotiationProtocol(
            max_turns=self._get_config("swarm_negotiation_max_turns", 4),
            skip_trivial=self._get_config("swarm_skip_trivial", True),
        )

        # State
        self.current_phase = SwarmPhase.IDLE
        self._current_analysis: TaskAnalysis | None = None
        self._current_proposal: ModeProposal | None = None
        self._negotiation_result: NegotiationResult | None = None
        self._current_task_id: str | None = None  # Phase 7: Current task ID

        # History
        self.processing_history: list[dict] = []

    def _get_config(self, key: str, default: Any) -> Any:
        """Get config value with fallback"""
        if self.config is None:
            return default
        return getattr(self.config, key, default)

    def process_task(
        self,
        task_input: str,
        blackboard: dict | None = None,
        force_mode: CollaborationMode | None = None,
        skip_negotiation: bool = False,
        on_negotiation_turn: Callable | None = None,
        on_execution_round: Callable | None = None,
    ) -> SwarmResult:
        """
        Process a task through the full Hybrid Swarm pipeline.

        V7.5 Phase 7: Session isolation for parallel task execution.

        Args:
            task_input: User's task description
            blackboard: Shared state dictionary
            force_mode: Force a specific mode (skip selection)
            skip_negotiation: Skip negotiation even if enabled
            on_negotiation_turn: V7.5 callback for real-time negotiation display
            on_execution_round: V7.5 callback for real-time execution display

        Returns:
            SwarmResult with complete processing details
        """
        start_time = datetime.now()
        blackboard = blackboard or {}

        # V7.5 Phase 7: Generate unique task ID and create session
        task_id = generate_task_id(prefix="swarm")
        self._current_task_id = task_id

        try:
            # Phase 1: Analyze task
            self.current_phase = SwarmPhase.ANALYZING
            # V10 SYNAPSE: Emit phase change telemetry (sync)
            get_telemetry_bridge().emit_sync(
                CerebroEventType.SWARM_PHASE_CHANGE, {"phase": self.current_phase.value, "task_id": task_id}
            )
            analysis = self.task_analyzer.analyze(task_input)
            self._current_analysis = analysis

            # V7.9: Check if spawning is recommended for complex tasks
            spawning_suggestion = self.get_spawning_suggestion(analysis)
            if spawning_suggestion:
                import sys

                print(
                    f"[SWARM SUGGESTION] {spawning_suggestion['reason']}\n"
                    f"  Recommended: {spawning_suggestion['command']}",
                    file=sys.stderr,
                )

            # Phase 2: Select mode (or use forced mode)
            self.current_phase = SwarmPhase.SELECTING
            # V10 SYNAPSE: Emit phase change telemetry (sync)
            get_telemetry_bridge().emit_sync(
                CerebroEventType.SWARM_PHASE_CHANGE, {"phase": self.current_phase.value, "task_id": task_id}
            )
            if force_mode:
                proposal = self._create_forced_proposal(force_mode, analysis)
            else:
                proposal = self.mode_selector.select_mode(analysis)
            self._current_proposal = proposal

            # Phase 3: Negotiate (if enabled and not skipped)
            negotiation_enabled = self._get_config("swarm_negotiation_enabled", True)
            negotiation_result = None

            if negotiation_enabled and not skip_negotiation and not force_mode:
                self.current_phase = SwarmPhase.NEGOTIATING
                # V10 SYNAPSE: Emit phase change telemetry (sync)
                get_telemetry_bridge().emit_sync(
                    CerebroEventType.SWARM_PHASE_CHANGE, {"phase": self.current_phase.value, "task_id": task_id}
                )
                negotiation_result = self._run_negotiation(analysis, proposal, on_turn=on_negotiation_turn)
                self._negotiation_result = negotiation_result

                # Update mode and assignments from negotiation
                if negotiation_result.status == NegotiationStatus.CONSENSUS:
                    final_mode = negotiation_result.selected_mode
                    agent_assignments = negotiation_result.agent_assignments

                    # V13.0 CEREBRO LIVE: Emit negotiation consensus
                    emit_agent_exchange(
                        "gemini", "claude", f"Consensus: {final_mode.value} mode agreed", exchange_type="consensus"
                    )
                else:
                    final_mode = proposal.mode
                    agent_assignments = proposal.agent_assignments
            else:
                final_mode = proposal.mode
                agent_assignments = proposal.agent_assignments

            # V7.5 Phase 7: Create isolated session for this task
            # V7.8.2 Phase 7b: EPHEMERAL sessions for trivial tasks (no persistence)
            if self.session_manager:
                is_ephemeral = analysis.complexity == TaskComplexity.TRIVIAL
                self.session_manager.create_task(task_id, final_mode.value, is_ephemeral=is_ephemeral)

            # Phase 4: Execute
            self.current_phase = SwarmPhase.EXECUTING
            # V10 SYNAPSE: Emit phase change telemetry (sync)
            get_telemetry_bridge().emit_sync(
                CerebroEventType.SWARM_PHASE_CHANGE,
                {"phase": self.current_phase.value, "task_id": task_id, "mode": final_mode.value},
            )

            # V7.9: Adaptive max_rounds based on task complexity
            config_max_rounds = self._get_config("swarm_max_rounds", None)
            if config_max_rounds is None:
                # Auto-adapt based on complexity
                adaptive_rounds = get_adaptive_max_rounds(analysis.complexity)
            else:
                adaptive_rounds = config_max_rounds

            # V7.9: Store task_analysis in blackboard for completion validation
            # V12.4: Store as dict for JSON serialization
            blackboard["task_analysis"] = analysis.to_dict()
            blackboard["workspace_path"] = self.workspace_path
            # V8.5.0: Add domains/complexity for AdaptiveFallbackSelector
            blackboard["domains"] = [d.value for d in analysis.domains]
            blackboard["complexity"] = analysis.complexity.name

            execution_context = ExecutionContext(
                task_input=task_input,
                agent_assignments=agent_assignments,
                blackboard=blackboard,
                max_rounds=adaptive_rounds,
                invoke_agent=self._wrap_invoke_agent(),
                on_round=on_execution_round,  # V7.5: Streaming callback
                # V7.5 Phase 7: Session isolation
                task_id=task_id,
                session_manager=self.session_manager,
                # V7.7 Phase 14e: Force CoT for EXPERT complexity
                force_cot=(analysis.complexity == TaskComplexity.EXPERT),
            )

            # V7.9: Pass workspace_path for artifact verification in PingPong
            executor = get_executor(final_mode, workspace_path=self.workspace_path)

            # V7.5 Phase 8: Self-Healing Swarm - execute with fallback
            use_self_healing = self._get_config("swarm_self_healing", True)
            if use_self_healing:
                execution_result = executor.execute_with_fallback(
                    execution_context, max_fallbacks=self._get_config("swarm_max_fallbacks", 2)
                )
            else:
                execution_result = executor.execute(execution_context)

            # Phase 5: Update metrics
            self._update_metrics(analysis, execution_result)

            # Complete
            self.current_phase = SwarmPhase.COMPLETED
            total_time = (datetime.now() - start_time).total_seconds()
            # V10 SYNAPSE: Emit phase change telemetry (sync)
            get_telemetry_bridge().emit_sync(
                CerebroEventType.SWARM_PHASE_CHANGE,
                {"phase": self.current_phase.value, "task_id": task_id, "duration": total_time},
            )

            result = SwarmResult(
                status=SwarmPhase.COMPLETED,
                final_output=execution_result.final_output,
                selected_mode=final_mode,
                task_analysis=analysis,
                mode_proposal=proposal,
                negotiation_result=negotiation_result,
                execution_result=execution_result,
                total_time_seconds=total_time,
            )

            # V7.9: Add spawning suggestion to execution_result metadata if applicable
            if spawning_suggestion:
                result.execution_result.metadata["spawning_suggestion"] = spawning_suggestion

            # Record history
            self._record_processing(result)

            # V7.6 Phase 10a: Record success to memory
            if self.success_memory and execution_result.status == ExecutionStatus.COMPLETED:
                try:
                    self.success_memory.record_success(task_id=task_id, analysis=analysis, result=result)
                except Exception as mem_err:
                    # V12.3: Log memory recording errors (was silent pass)
                    logger.warning(f"[SWARM] SuccessMemory recording failed for task {task_id}: {mem_err}")

            # V7.5 Phase 7: Mark task as completed
            if self.session_manager:
                from .session_manager import SessionStatus

                self.session_manager.complete_task(task_id, SessionStatus.COMPLETED)

            return result

        except Exception as e:
            self.current_phase = SwarmPhase.FAILED
            total_time = (datetime.now() - start_time).total_seconds()
            # V10 SYNAPSE: Emit phase change telemetry (sync) (sync since we're in except)
            get_telemetry_bridge().emit_sync(
                CerebroEventType.SWARM_PHASE_CHANGE,
                {"phase": self.current_phase.value, "task_id": task_id, "error": str(e)[:200]},
            )

            # Create error result
            return SwarmResult(
                status=SwarmPhase.FAILED,
                final_output=f"Swarm processing failed: {str(e)}",
                selected_mode=force_mode or CollaborationMode.PING_PONG,
                task_analysis=self._current_analysis
                or TaskAnalysis(complexity=1, domains=[], primary_domain=None, raw_input=task_input),
                mode_proposal=self._current_proposal
                or ModeProposal(
                    mode=CollaborationMode.PING_PONG, confidence=0.0, agent_assignments=[], reasoning="Error fallback"
                ),
                negotiation_result=None,
                execution_result=ExecutionResult(
                    mode=CollaborationMode.PING_PONG,
                    status=ExecutionStatus.FAILED,
                    final_output=str(e),
                    agent_outputs=[],
                    total_rounds=0,
                    total_tokens=0,
                    total_time_seconds=0.0,
                ),
                total_time_seconds=total_time,
            )

        finally:
            # V7.5 Phase 7: Ensure task is marked as completed (even on error)
            if self.session_manager and self._current_task_id:
                try:
                    task = self.session_manager.get_task(self._current_task_id)
                    if task and task.status.value == "active":
                        from .session_manager import SessionStatus

                        status = (
                            SessionStatus.COMPLETED
                            if self.current_phase == SwarmPhase.COMPLETED
                            else SessionStatus.FAILED
                        )
                        self.session_manager.complete_task(self._current_task_id, status)
                except Exception:
                    pass  # Don't fail the main task due to cleanup error
                finally:
                    self._current_task_id = None

    def _create_forced_proposal(self, mode: CollaborationMode, analysis: TaskAnalysis) -> ModeProposal:
        """Create a proposal for a forced mode"""
        # Use selector to get proper assignments
        proposal = self.mode_selector.select_mode(analysis)
        proposal.mode = mode
        proposal.reasoning = "User forced mode"
        proposal.confidence = 1.0
        return proposal

    def _run_negotiation(
        self, analysis: TaskAnalysis, proposal: ModeProposal, on_turn: Callable | None = None
    ) -> NegotiationResult:
        """Run negotiation protocol"""
        return self.negotiation.run_negotiation(
            task_analysis=analysis,
            initial_proposal=proposal,
            invoke_agent=self._invoke_for_negotiation,
            on_turn=on_turn,  # V7.5: Streaming callback
        )

    def _invoke_for_negotiation(self, agent_id: str, task_type: str, context: str) -> str:
        """Invoke agent for negotiation (returns string)"""
        if self.invoke_agent is None:
            return f"[Mock {agent_id} negotiation response]"

        response = self.invoke_agent(agent_id, task_type, context)

        if isinstance(response, str):
            return response
        elif hasattr(response, "content"):
            return response.content
        return str(response)

    def _wrap_invoke_agent(self) -> Callable:
        """Wrap invoke_agent to return AgentResponse.

        V8.1.6: Added session_uuid parameter for thread-safe parallel execution.
        """

        def wrapper(
            agent_id: str,
            task_type: str,
            context: str,
            session_uuid: str | None = None,
            isolated_env: dict[str, str] | None = None,
        ) -> AgentResponse:
            if self.invoke_agent is None:
                return AgentResponse(agent_id=agent_id, content=f"[Mock {agent_id} response]", status="mock")

            # V7.7 Phase 14e: Inject CoT instruction for EXPERT complexity
            if self._current_analysis and self._current_analysis.complexity == TaskComplexity.EXPERT:
                context += "\n\n<instruction>BEFORE answering or using tools, you MUST wrap your step-by-step reasoning in <thinking>...</thinking> tags.</instruction>"

            start = datetime.now()
            # V8.1.6: Pass session_uuid for thread-safe file access
            # V12.4 FIX: Pass isolated_env for session isolation (5th param from executors)
            response = self.invoke_agent(
                agent_id, task_type, context,
                session_uuid=session_uuid, isolated_env=isolated_env,
            )
            elapsed = (datetime.now() - start).total_seconds()

            if isinstance(response, AgentResponse):
                return response
            elif isinstance(response, str):
                # V7 FIX: Detect error responses from _invoke_for_swarm
                is_error = response.startswith("Error:") or "timed out" in response.lower()
                return AgentResponse(
                    agent_id=agent_id,
                    content=response,
                    status="error" if is_error else "success",
                    error=response if is_error else None,
                    time_seconds=elapsed,
                )
            elif isinstance(response, dict):
                return AgentResponse(
                    agent_id=agent_id,
                    content=response.get("content", str(response)),
                    status=response.get("status", "success"),
                    tokens_used=response.get("tokens_used", 0),
                    time_seconds=elapsed,
                )
            else:
                return AgentResponse(agent_id=agent_id, content=str(response), status="success", time_seconds=elapsed)

        return wrapper

    def _update_metrics(self, analysis: TaskAnalysis, result: ExecutionResult):
        """Update DyLAN metrics after execution"""
        if self.agent_pool is None:
            return

        for agent_output in result.agent_outputs:
            invocation = AgentInvocationResult(
                agent_id=agent_output.agent_id,
                task_type=analysis.primary_domain.value if analysis.primary_domain else "unknown",
                success=agent_output.status != "error",
                quality_score=0.7 if agent_output.status != "error" else 0.0,
                tokens_used=agent_output.tokens_used,
                time_seconds=agent_output.time_seconds,
            )
            self.agent_pool.record_invocation(invocation)

    def _record_processing(self, result: SwarmResult):
        """Record processing for history"""
        record = {
            "timestamp": result.timestamp.isoformat(),
            "mode": result.selected_mode.value,
            "complexity": result.task_analysis.complexity.name,
            "total_time": result.total_time_seconds,
            "status": result.status.value,
        }
        self.processing_history.append(record)

        # Keep last 100
        if len(self.processing_history) > 100:
            self.processing_history = self.processing_history[-100:]

    # === Public API for FSM integration ===

    def start_analysis(self, task_input: str) -> TaskAnalysis:
        """Start analysis phase (for FSM integration)"""
        self.current_phase = SwarmPhase.ANALYZING
        analysis = self.task_analyzer.analyze(task_input)
        self._current_analysis = analysis
        return analysis

    def get_analysis(self) -> TaskAnalysis | None:
        """Get current analysis"""
        return self._current_analysis

    def start_selection(self) -> ModeProposal:
        """Start mode selection phase"""
        self.current_phase = SwarmPhase.SELECTING
        if self._current_analysis is None:
            raise ValueError("Analysis must be run before selection")

        proposal = self.mode_selector.select_mode(self._current_analysis)
        self._current_proposal = proposal
        return proposal

    def start_negotiation(self, analysis: TaskAnalysis | None = None) -> NegotiationResult | None:
        """Start negotiation phase"""
        self.current_phase = SwarmPhase.NEGOTIATING

        analysis = analysis or self._current_analysis
        proposal = self._current_proposal

        if analysis is None or proposal is None:
            return None

        result = self._run_negotiation(analysis, proposal)
        self._negotiation_result = result
        return result

    def process_negotiation_turn(self) -> NegotiationResult | None:
        """Process a single negotiation turn (for FSM)"""
        # Negotiation is run in one shot for simplicity
        # This method returns the result if negotiation is complete
        return self._negotiation_result

    def execute_turn(self, task_input: str, blackboard: dict | None = None) -> ExecutionResult:
        """Execute current mode (for FSM integration)"""
        self.current_phase = SwarmPhase.EXECUTING

        mode = self._current_proposal.mode if self._current_proposal else CollaborationMode.PING_PONG
        if self._negotiation_result and self._negotiation_result.status == NegotiationStatus.CONSENSUS:
            mode = self._negotiation_result.selected_mode

        assignments = (
            self._negotiation_result.agent_assignments
            if self._negotiation_result
            else (self._current_proposal.agent_assignments if self._current_proposal else [])
        )

        # V7.7 Phase 14e: Check if EXPERT complexity for CoT
        is_expert = self._current_analysis and self._current_analysis.complexity == TaskComplexity.EXPERT

        context = ExecutionContext(
            task_input=task_input,
            agent_assignments=assignments,
            blackboard=blackboard or {},
            max_rounds=self._get_config("swarm_max_rounds", 6),
            invoke_agent=self._wrap_invoke_agent(),
            force_cot=is_expert,
        )

        executor = get_executor(mode)
        return executor.execute(context)

    def reset(self):
        """Reset engine state"""
        self.current_phase = SwarmPhase.IDLE
        self._current_analysis = None
        self._current_proposal = None
        self._negotiation_result = None

    def get_stats(self) -> dict:
        """Get swarm engine statistics"""
        mode_counts = {}
        for record in self.processing_history:
            mode = record["mode"]
            mode_counts[mode] = mode_counts.get(mode, 0) + 1

        return {
            "current_phase": self.current_phase.value,
            "total_processed": len(self.processing_history),
            "mode_distribution": mode_counts,
            "agent_pool_stats": self.agent_pool.get_pool_stats() if self.agent_pool else {},
            "mode_selector_stats": self.mode_selector.get_selection_stats(),
            "spawned_agents_count": self._count_spawned_agents(),
        }

    # === V7.9: Spawned Agent Integration ===

    def _discover_spawned_agents(self) -> int:
        """
        Discover and register spawned agents from workspace/agents/.

        V7.9: Auto-discovery at initialization.

        Returns:
            Number of agents discovered and registered
        """
        if not self.spawned_agent_loader or not self.agent_pool:
            return 0

        try:
            agents = self.spawned_agent_loader.discover_spawned_agents()
            for profile in agents:
                self.agent_pool.register(profile)
            return len(agents)
        except Exception as e:
            import sys

            print(f"[SWARM] Warning: Failed to discover spawned agents: {e}", file=sys.stderr)
            return 0

    def _count_spawned_agents(self) -> int:
        """Count spawned agents in the pool."""
        if not self.agent_pool:
            return 0

        return sum(1 for agent in self.agent_pool.agents.values() if agent.provider == "spawned")

    def _get_spawned_agents(self) -> list[AgentProfile]:
        """Get list of spawned agents from pool."""
        if not self.agent_pool:
            return []

        return [agent for agent in self.agent_pool.agents.values() if agent.provider == "spawned"]

    def should_suggest_spawning(self, analysis: TaskAnalysis) -> bool:
        """
        Check if spawning should be suggested for this task.

        V7.9: Suggest spawning for COMPLEX/EXPERT tasks when no suitable
        specialist exists in the pool.

        Args:
            analysis: Task analysis result

        Returns:
            True if spawning is recommended
        """
        # Only consider spawning for complex tasks
        if analysis.complexity not in [TaskComplexity.COMPLEX, TaskComplexity.EXPERT]:
            return False

        # Check if we have spawned specialists for the required domains
        spawned = self._get_spawned_agents()
        if not spawned:
            # No spawned agents - spawning might help
            return True

        # Check domain coverage
        required_domains = set(d.value for d in analysis.domains)
        covered_domains = set()
        for agent in spawned:
            covered_domains.update(c.lower() for c in agent.capabilities)

        # Suggest spawning if domains aren't covered
        return not required_domains.issubset(covered_domains)

    def get_spawning_suggestion(self, analysis: TaskAnalysis) -> dict | None:
        """
        Get spawning suggestion for a task.

        V7.9: Returns suggestion dict for user to spawn a specialist.

        Args:
            analysis: Task analysis result

        Returns:
            Dict with suggested agent configuration or None
        """
        if not self.should_suggest_spawning(analysis):
            return None

        # Build suggestion
        domains = [d.value for d in analysis.domains]
        primary = analysis.primary_domain.value if analysis.primary_domain else "general"

        return {
            "suggested": True,
            "reason": f"Task complexity ({analysis.complexity.name}) suggests spawning a specialist",
            "recommended_config": {
                "mission": f"Specialist for {primary} tasks",
                "domains": domains,
                "role": f"{primary}_specialist",
            },
            "command": f'/spawn "{primary}_expert" --mission "Expert for {", ".join(domains)}"',
        }
