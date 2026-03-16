# NEXUS MCP Module

## Synopsis

The **mcp** module implements the Model Context Protocol (MCP) for bidirectional agent communication. It provides both client capabilities (consuming external MCP servers) and server capabilities (exposing NEXUS as an MCP server for tools like Claude Desktop).

## Architecture

```text
MCP ARCHITECTURE
================

Client mode:
  NEXUS -> MCPClient -> external MCP servers
  Examples:
    - @modelcontextprotocol/server-filesystem
    - @modelcontextprotocol/server-github
    - custom MCP servers

Server mode:
  external clients -> server.py -> NEXUS
  Examples:
    - Claude Desktop
    - other MCP-compatible tools
```

## Component Map

| File | Purpose | Key Exports |
|------|---------|-------------|
| `protocol.py` | JSON-RPC 2.0 types | `MCPRequest`, `MCPResponse`, `MCPTool` |
| `client.py` | Consume external servers | `MCPClient` |
| `registry.py` | Server configuration | `MCPRegistry` |
| `server.py` | Expose NEXUS as server | MCP server implementation |

## Protocol Types

```python
@dataclass
class MCPRequest:
    jsonrpc: str = "2.0"
    method: str
    params: Optional[Dict] = None
    id: Optional[str] = None

@dataclass
class MCPResponse:
    jsonrpc: str = "2.0"
    result: Optional[Any] = None
    error: Optional[MCPError] = None
    id: Optional[str] = None

@dataclass
class MCPTool:
    name: str
    description: str
    inputSchema: Dict  # JSON Schema
```

## Key Interfaces

### MCPClient
```python
class MCPClient:
    """Client for consuming external MCP servers."""

    def __init__(self, command: List[str], env: Optional[Dict] = None)
    def initialize(self) -> MCPCapabilities
    def call_tool(self, name: str, arguments: Dict) -> MCPToolResult
    def list_tools(self) -> List[MCPTool]
    def close(self) -> None
```

### MCPRegistry
```python
class MCPRegistry:
    """Loads server configurations from mcp_servers.json."""

    def __init__(self, workspace_path: Path)
    def get_server(self, name: str) -> MCPServerConfig
    def list_servers(self) -> List[str]
```

## Client Usage

```python
from core.mcp import MCPClient, MCPRegistry

# Via registry (recommended)
registry = MCPRegistry(workspace_path)
config = registry.get_server("filesystem")
client = MCPClient(**config)

# Direct usage
client = MCPClient(
    command=["npx", "-y", "@modelcontextprotocol/server-filesystem"],
    env={"MCP_ROOT": "/tmp"}
)
client.initialize()

# Call tool
result = client.call_tool("read_file", {"path": "/tmp/test.txt"})
print(result.content)

# Cleanup
client.close()
```

## Server Mode (V9.0)

Run NEXUS as an MCP server:

```bash
python -m core.mcp.server
```

Server tools (high-level):
- `nexus_read`, `nexus_glob`, `nexus_grep` - workspace file access
- `nexus_analyze`, `nexus_status` - agent analysis and system status
- `nexus_research` - local-first research summary (mock/local mode)
- `nexus_memory_search` - structured project memory search
- `nexus_export_evidence_pack` - evidence pack artifacts (report, sources, trace, graph, manifest)
- `nexus_start_evidence_job`, `nexus_job_status`, `nexus_cancel_job` - background evidence-pack workflow control

Server resources:
- `nexus://config`
- `nexus://agents`
- `nexus://evidence/latest`
- `nexus://evidence-ledger/latest`
- `nexus://swarm-eval/latest`
- `nexus://provider-canaries/latest`
- `nexus://jobs/latest`

Server prompts:
- `Grounded Research`
- `Evidence Review`

Configure in Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "nexus": {
      "command": "python",
      "args": ["-m", "core.mcp.server"],
      "cwd": "/path/to/nexus"
    }
  }
}
```

## Registry Configuration

`workspace/mcp_servers.json`:

```json
{
  "servers": {
    "filesystem": {
      "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem"],
      "env": {"MCP_ROOT": "/workspace"}
    },
    "github": {
      "command": ["npx", "-y", "@modelcontextprotocol/server-github"],
      "env": {"GITHUB_TOKEN": "${GITHUB_TOKEN}"}
    }
  }
}
```

## Dependencies

### External
- `mcp` - MCP SDK (optional, for server mode)
- Standard library (subprocess, json)

## Version History

- **V8.0** - MCPClient for external server consumption
- **V9.0** - MCPServer for exposing NEXUS
- **V12.4** - Enhanced registry, tool schema validation
