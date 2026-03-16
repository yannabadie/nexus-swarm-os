# NEXUS Test Suite

## Synopsis

Test suite covering NEXUS runtime, API, memory, security, and workflow behavior. Exact counts and CI outcomes are published in the generated evidence ledger, not hardcoded in this document.

## Test Categories

| Category | Directory | Description | Key Tests |
|----------|-----------|-------------|-----------|
| **Core Unit Tests** | `tests/` (root) | 90+ unit tests for individual modules | FSM, drivers, memory, security, evolution |
| **API Tests** | `tests/api/` | REST API and RBAC validation | RBAC permissions, role hierarchy |
| **Audit Tests** | `tests/audit/` | System integrity audits | Isolation physics, security validation |
| **Fixtures** | `tests/fixtures/` | Test fixtures and mocks | MockDriver, mock_mcp_server |
| **FSM Tests** | `tests/fsm/` | Finite state machine tests | Hibernate, stagnation predictor |
| **Interaction Tests** | `tests/interaction/` | Human-in-the-loop tests | HITL persistence |
| **Smoke Checks** | `tests/proofs/` | Legacy path for smoke/regression checks | Headless mode verification |
| **Torture Tests** | `tests/torture/` | Resilience and chaos testing | Saga crash recovery, compensation |
| **Workflow Tests** | `tests/workflow/` | Distributed workflow tests | Redis registry, distributed locks |
| **V10 Tests** | `tests/v10/` | PRISM isolation suite | Cerebro API, memory optimization |
| **V11 Tests** | `tests/v11/` | SENTINEL security suite | Cortex, Keymaker, Memoria |

## Running Tests

### All Tests
```bash
python -m pytest tests/ -v
```

### Specific Categories
```bash
# Unit tests only
python -m pytest tests/test_*.py -v

# Torture tests
python -m pytest tests/torture/ -v

# API tests
python -m pytest tests/api/ -v

# Version-specific tests
python -m pytest tests/v10/ -v
python -m pytest tests/v11/ -v
```

### Specific Test Files
```bash
# Simple smoke test
python -m pytest tests/test_simple.py -v

# FSM transitions
python -m pytest tests/test_fsm_transitions.py -v

# Swarm engine
python -m pytest tests/test_hybrid_swarm.py -v

# Memory systems
python -m pytest tests/test_success_memory.py -v
python -m pytest tests/test_memory_retrieval.py -v
```

### Manual Execution
```bash
# Simple smoke tests (no pytest)
python tests/test_simple.py

# Global integration test
python tests/test_global_integration.py

# Verification scripts
python tests/verify_stability.py
python tests/verify_hive_mind.py
```

## Test Coverage

### Core Modules (90+ tests)

**Orchestration & FSM (15+ tests)**
- `test_fsm_transitions.py` - State machine transitions
- `test_hive_mind_e2e.py` - HiveMind pipeline E2E
- `test_hive_mind_execution.py` - HiveMind execution
- `test_async_hive_mind.py` - Async HiveMind operations
- `test_agent_service.py` - Agent service layer
- `test_bootstrap_service.py` - Bootstrap service

**Swarm Engine (10+ tests)**
- `test_hybrid_swarm.py` - All 6 swarm modes
- `test_swarm_bridge.py` - HiveMind-Swarm delegation
- `test_swarm_tool.py` - Swarm as tool
- `test_swarm_session_integration.py` - Session integration
- `test_agent_alternation.py` - Agent alternation patterns
- `test_hot_swap_lead.py` - Dynamic lead swapping
- `test_merge_strategies.py` - Result merging

**Drivers & LLM Integration (8+ tests)**
- `test_async_drivers.py` - Async driver operations
- `test_gemini_driver_session.py` - Gemini session persistence
- `test_stream_parser.py` - Streaming response parser
- `test_model_router.py` - Intelligent model routing
- `test_llm_context_isolation.py` - Context isolation
- `test_agent_as_tool.py` - Agent-as-tool pattern

**Memory Systems (8+ tests)**
- `test_success_memory.py` - Success memory RAG
- `test_memory_retrieval.py` - Memory retrieval
- `test_project_memory.py` - Project-specific memory
- `test_memory_service.py` - Memory service layer
- `test_dense_backend.py` - Dense vector backend
- `test_automemory_integration.py` - Auto-memory integration
- `test_atomic_store.py` - Atomic storage

**Security & KERNEL (10+ tests)**
- `test_security.py` - Security validation
- `test_security_execution_policy.py` - Execution policies
- `test_kernel_heredity.py` - KERNEL inheritance
- `test_prompt_injection.py` - Prompt injection protection
- `test_prompt_validator.py` - Prompt validation
- `test_path_traversal_security.py` - Path traversal protection
- `test_ssrf_protection.py` - SSRF protection
- `test_rate_limiter.py` - Rate limiting
- `test_circuit_breaker.py` - Circuit breaker pattern

**Evolution & Mutation (5+ tests)**
- `test_evolution_core.py` - Evolution engine
- `test_mutation_parser.py` - Mutation parsing
- `test_spinoff_service.py` - Spinoff creation
- `test_graph_of_thought.py` - Graph of Thought reasoning
- `test_auto_bootstrap.py` - Auto-bootstrap protocol

**Async & Resilience (10+ tests)**
- `test_async_primitives.py` - Async primitives (33 tests)
- `test_saga_manager.py` - Saga pattern
- `test_safe_task_manager.py` - Safe task management
- `test_adaptive_fallback.py` - Adaptive fallback
- `test_self_healing.py` - Self-healing mechanisms

