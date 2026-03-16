"""
Console UI V7 - Interface minimaliste avec Rich

Principes:
- Affiche: messages agents (content), résumés d'actions, résultats outils
- Cache: JSON, thought_process, internal state (sauf mode verbose)
- Utilise Rich pour: spinners, panels, formatting
"""

import os

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.spinner import Spinner

from core.foundation.agents.unified_registry import get_registry  # V8.4.0
from core.version import NEXUS_CODENAME, NEXUS_VERSION


class ConsoleV7:
    """Console UI minimaliste pour NEXUS"""

    def __init__(self, verbose: bool = False):
        """
        Initialize console

        Args:
            verbose: Si True, affiche détails FSM et JSON
        """
        # V9.1.1: Let Rich auto-detect terminal capabilities
        # - Don't force legacy_windows=False (breaks on conhost.exe)
        # - Don't force force_terminal=True (let Rich decide)
        # Rich will use VT100 if available, fallback to Windows API otherwise
        self.console = Console()
        self.verbose = verbose
        self._last_state: str | None = None

    def print_banner(self, gemini_model: str, claude_model: str, version: str = None, codename: str = None):
        """
        Print NEXUS banner au démarrage

        Args:
            gemini_model: Nom du modèle Gemini détecté
            claude_model: Nom du modèle Claude détecté
            version: Version from config (e.g., "8.3.1")
            codename: Codename from config (e.g., "TRUE HIVE MIND")
        """
        # Default values if not provided (backward compatibility)
        version = version or NEXUS_VERSION
        codename = codename or NEXUS_CODENAME

        banner = f"""
===========================================================
NEXUS V{version} "{codename}"
Persistent FSM Orchestrator
===========================================================
Gemini: {gemini_model}
Claude: {claude_model} (Dynamic: Opus for evolution/brainstorm)

Mode: Shared Runtime (CLI + SDK)
Type your task or use slash commands (/help for list)
"""
        self.console.print(banner, style="bold cyan")

    def display_result(self, result: dict):
        """
        Display turn result (appelé après chaque process_turn)

        Modes:
        - Normal: Affiche seulement content + résumé
        - Verbose: Affiche état FSM + détails

        Args:
            result: Dict returned by orchestrator.process_turn()
                {
                    "state": str,
                    "output": str,
                    "agent": str,
                    "finished": bool,
                    "error": Optional[str]
                }
        """
        state = result.get("state")
        output = result.get("output")
        agent = result.get("agent")
        error = result.get("error")

        # State transition visibility matters even outside verbose mode.
        if state and state != self._last_state:
            style = "bold cyan" if self.verbose else "dim"
            self.console.print(f"[{style}]Runtime -> {state}[/{style}]")
            self._last_state = state

        # Agent message
        if output and agent:
            # V7 FIX: Handle Swarm agent with distinct color
            # V8.4.0: Use registry for agent identification
            registry = get_registry()
            if registry.is_gemini(agent):
                color = "cyan"
                self.console.print(f"[{color}][{agent}][/{color}] {output}")
            elif agent == "Swarm":
                # V7 FIX: Swarm output already has [Swarm] prefix from orchestration
                # Don't add another prefix, just use magenta color for the whole output
                color = "magenta"
                self.console.print(f"[{color}]{output}[/{color}]")
            else:  # Claude or others
                color = "green"
                self.console.print(f"[{color}][{agent}][/{color}] {output}")
        elif output and not agent:
            # Output without agent (system messages)
            self.console.print(output)

        # Tool execution indication
        if state == "EXECUTING_TOOL" and "tool" in result:
            tool_name = result["tool"]
            self.console.print(f"[yellow][tool] Executing: {tool_name}[/yellow]")

        # Error
        if error:
            self.console.print(f"[red][error] {error}[/red]")

        # Validation results
        if "[OK]" in str(output) or "[OK]" in str(output):
            self.console.print(output, style="green")
        elif "[NO]" in str(output) or "[NO]" in str(output):
            self.console.print(output, style="yellow")

    def print_status(self, status: dict):
        """
        Print orchestrator status (/status command)

        Args:
            status: {
                "state": str,
                "agent": str,
                "iteration": int,
                "objective": str
            }
        """
        content = f"""State: {status["state"]}
Active Agent: {status["agent"]}
Iteration: {status["iteration"]}
Objective: {status["objective"]}"""

        panel = Panel(content, title="Orchestrator Status", border_style="cyan")
        self.console.print(panel)

    def print_doctor_results(self, results: dict):
        """
        Print diagnostics results (/doctor command)

        Args:
            results: {
                "gemini": {...},
                "claude": {...},
                "workspace": bool,
                "io_buffer": bool
            }
        """
        gemini = results["gemini"]
        claude = results["claude"]

        gemini_status = "[OK]" if gemini["available"] else "[NO]"
        claude_status = "[OK]" if claude["available"] else "[NO]"

        content = f"""{gemini_status} Gemini CLI: {gemini.get("model", "N/A")}
{claude_status} Claude CLI: {claude.get("model", "N/A")}
{"[OK]" if results.get("workspace") else "[NO]"} Workspace directory
{"[OK]" if results.get("io_buffer") else "[NO]"} IO Buffer directory"""

        panel = Panel(
            content,
            title="System Diagnostics",
            border_style="green" if results.get("workspace") and results.get("io_buffer") else "yellow",
        )
        self.console.print(panel)

    def print_help(self, help_message: str):
        """Print help message"""
        self.console.print(Panel(help_message, title="Help", border_style="cyan"))

    def print_error(self, error: str):
        """Print error message"""
        self.console.print(f"[red][error] {error}[/red]")

    def print(self, message: str, style: str | None = None):
        """
        Print simple message

        Args:
            message: Message to print
            style: Rich style (e.g. "bold", "red", "cyan")
        """
        if style:
            self.console.print(message, style=style)
        else:
            self.console.print(message)

    def print_runtime_plan(self, provider_snapshot: dict[str, object]) -> None:
        """Display the current runtime/provider plan at session start."""
        driver_mode = provider_snapshot.get("driver_mode", "auto")
        available_sdk = provider_snapshot.get("available_sdk_providers", [])
        warnings = provider_snapshot.get("warnings", [])
        self.console.print(f"[dim]Runtime mode: {driver_mode}[/dim]")
        if available_sdk:
            self.console.print(f"[dim]SDK providers: {', '.join(available_sdk)}[/dim]")
        for warning in warnings:
            self.console.print(f"[yellow]Provider warning:[/yellow] {warning}")

    def print_activity(self, event: dict[str, str]) -> None:
        """Display compact runtime activity from orchestrator callbacks."""
        if event.get("type") != "agent_status":
            return
        agent = event.get("agent", "agent")
        status = event.get("status", "idle")
        task_type = event.get("task_type", "")
        suffix = f" ({task_type})" if task_type else ""
        self.console.print(f"[dim]Activity -> {agent} {status}{suffix}[/dim]")

    def clear(self):
        """Clear terminal screen"""
        os.system("cls" if os.name == "nt" else "clear")  # nosec B605  # intentional: screen clear command, not user-controlled

    def show_spinner(self, text: str):
        """
        Show animated spinner (context manager)

        Usage:
            with console.show_spinner("Processing..."):
                # Long operation
                time.sleep(5)

        Args:
            text: Spinner text
        """
        return Live(Spinner("dots", text=text), console=self.console, refresh_per_second=10)

    def print_markdown(self, markdown_text: str):
        """
        Print formatted markdown

        Args:
            markdown_text: Markdown string
        """
        md = Markdown(markdown_text)
        self.console.print(md)
