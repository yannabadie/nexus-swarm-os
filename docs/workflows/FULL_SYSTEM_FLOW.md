# NEXUS Full System Flow

**Version**: 12.4 | **Last Updated**: 2025-12-16

End-to-end flow from user input to final result, showing how frontend and backend interact.

---

## Complete Request Lifecycle

```text
NEXUS FULL SYSTEM FLOW
======================

Frontend (CEREBRO)
  -> User enters a task in MissionControl
  -> User selects a mode such as LEAD_SUPPORT
  -> Frontend sends POST /api/workflow/start with JWT + task payload

Backend (CEREBRO API)
  -> JWT validation
  -> Rate limiting
  -> Orchestrator V7 process_turn(user_input)

Orchestrator path
  -> FSM transition: IDLE -> BRAINSTORMING
  -> Task analyzer scores complexity, domains, and provider fit
  -> Trivial task: direct execution
  -> Moderate+ task: route to Swarm or HiveMind

Lead/support execution example
  -> Hybrid Swarm Engine selects LEAD_SUPPORT
  -> Lead agent implements the task
  -> Tool execution runs through InputGuard, PathGuard, FileHandler, OutputGuard
  -> FSM transition: EXECUTING_TOOL -> VALIDATING_CFL
  -> Support agent reviews quality and security
  -> Consolidation merges outputs and records memory
  -> FSM transition: WAITING_USER

Realtime feedback
  -> Events stream over WebSocket during execution
  -> Frontend EventStream displays progress in real time
  -> Final result is rendered back to the user
```

---

## Event Timeline Example

```
T+0ms     | frontend  | POST /api/workflow/start
T+50ms    | backend   | JWT validated, rate check passed
T+100ms   | websocket | { type: "fsm.state_changed", payload: { from: "IDLE", to: "BRAINSTORMING" } }
T+150ms   | backend   | TaskAnalyzer: MODERATE complexity, CODING domain
T+200ms   | websocket | { type: "swarm.mode_selected", payload: { mode: "LEAD_SUPPORT", lead: "claude" } }
T+300ms   | backend   | Claude Opus analyzing requirements
T+1500ms  | websocket | { type: "tool.execution_started", payload: { tool: "write", path: "src/LoginForm.tsx" } }
T+2000ms  | websocket | { type: "tool.execution_completed", payload: { tool: "write", success: true } }
T+2100ms  | websocket | { type: "fsm.state_changed", payload: { from: "EXECUTING_TOOL", to: "VALIDATING_CFL" } }
T+3000ms  | backend   | Gemini 3 Pro reviewing code
T+3500ms  | websocket | { type: "swarm.review_complete", payload: { approved: true } }
T+4000ms  | websocket | { type: "workflow.completed", payload: { success: true, files_created: 1 } }
T+4050ms  | websocket | { type: "fsm.state_changed", payload: { from: "VALIDATING_CFL", to: "WAITING_USER" } }
```

---

## Error Handling Flow

```
Normal Flow                          Error Flow
    |                                    |
    v                                    v
Execution                          Execution fails
    |                                    |
    v                                    v
Success                            +-----------------+
    |                              | Phase 5:        |
    v                              | DIAGNOSIS       |
WAITING_USER                       | (error analysis)|
                                   +-----------------+
                                         |
                                         v
                                   +-----------------+
                                   | Phase 6:        |
                                   | RETRY           |
                                   | (max 3 attempts)|
                                   +-----------------+
                                         |
                                   +-----+-----+
                                   |           |
                              Retry OK    Retry failed
                                   |           |
                                   v           v
                              WAITING_USER   ERROR state
                                               |
                                               v
                                         User: /reset
                                               |
                                               v
                                             IDLE
```

---

## Fallback Chain Example

```
Selected mode: RED_BLUE (adversarial)
    |
    v
RED_BLUE execution fails (agents can't reach consensus)
    |
    v
Self-Healing: Try LEAD_SUPPORT
    |
    v
LEAD_SUPPORT execution fails (lead encounters error)
    |
    v
Self-Healing: Try SPECIALIST
    |
    v
SPECIALIST succeeds (single expert completes task)
    |
    v
Result returned to user
```

---

## Memory Integration

```
Task Completed
    |
    v
+-----------------------------------+
| SuccessMemory.record()            |
|                                   |
| Stored:                           |
| - Task description                |
| - Selected mode                   |
| - Agent performance               |
| - Tool sequence                   |
| - Success/failure                 |
+-----------------------------------+
    |
    v
Next similar task
    |
    v
+-----------------------------------+
| ModeSelector uses SuccessMemory   |
|                                   |
| - Check past success patterns     |
| - Adjust DyLAN scores             |
| - Select optimal mode             |
+-----------------------------------+
```

---

*Full System Flow V12.4 - NEXUS Documentation*
