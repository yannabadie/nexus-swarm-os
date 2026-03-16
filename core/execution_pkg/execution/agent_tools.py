"""
NEXUS V7.8 - Agent-as-Tool Registry (Phase 15: Vision Fractale)

Exposes spawned agents as callable tools, enabling fractal agent invocation.
Spawned agents can be invoked as tools by the Swarm, creating recursive
multi-agent patterns.

Architecture:
    +--------------------------------------------------------------+
    |  Swarm Engine                                                 |
    |  +-----------------+    +---------------------------------+ |
    |  | Task: "Analyze  |--->| AgentToolRegistry               | |
    |  | security vulns" |    | +---------------------------+   | |
    |  +-----------------+    | | agent_security_expert     |   | |
    |                         | | agent_code_reviewer       |   | |
    |                         | | agent_test_writer         |   | |
    |                         | +---------------------------+   | |
    |                         +----------------+----------------+ |
    |                                          |                   |
    |                                          v                   |
    |                         +---------------------------------+ |
    |                         | AgentInvoker.invoke_spawned()   | |
    |                         +---------------------------------+ |
    +--------------------------------------------------------------+

Usage:
    from core.execution_pkg.execution.agent_tools import AgentToolRegistry

    registry = AgentToolRegistry(workspace_path, agent_pool, invoker)
    registry.refresh()

    # List available agent tools
    tools = registry.list_agent_tools()

    # Execute an agent as a tool
    result = registry.execute_agent_tool("security_expert", {
        "task": "Analyze this code for SQL injection"
    })
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from core.execution_pkg.execution.tool_manager import ToolManager, ToolResult
    from core.execution_pkg.orchestration.agent_invoker import AgentInvoker
    from core.infrastructure.bootstrap.agent_loader import SpawnedAgentLoader
    from core.intelligence.swarm.agent_metrics import AgentPool, AgentProfile


# =============================================================================
# Constants
# =============================================================================

AGENT_TOOL_PREFIX = "agent_"  # Tools are named: agent_{agent_id}
DEFAULT_TIMEOUT = 120  # 2 minutes for agent invocation


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class AgentToolDefinition:
    """
    Tool definition for a spawned agent.

    Describes how to invoke the agent as a tool.
    """

    tool_name: str  # e.g., "agent_security_expert"
    agent_id: str  # e.g., "security_expert"
    description: str
    capabilities: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for tool registration."""
        return {
            "name": self.tool_name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "The task or question for the agent to handle"},
                    "context": {"type": "string", "description": "Additional context or code to analyze (optional)"},
                },
                "required": ["task"],
            },
            "capabilities": self.capabilities,
            "domains": self.domains,
        }


@dataclass
class AgentToolResult:
    """Result from executing an agent as a tool."""

    success: bool
    agent_id: str
    output: str
    error: str | None = None
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "agent_id": self.agent_id,
            "output": self.output,
            "error": self.error,
            "duration_seconds": self.duration_seconds,
        }


# =============================================================================
# AgentToolRegistry
# =============================================================================


