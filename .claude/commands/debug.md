---
description: "Debug test failures and errors - diagnose root cause and fix iteratively"
allowed-tools: "Bash,Glob,Read,Grep,Edit,TodoWrite"
---

# /debug Command - Debugging Agent

Invoke the debugging agent to diagnose and fix test failures or errors.

## Usage
- `/debug` - Analyze and fix all failing tests
- `/debug tests/core/swarm/test_bridge.py` - Debug specific test file
- `/debug ImportError` - Debug specific error type
- `/debug "StateTransitionError in orchestrator"` - Debug specific issue

## Arguments
`$ARGUMENTS` - Optional: specific test file, error type, or issue description

## Workflow

Based on the debugger agent, this command:

1. **Runs tests** to identify failures: `python -m pytest tests/ -q`
2. **Parses error output** - Extracts failure type, location, message
3. **Categorizes failures** - ASSERTION, EXCEPTION, TIMEOUT, IMPORT, FIXTURE
4. **Traces root cause** - Reads source, checks recent changes
5. **Implements fix** - Minimal change to resolve
6. **Re-runs tests** - Validates fix
7. **Iterates** until all tests pass or escalation needed

## NEXUS-Specific Error Patterns

| Error | Likely Cause | Check |
|-------|--------------|-------|
| `ImportError: circular` | HiveMind↔Swarm | `__init__.py` imports |
| `StateTransitionError` | Invalid FSM state | `TRANSITION_MATRIX` |
| `ValidationError` | Pydantic schema | Dataclass fields |
| `TimeoutError` | Async blocking | sync-in-async patterns |
| `AttributeError: NoneType` | Uninitialized | Initialization order |

## Investigation Commands
```bash
# Run specific test verbose
python -m pytest tests/path/test.py::test_name -v --tb=long

# Check imports
python -c "from core.module import Class"

# Check recent changes
git diff HEAD~5 -- <file>
```

## Task: $ARGUMENTS

If no specific target provided, run full test suite first:
```bash
python -m pytest tests/ -q
```

Then:
1. Parse all failures
2. Group by error type
3. Fix in order of dependency (IMPORT -> EXCEPTION -> ASSERTION)
4. Re-run after each fix
5. Report: error summary, root cause, fix applied, verification

Escalate if:
- More than 3 fix attempts on same issue
- Requires KERNEL.py modification
- Security-sensitive code affected
