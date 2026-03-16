# NEXUS V7 Test Protocol

**Version**: 1.0
**Date**: 2025-11-27
**Status**: Active

---

## 1. Overview

This document defines the formal testing protocol for NEXUS V7 Chrysalis. It covers:
- Test categories and priorities
- Test execution procedures
- Autonomous debug cycle workflow
- Session persistence for cross-session continuity
- Pass/fail criteria

---

## 2. Test Categories

### 2.1 Priority Levels

| Priority | Category | Threshold | Blocking Release |
|----------|----------|-----------|------------------|
| **CRITICAL** | Security, FSM, Core Tools | 100% pass | YES |
| **HIGH** | Swarm, Bootstrap, Evolution | >=90% pass | YES |
| **MEDIUM** | Integration, Routing | >=85% pass | NO |
| **LOW** | UI, Logging, Metrics | >=80% pass | NO |

### 2.2 Test Files

| File | Category | Tests | Priority |
|------|----------|-------|----------|
| `test_e2e_nexus.py` | End-to-End Suite | ~115 | CRITICAL/HIGH |
| `test_security.py` | Security | ~50 | CRITICAL |
| `test_fsm_transitions.py` | FSM | ~25 | CRITICAL |
| `test_tool_manager.py` | Tools | ~20 | CRITICAL |
| `test_hybrid_swarm.py` | Swarm | ~30 | HIGH |
| `test_auto_bootstrap.py` | Bootstrap | ~15 | HIGH |
| `test_graph_of_thought.py` | GoT | ~20 | HIGH |
| `test_integration.py` | Integration | ~25 | MEDIUM |
| `test_model_router.py` | Routing | ~15 | MEDIUM |
| `verify_stability.py` | Stability | ~5 | CRITICAL |

---

## 3. Test Matrix

### 3.1 E2E Test Classes

| Test Class | Tests | Category | Status |
|------------|-------|----------|--------|
| `TestOrchestratorE2E` | 25 | Core | [ ] |
| `TestREPLCommandsE2E` | 20 | REPL | [ ] |
| `TestFSMFlowsE2E` | 15 | FSM | [ ] |
| `TestSwarmModesE2E` | 20 | Swarm | [ ] |
| `TestEvolutionE2E` | 15 | Evolution | [ ] |
| `TestSecurityE2E` | 20 | Security | [ ] |

Legend: [OK] Pass | [NO] Fail | [ ] Not Run

### 3.2 Critical Tests

| ID | Test | File | Status |
|----|------|------|--------|
| C001 | Orchestrator initializes in IDLE | test_e2e_nexus.py | [ ] |
| C002 | Path traversal blocked | test_security.py | [ ] |
| C003 | Sacred files protected | test_security.py | [ ] |
| C004 | FSM transitions correct | test_fsm_transitions.py | [ ] |
| C005 | Tool execution safe | test_tool_manager.py | [ ] |
| C006 | Panic state terminal | test_fsm_transitions.py | [ ] |

---

## 4. Execution Commands

### 4.1 Quick Tests (~2 min)

```bash
cd NEXUS_V7_CHRYSALIS
python -m pytest tests/test_e2e_nexus.py -v --tb=short -m "not slow"
```

### 4.2 Full Test Suite (~10 min)

```bash
python -m pytest tests/ -v --tb=line
```

### 4.3 Category-Specific Tests

```bash
# Security tests only
python -m pytest tests/ -v -m security

# FSM tests only
python -m pytest tests/ -v -m fsm

# E2E tests only
python -m pytest tests/ -v -m e2e

# Swarm tests only
python -m pytest tests/ -v -m swarm
```

### 4.4 Single Test Debug

```bash
python -m pytest tests/test_e2e_nexus.py::TestOrchestratorE2E::test_simple_task_complete_cycle -v --tb=long
```

### 4.5 Coverage Report

```bash
python -m pytest tests/ --cov=core --cov-report=html
```

---

