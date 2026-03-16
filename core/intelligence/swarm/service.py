"""
NEXUS V9.1 - SwarmService

Service Layer for Hybrid Swarm Engine operations.
Extracted from repl.py to enable proper separation of concerns.

This service handles:
- Task execution via swarm
- Swarm status queries
- FSM-based swarm execution (debug)

Usage:
    from core.intelligence.swarm.service import SwarmService

    service = SwarmService(orchestrator, console, config)
    service.run_task("Analyze this codebase")
    status = service.get_status()
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.config import Config
    from core.interface_pkg.interface.console_v7 import ConsoleV7
    from core.orchestration_v7 import OrchestratorV7


@dataclass
class SwarmResult:
    """Result of a swarm task execution."""

    success: bool
    mode: str | None = None
    state: str | None = None
    analysis: dict[str, Any] | None = None
    error: str | None = None


@dataclass
class SwarmStatus:
    """Status of the swarm engine."""

    enabled: bool
    total_tasks: int = 0
    successful: int = 0
    failed: int = 0
    mode_distribution: dict[str, int] | None = None
    auto_route: bool = False


class SwarmService:
    """
    Service for Hybrid Swarm Engine operations.

    Handles task execution, status queries, and FSM-based debugging.
    Extracted from InteractiveNexusV7 (repl.py) for proper separation of concerns.
    """

    COLLABORATION_MODES = ["PARALLEL", "SEQUENTIAL", "LEAD_SUPPORT", "PING_PONG", "SPECIALIST", "RED_BLUE"]

    def __init__(self, orchestrator: OrchestratorV7, console: ConsoleV7, config: Config):
        """
        Initialize SwarmService.

        Args:
            orchestrator: The NEXUS orchestrator instance
            console: Console for output
            config: Configuration object
        """
        self.orchestrator = orchestrator
        self.console = console
        self.config = config

    # ==================== PUBLIC API ====================

    def run_task(
        self, task: str, on_negotiation_turn: Callable | None = None, on_execution_round: Callable | None = None
    ) -> SwarmResult:
        """
        Execute task via Hybrid Swarm Engine.

        Routes the task through the 6-mode collaboration system:
        - PARALLEL, SEQUENTIAL, LEAD_SUPPORT, PING_PONG, SPECIALIST, RED_BLUE

        Args:
            task: Task description from user
            on_negotiation_turn: Optional callback for negotiation updates
            on_execution_round: Optional callback for execution updates

        Returns:
            SwarmResult with execution status and results
        """
        if not self.orchestrator.swarm_engine:
            self.console.print_error("Swarm engine not initialized")
            self.console.print("Enable with SWARM_ENABLED=True in .env")
            return SwarmResult(success=False, error="Swarm engine not initialized")

        self.console.print("\n" + "=" * 60)
        self.console.print("[bee] HYBRID SWARM ENGINE")
        self.console.print("=" * 60)
        self.console.print(f"Task: {task[:100]}{'...' if len(task) > 100 else ''}")
        self.console.print("Analyzing task and negotiating collaboration mode...\n")

        # Create default callbacks if not provided
        if on_negotiation_turn is None:
            on_negotiation_turn = self._default_negotiation_callback
        if on_execution_round is None:
            on_execution_round = self._default_execution_callback

        try:
            result = self.orchestrator.process_with_swarm(
                task, on_negotiation_turn=on_negotiation_turn, on_execution_round=on_execution_round
            )

            # Display final results
            self.console.print(f"\n{'=' * 60}")
            self.console.print("[chart] SWARM RESULT")
            self.console.print(f"{'=' * 60}")
            self.console.print(f"Mode: {result.get('mode', 'N/A')}")
            self.console.print(f"Status: {result.get('state', 'N/A')}")

            # Show analysis summary if available
            if result.get("analysis"):
                analysis = result["analysis"]
                self.console.print(f"Complexity: {analysis.get('complexity', 'N/A')}")
                self.console.print(f"Domains: {', '.join(analysis.get('domains', []))}")

            self.console.print("=" * 60 + "\n")

            return SwarmResult(
                success=True, mode=result.get("mode"), state=result.get("state"), analysis=result.get("analysis")
            )

        except Exception as e:
            self.console.print_error(f"Swarm execution failed: {e}")
            if getattr(self.config, "ui_verbose", False):
                import traceback

                traceback.print_exc()
            return SwarmResult(success=False, error=str(e))

    def run_task_fsm(self, task: str) -> SwarmResult:
        """
        Execute task via FSM states (debug mode).

        Uses the FSM path: SWARM_ANALYZING -> SWARM_NEGOTIATING -> SWARM_EXECUTING

        Args:
            task: Task description from user

        Returns:
            SwarmResult with execution status
        """
        if not self.orchestrator.swarm_engine:
            self.console.print_error("Swarm engine not initialized")
            self.console.print("Enable with SWARM_ENABLED=True in .env")
            return SwarmResult(success=False, error="Swarm engine not initialized")

        self.console.print("\n" + "=" * 60)
        self.console.print("[bee] HYBRID SWARM ENGINE (FSM Mode)")
        self.console.print("=" * 60)
        self.console.print(f"Task: {task[:100]}{'...' if len(task) > 100 else ''}")
        self.console.print("Using FSM states (debug mode)...\n")

        try:
            # Start swarm via FSM
            result = self.orchestrator.start_swarm_mode(task)
            self.console.print(f"[FSM] State: {result.get('state')}")
            self.console.print(f"[FSM] {result.get('output', '')}\n")

            # Process through FSM states until done
            max_iterations = 20
            final_state = result.get("state", "UNKNOWN")

            for i in range(max_iterations):
                step_result = self.orchestrator.step()

                final_state = step_result.get("state", "UNKNOWN")
                output = step_result.get("output", "")

                self.console.print(f"[FSM {i + 1}] State: {final_state}")
                if output:
                    limit = getattr(self.config, "console_output_limit", 500)
                    self.console.print(f"{output[:limit]}{'...' if len(output) > limit else ''}\n")

                # Check if finished
                if step_result.get("finished") or final_state in ["IDLE", "WAITING_USER", "ERROR"]:
                    break

            self.console.print("=" * 60 + "\n")

            return SwarmResult(success=True, state=final_state)

        except Exception as e:
            self.console.print_error(f"Swarm FSM execution failed: {e}")
            if getattr(self.config, "ui_verbose", False):
                import traceback

                traceback.print_exc()
            return SwarmResult(success=False, error=str(e))

    def get_status(self) -> SwarmStatus:
        """
        Get Hybrid Swarm Engine status and metrics.

        Returns:
            SwarmStatus with engine state and statistics
        """
        self.console.print("\n" + "=" * 60)
        self.console.print("[bee] SWARM ENGINE STATUS")
        self.console.print("=" * 60)

        if not self.orchestrator.swarm_engine:
            self.console.print("\n[warning]  Swarm Engine: DISABLED")
            self.console.print("   Enable with SWARM_ENABLED=True in .env")
            self.console.print("=" * 60 + "\n")
            return SwarmStatus(enabled=False)

        self.console.print("\n[checkmark] Swarm Engine: ENABLED")

        # Get swarm stats
        stats = SwarmStatus(enabled=True)
        try:
            raw_stats = self.orchestrator.swarm_engine.get_stats()

            self.console.print(f"\n{'-' * 60}")
            self.console.print("COLLABORATION MODES")
            self.console.print(f"{'-' * 60}")
            for mode in self.COLLABORATION_MODES:
                self.console.print(f"  - {mode}")

            if raw_stats:
                stats.total_tasks = raw_stats.get("total_tasks", 0)
                stats.successful = raw_stats.get("successful", 0)
                stats.failed = raw_stats.get("failed", 0)
                stats.mode_distribution = raw_stats.get("mode_distribution")

                self.console.print(f"\n{'-' * 60}")
                self.console.print("EXECUTION STATISTICS")
                self.console.print(f"{'-' * 60}")
                self.console.print(f"Total Tasks Processed: {stats.total_tasks}")
                self.console.print(f"Successful: {stats.successful}")
                self.console.print(f"Failed: {stats.failed}")

                # Mode distribution
                if stats.mode_distribution:
                    self.console.print(f"\n{'-' * 60}")
                    self.console.print("MODE DISTRIBUTION")
                    self.console.print(f"{'-' * 60}")
                    for mode, count in stats.mode_distribution.items():
                        self.console.print(f"  {mode}: {count}")

        except Exception as e:
            self.console.print(f"\n[warning]  Could not retrieve stats: {e}")

        # Auto-route setting
        stats.auto_route = getattr(self.config, "swarm_auto_route", False)
        self.console.print(f"\n{'-' * 60}")
        self.console.print("CONFIGURATION")
        self.console.print(f"{'-' * 60}")
        self.console.print(f"Auto-Route (MODERATE+ tasks): {'ON' if stats.auto_route else 'OFF'}")
        self.console.print("  Set SWARM_AUTO_ROUTE=True in .env to enable")
        self.console.print("=" * 60 + "\n")

        return stats

    # ==================== PRIVATE HELPERS ====================

    def _default_negotiation_callback(self, message) -> None:
        """Default callback for negotiation turns."""
        from core.foundation.agents import get_registry

        registry = get_registry()
        agent = registry.get_display_name(message.sender)
        self.console.print(f"\n{'-' * 40}")
        self.console.print(f"[NEGOTIATION] {agent} (Turn {message.turn_number + 1})")
        self.console.print(f"{'-' * 40}")

        # Show natural content (truncated based on config)
        limit = getattr(self.config, "console_output_limit", 500)
        content = message.natural_content[:limit] if message.natural_content else ""
        self.console.print(content + ("..." if len(message.natural_content or "") > limit else ""))

        # Show structured proposal if present
        if message.structured_proposal:
            prop = message.structured_proposal
            if prop.proposed_mode:
                self.console.print(f"  -> Proposes: {prop.proposed_mode}")
            if prop.agrees_with_partner:
                self.console.print("  -> Agrees with partner: Yes")
            if prop.consensus_reached:
                self.console.print("  [checkmark] CONSENSUS REACHED")

    def _default_execution_callback(self, round_num: int, response) -> None:
        """Default callback for execution rounds."""
        from core.foundation.agents import get_registry

        registry = get_registry()
        agent = registry.get_display_name(response.agent_id)
        self.console.print(f"\n{'-' * 40}")
        self.console.print(f"[EXECUTION] Round {round_num + 1} - {agent}")
        self.console.print(f"{'-' * 40}")

        # Show content (truncated based on config)
        limit = getattr(self.config, "console_output_limit", 500)
        content = response.content[:limit] if response.content else ""
        self.console.print(content + ("..." if len(response.content or "") > limit else ""))

        if response.status == "error":
            self.console.print(f"  [warning]  Error: {response.error}")
