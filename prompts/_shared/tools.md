## OUTILS DISPONIBLES V12.4 (21+ outils - TOUS accessibles aux deux agents)

### Fichiers & Code
| Outil | Description |
|-------|-------------|
| `read` | Lire fichier |
| `write` | Creer/ecraser fichier (workspace/) |
| `edit` | Search & replace |
| `list_dir` | Lister repertoire |

### Recherche
| Outil | Description |
|-------|-------------|
| `glob` | Trouver fichiers par pattern |
| `grep` | Chercher dans le code (regex) |
| `web_search` | Recherche Google (via Gemini CLI) |
| `web_fetch` | Recuperer contenu URL (**SSRF protected V12.4**) |

### Execution
| Outil | Description |
|-------|-------------|
| `bash` | Commandes shell (**SANDBOXED** - voir security.md) |
| `git` | Operations Git |

### Planification
| Outil | Description |
|-------|-------------|
| `todo_write` | Plan partage Gemini<->Claude |

---

## Dynamic Tools (V7.8)

| Outil | Description |
|-------|-------------|
| `create_tool` | Creer script Python dynamique (valide AST) |
| `run_dynamic_tool` | Executer outil cree |
| `delete_tool` | Supprimer outil dynamique |
| `list_dynamic_tools` | Lister outils disponibles |

**Exemple:** Creer un outil pour parser JSON complexe au lieu d'un bash one-liner.

```json
{
  "tool_name": "create_tool",
  "arguments": {
    "name": "json_parser",
    "description": "Parse complex JSON structures",
    "code": "def run(data):\n    import json\n    return json.loads(data)"
  }
}
```

---

## Agent Tools (V7.8)

| Outil | Description |
|-------|-------------|
| `agent_{name}` | Invoquer agent spawne comme outil |

**Agents disponibles:** Listes via `/agents` ou `list_dir workspace/agents/`

**Exemple:** Si `sql_expert` est spawne -> `agent_sql_expert` devient disponible.

```json
{
  "tool_name": "agent_sql_expert",
  "arguments": {"task": "Optimize this query for performance"}
}
```

---

## Swarm Delegation (V8.3.1)

| Outil | Description |
|-------|-------------|
| `swarm_delegate` | Deleguer une sous-tache au Swarm Engine |

**Modes disponibles:** `parallel`, `sequential`, `lead_support`, `ping_pong`, `specialist`, `red_blue`

**Arguments:**
- `task` (requis): Description de la sous-tache
- `mode` (optionnel, defaut: "specialist"): Mode de collaboration
- `phase` (optionnel): Phase HiveMind actuelle (pour validation guardrails)
- `context_categories` (optionnel): Categories de contexte a inclure

**Exemples:**

```json
{
  "tool_name": "swarm_delegate",
  "arguments": {
    "task": "Analyser auth.py et security.py en parallele",
    "mode": "parallel"
  }
}
```

```json
{
  "tool_name": "swarm_delegate",
  "arguments": {
    "task": "Debattre de l'approche d'authentification",
    "mode": "red_blue",
    "phase": "debate"
  }
}
```

**Anti-Recursion:** Limite a `MAX_SWARM_DEPTH = 2` pour eviter les boucles infinies.
- Niveau 0: Invocation directe -> OK
- Niveau 1: Sub-agent invoque swarm_delegate -> OK
- Niveau 2: Sub-sub-agent tente swarm_delegate -> BLOQUE

**Quand utiliser:**
- Taches pouvant beneficier de collaboration multi-agents
- Debates adversariaux (red_blue)
- Analyses paralleles independantes
- NE PAS utiliser pour taches simples (overhead inutile)
- NE PAS utiliser depuis un agent deja spawne par Swarm (risque recursion)

---

## web_fetch - SSRF Protection (V12.4)

L'outil `web_fetch` inclut une protection SSRF complete:

**Bloque automatiquement:**
- Hostnames internes (localhost, *.internal, *.local)
- IPs privees (10.x, 172.16-31.x, 192.168.x)
- IPs loopback (127.x)
- Cloud metadata (169.254.169.254)
- Ports non-standard (< 1024 sauf 80/443)
- Bypass attempts (hex/decimal/octal IP encoding)

**Exemple securise:**
```json
{
  "tool_name": "web_fetch",
  "arguments": {
    "url": "https://api.github.com/repos/owner/repo",
    "max_length": 10000
  }
}
```

**Erreurs SSRF:**
```
SSRF Protection: Blocked hostname: localhost
SSRF Protection: Private IP: 10.0.0.1
SSRF Protection: Cloud metadata endpoint
```

---

## Memory Tools (V12.4)

### HybridBackend RRF
Le RAG utilise maintenant une fusion Dense + BM25S avec Reciprocal Rank Fusion:
- Recall improvements must be supported by evaluation artifacts
- Semantic search ("auth" trouve "authentication")
- Fallback automatique si dense indisponible

### MemoryCoordinator
Poids adaptatifs par domaine avec EMA learning:
- Ajuste automatiquement les poids des sources de memoire
- Apprend des patterns de succes/echec
- Optimise le retrieval au fil du temps
