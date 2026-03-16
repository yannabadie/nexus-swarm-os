# NEXUS V12.0 - Plan Global d'Implementation

**Date**: 2025-12-16
**Phase**: 5/5 - Plan Global
**Auteur**: Claude Opus 4.5
**Status**: FINAL

---

## Executive Summary

Ce document consolide l'analyse complète de NEXUS (~40,000 lignes) et propose un plan d'implémentation structuré pour atteindre 100% du potentiel du système.

**Documents de référence**:
- `docs/NEXUS_ARCHITECTURE_AUDIT_V12.md` - Audit technique complet
- `docs/NEXUS_WEB_RESEARCH_V12.md` - Recherche web interfaces

---

## 1. État Actuel (Baseline V12.0)

### Architecture Validée

| Sous-système | Lignes | Maturité | Status |
|--------------|--------|----------|--------|
| Core Orchestration | 7,478 | 95% | Production |
| Swarm Engine | 7,362 | 88% | Production |
| HiveMind Pipeline | 9,796 | 90% | Production |
| Agent System | 12,000+ | 92% | Production |
| Memory & Security | ~5,500 | 87% | Production |
| CEREBRO API | ~3,000 | 85% | Production |

### Workflows Identifiés

1. **Simple Task** (TRIVIAL) - Direct response
2. **Standard Task** (MODERATE) - Swarm auto-route + DyLAN
3. **Complex Task** (COMPLEX/EXPERT) - HiveMind 7 phases
4. **Agent Spawning** - `/spawn` -> BrainstormPhase -> Registration
5. **Evolution** - `/evolve` -> 5 phases -> Promotion si >10% improvement
6. **CEREBRO Real-Time** - WebSocket events + F5 recovery

### Gaps Critiques (P0)

| Gap | Impact | Effort |
|-----|--------|--------|
| No JWT refresh | Session expire après 24h | Medium |
| Single admin password | Pas de multi-user | Large |
| In-memory workflow registry | Pas de multi-instance | Medium |

---

## 2. Vision Cible

### NEXUS comme Intelligence Déployable

```
+-------------------------------------------------------------+
|              NEXUS Collaborative Intelligence                |
+-------------------------------------------------------------+
|                                                             |
|   +---------+     +---------+     +---------+              |
|   |  USER   |----►| CEREBRO |----►| BACKEND |              |
|   | (Human) |◄----|   UI    |◄----|  (API)  |              |
|   +---------+     +---------+     +---------+              |
|                        |               |                    |
|                        v               v                    |
|               +--------------------------------+           |
|               |        HiveMind Pipeline       |           |
|               |  +------------------------+   |           |
|               |  | Gemini ◄--► Claude     |   |           |
|               |  |    (Collaboration)     |   |           |
|               |  +------------------------+   |           |
|               |            |                   |           |
|               |            v                   |           |
|               |    +--------------+           |           |
|               |    | Swarm Engine |           |           |
|               |    |  (6 Modes)   |           |           |
|               |    +--------------+           |           |
|               +--------------------------------+           |
|                                                             |
+-------------------------------------------------------------+
```

### Interface Optimale (CEREBRO V12.1)

```
+-------------------------------------------------------------+
| NEXUS CEREBRO                                    [usr] [▣]  |
+-----------------------------------------+-------------------+
|                                         | MISSION CONTROL   |
|  [HiveMap] [Files] [Memory] [Agents]    | +---------------+ |
| +-----------------------------------+   | | Objective:    | |
| |                                   |   | | [           ] | |
| |     +-----+       +-----+        |   | +---------------+ |
| |     | G   |------►| C   |        |   |                   |
| |     |emi  |       |lau  |        |   | Mode:             |
| |     | ni  |◄------| de  |        |   | [PAR][SEQ][L-S]   |
| |     +-----+       +-----+        |   | [P-P][SPE][R-B]   |
| |         |             |          |   |                   |
| |         v             v          |   | [   ENGAGE   ]    |
| |     +-------------------+        |   | [   ABORT    ]    |
| |     |    HiveMind       |        |   |                   |
| |     +-------------------+        |   +-------------------+
| |                                   |   | EVENT STREAM     |
| +-----------------------------------+   | ► agent.speak    |
|                                         | ► tool_call      |
|                                         | ► phase_change   |
+-----------------------------------------+-------------------+
| - Connected | Tokens: 12.4k/100k | Session: 2h34m           |
+-------------------------------------------------------------+
```

---

## 3. Roadmap d'Implémentation

