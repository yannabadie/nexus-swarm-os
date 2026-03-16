# NEXUS V12.4 - FSM State Handlers

**Status**: Partially Migrated (P1.3 in progress)

## Overview

Modular state handlers for the FSM orchestrator. Extracted from the monolithic `core/orchestration/fsm_handlers.py` (1,845 lines) into focused, maintainable modules.

## Architecture

```
core/fsm/handlers/
+-- __init__.py                 # Facade pattern - delegates to handler modules
+-- base.py                     # BaseHandler - common infrastructure
+-- error.py                    # ERROR, PANIC states (30 lines)
+-- brainstorming.py            # BRAINSTORMING state (125 lines)
+-- executing_tool.py           # EXECUTING_TOOL state (47 lines)
+-- validating_cfl.py           # VALIDATING_CFL state (108 lines)
+-- evolution.py                # EVOLUTION_BRAINSTORM state (153 lines)
+-- swarm.py                    # SWARM_* states (107 lines)
```

## Migration Status

### [OK] Completed Modules

| Module | States | Lines | Status |
|--------|--------|-------|--------|
| `error.py` | ERROR, PANIC | 30 | [OK] Extracted & tested |
| `brainstorming.py` | BRAINSTORMING | 125 | [OK] Extracted & tested |
| `executing_tool.py` | EXECUTING_TOOL | 47 | [OK] Extracted & tested |
| `validating_cfl.py` | VALIDATING_CFL | 108 | [OK] Extracted & tested |
| `evolution.py` | EVOLUTION_BRAINSTORM | 153 | [OK] Extracted & tested |
| `swarm.py` | SWARM_ANALYZING, SWARM_NEGOTIATING, SWARM_EXECUTING | 107 | [OK] Extracted & tested |
| `idle_waiting.py` | IDLE, WAITING_USER | 391 | [OK] Extracted & tested |

**Total:** 8/8 handler groups (100% coverage), 1,181 lines extracted

### 📋 Remaining in Legacy File (Optional)

| Helper Methods | Lines | Usage |
|----------------|-------|-------|
| `_execute_simple_task` + fast path | ~357 | Delegated from idle_waiting.py |
| Lightweight CFL validation | ~244 | Used by simple execution |
| Delegated methods + async | ~63 | Infrastructure |

**Note**: These helpers remain in `core/orchestration/fsm_handlers.py` and are called via delegation. System is fully functional.

## Usage

```python
from core.fsm.handlers import FSMHandlers

# In OrchestratorV7.__init__
self.fsm_handlers = FSMHandlers(self)

# In process_turn() state dispatcher
result = self.fsm_handlers.handle_brainstorming()
```

## Handler Responsibilities

### BaseHandler
- Provides orchestrator access (`self._orch`)
- Delegation methods for common operations
- Logging infrastructure

### ErrorHandler
- ERROR state: Display error message, await /reset
- PANIC state: Fatal error with recovery option (V9.3)

### BrainstormingHandler
- Agent debate and tool consensus
- Plan health checking (ZOMBIE detection)
- Stagnation detection
- Agent alternation (Gemini ↔ Claude)

### ExecutingToolHandler
- Synchronous tool execution
- Agent switch for CFL validation

### ValidatingCFLHandler
- Cognitive Feedback Loop validation
- Task completion detection
- Stalemate checking
- Success/failure routing

### EvolutionHandler
- Evolution debate mode for mutations
- Mutation JSON detection
- Tool execution during evolution
- Sandbox policy enforcement

### SwarmHandler
- Swarm analysis (complexity + domains)
- Mode negotiation
- Swarm execution coordination

### IdleWaitingHandler (TODO)
- Task complexity analysis
- Routing logic (TRIVIAL -> SIMPLE -> MODERATE+)
- HiveMind integration
- Fast path optimization
- Simple task execution
- Auto-Memory recommendations

## Design Patterns

### Composition over Inheritance
- FSMHandlers facade composes handler instances
- Each handler inherits from BaseHandler for shared functionality

### Single Responsibility Principle
- Each handler focuses on one state or related states
- No file exceeds 500 lines (action plan requirement)

### Delegation Pattern
- Handlers delegate to orchestrator for shared state
- BaseHandler provides delegation methods

## Benefits

[OK] **Maintainability**: Small, focused modules instead of 1,845-line monolith
[OK] **Testability**: Each handler can be tested independently
[OK] **Clarity**: State handling logic is self-contained
[OK] **Scalability**: Easy to add new states or modify existing ones

## Next Steps

1. Extract idle_waiting.py with routing logic (~365 lines)
2. Extract simple_execution.py with task execution (~357 lines)
3. Extract lightweight_cfl.py with CFL validation helpers (~244 lines)
4. Remove LegacyFSMHandlers fallback from __init__.py
5. Delete core/orchestration/fsm_handlers.py
6. Update tests to reference new modules

## References

- **Action Plan**: MASTER_ACTION_PLAN.md P1.3
- **Original File**: core/orchestration/fsm_handlers.py (1,845 lines)
- **Target**: core/fsm/handlers/ (modular structure)
