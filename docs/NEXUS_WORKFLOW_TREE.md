# NEXUS V13.0 - Workflow Tree

**Version**: V13.0 MEMORIA UNIVERSALIS
**Generated**: 2025-12-16
**Purpose**: Complete map of all possible NEXUS workflows

---

## Overview

```
+-----------------------------------------------------------------------------+
|                        NEXUS WORKFLOW ARCHITECTURE                          |
|                                                                             |
|   USER INPUT --► TASK ANALYSIS --► ROUTING --► EXECUTION --► OUTPUT        |
|                       |              |            |                         |
|                       v              v            v                         |
|                  Complexity     FSM/HiveMind   Tools/Swarm                  |
|                  Detection      Selection      Orchestration                |
+-----------------------------------------------------------------------------+
```

---

## 1. Entry Points

### 1.1 REPL Commands (Interactive)

```
nexus7.py
    |
    +-- /help ----------------► Display commands
    +-- /status --------------► System status
    +-- /clear ---------------► Clear conversation
    |
    +-- /swarm <task> --------► Force swarm execution
    |       |
    |       +--► Mode Selection --► 6 Modes (see §4)
    |
    +-- /hive <task> ---------► Force HiveMind pipeline
    |       |
    |       +--► 7 Phases (see §3)
    |
    +-- /spawn <spec> --------► Agent creation
    |       |
    |       +--► Evolution Engine --► workspace/agents/
    |
    +-- /specialize <domain> -► Project specialization
    |       |
    |       +--► Mutation + New agent config
    |
    +-- /evolve --------------► Improve existing agent
    |       |
    |       +--► Performance metrics --► Optimized clone
    |
    +-- /memory --------------► RAG commands
    |       +-- /memory index <path>
    |       +-- /memory query <query>
    |       +-- /memory stats
    |
    +-- Natural language -----► TaskAnalyzer --► Auto-routing
```

### 1.2 CEREBRO API (Remote)

```
HTTP/WebSocket
    |
    +-- /api/auth/* ----------► JWT Authentication
    |       +-- POST /login
    |       +-- POST /refresh
    |       +-- GET /me
    |
    +-- /api/workflow/* ------► Workflow Control
    |       +-- POST /start ---► Start task
    |       +-- POST /abort ---► Abort current
    |       +-- GET /status ---► Current state
    |
    +-- /api/interactions/* --► Human-in-the-Loop
    |       +-- GET /pending
    |       +-- POST /:id/reply
    |
    +-- /api/memory/* --------► RAG Management
    |       +-- GET /stats
    |       +-- GET/POST/DELETE /namespaces
    |       +-- POST /ingest
    |       +-- POST /query
    |
    +-- /api/files/* ---------► Secure File Access
    |       +-- GET /content
    |       +-- GET /tree
    |
    +-- /ws/stream -----------► Real-time Events
            |
            +--► EventStream (WebSocket)
```

---

## 2. FSM (Finite State Machine) - Core Orchestration

### 2.1 State Diagram

```
                              +---------------+
                              |     IDLE      |◄------------------+
                              +-------+-------+                   |
                                      | User Input                |
                                      v                           |
                    +-------------------------------------+       |
                    |          TASK_ANALYSIS              |       |
                    |  (Complexity + Domain Detection)    |       |
                    +-----------------+-------------------+       |
                                      |                           |
              +-----------------------+-----------------------+   |
              v                       v                       v   |
    +-----------------+     +-----------------+     +-----------------+
    |   BRAINSTORMING |     |  HIVE_DELEGATE  |     | SWARM_DELEGATE  |
    |   (Simple/Mod)  |     |   (Complex+)    |     |  (Multi-agent)  |
    +--------+--------+     +--------+--------+     +--------+--------+
             |                       |                       |
             v                       v                       v
    +-----------------+     +-----------------+     +-----------------+
    | EXECUTING_TOOL  |     |  HiveMind 7φ    |     |  Swarm 6 modes  |
    +--------+--------+     +--------+--------+     +--------+--------+
             |                       |                       |
             +-----------------------+-----------------------+
                                     v
                           +-----------------+
                           | VALIDATING_CFL  |
                           | (Quality Check) |
                           +--------+--------+
                                    |
                    +---------------+---------------+
                    v               v               v
          +--------------+  +--------------+  +--------------+
          |   SUCCESS    |  |WAITING_USER  |  |    ERROR     |
          |  (Complete)  |  |  (HITL)      |  | (Recoverable)|
          +------+-------+  +------+-------+  +------+-------+
                 |                 |                  |
                 +-----------------+------------------+
                                   v
                              Back to IDLE
                                   |
                         (or PANIC if fatal)
```