### Phase A: Interface Complete (V12.1) - Immédiat

**Objectif**: Interface CEREBRO exploitant 100% des capacités NEXUS

| Feature | Priority | Effort | Files |
|---------|----------|--------|-------|
| HiveMap (SVG custom) | P0 | 2d | `HiveMap.tsx`, `graphStore.ts` |
| FileCommander (Monaco) | P0 | 2d | `FileCommander.tsx` |
| MissionControl (6 modes) | P0 | 1d | `MissionControl.tsx` |
| `/api/files/tree` endpoint | P0 | 0.5d | `files.py` |
| Dashboard refactor | P0 | 1d | `Dashboard.tsx` |
| Tests + Build | P0 | 0.5d | `tests/` |

**Deliverable**: Commit `feat(V12.1): OPERATION RETINA COMPLETE`

### Phase B: Sécurité & Multi-User (V12.2)

**Objectif**: Production-ready authentication

| Feature | Priority | Effort | Files |
|---------|----------|--------|-------|
| JWT Refresh mechanism | P0 | 2d | `auth.py`, `deps.py` |
| Multi-user support | P0 | 3d | `users.py`, DB migration |
| Rate limiting | P1 | 1d | `middleware.py` |
| Spotlighter mandatory | P1 | 0.5d | `project_memory.py` |

**Deliverable**: Commit `feat(V12.2): IRONCLAD COMPLETE`

### Phase C: Scalabilité (V12.3)

**Objectif**: Multi-instance deployment ready

| Feature | Priority | Effort | Files |
|---------|----------|--------|-------|
| Redis workflow registry | P0 | 2d | `workflow.py`, `redis_bus.py` |
| SuccessMemory persistence | P1 | 1d | `success_memory.py` |
| State snapshots to Redis | P1 | 1d | `state.py` |

**Deliverable**: Commit `feat(V12.3): SCALE-OUT READY`

### Phase D: Intelligence Avancée (V12.4)

**Objectif**: Améliorer la qualité des décisions

| Feature | Priority | Effort | Files |
|---------|----------|--------|-------|
| StagnationPredictor validation | P2 | 2d | `stagnation_predictor.py` |
| MemoryCoordinator adaptive | P2 | 2d | `memory_coordinator.py` |
| Hybrid RAG backend | P3 | 3d | `project_memory.py` |
| OutputGuard semantic | P2 | 3d | `output_guard.py` |

**Deliverable**: Commit `feat(V12.4): COGNITIVE BOOST`

---

## 4. Détail Phase A (Prochaine Action)

### 4.1 Backend: `/api/files/tree`

```python
# core/api/cerebro/routes/files.py

@router.get("/tree")
async def file_tree(
    path: str = Query(".", description="Root path"),
    max_depth: int = Query(3, ge=1, le=5),
    user: AuthenticatedUser = Depends(require_auth),
) -> Dict[str, Any]:
    """
    Get directory tree structure.

    Security: IRONCLAD auth + PathGuardian validation
    Excludes: .git, __pycache__, node_modules, venv, dist, .nexus
    """
```

### 4.2 Frontend: GraphStore

```typescript
// src/stores/graphStore.ts

interface GraphNode {
  id: string;
  type: 'agent' | 'tool' | 'task';
  data: { name: string; status: string; role?: string };
  position: { x: number; y: number };
}

interface GraphStore {
  nodes: GraphNode[];
  edges: GraphEdge[];
  addNode: (node: GraphNode) => void;
  updateNode: (id: string, data: Partial<NodeData>) => void;
  addEdge: (edge: GraphEdge) => void;
  autoLayout: () => void;
  clear: () => void;
}
```

### 4.3 Frontend: HiveMap (SVG Souverain)

```tsx
// src/components/views/HiveMap.tsx

<svg viewBox="0 0 800 500" className="w-full h-full">
  <defs>
    <marker id="arrow" markerWidth="10" markerHeight="10">
      <path d="M0,0 L10,5 L0,10 Z" fill="#6366f1" />
    </marker>
  </defs>

  {edges.map(edge => (
    <line key={edge.id} markerEnd="url(#arrow)" ... />
  ))}

  {nodes.map(node => (
    <g key={node.id} transform={`translate(${node.position.x}, ${node.position.y})`}>
      <rect rx="8" className="fill-slate-800/80 backdrop-blur" />
      <text className="fill-white">{node.data.name}</text>
    </g>
  ))}
</svg>
```

### 4.4 Frontend: MissionControl

