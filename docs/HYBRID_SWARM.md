# NEXUS V12.4 - Hybrid Swarm Engine

**Current Version**: V12.4 NX-CG (model-agnostic, CapabilityRouter)
**Original**: V7.0 "Chrysalis" Sprint 9 (2025-11-26)
**Last Updated**: 2026-03-17

---

## Executive Summary

Le **Hybrid Swarm Engine** est le cœur de NEXUS V7. Il transforme le système d'un orchestrateur à rôles fixes en une collaboration dynamique où Gemini et Claude **négocient** le meilleur mode de travail pour chaque tâche.

> "Pas de rôles fixes - Négociation à la volée"

---

## Table des Matières

1. [Vision et Philosophie](#vision-et-philosophie)
2. [Architecture](#architecture)
3. [Les 6 Modes de Collaboration](#les-6-modes-de-collaboration)
4. [Pipeline Complet](#pipeline-complet)
5. [Composants Détaillés](#composants-détaillés)
6. [Protocole de Négociation](#protocole-de-négociation)
7. [Intégration FSM](#intégration-fsm)
8. [Configuration](#configuration)
9. [API Reference](#api-reference)
10. [Exemples d'Utilisation](#exemples-dutilisation)
11. [Tests](#tests)
12. [Troubleshooting](#troubleshooting)

---

## Vision et Philosophie

### Le Problème

Les systèmes multi-agents traditionnels ont des rôles fixes:
- Agent A = Planificateur
- Agent B = Exécuteur

Cette rigidité ne reflète pas la réalité des tâches complexes.

### La Solution NEXUS

Le Hybrid Swarm Engine permet aux agents de:
1. **Analyser** chaque tâche (complexité, domaines)
2. **Négocier** le meilleur mode de collaboration
3. **Exécuter** selon le mode choisi
4. **Apprendre** via DyLAN metrics

### Principes Fondamentaux

| Principe | Description |
|----------|-------------|
| **Égalité** | Gemini et Claude sont des pairs (pas de hiérarchie) |
| **Dynamisme** | Le mode change à chaque tâche |
| **Consensus** | Les agents doivent s'accorder |
| **Apprentissage** | DyLAN améliore les choix au fil du temps |

---

## Architecture

```
                         USER INPUT
                              |
                              v
+-------------------------------------------------------------+
|                    HYBRID SWARM ENGINE                       |
|                                                              |
|  +--------------+   +--------------+   +----------------+   |
|  | TaskAnalyzer |-->| ModeSelector |-->| Negotiation    |   |
|  |              |   |   (DyLAN)    |   | Protocol       |   |
|  +--------------+   +--------------+   +----------------+   |
|         |                  |                   |             |
|         v                  v                   v             |
|  +-----------------------------------------------------+    |
|  |                  MODE EXECUTORS                      |    |
|  |  +--------+ +--------+ +---------+ +---------+     |    |
|  |  |PARALLEL| |SEQUENT | |  LEAD   | |PING_PONG|     |    |
|  |  +--------+ +--------+ +---------+ +---------+     |    |
|  |  +----------+ +----------+                          |    |
|  |  |SPECIALIST| | RED_BLUE |                          |    |
|  |  +----------+ +----------+                          |    |
|  +-----------------------------------------------------+    |
|                              |                               |
+------------------------------+-------------------------------+
                               v
                    ORCHESTRATOR V7 (FSM)
```

### Fichiers du Module

```
core/swarm/
+-- __init__.py               # Exports (~150 lignes)
+-- agent_metrics.py          # DyLAN metrics (Sprint 3)
+-- collaboration_modes.py    # 6 modes + caractéristiques
+-- task_analyzer.py          # Analyse complexité/domaines
+-- mode_selector.py          # Sélection basée sur DyLAN
+-- negotiation_protocol.py   # Protocole hybride
+-- mode_executors.py         # 6 executors
+-- hybrid_swarm_engine.py    # Moteur principal
```

---

## Les 6 Modes de Collaboration

### Vue d'Ensemble

| Mode | Icône | Description | Cas d'Usage |
|------|-------|-------------|-------------|
| **PARALLEL** | ⚡ | Travail simultané, merge results | Sous-tâches indépendantes |
| **SEQUENTIAL** | ➡️ | Premier puis second (pipeline) | Dépendances claires |
| **LEAD_SUPPORT** | 👑 | Lead (80%) + Support (20%) | Expertise dominante |
| **PING_PONG** | 🏓 | Alternance rapide | Créativité, brainstorm |
| **SPECIALIST** | 🎯 | Expert unique | Expertise exclusive |
| **RED_BLUE** | ⚔️ | Adversarial (propose/attack) | Sécurité, décisions critiques |

### Détails par Mode

#### PARALLEL ⚡

```
+---------+     +---------+
| Gemini  |     | Claude  |
| Task A  |     | Task B  |
+----+----+     +----+----+
     |               |
     +------+--------+
            v
      +---------+
      |  MERGE  |
      +---------+
```

- **Quand**: Sous-tâches indépendantes
- **Avantage**: Rapidité (temps = max(A, B))
- **Caractéristiques**:
  - `parallelism_benefit`: 1.0
  - `typical_rounds`: 1

#### SEQUENTIAL ➡️

```
+---------+     +---------+
| Agent 1 |---->| Agent 2 |
| Phase 1 |     | Phase 2 |
+---------+     +---------+
```

- **Quand**: Résultat de A nécessaire pour B
- **Avantage**: Cohérence
- **Caractéristiques**:
  - `parallelism_benefit`: 0.0
  - `typical_rounds`: 2

#### LEAD_SUPPORT 👑

```
+-------------------------+
|        LEAD (80%)       |
|  +-------------------+  |
|  | Développe solution |  |
|  +---------+---------+  |
|            |            |
|   +--------v--------+   |
|   | SUPPORT (20%)   |   |
|   | Review/Feedback |   |
|   +--------+--------+   |
|            |            |
|  +---------v---------+  |
|  | LEAD révise       |  |
|  +-------------------+  |
+-------------------------+
```

- **Quand**: Un agent a une expertise claire
- **Avantage**: Qualité + vérification
- **Caractéristiques**:
  - `complexity_affinity`: 0.7
  - `typical_rounds`: 3

#### PING_PONG 🏓

```
     Round 1      Round 2      Round 3
+---------+  +---------+  +---------+
| Gemini  |->| Claude  |->| Gemini  |-> ...
+---------+  +---------+  +---------+
```

- **Quand**: Brainstorming, créativité
- **Avantage**: Co-construction
- **Caractéristiques**:
  - `typical_rounds`: 6 (max)
  - Converge quand agent dit "FINISHED"

#### SPECIALIST 🎯

```
+-------------------------+
|   EXPERT (100%)         |
|   +-----------------+   |
|   | Gemini OR Claude |   |
|   |   handles all    |   |
|   +-----------------+   |
|                         |
|   [Other observes]      |
+-------------------------+
```

- **Quand**: Expertise exclusive (SWE-bench pour Claude, Terminal-Bench pour Gemini)
- **Avantage**: Efficacité
- **Caractéristiques**:
  - `typical_rounds`: 1
  - Single agent

#### RED_BLUE ⚔️

```
+--------------------------------------+
|  Phase 1: BLUE Propose               |
|  +--------------------------------+  |
|  | Claude: "Voici ma solution..." |  |
|  +--------------------------------+  |
|                                      |
|  Phase 2: RED Attack                 |
|  +--------------------------------+  |
|  | Gemini: "Faille trouvée..."    |  |
|  +--------------------------------+  |
|                                      |
|  Phase 3: BLUE Defend                |
|  +--------------------------------+  |
|  | Claude: "Voici la correction"  |  |
|  +--------------------------------+  |
|                                      |
|  Phase 4: RED Verify                 |
|  +--------------------------------+  |
|  | Gemini: "PASS/FAIL + raisons"  |  |
|  +--------------------------------+  |
+--------------------------------------+
```

- **Quand**: Sécurité, décisions critiques
- **Avantage**: Robustesse
- **Caractéristiques**:
  - `adversarial`: True
  - `complexity_affinity`: 1.0
  - `typical_rounds`: 4

---

## Pipeline Complet

```
User Input
    |
    v
+-----------------------------------------------------+
| 1. TASK ANALYSIS                                     |
|    TaskAnalyzer.analyze(input)                       |
|    -> complexity: TRIVIAL -> EXPERT                    |
|    -> domains: [CODING, RESEARCH, SECURITY...]        |
|    -> gemini_fit_score: 0.0 - 1.0                     |
|    -> claude_fit_score: 0.0 - 1.0                     |
+-----------------------------------------------------+
    |
    v
+-----------------------------------------------------+
| 2. MODE SELECTION (DyLAN-based)                      |
|    ModeSelector.select_mode(analysis)                |
|    -> Score each mode for task                        |
|    -> Use agent importance scores                     |
|    -> Return ModeProposal                             |
+-----------------------------------------------------+
    |
    v
+-----------------------------------------------------+
| 3. NEGOTIATION (if enabled)                          |
|    NegotiationProtocol.run_negotiation()             |
|    -> Agents debate in natural language               |
|    -> Embed <negotiate> JSON proposals                |
|    -> Max 4 turns or consensus                        |
+-----------------------------------------------------+
    |
    v
+-----------------------------------------------------+
| 4. EXECUTION                                         |
|    ModeExecutor.execute(context)                     |
|    -> Run according to selected mode                  |
|    -> Track tokens/time per agent                     |
+-----------------------------------------------------+
    |
    v
+-----------------------------------------------------+
| 5. METRICS UPDATE                                    |
|    AgentPool.record_invocation()                     |
|    -> Update DyLAN importance scores                  |
|    -> Improve future mode selection                   |
+-----------------------------------------------------+
    |
    v
 Final Output
```

---

## Composants Détaillés

### TaskAnalyzer

Analyse l'input utilisateur pour déterminer:

```python
from core.swarm import TaskAnalyzer, TaskComplexity, TaskDomain

analyzer = TaskAnalyzer()
analysis = analyzer.analyze("Fix the authentication bug in auth.py")

print(analysis.complexity)        # TaskComplexity.COMPLEX
print(analysis.domains)           # [TaskDomain.DEBUGGING, TaskDomain.CODING]
print(analysis.gemini_fit_score)  # 0.65
print(analysis.claude_fit_score)  # 0.90
print(analysis.recommended_lead)  # "claude"
```

#### TaskComplexity (1-5)

| Niveau | Valeur | Négociation |
|--------|--------|-------------|
| TRIVIAL | 1 | Skip |
| SIMPLE | 2 | Optionnel |
| MODERATE | 3 | Recommandé |
| COMPLEX | 4 | Requis |
| EXPERT | 5 | Requis + RED_BLUE |

#### TaskDomain

- `CODING`: Implémentation, code
- `RESEARCH`: Recherche web, documentation
- `ANALYSIS`: Analyse, compréhension
- `CREATIVE`: Brainstorming, idées
- `DEBUGGING`: Debug, fix
- `SECURITY`: Sécurité, vulnérabilités
- `DOCUMENTATION`: Docs, README
- `TESTING`: Tests, validation
- `ARCHITECTURE`: Design, structure
- `WEB_INTERACTION`: APIs, web

### ModeSelector

Sélectionne le mode optimal en combinant:
1. **Task Analysis** (30%): Complexité, domaines
2. **Domain Fit** (25%): Forces des agents
3. **DyLAN Scores** (25%): Importance historique
4. **Requirements Fit** (20%): Web, code, reasoning

```python
from core.swarm import ModeSelector, AgentPool

pool = AgentPool()
selector = ModeSelector(agent_pool=pool)

proposal = selector.select_mode(analysis)

print(proposal.mode)        # CollaborationMode.LEAD_SUPPORT
print(proposal.confidence)  # 0.85
print(proposal.reasoning)   # "Task complexity: complex | Domains: debugging | ..."
```

### NegotiationProtocol

Format hybride: **langage naturel + JSON structuré**

```
Gemini: "Pour cette tâche de debugging, je pense que le mode LEAD_SUPPORT
serait optimal. Claude a une expertise claire en code Python.

<negotiate>
{
  "proposed_mode": "lead_support",
  "proposed_lead": "Claude",
  "confidence": 0.85,
  "my_role": "support",
  "justification": "Debugging Python = Claude strength"
}
</negotiate>"

Claude: "D'accord, je mènerai l'investigation du bug.

<negotiate>
{
  "agrees_with_partner": true,
  "consensus_reached": true,
  "subtasks": {
    "Claude": "Code analysis + fix",
    "Gemini": "Web research for similar issues"
  }
}
</negotiate>"
```

### Mode Executors

Chaque mode a son executor:

```python
from core.swarm import get_executor, CollaborationMode

executor = get_executor(CollaborationMode.PARALLEL)
result = executor.execute(context)

print(result.mode)           # CollaborationMode.PARALLEL
print(result.status)         # ExecutionStatus.COMPLETED
print(result.total_rounds)   # 1
print(result.final_output)   # Merged output
```

---

## Intégration FSM

### Nouveaux États

```python
class OrchestratorState(Enum):
    # États existants...
    IDLE = auto()
    BRAINSTORMING = auto()
    EXECUTING_TOOL = auto()
    VALIDATING_CFL = auto()

    # Nouveaux états Swarm (Sprint 9)
    SWARM_ANALYZING = auto()     # Analyse de la tâche
    SWARM_NEGOTIATING = auto()   # Négociation du mode
    SWARM_EXECUTING = auto()     # Exécution du mode
```

### Transitions

```
IDLE
  | (swarm enabled + user input)
  v
SWARM_ANALYZING ---------------------+
  |                                  |
  | (trivial task)                   | (complex task)
  |                                  v
  +--------------------------► SWARM_NEGOTIATING
                                    |
                                    v
                              SWARM_EXECUTING
                                    |
                                    v
                              VALIDATING_CFL
                                    |
                                    v
                                  IDLE
```

### Utilisation dans Orchestrator

```python
# Méthode FSM (états)
result = orchestrator.start_swarm_mode("Fix the bug")
while result["state"] != "IDLE":
    result = orchestrator.process_turn()

# Méthode directe (one-shot)
result = orchestrator.process_with_swarm(
    task_input="Fix the bug",
    force_mode=CollaborationMode.LEAD_SUPPORT,  # Optional
    skip_negotiation=True  # Optional
)
```

---

## Configuration

### Variables d'Environnement

```bash
# Activer/Désactiver Swarm
SWARM_ENABLED=True

# Négociation
SWARM_NEGOTIATION=True
SWARM_NEGOTIATION_TURNS=4

# Mode par défaut (si pas de négociation)
SWARM_DEFAULT_MODE=ping_pong

# Skip pour tâches triviales
SWARM_SKIP_TRIVIAL=True

# Limite d'exécution
SWARM_MAX_ROUNDS=6
```

### Config Python

```python
from core.config import Config

config = Config()
config.swarm_enabled = True
config.swarm_negotiation_enabled = True
config.swarm_negotiation_max_turns = 4
config.swarm_default_mode = "ping_pong"
config.swarm_skip_trivial = True
config.swarm_max_rounds = 6
```

---

## API Reference

### HybridSwarmEngine

```python
class HybridSwarmEngine:
    def __init__(
        self,
        agent_pool: Optional[AgentPool] = None,
        model_router: Optional[ModelRouter] = None,
        config: Optional[Config] = None,
        invoke_agent: Optional[Callable] = None
    )

    def process_task(
        self,
        task_input: str,
        blackboard: Optional[Dict] = None,
        force_mode: Optional[CollaborationMode] = None,
        skip_negotiation: bool = False
    ) -> SwarmResult

    def start_analysis(self, task_input: str) -> TaskAnalysis
    def start_selection(self) -> ModeProposal
    def start_negotiation(self) -> Optional[NegotiationResult]
    def execute_turn(self, task_input: str, blackboard: Dict) -> ExecutionResult

    def reset(self)
    def get_stats(self) -> Dict
```

### SwarmResult

```python
@dataclass
class SwarmResult:
    status: SwarmPhase
    final_output: str
    selected_mode: CollaborationMode
    task_analysis: TaskAnalysis
    mode_proposal: ModeProposal
    negotiation_result: Optional[NegotiationResult]
    execution_result: ExecutionResult
    total_time_seconds: float
    timestamp: datetime
```

---

## Exemples d'Utilisation

### Exemple 1: Utilisation Basique

```python
from core.swarm import HybridSwarmEngine

engine = HybridSwarmEngine()
result = engine.process_task("Write a function to parse JSON safely")

print(f"Mode: {result.selected_mode.value}")
print(f"Output: {result.final_output}")
```

### Exemple 2: Forcer un Mode

```python
from core.swarm import HybridSwarmEngine, CollaborationMode

engine = HybridSwarmEngine()
result = engine.process_task(
    "Review this code for security vulnerabilities",
    force_mode=CollaborationMode.RED_BLUE
)
```

### Exemple 3: Via Orchestrator

```python
from core.orchestration_v7 import OrchestratorV7

orchestrator = OrchestratorV7(workspace, config, gemini_info, claude_info)

# Méthode one-shot
result = orchestrator.process_with_swarm("Debug the authentication flow")

# OU via FSM
orchestrator.start_swarm_mode("Debug the authentication flow")
while orchestrator.state.name.startswith("SWARM"):
    result = orchestrator.process_turn()
```

### Exemple 4: Analyse Seule

```python
from core.swarm import TaskAnalyzer

analyzer = TaskAnalyzer()
analysis = analyzer.analyze("Create a REST API with authentication")

print(f"Complexity: {analysis.complexity.name}")
print(f"Domains: {[d.value for d in analysis.domains]}")
print(f"Recommended lead: {analysis.recommended_lead}")
print(f"Needs adversarial: {analysis.needs_adversarial_mode}")
```

---

## Tests

### Lancer les Tests

```bash
cd NEXUS_V7_CHRYSALIS
python -m pytest tests/test_hybrid_swarm.py -v
```

### Couverture

| Module | Tests |
|--------|-------|
| CollaborationModes | 6 |
| TaskAnalyzer | 6 |
| ModeSelector | 4 |
| NegotiationProtocol | 6 |
| ModeExecutors | 7 |
| HybridSwarmEngine | 8 |
| FSM Integration | 2 |
| Config | 2 |
| **Total** | **41** |

---

## Troubleshooting

### Swarm Désactivé

```
Error: Swarm engine not enabled
```

**Solution**: Vérifier `SWARM_ENABLED=True` dans `.env`

### Négociation Timeout

```
Status: timeout (4 turns without consensus)
```

**Solution**: Augmenter `SWARM_NEGOTIATION_TURNS` ou forcer un mode

### Mode Non Approprié

Si le mode sélectionné ne convient pas:

```python
# Forcer un mode spécifique
result = engine.process_task(task, force_mode=CollaborationMode.PARALLEL)
```

### Agents en Stagnation

Si les agents répètent les mêmes messages:
- Le `StagnationDetector` détecte automatiquement
- Force un switch d'agent ou une décision

---

## Changelog

### V12.4 NX-CG (2026-03-17) — Model-Agnostic Migration

- **CapabilityRouter** (`capability_router.py`): maps `TaskAnalysis.domains` → semantic slots (`primary`, `secondary`, `critic`, `executor`) → `BaseAsyncDriver`. Supports 7 providers × 13 task domains via `AGENT_DOMAIN_STRENGTHS` scoring table.
- **NegotiationProtocol**: removed hardcoded `["gemini", "claude"]` fallback — now uses `registry.get_active_builtin_ids()`. Guards empty registry with `NegotiationStatus.FORCED`.
- **HybridSwarmEngine**: single-provider mode degradation — `PARALLEL`, `LEAD_SUPPORT`, `PING_PONG`, `RED_BLUE` auto-degrade to `SPECIALIST` when only 1 provider is registered.
- **TaskDomain**: extended with `GENERAL`, `WRITING`, `REASONING` values.
- **DynamicRoleAssigner**: `DEFAULT_DOMAIN_PROFILES` extended from 2 → 7 providers.
- **Executor base**: provider lookup via `agent_desc.provider.value` (no hardcoded strings).

### Sprint 9 (2025-11-26)

- Initial implementation
- 6 collaboration modes
- Task analyzer with domain detection
- DyLAN-based mode selector
- Hybrid negotiation protocol
- FSM integration (3 new states)
- 41 unit tests

---

*Documentation Hybrid Swarm Engine - NEXUS V7.0 "Chrysalis" / V12.4 NX-CG*