**Session & State (8+ tests)**
- `test_session_manager.py` - Session lifecycle
- `test_session_metrics.py` - Session metrics
- `test_ephemeral_sessions.py` - Ephemeral sessions
- `test_workspace_manager.py` - Workspace management
- `test_workspace_isolation.py` - Workspace isolation
- `test_context_scope.py` - Context scoping

**Tools & Execution (8+ tests)**
- `test_tool_manager.py` - Tool management
- `test_tool_registry.py` - Tool registry
- `test_unified_registry.py` - Unified registry
- `test_execution_engine.py` - Execution engine
- `test_dynamic_tools.py` - Dynamic tool generation
- `test_mcp_client.py` - MCP client
- `test_mcp_server.py` - MCP server

**Telemetry & Monitoring (5+ tests)**
- `test_telemetry_service.py` - Telemetry service
- `test_telemetry_export.py` - Telemetry export
- `test_budget_tracker.py` - Token budget tracking
- `test_budget_service.py` - Budget service
- `test_event_bus.py` - Event bus

**Validation & Quality (5+ tests)**
- `test_validation_service.py` - Validation service
- `test_tiered_validator.py` - Tiered validation
- `test_task_completion_validator.py` - Task completion
- `test_cot_enforcement.py` - Chain-of-thought enforcement
- `test_analysis_adapter.py` - Analysis adaptation

**Integration & E2E (5+ tests)**
- `test_global_integration.py` - Full system integration
- `test_integration.py` - Component integration
- `test_v8_integrations.py` - V8 feature integration
- `test_fast_path.py` - Fast path optimization
- `test_phase16_dx.py` - Phase 16 DX features

**Benchmarks (3 tests)**
- `benchmark_professional.py` - Professional benchmarks
- `benchmark_realworld.py` - Real-world scenarios
- `stress_test_torture.py` - Stress testing

**Verification Scripts (3 scripts)**
- `verify_stability.py` - System stability
- `verify_hive_mind.py` - HiveMind verification
- `verify_hive_mind_routing.py` - Routing verification

## Test Configuration

### Fixtures (conftest.py)

**MockDriver**: Reusable mock for GeminiDriverV7 and ClaudeDriverHybrid
```python
driver = MockDriver("Gemini")
driver.set_responses([
    {"sender": "Gemini", "action_type": "TALK", "content": "...", "status": "CONTINUE"},
    {"sender": "Gemini", "action_type": "FINISH", "content": "...", "status": "FINISHED"},
])
```

**MockConfig**: Test configuration with sensible defaults
- Temporary workspace
- Mocked API paths
- Disabled notifications
- Fast timeouts

**orchestrator_with_mocks**: OrchestratorV7 with mocked drivers (no API calls)
```python
def test_something(orchestrator_with_mocks):
    orch = orchestrator_with_mocks
    orch.drivers["Gemini"].set_responses([...])
    result = orch.process_turn("Do something")
```

**run_orchestrator_loop**: Helper to run orchestrator until completion
```python
def test_loop(orchestrator_with_mocks, run_orchestrator_loop):
    result = run_orchestrator_loop(orch, "Task", max_iterations=10)
    assert result["final_state"] == "IDLE"
```

## Test Dependencies

**Required**:
- `pytest` - Test framework
- `pytest-asyncio` - Async test support

**Optional**:
- `fakeredis` - Redis mocking (workflow tests)
- Standard library mocking (`unittest.mock`)

## Test Philosophy

**Truth-Bound Testing**:
- Test actual code behavior, not assumptions
- Mock only external dependencies (APIs, file system)
- Use real implementations for internal modules
- Verify state transitions explicitly

**Coverage Strategy**:
- Unit tests: Individual functions/classes
- Integration tests: Module interactions
- E2E tests: Full system workflows
- Torture tests: Edge cases and resilience
- Smoke checks: Regression-oriented checks for major features

**Anti-Patterns to Avoid**:
- Testing mocks instead of implementation
- Over-mocking internal dependencies
- Brittle tests tied to implementation details
- Missing negative test cases

## CI/CD Integration

Tests are designed for continuous integration:
- Exit code 0 on success
- Exit code 1 on failure
- Verbose output with `-v`
- Parallel execution supported
- Isolated temporary workspaces

## Subdirectories

- [api/](api/) - REST API and RBAC tests
- [audit/](audit/) - System integrity audits
- [fixtures/](fixtures/) - Test fixtures and mocks
- [fsm/](fsm/) - FSM state machine tests
- [interaction/](interaction/) - Human-in-the-loop tests
- [proofs/](proofs/) - Smoke tests for major features
- [torture/](torture/) - Resilience and chaos testing
- [v10/](v10/) - PRISM isolation suite (V10)
- [v11/](v11/) - SENTINEL security suite (V11)
- [workflow/](workflow/) - Distributed workflow tests

## Maintenance

**Adding New Tests**:
1. Place in appropriate category directory
2. Use existing fixtures from `conftest.py`
3. Follow naming convention: `test_*.py`
4. Update this README with test description

**Updating Existing Tests**:
1. Verify test still reflects actual behavior
2. Update mocks if API changes
3. Add new test cases for bug fixes
4. Document breaking changes

## Related Documentation

- [Core Architecture](../docs/architecture/GLOBAL_ARCHITECTURE.md)
- [Workflow Map](../docs/architecture/WORKFLOWS_MAP.md)
- [Development Guide](../ROADMAP.md)
- [Module READMEs](../core/README.md)
