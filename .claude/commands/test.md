---
description: "Run tests with analysis - execute pytest, parse results, suggest fixes"
allowed-tools: "Bash,Read,Grep,TodoWrite"
---

# /test Command - Test Runner

Run the NEXUS test suite with intelligent analysis of results.

## Usage
- `/test` - Run all tests
- `/test core/swarm` - Run tests for specific module
- `/test --coverage` - Run with coverage report
- `/test --verbose` - Run with verbose output
- `/test test_hive_mind_e2e.py` - Run specific test file

## Arguments
`$ARGUMENTS` - Optional: test path, module name, or flags

## Test Commands

```bash
# All tests (quick)
python -m pytest tests/ -q

# Specific module
python -m pytest tests/core/swarm/ -v

# With coverage
python -m pytest --cov=core --cov-report=term-missing tests/

# Specific file
python -m pytest tests/test_specific.py -v

# Pattern matching
python -m pytest tests/ -k "swarm or hive"
```

## Test Categories

| Directory | Type | Count |
|-----------|------|-------|
| `tests/` | All tests | 667+ |
| `tests/core/` | Unit tests | ~400 |
| `tests/integration/` | Integration | ~100 |
| `tests/torture/` | Stress tests | ~50 |
| `tests/v11/` | V11 specific | ~30 |

## Analysis Output

After running tests, provide:

1. **Summary**
   - Total: X tests
   - Passed: Y (Z%)
   - Failed: N
   - Skipped: M

2. **Failures** (if any)
   - Test name
   - Error type
   - File:line
   - Brief cause analysis

3. **Coverage** (if --coverage)
   - Overall %
   - Low coverage modules
   - Missing lines

4. **Recommendations**
   - Fix priorities (which failures to address first)
   - Flaky test warnings
   - Performance issues (slow tests)

## Task: $ARGUMENTS

Parse arguments and run appropriate test command.

If `$ARGUMENTS` is empty, run: `python -m pytest tests/ -q`

If `$ARGUMENTS` contains:
- A path: run tests for that path
- `--coverage`: add coverage flags
- `--verbose`: add `-v` flag
- A module name: find and run module tests

After execution, parse output and provide analysis report.