### 2.2 Complete State List (15 States)

| State | Description | Transitions To |
|-------|-------------|----------------|
| `IDLE` | Awaiting input | TASK_ANALYSIS |
| `TASK_ANALYSIS` | Routing decision | BRAINSTORMING, HIVE_DELEGATE, SWARM_DELEGATE |
| `BRAINSTORMING` | Agent exchange | EXECUTING_TOOL, WAITING_USER |
| `EXECUTING_TOOL` | Tool execution | VALIDATING_CFL, ERROR |
| `VALIDATING_CFL` | Quality check | IDLE, BRAINSTORMING, ERROR |
| `WAITING_USER` | Human input needed | BRAINSTORMING |
| `ERROR` | Recoverable error | IDLE (via /reset) |
| `PANIC` | Fatal error | (restart required) |
| `HIVE_DELEGATE` | HiveMind handoff | HiveMind pipeline |
| `SWARM_DELEGATE` | Swarm handoff | Swarm modes |
| `SWARM_NEGOTIATING` | Mode selection | SWARM_EXECUTING |
| `SWARM_EXECUTING` | Multi-agent work | SWARM_MERGING |
| `SWARM_MERGING` | Result merge | VALIDATING_CFL |
| `HIBERNATING` | Low-power wait | IDLE |
| `FINALIZING` | Output prep | IDLE |

---

## 3. HiveMind Pipeline - Complex Tasks

### 3.1 Phase Flow

```
+-------------------------------------------------------------------------+
|                         HIVEMIND 7-PHASE PIPELINE                       |
+-------------------------------------------------------------------------+

Phase 1: ANALYSIS
    |
    +-- Claude Analysis ------► Independent reasoning
    +-- Gemini Analysis ------► Independent reasoning
    +-- Merge ----------------► Combined understanding
                |
                v
Phase 2: DEBATE (if disagreement)
    |
    +-- Point identification -► Areas of conflict
    +-- Exchange arguments ---► Max 4 rounds
    +-- Resolution -----------► Consensus or escalate
                |
                v
Phase 3: ARCHITECTURE
    |
    +-- Plan design ----------► Execution steps
    +-- Tool selection -------► Required tools
    +-- Dependency graph -----► Step ordering
                |
                v
Phase 4: EXECUTION
    |
    +-- Step execution -------► Sequential/Parallel
    +-- SwarmBridge ----------► Delegate to Swarm if needed
    +-- Progress tracking ----► Real-time events
                |
                v
Phase 5: DIAGNOSIS (on error)
    |
    +-- Error analysis -------► Root cause
    +-- Recovery plan --------► Fix strategy
    +-- Retry logic ----------► Up to 3 attempts
                |
                v
Phase 6: CONSOLIDATION
    |
    +-- Result merge ---------► Combine outputs
    +-- Quality check --------► Validation
    +-- Summary --------------► Human-readable
                |
                v
Phase 7: COMPLETION
    |
    +-- HIVE_SUCCESS ---------► Task complete
    +-- HIVE_FAILED ----------► Task failed (with report)
```

### 3.2 HiveMind State Machine (24 States)

