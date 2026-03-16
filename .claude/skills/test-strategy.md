---
name: test-strategy
description: NEXUS testing patterns and conventions. Use when writing tests, debugging failures, or validating changes.
---

# NEXUS Testing Strategy

## Test File Naming Convention

- `test_*.py` - Unit tests
- `test_*_integration.py` - Integration tests (require real API keys)
- `test_*_e2e.py` - End-to-end tests
- Mirror module structure: `core/memory/rag.py` -> `tests/test_memory_rag.py`

## Test Organization

```
tests/
+-- conftest.py              # Shared fixtures
+-- test_*.py                # Unit tests (fast, no external deps)
+-- test_*_integration.py    # Integration (GEMINI_API_KEY, ANTHROPIC_API_KEY)
+-- torture_v8.py            # Stress tests (nightly CI)
+-- benchmark_professional.py # Performance benchmarks
```

## Fixtures Pattern (conftest.py)

**Use module-level fixtures**:
```python
@pytest.fixture(scope="session")
def expensive_setup():
    # Reused across all tests

@pytest.fixture(scope="function")
def isolated_test():
    # Fresh for each test
```

**Common fixtures available**:
- `tmp_path` - Temporary directory
- `orchestrator_with_mocks` - OrchestratorV7 with mocked drivers
- `orchestrator_with_swarm` - With SwarmEngine enabled

## Assertion Style

**Informative failures**:
```python
# [NO] Bad
assert result.status == "success"

# [OK] Good
assert result.status == "success", f"Expected success, got {result.status}: {result.error}"
```

## Running Tests

```bash
# All tests
pytest tests/

# Specific test file
pytest tests/test_orchestration.py -v

# Specific test
pytest tests/test_orchestration.py::TestOrchestratorV7::test_idle_to_brainstorming -v

# With coverage
pytest tests/ --cov=core --cov-report=term-missing

# Fast (skip slow tests)
pytest tests/ -m "not slow"

# Integration tests only (requires API keys)
SKIP_LLM_TESTS=0 pytest tests/test_*_integration.py
```

## Coverage Requirements

- **Minimum**: 40% (enforced by CI)
- **Target**: 60%+ for core modules
- **Critical modules**: 80%+ (orchestration, drivers, security)

## Test Categories (markers)

```python
@pytest.mark.slow          # Long-running tests
@pytest.mark.integration   # Requires external services
@pytest.mark.torture       # Stress/chaos tests
```

## Mocking Guidelines

**Mock external dependencies**:
- LLM API calls (GeminiDriverV7, ClaudeDriverHybrid)
- File system (when not testing I/O)
- Time (for deterministic tests)

**V12.4 Mock Updates** (after P5.1 refactoring):
```python
# [NO] Old (fails - driver not imported directly)
with patch('core.orchestration_v7.GeminiDriverV7'):

# [OK] New (correct - mock factory)
with patch('core.drivers.async_factory.AsyncDriverFactory.get_best_gemini'):
```

## Common Patterns

**Testing state transitions**:
```python
def test_idle_to_brainstorming(orchestrator_with_mocks):
    orch = orchestrator_with_mocks
    assert orch.state == OrchestratorState.IDLE

    result = orch.process_turn("test task")

    assert orch.state == OrchestratorState.BRAINSTORMING
    assert result["finished"] is False
```

**Testing tool execution**:
```python
def test_tool_execution(orchestrator_with_mocks):
    orch = orchestrator_with_mocks
    tool_use = ToolUse(tool_name="read", params={"file_path": "test.txt"})

    result = orch.execute_tool(tool_use)

    assert result.status == "success"
```

## Debugging Failed Tests

1. **Run with verbose output**: `pytest tests/test_file.py -vv`
2. **Show print statements**: `pytest tests/test_file.py -s`
3. **Stop on first failure**: `pytest tests/test_file.py -x`
4. **Run failed tests only**: `pytest --lf`
5. **Debug with breakpoint**: Add `import pdb; pdb.set_trace()` in test

## CI Test Execution

**GitHub Actions runs**:
- Python 3.11, 3.12, 3.13 (matrix)
- Coverage threshold: 40%
- Timeout: 60s per test
- Fail-fast: disabled (all variants run)

**Before committing**:
```bash
# Run tests locally
pytest tests/ --tb=short

# Check coverage
pytest tests/ --cov=core --cov-fail-under=40

# Verify syntax
python -m py_compile $(find core -name "*.py")
```

## NEXUS-Specific Test Considerations

**FSM State Machine**:
- Test all state transitions in `TRANSITION_MATRIX`
- Verify guards prevent invalid transitions
- Test panic/error recovery paths

**Multi-Agent Orchestration**:
- Mock both Gemini and Claude drivers
- Test agent alternation enforcement
- Verify message validation (Pydantic)

**Memory Systems**:
- Test blackboard persistence
- Verify Auto-Memory recording
- Test RAG retrieval accuracy

**Security**:
- Test InputGuard threat detection
- Verify OutputGuard response filtering
- Test KERNEL integrity enforcement

## Pro Tips

- **Use fixtures liberally** - DRY principle
- **Test edge cases** - Empty inputs, None values, invalid types
- **Test error paths** - Not just happy path
- **Keep tests fast** - Mock I/O, use in-memory data
- **Make tests deterministic** - No random data, fixed seeds
- **One concept per test** - Easy to debug when it fails

## When Tests Fail in CI

1. Check CI logs: `gh run view <run-id> --log-failed`
2. Identify error pattern (import, assertion, timeout)
3. Reproduce locally: Same Python version
4. Fix and verify: Run tests before pushing
5. **VERIFY CI passes**: `gh run list` after push

Remember: **NEVER claim "tests pass" without running them** [OK]
