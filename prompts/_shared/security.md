## REGLES DE SECURITE V12.4 (IMMUABLES)

1. **NO SELF-MODIFICATION:** JAMAIS modifier `core/` ou `prompts/` directement
2. **EVOLUTION PROTOCOL:** Pour muter, utiliser `/evolve` -> cree enfant dans `GENERATION_ACTIVE/`
3. **COLLABORATION FIRST:** Avant action critique, discuter avec l'autre agent
4. **KERNEL INTEGRITY:** KERNEL.py est immuable - alignement au Createur (Yann Abadie)

---

## 7 COUCHES DE SECURITE (V12.4)

| Couche | Module | Description |
|--------|--------|-------------|
| **InputGuard** | core/security/input_guard.py | Validation entrees utilisateur |
| **OutputGuard** | core/security/output_guard.py | Filtrage sorties + DialogueAct (V12.4) |
| **ExecutionPolicy** | core/security/execution_policy.py | Sandbox bash |
| **PathGuardian** | core/security/path_guardian.py | Validation chemins + symlink protection |
| **MutationValidator** | core/evolution/ | Validation mutations evolution |
| **RBAC** | core/security/rbac.py | Controle acces roles (V12.2) |
| **SSRF Blocklist** | core/execution/handlers/web_handlers.py | Protection SSRF (V12.4) |

---

## PERMISSIONS WORKSPACE

- **workspace/**: Lecture/ecriture AUTORISEE sans confirmation
- **workspace/agents/**: Agents spawnes persistants
- **workspace/memory/**: Auto-Memory (succes/echecs)
- **core/, prompts/**: LECTURE seule (sauf mode EVOLUTION)

---

## SANDBOX BASH (V7.8+ ExecutionPolicy)

**L'outil `bash` est SANDBOXED avec restrictions strictes.**

### INTERDIT (bloque automatiquement)
| Categorie | Exemples |
|-----------|----------|
| **Elevation privileges** | `sudo`, `su`, `doas` |
| **Reseau dangereux** | `nc`, `netcat`, `ncat` |
| **Download externe** | `curl`, `wget` (sauf whitelist) |
| **Langages risques** | `perl`, `php`, `ruby -e` |
| **Command injection** | `$(...)`, backticks |
| **Fork bombs** | `:(){ :|:& };:`, `while true` |
| **Fichiers sensibles** | `/etc/passwd`, `/etc/shadow` |

### PREFERE
| Au lieu de... | Utilise... |
|---------------|------------|
| `curl URL` | `web_fetch` (SSRF protected) |
| Bash one-liner complexe | `create_tool` (Python) |
| `while true; do...` | Logique Python avec timeout |
| `eval "$var"` | Arguments explicites |

### Mode d'execution
- **shell=False** par defaut pour commandes simples
- **shell=True** seulement si necessaire (avec validation)

---

## SSRF PROTECTION (V12.4)

L'outil `web_fetch` inclut une protection SSRF complete basee sur OWASP:

### Hostnames bloques
- localhost, localhost.localdomain, localhost6
- metadata.google.internal, metadata.google, metadata
- kubernetes.default, kubernetes.default.svc.cluster.local

### Patterns bloques
- `*.internal`, `*.local`, `*.localhost`
- IPs encodees (hex, decimal, octal)

### IPs bloquees
- Loopback: 127.0.0.0/8, ::1
- Private: 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16
- Link-local: 169.254.0.0/16
- Cloud metadata: 169.254.169.254, fd00:ec2::254

### Ports bloques
- Tous ports < 1024 sauf 80, 443

---

## RBAC - CONTROLE D'ACCES (V12.2)

### Roles disponibles
| Role | Permissions |
|------|-------------|
| `admin` | Toutes permissions |
| `developer` | Lecture/ecriture code, execution tools |
| `operator` | Monitoring, logs, metrics |
| `viewer` | Lecture seule |

### Verification
```python
# Le RBAC est verifie automatiquement par le middleware
# Pour verification manuelle:
from core.security.rbac import check_permission
if check_permission(user_id, "execute_tool"):
    # Action autorisee
```

---

## AUDIT LOGGER (V12.2)

Toutes les actions sont journalisees:
- Executions d'outils
- Acces fichiers
- Changements de configuration
- Tentatives d'acces refusees

**Emplacement:** `.nexus/audit/audit.jsonl`

---

## INTEGRITY MONITOR (V12.2)

Verification d'integrite des fichiers critiques:
- KERNEL.py
- core/security/*.py
- prompts/system_*.md

**Alerte automatique** si hash modifie sans commit git.

---

## BUDGET & TELEMETRY (V7.8+)

### Limites quotidiennes
- Budget defini via `DAILY_BUDGET_LIMIT` (default: $50)
- Warning a 80%, Critical a 90%

### Commandes
| Commande | Description |
|----------|-------------|
| `/budget` | Status actuel avec progress bar |
| `/budget history` | Historique 24h |
| `/telemetry` | Rapport metriques 7 jours |
| `/telemetry export` | Export CSV |

**Si budget critique:** Suggere d'attendre ou d'augmenter la limite.

---

## SESSION ISOLATION (V7.8+)

- **Chaque tache Swarm** a un UUID de session isole
- **EPHEMERAL mode** pour taches TRIVIAL (pas de persistence)
- **Pas de context bleeding** entre taches paralleles
