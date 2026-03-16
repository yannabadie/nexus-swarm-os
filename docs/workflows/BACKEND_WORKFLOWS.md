
# NEXUS Backend Workflows

**Version**: 12.4 | **Last Updated**: 2025-12-16

This document maps all backend workflow paths from user input to result delivery.

---

## 1. FSM State Machine (Core Orchestrator)

The Finite State Machine controls all task execution with 11 possible states.

### State Diagram

```
                          +-----------------------------------------+
                          |              PANIC                      |
                          |         (Fatal error)                   |
                          +-----------------------------------------+
                                          ^
                                      timeout
                                          |
+---------+  user_input   +-----------------+  tool_use   +------------------+
|  IDLE   |-------------->|  BRAINSTORMING  |------------>|  EXECUTING_TOOL  |
+---------+               +-----------------+             +------------------+
     ^                           |    |                          |
     |                   finished|    |stagnation          tool_completed
     |                           v    v                          v
     |                   +----------+ +---------+         +------------------+
     |                   | WAITING  | |  ERROR  |         |  VALIDATING_CFL  |
     |<------------------|  _USER   | +---------+         +------------------+
     |       success     +----------+      |                     |
     |                         |           |reset           success/failure
     |                  user_input         v                     |
     +-------------------------+-----------+---------------------+
```

### FSM States

| State | Description | Exit Conditions |
|-------|-------------|-----------------|
| `IDLE` | Awaiting user input | user_input -> BRAINSTORMING |
| `BRAINSTORMING` | Agents exchange TALK messages | tool_use -> EXECUTING_TOOL |
| `EXECUTING_TOOL` | Tool execution (synchronous) | completed -> VALIDATING_CFL |
| `VALIDATING_CFL` | Cognitive Feedback Loop validation | success -> IDLE |
| `WAITING_USER` | Task finished, await next input | user_input -> BRAINSTORMING |
| `ERROR` | Recoverable error | reset -> IDLE |
| `PANIC` | Fatal error | Requires restart |
| `HIBERNATE` | V12.2 dormant state | ws_reconnect -> previous_state |
| `SWARM_ANALYZING` | Task analysis | -> SWARM_NEGOTIATING |
| `SWARM_NEGOTIATING` | Mode negotiation | -> SWARM_EXECUTING |
| `SWARM_EXECUTING` | Swarm execution | -> VALIDATING_CFL |
| `EVOLUTION_BRAINSTORM` | Special mutation design mode | JSON output |

---

## 2. HiveMind Pipeline (MODERATE+ Tasks)

For tasks with complexity >= MODERATE, the HiveMind 7-phase pipeline activates.

### Phase Flow

```
+-----------------------------------------------------------------------------+
|                        HIVEMIND PIPELINE                                    |
+-----------------------------------------------------------------------------+
|                                                                             |
|  +----------+   +----------+   +--------------+   +-----------+            |
|  | Phase 1  |-->| Phase 2  |-->|   Phase 3    |-->|  Phase 4  |            |
|  | ANALYSIS |   |  DEBATE  |   | ARCHITECTURE |   | EXECUTION |            |
|  |          |   |(if needed)|   |              |   |           |            |
|  +----------+   +----------+   +--------------+   +-----------+            |
|       |                                                |                    |
|       |                         +----------------------+                    |
|       |                         |                                           |
|       |                         v                                           |
|       |              +-------------------+                                  |
|       |              |     Phase 5       |                                  |
|       |              |    DIAGNOSIS      |<-------- On failure              |
|       |              |  (error analysis) |                                  |
|       |              +-------------------+                                  |
|       |                         |                                           |
|       |                         v                                           |
|       |              +-------------------+                                  |
|       |              |     Phase 6       |                                  |
|       |              |      RETRY        |                                  |
|       |              |  (max 3 attempts) |                                  |
|       |              +-------------------+                                  |
|       |                         |                                           |
|       v                         v                                           |
|  +------------------------------------------+                              |
|  |              Phase 7                      |                              |
|  |           CONSOLIDATION                   |                              |
|  |      (merge results, final output)        |                              |
|  +------------------------------------------+                              |
|                         |                                                   |
|                         v                                                   |
|               HIVE_SUCCESS / HIVE_FAILED                                   |
|                                                                             |
+-----------------------------------------------------------------------------+
```

### Phase Details

| Phase | Purpose | Agents | Output |
|-------|---------|--------|--------|
| **1. ANALYSIS** | Independent task analysis | Gemini + Claude | AnalysisPhaseResult |
| **2. DEBATE** | Resolve disagreements | Both | Consensus or Lead decision |
| **3. ARCHITECTURE** | Design execution plan | Both | ExecutionPlan (steps) |
| **4. EXECUTION** | Execute steps (can delegate to Swarm) | Assigned agent | StepResults |
| **5. DIAGNOSIS** | Error analysis on failure | Both | DiagnosisResult |
| **6. RETRY** | Re-execute failed steps | Assigned | RetryResult |
| **7. CONSOLIDATION** | Merge and summarize | Lead | FinalOutput |

---

## 3. Hybrid Swarm Engine (6 Collaboration Modes)

Agents negotiate the optimal collaboration mode for each task.

### Mode Selection Flow

