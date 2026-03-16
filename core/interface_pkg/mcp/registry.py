"""
MCP Registry - Server configuration loader

Loads MCP server configurations from workspace/.nexus/mcp_servers.json
and manages active server connections.
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from .client import MCPClient, MCPClientError
from .discovery import MCPToolDiscovery, ToolDiscoveryResult

# =============================================================================
# Configuration Types
# =============================================================================


@dataclass
class MCPServerConfig:
    """
    Configuration for a single MCP server.

    Example config:
        {
            "name": "filesystem",
            "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
            "env": {"DEBUG": "true"},
            "enabled": true,
            "description": "File system access server"
        }
    """

    name: str
    command: list[str]
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    description: str = ""
    args: list[str] = field(default_factory=list)  # Additional args appended to command

    @property
    def full_command(self) -> list[str]:
        """Get full command with args."""
        return self.command + self.args

    def to_dict(self) -> dict:
        """Serialize to dict."""
        return {
            "name": self.name,
            "command": self.command,
            "env": self.env,
            "enabled": self.enabled,
            "description": self.description,
            "args": self.args,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MCPServerConfig":
        """Deserialize from dict."""
        return cls(
            name=data.get("name", "unknown"),
            command=data.get("command", []),
            env=data.get("env", {}),
            enabled=data.get("enabled", True),
            description=data.get("description", ""),
            args=data.get("args", []),
        )


# =============================================================================
# Registry
# =============================================================================


class MCPRegistry:
    """
    Registry for MCP server configurations.

    Loads configurations from workspace/.nexus/mcp_servers.json
    and manages server connections.

    Usage:
        registry = MCPRegistry(workspace_path)

        # Get all enabled server configs
        servers = registry.get_servers()

        # Get a specific server config
        fs_config = registry.get_server("filesystem")

        # Create a client for a server
        client = registry.create_client("filesystem")

        # Get or create connected client (cached)
        client = registry.get_client("filesystem")
    """

    CONFIG_FILENAME = "mcp_servers.json"
    CONFIG_PATH = ".nexus"

    def __init__(self, workspace_path: Path):
        """
        Initialize registry.

        Args:
            workspace_path: Path to workspace directory
        """
        self.workspace_path = Path(workspace_path)
        self.config_path = self.workspace_path / self.CONFIG_PATH / self.CONFIG_FILENAME

        # Server configs (loaded on demand)
        self._configs: dict[str, MCPServerConfig] | None = None

        # Active clients (lazy initialization)
        self._clients: dict[str, MCPClient] = {}

        # Logger
        self._logger = logging.getLogger("nexus.mcp.registry")

    # =========================================================================
    # Configuration
    # =========================================================================

    def get_servers(self, include_disabled: bool = False) -> list[MCPServerConfig]:
        """
        Get all server configurations.

        Args:
            include_disabled: Include disabled servers

        Returns:
            List of server configs
        """
        self._ensure_loaded()
        servers = list(self._configs.values())

        if not include_disabled:
            servers = [s for s in servers if s.enabled]

        return servers

    def get_server(self, name: str) -> MCPServerConfig | None:
        """
        Get a specific server configuration.

        Args:
            name: Server name

        Returns:
            MCPServerConfig or None
        """
        self._ensure_loaded()
        return self._configs.get(name)

    def add_server(self, config: MCPServerConfig) -> None:
        """
        Add or update a server configuration.

        Args:
            config: Server configuration
        """
        self._ensure_loaded()
        self._configs[config.name] = config
        self._save_config()

    def remove_server(self, name: str) -> bool:
        """
        Remove a server configuration.

        Args:
            name: Server name

        Returns:
            True if removed, False if not found
        """
        self._ensure_loaded()
        if name in self._configs:
            del self._configs[name]
            self._save_config()
            return True
        return False

    def reload(self) -> None:
        """Reload configuration from file."""
        self._configs = None
        self._ensure_loaded()

    # =========================================================================
    # Client Management
    # =========================================================================

    def create_client(
        self,
        name: str,
        auto_initialize: bool = False,
    ) -> MCPClient | None:
        """
        Create a new client for a server.

        Args:
            name: Server name
            auto_initialize: Start and initialize immediately

        Returns:
            MCPClient or None if server not found
        """
        config = self.get_server(name)
        if config is None:
            self._logger.warning(f"MCP server not found: {name}")
            return None

        if not config.enabled:
            self._logger.warning(f"MCP server disabled: {name}")
            return None

        client = MCPClient(
            command=config.full_command,
            env=config.env or None,
            cwd=self.workspace_path,
        )

        if auto_initialize:
            try:
                client.start()
                client.initialize()
            except MCPClientError as e:
                self._logger.error(f"Failed to initialize MCP server {name}: {e}")
                client.close()
                raise

        return client

    def get_client(self, name: str) -> MCPClient | None:
        """
        Get or create a connected client for a server.

        Clients are cached and reused. Automatically reconnects if needed.

        Args:
            name: Server name

        Returns:
            Connected MCPClient or None
        """
        # Check cache
        if name in self._clients:
            client = self._clients[name]
            if client.is_connected and client.is_initialized:
                return client
            # Cleanup dead client
            client.close()
            del self._clients[name]

        # Create new client
        try:
            client = self.create_client(name, auto_initialize=True)
            if client:
                self._clients[name] = client
            return client
        except MCPClientError as e:
            self._logger.error(f"Failed to connect to MCP server {name}: {e}")
            return None

    def close_client(self, name: str) -> None:
        """
        Close and remove a client.

        Args:
            name: Server name
        """
        if name in self._clients:
            self._clients[name].close()
            del self._clients[name]

    def close_all(self) -> None:
        """Close all active clients."""
        for name in list(self._clients.keys()):
            self.close_client(name)

    # =========================================================================
    # Tool Discovery
    # =========================================================================

    def discover_all_tools(self, validate_schemas: bool = True) -> ToolDiscoveryResult:
        """
        Discover tools from all enabled MCP servers.

        Queries each enabled server for its tools, validates schemas,
        and returns a unified result with all discovered tools.

        Args:
            validate_schemas: Whether to validate tool input schemas

        Returns:
            ToolDiscoveryResult with all discovered tools and server statuses
        """
        discovery = MCPToolDiscovery(self)
        return discovery.discover_all(validate_schemas=validate_schemas)

    def discover_server_tools(self, server_name: str, validate_schemas: bool = True) -> list:
        """
        Discover tools from a specific server.

        Args:
            server_name: Server name to query
            validate_schemas: Whether to validate tool input schemas

        Returns:
            List of DiscoveredTool instances
        """
        discovery = MCPToolDiscovery(self)
        return discovery.discover_server(server_name, validate_schemas)

    # =========================================================================
    # Internal Methods
    # =========================================================================

    def _ensure_loaded(self) -> None:
        """Ensure configuration is loaded."""
        if self._configs is None:
            self._load_config()

    def _load_config(self) -> None:
        """Load configuration from file."""
        self._configs = {}

        if not self.config_path.exists():
            self._logger.debug(f"MCP config not found: {self.config_path}")
            return

        try:
            with open(self.config_path, encoding="utf-8") as f:
                data = json.load(f)

            # Parse servers
            servers = data.get("servers", data.get("mcpServers", {}))

            if isinstance(servers, dict):
                # Format: {"name": {...config...}}
                for name, config_data in servers.items():
                    if isinstance(config_data, dict):
                        config_data["name"] = name
                        config = MCPServerConfig.from_dict(config_data)
                        self._configs[name] = config

            elif isinstance(servers, list):
                # Format: [{...config...}, ...]
                for config_data in servers:
                    if isinstance(config_data, dict):
                        config = MCPServerConfig.from_dict(config_data)
                        self._configs[config.name] = config

            self._logger.info(f"Loaded {len(self._configs)} MCP server configs")

        except json.JSONDecodeError as e:
            self._logger.error(f"Invalid MCP config JSON: {e}")
        except Exception as e:
            self._logger.error(f"Failed to load MCP config: {e}")

    def _save_config(self) -> None:
        """Save configuration to file."""
        # Ensure directory exists
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        # Build config dict
        servers = {}
        for name, config in self._configs.items():
            servers[name] = {
                "command": config.command,
                "env": config.env,
                "enabled": config.enabled,
                "description": config.description,
                "args": config.args,
            }

        data = {"servers": servers}

        # Write file
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        self._logger.info(f"Saved MCP config to {self.config_path}")


# =============================================================================
# Default Configuration Template
# =============================================================================

DEFAULT_MCP_CONFIG = {
    "servers": {
        # Example: File system server (commented out by default)
        # "filesystem": {
        #     "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem"],
        #     "args": ["/tmp"],
        #     "enabled": true,
        #     "description": "File system access via MCP"
        # },
        # Example: GitHub server
        # "github": {
        #     "command": ["npx", "-y", "@modelcontextprotocol/server-github"],
        #     "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "your-token"},
        #     "enabled": false,
        #     "description": "GitHub API via MCP"
        # },
    }
}


def create_default_config(workspace_path: Path) -> Path:
    """
    Create default MCP configuration file.

    Args:
        workspace_path: Workspace directory

    Returns:
        Path to created config file
    """
    config_path = workspace_path / MCPRegistry.CONFIG_PATH / MCPRegistry.CONFIG_FILENAME
    config_path.parent.mkdir(parents=True, exist_ok=True)

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_MCP_CONFIG, f, indent=2)

    return config_path
