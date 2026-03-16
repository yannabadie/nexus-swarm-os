# Plan de Migration Full Async + CLI - NEXUS NX

**Date**: 2025-12-15
**Option**: B - Full Async avec conservation des drivers CLI
**Objectif**: Architecture async propre tout en gardant Gemini CLI / Claude Code CLI
**Effort estimé**: 2-3 semaines

---

## 1. Vue d'Ensemble

### Architecture Actuelle (Problématique)

```
+-----------------------------------------------------------------+
|                    ARCHITECTURE ACTUELLE                         |
+-----------------------------------------------------------------+
|                                                                  |
|  main() [SYNC]                                                   |
|      |                                                           |
|      v                                                           |
|  REPL.run() [SYNC]                                               |
|      |                                                           |
|      v                                                           |
|  OrchestratorV7.process_turn() [SYNC]                           |
|      |                                                           |
|      +--► _handle_trivial() [SYNC]                              |
|      |                                                           |
|      +--► _handle_moderate_plus() [SYNC]                        |
|      |        |                                                  |
|      |        v                                                  |
|      |    +-------------------------------------+               |
|      |    | ThreadPoolExecutor + asyncio.run() | ◄-- F18!      |
|      |    |     |                               |               |
|      |    |     v                               |               |
|      |    | HiveMind.process_task() [ASYNC]    |               |
|      |    +-------------------------------------+               |
|      |                                                           |
|      +--► SwarmEngine [HYBRIDE]                                 |
|               |                                                  |
|               v                                                  |
|           AsyncGeminiDriver.invoke() [ASYNC]                    |
|               |                                                  |
|               v                                                  |
|           asyncio.create_subprocess_exec()                      |
|               |                                                  |
|               v                                                  |
|           [Gemini CLI / Claude Code CLI]                        |
|                                                                  |
+-----------------------------------------------------------------+
```

### Architecture Cible (Full Async + CLI)

```
+-----------------------------------------------------------------+
|                    ARCHITECTURE CIBLE                            |
+-----------------------------------------------------------------+
|                                                                  |
|  if __name__ == "__main__":                                      |
|      asyncio.run(main())  ◄-- SINGLE EVENT LOOP                 |
|          |                                                       |
|          v                                                       |
|  async def main():                                               |
|      orch = OrchestratorV7()                                     |
|      await orch.run_async()                                      |
|          |                                                       |
|          v                                                       |
|  await REPL.run_async()                                          |
|          |                                                       |
|          v                                                       |
|  await OrchestratorV7.process_turn_async()                      |
|          |                                                       |
|          +--► await _handle_trivial_async()                     |
|          |                                                       |
|          +--► await _handle_moderate_plus_async()               |
|          |        |                                              |
|          |        v                                              |
|          |    await HiveMind.process_task()  ◄-- DIRECT AWAIT   |
|          |                                                       |
|          +--► await SwarmEngine.execute_async()                 |
|                   |                                              |
|                   v                                              |
|               await AsyncGeminiDriver.invoke()                  |
|                   |                                              |
|                   v                                              |
|               await asyncio.create_subprocess_exec()            |
|                   |                                              |
|                   v                                              |
|               [Gemini CLI / Claude Code CLI]                    |
|                                                                  |
+-----------------------------------------------------------------+
```

---

## 2. Patterns à Corriger

### F18: Nested Event Loops (CRITIQUE)

**Localisation**: 4 fichiers

| Fichier | Ligne | Pattern Actuel |
|---------|-------|----------------|
| `core/orchestration/fsm_handlers.py` | 773-788 | ThreadPoolExecutor + asyncio.run() |
| `core/swarm/executors/parallel_executor.py` | 64-70 | ThreadPoolExecutor + asyncio.run() |
| `core/async_utils.py` | 59-69 | ThreadPoolExecutor + asyncio.run() |
| `core/orchestration/sync_bridge.py` | 427-435 | ThreadPoolExecutor + asyncio.run() |

**Pattern Problématique**:
```python
# AVANT (F18)
def _handle_moderate_plus(self, user_input):
    try:
        loop = asyncio.get_running_loop()
        # Loop running -> ThreadPool hack
        with ThreadPoolExecutor() as executor:
            def run_hive():
                return asyncio.run(  # NESTED LOOP!
                    self._hive_mind.process_task(user_input)
                )
            future = executor.submit(run_hive)
            result = future.result(timeout=300)
    except RuntimeError:
        result = asyncio.run(self._hive_mind.process_task(user_input))
```

