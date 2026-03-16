# NEXUS V9.4 - ARCHITECTURE MAP

**Date:** 2025-12-13
**Architecte:** NEXUS PRIME (Claude Opus 4.5)
**Version:** 9.4 (Branch N9AF)
**Status:** Historical architecture snapshot from the pre-consolidation layout.

> This document is kept for historical review only.
> It is **not** the canonical architecture reference for `NX-CG`.
> Use `ROADMAP.md` for governance posture, `README.md` / `START_HERE.md` for supported runtime surfaces,
> and `docs/ARCHITECTURE_MAP_GENERATED.md` plus the live `core/` tree for the current package layout.

---

## LEVEL 1: VUE ORBITALE (C4 Context)

Vue système montrant NEXUS et ses interactions externes.

```mermaid
C4Context
    title NEXUS V9.4 - System Context Diagram

    Person(user, "Utilisateur", "Développeur utilisant NEXUS")

    System(nexus, "NEXUS V9.4", "Orchestrateur Multi-Agent<br/>Collaborative Intelligence")

    System_Ext(gemini_cli, "Gemini CLI", "google-gemini CLI<br/>JSON Strict Protocol")
    System_Ext(claude_cli, "Claude CLI", "anthropic CLI<br/>Hybrid XML Protocol")
    System_Ext(filesystem, "File System", "workspace/, .nexus/<br/>agents/, logs/")
    System_Ext(git, "Git Repository", "Version control<br/>LINEAGE tracking")

    Rel(user, nexus, "Commandes REPL", "stdin/stdout")
    Rel(nexus, gemini_cli, "subprocess", "JSON | --resume")
    Rel(nexus, claude_cli, "subprocess", "XML | <tool_use>")
    Rel(nexus, filesystem, "read/write", "JSON, Markdown, Python")
    Rel(nexus, git, "git CLI", "commits, branches")

    UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="1")
```

### Métadonnées Level 1

| Aspect | Valeur |
|--------|--------|
| **Pattern** | Hexagonal Architecture (Ports & Adapters) |
| **Santé** | 🟢 Clean - Boundaries claires |
| **Couplage Externe** | Faible (CLI wrappers isolent les APIs) |
| **Trust Boundary** | KERNEL.py valide toutes les mutations |

### Liens Documentation
- [KERNEL.py](KERNEL.py) - Règles d'alignement immuables
- [core/drivers/README.md](core/drivers/README.md) - Drivers LLM

---

## LEVEL 2: VUE SECTORIELLE (Containers)

Architecture interne montrant les modules et flux de données.

```mermaid
graph TD
    subgraph "Entry Layer"
        CLI[nexus7.py<br/>REPL Entry Point]
        API[core/api/<br/>REST Endpoints]
    end

    subgraph "Orchestration Layer"
        FSM[core/fsm/<br/>11 States FSM]
        ORCH[core/orchestration_v7.py<br/>OrchestratorV7]
        HIVE[core/hive_mind/<br/>7-Phase Pipeline]
        SYNC[sync_bridge.py<br/>V9.4 Mediator]
    end

    subgraph "Execution Layer"
        SWARM[core/swarm/<br/>6 Collaboration Modes]
        HANDLERS[core/execution/handlers/<br/>Modular Tool Handlers]
        DRV_G[GeminiDriverV7<br/>JSON Protocol]
        DRV_C[ClaudeDriverHybrid<br/>XML Protocol]
    end

    subgraph "Intelligence Layer"
        MEM[core/memory/<br/>RAG + SuccessMemory]
        EVO[core/evolution/<br/>Agent Factory]
        ROUTE[core/routing/<br/>Model Router]
        AGENTS[core/agents/<br/>Unified Registry]
    end

    subgraph "Support Layer"
        SEC[core/security/<br/>Guards + Policies]
        TEL[core/telemetry/<br/>Metrics Export]
        LOG[core/logging/<br/>Event Logger]
        BOOT[core/bootstrap/<br/>Auto-Discovery]
        HEALTH[core/resilience/<br/>SystemHealth]
    end

    %% Entry flows
    CLI -->|"UserInput | str"| FSM
    API -->|"HTTPRequest | JSON"| ORCH

    %% Orchestration flows
    FSM -->|"StateTransition | enum"| ORCH
    ORCH -->|"HiveMindTask | dataclass"| HIVE
    ORCH -->|"SwarmTask | dataclass"| SWARM
    HIVE <-->|"SyncEvent | dataclass"| SYNC
    SYNC <-->|"SyncEvent | dataclass"| SWARM

    %% Execution flows
    HIVE -->|"LLMRequest | HeavyMessageV7"| DRV_G
    HIVE -->|"LLMRequest | HeavyMessageV7"| DRV_C
    SWARM -->|"ModeExecution | CollaborationResult"| DRV_G
    SWARM -->|"ModeExecution | CollaborationResult"| DRV_C
    ORCH -->|"ToolCall | ToolRequest"| HANDLERS
    HANDLERS -->|"SecurityCheck | ToolRequest"| SEC

    %% Intelligence flows
    DRV_G -->|"ContextQuery | str"| MEM
    DRV_C -->|"ContextQuery | str"| MEM
    ORCH -->|"SpawnRequest | MutationProposal"| EVO
    ORCH -->|"ModelSelect | TaskType"| ROUTE
    SWARM -->|"AgentLookup | agent_id"| AGENTS

    %% Support flows
    ORCH -->|"Metrics | TelemetryEvent"| TEL
    ORCH -->|"LogEvent | dict"| LOG
    CLI -->|"ProjectScan | Path"| BOOT

    %% Styling
    classDef entry fill:#e1f5fe
    classDef orch fill:#fff3e0
    classDef exec fill:#f3e5f5
    classDef intel fill:#e8f5e9
    classDef support fill:#fce4ec

    class CLI,API entry
    class FSM,ORCH,HIVE,SYNC orch
    class SWARM,TOOLS,DRV_G,DRV_C exec
    class MEM,EVO,ROUTE,AGENTS intel
    class SEC,TEL,LOG,BOOT support
```

