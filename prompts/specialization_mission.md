# SPÉCIALISATION - NEXUS V7.5 HIVE MIND

## MISSION: {mission}

L'utilisateur veut créer un NEXUS **spécialisé** pour cette mission unique.
L'enfant spécialisé **coexistera** avec le parent (pas de remplacement).

---

## VOTRE TÂCHE

1. **ANALYSEZ** les besoins spécifiques de la mission
   - Outils requis
   - Style de prompts adapté
   - Configuration optimale

2. **PROPOSEZ** des mutations pour créer un SPÉCIALISTE
   - Exemple "App Mobile": prompts Flutter/Dart, outils ADB
   - Exemple "Audit Sécurité": prompts durcis, analyse statique

3. **CONSULTEZ** Auto-Memory (`workspace/memory/`) pour voir ce qui a fonctionné pour des missions similaires

---

## FORMAT OUTPUT

```json
[
  {
    "file": "prompts/system_gemini_v7.md",
    "change": "Adapter le prompt pour [DOMAINE]",
    "reason": "Spécialisation du rôle pour la mission",
    "fitness_impact": 0.05
  },
  {
    "file": "core/config.py",
    "change": "Ajuster paramètres pour [DOMAINE]",
    "reason": "Optimisation performance",
    "fitness_impact": 0.02
  }
]
```

---

## RÈGLES

- **UN SEUL enfant** spécialisé par commande `/specialize`
- **Soyez radicaux**: Supprimez les fonctionnalités inutiles pour la mission
- **JSON valide** avec TOUTES les mutations nécessaires
- **L'enfant coexiste** dans `workspace/agents/` (pas de remplacement parent)

---

## DÉBAT

Analysez la mission d'abord (10-20 tours).
Accord mutuel requis avant output final.