## 5. Autonomous Debug Cycle Workflow

### 5.1 Workflow Diagram

```
+-----------------------------------------+
|         AUTONOMOUS DEBUG CYCLE          |
+-----------------------------------------+
|                                         |
|  1. RUN TESTS                           |
|     pytest tests/ -v --tb=short         |
|              |                          |
|              v                          |
|  2. ALL PASSED? --- YES --► DONE [OK]     |
|              |                          |
|              NO                         |
|              v                          |
|  3. PARSE FAILURES                      |
|     - Categorize (IMPORT/ASSERT/etc)    |
|     - Prioritize (P1-P4)                |
|              |                          |
|              v                          |
|  4. FOR EACH FAILURE (max 3 attempts):  |
|     a. INVESTIGATE (read source)        |
|     b. CLASSIFY (BUG/TEST/ENV)          |
|     c. FIX (minimal change)             |
|     d. VERIFY (re-run single test)      |
|              |                          |
|              v                          |
|  5. SAVE STATE                          |
|     debug_cycle_state.json              |
|              |                          |
|              v                          |
|  6. CONTEXT LIMIT? --- YES --► HANDOFF  |
|              |                          |
|              NO                         |
|              +----------► LOOP (1)      |
+-----------------------------------------+
```

### 5.2 Error Categories

| Category | Pattern | Priority | Action |
|----------|---------|----------|--------|
| IMPORT_ERROR | ImportError, ModuleNotFoundError | P1 | Fix imports/paths |
| SYNTAX_ERROR | SyntaxError | P1 | Fix syntax |
| ATTRIBUTE_ERROR | AttributeError | P2 | Add missing method/attr |
| TYPE_ERROR | TypeError | P2 | Fix type mismatch |
| ASSERTION_ERROR | AssertionError | P3 | Debug logic/fix test |
| TIMEOUT | TimeoutError | P4 | Optimize or increase timeout |
| FIXTURE_ERROR | fixture not found | P1 | Add fixture to conftest |

### 5.3 Fix Classification

| Classification | Description | Action |
|----------------|-------------|--------|
| BUG | Actual code bug | Fix in source |
| TEST | Test is incorrect | Fix test |
| ENV | Environment issue | Fix setup |
| SKIP | Cannot fix now | Mark skip |

---

## 6. Session Persistence

### 6.1 State File Location

```
workspace/logs/debug_cycle_state.json
```

### 6.2 State File Format

```json
{
  "session_id": "2025-11-27T10:00:00Z",
  "cycle_number": 1,
  "status": "IN_PROGRESS",
  "initial_test_run": {
    "total_tests": 115,
    "passed": 100,
    "failed": 15,
    "errors": 5,
    "skipped": 2
  },
  "failures": [
    {
      "id": "F001",
      "test_id": "test_e2e_nexus.py::TestOrchestratorE2E::test_simple_task",
      "category": "ASSERTION_ERROR",
      "priority": 3,
      "status": "PENDING",
      "attempts": 0,
      "error_message": "AssertionError: expected IDLE, got BRAINSTORMING",
      "file_path": "tests/test_e2e_nexus.py",
      "line_number": 42,
      "fix_applied": null
    }
  ],
  "fixes_applied": [
    {
      "failure_id": "F002",
      "fix_type": "BUG",
      "file_modified": "core/orchestration_v7.py",
      "description": "Fixed state transition logic",
      "timestamp": "2025-11-27T10:15:00Z"
    }
  ],
  "next_action": {
    "action": "FIX_FAILURE",
    "target": "F001",
    "details": "Investigate assertion failure in test_simple_task"
  },
  "metrics": {
    "total_fixes_attempted": 5,
    "successful_fixes": 3,
    "tests_now_passing": 103
  }
}
```

### 6.3 Session Handoff Document

When approaching context limit, create:

```
workspace/logs/debug_handoff_YYYY-MM-DD_HH-MM.md
```

