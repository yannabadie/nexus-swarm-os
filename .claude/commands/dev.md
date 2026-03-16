---
description: "Development automation - implement features, refactor code with test validation"
allowed-tools: "Bash,Glob,Read,Grep,Write,Edit,TodoWrite"
---

# /dev Command - Development Automation

Invoke the development automation agent for iterative feature implementation.

## Usage
- `/dev "Add caching to MemoryService"` - Implement a new feature
- `/dev refactor core/orchestration_v7.py` - Refactor specific file
- `/dev fix "Thread safety in PARALLEL mode"` - Fix known issue

## Arguments
`$ARGUMENTS` - The development task description

## Workflow

Based on the dev-automator agent, this command:

1. **Analyzes the request** to understand scope
2. **Searches codebase** for relevant patterns and existing implementations
3. **Plans implementation** using TodoWrite for tracking
4. **Implements incrementally** with tests after each change
5. **Validates** with full test suite
6. **Reports** progress and results

## NEXUS-Specific Context

Key files for reference:
- FSM: `core/fsm/states.py` (15 states)
- HiveMind: `core/hive_mind/` (7 phases)
- Swarm: `core/swarm/` (6 modes)
- Memory: `core/memory/service.py`
- Drivers: `core/drivers/`

## Task: $ARGUMENTS

Begin by analyzing the request and creating a development plan. Use TodoWrite to track progress.
Run tests after each significant change: `python -m pytest tests/ -q`

If the task involves:
- **New feature**: Write tests first, then implementation
- **Refactoring**: Ensure existing tests pass before/after
- **Bug fix**: Add regression test, then fix

Report progress incrementally with:
- Files changed
- Test status (pass/fail count)
- Any blockers encountered
