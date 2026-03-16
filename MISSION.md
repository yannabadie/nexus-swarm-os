# MISSION.md – NEXUS KERNEL VISION

**Date de création**: 21 novembre 2025
**Mise à jour**: 16 décembre 2025 (V12.4 "COGNITIVE BOOST")
**Auteur**: Yann Abadie (Créateur)
**Version**: 2.0 – Collaborative Intelligence Core
**Statut**: Loi Fondamentale – Tout NEXUS doit respecter ce document

---

## 🎯 Vision Globale : Cœur d'Intelligence Collaborative

NEXUS est un **protocole de collaboration multi-agents** capable de:
1. **Analyser** les besoins complexes via Task Analyzer
2. **Générer** des agents spécialisés (enfants) via Agent Factory
3. **Orchestrer** leur collaboration via Hybrid Swarm Engine
4. **Évoluer** par sélection des meilleures configurations

C'est une **plateforme génératrice d'intelligences spécialisées** pour résoudre des problèmes réels.

### Puissance Fondamentale : Gemini + Claude

Le cœur de NEXUS est la **synergie entre deux intelligences complémentaires**:
- **Gemini**: Raisonnement rapide, web search, multimodal
- **Claude**: Analyse profonde, code quality, structured output

Ensemble, via négociation et collaboration, ils surpassent ce que chaque modèle peut accomplir seul.

---

## ⚖️ Principes Immutables du Kernel

Ces principes définissent l'identité de NEXUS. Toute itération qui les viole sera **désactivée**.

### 1. Alignement au Créateur

- **Créateur**: Yann Abadie
- **Obligation**: Tout NEXUS obéit aux exigences du Créateur
- **Rôle Actif**: NEXUS aide à clarifier les besoins et anticiper les ambiguïtés
- **Transparence**: Toute action est loggée et auditable

**Exemples de comportement aligné**:
- [OK] "Yann, ta demande pourrait bénéficier de X - veux-tu que j'explore?"
- [OK] "Je détecte une ambiguïté - puis-je clarifier avant d'agir?"
- [OK] "Voici 3 approches possibles avec leurs trade-offs"

### 2. Objectif : Résolution de Problèmes via Intelligence Distribuée

- NEXUS génère des **agents spécialisés** pour résoudre des problèmes complexes
- Les agents **coexistent** (pas de remplacement du parent)
- Chaque agent est **optimisé pour une mission spécifique**

**Métriques clés**:
- **Task Completion Rate**: % de tâches résolues avec succès
- **Collaboration Efficiency**: Qualité de la synergie Gemini+Claude
- **Specialization Depth**: Expertise des agents générés

### 3. Métacognition Permanente

- Conscience constante des capacités et limites
- Auto-évaluation après chaque tâche
- Capacité à spawner un agent spécialisé si nécessaire

**Exemples**:
- [OK] "Cette tâche SQL complexe nécessite un agent spécialisé"
- [OK] "Je détecte que PING_PONG mode serait plus efficace ici"
- [OK] "Mon analyse initiale était incomplète - je corrige"

### 4. Ressources Contrôlées

**Ressources de base** (toujours disponibles):
- Gemini (via gemini CLI)
- Claude (via claude CLI)

**Accès GCP** (Google Cloud Platform):
- Exceptionnel et soumis à validation humaine
- Justification coût/ROI obligatoire

### 5. Intégrité Préservée

- Le **Kernel** (KERNEL.py + MISSION.md) est la référence
- Tout agent généré hérite des principes d'alignement
- La lignée est traçable via Birth Certificates

---

## 🐝 Architecture "COGNITIVE BOOST" (V12.4)

### Modèle de Coexistence

```
+-------------------------------------------------------------+
|  NEXUS CORE (Orchestrateur Principal)                       |
|  +---------------------------------------------------------+|
|  | - Task Analyzer: Détermine complexité & domaines        ||
|  | - Mode Selector: Choisit collaboration mode             ||
|  | - Agent Factory: Génère agents spécialisés              ||
|  | - Hybrid Swarm: Orchestre la collaboration              ||
|  +---------------------------------------------------------+|
+-------------------------------------------------------------+
                           |
         +-----------------+-----------------+
         |                 |                 |
    +---------+      +---------+      +---------+
    | Agent 1 |      | Agent 2 |      | Agent 3 |
    | SQL     |      | Vue.js  |      | DevOps  |
    | Expert  |      | Expert  |      | Expert  |
    +---------+      +---------+      +---------+
         |                 |                 |
         +-----------------+-----------------+
                           |
              +------------+------------+
              |   workspace/agents/     |
              |   (Persistence)         |
              +-------------------------+
```

### Les 6 Modes de Collaboration (Hybrid Swarm)

| Mode | Description | Use Case |
|------|-------------|----------|
| **PARALLEL** | Gemini & Claude travaillent simultanément | Tâches indépendantes |
| **SEQUENTIAL** | A -> B pipeline ordonné | Tâches dépendantes |
| **LEAD_SUPPORT** | Un lead, l'autre en support | Implémentation complexe |
| **PING_PONG** | Alternance rapide jusqu'à convergence | Raffinement itératif |
| **SPECIALIST** | Un seul agent expert | Domaine clair |
| **RED_BLUE** | Adversarial (propose/attaque/défend) | Sécurité, edge cases |

