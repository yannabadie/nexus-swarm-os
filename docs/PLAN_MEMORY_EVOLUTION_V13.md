# PLAN: OPERATION MEMORIA UNIVERSALIS
## Evolution du Système RAG vers Multi-Format & Multi-Namespace

**Date**: 2025-12-16
**Version cible**: V13.0
**Auteur**: Claude Opus 4.5
**Statut**: PLAN APPROUVÉ EN ATTENTE

---

## URGENCE: README Destruction Recovery

### Constat Catastrophique

Le script `nexus-doc-generator` a **détruit** la documentation:

| Fichier | Avant | Après |
|---------|-------|-------|
| **README.md (racine)** | ~400 lignes, Quick Start, diagrammes, features | 40 lignes, "Subpackages: 16, Modules: 0" |
| **core/README.md** | Documentation architecture | Stats erronées + mermaid pollué |
| **46+ module READMEs** | Headers utiles | Pollution auto-générée |

### Contenu Perdu (README Racine)

```
PERDU:
- Banner/Logo NEXUS HIVE MIND
- Badges (Version, Python, Claude, Gemini, License)
- Vision statement "Collaborative Intelligence Core"
- Quick Start (pip install, python nexus7.py)
- Core Power diagram ASCII (Gemini+Claude symbiosis)
- V8.3 Features table (15+ phases documentées)
- Hybrid Swarm Engine (6 modes)
- Agent Factory (/spawn examples)
- Architecture diagram ASCII (FSM complet)
- Commands table (15+ commandes)
- Project Structure tree
- Documentation links table
- Requirements (Python 3.11+, CLIs)
- Principles (5 principes clés)
- Test Status (667 passed, 9/10)
- Author credit

RESTE:
- Liste de sous-dossiers
- "Aggregated Statistics: 0 modules, 0 LOC" (FAUX)
```

### Phase 0: README Restoration (CRITIQUE)

| Tâche | Effort | Priorité |
|-------|--------|----------|
| Restaurer README.md racine depuis backup historique | 1h | **P0 CRITIQUE** |
| Mettre à jour vers V12.4 (dates, features, versions) | 30 min | P0 |
| Nettoyer les 46 module READMEs (supprimer pollution) | 2h | P1 |
| Désactiver/corriger nexus-doc-generator | 30 min | P1 |
| Tests: vérifier tous les liens README | 30 min | P2 |

**Total Phase 0**: ~4.5h

### README Racine Cible (V12.4)

Le README restauré doit inclure:

1. **Header**: Banner, badges actualisés (V12.4, Python 3.11+)
2. **Vision**: "Collaborative Intelligence Core for Specialized Agent Generation"
3. **Quick Start**: pip install + python nexus7.py
4. **Core Power**: Diagramme Gemini 3 Pro + Claude Opus 4.5
5. **V12.4 Features**:
   - V12.2 IRONCLAD (Security)
   - V12.3 SCALE-OUT (Multi-instance)
   - V12.4 COGNITIVE BOOST (StagnationPredictor, HybridBackend RRF)
6. **Architecture V12**: FSM + HiveMind + Swarm + CEREBRO
7. **Commands**: Table mise à jour avec /cerebro, /opsview
8. **Project Structure**: Inclure interface/ui/cerebro
9. **Documentation**: Liens vers docs/
10. **Test Status**: 1200+ tests
11. **Security**: 7 couches (RBAC, SSRF, etc.)

---

## Contexte & Vision

### Problème Actuel

NEXUS est conçu comme un **outil généraliste d'intelligence collaborative**, pas seulement un outil de programmation. Cependant:

| Limitation | Impact |
|------------|--------|
| **7 types de fichiers seulement** | .py, .md, .txt, .yaml, .yml, .json, .toml - pas de PDF, images, audio |
| **RAG global unique** | Pas de séparation Project vs Agent |
| **Invisible en UI** | CEREBRO n'expose pas le système mémoire |
| **CLI uniquement** | `/learn`, `/rag` en ligne de commande, pas de drag & drop |

### Vision V13