| Phase | States |
|-------|--------|
| **Idle** | `HIVE_IDLE` |
| **Analysis** | `ANALYSIS_PENDING`, `ANALYSIS_CLAUDE`, `ANALYSIS_GEMINI`, `ANALYSIS_COMPLETE` |
| **Debate** | `DEBATE_PENDING`, `DEBATE_ROUND`, `DEBATE_COMPLETE`, `DEBATE_ESCALATED` |
| **Architecture** | `ARCH_PENDING`, `ARCH_DESIGNING`, `ARCH_COMPLETE` |
| **Execution** | `EXEC_PENDING`, `EXEC_STEP`, `EXEC_SWARM_DELEGATE`, `EXEC_COMPLETE` |
| **Diagnosis** | `DIAG_PENDING`, `DIAG_ANALYZING`, `DIAG_COMPLETE` |
| **Consolidation** | `CONSOL_PENDING`, `CONSOL_MERGING`, `CONSOL_COMPLETE` |
| **Terminal** | `HIVE_SUCCESS`, `HIVE_FAILED` |

---

## 4. Swarm Engine - Multi-Agent Collaboration

### 4.1 Mode Selection Flow

```
Task Input
    |
    v
+-------------------------------------------------------------+
|                    MODE SELECTOR (DyLAN)                     |
|                                                              |
|  Factors:                                                    |
|  - Task complexity (TRIVIAL -> EXPERT)                        |
|  - Domain (CODING, RESEARCH, ANALYSIS, CREATIVE)             |
|  - Agent metrics (success rate, response time)               |
|  - Historical patterns (SuccessMemory)                       |
+-------------------------------------------------------------+
    |
    +-- Independent subtasks ---------► PARALLEL
    +-- Dependent steps --------------► SEQUENTIAL
    +-- Complex + guidance -----------► LEAD_SUPPORT
    +-- Iterative refinement ---------► PING_PONG
    +-- Single expert domain ---------► SPECIALIST
    +-- Security/Adversarial ---------► RED_BLUE
```

### 4.2 Mode Details

#### PARALLEL Mode
```
+-------------+     +-------------+
|   Claude    |     |   Gemini    |
|  Subtask A  |     |  Subtask B  |
+------+------+     +------+------+
       |                   |
       +-------+-----------+
               v
        +-------------+
        |   Merger    |
        |  (Results)  |
        +-------------+
```

#### SEQUENTIAL Mode
```
+-------------+     +-------------+     +-------------+
|   Agent 1   |----►|   Agent 2   |----►|   Agent 3   |
|   Step 1    |     |   Step 2    |     |   Step 3    |
+-------------+     +-------------+     +-------------+
```

#### LEAD_SUPPORT Mode
```
+-----------------------------------------+
|              LEAD (Claude)              |
|  - Drives implementation                |
|  - Makes decisions                      |
+--------------------+--------------------+
                     | Review/Assist
                     v
+-----------------------------------------+
|            SUPPORT (Gemini)             |
|  - Reviews work                         |
|  - Provides suggestions                 |
+-----------------------------------------+
```

#### PING_PONG Mode
```
    Claude                  Gemini
       |                       |
       |---- Proposal --------►|
       |                       |
       |◄--- Refinement -------|
       |                       |
       |---- Counter ---------►|
       |                       |
       |◄--- Agreement --------|
       |                       |
    (Converges after N rounds)
```

#### SPECIALIST Mode
```
+-----------------------------------------+
|            SPECIALIST                   |
|  (Single agent handles entire task)     |
|                                         |
|  Selected based on:                     |
|  - Domain expertise                     |
|  - Historical success rate              |
+-----------------------------------------+
```

#### RED_BLUE Mode
```
+-----------------+         +-----------------+
|    RED TEAM     |◄-------►|   BLUE TEAM     |
|   (Attacker)    |         |   (Defender)    |
|                 |         |                 |
| - Find flaws    |         | - Fix issues    |
| - Attack plan   |         | - Harden code   |
| - Edge cases    |         | - Validate      |
+-----------------+         +-----------------+
            |                       |
            +-----------+-----------+
                        v
              +-----------------+
              |  FINAL REVIEW   |
              |  (Hardened)     |
              +-----------------+
```

---

## 5. Tool Execution Workflows

### 5.1 Tool Categories

