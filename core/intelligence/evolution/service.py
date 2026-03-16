"""
NEXUS V9.1 - EvolutionService

Service Layer for Evolution operations.
Wraps EvolutionManager with UI output (console callbacks).

This service handles:
- Evolution cycle execution with progress UI
- Evolution status display
- Child review with interactive prompts
- Promotion and archival with progress feedback

Usage:
    from core.intelligence.evolution.service import EvolutionService

    service = EvolutionService(evolution_manager, console, config)
    service.evolve(child_count=3)
    service.status()
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.config import Config
    from core.intelligence.evolution.manager import EvolutionManager
    from core.interface_pkg.interface.console_v7 import ConsoleV7


@dataclass
class EvolutionServiceResult:
    """Result of an evolution service operation."""

    success: bool
    message: str | None = None
    error: str | None = None
    data: dict[str, Any] | None = None


class EvolutionService:
    """
    Service for Evolution Engine operations.

    Wraps EvolutionManager with console UI output.
    Extracted from InteractiveNexusV7 (repl.py) for proper separation of concerns.
    """

    def __init__(
        self,
        evolution_manager: EvolutionManager,
        console: ConsoleV7,
        config: Config,
        workspace_path: Path | None = None,
        rate_limiter: Any | None = None,
    ):
        """
        Initialize EvolutionService.

        Args:
            evolution_manager: The EvolutionManager instance
            console: Console for output
            config: Configuration object
            workspace_path: Path to workspace (for lineage)
            rate_limiter: Optional rate limiter instance
        """
        self.manager = evolution_manager
        self.console = console
        self.config = config
        self.workspace_path = workspace_path or evolution_manager.workspace_path
        self.rate_limiter = rate_limiter or evolution_manager.rate_limiter

    # ==================== PUBLIC API ====================

    def evolve(
        self,
        child_count: int = 3,
        auto_triggered: bool = False,
        focus_areas: list[str] | None = None,
    ) -> EvolutionServiceResult:
        """
        Run evolution cycle with UI feedback.

        Args:
            child_count: Number of children to create
            auto_triggered: True if triggered by 50-turn threshold
            focus_areas: Optional focus areas for mutations

        Returns:
            EvolutionServiceResult with cycle results
        """
        self.console.print("\n" + "=" * 60)
        self.console.print("🧬 EVOLUTION CYCLE STARTED")
        self.console.print("=" * 60)

        if auto_triggered:
            self.console.print("Trigger: Auto (50 successful turns)")
        else:
            self.console.print("Trigger: Manual (/evolve command)")

        self.console.print(f"Children to create: {child_count}")
        self.console.print("=" * 60 + "\n")

        # Check rate limits with UI feedback
        can_evolve, reason = self.rate_limiter.can_evolve(child_count)
        if not can_evolve:
            self.console.print(f"[red][NO] Evolution blocked: {reason}[/red]")
            self.console.print("\nRate limit statistics:")
            stats = self.rate_limiter.get_stats()
            self.console.print(
                f"  Today's evolutions: {stats['today_evolutions']}/{self.config.max_generations_per_day}"
            )
            self.console.print(f"  Remaining today: {stats['remaining_today']}")
            if "hours_since_last" in stats:
                self.console.print(f"  Hours since last: {stats['hours_since_last']}h")
                self.console.print(f"  Next evolution at: {stats['can_evolve_at']}")
            self.console.print("\nUse /evolve-status to see full statistics\n")
            return EvolutionServiceResult(success=False, error=reason)

        try:
            # Delegate to EvolutionManager
            result = self.manager.run_evolution_cycle(
                child_count=child_count,
                focus_areas=focus_areas,
            )

            # Display results
            if result.success:
                self.console.print("\n" + "=" * 60)
                self.console.print("[OK] ÉMERGENT EVOLUTION COMPLETE")
                self.console.print("=" * 60)
                self.console.print("\n📊 Summary:")
                self.console.print(f"  Mutations proposed: {result.mutations_proposed}")
                self.console.print(f"  Children created: {result.children_created}")
                self.console.print(f"  Children validated: {result.children_validated}")
                if result.winner_id:
                    self.console.print(f"  🏆 Winner: {result.winner_id}")
                    self.console.print(f"  📈 Fitness Score: {result.winner_score:.3f}")
                if result.promoted:
                    self.console.print("  [OK] Winner promoted to parent")
                self.console.print(f"\n  Duration: {result.duration_seconds:.1f}s")
                self.console.print("\nReview with: /review")
                self.console.print("Status with: /evolve-status\n")

                return EvolutionServiceResult(
                    success=True,
                    data={
                        "mutations_proposed": result.mutations_proposed,
                        "children_created": result.children_created,
                        "children_validated": result.children_validated,
                        "winner_id": result.winner_id,
                        "winner_score": result.winner_score,
                        "promoted": result.promoted,
                    },
                )
            else:
                self.console.print(f"\n[red][NO] Evolution failed at phase: {result.phase_reached}[/red]")
                for error in result.errors:
                    self.console.print(f"  - {error}")
                self.console.print("\nUse /evolve-status for more details.\n")

                return EvolutionServiceResult(
                    success=False, error=f"Failed at phase: {result.phase_reached}", data={"errors": result.errors}
                )

        except Exception as e:
            self.console.print_error(f"Evolution cycle failed: {e}")
            if getattr(self.config, "ui_verbose", False):
                import traceback

                traceback.print_exc()
            return EvolutionServiceResult(success=False, error=str(e))

    def status(self) -> EvolutionServiceResult:
        """
        Show evolution status with UI.

        Returns:
            EvolutionServiceResult with status data
        """
        from core.intelligence.evolution.lineage import get_evolution_stats, load_lineage

        try:
            lineage = load_lineage(self.workspace_path)
            parent = lineage["current_parent"]
            stats = get_evolution_stats(lineage)

            self.console.print("\n" + "=" * 60)
            self.console.print("🧬 EVOLUTION STATUS")
            self.console.print("=" * 60)
            self.console.print(f"\nCurrent Parent: {parent['id']}")
            self.console.print(f"Generation: {parent['generation']}")
            # V7.5: Support both old and new field names
            score = parent.get("fitness_score") or parent.get("asi_proximity_score", 0.7)
            self.console.print(f"Fitness Score: {score}")
            self.console.print(f"Activated: {parent['activated_at']}")
            self.console.print(f"\n{'-' * 60}")
            self.console.print("STATISTICS")
            self.console.print(f"{'-' * 60}")
            self.console.print(f"Total Generations: {stats['total_generations']}")
            self.console.print(f"Total Children Created: {stats['total_children_created']}")
            self.console.print(f"Successful Promotions: {stats['successful_promotions']}")
            self.console.print(f"\nStagnation Counter: {stats['stagnation_counter']}/3")

            if stats["stagnation_counter"] >= 2:
                self.console.print("[warning]️  WARNING: Approaching SURVIVAL_LAW threshold!")
            elif stats["stagnation_counter"] >= 3:
                self.console.print("🚨 CRITICAL: SURVIVAL_LAW triggered - human intervention required!")

            # Rate limiter statistics
            self.console.print(f"\n{'-' * 60}")
            self.console.print("RATE LIMITING")
            self.console.print(f"{'-' * 60}")
            rate_stats = self.rate_limiter.get_stats()
            self.console.print(f"Total Evolutions: {rate_stats['total_evolutions']}")
            self.console.print(f"Total Children Created: {rate_stats['total_children']}")
            self.console.print(
                f"Today's Evolutions: {rate_stats['today_evolutions']}/{self.config.max_generations_per_day}"
            )
            self.console.print(f"Remaining Today: {rate_stats['remaining_today']}")
            if "hours_since_last" in rate_stats:
                self.console.print(f"Hours Since Last Evolution: {rate_stats['hours_since_last']}h")
                self.console.print(f"Can Evolve Again At: {rate_stats['can_evolve_at']}")
            else:
                self.console.print("No evolutions recorded yet")

            self.console.print("=" * 60 + "\n")

            return EvolutionServiceResult(
                success=True,
                data={
                    "parent_id": parent["id"],
                    "generation": parent["generation"],
                    "fitness_score": score,
                    "stats": stats,
                    "rate_stats": rate_stats,
                },
            )

        except Exception as e:
            self.console.print_error(f"Failed to load evolution status: {e}")
            return EvolutionServiceResult(success=False, error=str(e))

    def promote(
        self,
        child_id: str,
        fitness_score: float,
        generation: int,
        child_metadata: dict[str, Any] | None = None,
    ) -> EvolutionServiceResult:
        """
        Promote a child to become new parent with UI feedback.

        Uses EvolutionManager.promote_child() which delegates to PromotePhase.

        Args:
            child_id: ID of child to promote
            fitness_score: Child's fitness score
            generation: Current generation number
            child_metadata: Optional additional metadata

        Returns:
            EvolutionServiceResult with promotion results
        """
        self.console.print(f"\n{'-' * 60}")
        self.console.print("🔄 PROMOTION IN PROGRESS")
        self.console.print(f"{'-' * 60}")

        # Define progress callback for UI output
        def progress_callback(message: str, progress: float):
            if "Archiving" in message:
                self.console.print(f"📦 {message}")
            elif "Promoting" in message:
                self.console.print(f"🚀 {message}")
            elif "Updating" in message:
                self.console.print(f"📝 {message}")
            elif "complete" in message.lower():
                self.console.print(f"[OK] {message}")

        # Temporarily set progress callback
        original_callback = self.manager.progress_callback
        self.manager.progress_callback = progress_callback

        try:
            result = self.manager.promote_child(
                child_id=child_id,
                fitness_score=fitness_score,
                generation=generation,
                child_metadata=child_metadata,
            )

            if result.success:
                self.console.print(f"\n{'-' * 60}")
                self.console.print("[OK] PROMOTION COMPLETE")
                self.console.print(f"{'-' * 60}")
                self.console.print(f"New active parent: {child_id}")
                self.console.print(f"Generation: {generation}")
                self.console.print(f"Fitness Score: {fitness_score:.3f}")

                return EvolutionServiceResult(
                    success=True,
                    data={
                        "child_id": child_id,
                        "generation": result.new_generation,
                        "backup_path": result.backup_path,
                    },
                )
            else:
                self.console.print_error(f"Promotion failed: {', '.join(result.errors)}")
                return EvolutionServiceResult(success=False, error="; ".join(result.errors))

        except Exception as e:
            self.console.print_error(f"Promotion failed: {e}")
            return EvolutionServiceResult(success=False, error=str(e))
        finally:
            self.manager.progress_callback = original_callback

    def archive(
        self,
        child_id: str,
        generation: int,
        reason: str = "manual_review_rejection",
        fitness_score: float = 0.0,
    ) -> EvolutionServiceResult:
        """
        Archive a rejected child with UI feedback.

        Uses EvolutionManager.archive_child() which delegates to PromotePhase.

        Args:
            child_id: ID of child to archive
            generation: Current generation number
            reason: Rejection reason
            fitness_score: Child's fitness score

        Returns:
            EvolutionServiceResult with archive results
        """
        self.console.print(f"Archiving rejected child: {child_id}")

        try:
            result = self.manager.archive_child(
                child_id=child_id,
                reason=reason,
                generation=generation,
                fitness_score=fitness_score,
            )

            if result.success:
                self.console.print(f"[OK] Moved to {result.archive_path}")
                self.console.print("[OK] Updated lineage with rejection record")

                return EvolutionServiceResult(
                    success=True,
                    data={
                        "child_id": child_id,
                        "archive_path": result.archive_path,
                    },
                )
            else:
                self.console.print_error(f"Archival failed: {result.reason}")
                return EvolutionServiceResult(success=False, error=result.reason)

        except Exception as e:
            self.console.print_error(f"Archival failed: {e}")
            return EvolutionServiceResult(success=False, error=str(e))


def _get_evolution_service(context) -> EvolutionService:
    """
    Get or create EvolutionService from command context.

    Helper function for command implementations.
    """
    # Try to get cached service
    service = context.extras.get("evolution_service")
    if service:
        return service

    # Get required dependencies
    evolution_manager = context.extras.get("evolution_manager")
    if not evolution_manager:
        # Try to get from repl
        repl = context.extras.get("repl")
        if repl and hasattr(repl, "evolution_manager"):
            evolution_manager = repl.evolution_manager
        else:
            raise RuntimeError("EvolutionManager not available in context")

    console = context.console
    config = context.config or getattr(context.orchestrator, "config", None)

    # Get workspace_path and rate_limiter
    workspace_path = context.extras.get("workspace_path")
    rate_limiter = context.extras.get("rate_limiter")

    if not workspace_path and hasattr(evolution_manager, "workspace_path"):
        workspace_path = evolution_manager.workspace_path
    if not rate_limiter and hasattr(evolution_manager, "rate_limiter"):
        rate_limiter = evolution_manager.rate_limiter

    return EvolutionService(
        evolution_manager=evolution_manager,
        console=console,
        config=config,
        workspace_path=workspace_path,
        rate_limiter=rate_limiter,
    )