### Métadonnées Level 2

| Module | Pattern | Santé | Couplage | Tests |
|--------|---------|-------|----------|-------|
| **FSM** | State Machine | 🟢 Clean | Low | [test_fsm.py](tests/test_fsm.py) |
| **OrchestratorV7** | Mediator + Facade | 🟡 Complex | Medium | [test_orchestration.py](tests/test_orchestration.py) |
| **HiveMind** | Pipeline | 🟢 Clean | Medium | [test_hive_mind.py](tests/test_hive_mind.py) |
| **Swarm** | Strategy | 🟡 Complex | Medium | [test_swarm.py](tests/test_swarm.py) |
| **Drivers** | Adapter | 🟢 Clean | Low | [test_drivers.py](tests/test_drivers.py) |
| **ToolManager** | Command | 🔴 God Class | High | [test_tool_manager.py](tests/test_tool_manager.py) |
| **Memory** | Repository | 🟢 Clean | Low | [test_memory.py](tests/test_memory.py) |
| **Security** | Chain of Responsibility | 🟢 Clean | Low | [test_security.py](tests/test_security.py) |

### Légende Flux de Données

| Format | Description |
|--------|-------------|
| `Type \| Protocol` | Type de données et protocole utilisé |
| `dataclass` | Structure typée Python (Pydantic-like) |
| `enum` | Énumération (FSMState, SwarmMode) |
| `str` | Texte brut |
| `JSON` | Sérialisation JSON |

### Liens Documentation
- [core/README.md](core/README.md) - Vue d'ensemble core/
- [core/fsm/README.md](core/fsm/README.md) - Machine à états
- [core/swarm/README.md](core/swarm/README.md) - Hybrid Swarm Engine

---

## LEVEL 3: ZOOM TACTIQUE (3 Sous-systèmes Critiques)

### 3.1 OrchestratorV7 + FSM (Cœur du Système)

**Fichiers:** `core/orchestration_v7.py` (1074 LOC), `core/orchestration/fsm_handlers.py` (1408 LOC)

```mermaid
sequenceDiagram
    autonumber
    participant U as User
    participant R as REPL
    participant O as OrchestratorV7
    participant FSM as FSMState
    participant H as HiveMind
    participant S as Swarm

    U->>R: "Analyze this codebase"
    R->>O: process_input(text)
    O->>O: _analyze_task_complexity()

    alt Complexity >= MODERATE
        O->>FSM: transition(BRAINSTORMING)
        FSM-->>O: StateTransition OK
        O->>H: process_task(objective)
        H-->>O: HiveMindResult

        alt HiveMind delegates to Swarm
            H->>S: delegate(execution_step)
            S-->>H: CollaborationResult
        end

        O->>FSM: transition(IDLE)
    else Complexity < MODERATE
        O->>FSM: transition(EXECUTING_TOOL)
        O->>O: _direct_execution()
        O->>FSM: transition(IDLE)
    end

    O-->>R: response
    R-->>U: formatted_output
```

#### Métadonnées 3.1

