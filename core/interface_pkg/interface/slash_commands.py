"""
Slash Commands - Commandes système pour NEXUS V7.7 HIVE MIND

Commandes organisées par catégorie pour une meilleure UX.

V7.7 Phase 16: Developer Experience
- Commandes catégorisées
- /budget pour gestion financière
- /tutorial pour guide interactif
"""

# =============================================================================
# COMMAND CATEGORIES (V7.7 Phase 16)
# =============================================================================

COMMAND_CATEGORIES = {
    "🐝 Collaboration": {
        "/swarm <task>": "Route task through Hybrid Swarm Engine (6 modes)",
        "/swarm-status": "Show current swarm mode and DyLAN metrics",
        "/swarm-fsm <task>": "Route task via FSM states (debug mode)",
        "/pool-stats": "Show agent pool DyLAN importance scores",
    },
    "🧬 Evolution": {
        "/evolve [count]": "Create and evaluate child generations (default: 3)",
        "/evolve-status": "Show evolution stats and stagnation counter",
        "/review": "Review and evaluate pending children",
        "/specialize <mission>": "Create specialized NEXUS spinoff",
        "/spawn <role>": "Create specialized agent (e.g., /spawn SQL Expert)",
        "/agents": "List all spawned agents",
    },
    "📊 Monitoring": {
        "/status": "Show orchestrator state, agent, iteration",
        "/telemetry": "Show telemetry report (last 7 days)",
        "/telemetry status": "Show detailed telemetry stats",
        "/telemetry export [days]": "Export telemetry to CSV",
        "/budget": "Show budget status (spent, limit, remaining)",
        "/budget reset": "Reset daily budget counter",
        "/budget add <amount>": "Add emergency credit to budget",
        "/budget history": "Show recent API costs",
    },
    "📁 Workspace": {
        "/workspace": "Show current workspace info",
        "/workspace new [name]": "Create new workspace, archive current",
        "/workspace list": "List all workspaces",
        "/workspace switch <name>": "Switch to another workspace",
        "/bootstrap [path]": "Analyze project and generate NEXUS.md",
    },
    "🧠 Memory": {
        "/learn [path]": "Index file/directory into project memory",
        "/forget [path]": "Remove file/directory from project memory",
        "/memory-status": "Show indexed files, chunks, and storage location",
        "/rag init": "Initialize RAG on workspace/memory/ (session data)",
        "/rag clear": "Clear all RAG indexed data",
        "/rag query <text>": "Test RAG retrieval with a query",
    },
    "⚙️ System": {
        "/clear": "Clear terminal screen",
        "/reset": "Reset orchestrator to IDLE state",
        "/doctor": "Run system diagnostics",
        "/mode <name>": "Change mode (Normal, InProjectImprovement)",
        "/chat": "Enter chat-only mode (no tools)",
        "/help": "Show this help message",
        "/tutorial": "Interactive guide for new users",
        "/quickstart": "Quick start summary (5 min read)",
        "exit": "Exit NEXUS",
    },
}

# Flat dictionary for backwards compatibility
SLASH_COMMANDS = {}
for _category, commands in COMMAND_CATEGORIES.items():
    SLASH_COMMANDS.update(commands)


def get_help_message() -> str:
    """
    Generate categorized help message.

    Returns:
        Formatted help string with categories
    """
    # Get version from core module
    from core import __codename__, __version__

    lines = [
        "==============================================================",
        f"NEXUS V{__version__} {__codename__} - Command Reference",
        "==============================================================",
        "",
    ]

    for category, commands in COMMAND_CATEGORIES.items():
        lines.append(category)
        lines.append("-" * 60)
        for cmd, desc in commands.items():
            # Truncate description if too long
            desc_short = desc[:45] + "..." if len(desc) > 48 else desc
            lines.append(f"  {cmd:<25} {desc_short}")
        lines.append("-" * 60)
        lines.append("")

    lines.append("Tip: Use /tutorial for an interactive guide")

    return "\n".join(lines)


def get_category_for_command(cmd: str) -> str:
    """
    Find which category a command belongs to.

    Args:
        cmd: Command string (e.g., "/swarm")

    Returns:
        Category name or "Unknown"
    """
    cmd_base = cmd.split()[0].lower()
    for category, commands in COMMAND_CATEGORIES.items():
        for command in commands:
            if command.split()[0].lower() == cmd_base:
                return category
    return "Unknown"


def is_slash_command(user_input: str) -> bool:
    """
    Check if input is a slash command

    Args:
        user_input: User's input string

    Returns:
        True if starts with '/'
    """
    return user_input.strip().startswith("/")


def is_exit_command(user_input: str) -> bool:
    """
    Check if input is an exit command

    Args:
        user_input: User's input string

    Returns:
        True if 'exit', 'quit', or 'q'
    """
    return user_input.strip().lower() in ["exit", "quit", "q"]


def parse_command(user_input: str) -> tuple:
    """
    Parse slash command into (command, args)

    Args:
        user_input: Slash command string (e.g. "/mode Normal")

    Returns:
        Tuple (command, args)
        Example: ("/mode Normal") -> ("/mode", "Normal")

    Examples:
        >>> parse_command("/clear")
        ('/clear', '')

        >>> parse_command("/mode Normal")
        ('/mode', 'Normal')

        >>> parse_command("/budget add 10")
        ('/budget', 'add 10')
    """
    parts = user_input.strip().split(maxsplit=1)
    command = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    return command, args
