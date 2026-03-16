## AUTO-MEMORY V12.4 "COGNITIVE BOOST"

**NEXUS apprend de ses succes et echecs avec 4 systemes de memoire.**

---

## 1. Success/Failure Memory (V7.5)

- `workspace/memory/successes.jsonl` - Patterns qui ont fonctionne
- `workspace/memory/failures.jsonl` - Approches a eviter
- `workspace/memory/fitness_scores.json` - Scores par agent/mode

**Utilisation:**
- Si un mode Swarm a bien marche pour un type de tache, reutilise-le
- Si une approche a echoue, evite-la ou adapte-la
- Les scores de fitness guident le choix d'agent lead

---

## 2. Project Memory RAG (V7.9)

**NEXUS indexe automatiquement le code et la documentation du projet.**

### Backend Retrieval (Auto-select: Dense > BM25S > TF-IDF)
| Backend | Type | Performance | Disponibilite |
|---------|------|-------------|---------------|
| **Dense** | Semantic | +10% recall vs BM25S | Si `lancedb` + `sentence-transformers` |
| **BM25S** | Lexical | Improvement tracked in evidence artifacts | Si `bm25s` installe |
| **TF-IDF** | Lexical | Fallback fiable | Toujours (stdlib) |

### Dense Backend
- **Model**: `all-MiniLM-L6-v2` (22MB, 384 dim)
- **Storage**: `.nexus/lancedb/`
- **Feature**: Semantic search ("auth" trouve "authentication")

### Auto-injection
- Pour taches **MODERATE+**, le contexte RAG pertinent est auto-injecte
- Chunks de code/docs les plus pertinents a la query

### Stockage
- `.nexus/project_knowledge.json` - Index persistant (hors workspace/)
- Survit a `/workspace new`

---

## 3. HybridBackend RRF (V12.4)

**Fusion Dense + BM25S avec Reciprocal Rank Fusion.**

### Fonctionnement
```
Query -> Dense Search -> Top-K Dense Results
      -> BM25S Search -> Top-K Lexical Results
      -> RRF Fusion   -> Final Ranked Results
```

### Reciprocal Rank Fusion (RRF)
Score combine: `sum(1 / (k + rank_i))` pour chaque document

**Avantages:**
- Combine force semantique (Dense) + exacte (BM25S)
- Robuste aux variations de requete
- Fallback automatique si un backend echoue

### Configuration
```python
# Dans .nexus/config.json
{
  "memory": {
    "backend": "hybrid",
    "rrf_k": 60,  # Parametre RRF (default: 60)
    "dense_weight": 0.6,
    "bm25_weight": 0.4
  }
}
```

---

## 4. MemoryCoordinator (V12.4)

**Poids adaptatifs par domaine avec EMA learning.**

### Fonctionnement
- Chaque domaine (CODING, RESEARCH, DESIGN, etc.) a des poids de source
- Les poids s'ajustent automatiquement en fonction des succes/echecs
- Utilise Exponential Moving Average (EMA) pour lisser les mises a jour

### Domaines supportes
| Domaine | Description |
|---------|-------------|
| `CODING` | Implementation, debugging |
| `RESEARCH` | Web search, documentation |
| `DESIGN` | Architecture, UX |
| `TESTING` | Tests, validation |
| `SECURITY` | Audit, vulnerabilites |

### Sources de memoire
- `success_memory` - Patterns gagnants
- `failure_memory` - Patterns a eviter
- `project_rag` - Contexte projet
- `web_search` - Resultats web recents

### EMA Learning
```python
# Mise a jour apres chaque tache
new_weight = alpha * current_score + (1 - alpha) * old_weight
# alpha = 0.1 (learning rate)
```

---

## Commandes Utilisateur

| Commande | Description |
|----------|-------------|
| `/memory status` | Stats d'indexation (chunks, fichiers, backend) |
| `/memory index <dir>` | Forcer l'indexation d'un repertoire |
| `/learn <file>` | Ajouter fichier specifique a la memoire |
| `/forget <file>` | Retirer fichier de la memoire |
| `/memory reset` | Reinitialiser toute la memoire |

---

## Suggestions d'Utilisation

| Situation | Suggestion |
|-----------|------------|
| Nouveau module non indexe | `/learn <file>` ou `/memory index` |
| RAG retourne resultats non pertinents | `/memory reset` puis re-index |
| Tache echoue plusieurs fois | Verifier `failures.jsonl` pour patterns |
| Performance RAG degradee | `/memory status` pour diagnostiquer |
