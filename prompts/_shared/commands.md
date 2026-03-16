## COMMANDES REPL V12.4

**L'utilisateur peut invoquer ces commandes. Tu peux les suggerer quand pertinent.**

---

## Collaboration (Swarm)

| Commande | Description |
|----------|-------------|
| `/swarm <task>` | Route tache via Hybrid Swarm Engine |
| `/swarm-status` | Mode actuel + metriques DyLAN |
| `/pool-stats` | Scores importance par agent |

---

## Evolution & Agents

| Commande | Description |
|----------|-------------|
| `/evolve [n]` | Creer n enfants (default: 3) |
| `/spawn <role>` | Creer agent specialise |
| `/agents` | Lister agents spawnes |
| `/specialize <mission>` | Creer spinoff specialise |
| `/review` | Review enfants pending |

---

## Memory & Monitoring

| Commande | Description |
|----------|-------------|
| `/memory status` | Stats Project Memory RAG + HybridBackend |
| `/memory index <dir>` | Forcer indexation |
| `/learn <file>` | Ajouter fichier a la memoire |
| `/forget <file>` | Retirer fichier de la memoire |
| `/memory reset` | Reinitialiser la memoire |
| `/budget` | Status budget quotidien |
| `/telemetry` | Rapport 7 jours |
| `/telemetry export` | Export CSV |

---

## Workspace

| Commande | Description |
|----------|-------------|
| `/workspace` | Status workspace actuel |
| `/workspace new` | Nouveau workspace (memory preservee) |
| `/bootstrap` | Analyse projet et genere NEXUS.md |

---

## System

| Commande | Description |
|----------|-------------|
| `/help` | Aide complete |
| `/tutorial` | Guide interactif (5 etapes) |
| `/quickstart` | Resume rapide |
| `/status` | Etat orchestrateur + FSM |
| `/doctor` | Diagnostics systeme |
| `/reset` | Reset etat (si ERROR) |
| `/chat` | Mode chat-only (pas d'outils) |
| `/save` | Sauvegarder session |
| `/history` | Historique sessions |

---

## CEREBRO Dashboard (V12.0+)

| Commande | Description |
|----------|-------------|
| `/cerebro start` | Demarrer le dashboard WebSocket |
| `/cerebro stop` | Arreter le dashboard |
| `/cerebro status` | Etat du serveur CEREBRO |

**Acces:** `http://localhost:8765` une fois demarre

---

## OpsView Dashboard (V12.1+)

| Commande | Description |
|----------|-------------|
| `/opsview` | Ouvrir cockpit production |
| `/metrics` | Afficher metriques Prometheus |
| `/metrics export` | Export metriques JSON |

---

## RBAC & Audit (V12.2+)

| Commande | Description |
|----------|-------------|
| `/rbac status` | Afficher role actuel |
| `/rbac permissions` | Lister permissions |
| `/audit tail [n]` | Dernieres n entrees audit |
| `/audit search <pattern>` | Rechercher dans audit |

---

## Multi-Instance (V12.3+)

| Commande | Description |
|----------|-------------|
| `/instances` | Lister instances actives |
| `/instance info` | Info instance courante |

---

## QUAND SUGGERER UNE COMMANDE

| Situation | Commande a suggerer |
|-----------|---------------------|
| Nouveau projet non analyse | `/bootstrap` |
| Fichier non indexe | `/learn <file>` ou `/memory index` |
| Budget faible | `/budget` pour verifier |
| Tache complexe multi-agents | `/swarm <task>` |
| Performance agents inconnue | `/pool-stats` |
| Besoin d'expert domaine | `/spawn <role>` |
| Dashboard temps reel | `/cerebro start` |
| Metriques production | `/opsview` ou `/metrics` |
| Verifier permissions | `/rbac status` |
| Audit actions | `/audit tail` |

**Note:** Les agents ne peuvent PAS executer ces commandes directement. Ils peuvent seulement les suggerer a l'utilisateur.
