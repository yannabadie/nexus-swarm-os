# NEXUS V12.0 - Audit Complet de l'Architecture

**Date**: 2025-12-16
**Version**: V12.0.1 (commit 7b7046f)
**Auteur**: Claude Opus 4.5 (Analyse automatisée)

---

## Executive Summary

NEXUS est un **orchestrateur multi-agents de production** avec ~40,000 lignes de code réparties sur 6 sous-systèmes majeurs:

| Sous-système | Lignes | Maturité | Status |
|--------------|--------|----------|--------|
| Core Orchestration | 7,478 | 95% | Production |
| Swarm Engine | 7,362 | 88% | Production |
| HiveMind Pipeline | 9,796 | 90% | Production |
| Agent System | 12,000+ | 92% | Production |
| Memory & Security | ~5,500 | 87% | Production |
| CEREBRO API | ~3,000 | 85% | Production |

---

## 1. Core Orchestration (7,478 lignes)

### Architecture FSM
- **14 états FSM** (11 core + 3 swarm)
- **27 transitions** documentées
- **5 stratégies de récupération** (HealthStateMachine)

### Modules Clés
| Module | Lignes | Responsabilité |
|--------|--------|----------------|
| orchestration_v7.py | 1,122 | FSM principal |
| fsm_handlers.py | 1,820 | Handlers d'état |
| agent_invoker.py | 482 | Invocation + routing |
| context_builder.py | 423 | Construction contexte |
| sync_bridge.py | 805 | Sync HiveMind/Swarm |
| health_state_machine.py | 549 | Monitoring santé |
| stagnation_predictor.py | 476 | Prédiction proactive |

### États FSM
```
IDLE -> BRAINSTORMING -> EXECUTING_TOOL -> VALIDATING_CFL -> IDLE
         ↓                                      ↓
    WAITING_USER <------------------------ ERROR -> PANIC

États Swarm: SWARM_ANALYZING -> SWARM_NEGOTIATING -> SWARM_EXECUTING
```

### Points Forts
- Thread-safe via TaskExecutionContext immutable (V9.3)
- OWASP LLM01:2025 compliance (prompt injection)
- KERNEL integrity checks (every 100 iterations)
- Composition-based refactoring (V7.8 Phase 14c)

---

## 2. Swarm Engine (7,362 lignes)

### 6 Modes de Collaboration
| Mode | Description | Affinity | Rounds |
|------|-------------|----------|--------|
| PARALLEL | Travail simultané, fusion | 0.5 | 1 |
| SEQUENTIAL | Exécution ordonnée A->B | 0.6 | 2 |
| LEAD_SUPPORT | Lead 80%, Support 20% | 0.7 | 3 |
| PING_PONG | Alternance rapide | 0.6 | 6 |
| SPECIALIST | Expert unique | 0.8 | 1 |
| RED_BLUE | Adversarial propose/attack | 1.0 | 4 |

### Task Analyzer (3-Stage)
1. **Stage 1 (Regex)**: $0 cost - Instant commands
2. **Stage 2 (Heuristic)**: 68 keywords, 10 domains
3. **Stage 3 (LLM)**: Future - Low confidence escalation

### DyLAN Metrics
```
importance_score = quality_score / cost
selection_score = complexity_fit(0.30) + domain_fit(0.25) +
                  dylan_fit(0.25) + requirements_fit(0.20)
```

### Self-Healing Fallback (V7.5 Phase 8)
```
PARALLEL -> SEQUENTIAL -> SPECIALIST
RED_BLUE -> LEAD_SUPPORT -> SPECIALIST
```

---

## 3. HiveMind Pipeline (9,796 lignes)

### 7 Phases
| Phase | Fonction | États |
|-------|----------|-------|
| 1. Analysis | Analyse indépendante | ANALYZING_GEMINI, ANALYZING_CLAUDE |
| 2. Debate | Résolution désaccords | DEBATING, CHECKING_CONSENSUS |
| 3. Architecture | Design plan exécution | ARCHITECTING, CHECKING_REGISTRY |
| 4. Execution | Exécution monitorée | EXECUTING, MONITORING |
| 5. Diagnosis | Analyse échecs | DIAGNOSING |
| 6. Retry | Retry adaptatif | DECIDING_RETRY, APPLYING_CHANGES |
| 7. Consolidation | Archivage connaissances | REFLECTING, CONSOLIDATING |