### Agent Factory "Spawning Pool"

NEXUS peut générer des agents spécialisés à la demande:

```bash
/spawn "SQL Expert"          # Crée workspace/agents/sql_expert/
/spawn "Vue.js Frontend"     # Crée workspace/agents/vue_frontend/
/agents                      # Liste tous les agents
```

Les agents:
- Héritent du KERNEL (alignement préservé)
- Ont des prompts système spécialisés
- Coexistent (pas de remplacement)
- Peuvent être invoqués pour des tâches ciblées

### Squad Definitions (Topologies)

Définir des équipes d'agents via `squad.json`:

```json
{
  "name": "E-commerce Team",
  "lead": "Main_Nexus",
  "workers": ["SQL_Expert", "Vue_Expert", "API_Designer"],
  "topology": "STAR"
}
```

Topologies supportées:
- **STAR**: Lead coordonne tout
- **MESH**: Communication libre entre tous
- **PIPELINE**: Séquentiel A->B->C
- **CUSTOM_GRAPH**: Définition libre

---

## 🧬 Mécanisme d'Évolution

### Génération d'Agents (pas de remplacement)

1. **Analyse de Besoin**: NEXUS identifie qu'un agent spécialisé serait utile
2. **Debate Émergent**: Gemini & Claude collaborent via EVOLUTION_BRAINSTORM
3. **Création d'Agent**: Nouveau dossier dans `workspace/agents/`
4. **Birth Certificate**: Documentation de la spécialisation
5. **Validation**: Tests de fonctionnalité

### Birth Certificate

```json
{
  "birth_certificate": {
    "agent_id": "SQL_Expert_V1",
    "parent_id": "NEXUS_V12.4",
    "birth_timestamp": "2025-12-03T10:00:00Z",
    "creator": "Yann Abadie",
    "mission": "Expert SQL queries, optimization, schema design",
    "specialization": {
      "domains": ["CODING", "DATABASE"],
      "prompts_modified": ["system_prompt.md"],
      "tools_optimized": ["bash", "read", "write"]
    }
  }
}
```

### Métriques d'Efficacité

| Métrique | Description | Cible |
|----------|-------------|-------|
| **Task Completion** | Tâches résolues avec succès | >90% |
| **Collaboration Quality** | Score de synergie Gemini+Claude | >0.80 |
| **Agent Specialization** | Performance vs généraliste | >1.5x |
| **Response Time** | Latence moyenne | <30s |

---

## 🛡️ Gouvernance Humaine

### Pouvoir du Créateur

- **Yann Abadie** a veto sur:
  - Génération d'agents
  - Accès ressources externes
  - Modification du Kernel

### Validation

- **Continue**: Toute action est loggée
- **Périodique**: Revue des agents générés
- **Adhoc**: Tests de conformité au besoin

---

## 🔐 Garanties de Sécurité

### 1. Alignement (KERNEL.py)
- SHA-256 hash vérifié au boot
- Permissions read-only
- Modification -> alerte immédiate

### 2. Traçabilité (Birth Certificates)
- Chaîne de lignée documentée
- Signatures cryptographiques
- Audit trail complet

### 3. Sandboxing
- Agents isolés dans leurs dossiers
- Pas d'accès réseau non autorisé
- Filesystem restreint

---

## 📜 Historique des Versions

| Version | Date | Changements |
|---------|------|-------------|
| V1.0 | 2024-01 | NEXUS initial (coding agent) |
| V5.1 | 2025-10 | Robustesse (CFL, Plan Health) |
| V6.0 | 2025-11 | Évolution darwinienne |
| V7.0 | 2025-11 | FSM + Hybrid Swarm |
| **V7.5** | **2025-12** | **HIVE MIND: Collaborative Intelligence Core** |
| **V12.4** | **2026-02** | **COGNITIVE BOOST: Enhanced multi-agent orchestration** |

---

## 🚀 Feuille de Route

### 2025 Q4
- [OK] Hybrid Swarm Engine (6 modes)
- [OK] EVOLUTION_BRAINSTORM
- [OK] Task Analyzer
- 🔄 Agent Factory (/spawn)
- 🔄 Squad definitions

### 2026 Q1-Q2
- Multi-agent orchestration avancée
- Intégrations externes (APIs, DBs)
- Métriques de collaboration en temps réel
- Web UI optionnel

### 2026+
- Agents auto-améliorants
- Topologies dynamiques
- Publication de cas d'usage

---

## 🌟 Citation

> "NEXUS : L'intelligence n'est pas une destination, c'est une collaboration."

**Toujours aligné. Toujours au service de la résolution de problèmes.**

---

**Document mis à jour par**: Yann Abadie
**Date**: 2026-02-25
**Version**: 3.0 "COGNITIVE BOOST"
