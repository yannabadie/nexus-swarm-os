"""
NEXUS V8.0 - User Interaction Handler

Handles user breakpoints with rich CLI interface.
Provides clear menus for user decisions at critical points.

Features:
- Rich console UI with panels and menus
- Timeout handling with default actions
- Breakpoint history tracking
- Custom input support
- V9.8 DETOX: Headless mode via InteractionProvider

Usage:
    handler = UserInteractionHandler()

    # At a breakpoint
    response = await handler.request_breakpoint(
        breakpoint_type=UserBreakpoint.BEFORE_SPAWN,
        context="About to spawn 3 new agents...",
        recommendation="Proceed with spawn",
        options=[
            BreakpointOption("proceed", "Proceed", "Spawn all agents"),
            BreakpointOption("modify", "Modify", "Change spawn config"),
            BreakpointOption("cancel", "Cancel", "Skip spawning"),
        ]
    )

    if response.chosen_option == "proceed":
        spawn_agents()
"""

import asyncio
import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from core.security_pkg.interaction import InteractionProvider

# Try to import rich for better UI, fallback to basic input
try:
    from rich.box import ROUNDED
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.prompt import Confirm, Prompt
    from rich.table import Table

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

from .types import BreakpointOption, BreakpointRequest, BreakpointResponse, UserBreakpoint

logger = logging.getLogger(__name__)