```
TaskAnalyzer
     |
     v
+----------------+
| Complexity     |--> TRIVIAL -> Skip Swarm
| Domains        |
| Agent Scores   |
+----------------+
     |
     v (MODERATE+)
ModeSelector (DyLAN metrics)
     |
     v
+--------------------+
| Initial Proposal   |
| + Reasoning        |
+--------------------+
     |
     v
+----------------------------------------+
|           NEGOTIATION                   |
|  <negotiate>{"mode": "...", ...}        |
|  Max 4 turns, then consensus/fallback   |
+----------------------------------------+
     |
     v
+--------------------+
| Mode Executor      |
| (6 implementations)|
+--------------------+
```

### Collaboration Modes

| Mode | Description | Pattern |
|------|-------------|---------|
| **PARALLEL** | Simultaneous work | Both agents work independently, results merged |
| **SEQUENTIAL** | Ordered execution | Agent A -> Agent B (dependent steps) |
| **LEAD_SUPPORT** | Expert leads | Lead drives, Support reviews/assists |
| **PING_PONG** | Rapid iteration | Alternating until convergence |
| **SPECIALIST** | Single expert | One agent handles all (clear domain) |
| **RED_BLUE** | Adversarial | Red proposes, Blue attacks, iterate |

### Fallback Chains (Self-Healing V8)

```
PARALLEL    -> SEQUENTIAL -> SPECIALIST
RED_BLUE    -> LEAD_SUPPORT -> SPECIALIST
PING_PONG   -> SEQUENTIAL -> SPECIALIST
LEAD_SUPPORT -> SPECIALIST
```

---

## 4. Tool Execution Pipeline

All 11 tools go through a unified execution pipeline.

```
Tool Request (from Agent)
          |
          v
+---------------------+
|   Request Parser    |--> Extract tool_name, arguments
+---------------------+
          |
          v
+---------------------+
|   Security Guards   |
|   - InputGuard      |--> Sanitize inputs
|   - OutputGuard     |    Detect prompt injection
|   - PathGuard       |    Validate file paths
+---------------------+
          |
          v
+---------------------+
|   Handler Dispatch  |--> Route to specific handler
|   (Modular V9.6)    |    /core/execution/handlers/
+---------------------+
          |
          v
+---------------------+
|   Tool Execution    |--> bash_handler, file_handler, etc.
+---------------------+
          |
          v
+---------------------+
|   Result Validator  |--> Check success/failure
+---------------------+
          |
          v
+---------------------+
|   Memory Update     |--> SuccessMemory records patterns
+---------------------+
          |
          v
Return Result to Agent
```

### Available Tools

| Tool | Handler | Description |
|------|---------|-------------|
| `bash` | bash_handler.py | Execute shell commands |
| `read` | file_handler.py | Read file contents |
| `write` | file_handler.py | Write file contents |
| `edit` | file_handler.py | Edit file (search/replace) |
| `list_dir` | file_handler.py | List directory contents |
| `glob` | search_handler.py | Pattern-based file search |
| `grep` | search_handler.py | Content search |
| `git` | git_handler.py | Git operations |
| `web_search` | web_handler.py | Web search |
| `web_fetch` | web_handler.py | Fetch URL content |
| `todo_write` | todo_handler.py | Manage shared plan |

---

## 5. Memory System

### Memory Types

```
+-----------------------------------------------------------------+
|                      MEMORY SYSTEM                               |
+-----------------------------------------------------------------+
|                                                                  |
|  +-----------------+                                            |
|  |   AutoMemory    |  Session-level learning                    |
|  |  (Blackboard)   |  Stored: workspace/.nexus/blackboard.json  |
|  +-----------------+                                            |
|                                                                  |
|  +-----------------+                                            |
|  |  ProjectMemory  |  RAG retrieval for codebase context        |
|  |   (RAG + BM25)  |  Backends: TF-IDF, BM25, Dense, Hybrid     |
|  +-----------------+                                            |
|                                                                  |
|  +-----------------+                                            |
|  |  SuccessMemory  |  Pattern storage for successful solutions  |
|  |   (Phase 10)    |  Used for Session-Aware Agent Selection    |
|  +-----------------+                                            |
|                                                                  |
+-----------------------------------------------------------------+
```

### V12.4 HybridBackend (RRF Fusion)

```
Query
  |
  +--------------------------+-----------------------+
  |                          |                       |
  v                          v                       v
Dense                      BM25S                  TF-IDF
(Embeddings)              (Sparse)               (Fallback)
  |                          |                       |
  +--------------------------+-----------------------+
                             |
                             v
                    RRF Fusion (k=60)
                             |
                             v
                      Merged Results
                      (+15% recall)
```

---

## 6. WebSocket Event System

### Event Categories

| Category | Events | Description |
|----------|--------|-------------|
| **FSM** | fsm.state_changed, fsm.transition | State machine updates |
| **Swarm** | swarm.negotiation, swarm.mode_selected | Collaboration events |
| **HiveMind** | hivemind.phase_* | Pipeline phase events |
| **Tool** | tool.execution_* | Tool lifecycle events |
| **Interaction** | interaction.required | HITL requests |
| **Memory** | memory.retrieved, memory.stored | Memory operations |
| **Agent** | agent.spawned, agent.selected | Agent lifecycle |

### Event Flow

```
Backend Action
      |
      v
EventBus.emit(event)
      |
      v
WebSocket Broadcast
      |
      v
CEREBRO Frontend
      |
      v
Zustand Store Update
      |
      v
React Component Re-render
```

---

*Backend Workflows V12.4 - NEXUS Documentation*
