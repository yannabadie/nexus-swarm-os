# Test Fixtures

## Synopsis

Test fixtures, mocks, and sample data for NEXUS test suite. Provides reusable test infrastructure including mock MCP servers, stagnation samples, and shared test utilities.

## Fixtures

| File | Purpose | Usage |
|------|---------|-------|
| `mock_mcp_server.py` | Mock MCP server for testing MCP client | Simulates tool execution without real MCP server |
| `stagnation_samples.json` | Sample stagnant conversations for predictor training | Used by `test_stagnation_predictor.py` |

## Mock MCP Server

Provides a lightweight mock Model Context Protocol (MCP) server for testing:
- Simulates tool discovery
- Mocks tool execution results
- Validates request/response format
- No external dependencies

**Usage Example**:
```python
from tests.fixtures.mock_mcp_server import MockMCPServer

server = MockMCPServer()
tools = server.list_tools()
result = server.execute_tool("read_file", {"path": "test.txt"})
```

## Stagnation Samples

JSON file containing real conversation samples exhibiting stagnation patterns:
- Repetitive messages
- Circular reasoning
- Tool mention without execution
- Semantic similarity increase

Used by `StagnationPredictor` accuracy tests to validate prediction algorithms.

## Shared Test Fixtures (conftest.py)

Main test fixtures defined in `tests/conftest.py`:
- `MockDriver` - Mock LLM driver
- `MockConfig` - Test configuration
- `orchestrator_with_mocks` - OrchestratorV7 with mocked drivers
- `run_orchestrator_loop` - Helper for running FSM loops
- `temp_workspace` - Temporary workspace
- `sample_task_analysis` - Sample TaskAnalysis

## Dependencies

- Standard library only (no external dependencies)
- `unittest.mock` - Mocking framework

## Related

- [tests/conftest.py](../conftest.py) - Main test fixtures
- [tests/proofs/](../proofs/) - Legacy smoke/regression checks using these fixtures
- [core/interface_pkg/mcp/](../../core/interface_pkg/mcp/) - Real MCP implementation