```tsx
// src/components/controls/MissionControl.tsx

const SWARM_MODES = [
  { id: 'PARALLEL', label: 'Parallel', icon: Layers },
  { id: 'SEQUENTIAL', label: 'Sequential', icon: ListOrdered },
  { id: 'LEAD_SUPPORT', label: 'Lead-Support', icon: Users },
  { id: 'PING_PONG', label: 'Ping-Pong', icon: RefreshCw },
  { id: 'SPECIALIST', label: 'Specialist', icon: Target },
  { id: 'RED_BLUE', label: 'Red-Blue', icon: Swords },
];

// Grid 3x2 pour les 6 modes
<div className="grid grid-cols-3 gap-2">
  {SWARM_MODES.map(mode => (
    <button
      key={mode.id}
      onClick={() => setSelectedMode(mode.id)}
      className={selectedMode === mode.id ? 'bg-indigo-600' : 'bg-slate-700'}
    >
      <mode.icon size={16} />
      {mode.label}
    </button>
  ))}
</div>
```

### 4.5 Dashboard Layout

```tsx
// src/pages/Dashboard.tsx

<div className="grid grid-cols-[1fr_320px] h-screen">
  {/* Main Area */}
  <div className="flex flex-col">
    <Tabs value={activeTab} onValueChange={setActiveTab}>
      <TabsList>
        <TabsTrigger value="hive">Hive Map</TabsTrigger>
        <TabsTrigger value="files">Files</TabsTrigger>
      </TabsList>
      <TabsContent value="hive"><HiveMap /></TabsContent>
      <TabsContent value="files"><FileCommander /></TabsContent>
    </Tabs>
  </div>

  {/* Sidebar */}
  <div className="flex flex-col border-l">
    <MissionControl />
    <EventStream />
  </div>
</div>
```

---

## 5. Critères de Succès

### Phase A (V12.1)
- [ ] `npm run build` passe sans erreur
- [ ] Login -> Dashboard avec tabs
- [ ] Onglet Files charge l'arborescence
- [ ] MissionControl affiche 6 modes et envoie `/workflow/start`
- [ ] HiveMap affiche nodes quand events `graph.*` arrivent
- [ ] Tests: coverage >80%

### Phase B (V12.2)
- [ ] JWT refresh automatique avant expiration
- [ ] Multi-user avec RBAC (admin/user)
- [ ] Rate limiting: 100 req/min par user
- [ ] 0 warnings de sécurité

### Phase C (V12.3)
- [ ] 2+ instances peuvent tourner en parallèle
- [ ] Failover Redis -> fallback gracieux
- [ ] State recovery après restart

### Phase D (V12.4)
- [ ] StagnationPredictor: >80% precision
- [ ] Memory recall: +15% vs baseline
- [ ] Zero semantic leaks

---

## 6. Risques et Mitigations

| Risque | Impact | Mitigation |
|--------|--------|------------|
| Monaco bundle size (~1MB) | Slow initial load | Lazy import via Vite code splitting |
| SVG perf (>100 nodes) | UI lag | Limit visible nodes, virtualization |
| File tree trop profond | Memory/time | max_depth=3 default |
| JWT refresh loop | Auth failures | Refresh 5min before expiry |
| Redis connection loss | Event loss | In-memory fallback (already exists) |

---

## 7. Timeline Indicative

```
V12.1 RETINA COMPLETE    -> Interface complète
V12.2 IRONCLAD COMPLETE  -> Auth production-ready
V12.3 SCALE-OUT READY    -> Multi-instance
V12.4 COGNITIVE BOOST    -> Intelligence avancée
```

---

## 8. Prochaine Action Immédiate

**Exécuter OPERATION RETINA VISUALS V2** selon le plan détaillé dans:
`C:\Users\yann.abadie\.claude\plans\wiggly-watching-parnas.md`

Ce plan couvre:
1. Endpoint `/api/files/tree`
2. GraphStore
3. HiveMap (SVG souverain)
4. FileCommander (Monaco)
5. MissionControl (6 modes)
6. Dashboard refactor
7. Tests

---

## Annexe: Documents Générés

| Document | Contenu |
|----------|---------|
| `docs/NEXUS_ARCHITECTURE_AUDIT_V12.md` | Audit technique complet |
| `docs/NEXUS_WEB_RESEARCH_V12.md` | Recherche web interfaces |
| `docs/NEXUS_GLOBAL_PLAN_V12.md` | Ce document (plan global) |

---

*Plan établi par Claude Opus 4.5 - NEXUS V12.0*