class AgentToolRegistry:
    """
    Registry that exposes spawned agents as callable tools.

    V7.8 Phase 15: Vision Fractale - Enables recursive agent invocation.

    When agents are spawned via /spawn, they are automatically registered
    as tools. Other agents (or the Swarm) can then invoke them like any
    other tool, enabling fractal patterns:

    - Main task -> spawns specialist agent -> specialist invokes another agent
    - RED_BLUE mode -> red team agent spawns attack specialists
    - PARALLEL mode -> each subtask handled by domain-specific agent

    Thread Safety:
        The registry is read-heavy. Refreshes are infrequent (on spawn).
        Tool execution is thread-safe via AgentInvoker.
    """

    def __init__(
        self,
        workspace_path: Path,
        agent_pool: Optional["AgentPool"] = None,
        agent_invoker: Optional["AgentInvoker"] = None,
        agent_loader: Optional["SpawnedAgentLoader"] = None,
    ):
        """
        Initialize the Agent Tool Registry.

        Args:
            workspace_path: Path to NEXUS workspace
            agent_pool: AgentPool for accessing agent profiles
            agent_invoker: AgentInvoker for executing agents
            agent_loader: SpawnedAgentLoader for loading agent configs
        """
        self.workspace_path = Path(workspace_path)
        self.agents_dir = self.workspace_path / "agents"

        self._agent_pool = agent_pool
        self._agent_invoker = agent_invoker
        self._agent_loader = agent_loader

        self._tools: dict[str, AgentToolDefinition] = {}
        self._logger = logging.getLogger("nexus.agent_tools")

    def set_dependencies(
        self, agent_pool: "AgentPool", agent_invoker: "AgentInvoker", agent_loader: "SpawnedAgentLoader"
    ) -> None:
        """
        Set dependencies after initialization.

        Useful when registry is created before orchestrator is fully initialized.

        Args:
            agent_pool: AgentPool instance
            agent_invoker: AgentInvoker instance
            agent_loader: SpawnedAgentLoader instance
        """
        self._agent_pool = agent_pool
        self._agent_invoker = agent_invoker
        self._agent_loader = agent_loader

    def refresh(self) -> int:
        """
        Refresh the registry by scanning for spawned agents.

        Called after /spawn or at startup.

        Returns:
            Number of agent tools registered
        """
        self._tools.clear()

        if not self._agent_pool:
            self._logger.debug("No agent pool available, skipping refresh")
            return 0

        # Get all spawned agents from pool
        spawned = self._agent_pool.get_spawned_agents()

        for agent_profile in spawned:
            try:
                tool_def = self._create_tool_definition(agent_profile)
                self._tools[tool_def.tool_name] = tool_def
                self._logger.debug(f"Registered agent tool: {tool_def.tool_name}")
            except Exception as e:
                self._logger.warning(f"Failed to create tool for agent {agent_profile.agent_id}: {e}")

        self._logger.info(f"Agent Tool Registry: {len(self._tools)} agent(s) available as tools")
        return len(self._tools)

    def _create_tool_definition(self, agent_profile: "AgentProfile") -> AgentToolDefinition:
        """
        Create a tool definition from an agent profile.

        Args:
            agent_profile: Agent profile from AgentPool

        Returns:
            AgentToolDefinition for the agent
        """
        agent_id = agent_profile.agent_id
        tool_name = f"{AGENT_TOOL_PREFIX}{agent_id}"

        # Try to get richer description from loader
        description = f"Invoke spawned agent: {agent_id}"
        domains = []

        if self._agent_loader:
            config = self._agent_loader.load_agent_config(agent_id)
            if config:
                description = config.mission or description
                domains = config.domains or []

        return AgentToolDefinition(
            tool_name=tool_name,
            agent_id=agent_id,
            description=description,
            capabilities=agent_profile.capabilities,
            domains=domains,
        )

    def list_agent_tools(self) -> list[AgentToolDefinition]:
        """
        List all available agent tools.

        Returns:
            List of AgentToolDefinition objects
        """
        return list(self._tools.values())

    def get_tool_definition(self, tool_name: str) -> AgentToolDefinition | None:
        """
        Get definition for a specific agent tool.

        Args:
            tool_name: Tool name (e.g., "agent_security_expert")

        Returns:
            AgentToolDefinition or None
        """
        return self._tools.get(tool_name)

    def is_agent_tool(self, tool_name: str) -> bool:
        """
        Check if a tool name refers to an agent tool.

        Args:
            tool_name: Tool name to check

        Returns:
            True if this is a registered agent tool
        """
        return tool_name in self._tools

    def execute_agent_tool(self, tool_name: str, args: dict[str, Any]) -> AgentToolResult:
        """
        Execute an agent as a tool.

        Args:
            tool_name: Tool name (e.g., "agent_security_expert")
            args: Tool arguments:
                - task: str (required) - The task for the agent
                - context: str (optional) - Additional context

        Returns:
            AgentToolResult with execution output
        """
        import time

        start_time = time.time()

        # Validate tool exists
        tool_def = self._tools.get(tool_name)
        if not tool_def:
            return AgentToolResult(
                success=False,
                agent_id="",
                output="",
                error=f"Unknown agent tool: {tool_name}. Available: {list(self._tools.keys())}",
            )

        # Validate invoker is available
        if not self._agent_invoker:
            return AgentToolResult(
                success=False, agent_id=tool_def.agent_id, output="", error="AgentInvoker not configured"
            )

        # Extract arguments
        task = args.get("task", "")
        context = args.get("context", "")

        if not task:
            return AgentToolResult(
                success=False, agent_id=tool_def.agent_id, output="", error="'task' argument is required"
            )

        # Build full context for agent
        full_context = f"# Task\n{task}"
        if context:
            full_context += f"\n\n# Context\n{context}"

        try:
            # Invoke the spawned agent
            self._logger.debug(f"Invoking agent tool: {tool_name} with task: {task[:100]}...")

            response = self._agent_invoker.invoke_spawned_agent(
                agent_id=tool_def.agent_id, task_type="tool_invocation", context=full_context
            )

            duration = time.time() - start_time

            return AgentToolResult(success=True, agent_id=tool_def.agent_id, output=response, duration_seconds=duration)

        except Exception as e:
            duration = time.time() - start_time
            self._logger.error(f"Agent tool execution failed: {e}")

            return AgentToolResult(
                success=False, agent_id=tool_def.agent_id, output="", error=str(e), duration_seconds=duration
            )

    def create_tool_handler(self, tool_name: str) -> Callable[[dict], "ToolResult"]:
        """
        Create a ToolManager-compatible handler for an agent tool.

        This allows agent tools to be registered in ToolManager alongside
        built-in tools.

        Args:
            tool_name: Tool name

        Returns:
            Handler function compatible with ToolManager.tools dict
        """
        # Import here to avoid circular dependency
        from core.execution_pkg.execution.tool_manager import ToolResult

        def handler(args: dict) -> ToolResult:
            result = self.execute_agent_tool(tool_name, args)

            return ToolResult(
                tool_name=tool_name,
                status="SUCCESS" if result.success else "FAILURE",
                output=result.output,
                error=result.error or "",
            )

        return handler

    def register_with_tool_manager(self, tool_manager: "ToolManager") -> int:
        """
        Register all agent tools with a ToolManager.

        This makes agent tools available alongside built-in tools.

        Args:
            tool_manager: ToolManager instance

        Returns:
            Number of tools registered
        """
        count = 0
        for tool_name in self._tools:
            handler = self.create_tool_handler(tool_name)
            tool_manager.tools[tool_name] = handler
            count += 1

        self._logger.info(f"Registered {count} agent tool(s) with ToolManager")
        return count

    def get_tools_for_domain(self, domain: str) -> list[AgentToolDefinition]:
        """
        Get agent tools relevant to a specific domain.

        Args:
            domain: Domain name (e.g., "security", "coding")

        Returns:
            List of matching AgentToolDefinitions
        """
        domain_lower = domain.lower()
        matches = []

        for tool_def in self._tools.values():
            # Check domains
            if any(domain_lower in d.lower() for d in tool_def.domains):
                matches.append(tool_def)
                continue
            # Check capabilities
            if any(domain_lower in c.lower() for c in tool_def.capabilities):
                matches.append(tool_def)

        return matches

    def get_summary(self) -> dict[str, Any]:
        """
        Get summary of registered agent tools.

        Returns:
            Dictionary with registry statistics
        """
        return {
            "total_tools": len(self._tools),
            "tools": [
                {"name": t.tool_name, "agent_id": t.agent_id, "capabilities": t.capabilities, "domains": t.domains}
                for t in self._tools.values()
            ],
        }


# =============================================================================
# Factory Function
# =============================================================================

_registry: AgentToolRegistry | None = None


def get_agent_tool_registry(
    workspace_path: Path | None = None,
    agent_pool: Optional["AgentPool"] = None,
    agent_invoker: Optional["AgentInvoker"] = None,
    agent_loader: Optional["SpawnedAgentLoader"] = None,
) -> AgentToolRegistry:
    """
    Get or create the global AgentToolRegistry instance.

    Args:
        workspace_path: Required for first initialization
        agent_pool: Optional AgentPool (can be set later)
        agent_invoker: Optional AgentInvoker (can be set later)
        agent_loader: Optional SpawnedAgentLoader (can be set later)

    Returns:
        AgentToolRegistry instance
    """
    global _registry

    if _registry is None:
        if workspace_path is None:
            raise ValueError("workspace_path required for first initialization")
        _registry = AgentToolRegistry(workspace_path, agent_pool, agent_invoker, agent_loader)
    elif agent_pool or agent_invoker or agent_loader:
        # Update dependencies if provided
        if agent_pool:
            _registry._agent_pool = agent_pool
        if agent_invoker:
            _registry._agent_invoker = agent_invoker
        if agent_loader:
            _registry._agent_loader = agent_loader

    return _registry