```
NEXUS TOOLS (16+)
    |
    +-- File Operations
    |       +-- read ------► Read file content
    |       +-- write -----► Create/overwrite file
    |       +-- edit ------► Modify existing file
    |       +-- list_dir --► Directory listing
    |       +-- glob ------► Pattern matching
    |       +-- grep ------► Content search
    |
    +-- Execution
    |       +-- bash ------► Shell commands
    |       +-- git -------► Version control
    |
    +-- Research
    |       +-- web_search ► Internet search
    |       +-- web_fetch -► URL content
    |
    +-- Memory
    |       +-- rag_query -► Semantic search
    |       +-- rag_index -► Index files
    |       +-- rag_forget ► Remove from index
    |
    +-- Coordination
            +-- todo_write ► Task management
            +-- interaction ► Human-in-the-loop
```

### 5.2 Tool Execution Flow

```
Tool Request
    |
    v
+-----------------------------------------+
|           EXECUTION POLICY              |
|  - Check KERNEL.py alignment            |
|  - Validate permissions                 |
|  - Apply sandboxing                     |
+--------------------+--------------------+
    |
    +-- ALLOWED ------► Execute tool
    |                       |
    |                       v
    |               +-----------------+
    |               |  Tool Handler   |
    |               +--------+--------+
    |                        |
    |                        v
    |               +-----------------+
    |               |  Result/Error   |
    |               +-----------------+
    |
    +-- DENIED -------► Return error + reason
```

---

## 6. Memory System Workflows

### 6.1 RAG Pipeline

```
Document Input
    |
    +-- Code files --------► AST parsing
    +-- PDF/DOCX ----------► Docling extraction
    +-- Images ------------► OCR/Vision
    +-- Other -------------► Text extraction
            |
            v
+-----------------------------------------+
|            CHUNKING                      |
|  - 512 tokens per chunk                 |
|  - 50 token overlap                     |
|  - Context preservation                 |
+--------------------+--------------------+
            |
            v
+-----------------------------------------+
|           EMBEDDING                      |
|  - MiniLM-L6-v2 (384 dims)              |
|  - Batch processing                     |
+--------------------+--------------------+
            |
            v
+-----------------------------------------+
|           STORAGE                        |
|  - LanceDB (vector store)               |
|  - Namespace isolation                  |
|  - Metadata indexing                    |
+-----------------------------------------+
```

### 6.2 Namespace Architecture

```
.nexus/
    |
    +-- project_knowledge.json -----► Project RAG metadata
    |
    +-- lancedb/
    |       +-- project/ -----------► Project vectors
    |
    +-- agent_rags/
            +-- security_expert/
            |       +-- knowledge.json
            |       +-- lancedb/
            |
            +-- code_reviewer/
            |       +-- knowledge.json
            |       +-- lancedb/
            |
            +-- {agent_name}/
                    +-- knowledge.json
                    +-- lancedb/
```

### 6.3 Query Flow

```
User Query
    |
    v
+-----------------------------------------+
|           EMBEDDING                      |
|  Query -> 384-dim vector                 |
+--------------------+--------------------+
    |
    v
+-----------------------------------------+
|         HYBRID SEARCH                    |
|  - Dense: Cosine similarity             |
|  - Sparse: BM25 (optional)              |
|  - RRF fusion                           |
+--------------------+--------------------+
    |
    v
+-----------------------------------------+
|           RERANKING                      |
|  - Top-K selection                      |
|  - Metadata filtering                   |
|  - Deduplication                        |
+--------------------+--------------------+
    |
    v
Relevant Chunks -> Agent Context
```

---

## 7. Evolution & Spawn Workflows

### 7.1 Agent Spawn

```
/spawn "Security Expert for Python auditing"
    |
    v
+-----------------------------------------+
|         SPECIFICATION ANALYSIS           |
|  - Domain extraction                    |
|  - Capability mapping                   |
|  - Parent selection                     |
+--------------------+--------------------+
    |
    v
+-----------------------------------------+
|         BRAINSTORM (Gemini+Claude)       |
|  - Capability discussion                |
|  - Prompt engineering                   |
|  - Configuration design                 |
+--------------------+--------------------+
    |
    v
+-----------------------------------------+
|         AGENT CREATION                   |
|  workspace/agents/{agent_name}/         |
|  +-- config.yaml                        |
|  +-- system_prompt.md                   |
|  +-- capabilities.json                  |
|  +-- rag/                               |
+-----------------------------------------+
```