| Aspect | Valeur |
|--------|--------|
| **Pattern** | Mediator (OrchestratorV7) + State (FSM) |
| **Santé** | 🟡 Complex - fsm_handlers.py trop grand |
| **Couplage** | Medium - Dépend de HiveMind et Swarm |
| **Points de Décision** | `_analyze_task_complexity()`, `FSM.can_transition()` |
| **Chemin d'Erreur** | FSM -> ERROR -> PANIC (si non récupérable) |

#### Recommandation
- Extraire `fsm_handlers.py` en handlers individuels par état

---

### 3.2 HybridSwarmEngine (Sélection de Mode)

**Fichiers:** `core/swarm/engine.py`, `core/swarm/mode_selector.py` (981 LOC), `core/swarm/mode_executors.py` (1323 LOC)

```mermaid
sequenceDiagram
    autonumber
    participant C as Caller
    participant E as SwarmEngine
    participant A as TaskAnalyzer
    participant S as ModeSelector
    participant N as Negotiation
    participant X as ModeExecutor

    C->>E: execute(task, agents)
    E->>A: analyze(task)
    A-->>E: TaskAnalysis(complexity, domains)

    E->>S: select_mode(analysis, agents)
    S->>S: _compute_dylan_scores()
    S-->>E: ModeProposal(mode, roles)

    alt Negotiation Required
        E->>N: negotiate(proposal, agents)
        loop Max 4 turns
            N->>N: agent_counter_propose()
            alt Consensus Reached
                N-->>E: AgreedMode
            else No Consensus
                N-->>E: FallbackMode
            end
        end
    end

    E->>X: execute_mode(mode, task)

    alt Mode Fails (Self-Healing V8.1.3)
        X-->>E: ExecutionError
        E->>E: _fallback_chain()
        Note over E: PARALLEL->SEQUENTIAL->SPECIALIST
        E->>X: execute_mode(fallback_mode)
    end

    X-->>E: CollaborationResult
    E-->>C: SwarmResult
```

#### Métadonnées 3.2

| Aspect | Valeur |
|--------|--------|
| **Pattern** | Strategy (6 modes) + Chain of Responsibility (Fallback) |
| **Santé** | 🟡 Complex - mode_executors.py contient 6 classes |
| **Couplage** | Medium - Dépend de Drivers et Agents |
| **Points de Décision** | `ModeSelector.select()`, `Negotiation.resolve()` |
| **Self-Healing** | Fallback chains: PARALLEL->SEQUENTIAL->SPECIALIST |

#### Recommandation
- Extraire chaque mode dans `core/swarm/executors/{mode}.py`

---

### 3.3 HiveMind Pipeline (7 Phases)

**Fichiers:** `core/hive_mind/orchestrator.py` (826 LOC), `core/hive_mind/phases/*.py`

```mermaid
sequenceDiagram
    autonumber
    participant O as Orchestrator
    participant HM as TrueHiveMind
    participant P1 as Phase_Analysis
    participant P2 as Phase_Debate
    participant P3 as Phase_Architecture
    participant P4 as Phase_Execution
    participant P5 as Phase_Diagnosis
    participant P6 as Phase_Consolidation
    participant SB as SyncBridge
    participant SM as SagaManager

    O->>HM: process_task(objective)
    HM->>SM: checkpoint("start")

    %% Phase 1: Analysis
    HM->>P1: execute(gemini, claude)
    P1->>P1: parallel_analysis()
    P1-->>HM: AnalysisResult
    HM->>SM: checkpoint("analysis")
    HM->>SB: sync_checkpoint("analysis")

    %% Phase 2: Debate (conditional)
    alt Disagreement Detected
        HM->>P2: execute(analyses)
        loop Until Consensus or Max Rounds
            P2->>P2: exchange_arguments()
        end
        P2-->>HM: DebateResult
        HM->>SM: checkpoint("debate")
    end

    %% Phase 3: Architecture
    HM->>P3: execute(consensus)
    P3-->>HM: ExecutionPlan
    HM->>SM: checkpoint("architecture")

    %% Phase 4: Execution
    HM->>P4: execute(plan)
    loop For each step
        P4->>P4: execute_step()
        alt Step uses Swarm
            P4->>SB: delegate_to_swarm()
        end
    end

    alt Execution Failed
        P4-->>HM: ExecutionError
        HM->>P5: diagnose(error)
        P5-->>HM: DiagnosisResult

        alt Retry Possible
            HM->>SM: rollback_to("architecture")
            HM->>SB: coordinated_rollback()
            Note over HM: Retry from Phase 3
        else Retry Exhausted
            HM->>P6: consolidate(partial_results)
        end
    else Execution Success
        P4-->>HM: ExecutionResult
    end

    %% Phase 6: Consolidation
    HM->>P6: consolidate(results)
    P6-->>HM: FinalResult
    HM->>SM: checkpoint("consolidation")

    HM-->>O: HiveMindResult
```