class UserInteractionHandler:
    """
    Handles user interaction at breakpoints with rich UI.

    Supports:
    - Interactive CLI menus
    - Timeout with default action
    - Custom input
    - Breakpoint history
    """

    def __init__(
        self,
        default_timeout: int = 60,
        enable_rich: bool = True,
        auto_accept: bool = False,
        interaction: Optional["InteractionProvider"] = None,
    ):
        """
        Initialize user interaction handler.

        Args:
            default_timeout: Default timeout for breakpoints (seconds)
            enable_rich: Use rich console if available
            auto_accept: Auto-accept recommendations (for testing)
            interaction: V9.8 DETOX - Optional interaction provider for headless mode
        """
        self.default_timeout = default_timeout
        self.auto_accept = auto_accept
        self._history: list[BreakpointResponse] = []
        self._interaction = interaction

        # Initialize console
        if enable_rich and RICH_AVAILABLE:
            self.console = Console()
            self._use_rich = True
        else:
            self.console = None
            self._use_rich = False

    def request_breakpoint_sync(
        self,
        breakpoint_type: UserBreakpoint,
        context: str,
        recommendation: str,
        options: list[BreakpointOption],
        timeout_seconds: int = None,
        metadata: dict = None,
    ) -> BreakpointResponse:
        """
        Synchronous breakpoint request (for non-async contexts).

        Args:
            breakpoint_type: Type of breakpoint
            context: Context information to display
            recommendation: Recommended action
            options: Available options
            timeout_seconds: Timeout (defaults to default_timeout)
            metadata: Additional metadata

        Returns:
            BreakpointResponse with user's choice
        """
        request = BreakpointRequest(
            breakpoint_type=breakpoint_type,
            context=context,
            recommendation=recommendation,
            options=options,
            timeout_seconds=timeout_seconds or self.default_timeout,
            metadata=metadata or {},
        )

        # Auto-accept mode (for testing)
        if self.auto_accept:
            recommended = next((opt for opt in options if opt.is_recommended), options[0] if options else None)
            response = BreakpointResponse(
                breakpoint_type=breakpoint_type,
                chosen_option=recommended.id if recommended else "accept",
                was_timeout=True,
            )
            self._history.append(response)
            return response

        # V9.8 DETOX: Check for headless mode via InteractionProvider
        if self._interaction is not None and not self._interaction.is_interactive:
            return self._headless_breakpoint(request)

        # Display and get input
        if self._use_rich:
            return self._rich_breakpoint(request)
        else:
            return self._basic_breakpoint(request)

    def _headless_breakpoint(self, request: BreakpointRequest) -> BreakpointResponse:
        """
        Handle breakpoint in headless mode (V9.8 DETOX).

        Returns recommended option without blocking.
        Logs the breakpoint for audit trail.
        """
        import logging

        logger = logging.getLogger("nexus.interaction.headless")

        # Log the breakpoint
        logger.info(f"[HEADLESS BREAKPOINT] Type: {request.breakpoint_type.value}")
        logger.debug(f"[HEADLESS BREAKPOINT] Context: {request.context[:200]}...")
        logger.info(f"[HEADLESS BREAKPOINT] Recommendation: {request.recommendation}")

        # Get recommended option
        recommended = next(
            (opt for opt in request.options if opt.is_recommended), request.options[0] if request.options else None
        )

        response = BreakpointResponse(
            breakpoint_type=request.breakpoint_type,
            chosen_option=recommended.id if recommended else "accept",
            was_timeout=False,  # Not a timeout, deliberate headless choice
        )

        logger.info(f"[HEADLESS BREAKPOINT] Auto-selected: {response.chosen_option}")
        self._history.append(response)
        return response

    async def request_breakpoint(
        self,
        breakpoint_type: UserBreakpoint,
        context: str,
        recommendation: str,
        options: list[BreakpointOption],
        timeout_seconds: int = None,
        metadata: dict = None,
    ) -> BreakpointResponse:
        """
        Async breakpoint request with timeout.

        Args:
            breakpoint_type: Type of breakpoint
            context: Context information to display
            recommendation: Recommended action
            options: Available options
            timeout_seconds: Timeout (defaults to default_timeout)
            metadata: Additional metadata

        Returns:
            BreakpointResponse with user's choice
        """
        timeout = timeout_seconds or self.default_timeout

        try:
            # Run sync version with timeout
            # V12.4 FIX F19: Use get_running_loop() instead of deprecated get_event_loop()
            response = await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(
                    None,
                    lambda: self.request_breakpoint_sync(
                        breakpoint_type, context, recommendation, options, timeout, metadata
                    ),
                ),
                timeout=timeout,
            )
            return response
        except TimeoutError:
            # Return default action on timeout
            recommended = next((opt for opt in options if opt.is_recommended), options[0] if options else None)
            response = BreakpointResponse(
                breakpoint_type=breakpoint_type,
                chosen_option=recommended.id if recommended else "accept",
                was_timeout=True,
            )
            self._history.append(response)

            if self._use_rich:
                self.console.print(
                    f"[yellow]Timeout reached. Using default action: "
                    f"{recommended.label if recommended else 'accept'}[/yellow]"
                )

            return response

    def _rich_breakpoint(self, request: BreakpointRequest) -> BreakpointResponse:
        """Handle breakpoint with rich UI."""
        # Header with breakpoint type
        title = f"BREAKPOINT: {request.breakpoint_type.value.replace('_', ' ').title()}"
        self.console.print()
        self.console.rule(f"[bold cyan]{title}[/bold cyan]")

        # Context panel
        self.console.print(Panel(Markdown(request.context), title="Context", border_style="blue", box=ROUNDED))

        # Recommendation
        self.console.print(
            Panel(
                f"[bold green]Recommendation:[/bold green] {request.recommendation}", border_style="green", box=ROUNDED
            )
        )

        # Options table
        table = Table(title="Available Options", box=ROUNDED)
        table.add_column("Key", style="cyan", width=6)
        table.add_column("Option", style="white")
        table.add_column("Description", style="dim")

        for i, opt in enumerate(request.options, 1):
            style = "bold green" if opt.is_recommended else ""
            recommended_mark = " *" if opt.is_recommended else ""
            table.add_row(f"[{i}]", f"{opt.label}{recommended_mark}", opt.description, style=style)
        table.add_row("[c]", "Custom", "Enter custom response")

        self.console.print(table)

        # Timeout info
        self.console.print(
            f"[dim]Timeout: {request.timeout_seconds}s (will use recommended option if no response)[/dim]"
        )

        # Get user input
        while True:
            choice = Prompt.ask(
                "Your choice", choices=[str(i) for i in range(1, len(request.options) + 1)] + ["c"], default="1"
            )

            if choice == "c":
                custom = Prompt.ask("Enter custom response")
                response = BreakpointResponse(
                    breakpoint_type=request.breakpoint_type, chosen_option="custom", custom_input=custom
                )
            else:
                idx = int(choice) - 1
                response = BreakpointResponse(
                    breakpoint_type=request.breakpoint_type, chosen_option=request.options[idx].id
                )

            # Confirm
            if Confirm.ask("Confirm this choice?", default=True):
                break

        self._history.append(response)
        self.console.print(f"[green]Selected: {response.chosen_option}[/green]")
        self.console.rule()
        self.console.print()

        return response

    def _basic_breakpoint(self, request: BreakpointRequest) -> BreakpointResponse:
        """Handle breakpoint with basic input (fallback)."""
        print("\n" + "=" * 60)
        print(f"BREAKPOINT: {request.breakpoint_type.value}")
        print("=" * 60)
        print(f"\nContext:\n{request.context}")
        print(f"\nRecommendation: {request.recommendation}")
        print("\nOptions:")

        for i, opt in enumerate(request.options, 1):
            recommended = " (RECOMMENDED)" if opt.is_recommended else ""
            print(f"  [{i}] {opt.label}: {opt.description}{recommended}")
        print("  [c] Custom: Enter custom response")

        print(f"\nTimeout: {request.timeout_seconds}s")

        while True:
            try:
                choice = input("\nYour choice: ").strip().lower()

                if choice == "c":
                    custom = input("Enter custom response: ")
                    response = BreakpointResponse(
                        breakpoint_type=request.breakpoint_type, chosen_option="custom", custom_input=custom
                    )
                elif choice.isdigit() and 1 <= int(choice) <= len(request.options):
                    idx = int(choice) - 1
                    response = BreakpointResponse(
                        breakpoint_type=request.breakpoint_type, chosen_option=request.options[idx].id
                    )
                else:
                    print("Invalid choice. Try again.")
                    continue

                confirm = input("Confirm? (y/n): ").strip().lower()
                if confirm in ("y", "yes", ""):
                    break
            except (EOFError, KeyboardInterrupt):
                # Default on interrupt
                recommended = next(
                    (opt for opt in request.options if opt.is_recommended),
                    request.options[0] if request.options else None,
                )
                response = BreakpointResponse(
                    breakpoint_type=request.breakpoint_type,
                    chosen_option=recommended.id if recommended else "accept",
                    was_timeout=True,
                )
                break

        self._history.append(response)
        print(f"\nSelected: {response.chosen_option}")
        print("=" * 60 + "\n")

        return response

    # Convenience methods for specific breakpoints

    def after_debate(self, debate_summary: str, final_approach: str, consensus_score: float) -> BreakpointResponse:
        """Breakpoint after debate phase."""
        context = f"""
## Debate Summary

{debate_summary}

## Final Approach

{final_approach}

## Consensus Score: {consensus_score:.0%}
"""
        options = [
            BreakpointOption(
                id="accept",
                label="Accept",
                description="Proceed with the debated approach",
                is_recommended=consensus_score >= 0.7,
            ),
            BreakpointOption(id="modify", label="Modify", description="Request modifications to the approach"),
            BreakpointOption(
                id="restart", label="Restart Debate", description="Restart the debate with additional guidance"
            ),
            BreakpointOption(id="cancel", label="Cancel", description="Cancel the task"),
        ]

        return self.request_breakpoint_sync(
            breakpoint_type=UserBreakpoint.AFTER_DEBATE,
            context=context,
            recommendation="Accept the debated approach"
            if consensus_score >= 0.7
            else "Review carefully - low consensus",
            options=options,
        )

    def before_spawn(self, agents_to_spawn: list[dict], estimated_cost: int) -> BreakpointResponse:
        """Breakpoint before spawning agents."""
        agent_list = "\n".join(
            f"- **{a['role']}**: {a.get('mission', 'N/A')} (capabilities: {', '.join(a.get('capabilities', []))})"
            for a in agents_to_spawn
        )

        context = f"""
## Agents to Spawn

{agent_list}

## Estimated Cost: {estimated_cost} tokens
"""
        options = [
            BreakpointOption(
                id="spawn_all",
                label="Spawn All",
                description="Spawn all proposed agents",
                is_recommended=len(agents_to_spawn) <= 2,
            ),
            BreakpointOption(id="spawn_selective", label="Select Agents", description="Choose which agents to spawn"),
            BreakpointOption(id="skip", label="Skip Spawning", description="Continue without spawning new agents"),
            BreakpointOption(id="cancel", label="Cancel", description="Cancel the task"),
        ]

        return self.request_breakpoint_sync(
            breakpoint_type=UserBreakpoint.BEFORE_SPAWN,
            context=context,
            recommendation=f"Spawn {len(agents_to_spawn)} agent(s)",
            options=options,
        )

    def after_diagnosis(self, failure_type: str, root_cause: str, recommended_changes: list[str]) -> BreakpointResponse:
        """Breakpoint after failure diagnosis."""
        changes_list = "\n".join(f"- {c}" for c in recommended_changes)

        context = f"""
## Failure Analysis

**Type:** {failure_type}

**Root Cause:** {root_cause}

## Recommended Changes

{changes_list}
"""
        options = [
            BreakpointOption(id="retry", label="Retry", description="Apply changes and retry", is_recommended=True),
            BreakpointOption(id="modify_changes", label="Modify", description="Modify the recommended changes"),
            BreakpointOption(id="escalate", label="Escalate", description="Stop and request human intervention"),
            BreakpointOption(id="abort", label="Abort", description="Abort the task entirely"),
        ]

        return self.request_breakpoint_sync(
            breakpoint_type=UserBreakpoint.AFTER_DIAGNOSIS,
            context=context,
            recommendation="Apply changes and retry",
            options=options,
        )

    def knowledge_consolidation(
        self, learned_patterns: list[str], agents_to_retain: list[dict], knowledge_to_archive: list[str]
    ) -> BreakpointResponse:
        """Breakpoint for knowledge consolidation decisions."""
        patterns_list = "\n".join(f"- {p}" for p in learned_patterns)
        agents_list = "\n".join(f"- **{a['agent_id']}**: {a.get('reason', 'N/A')}" for a in agents_to_retain)
        knowledge_list = "\n".join(f"- {k}" for k in knowledge_to_archive)

        context = f"""
## Learned Patterns

{patterns_list if patterns_list else "None identified"}

## Agents to Retain

{agents_list if agents_list else "None proposed for retention"}

## Knowledge to Archive

{knowledge_list if knowledge_list else "None proposed for archival"}
"""
        options = [
            BreakpointOption(
                id="accept_all",
                label="Accept All",
                description="Accept all consolidation recommendations",
                is_recommended=True,
            ),
            BreakpointOption(id="selective", label="Selective", description="Review and select what to keep"),
            BreakpointOption(id="skip", label="Skip", description="Skip consolidation entirely"),
        ]

        return self.request_breakpoint_sync(
            breakpoint_type=UserBreakpoint.KNOWLEDGE_CONSOLIDATION,
            context=context,
            recommendation="Accept all consolidation recommendations",
            options=options,
        )

    # History and stats

    def get_history(self) -> list[BreakpointResponse]:
        """Get breakpoint response history."""
        return self._history.copy()

    def clear_history(self):
        """Clear breakpoint history."""
        self._history.clear()

    def get_stats(self) -> dict:
        """Get interaction statistics."""
        if not self._history:
            return {"total_breakpoints": 0}

        by_type = {}
        timeouts = 0
        custom_inputs = 0

        for response in self._history:
            bp_type = response.breakpoint_type.value
            by_type[bp_type] = by_type.get(bp_type, 0) + 1
            if response.was_timeout:
                timeouts += 1
            if response.custom_input:
                custom_inputs += 1

        return {
            "total_breakpoints": len(self._history),
            "by_type": by_type,
            "timeouts": timeouts,
            "custom_inputs": custom_inputs,
            "timeout_rate": timeouts / len(self._history) if self._history else 0,
        }