### 7.2 Evolution Cycle

```
/evolve
    |
    v
+-----------------------------------------+
|         METRICS ANALYSIS                 |
|  - Success rate                         |
|  - Task completion time                 |
|  - Error patterns                       |
+--------------------+--------------------+
    |
    v
+-----------------------------------------+
|         MUTATION PROPOSAL                |
|  - Capability adjustments               |
|  - Prompt refinements                   |
|  - Tool preferences                     |
+--------------------+--------------------+
    |
    v
+-----------------------------------------+
|         OFFSPRING CREATION               |
|  - Clone parent                         |
|  - Apply mutations                      |
|  - Validate                             |
+--------------------+--------------------+
    |
    v
New Agent (Improved Version)
```

---

## 8. CEREBRO UI Workflows

### 8.1 Dashboard Layout

```
+-------------------------------------------------------------+
|                        HEADER                               |
|  [Logo] NEXUS CEREBRO    [User] [WS: Connected] [Logout]    |
+-----------------------------------+-------------------------+
|                                   |                         |
|  [Hive Map] [Files] [Memory]      |    MISSION CONTROL      |
|  ----------------------------     |    ---------------      |
|                                   |    Mode: [Dropdown]     |
|     TAB CONTENT                   |    [Start Task]         |
|                                   |    [Abort]              |
|     - HiveMap: Agent graph        |                         |
|     - Files: Tree + Editor        +-------------------------+
|     - Memory: RAG panel           |                         |
|                                   |    EVENT STREAM         |
|                                   |    ---------------      |
|                                   |    [Live events]        |
|                                   |    [Auto-scroll]        |
|                                   |                         |
+-----------------------------------+-------------------------+
```

### 8.2 Event Flow (WebSocket)

```
Backend (FastAPI)
    |
    +-- State changes ------------+
    +-- Tool executions ----------+
    +-- Agent messages -----------+---► WebSocket
    +-- Errors -------------------+      |
    +-- Progress updates ---------+      |
                                         v
                               +-----------------+
                               |  Event Store    |
                               |  (Zustand)      |
                               +--------+--------+
                                        |
                    +-------------------+-------------------+
                    v                   v                   v
            +-------------+     +-------------+     +-------------+
            | EventStream |     |  HiveMap    |     |   Toasts    |
            |  (Live log) |     |  (Update)   |     |  (Alerts)   |
            +-------------+     +-------------+     +-------------+
```

### 8.3 Interaction Flow (HITL)

```
Backend needs human input
    |
    v
Event: interaction.request
    |
    v
+-----------------------------------------+
|         InteractionModal                |
|                                         |
|  [Question from agent]                  |
|                                         |
|  +---------------------------------+    |
|  |  Response textarea              |    |
|  +---------------------------------+    |
|                                         |
|  [Cancel]                [Submit]       |
+-----------------------------------------+
    |
    v
POST /api/interactions/:id/reply
    |
    v
Backend continues execution
```

---

## 9. Security Workflows

### 9.1 Request Validation

```
User Request
    |
    v
+-----------------------------------------+
|         KERNEL.py CHECK                  |
|  - Alignment verification               |
|  - Creator binding (immutable)          |
+--------------------+--------------------+
    |
    v
+-----------------------------------------+
|         EXECUTION POLICY                 |
|  - Path validation                      |
|  - Command filtering                    |
|  - SSRF protection                      |
+--------------------+--------------------+
    |
    v
+-----------------------------------------+
|         TENANT ISOLATION                 |
|  - Multi-tenant context                 |
|  - Data separation                      |
|  - Access control                       |
+--------------------+--------------------+
    |
    v
Execute (if all checks pass)
```

### 9.2 7 Security Layers

