# OPERATION CORTEX V11.5 - Deliverable Report

**Date:** 2025-12-15
**Commit:** `2e20dba` (branch: NX)
**Implémenté par:** Claude Opus 4.5
**Validé par:** Conseiller externe (3 revues successives)

---

## Executive Summary

OPERATION CORTEX transforme l'API CEREBRO d'une "Radio" (streaming events) en un "Cockpit" complet permettant le pilotage bidirectionnel depuis l'UI.

### 3 Bugs Critiques Corrigés

| Bug | Symptôme | Solution |
|-----|----------|----------|
| **Fantôme de la Question** | Pending interactions perdues sur F5 | `pending_interactions` inclus dans `/api/state/snapshot` |
| **Guillotine du TTL** | État expiré après 1h d'inactivité | TTL augmenté à 24h (`STATE_TTL = 86400`) |
| **Étouffement (OOM)** | Crash serveur sur gros fichiers | Limite 1MB avec HTTP 413 (`MAX_FILE_SIZE = 1_000_000`) |

---

## Nouveaux Endpoints API

### 1. State Snapshot (F5 Recovery)

**`GET /api/state/snapshot?tenant_id=X&workspace_id=Y`**

Récupère l'état complet pour hydrater l'UI après refresh (F5).

```json
{
  "phase": {"state": "EXECUTING", "progress": 50},
  "nodes": {"agent_001": {"role": "analyst", "status": "active"}},
  "logs": [{"level": "INFO", "message": "Starting analysis..."}],
  "pending_interactions": [
    {"request_id": "abc123", "type": "confirm", "prompt": "Continuer?"}
  ],
  "tenant_id": "my_tenant",
  "workspace_id": "default"
}
```

**Points Critiques:**
- `pending_interactions` provient du `HeadlessProvider` (RAM Python), pas de Redis
- Résout le bug "Fantôme de la Question"
- TTL Redis = 24h (86400 secondes)

---

### 2. Human-in-the-Loop (Interaction Resolution)

**`POST /api/interactions/{request_id}/reply`**

Permet à l'UI de répondre aux questions de l'agent.

```json
// Request
{"response": true}

// Response (200)
{"status": "resolved", "request_id": "abc123"}

// Error (404)
{"detail": "Request abc123 not found or already expired/resolved"}
```

**`GET /api/interactions/pending`**

Liste les interactions en attente.

```json
{"pending": [
  {"request_id": "abc123", "type": "confirm", "prompt": "Continuer?", "timestamp": "2025-12-15T10:30:00Z"}
]}
```

---

### 3. Workflow Control

**`POST /api/workflow/start?tenant_id=X`**

Démarre une tâche de manière non-bloquante.

```json
// Request
{"task": "Analyse ce fichier et corrige les bugs"}

// Response (200)
{"workflow_id": "wf_abc123", "status": "pending"}
```

**`GET /api/workflow/{workflow_id}`**

Récupère le statut d'un workflow.

```json
{
  "workflow_id": "wf_abc123",
  "status": "running",  // pending | running | completed | failed | cancelled
  "task": "Analyse ce fichier...",
  "result": null,
  "error": null
}
```

**`POST /api/workflow/{workflow_id}/stop`**

Arrête un workflow en cours.

---

### 4. Secure File Access

**`GET /api/files/content?path=relative/path.py`**

Lit un fichier avec protection OOM.

```json
// Success (200)
{"path": "relative/path.py", "content": "...", "size": 1234}

// Too Large (413)
{"detail": "File too large: 2,000,000 bytes exceeds 1,000,000 byte limit"}

// Forbidden (403) - Path traversal blocked
{"detail": "Access denied: [SECURITY] Read outside allowed zones: /etc/passwd"}
```

**`POST /api/files/save`**

Écrit un fichier avec validation PathGuardian.

```json
// Request
{"path": "output/result.json", "content": "{\"result\": true}"}

// Response (200)
{"status": "saved", "path": "output/result.json"}
```

---

## Modifications Architecturales

### HeadlessProvider (Human-in-the-Loop)

**Fichier:** `core/interaction/headless_provider.py`

```python
# Nouveaux attributs
_interactive: bool = False  # Opt-in pour backward compat
_interaction_timeout: float = 300.0  # 5 min
_pending_futures: Dict[str, asyncio.Future] = {}
_pending_interactions: Dict[str, dict] = {}

# Nouvelles méthodes
def get_pending_requests(self) -> List[dict]
def resolve_interaction(self, request_id: str, response: Any) -> bool

# Méthodes modifiées (ask, confirm, choose)
# - Génèrent un request_id unique
# - En mode interactive=True: attendent sur Future
# - En mode interactive=False: comportement legacy inchangé
```

**Pattern Async Future:**
```python
async def ask(self, prompt: str, ...):
    request_id = str(uuid4())[:8]

    if self._interactive:
        future = asyncio.Future()
        self._pending_futures[request_id] = future
        try:
            result = await asyncio.wait_for(future, timeout=self._interaction_timeout)
            return str(result)
        except asyncio.TimeoutError:
            return default or ""

    return default or ""  # Legacy behavior
```

---

### TelemetryBridge (State Persistence)

**Fichier:** `core/events/telemetry_bridge.py`

