# MCP Server Implementation Guide for NEXUS

**Date**: 2025-12-11
**Source**: Research agent (MCP SDK, FastMCP)
**Target**: NEXUS V9.1.0 MCP Server

---

## Executive Summary

The Model Context Protocol (MCP) is Anthropic's open standard for LLM-tool integration. NEXUS currently has an MCP **Client** (`core/mcp/client.py`). This guide covers adding MCP **Server** capability to expose NEXUS as a tool for Claude Desktop.

---

## 1. FastMCP - Recommended Approach

### Installation
```bash
pip install mcp
```

### Basic Pattern
```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("NEXUS Server")

@mcp.tool()
def spawn_agent(specialty: str, description: str = "") -> dict:
    """Create a specialized agent in NEXUS workspace."""
    return {"status": "spawned", "agent_id": "..."}

if __name__ == "__main__":
    mcp.run(transport="stdio")
```

---

## 2. Transport Options

| Transport | Use Case | Configuration |
|-----------|----------|---------------|
| **stdio** | Claude Desktop (local) | Default, subprocess |
| **SSE** | Remote clients | HTTP Server-Sent Events |
| **HTTP Streamable** | New 2025 spec | Single bidirectional endpoint |

### Claude Desktop Configuration

**Location**: `%APPDATA%\Claude\claude_desktop_config.json` (Windows)

```json
{
  "mcpServers": {
    "nexus": {
      "command": "python",
      "args": ["C:/Code/NEXUS/NEXUS-N7A/nexus_mcp_server.py"]
    }
  }
}
```

---

## 3. Proposed Tool Categories

| Category | Tools | Description |
|----------|-------|-------------|
| **Orchestration** | `analyze_task`, `execute_pipeline` | HiveMind 7-phase pipeline |
| **Swarm** | `execute_swarm`, `negotiate_mode` | 6 swarm modes |
| **Agent Management** | `spawn_agent`, `list_agents` | Spawned agents |
| **Evolution** | `trigger_evolution` | Children creation |
| **Memory** | `query_memory` | RAG + SuccessMemory |

---

## 4. Implementation Plan

### File Structure
```
core/mcp/
+-- __init__.py      # Existing
+-- client.py        # Existing MCP client
+-- server.py        # NEW - MCP server
+-- tools.py         # NEW - Tool definitions

nexus_mcp_server.py  # NEW - Entry point
```

### Server Implementation

```python
# core/mcp/server.py

class NexusMCPServer:
    def __init__(self, workspace_path: Path):
        self.workspace = workspace_path
        self.mcp = FastMCP("NEXUS Orchestrator")
        self._register_tools()

    def _register_tools(self):
        @self.mcp.tool()
        def spawn_agent(specialty: str) -> dict:
            """Create a specialized agent."""
            pool = SpawningPool(self.workspace)
            agent_id = pool.spawn(specialty)
            return {"agent_id": agent_id}

        @self.mcp.tool()
        def execute_swarm(task: str, mode: str) -> dict:
            """Execute task with swarm mode."""
            engine = SwarmEngine(self.workspace)
            return engine.execute(task, mode).to_dict()

    def run(self, transport: str = "stdio"):
        self.mcp.run(transport=transport)
```

---

## 5. Security Best Practices

### Critical Rules
1. **Path Traversal Protection**: Validate all paths within `workspace/`
2. **Tool Authorization**: Allow/deny lists for sensitive operations
3. **Audit Logging**: Log all MCP tool invocations
4. **Rate Limiting**: Prevent abuse of expensive operations

### Restricted Tools
```python
RESTRICTED_TOOLS = [
    "delete_all_agents",
    "override_kernel",
    "execute_arbitrary_code",
]
```

---

## 6. Testing

### MCP Inspector
```bash
# Install mcp CLI
pip install mcp

# Run with inspector
mcp dev nexus_mcp_server.py
```

---

## 7. Desktop Extension (Future)

One-click installation via `.mcpb` bundle:
```
nexus-extension.mcpb/
+-- manifest.json
+-- server.py
+-- requirements.txt
+-- README.md
```

---

## Sources

- [GitHub - modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk)
- [FastMCP Documentation](https://gofastmcp.com/servers/tools)
- [Claude Desktop MCP Integration](https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop)