```
Layer 1: KERNEL.py ---------► Immutable alignment
Layer 2: JWT Auth ----------► Token validation
Layer 3: RBAC --------------► Role-based access
Layer 4: Tenant Isolation --► Data separation
Layer 5: Rate Limiting -----► DoS protection
Layer 6: SSRF Protection ---► URL validation
Layer 7: Path Sandbox ------► File access control
```

---

## 10. Complete Workflow Examples

### 10.1 Simple Task (No Swarm)

```
User: "Read main.py and explain it"
    |
    v
IDLE -> TASK_ANALYSIS
    |
    v
Complexity: TRIVIAL -> BRAINSTORMING (direct)
    |
    v
Agent reads file -> Explanation
    |
    v
VALIDATING_CFL -> IDLE
    |
    v
Response to user
```

### 10.2 Complex Task (HiveMind + Swarm)

```
User: "Refactor auth system with tests"
    |
    v
IDLE -> TASK_ANALYSIS
    |
    v
Complexity: COMPLEX -> HIVE_DELEGATE
    |
    v
+-----------------------------------------+
|              HIVEMIND                    |
|                                         |
|  Phase 1: Both agents analyze auth      |
|  Phase 2: Debate on approach            |
|  Phase 3: Design refactor plan          |
|  Phase 4: Execute steps                 |
|      +-- Step 3: SwarmBridge            |
|              +-- PARALLEL mode          |
|                  (Claude: refactor)     |
|                  (Gemini: tests)        |
|  Phase 6: Merge results                 |
|  Phase 7: Complete                      |
+-----------------------------------------+
    |
    v
VALIDATING_CFL -> IDLE
    |
    v
Complete refactored code + tests
```

### 10.3 Security Audit (RED_BLUE)

```
User: "/swarm red_blue Security audit of api/"
    |
    v
SWARM_DELEGATE -> SWARM_NEGOTIATING
    |
    v
Mode: RED_BLUE (forced)
    |
    v
+-----------------------------------------+
|            RED_BLUE MODE                 |
|                                         |
|  RED (Gemini):                          |
|  - Scan for vulnerabilities             |
|  - Attempt exploits                     |
|  - Document attack vectors              |
|                                         |
|  BLUE (Claude):                         |
|  - Review findings                      |
|  - Propose fixes                        |
|  - Validate mitigations                 |
|                                         |
|  Final: Hardened code + report          |
+-----------------------------------------+
    |
    v
Security report + fixes
```

---

## 11. Error Recovery Workflows

### 11.1 Recoverable Error

```
Error occurs
    |
    v
STATE -> ERROR
    |
    v
User: /reset
    |
    v
ERROR -> IDLE
    |
    v
Ready for new input
```

### 11.2 HiveMind Diagnosis

```
Execution step fails
    |
    v
EXEC_STEP -> DIAG_PENDING
    |
    v
+-----------------------------------------+
|           DIAGNOSIS PHASE                |
|                                         |
|  1. Analyze error                       |
|  2. Identify root cause                 |
|  3. Propose fix                         |
|  4. Retry (up to 3x)                    |
+-----------------------------------------+
    |
    +-- Success -> Continue execution
    +-- Fail 3x -> HIVE_FAILED
```

---

## 12. Quick Reference

### Commands -> Workflows

| Command | Workflow Path |
|---------|---------------|
| Natural text | TaskAnalyzer -> Auto-route |
| `/swarm` | Force Swarm Engine |
| `/hive` | Force HiveMind |
| `/spawn` | Evolution -> Agent creation |
| `/evolve` | Evolution -> Mutation |
| `/memory index` | RAG -> Ingestion |
| `/memory query` | RAG -> Search |
| `/status` | Direct -> Status display |
| `/reset` | ERROR -> IDLE |

### Complexity -> Orchestration

| Complexity | Handler |
|------------|---------|
| TRIVIAL | Direct (single agent) |
| SIMPLE | Brainstorming |
| MODERATE | HiveMind or Swarm |
| COMPLEX | HiveMind + Swarm |
| EXPERT | Full HiveMind pipeline |

---

*Document generated: 2025-12-16 | NEXUS V13.0 MEMORIA UNIVERSALIS*