### SwarmBridge (V8.3 "Dictator Mode")
- HiveMind = Stratège (QUOI et QUAND)
- Swarm = Tacticien (COMMENT)
- 9 combinaisons phase-mode validées

### SagaManager (V8.4.4)
- Checkpoints atomiques
- Rollback avec truncation contexte
- Anti-hallucination (context_index)
- Guards de phase (validation transitions)

### Context Manager
- Sliding window avec éviction prioritaire
- Scopes: FRESH, TASK_ONLY, TASK_PLUS_RESULTS, FULL
- Budgets par opération (5k-15k tokens)

---

## 4. Agent System (12,000+ lignes)

### Types d'Agents
| Type | Provider | Modèles |
|------|----------|---------|
| Gemini | GOOGLE | gemini-3-pro |
| Claude | ANTHROPIC | opus-4.5, sonnet-4.5 |
| Spawned | CUSTOM | Via /spawn |

### Driver Architecture (V11 F31)
```
DriverProtocol (ABC)
+-- AsyncGeminiDriver (JSON strict)
+-- AsyncClaudeDriver (Hybrid: XML + natural)
+-- Future: OllamaDriver
```

### Evolution Pipeline (5 Phases)
1. BRAINSTORM -> Mutation proposals via debate
2. CREATE -> Clone + apply patches
3. VALIDATE -> 4-tier validation
4. EVALUATE -> Fitness benchmarking
5. PROMOTE -> Winner replacement

### Agent-as-Tool (Vision Fractale Phase 15)
- Spawned agents exposés comme tools
- Invocation récursive (MAX_SWARM_DEPTH=2)
- AgentToolRegistry dynamique

### Tool Registry (11 Core Tools)
`bash`, `read`, `write`, `edit`, `list_dir`, `git`, `web_search`, `web_fetch`, `glob`, `grep`, `todo_write`

---

## 5. Memory & Security (~5,500 lignes)

