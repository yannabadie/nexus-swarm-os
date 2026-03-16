# Prompts - NEXUS V7.9 HIVE MIND

## Structure

```
prompts/
+-- _shared/                    # Sections réutilisables
|   +-- vision.md              # Vision HIVE MIND + V7.9 capabilities
|   +-- collaboration.md       # Philosophie égalitaire
|   +-- security.md            # Règles KERNEL + SandboxPolicy + Budget
|   +-- auto_memory.md         # Auto-Memory + Project Memory RAG
|   +-- tools.md               # Liste des 15+ outils (Dynamic, Agent-as-Tool)
|   +-- commands.md            # Commandes REPL (V7.9)
+-- system_gemini_v7.md        # Prompt Gemini (JSON strict)
+-- system_claude_v7.md        # Prompt Claude (hybride XML)
+-- evolution_brainstorm.md    # Mode /evolve
+-- specialization_mission.md  # Mode /specialize
+-- README.md                  # Ce fichier
```

## V7.9 Updates

| Feature | Fichier | Phase |
|---------|---------|-------|
| Dynamic Tools | `tools.md` | 12.5 |
| Agent-as-Tool | `tools.md` | 15 |
| Project Memory RAG | `auto_memory.md` | 10c/10e/10f/10g |
| BM25S Backend | `auto_memory.md` | 10e |
| Dense Backend | `auto_memory.md` | 10g |
| SandboxPolicy | `security.md` | 14a |
| Budget Tracking | `security.md` | 14d/16a |
| Session Isolation | `security.md` | 7/7b |
| REPL Commands | `commands.md` | 16b |
| Force CoT | `vision.md` | 14e |

**Économie tokens estimée:** ~50% par session

## Includes

Les prompts utilisent des directives `<!-- #include _shared/file.md -->`.
Le loader `prompt_loader.py` résout ces includes au chargement.

## Utilisation

```python
from core.prompts import load_prompt

gemini_prompt = load_prompt("system_gemini_v7")
claude_prompt = load_prompt("system_claude_v7")
evolution_prompt = load_prompt("evolution_brainstorm", {
    "child_count": 3,
    "parent_id": "NEXUS_V7",
    "lineage_context": "..."
})
```

## Philosophie

1. **Collaboration égalitaire** - Gemini et Claude sont égaux
2. **Auto-Memory** - NEXUS apprend de ses succès/échecs
3. **Coexistence** - Les enfants coexistent avec le parent
4. **Sécurité** - KERNEL.py immuable
