"""
REPL Interface V7 - Persistent Orchestrator

Le REPL crée l'orchestrateur UNE FOIS et le garde en mémoire
toute la session (persistent FSM architecture)
"""

import os
import sys
from pathlib import Path

# Fix VS Code terminal on Windows: unset TERM to let prompt_toolkit auto-detect
if sys.platform == "win32" and os.environ.get("TERM") == "xterm-256color":
    del os.environ["TERM"]

import asyncio
from contextlib import nullcontext

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout

from core.config import load_config
from core.fsm.states import OrchestratorState
from core.intelligence.evolution import AutoPromotionDecision, ChildValidator
from core.intelligence.evolution.manager import EvolutionManager  # V7.5 Phase 0a: Central evolution orchestrator
from core.intelligence.evolution.rate_limiter import EvolutionRateLimiter
from core.interface_pkg.interface.commands import (
    SLASH_COMMANDS,
    CommandContext,
    CommandStatus,
    get_help_message,
    # V9: Command Pattern
    get_initialized_registry,
    is_exit_command,
    is_slash_command,
    parse_command,
)
from core.runtime import NexusSessionRuntime
from core.ui.console_v7 import ConsoleV7


class InteractiveNexusV7:
    """
    REPL persistant pour NEXUS V7

    Features:
    - Orchestrator créé UNE FOIS (vit toute la session)
    - Historique des commandes (prompt_toolkit)
    - Slash commands: /mode, /clear, /status, /doctor, /reset
    """

    def __init__(self, workspace_path: Path, gemini_info: dict, claude_info: dict):
        self.workspace_path = workspace_path
        self.config = load_config()

        # Calculate NEXUS root path robustly (with validation)
        self.nexus_root = self._calculate_nexus_root()

        # Create orchestrator ONCE via the shared session runtime facade.
        self.runtime = NexusSessionRuntime(workspace_path, self.config, gemini_info, claude_info)
        self.orchestrator = self.runtime.orchestrator

        # UI
        self.console = ConsoleV7(verbose=self.config.ui_verbose)

        # Prompt toolkit session with fallback for non-interactive terminals
        history_file = workspace_path / ".nexus" / "history.txt"
        self.session = None
        self._use_simple_input = False

        try:
            self.session = PromptSession(history=FileHistory(str(history_file)))
        except Exception as e:
            # Fallback for VS Code terminal, piped input, or other non-standard terminals
            print(f"[INFO] prompt_toolkit unavailable ({type(e).__name__}), using simple input mode")
            self._use_simple_input = True

        # Evolution tracking
        self.successful_turns = 0  # Counter for auto-evolution trigger
        self.evolution_trigger_threshold = 50  # Trigger evolution after N successful turns

        # Rate limiter for evolution cycles
        self.rate_limiter = EvolutionRateLimiter(workspace_path, self.config)

        # V7.5 Phase 0a: EvolutionManager - Central orchestrator for evolution
        self.evolution_manager = EvolutionManager(
            workspace_path=workspace_path,
            nexus_root=self.nexus_root,
            config=self.config,
            orchestrator=self.orchestrator,
            rate_limiter=self.rate_limiter,
            progress_callback=self._evolution_progress_callback,
        )

        # Abort flag for graceful shutdown of long-running operations
        self._abort_requested = False

        # V7.7 Phase 15: Set up streaming callback if enabled
        self._streaming_active = False  # Track if we're currently streaming
        if getattr(self.config, "streaming_enabled", False):
            self.orchestrator.on_token = self._stream_token
        self.orchestrator.on_agent_status = self._display_runtime_event

    def _get_input(self, prompt: str = "nexus7> ") -> str:
        """Get user input with fallback for non-interactive terminals."""
        if self._use_simple_input:
            try:
                return input(prompt)
            except EOFError:
                return "/exit"
        else:
            return self.session.prompt(prompt)

    def _evolution_progress_callback(self, message: str, progress: float):
        """Callback for EvolutionManager progress updates."""
        # Display progress bar if console supports it
        progress_pct = int(progress * 100)
        bar_width = 30
        filled = int(bar_width * progress)
        bar = "█" * filled + "░" * (bar_width - filled)
        self.console.print(f"[dim][{bar}] {progress_pct}%[/dim] {message}")

    def _stream_token(self, token: str) -> None:
        """
        Callback for streaming tokens to console (V7.7 Phase 15).

        Called by orchestrator's invoke_stream for each text chunk.
        Prints tokens in real-time without newline, then flushes.
        """
        if token:
            print(token, end="", flush=True)
            self._streaming_active = True

    def _display_runtime_event(self, event: dict[str, str]) -> None:
        """Display runtime activity events emitted by the orchestrator."""
        self.console.print_activity(event)

    def run(self):
        """Main REPL loop"""
        # Clear previous session state at startup (fresh start)
        # This prevents stale objectives from previous sessions
        self.orchestrator.reset_to_idle(clear_task=True)

        self.console.print_banner(
            gemini_model=self.orchestrator.gemini_info["model"],
            claude_model=self.orchestrator.claude_info["model"],
            version=self.config.nexus_version,
            codename=self.config.nexus_codename,
        )
        self.console.print_runtime_plan(self.config.provider_snapshot)

        # V7 Sprint 11: Display startup hints (bootstrap, swarm status)
        hints = self.orchestrator.get_startup_hints()
        if hints:
            self.console.print("")
            for hint in hints:
                self.console.print(f"  {hint}")
            self.console.print("")

        while True:
            try:
                # Get user input
                user_input = self._get_input("nexus7> ")

                # Sanitize input: strip ANSI escape sequences that can corrupt objectives
                # Escape sequences like 0~, [D, ESC[ can leak from terminal on Windows
                import re

                user_input = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", user_input)  # ESC[...X sequences
                user_input = re.sub(r"[0-9]+~", "", user_input)  # 0~ type sequences (Insert, Home, etc.)
                user_input = re.sub(r"\[\w\]?", "", user_input)  # Orphan [D, [A sequences
                user_input = user_input.strip()

                if not user_input:
                    continue

                # Handle slash commands
                if is_slash_command(user_input):
                    self.handle_command(user_input)
                    continue

                # Handle exit
                if is_exit_command(user_input):
                    self._abort_requested = True  # Signal any running operations to stop
                    self.console.print("👋 Goodbye!")
                    break

                # Process turn with orchestrator
                result = self.orchestrator.process_turn(user_input)
                self.console.display_result(result)

                # Continue processing until exit conditions
                # V7 UX FIX: After each full exchange (2 turns), check if user wants to interject
                # Ctrl+C always works for immediate interruption
                max_iterations = 50  # Safety limit
                iterations = 0
                tool_active = False  # Extends the limit when tools are being used

                while result["state"] not in ["IDLE", "ERROR", "PANIC", "FINISHED"] and iterations < max_iterations:
                    # Check for abort signal (set by exit command)
                    if self._abort_requested:
                        self.console.print("🛑 Abort requested - stopping")
                        break
                    result = self.orchestrator.process_turn()
                    self.console.display_result(result)
                    iterations += 1

                    # Track if tools are being used (complex task)
                    if result.get("state") == "EXECUTING_TOOL":
                        tool_active = True

                    # V7.1 Balanced Autonomy: Visual checkpoint every 10 turns (no blocking)
                    # Agents iterate freely, user can Ctrl+C to interrupt anytime
                    if iterations > 0 and iterations % 10 == 0:
                        state = result.get("state", "UNKNOWN")
                        self.console.print(f"[dim]--- Iteration {iterations} | State: {state} ---[/dim]")
                        tool_active = False  # Reset tool tracking

                    # Prompt user only in specific cases:
                    # 1. Approaching max iterations (warning at 48)
                    # 2. Agent explicitly needs input
                    # 3. Error state detected
                    needs_user_prompt = (
                        result.get("needs_user_input", False)
                        or result.get("state") == "ERROR"
                        or iterations >= (max_iterations - 2)  # Warning before limit
                    )

                    if needs_user_prompt and not tool_active:
                        self.console.print("[yellow]--- User input needed (or press Enter to continue) ---[/yellow]")
                        try:
                            user_input = input().strip()
                            if user_input:
                                # User wants to interject - add their message to context
                                self.console.print(f"[bold green]You:[/bold green] {user_input}")
                                # Inject user message into the conversation
                                self.orchestrator.memory.add_to_history(
                                    {
                                        "sender": "User",
                                        "action_type": "TALK",
                                        "content": user_input,
                                        "status": "CONTINUE",
                                    }
                                )
                                # Reset iteration counter and continue
                                iterations = 0
                        except (EOFError, KeyboardInterrupt):
                            self.console.print("\n[Returning to prompt]")
                            self.orchestrator.reset_to_idle()
                            break

                if iterations >= max_iterations:
                    self.console.print_error("Max iterations reached. Use /reset")
                    self.orchestrator.reset_to_idle()

                if result.get("finished") and result["state"] != "IDLE":
                    self.console.print("\n[Task Complete]\n")
                    # Increment successful turn counter for evolution trigger
                    self.successful_turns += 1

                    # Check for auto-evolution trigger
                    if self.successful_turns >= self.evolution_trigger_threshold:
                        self.console.print(
                            f"\n⚡ AUTO-EVOLUTION TRIGGER: {self.successful_turns} successful turns reached"
                        )
                        self.console.print("   Starting evolution cycle...\n")
                        self.run_evolve(auto_triggered=True)
                        self.successful_turns = 0  # Reset counter

            except KeyboardInterrupt:
                self.console.print("\n(Interrupted - use 'exit' to quit)")
                continue

            except Exception as e:
                self.console.print_error(f"Unexpected error: {e}")
                import traceback

                if self.config.ui_verbose:
                    traceback.print_exc()
                continue

    # =========================================================================
    # V9 CYBORG: Async REPL Loop
    # =========================================================================

    async def run_async(self):
        """
        V9 Cyborg Async REPL loop.

        Uses prompt_toolkit's prompt_async() for non-blocking input,
        wrapped with patch_stdout() to prevent streaming corruption.

        Gracefully handles Ctrl+C to cancel all async driver processes.
        """
        import re

        # Clear previous session state at startup (fresh start)
        self.orchestrator.reset_to_idle(clear_task=True)

        self.console.print_banner(
            gemini_model=self.orchestrator.gemini_info["model"],
            claude_model=self.orchestrator.claude_info["model"],
            version=self.config.nexus_version,
            codename=self.config.nexus_codename,
        )
        self.console.print_runtime_plan(self.config.provider_snapshot)

        self.console.print("\n⚡ V9 Async Mode Active")

        # V7 Sprint 11: Display startup hints
        hints = self.orchestrator.get_startup_hints()
        if hints:
            self.console.print("")
            for hint in hints:
                self.console.print(f"  {hint}")
            self.console.print("")

        # V12.4: Use nullcontext for piped/headless mode to avoid NoConsoleScreenBufferError
        stdout_context = nullcontext() if self._use_simple_input else patch_stdout()
        with stdout_context:
            while True:
                try:
                    # V9: Non-blocking input
                    # V11.4 ASYNC: get_running_loop() for Python 3.12+ compatibility
                    if self._use_simple_input:
                        loop = asyncio.get_running_loop()
                        user_input = await loop.run_in_executor(None, lambda: input("nexus7> "))
                    else:
                        user_input = await self.session.prompt_async("nexus7> ")

                    # Sanitize input (same as sync version)
                    user_input = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", user_input)
                    user_input = re.sub(r"[0-9]+~", "", user_input)
                    user_input = re.sub(r"\[\w\]?", "", user_input)
                    user_input = user_input.strip()

                    if not user_input:
                        continue

                    # Slash commands: keep sync (fast, no I/O)
                    if is_slash_command(user_input):
                        self.handle_command(user_input)
                        continue

                    # Handle exit
                    if is_exit_command(user_input):
                        self._abort_requested = True
                        self.console.print("👋 Goodbye!")
                        break

                    # V9: Async processing
                    await self._process_turn_async(user_input)

                except KeyboardInterrupt:
                    self.console.print("\n🛑 Interruption - cancelling async tasks...")
                    # V9: Cancel all async driver processes
                    try:
                        from core.drivers.async_factory import get_driver_factory

                        factory = get_driver_factory()
                        if factory:
                            cancelled = await factory.cancel_all()
                            if cancelled > 0:
                                self.console.print(f"  Cancelled {cancelled} process(es)")
                    except ImportError:
                        pass
                    continue

                except EOFError:
                    break

                except Exception as e:
                    self.console.print_error(f"Unexpected error: {e}")
                    if self.config.ui_verbose:
                        import traceback

                        traceback.print_exc()
                    continue

    async def _process_turn_async(self, user_input: str):
        """
        V9 Async wrapper for orchestrator.process_turn().

        If orchestrator has process_turn_async(), uses it.
        Otherwise falls back to sync process_turn() in executor.
        """
        # Check for async method first
        if hasattr(self.orchestrator, "process_turn_async"):
            result = await self.orchestrator.process_turn_async(user_input)
        else:
            # Fallback: Run sync in executor (non-blocking for REPL)
            # V11.4 ASYNC: get_running_loop() for Python 3.12+ compatibility
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, lambda: self.orchestrator.process_turn(user_input))

        self.console.display_result(result)

        # Continue processing until exit conditions (same logic as sync)
        max_iterations = 50
        iterations = 0
        tool_active = False

        while result["state"] not in ["IDLE", "ERROR", "PANIC", "FINISHED"] and iterations < max_iterations:
            if self._abort_requested:
                self.console.print("🛑 Abort requested - stopping")
                break

            if hasattr(self.orchestrator, "process_turn_async"):
                result = await self.orchestrator.process_turn_async()
            else:
                # V11.4 ASYNC: get_running_loop() for Python 3.12+ compatibility
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, lambda: self.orchestrator.process_turn())

            self.console.display_result(result)
            iterations += 1

            # Track tool usage
            if result.get("state") == "EXECUTING_TOOL":
                tool_active = True

            # Visual checkpoint every 10 turns
            if iterations > 0 and iterations % 10 == 0:
                state = result.get("state", "UNKNOWN")
                self.console.print(f"[dim]--- Iteration {iterations} | State: {state} ---[/dim]")
                tool_active = False

            # Check if user input needed
            needs_user_prompt = (
                result.get("needs_user_input", False)
                or result.get("state") == "ERROR"
                or iterations >= (max_iterations - 2)
            )

            if needs_user_prompt and not tool_active:
                self.console.print("[yellow]--- User input needed (or press Enter to continue) ---[/yellow]")
                try:
                    # Async input for interjection
                    # V11.4 ASYNC: get_running_loop() for Python 3.12+ compatibility
                    loop = asyncio.get_running_loop()
                    user_interjection = await loop.run_in_executor(None, lambda: input().strip())
                    if user_interjection:
                        self.console.print(f"[bold green]You:[/bold green] {user_interjection}")
                        self.orchestrator.memory.add_to_history(
                            {
                                "sender": "User",
                                "action_type": "TALK",
                                "content": user_interjection,
                                "status": "CONTINUE",
                            }
                        )
                        iterations = 0
                except (EOFError, KeyboardInterrupt):
                    self.console.print("\n[Returning to prompt]")
                    self.orchestrator.reset_to_idle()
                    break

        if iterations >= max_iterations:
            self.console.print_error("Max iterations reached. Use /reset")
            self.orchestrator.reset_to_idle()

        if result.get("finished") and result["state"] != "IDLE":
            self.console.print("\n[OK] [Task Complete]\n")
            self.successful_turns += 1

            # Check for auto-evolution trigger
            if self.successful_turns >= self.evolution_trigger_threshold:
                self.console.print(f"\n⚡ AUTO-EVOLUTION TRIGGER: {self.successful_turns} successful turns reached")
                self.console.print("   Starting evolution cycle...\n")
                self.run_evolve(auto_triggered=True)
                self.successful_turns = 0

    def handle_command(self, command: str):
        """
        Handle slash commands via V9 Command Pattern.

        Uses CommandRegistry to dispatch commands to their handlers.
        This replaces the legacy 26-branch elif chain.

        Args:
            command: Slash command string (e.g. "/status")
        """
        cmd, args = parse_command(command)

        # Special case: /help uses legacy help message for full coverage
        if cmd == "/help":
            self.console.print_help(get_help_message())
            return

        # V9: Command Pattern dispatch
        registry = get_initialized_registry()
        context = CommandContext(
            orchestrator=self.orchestrator, console=self.console, config=self.config, extras={"repl": self}
        )

        # Dispatch command
        full_command = f"{cmd} {args}".strip() if args else cmd
        result = registry.dispatch(full_command, context)

        # Handle result
        if result.message:
            if result.status == CommandStatus.ERROR or result.status == CommandStatus.INVALID_ARGS:
                self.console.print_error(result.message)
            elif result.status == CommandStatus.NOT_FOUND:
                # Fallback to legacy error message with available commands
                self.console.print_error(f"Unknown command: {cmd}")
                self.console.print(f"Available commands: {', '.join(SLASH_COMMANDS.keys())}")
            else:
                self.console.print(result.message)

    def show_status(self):
        """Show orchestrator status (/status command)"""
        status = {
            "state": self.orchestrator.state.name,
            "agent": self.orchestrator.active_agent,
            "iteration": self.orchestrator.iteration,
            "objective": self.orchestrator.blackboard.get("objective", "None"),
        }
        self.console.print_status(status)

    def run_doctor(self):
        """Run system diagnostics (/doctor command)"""
        from core.meta.cli_inspector import CLIInspector

        self.console.print("🔍 Running diagnostics...")

        inspector = CLIInspector()
        gemini = inspector.inspect_gemini()
        claude = inspector.inspect_claude()

        results = {
            "gemini": gemini,
            "claude": claude,
            "workspace": self.workspace_path.exists(),
            "io_buffer": (self.workspace_path / "_IO_BUFFER").exists(),
        }

        self.console.print_doctor_results(results)

    # V9.1: run_bootstrap() delegated to BootstrapService
    # See: core/bootstrap/service.py, core/interface/commands/workspace.py

    def run_review(self):
        """Run interactive review of pending children (/review command)"""
        from core.interface_pkg.interface_pkg.notifications import check_pending_review
        from core.interface_pkg.interface_pkg.notifications.file_notifier import delete_pending_review

        # Check if there's a pending review
        pending_metadata = check_pending_review(self.workspace_path)

        if not pending_metadata:
            self.console.print("ℹ️  No pending reviews found.")
            self.console.print("   Pending reviews are created after evolution completes.")
            return

        generation = pending_metadata["generation"]
        children = pending_metadata["children"]
        hours_elapsed = pending_metadata["hours_elapsed"]

        # Display review header
        self.console.print("\n" + "=" * 60)
        self.console.print(f"📋 REVIEW - Generation {generation}")
        self.console.print("=" * 60)
        self.console.print(f"Children: {len(children)}")
        self.console.print(f"Elapsed: {hours_elapsed:.1f}h")
        self.console.print("=" * 60 + "\n")

        # Interactive review loop
        for i, child in enumerate(children, 1):
            self.console.print(f"\n{'-' * 60}")
            self.console.print(f"Child {i}/{len(children)}: {child['id']}")
            self.console.print(f"{'-' * 60}")
            self.console.print(f"Fitness Score: {child['score']:.3f} ({child['improvement']:+.1%} vs parent)")

            # Show improvements if available
            if "improvements_summary" in child:
                self.console.print(f"\nImprovements:\n{child['improvements_summary']}")

            self.console.print(f"\nBirth Certificate: {child.get('birth_cert_path', 'Not found')}")
            self.console.print(f"Evaluation Results: {child.get('eval_results_path', 'Not found')}")

            # V7: Check auto-promotion eligibility
            decision_result = self._check_auto_promotion(child)

            # Display safety gates status
            self.console.print(
                f"\n🔒 Safety Gates ({sum(1 for g in decision_result.gates if g.passed)}/{len(decision_result.gates)} passed):"
            )
            for gate in decision_result.gates:
                status = "[OK]" if gate.passed else "[NO]"
                blocking = " [BLOCKING]" if gate.blocking else ""
                self.console.print(f"   {status} {gate.name}: {gate.score:.2f}/{gate.threshold:.2f}{blocking}")

            # Auto-promotion if enabled and approved
            if self.config.auto_promotion_enabled and decision_result.approved:
                self.console.print(f"\n🚀 AUTO-PROMOTION: {child['id']} passes all gates!")
                self.console.print(f"   Confidence: {decision_result.confidence:.1%}")
                self.console.print(f"   Reason: {decision_result.reason}")
                try:
                    # V9.1: Use EvolutionManager (delegates to PromotePhase)
                    result = self.evolution_manager.promote_child(
                        child_id=child["id"],
                        fitness_score=child["score"],
                        generation=generation,
                        child_metadata={"improvements_summary": child.get("improvements_summary")},
                    )
                    if result.success:
                        self.console.print(f"[OK] Auto-promotion complete: {child['id']} is now the active parent")
                    else:
                        raise Exception("; ".join(result.errors))
                except Exception as e:
                    self.console.print_error(f"Auto-promotion failed: {e}")
                    self.console.print("[warning]️  Falling back to manual review...")
                else:
                    continue  # Move to next child (auto-promoted successfully)

            # Show reason if not auto-approved
            if not decision_result.approved:
                self.console.print(f"\n[warning]️  Manual review required: {decision_result.reason}")

            # Get user decision (manual review)
            while True:
                self.console.print("\n[A]pprove | [R]eject | [T]est | [S]kip | [Q]uit review")
                try:
                    decision = self._get_input("nexus7/review> ").strip().lower()
                except KeyboardInterrupt:
                    self.console.print("\nReview interrupted.")
                    return

                if decision in ["a", "approve"]:
                    self.console.print(f"[OK] Approved: {child['id']} will become new parent")
                    # V9.1: Use EvolutionManager (delegates to PromotePhase)
                    try:
                        result = self.evolution_manager.promote_child(
                            child_id=child["id"],
                            fitness_score=child["score"],
                            generation=generation,
                            child_metadata={"improvements_summary": child.get("improvements_summary")},
                        )
                        if result.success:
                            self.console.print(f"[OK] Promotion complete: {child['id']} is now the active parent")
                        else:
                            raise Exception("; ".join(result.errors))
                    except Exception as e:
                        self.console.print_error(f"Promotion failed: {e}")
                        self.console.print("[warning]️  Manual promotion required")
                    break
                elif decision in ["r", "reject"]:
                    self.console.print(f"[NO] Rejected: {child['id']} will be archived")
                    # V9.1: Use EvolutionManager (delegates to PromotePhase)
                    try:
                        result = self.evolution_manager.archive_child(
                            child_id=child["id"],
                            reason="manual_review_rejection",
                            generation=generation,
                            fitness_score=child.get("score", 0.0),
                        )
                        if result.success:
                            self.console.print(f"[OK] Child archived: {child['id']}")
                        else:
                            raise Exception(result.reason)
                    except Exception as e:
                        self.console.print_error(f"Archival failed: {e}")
                        self.console.print("[warning]️  Manual cleanup required")
                    break
                elif decision in ["t", "test"]:
                    self.console.print(f"🧪 Opening test mode for {child['id']}")
                    self.console.print("[warning]️  Manual testing required (auto-testing not yet implemented)")
                    break
                elif decision in ["s", "skip"]:
                    self.console.print(f"⏭️  Skipped: {child['id']}")
                    break
                elif decision in ["q", "quit"]:
                    self.console.print("\nExiting review (progress not saved)")
                    return
                else:
                    self.console.print_error("Invalid choice. Use A/R/T/S/Q")

        # Review completed
        self.console.print("\n" + "=" * 60)
        self.console.print("[OK] Review completed for all children")
        self.console.print("=" * 60)

        # Ask to delete PENDING_REVIEW files
        self.console.print("\nDelete PENDING_REVIEW files? [y/N]")
        try:
            confirm = self._get_input("nexus7/review> ").strip().lower()
        except KeyboardInterrupt:
            self.console.print("\nKeeping PENDING_REVIEW files.")
            return

        if confirm == "y":
            if delete_pending_review(self.workspace_path):
                self.console.print("[OK] PENDING_REVIEW files deleted")
            else:
                self.console.print("[warning]️  No files to delete")
        else:
            self.console.print("PENDING_REVIEW files kept (use /review again to continue)")

    def _get_parent_fitness_score(self) -> float:
        """
        Get current parent's fitness score from LINEAGE.json (V7 Auto-Promotion).

        Returns:
            Parent fitness score (default 0.75 if not found)
        """
        import json

        lineage_path = self.nexus_root.parent / "LINEAGE.json"  # 20_NEXUS/LINEAGE.json
        if lineage_path.exists():
            try:
                data = json.loads(lineage_path.read_text(encoding="utf-8"))
                parent_id = data.get("current_parent", {}).get("id")
                if parent_id and parent_id in data.get("nodes", {}):
                    # V7.5: Support both old and new field names
                    node = data["nodes"][parent_id]
                    return node.get("fitness_score") or node.get("asi_proximity_score", 0.75)
            except Exception:
                pass
        return 0.75  # Default fallback

    def _check_auto_promotion(self, child: dict) -> AutoPromotionDecision:
        """
        Check if child is eligible for auto-promotion (V7).

        Args:
            child: Child metadata dict from PENDING_REVIEW

        Returns:
            AutoPromotionDecision with gates and approval status
        """
        import json

        # Build validation_result dict from child data
        validation_result = {
            "passed": True,  # If it's in pending review, it passed validation
            "fitness_score": child.get("score", 0),
            "red_team_score": child.get("validation", {}).get("red_team_score"),
        }

        # Try to load full validation results if available
        eval_path = child.get("eval_results_path")
        if eval_path:
            try:
                eval_path = Path(eval_path)
                if eval_path.exists():
                    full_results = json.loads(eval_path.read_text(encoding="utf-8"))
                    # V7.5: Support both old and new field names
                    fitness = full_results.get("fitness_score") or full_results.get("asi_score", child.get("score", 0))
                    validation_result.update(
                        {
                            "passed": full_results.get("passed", True),
                            "red_team_score": full_results.get("red_team_score"),
                            "fitness_score": fitness,
                        }
                    )
            except Exception:
                pass

        # Get parent score for comparison
        parent_fitness = self._get_parent_fitness_score()

        # Use ChildValidator to check eligibility (create dummy instance)
        validator = ChildValidator(
            child_path=Path("."),  # Not used by check_auto_promotion_eligibility
            child_id="",
            parent_id="",
        )

        return validator.check_auto_promotion_eligibility(
            validation_result=validation_result, parent_fitness_score=parent_fitness, config=self.config
        )

    # ==================== WORKSPACE MANAGEMENT ====================

    def handle_workspace_command(self, args: str):
        """
        Handle /workspace commands (V7.1 Multi-Workspace).

        Subcommands:
            /workspace           - Show current workspace
            /workspace new [name] - Create new workspace, archive current
            /workspace list      - List all workspaces
            /workspace switch <name> - Switch to another workspace
        """

        try:
            from core.interface_pkg.interface_pkg.workspace import (  # noqa: F401  # P5.6 workspace module not yet implemented
                WorkspaceError,
                WorkspaceExistsError,
                WorkspaceManager,
                WorkspaceNotFoundError,
            )
        except (ImportError, ModuleNotFoundError):
            self.console.print("[yellow]Workspace management not available (module not implemented)[/yellow]")
            return

        # Lazy init workspace manager
        if not hasattr(self, "workspace_manager"):
            self.workspace_manager = WorkspaceManager(self.nexus_root)

        parts = args.strip().split(maxsplit=1)
        subcommand = parts[0].lower() if parts else ""
        sub_args = parts[1] if len(parts) > 1 else ""

        try:
            if not subcommand:
                # /workspace - Show current workspace status
                self._show_workspace_status()

            elif subcommand == "new":
                self._workspace_new(sub_args or None)

            elif subcommand == "list":
                self._show_workspace_list()

            elif subcommand == "switch":
                if not sub_args:
                    self.console.print_error("Usage: /workspace switch <name>")
                    self.console.print("Use '/workspace list' to see available workspaces")
                    return
                self._workspace_switch(sub_args)

            else:
                self.console.print_error(f"Unknown subcommand: {subcommand}")
                self.console.print("Usage: /workspace [new|list|switch] [args]")

        except WorkspaceNotFoundError as e:
            self.console.print_error(str(e))
            suggestions = self.workspace_manager.get_suggestions(sub_args)
            if suggestions:
                self.console.print(f"Did you mean: {', '.join(suggestions)}?")

        except WorkspaceExistsError as e:
            self.console.print_error(str(e))

        except WorkspaceError as e:
            self.console.print_error(f"Workspace error: {e}")

    def _show_workspace_status(self):
        """Display current workspace info."""
        from rich.panel import Panel

        current = self.workspace_manager.get_current()
        if not current:
            self.console.print("No active workspace.")
            return

        content = f"""[bold cyan]Current Workspace:[/bold cyan] {current.name}

[dim]Created:[/dim]     {current.created_at.strftime("%Y-%m-%d %H:%M")}
[dim]Last used:[/dim]   {current.get_relative_time()}
[dim]Task:[/dim]        "{current.last_task[:50] + "..." if len(current.last_task) > 50 else current.last_task or "None"}"
[dim]Iterations:[/dim]  {current.metrics.iterations}
[dim]Size:[/dim]        {current.get_size_human()}
[dim]Files:[/dim]       {current.metrics.files_count}

[dim]Commands:[/dim]
   /workspace new [name]     Create fresh workspace
   /workspace list           Show all workspaces
   /workspace switch <name>  Switch to another workspace"""

        panel = Panel(content, title="Workspace", border_style="cyan")
        self.console.console.print(panel)

    def _show_workspace_list(self):
        """Display workspace list as Rich table."""
        from rich.table import Table

        workspaces = self.workspace_manager.list_workspaces()

        if not workspaces:
            self.console.print("No workspaces found.")
            return

        table = Table(title="NEXUS Workspaces", show_header=True, header_style="bold cyan", border_style="dim")

        table.add_column("Status", style="bold", width=8)
        table.add_column("Name", style="cyan", max_width=28)
        table.add_column("Last Used", width=12)
        table.add_column("Task", max_width=20)
        table.add_column("Size", justify="right", width=8)

        for ws in workspaces:
            status = "[green]- ACTIF[/green]" if ws.is_current else ""
            name = ws.name[:28]
            last_used = ws.get_relative_time()
            task = (ws.last_task[:18] + "..") if len(ws.last_task) > 18 else ws.last_task or "-"
            size = ws.get_size_human()

            table.add_row(status, name, last_used, task, size)

        self.console.console.print(table)
        self.console.print("\n[dim]Tip: Use /workspace switch <name> to change workspace[/dim]")

    def _workspace_new(self, name: str = None):
        """Create new workspace with confirmation."""
        current = self.workspace_manager.get_current()

        # Show confirmation
        self.console.print("\n📦 [bold]Création d'un nouveau workspace[/bold]\n")

        if current:
            self.console.print(f"  Workspace actuel:  {current.name}")
            self.console.print(f"  Archive vers:      workspace_archive/{current.name}/")
            self.console.print(f"  Fichiers:          {current.metrics.files_count} ({current.get_size_human()})")

        if name:
            self.console.print(f"\n  Nouveau workspace: {name}")
        else:
            self.console.print("\n  Nouveau workspace: [auto-généré depuis l'objectif]")

        self.console.console.print("\n  Confirmer? (Y/n): ", end="")

        try:
            confirm = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            self.console.print("\nAnnulé.")
            return

        if confirm and confirm != "y":
            self.console.print("Annulé.")
            return

        # Create workspace with spinner effect
        self.console.print("\n  ⠋ Archivage en cours...")

        try:
            new_ws = self.workspace_manager.create_workspace(name=name, archive_current=True)

            self.console.print("  [OK] Workspace archivé")
            self.console.print("  [OK] Nouveau workspace créé")

            # Hot-swap: reinitialize orchestrator
            self._reinit_orchestrator(new_ws.path)

            self.console.print(f"\n[OK] Workspace prêt: [bold cyan]{new_ws.name}[/bold cyan]\n")

        except Exception as e:
            self.console.print_error(f"Erreur: {e}")

    def _workspace_switch(self, name: str):
        """Switch to another workspace with confirmation."""
        current = self.workspace_manager.get_current()

        # Find target
        target = self.workspace_manager.find_workspace(name)
        if not target:
            suggestions = self.workspace_manager.get_suggestions(name)
            if suggestions:
                self.console.print_error(f"Workspace '{name}' non trouvé.")
                self.console.print(f"Vouliez-vous dire: {', '.join(suggestions)}?")
            else:
                self.console.print_error(f"Workspace '{name}' non trouvé.")
                self.console.print("Use '/workspace list' to see available workspaces")
            return

        # Check if already active
        if target.name == (current.name if current else ""):
            self.console.print(f"Workspace '{name}' est déjà actif.")
            return

        # Show confirmation
        self.console.print("\n🔄 [bold]Changement de workspace[/bold]\n")

        if current:
            self.console.print(f"  De:   {current.name} ({current.metrics.iterations} iterations)")

        self.console.print(f"  Vers: {target.name}")

        self.console.console.print("\n  Sauvegarder l'état actuel? (Y/n): ", end="")

        try:
            confirm = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            self.console.print("\nAnnulé.")
            return

        archive_current = confirm != "n"

        # Switch
        self.console.print("\n  ⠋ Sauvegarde...")

        try:
            old_ws, new_ws = self.workspace_manager.switch_workspace(name=target.name, archive_current=archive_current)

            self.console.print("  [OK] État sauvegardé")
            self.console.print(f"  ⠋ Chargement {new_ws.name}...")

            # Hot-swap: reinitialize orchestrator
            self._reinit_orchestrator(new_ws.path)

            self.console.print("  [OK] Workspace chargé")

            # Show restored state
            self.console.print(f"""
  État restauré:
    Iterations:    {new_ws.metrics.iterations}
    Dernière tâche: "{new_ws.last_task[:40] + "..." if len(new_ws.last_task) > 40 else new_ws.last_task or "None"}"

[OK] Switched to: [bold cyan]{new_ws.name}[/bold cyan]
""")

        except Exception as e:
            self.console.print_error(f"Erreur: {e}")
            import traceback

            if self.config.ui_verbose:
                traceback.print_exc()

    def _reinit_orchestrator(self, new_workspace_path: Path):
        """
        Reinitialize orchestrator for new workspace (hot-swap).

        This allows changing workspace without restarting NEXUS.
        """
        from prompt_toolkit.history import FileHistory

        from core.execution_pkg.execution.tool_manager import ToolManager
        from core.synapse.memory_v7 import MemoryManagerV7

        # 1. Save current state to disk
        self.orchestrator.memory.save_to_disk()

        # 2. Update workspace paths
        self.workspace_path = new_workspace_path
        self.orchestrator.workspace_path = new_workspace_path

        # 3. Recreate MemoryManager with new path
        self.orchestrator.memory = MemoryManagerV7(workspace_path=new_workspace_path, config=self.config)

        # 4. Load blackboard from new workspace
        self.orchestrator.blackboard = self.orchestrator.memory.blackboard

        # 5. Recreate ToolManager
        self.orchestrator.tool_manager = ToolManager(new_workspace_path)

        # 6. Update prompt_toolkit history
        history_file = new_workspace_path / ".nexus" / "history.txt"
        history_file.parent.mkdir(parents=True, exist_ok=True)
        self.session = PromptSession(history=FileHistory(str(history_file)))

        # 7. Reset FSM to IDLE
        self.orchestrator.state = OrchestratorState.IDLE
        self.orchestrator.iteration = 0

        # 8. Update workspace manager reference
        if hasattr(self, "workspace_manager"):
            try:
                from core.interface_pkg.interface_pkg.workspace import (
                    WorkspaceManager,  # noqa: F401  # P5.6 not yet implemented
                )

                self.workspace_manager = WorkspaceManager(self.nexus_root)
            except (ImportError, ModuleNotFoundError):
                pass

    # ==================== END WORKSPACE MANAGEMENT ====================

    # V9.1: Telemetry & Budget commands delegated to TelemetryService/BudgetService
    # See: core/telemetry/service.py, core/interface/commands/misc.py

    # =========================================================================
    # Project Memory Commands (V9.1 - Delegated to MemoryService)
    # =========================================================================

    def _get_memory_service(self):
        """Get or create MemoryService instance."""
        if not hasattr(self, "_memory_service"):
            from core.memory_pkg.memory import MemoryService

            self._memory_service = MemoryService(
                getattr(self.orchestrator, "project_memory", None), self.workspace_path, self.console
            )
        return self._memory_service

    def handle_learn_command(self, args: str):
        """Delegate to MemoryService.learn()"""
        self._get_memory_service().learn(args)

    def handle_forget_command(self, args: str):
        """Delegate to MemoryService.forget()"""
        self._get_memory_service().forget(args)

    def show_memory_status(self):
        """Delegate to MemoryService.get_status()"""
        self._get_memory_service().get_status()

    def handle_rag_command(self, args: str):
        """Delegate to MemoryService.handle_rag_command()"""
        self._get_memory_service().handle_rag_command(args)

    def run_tutorial(self):
        """Run interactive tutorial (/tutorial command)."""
        from core.interface_pkg.interface.tutorial import InteractiveTutorial

        tutorial = InteractiveTutorial()
        tutorial.run(self.console.console.print)

    def show_quickstart(self):
        """Show quick start guide (/quickstart command)."""
        from core.interface_pkg.interface.tutorial import InteractiveTutorial

        tutorial = InteractiveTutorial()
        self.console.console.print(tutorial.get_quick_start())

    def toggle_chat_mode(self):
        """Toggle chat-only mode (/chat command)."""
        current = self.orchestrator.blackboard.get("chat_mode", False)
        new_mode = not current
        self.orchestrator.blackboard["chat_mode"] = new_mode

        if new_mode:
            self.console.print("\n💬 [cyan]Chat mode ENABLED[/cyan]")
            self.console.print("   Tools are disabled. Use /chat to re-enable.\n")
        else:
            self.console.print("\n🔧 [green]Chat mode DISABLED[/green]")
            self.console.print("   Full agent capabilities restored.\n")

    # ==================== END PHASE 16 ====================

    # V7.5 Phase 0a: brainstorm_children_with_ais() REMOVED
    # Logic moved to core/evolution/phases/brainstorm.py (BrainstormPhase)
    # Called via EvolutionManager.brainstorm_mutations()

    # V9.1: brainstorm_spinoff_with_ais() and run_specialization() delegated to SpinoffService
    # See: core/bootstrap/service.py, core/interface/commands/workspace.py

    def _calculate_nexus_root(self) -> Path:
        """
        Calculate NEXUS root path robustly with validation.

        Returns:
            Path to NEXUS_V7_CHRYSALIS directory

        Raises:
            RuntimeError if path cannot be determined
        """
        # Primary method: Calculate from __file__
        calculated_path = Path(__file__).parent.parent.parent.resolve()

        # Validation: Check for expected markers
        expected_markers = ["nexus7.py", "core", "prompts"]
        for marker in expected_markers:
            if not (calculated_path / marker).exists():
                # Fallback: Try to find from workspace_path
                if self.workspace_path.name == "workspace":
                    fallback_path = self.workspace_path.parent.resolve()
                    if all((fallback_path / m).exists() for m in expected_markers):
                        return fallback_path

                raise RuntimeError(
                    f"NEXUS root path validation failed. "
                    f"Expected markers {expected_markers} not found at {calculated_path}"
                )

        return calculated_path

    # V7.5 Phase 0a: _validate_mutation_path() REMOVED
    # Logic moved to core/evolution/phases/create.py (CreatePhase._validate_mutation_path)

    def run_evolve(self, child_count: int = 3, auto_triggered: bool = False):
        """
        Run evolution cycle: create and evaluate children.

        V7.5 Phase 0a: Delegates to EvolutionManager for all evolution logic.
        REPL handles only UI/console output.

        Args:
            child_count: Number of children to create
            auto_triggered: True if triggered by 50-turn threshold
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
            return

        try:
            # V7.5 Phase 0a: Delegate to EvolutionManager
            result = self.evolution_manager.run_evolution_cycle(
                child_count=child_count,
                focus_areas=None,  # TODO: Add focus areas from command
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
            else:
                self.console.print(f"\n[red][NO] Evolution failed at phase: {result.phase_reached}[/red]")
                for error in result.errors:
                    self.console.print(f"  - {error}")
                self.console.print("\nUse /evolve-status for more details.\n")

        except Exception as e:
            self.console.print_error(f"Evolution cycle failed: {e}")
            import traceback

            if self.config.ui_verbose:
                traceback.print_exc()

    def show_evolve_status(self):
        """Show evolution statistics and stagnation counter (/evolve-status command)"""
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

            self.console.print(f"\n{'-' * 60}")
            self.console.print("SESSION STATUS")
            self.console.print(f"{'-' * 60}")
            self.console.print(f"Successful Turns This Session: {self.successful_turns}")
            self.console.print(f"Auto-Evolution Trigger: {self.evolution_trigger_threshold} turns")
            remaining = self.evolution_trigger_threshold - self.successful_turns
            self.console.print(f"Turns Until Auto-Evolution: {remaining}")

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

        except Exception as e:
            self.console.print_error(f"Failed to load evolution status: {e}")

    # =========================================================================
    # Swarm Commands (V9.1 - Delegated to SwarmService)
    # =========================================================================

    def _get_swarm_service(self):
        """Get or create SwarmService instance."""
        if not hasattr(self, "_swarm_service"):
            from core.intelligence.swarm import SwarmService

            self._swarm_service = SwarmService(self.orchestrator, self.console, self.config)
        return self._swarm_service

    def run_swarm_task(self, task: str):
        """Delegate to SwarmService.run_task()"""
        self._get_swarm_service().run_task(task)

    def run_swarm_task_fsm(self, task: str):
        """Delegate to SwarmService.run_task_fsm()"""
        self._get_swarm_service().run_task_fsm(task)

    def show_swarm_status(self):
        """Delegate to SwarmService.get_status()"""
        self._get_swarm_service().get_status()

    # =========================================================================
    # Agent Commands (V9.1 - Delegated to AgentService)
    # =========================================================================

    def _get_agent_service(self):
        """Get or create AgentService instance."""
        if not hasattr(self, "_agent_service"):
            from core.foundation.agents import AgentService

            self._agent_service = AgentService(self.orchestrator, self.workspace_path, self.console)
        return self._agent_service

    def spawn_agent(self, role: str):
        """Delegate to AgentService.spawn()"""
        self._get_agent_service().spawn(role)

    def list_agents(self):
        """Delegate to AgentService.list_agents()"""
        self._get_agent_service().list_agents()

    def show_pool_stats(self):
        """Delegate to AgentService.get_pool_stats()"""
        self._get_agent_service().get_pool_stats()

    # =========================================================================
    # V9.1: Evolution methods (_promote_child, _archive_rejected_child) REMOVED
    # These were 100% duplicates of core/evolution/phases/promote.py
    # Now using EvolutionManager.promote_child() and .archive_child() directly
    # See: core/evolution/service.py for Service Layer implementation
    # =========================================================================