#### Métadonnées 3.3

| Aspect | Valeur |
|--------|--------|
| **Pattern** | Pipeline + Saga (Checkpoints & Rollback) |
| **Santé** | 🟢 Clean - Phases bien isolées |
| **Couplage** | Medium - SyncBridge V9.4 coordonne avec Swarm |
| **Points de Décision** | Consensus detection, Retry logic, Rollback target |
| **Checkpoints** | 5 points: start, analysis, debate, architecture, consolidation |

#### Recommandation
- Documenter le flux inverse Swarm->HiveMind (actuellement un angle mort)

---

## RÉSUMÉ ARCHITECTURAL

### Vue d'Ensemble

```
+-----------------------------------------------------------------+
|                    NEXUS V9.4 "SYNC BRIDGE"                     |
+-----------------------------------------------------------------+
|  +---------+    +-------------+    +-------------------------+  |
|  |  REPL   |--->| Orchestrator|--->| HiveMind (7 phases)     |  |
|  | nexus7  |    |     V7      |    | +---+---+---+---+---+--+|  |
|  +---------+    |   + FSM     |    | | A | D | R | E | G | C||  |
|                 +------+------+    | +---+---+---+---+---+--+|  |
|                        |           +------------+------------+  |
|                        |                        |               |
|                        |    +-------------------+-----------+   |
|                        |    |  OrchestratorSyncBridge V9.4  |   |
|                        |    +-------------------+-----------+   |
|                        |                        |               |
|                        |           +------------+------------+  |
|                        +---------->| HybridSwarmEngine       |  |
|                                    | +----+----+----+----+--+|  |
|                                    | |PAR |SEQ |L-S |P-P |SP||  |
|                                    | +----+----+----+----+--+|  |
|                                    +-------------------------+  |
|                                              |                  |
|                        +---------------------+---------------+  |
|                        |           LLM Drivers               |  |
|                        |  +-------------+  +--------------+  |  |
|                        |  |GeminiDriver |  | ClaudeDriver |  |  |
|                        |  |   (JSON)    |  |    (XML)     |  |  |
|                        |  +-------------+  +--------------+  |  |
|                        +-------------------------------------+  |
+-----------------------------------------------------------------+
```

### Patterns Architecturaux Principaux

| Pattern | Localisation | Usage |
|---------|--------------|-------|
| **State Machine** | FSM | 11 états, transitions validées |
| **Mediator** | OrchestratorV7, SyncBridge | Coordination sans couplage direct |
| **Pipeline** | HiveMind | 7 phases séquentielles |
| **Strategy** | Swarm | 6 modes interchangeables |
| **Saga** | SagaManager | Checkpoints + Rollback distribué |
| **Chain of Responsibility** | Security Guards, Fallback Chain | Traitement en cascade |
| **Adapter** | Drivers | Abstraction CLI -> Protocol unifié |
| **Repository** | Memory, AgentRegistry | Accès données centralisé |

### Points de Vigilance

| Zone | Problème | Impact | Priorité |
|------|----------|--------|----------|
| `tool_manager.py` | God Class (1848 LOC) | Maintenance difficile | 🔴 HIGH |
| `fsm_handlers.py` | Fichier monolithique (1408 LOC) | Tests complexes | 🔴 HIGH |
| `mode_executors.py` | 6 classes dans 1 fichier | Couplage artificiel | 🟡 MEDIUM |
| Swarm->HiveMind | Flux non documenté | Angle mort | 🟡 MEDIUM |

---

## CROSS-REFERENCES

| Section | Documentation Détaillée |
|---------|------------------------|
| FSM | [core/fsm/README.md](core/fsm/README.md) |
| Swarm | [core/swarm/README.md](core/swarm/README.md) |
| HiveMind | [core/hive_mind/README.md](core/hive_mind/README.md) |
| Drivers | [core/drivers/README.md](core/drivers/README.md) |
| Security | [core/security/README.md](core/security/README.md) |
| Memory | [core/memory/README.md](core/memory/README.md) |
| Orchestration | [core/orchestration/README.md](core/orchestration/README.md) |
| Audit Complet | [AUDIT_REPORT.md](AUDIT_REPORT.md) |

---

*Généré par NEXUS PRIME - Architecture Map V9.4*