**Pattern Corrigé**:
```python
# APRÈS
async def _handle_moderate_plus_async(self, user_input):
    # Direct await - no nesting!
    result = await self._hive_mind.process_task(user_input)
    return result
```

---

### F19: Deprecated asyncio.get_event_loop()

**Localisation**: 18+ fichiers

```bash
# Fichiers affectés
core/hive_mind/user_interaction.py:222
core/orchestration/fsm_handlers.py:1391
core/hive_mind/async_adapter.py:272
core/interaction/cli_provider.py:59
core/bootstrap/service.py:177
core/hive_mind/saga_manager.py:575
core/interface/repl.py:317,383,403,432
core/telemetry/service.py:351,369
# ... et autres
```

**Pattern Problématique**:
```python
# AVANT (F19) - Deprecated Python 3.10+, Error Python 3.12+
loop = asyncio.get_event_loop()
loop.run_until_complete(coro)
```

**Pattern Corrigé**:
```python
# APRÈS - Option A: Dans contexte async
loop = asyncio.get_running_loop()

# APRÈS - Option B: Entry point sync
asyncio.run(coro)

# APRÈS - Option C: Compatibilité
try:
    loop = asyncio.get_running_loop()
except RuntimeError:
    # Not in async context
    asyncio.run(coro)
```

---

### F20: threading.Lock dans méthodes async

**Localisation**: `core/orchestration/sync_bridge.py`

**Pattern Problématique**:
```python
# AVANT (F20)
class OrchestratorSyncBridge:
    def __init__(self):
        self._lock = threading.RLock()  # Threading lock

    async def sync_checkpoint(self, ...):  # ASYNC method
        with self._lock:  # BLOCKS EVENT LOOP!
            # ...
```

**Pattern Corrigé**:
```python
# APRÈS
class OrchestratorSyncBridge:
    def __init__(self):
        self._async_lock = asyncio.Lock()  # Async lock

    async def sync_checkpoint(self, ...):
        async with self._async_lock:  # Non-blocking
            # ...
```

---

### F21: Fausse async (asyncio.to_thread wrapper)

**Localisation**: `core/drivers/gemini_driver_v7.py:270-297`

**Pattern Problématique**:
```python
# AVANT (F21) - Fake async
async def send_message_async(self, prompt, ...):
    # Wraps sync in thread - inefficient
    return await asyncio.to_thread(self.invoke, prompt, ...)
```

**Pattern Corrigé**:
```python
# APRÈS - True async driver
# Utiliser AsyncGeminiDriver directement au lieu de GeminiDriverV7

# Dans l'orchestrateur:
self.gemini_driver = AsyncGeminiDriver(config)  # Pas GeminiDriverV7

# Appel direct async
result = await self.gemini_driver.invoke(context)
```

---

### F22: Mixed execute patterns

**Localisation**: `core/swarm/executors/parallel_executor.py`

**Pattern Problématique**:
```python
# AVANT (F22)
class ParallelExecutor:
    def execute(self, context):  # SYNC entry
        try:
            loop = asyncio.get_running_loop()
            future = asyncio.run_coroutine_threadsafe(
                self.execute_async(context), loop
            )
            return future.result(timeout=300)
        except RuntimeError:
            return asyncio.run(self.execute_async(context))
```

**Pattern Corrigé**:
```python
# APRÈS
class ParallelExecutor:
    # Supprimer execute() sync, garder seulement async
    async def execute(self, context):
        results = await asyncio.gather(*async_tasks)
        return self._merge(results)
```

---

### F23: Blackboard non thread-safe

**Localisation**: `core/hive_mind/orchestrator.py`

**Pattern Problématique**:
```python
# AVANT (F23)
self.blackboard = {}  # Simple dict, race condition possible
```

**Pattern Corrigé**:
```python
# APRÈS - Option A: asyncio.Lock
class AsyncBlackboard:
    def __init__(self):
        self._data = {}
        self._lock = asyncio.Lock()

    async def set(self, key, value):
        async with self._lock:
            self._data[key] = value

    async def get(self, key, default=None):
        async with self._lock:
            return self._data.get(key, default)

# APRÈS - Option B: Utiliser AsyncBlackboard existant
from core.async_primitives.blackboard import AsyncBlackboard
self.blackboard = AsyncBlackboard()
```