```
+-----------------------------------------------------------------+
|  NEXUS V13 - UNIVERSAL KNOWLEDGE LAYER                          |
+-----------------------------------------------------------------+
|                                                                  |
|  +----------------------------------------------------------+   |
|  |                    DATA INGESTION                         |   |
|  |  +-----+ +-----+ +-----+ +-----+ +-----+ +-----+        |   |
|  |  | PDF | |DOCX | | IMG | |AUDIO| | URL | |CODE |        |   |
|  |  +--+--+ +--+--+ +--+--+ +--+--+ +--+--+ +--+--+        |   |
|  |     +-------+-------+-------+-------+-------+             |   |
|  |                        |                                  |   |
|  |                  +-----v-----+                            |   |
|  |                  |  DOCLING  |  (Universal Parser)        |   |
|  |                  +-----+-----+                            |   |
|  +------------------------+---------------------------------+   |
|                           |                                      |
|  +------------------------v---------------------------------+   |
|  |                    RAG NAMESPACES                         |   |
|  |  +-----------------+    +-----------------------------+  |   |
|  |  |  PROJECT RAG    |    |      AGENT RAGs             |  |   |
|  |  |  (Global)       |    |  +-----+ +-----+ +-----+   |  |   |
|  |  |  - All ingested |    |  |Agent| |Agent| |Agent|   |  |   |
|  |  |    documents    |    |  |  A  | |  B  | |  C  |   |  |   |
|  |  |  - Shared by    |    |  |     | |     | |     |   |  |   |
|  |  |    all agents   |    |  |Scope| |Scope| |Scope|   |  |   |
|  |  +-----------------+    |  +-----+ +-----+ +-----+   |  |   |
|  |                         +-----------------------------+  |   |
|  +----------------------------------------------------------+   |
|                                                                  |
|  +----------------------------------------------------------+   |
|  |                    CEREBRO UI                             |   |
|  |  +----------------------------------------------------+  |   |
|  |  |  MEMORY PANEL                                       |  |   |
|  |  |  +--------------------------------------------+    |  |   |
|  |  |  |  [Drop files here or click to browse]      |    |  |   |
|  |  |  |  Supports: PDF, DOCX, Images, Audio, URLs  |    |  |   |
|  |  |  +--------------------------------------------+    |  |   |
|  |  |                                                     |  |   |
|  |  |  Indexed: 142 docs | 3,456 chunks | Last: 5min ago |  |   |
|  |  |  ████████████████░░░░ 80% coverage                  |  |   |
|  |  |                                                     |  |   |
|  |  |  [Project RAG v] [+ Create Agent RAG]               |  |   |
|  |  +----------------------------------------------------+  |   |
|  +----------------------------------------------------------+   |
+-----------------------------------------------------------------+
```

---

## Architecture Technique

### 1. Multi-Format Ingestion via Docling