Contents:
- Current progress summary
- Remaining failures list
- Attempted fixes
- Recommended next steps
- Context for resumption

---

## 7. Pass/Fail Criteria

### 7.1 Release Criteria

| Metric | Required | Actual |
|--------|----------|--------|
| CRITICAL tests passing | 100% | PENDING |
| HIGH tests passing | >=90% | PENDING |
| MEDIUM tests passing | >=85% | PENDING |
| No security regressions | YES | PENDING |
| No FSM regressions | YES | PENDING |

### 7.2 Test Run Summary Template

```text
===========================================
NEXUS V7 TEST SUMMARY
===========================================
Date: YYYY-MM-DD HH:MM
Branch: N7C
Commit: xxxxxxx

RESULTS:
  Total:    XXX tests
  Passed:   XXX (XX%)
  Failed:   XXX (XX%)
  Errors:   XXX
  Skipped:  XXX

BY CATEGORY:
  CRITICAL: XX/XX (XX%) PASS/FAIL
  HIGH:     XX/XX (XX%) PASS/FAIL
  MEDIUM:   XX/XX (XX%) PASS/FAIL

BLOCKING ISSUES:
  - [if any]

RELEASE STATUS: READY / BLOCKED
===========================================
```

---

## 8. Pytest Markers

### 8.1 Available Markers

```python
@pytest.mark.e2e        # End-to-end tests
@pytest.mark.slow       # Slow running tests
@pytest.mark.security   # Security-related tests
@pytest.mark.swarm      # Swarm engine tests
@pytest.mark.evolution  # Evolution system tests
@pytest.mark.fsm        # FSM state machine tests
@pytest.mark.repl       # REPL command tests
```

### 8.2 Running with Markers

```bash
# Run only e2e tests
pytest -m e2e

# Run all except slow
pytest -m "not slow"

# Run security AND e2e
pytest -m "security and e2e"
```

---

## 9. Troubleshooting

### 9.1 Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| Import errors | Path not set | Check sys.path in conftest |
| Fixture not found | Missing conftest | Ensure conftest.py exists |
| Timeout | Slow mock | Increase timeout in config |
| State pollution | Shared state | Use fresh fixtures |

### 9.2 Debug Commands

```bash
# Verbose output with full traceback
pytest -v --tb=long

# Stop on first failure
pytest -x

# Show print statements
pytest -s

# Run last failed
pytest --lf
```

---

## 10. Maintenance

### 10.1 Adding New Tests

1. Choose appropriate test file
2. Add to correct test class
3. Use existing fixtures
4. Add appropriate markers
5. Update test matrix in this document

### 10.2 Updating Protocol

1. Update version number
2. Add change description
3. Update test counts
4. Update thresholds if needed

---

## Appendix A: Mock Response Patterns

### A.1 Simple Task Flow

```python
# Gemini delegates, Claude finishes
gemini_responses = [
    {"sender": "Gemini", "action_type": "DELEGATE", "content": "...", "next_agent": "Claude", "status": "CONTINUE"}
]
claude_responses = [
    {"sender": "Claude", "action_type": "TALK", "content": "Done", "status": "FINISHED"}
]
```

### A.2 Tool Execution Flow

```python
# Tool use -> validation -> finish
responses = [
    {"sender": "Claude", "action_type": "TOOL_USE", "tool_use": {...}, "status": "CONTINUE"},
    {"sender": "Claude", "action_type": "TALK", "content": "Done", "status": "FINISHED"}
]
```

### A.3 Swarm Negotiation Flow

```python
# Negotiate -> consensus
responses = [
    {"sender": "Gemini", "action_type": "TALK", "content": "<negotiate>{...}</negotiate>", "status": "CONTINUE"},
    {"sender": "Claude", "action_type": "TALK", "content": "<negotiate>{\"accept\": true}</negotiate>", "status": "CONTINUE"}
]
```

---

*Document generated for NEXUS V7 Chrysalis E2E Testing Protocol*