---

## 3. Plan de Migration par Fichier

### Phase 1: Entry Points (2 jours)

| Fichier | Modification | Priorité |
|---------|--------------|----------|
| `nexus7.py` | `asyncio.run(main())` | P0 |
| `core/interface/repl.py` | `async def run()` | P0 |
| `core/orchestration_v7.py` | `async def process_turn()` | P0 |

**nexus7.py** (Entry Point):
```python
# AVANT
def main():
    orch = OrchestratorV7(...)
    repl = REPL(orch)
    repl.run()

if __name__ == "__main__":
    main()

# APRÈS
async def main():
    orch = OrchestratorV7(...)
    repl = REPL(orch)
    await repl.run_async()

if __name__ == "__main__":
    asyncio.run(main())
```

---

### Phase 2: Orchestrator (3 jours)

| Fichier | Modification | Priorité |
|---------|--------------|----------|
| `core/orchestration_v7.py` | Convertir en full async | P0 |
| `core/orchestration/fsm_handlers.py` | Supprimer ThreadPoolExecutor | P0 |
| `core/orchestration/sync_bridge.py` | asyncio.Lock | P1 |
| `core/orchestration/agent_invoker.py` | async def invoke | P1 |

**orchestration_v7.py**:
```python
class OrchestratorV7:
    async def process_turn(self, user_input: str) -> Dict:
        """Main entry - now async."""
        # Dispatch to async handlers
        if complexity == TaskComplexity.TRIVIAL:
            return await self._handlers.handle_trivial_async(user_input)
        elif complexity >= TaskComplexity.MODERATE:
            return await self._handlers.handle_moderate_plus_async(user_input)
```

---

### Phase 3: Swarm Engine (2 jours)

| Fichier | Modification | Priorité |
|---------|--------------|----------|
| `core/swarm/engine.py` | async execute | P1 |
| `core/swarm/executors/parallel_executor.py` | Supprimer sync execute | P0 |
| `core/swarm/executors/ping_pong_executor.py` | async execute | P1 |
| `core/swarm/executors/lead_support_executor.py` | async execute | P1 |

---

### Phase 4: Drivers (1 jour)

| Fichier | Modification | Priorité |
|---------|--------------|----------|
| `core/drivers/gemini_driver_v7.py` | Déprécier, utiliser AsyncGeminiDriver | P1 |
| `core/drivers/claude_driver_hybrid.py` | Déprécier, utiliser AsyncClaudeDriver | P1 |

**Note**: Les AsyncDrivers existent déjà et utilisent `asyncio.create_subprocess_exec`. On les utilise directement.

---

### Phase 5: Utilities (1 jour)

| Fichier | Modification | Priorité |
|---------|--------------|----------|
| `core/async_utils.py` | Supprimer patterns deprecated | P2 |
| Tous les fichiers avec `get_event_loop()` | Migrer vers `get_running_loop()` | P2 |

---

## 4. Checklist de Migration

### Pre-Migration
- [ ] Backup de la branche actuelle
- [ ] Créer branche `nx-full-async`
- [ ] Vérifier que tous les tests passent

### Phase 1: Entry Points
- [ ] Modifier `nexus7.py` -> `asyncio.run(main())`
- [ ] Modifier `REPL.run()` -> `async def run_async()`
- [ ] Vérifier startup fonctionne

### Phase 2: Orchestrator
- [ ] `OrchestratorV7.process_turn()` -> `async`
- [ ] `FSMHandlers._handle_*()` -> `async`
- [ ] Supprimer tous les `ThreadPoolExecutor + asyncio.run()`
- [ ] Remplacer `threading.RLock` par `asyncio.Lock`
- [ ] Tests orchestrator

### Phase 3: Swarm
- [ ] `HybridSwarmEngine.execute()` -> `async`
- [ ] `ParallelExecutor.execute()` -> supprimer sync
- [ ] Tous executors -> async only
- [ ] Tests swarm

### Phase 4: Drivers
- [ ] Remplacer `GeminiDriverV7` par `AsyncGeminiDriver`
- [ ] Remplacer `ClaudeDriverHybrid` par `AsyncClaudeDriver`
- [ ] Tests drivers