```python
STATE_TTL = 86400  # 24 hours

async def _persist_state(self, tenant_id, workspace_id, event_type, payload):
    """Persiste les événements étatiques dans Redis."""
    base_key = f"nexus:{tenant_id}:{workspace_id}:state"

    if event_type in (HIVE_PHASE_START, HIVE_STATE_CHANGE):
        await redis.set(f"{base_key}:phase", json.dumps(payload), ex=STATE_TTL)

    elif event_type == GRAPH_NODE_SPAWN:
        await redis.hset(f"{base_key}:nodes", node_id, json.dumps(payload))
        await redis.expire(f"{base_key}:nodes", STATE_TTL)

    elif event_type == LOG:
        await redis.lpush(f"{base_key}:logs", json.dumps(payload))
        await redis.ltrim(f"{base_key}:logs", 0, 99)  # Max 100 logs
```

**Appel depuis `emit()`:**
```python
async def emit(self, event_type, payload, ...):
    result = await bus.publish(event)
    await self._persist_state(tenant_id, workspace_id, event_type, payload)
    return result
```

---

### PathGuardian (File Security)

**Utilisé par:** `routes/files.py`

```python
MAX_FILE_SIZE = 1_000_000  # 1MB

async def read_file(path: str):
    guardian = PathGuardian(workspace, nexus_root)

    is_valid, resolved_path, message = guardian.validate_read(path)
    if not is_valid:
        raise HTTPException(403, f"Access denied: {message}")

    file_size = resolved_path.stat().st_size
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(413, f"File too large: {file_size} > {MAX_FILE_SIZE}")

    return resolved_path.read_text()
```

---

## Tests Implémentés

**Fichier:** `tests/v11/test_cortex.py` (15 tests)

| Classe | Tests |
|--------|-------|
| `TestHeadlessProviderInteractive` | 4 tests (backward compat, interactive mode) |
| `TestFileSizeLimit` | 2 tests (1MB constant, HTTP 413) |
| `TestStateSnapshot` | 1 test (pending_interactions) |
| `TestInteractionEndpoint` | 1 test (pending empty) |
| `TestWorkflowEndpoint` | 2 tests (start, not found) |
| `TestTelemetryBridgePersistence` | 2 tests (TTL 24h, method exists) |
| `TestCORTEXRoutes` | 1 test (routes registered) |
| `TestBackwardCompatibility` | 2 tests (ask/confirm defaults) |

---

## Backward Compatibility

| Élément | Comportement |
|---------|--------------|
| `HeadlessProvider()` | `interactive=False` par défaut -> comportement legacy |
| `TelemetryBridge.emit()` | Toujours fire-and-forget, `_persist_state()` silencieux si Redis absent |
| `.env.example` | `PROJECT_MEMORY_BACKEND=auto` (était `tfidf`, code utilisait déjà `auto`) |
| Endpoints existants | Inchangés (`/ws/stream`, `/health`, etc.) |

---

## Fichiers Créés/Modifiés

### Nouveaux (5)
```
core/api/cerebro/routes/state.py         # GET/DELETE /api/state/snapshot
core/api/cerebro/routes/interactions.py  # POST /{id}/reply, GET /pending
core/api/cerebro/routes/workflow.py      # POST /start, GET /{id}, POST /{id}/stop
core/api/cerebro/routes/files.py         # GET /content, POST /save, GET /info
tests/v11/test_cortex.py                 # 15 tests
```

### Modifiés (5)
```
.env.example                              # PROJECT_MEMORY_BACKEND=auto
core/interaction/headless_provider.py     # +120 LOC (interactive mode)
core/events/telemetry_bridge.py           # +60 LOC (_persist_state)
core/api/cerebro/app.py                   # +15 LOC (route registration)
core/api/cerebro/routes/__init__.py       # +6 LOC (exports)
```

---

## API Endpoints Summary

| Endpoint | Méthode | Description | Status Code |
|----------|---------|-------------|-------------|
| `/ws/stream` | WS | Event streaming (existant V10) | - |
| `/api/state/snapshot` | GET | État pour F5 recovery | 200, 503, 500 |
| `/api/state/snapshot` | DELETE | Clear state (test) | 200, 503 |
| `/api/interactions/{id}/reply` | POST | Répondre à un agent | 200, 400, 404 |
| `/api/interactions/pending` | GET | Liste interactions | 200 |
| `/api/workflow/start` | POST | Démarrer une tâche | 200 |
| `/api/workflow/{id}` | GET | Status d'une tâche | 200, 404 |
| `/api/workflow/{id}/stop` | POST | Arrêter une tâche | 200, 400, 404 |
| `/api/workflow/` | GET | Liste workflows | 200 |
| `/api/files/content` | GET | Lire un fichier (<=1MB) | 200, 403, 404, 413 |
| `/api/files/save` | POST | Écrire un fichier | 200, 403, 500 |
| `/api/files/info` | GET | Métadonnées fichier | 200, 403 |

---

## Next Steps (V11.6)

1. **CancellationToken Integration**: Workflow stop avec arrêt gracieux
2. **Redis Workflow Registry**: Pour multi-instance (actuellement in-memory)
3. **File Streaming**: Pour fichiers > 1MB (chunked response)
4. **WebSocket Reconnection**: Auto-reconnect avec state recovery

---

## Sources

- [Redis TTL Best Practices](https://medium.com/platform-engineer/redis-memory-optimization-techniques-best-practices-3cad22a5a986)
- [FastAPI File Size Limits](https://github.com/fastapi/fastapi/discussions/8167)
- [FastAPI BackgroundTasks](https://fastapi.tiangolo.com/tutorial/background-tasks/)
- [Human-in-Loop Patterns](https://github.com/langchain-ai/langgraph/discussions/2911)

---

**Commit:** `2e20dba` | **Branch:** NX | **Date:** 2025-12-15