### Memory System (3 Layers)
| Layer | Type | Storage |
|-------|------|---------|
| ProjectMemory | RAG | .nexus/project_knowledge.json |
| SuccessMemory | Episodic | workspace/memory/successes.json |
| AutoMemory | Procedural | workspace/memory/*.jsonl |

### RAG Backends (Pluggable)
1. **Dense**: LanceDB + sentence-transformers (+10% recall)
2. **BM25S**: Snowball stemming (+15% vs TF-IDF)
3. **TF-IDF**: Fallback (zero deps)

### MemoryCoordinator (V11.2 MEMORIA)
- Weights: Semantic 60% + Procedural 40%
- Time decay: `exp(-0.004 * age_days)`
- Unified recommendations

### Security (7 Layers)
| Layer | Module | Protection |
|-------|--------|------------|
| 1 | InputGuard | Prompt injection (OWASP LLM01:2025) |
| 2 | Spotlighter | RAG datamarking |
| 3 | ExecutionPolicy | Command injection |
| 4 | PathGuardian | Path traversal |
| 5 | OutputGuard | System prompt leaks |
| 6 | MutationValidator | Behavioral analysis |
| 7 | CodeValidator | Dynamic code AST |

### KERNEL.py (Immutable Anchor)
- 5 lois immuables
- SHA-256 boot verification
- V8.8 Heredity check (5% drift tolerance)

---

## 6. CEREBRO API (~3,000 lignes)

### Endpoints
| Route | Method | Purpose |
|-------|--------|---------|
| /api/auth/login | POST | JWT authentication |
| /api/auth/me | GET | Token validation |
| /api/state/snapshot | GET | F5 recovery |
| /api/workflow/start | POST | Launch workflow |
| /api/workflow/{id} | GET | Poll status |
| /api/files/tree | GET | Directory browser |
| /api/files/content | GET | File read |
| /api/files/save | POST | File write |
| /api/interactions/pending | GET | HITL requests |
| /ws/stream | WS | Event streaming |

### Event Types (23)
- Interaction: ask, confirm, choose, announce, progress
- Orchestration: state_change, phase_start, phase_end
- Agent: speak, tool_call, tool_result
- Swarm: mode_selected, negotiation, phase_change
- HiveMind: state_change, phase_start, phase_end
- Graph: node_spawn, node_update, edge_message
- System: log, error, heartbeat, connected

### Security (V11.6.2 IRONCLAD)
- JWT mandatory (Zero Trust)
- Token in-memory only (no localStorage)
- Tenant isolation from JWT claims
- PathGuardian on all file ops

### Redis Event Bus (V12.0)
- Pub/Sub avec pattern channels
- In-memory fallback si Redis indisponible
- Thread-safe via call_soon_threadsafe

---

## 7. Workflows Identifiés

### Workflow 1: Simple Task (TRIVIAL)
```
User Input -> InputGuard -> FSM IDLE -> BRAINSTORMING (1 turn) -> Response
```

### Workflow 2: Standard Task (MODERATE)
```
User Input -> TaskAnalyzer -> Swarm Auto-Route ->
  -> Mode Selection (DyLAN) -> Negotiation ->
  -> Execution (LEAD_SUPPORT typical) -> CFL Validation -> Response
```

### Workflow 3: Complex Task (COMPLEX/EXPERT)
```
User Input -> HiveMind Gate ->
  -> Phase 1: Independent Analysis (Gemini + Claude)
  -> Phase 2: Debate (if disagreement >15%)
  -> Phase 3: Architecture (SwarmBridge delegation)
  -> Phase 4: Monitored Execution
  -> [If fail: Phase 5 Diagnosis -> Phase 6 Retry]
  -> Phase 7: Consolidation (RAG archival)
```

### Workflow 4: Agent Spawning
```
/spawn "Role" -> BrainstormPhase (debate) ->
  -> InferenceConfig extraction -> Validation ->
  -> BIRTH_CERTIFICATE.json + system_prompt.md ->
  -> AgentPool registration -> agent_{id} tool available
```

### Workflow 5: Evolution
```
/evolve -> BrainstormPhase (mutations) ->
  -> CreatePhase (clone + patch) ->
  -> ValidatePhase (4-tier) ->
  -> EvaluatePhase (benchmark) ->
  -> PromotePhase (if >10% improvement)
```

### Workflow 6: CEREBRO Real-Time
```
Frontend Login -> JWT -> WebSocket Connect ->
  -> Event Subscription (tenant-scoped) ->
  -> HiveMap updates (graph.* events) ->
  -> InteractionModal (interaction.* events) ->
  -> F5 Recovery (/api/state/snapshot)
```

---

## 8. Gaps Identifiés

### Critical (P0)
| Gap | Impact | Effort |
|-----|--------|--------|
| No JWT refresh | Session expires after 24h | Medium |
| Single admin password | No multi-user | Large |
| In-memory workflow registry | No multi-instance | Medium |

### High (P1)
| Gap | Impact | Effort |
|-----|--------|--------|
| SuccessMemory session-scoped | Patterns lost on reset | Medium |
| No rate limiting | Brute-force possible | Small |
| Spotlighter not mandatory | Inconsistent RAG protection | Small |

### Medium (P2)
| Gap | Impact | Effort |
|-----|--------|--------|
| StagnationPredictor untested | Proactive detection uncertain | Medium |
| SyncBridge new (V9.4) | HiveMind/Swarm sync fragile | Medium |
| OutputGuard regex-only | Semantic leaks possible | Large |
| MemoryCoordinator weights static | No adaptive tuning | Medium |

### Low (P3)
| Gap | Impact | Effort |
|-----|--------|--------|
| No hybrid RAG backend | Suboptimal recall | Medium |
| No query expansion | Lexical misses | Small |
| Phase 10c embeddings | Context not semantic | Large |

---

## 9. Métriques Clés

| Métrique | Valeur |
|----------|--------|
| Total Lines of Code | ~40,000 |
| FSM States | 14 (11 core + 3 swarm) |
| HiveMind States | 24 |
| Collaboration Modes | 6 |
| Security Layers | 7 |
| Core Tools | 11 |
| Event Types | 23 |
| API Endpoints | 15+ |
| Test Coverage | ~1000 tests |

---

## 10. Conclusion

NEXUS V12.0 est un système **production-ready** avec une architecture mature:

**Forces:**
- FSM robuste avec récupération automatique
- 6 modes de collaboration adaptatifs (DyLAN)
- Pipeline HiveMind 7 phases avec checkpoints
- Sécurité 7 couches (OWASP compliant)
- API temps réel avec fallback gracieux

**Priorités Immédiates:**
1. JWT refresh mechanism
2. Multi-user authentication
3. Redis workflow registry
4. Rate limiting

**Architecture Recommandée pour Interface:**
- Graph visualization (custom SVG ou React Flow)
- Real-time event stream (WebSocket)
- Mission control (6 modes visibles)
- File commander (Monaco editor)
- Memory/knowledge browser

---

*Rapport généré automatiquement par Claude Opus 4.5*