**Choix**: [Docling](https://github.com/docling-project/docling) (IBM/LF AI Foundation)

| Avantage | Détail |
|----------|--------|
| **Formats supportés** | PDF, DOCX, PPTX, XLSX, HTML, images (PNG, JPEG, TIFF), audio (WAV, MP3) |
| **100% local** | Aucune API cloud requise |
| **MIT License** | Open source, libre d'usage |
| **5 lignes de code** | Intégration minimale |
| **Markdown output** | Compatible avec notre chunking existant |

**Installation**:
```bash
pip install docling
```

**Intégration dans ProjectMemory**:
```python
# core/memory/ingestors/__init__.py (NOUVEAU)

from docling.document_converter import DocumentConverter

class UniversalIngestor:
    """Ingestion multi-format via Docling."""

    SUPPORTED = [".pdf", ".docx", ".pptx", ".xlsx", ".html",
                 ".png", ".jpg", ".jpeg", ".tiff", ".wav", ".mp3"]

    def __init__(self):
        self.converter = DocumentConverter()

    def ingest(self, path: Path) -> str:
        """Convertit n'importe quel format en Markdown."""
        result = self.converter.convert(str(path))
        return result.document.export_to_markdown()
```

### 2. Architecture Multi-Namespace

**Concept**: Séparer Project RAG (global) et Agent RAGs (scoped)

```
.nexus/
+-- project_knowledge.json      # Project RAG (existant)
+-- lancedb/
|   +-- project/                # Project vectors
+-- agent_rags/                 # NOUVEAU
|   +-- security_expert/
|   |   +-- knowledge.json
|   |   +-- lancedb/
|   +-- code_reviewer/
|   |   +-- knowledge.json
|   |   +-- lancedb/
|   +-- {agent_name}/
|       +-- ...
+-- rag_config.json             # NOUVEAU - namespace config
```

**API**:
```python
# core/memory/namespace_manager.py (NOUVEAU)

class RAGNamespaceManager:
    """Gère les namespaces RAG (Project + Agents)."""

    def get_project_rag(self) -> ProjectMemory:
        """RAG global du projet."""
        return self._project_rag

    def get_agent_rag(self, agent_name: str) -> ProjectMemory:
        """RAG dédié à un agent spécifique."""
        if agent_name not in self._agent_rags:
            self._create_agent_namespace(agent_name)
        return self._agent_rags[agent_name]

    def list_namespaces(self) -> List[str]:
        """Liste tous les namespaces disponibles."""
        return ["project"] + list(self._agent_rags.keys())

    def merge_to_project(self, agent_name: str) -> None:
        """Fusionne un RAG agent vers le Project RAG."""
        ...
```

**Utilisation par les agents**:
```python
# Dans un agent spawné
agent_rag = namespace_manager.get_agent_rag("security_expert")
agent_rag.ingest(Path("security_guidelines.pdf"))

# L'agent utilise son propre contexte
context = agent_rag.retrieve("OWASP top 10")
```

### 3. UI CEREBRO - Memory Panel

**Nouveau composant**: `interface/ui/cerebro/src/components/MemoryPanel.tsx`

```tsx
// MemoryPanel.tsx

import { useState, useCallback } from 'react';
import { useDropzone } from 'react-dropzone';
import { toast } from 'sonner';

interface MemoryStats {
  indexed_files: number;
  total_chunks: number;
  last_update: string;
  coverage_percent: number;
  namespaces: string[];
}

export function MemoryPanel() {
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [namespace, setNamespace] = useState('project');
  const [uploading, setUploading] = useState(false);

  const onDrop = useCallback(async (files: File[]) => {
    setUploading(true);
    const formData = new FormData();
    files.forEach(f => formData.append('files', f));
    formData.append('namespace', namespace);

    try {
      const res = await fetch('/api/memory/ingest', {
        method: 'POST',
        body: formData,
      });
      if (res.ok) {
        toast.success(`${files.length} fichiers ingérés`);
        refreshStats();
      } else {
        toast.error('Erreur d\'ingestion');
      }
    } finally {
      setUploading(false);
    }
  }, [namespace]);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'application/pdf': ['.pdf'],
      'application/vnd.openxmlformats-officedocument.*': ['.docx', '.pptx', '.xlsx'],
      'image/*': ['.png', '.jpg', '.jpeg', '.tiff'],
      'audio/*': ['.wav', '.mp3'],
      'text/*': ['.txt', '.md', '.py', '.json'],
    }
  });

  return (
    <div className="bg-nexus-dark rounded-lg border border-gray-700 p-4">
      <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
        <span className="text-2xl">🧠</span>
        Project Memory
      </h2>

      {/* Drop Zone */}
      <div
        {...getRootProps()}
        className={`border-2 border-dashed rounded-lg p-6 text-center cursor-pointer
          transition-colors ${isDragActive
            ? 'border-secondary bg-secondary/10'
            : 'border-gray-600 hover:border-gray-500'}`}
      >
        <input {...getInputProps()} />
        {uploading ? (
          <div className="flex items-center justify-center gap-2">
            <div className="animate-spin h-5 w-5 border-2 border-secondary border-t-transparent rounded-full" />
            <span className="text-gray-400">Ingestion en cours...</span>
          </div>
        ) : isDragActive ? (
          <p className="text-secondary">Déposez les fichiers ici...</p>
        ) : (
          <div>
            <p className="text-gray-400">Glissez-déposez des fichiers ici</p>
            <p className="text-gray-500 text-sm mt-1">
              PDF, DOCX, Images, Audio, Code
            </p>
          </div>
        )}
      </div>

      {/* Stats */}
      {stats && (
        <div className="mt-4 space-y-2">
          <div className="flex justify-between text-sm">
            <span className="text-gray-400">Fichiers indexés</span>
            <span className="text-white">{stats.indexed_files}</span>
          </div>
          <div className="flex justify-between text-sm">
            <span className="text-gray-400">Chunks</span>
            <span className="text-white">{stats.total_chunks}</span>
          </div>
          <div className="w-full bg-gray-700 rounded-full h-2 mt-2">
            <div
              className="bg-secondary h-2 rounded-full"
              style={{ width: `${stats.coverage_percent}%` }}
            />
          </div>
        </div>
      )}

      {/* Namespace Selector */}
      <div className="mt-4 flex gap-2">
        <select
          value={namespace}
          onChange={(e) => setNamespace(e.target.value)}
          className="flex-1 bg-gray-800 text-white rounded px-3 py-2 text-sm"
        >
          <option value="project">Project RAG</option>
          {stats?.namespaces.filter(n => n !== 'project').map(ns => (
            <option key={ns} value={ns}>{ns}</option>
          ))}
        </select>
        <button
          className="px-3 py-2 bg-secondary text-white rounded text-sm"
          onClick={() => {/* Create agent RAG modal */}}
        >
          + Agent RAG
        </button>
      </div>
    </div>
  );
}
```

### 4. API Backend pour Ingestion

**Nouveau endpoint**: `core/api/cerebro/routes/memory.py`

```python
# memory.py

from fastapi import APIRouter, UploadFile, File, Form
from typing import List
import tempfile
from pathlib import Path

router = APIRouter(prefix="/memory", tags=["memory"])

@router.post("/ingest")
async def ingest_files(
    files: List[UploadFile] = File(...),
    namespace: str = Form("project")
):
    """Ingère des fichiers dans le RAG spécifié."""
    from core.memory.namespace_manager import get_namespace_manager
    from core.memory.ingestors import UniversalIngestor

    manager = get_namespace_manager()
    ingestor = UniversalIngestor()
    rag = manager.get_agent_rag(namespace) if namespace != "project" else manager.get_project_rag()

    results = []
    for file in files:
        # Save temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename).suffix) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = Path(tmp.name)

        try:
            # Convert to markdown via Docling
            markdown = ingestor.ingest(tmp_path)

            # Index in RAG
            rag.index_text(markdown, source=file.filename)
            results.append({"file": file.filename, "status": "ok"})
        except Exception as e:
            results.append({"file": file.filename, "status": "error", "error": str(e)})
        finally:
            tmp_path.unlink()

    return {"results": results, "indexed": len([r for r in results if r["status"] == "ok"])}

@router.get("/stats")
async def get_memory_stats(namespace: str = "project"):
    """Statistiques du RAG spécifié."""
    from core.memory.namespace_manager import get_namespace_manager

    manager = get_namespace_manager()
    rag = manager.get_agent_rag(namespace) if namespace != "project" else manager.get_project_rag()

    return {
        "indexed_files": rag.get_indexed_file_count(),
        "total_chunks": len(rag.chunks),
        "last_update": rag.last_update.isoformat() if rag.last_update else None,
        "coverage_percent": rag.get_coverage_percent(),
        "namespaces": manager.list_namespaces(),
        "backend": rag.get_backend_info()["backend"]
    }

@router.get("/namespaces")
async def list_namespaces():
    """Liste tous les namespaces RAG."""
    from core.memory.namespace_manager import get_namespace_manager
    return {"namespaces": get_namespace_manager().list_namespaces()}

@router.post("/namespaces")
async def create_namespace(name: str):
    """Crée un nouveau namespace pour un agent."""
    from core.memory.namespace_manager import get_namespace_manager
    get_namespace_manager().create_agent_namespace(name)
    return {"status": "created", "namespace": name}

@router.delete("/namespaces/{name}")
async def delete_namespace(name: str):
    """Supprime un namespace agent."""
    if name == "project":
        raise HTTPException(400, "Cannot delete project namespace")
    from core.memory.namespace_manager import get_namespace_manager
    get_namespace_manager().delete_agent_namespace(name)
    return {"status": "deleted", "namespace": name}
```

---

## Plan d'Implémentation

### Phase 1: Multi-Format Ingestion (Priorité HAUTE)

| Tâche | Effort | Fichiers |
|-------|--------|----------|
| Installer Docling | 5 min | requirements.txt |
| Créer UniversalIngestor | 1h | core/memory/ingestors/ |
| Intégrer dans ProjectMemory | 30 min | core/memory/project_memory.py |
| Tests unitaires | 1h | tests/memory/test_ingestors.py |

**Dépendance**:
```
docling>=2.65.0
```

### Phase 2: Multi-Namespace (Priorité HAUTE)

| Tâche | Effort | Fichiers |
|-------|--------|----------|
| RAGNamespaceManager | 2h | core/memory/namespace_manager.py |
| Storage structure | 30 min | .nexus/agent_rags/ |
| Factory integration | 30 min | core/factory.py |
| Agent spawn integration | 1h | core/evolution/spawn.py |
| Tests | 1h | tests/memory/test_namespaces.py |

### Phase 3: API Backend (Priorité MOYENNE)

| Tâche | Effort | Fichiers |
|-------|--------|----------|
| Routes memory.py | 1h | core/api/cerebro/routes/memory.py |
| File upload handling | 30 min | dependencies |
| Register routes | 15 min | core/api/cerebro/__init__.py |
| Tests E2E | 1h | tests/api/test_memory_routes.py |

### Phase 4: CEREBRO UI (Priorité MOYENNE)

| Tâche | Effort | Fichiers |
|-------|--------|----------|
| Install react-dropzone | 5 min | package.json |
| MemoryPanel.tsx | 2h | src/components/MemoryPanel.tsx |
| Intégration layout | 30 min | src/pages/Dashboard.tsx |
| API client | 30 min | src/services/memoryApi.ts |
| Tests Vitest | 1h | src/components/__tests__/ |

### Phase 5: OPERATION POLISH (Priorité BASSE - déjà documenté)

| Tâche | Effort |
|-------|--------|
| Auto-scroll EventStream | 15 min |
| Sonner toasts | 30 min |
| Markdown rendering | 1h |
| CLEAR BOARD button | 15 min |

---

## Dépendances Totales

### Backend (requirements.txt additions)
```
docling>=2.65.0
python-multipart>=0.0.9  # Pour FastAPI file uploads
```

### Frontend (package.json additions)
```json
{
  "dependencies": {
    "react-dropzone": "^14.3.5",
    "react-markdown": "^9.1.0",
    "rehype-highlight": "^7.0.0",
    "sonner": "^1.7.0"
  }
}
```

---

## Effort Total Estimé

| Phase | Effort | Priorité |
|-------|--------|----------|
| **Phase 0: README Recovery** | **4.5h** | **P0 CRITIQUE** |
| Phase 1: Multi-Format | 2.5h | HAUTE |
| Phase 2: Multi-Namespace | 5h | HAUTE |
| Phase 3: API Backend | 2.75h | MOYENNE |
| Phase 4: CEREBRO UI | 4h | MOYENNE |
| Phase 5: POLISH | 2h | BASSE |
| **TOTAL** | **~20.5h** | |

---

## Risques & Mitigations

| Risque | Probabilité | Impact | Mitigation |
|--------|-------------|--------|------------|
| Docling dépendances lourdes | Moyenne | Moyen | Installation optionnelle, fallback text-only |
| Performance multi-namespace | Basse | Moyen | Lazy loading, cache LRU |
| Breaking changes API | Basse | Haut | Versioning API, backward compat |
| Bundle size frontend | Moyenne | Bas | Lazy loading react-dropzone |

---

## Métriques de Succès

| Métrique | Cible |
|----------|-------|
| Formats supportés | 15+ (vs 7 actuel) |
| Namespaces créables | Illimité |
| UI Memory visible | 100% des pages CEREBRO |
| Drag & drop fonctionnel | Oui |
| Tests coverage | >80% |

---

## Prochaines Actions

1. **[P0 CRITIQUE] Restaurer README.md racine** depuis contenu historique fourni
2. **[P0] Mettre à jour vers V12.4** (versions, features, diagrammes)
3. **[P1] Nettoyer les 46 module READMEs** pollués par nexus-doc-generator
4. **Validation du plan** par le conseiller
5. **Installation Docling** et tests locaux
6. **Implémentation Phase 1+2** (Multi-Format + Multi-Namespace)
7. **Implémentation Phase 3+4** (API + UI)
8. **Phase 5** (OPERATION POLISH) en parallèle

---

## Sources

- [Docling GitHub](https://github.com/docling-project/docling)
- [Docling PyPI](https://pypi.org/project/docling/)
- [LanceDB Multi-tenant](https://lancedb.github.io/lancedb/)
- [Multi-tenant RAG Best Practices](https://www.thenile.dev/blog/multi-tenant-rag)
- [React Dropzone](https://react-dropzone.js.org/)
- [Filestack Drag & Drop UX](https://blog.filestack.com/building-modern-drag-and-drop-upload-ui/)

---

*Plan créé le 2025-12-16 - NEXUS V13.0 "MEMORIA UNIVERSALIS"*
