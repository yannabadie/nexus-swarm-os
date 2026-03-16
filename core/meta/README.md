# NEXUS Meta Module

## Synopsis

The **meta** module provides introspection capabilities for NEXUS, enabling self-analysis of CLI tools and agent capabilities. It allows agents to discover available commands, inspect tool signatures, and understand the system's interface.

## Component Map

| File | Purpose | Key Exports |
|------|---------|-------------|
| `cli_inspector.py` | CLI tool introspection | `CLIInspector`, `ToolSignature` |

## Key Interfaces

### CLIInspector
```python
class CLIInspector:
    """Inspects CLI tools and extracts signatures."""

    def get_tool_signature(self, tool_name: str) -> ToolSignature
    def list_available_tools(self) -> List[str]
    def get_tool_help(self, tool_name: str) -> str
```

### ToolSignature
```python
@dataclass
class ToolSignature:
    name: str
    description: str
    parameters: List[Parameter]
    return_type: Optional[str]
    examples: List[str]
```

## Usage

```python
from core.meta import CLIInspector

inspector = CLIInspector()

# List available tools
tools = inspector.list_available_tools()

# Get tool signature
sig = inspector.get_tool_signature("read")
print(f"Tool: {sig.name}")
print(f"Params: {sig.parameters}")
```

## Dependencies

### External
- Standard library (inspect, ast)

## Version History

- **V8.0** - Initial CLIInspector implementation
- **V12.4** - Enhanced signature extraction