### Phase 5: Cleanup
- [ ] Grep `get_event_loop` -> migrer
- [ ] Grep `asyncio.run(` (hors entry point) -> supprimer
- [ ] Grep `ThreadPoolExecutor` + async -> supprimer
- [ ] Tests complets

### Post-Migration
- [ ] Load testing
- [ ] Vérifier pas de regression
- [ ] Merge dans NX

---

## 5. Risques et Mitigations

| Risque | Probabilité | Impact | Mitigation |
|--------|-------------|--------|------------|
| Regression fonctionnelle | Moyenne | Haut | Tests unitaires à chaque phase |
| Deadlock async | Faible | Critique | Revue de code, pas de sync dans async |
| Performance dégradée | Faible | Moyen | Benchmarks avant/après |
| Incompatibilité plugins | Moyenne | Moyen | Interface async + sync wrapper |

---

## 6. Tests de Validation

### Test 1: Single Agent Mode
```bash
# Doit fonctionner sans erreur
nexus7> "Hello"
# Réponse normale
```

### Test 2: HiveMind (MODERATE+)
```bash
# Doit utiliser HiveMind sans ThreadPoolExecutor
nexus7> "Analyze this codebase and propose improvements"
# Pipeline 7 phases, pas de nested loop
```

### Test 3: PARALLEL Mode
```bash
# Doit exécuter les deux agents en vraie parallèle async
nexus7> /swarm parallel "Compare React vs Vue for this project"
# asyncio.gather() sans threads
```

### Test 4: No Deprecation Warnings
```bash
python -W error::DeprecationWarning nexus7.py
# Doit démarrer sans DeprecationWarning asyncio
```

---

## 7. Métriques de Succès

| Métrique | Avant | Cible |
|----------|-------|-------|
| DeprecationWarnings asyncio | 18+ | 0 |
| ThreadPoolExecutor dans async | 4 | 0 |
| threading.Lock dans async | 2+ | 0 |
| Nested event loops | 4 | 0 |
| Tests passants | X | X (pas de regression) |

---

## 8. Commandes de Vérification

```bash
# Trouver les nested event loops restants
grep -rn "asyncio.run(" core/ --include="*.py" | grep -v "if __name__"

# Trouver les get_event_loop deprecated
grep -rn "get_event_loop()" core/ --include="*.py"

# Trouver les ThreadPoolExecutor dans contexte async
grep -rn "ThreadPoolExecutor" core/ --include="*.py"

# Trouver les threading.Lock
grep -rn "threading.RLock\|threading.Lock" core/ --include="*.py"
```

---

## 9. Estimation Effort

| Phase | Effort | Développeur |
|-------|--------|-------------|
| Phase 1: Entry Points | 2 jours | 1 |
| Phase 2: Orchestrator | 3 jours | 1 |
| Phase 3: Swarm | 2 jours | 1 |
| Phase 4: Drivers | 1 jour | 1 |
| Phase 5: Cleanup | 1 jour | 1 |
| Tests & Debug | 2 jours | 1 |
| **Total** | **11 jours (~2 semaines)** | 1 |

---

## 10. Décisions Architecturales

### ADR-001: Single Event Loop

**Contexte**: L'architecture actuelle crée des event loops imbriqués via ThreadPoolExecutor.

**Décision**: Un seul event loop créé au démarrage via `asyncio.run(main())`.

**Conséquences**:
- Toutes les opérations async partagent le même loop
- Plus de deadlocks liés aux nested loops
- Simplification du debugging

### ADR-002: Async-First, Sync Wrapper

**Contexte**: Certains composants externes peuvent nécessiter des interfaces sync.

**Décision**: Toute la logique est async. Des wrappers sync optionnels pour compatibilité.

**Pattern**:
```python
class Component:
    async def operation(self):  # Primary async
        ...

    def operation_sync(self):  # Optional sync wrapper
        return asyncio.run(self.operation())
```

### ADR-003: Conservation des Drivers CLI

**Contexte**: Migration vers API directe trop coûteuse à court terme.

**Décision**: Conserver `asyncio.create_subprocess_exec` pour les CLI.

**Conséquences**:
- Performance subprocess maintenue (pas optimale mais acceptable)
- Features CLI préservées (session, tools)
- Migration API possible ultérieurement

---

*Document de migration - NEXUS NX vers Full Async + CLI*
*Version: 1.0*
*Date: 2025-12-15*
