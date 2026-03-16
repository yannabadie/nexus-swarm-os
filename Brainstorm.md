Je ne sais pas quoi vendre, jai besoin de toi pour décider et ordonner, prends le temps de faire des recherches poussées, des projections des scnéraios, réfléchis étapes par étapes, si le chemin n'est pas le bon trouves en un autre
Thought for 16m 32s

Tu n’as pas un problème “tech” ici, tu as un problème de positionnement + trajectoire. Ton repo est devenu suffisamment stable (CI, quickstart, extras, CLI, MCP) pour que la vraie question soit : quel produit minimum tu peux livrer qui a une chance d’être adopté et payé — sans replonger dans “l’OS agentique universel”.

 

Je vais trancher avec une logique simple : ce qui gagne en 2026, ce n’est pas l’orchestration, c’est la distribution + la confiance + la gouvernance + les preuves.

1) Ce qui a changé en 2026 (marché)
Les agents sont déjà en prod, mais la douleur principale est la qualité et l’observabilité

LangChain (enquête 1300+ personnes) indique qu’en entrant en 2026 :

~57% ont des agents en production

la qualité est un frein majeur (~32%)

l’observabilité est devenue “table stakes” (~89%)

l’usage multi-modèles est la norme (OpenAI, Gemini, Claude, OSS)

➡️ Donc “un framework de plus” ne résout pas la douleur #1. Les équipes veulent : prouver, debugger, mesurer, contrôler.

MCP est en train de devenir l’infrastructure commune

Deux signaux très forts :

MCP est passé sous gouvernance neutre (Linux Foundation / AAIF).
Linux Foundation + Anthropic + OpenAI annoncent l’AAIF, et Anthropic donne MCP à la fondation (OpenAI donne AGENTS.md).

La distribution MCP est en train de se structurer

GitHub a lancé une MCP Registry comme “home base” de découverte des serveurs MCP.

VS Code / Copilot a MCP en GA (prod), avec une couche “policy” côté orgs.

Le registry MCP officiel supporte PyPI / npm / NuGet / Docker mais est encore en preview (risque de breaking changes).

➡️ Si tu construis un outil MCP-first, tu rides une vague de distribution réelle.

MCP Apps = le chaînon manquant “UI” (très important pour toi)

Le blog MCP annonce MCP Apps : un dev d’outil peut livrer une expérience UI sans écrire du code client spécifique, avec support annoncé dans Claude (web+desktop), Goose, VS Code Insiders, et “ChatGPT starting this week”.

 

➡️ Ça veut dire que ton “Cerebro UI” peut être repensé comme MCP App (plus simple à distribuer, moins de front à maintenir).

La compétition “framework” est devenue brutale

Microsoft pousse Agent Framework comme successeur direct AutoGen + Semantic Kernel, avec state management, middleware, telemetry, workflows, features enterprise.

OpenAI a son Agents SDK (outils, handoffs, streaming, traces).

LangGraph, CrewAI, etc. dominent déjà l’esprit des devs et les budgets tooling.

➡️ Construire/vendre “NEXUS = framework agentique” te met dans la catégorie la plus saturée.

2) Ce que NEXUS a déjà de vendable (assets concrets)

Tu as déjà un “produit wedge” naturel, écrit noir sur blanc :

Research CLI + Evidence Pack : mode mock (zéro clé), outputs artefacts (report.md, sources.json, graph, etc.).

MCP server : nexus-mcp, installable via extras, configuré dans claude_desktop_config.json.

API + streaming (Cerebro) : possible, mais optionnel, et probablement trop lourd à vendre “as-is”.

➡️ Ton repo dit déjà lui‑même ce que tu devrais vendre : Evidence Pack + MCP. C’est cohérent avec la demande marché (qualité/observabilité).

3) Les 5 choses que tu pourrais “vendre” (et ma note honnête)

Je vais scorer selon : Différenciation, urgence marché, distribution, effort, probabilité de paiement (1–5).

Option A — Vendre NEXUS comme framework multi-agents

Différenciation : 2 (plein de frameworks + gros acteurs)

Urgence : 2

Distribution : 2

Effort : 1 (énorme)

Paiement : 2
➡️ Score global faible. Risque : tu passes 12 mois à courir derrière Agent Framework / LangGraph / Agents SDK.

Option B — Vendre “Evidence Pack” (CLI + MCP) : sorties traçables + manifest + preuves

Différenciation : 4 (peu de projets vendent les artefacts vérifiables comme produit central)

Urgence : 5 (qualité/observabilité sont les pains #1)

Distribution : 5 (MCP + registries + IDEs)

Effort : 4 (tu as déjà la base)

Paiement : 3–4 (très payant en B2B si tu apportes contrôle/policy/logs)
➡️ Meilleur ratio impact/effort.

Option C — Vendre un SaaS “Evidence Vault / Governance”

Stockage, audit trails, policy, redaction, multi-tenant, SSO.

Différenciation : 3–4

Urgence : 5 (gouvernance devient critique dans les entreprises)

Distribution : 3

Effort : 1–2 (lourd)

Paiement : 5 (si tu signes 1–2 clients)
➡️ Bon... mais à faire après avoir une wedge adoptée, sinon tu construis du vide.

Option D — Vendre une UI “Cerebro” comme produit

Différenciation : 3

Urgence : 2–3

Distribution : 2
➡️ Mauvais canal. MAIS : si tu la transforms en MCP App, elle redevient intéressante.

Option E — Vendre du service (audits, mise en place agents, gouvernance) + outil OSS

Différenciation : dépend de toi

Urgence : 4–5

Distribution : toi (réseau)

Effort : 4 (monétisable vite)

Paiement : 4
➡️ Très pragmatique pour financer B/C.

4) Décision que je te recommande
Ce que tu vends (ordre strict)

Produit #1 (wedge, OSS + pro)
“NEXUS Evidence Pack” = transformer une question en livrables vérifiables (report + sources + trace + graph + metrics + manifest).
Tu le distribues via :

CLI (nexus-research)

MCP server (nexus-mcp) branchable dans Claude Desktop/VS Code/Copilot etc.

Produit #2 (pro, payant)
“NEXUS Evidence Pack Pro” = ce que les équipes paient réellement :

policy (ce que l’agent a le droit de faire)

redaction / secrets handling

cost caps / budgets

export vers PR, Jira, Confluence

signature/immutabilité des artefacts + conservation

Produit #3 (différenciation UI)
“Evidence Review App” en MCP Apps : UI interactive pour explorer trace, sources, graph, budgets, décisions — utilisable cross-clients.

Monétisation immédiate (dès maintenant)
Du service packagé (3 offres) :

“Audit agentique + blueprint” (2–5 jours)

“Mise en place Evidence Pack en CI + PR review” (1–2 semaines)

“Gouvernance agents (policies + logs + incident playbook)” (2–4 semaines)

Ça finance la construction du Pro.

5) Projections réalistes (6 mois)

Je vais être transparent : les chiffres sont des scénarios, pas une promesse.

Hypothèses raisonnables

Ton acquisition principale vient de la distribution MCP + GitHub/VS Code + bouche à oreille.

Conversion OSS -> payant est souvent basse (0,5–3% mentionné dans des analyses “open source SaaS”).

B2B est plus lent, mais panier moyen plus élevé.

Scénario pessimiste (mais plausible)

6 mois : 500–2000 installs/downloads

0–2 équipes payantes (ou 1–2 missions de service)

Résultat : tu gardes l’OSS comme portfolio + outil perso, tu pivotes vers consulting.

Scénario base case

6 mois : 3000–8000 installs

0,5% conversion team à 200–400€/mois -> 15–40 teams (si tu as un vrai “Pro” utile)

3–6 missions de service

Résultat : 3k–15k€ MRR possible + cash de service (mais encore instable)

Scénario optimiste

6 mois : 20k installs (si un use-case devient viral : “PR Evidence Review MCP”)

1% conversion -> 200 teams à 300€/mois = 60k€ MRR

Résultat : tu peux staffer

Le levier le plus important n’est pas le nombre d’agents, c’est :
un use-case “must-have” + distribution MCP registry + une “demo qui claque”.

6) Comment tu sais en 14 jours si tu es sur le bon chemin

Objectif : validation marché, pas “refacto”.

3 signaux à obtenir en 2 semaines

10 conversations (tech leads / archis / devsecops)
Tu ne “pitches” pas NEXUS, tu poses :

“Quand tu sors un rapport d’agent, qu’est-ce qui te manque pour le faire valider ?”

“Qu’est-ce qui te ferait confiance : trace ? sources ? hash ? policy ?”

“Quel format te fait gagner du temps en PR ?”

Un use-case canonique dans README
Ex : “PR Review Evidence Pack”

Input : PR diff + question

Output : artefacts + commentaire PR + score confiance + risques

Un canal de distribution réellement branché

serveur MCP listé (registry officiel/GitHub MCP registry selon ce qui est le plus pertinent)

install en 1 commande

une démo vidéo de 90 secondes

Si tu n’obtiens pas au moins 3 personnes qui disent “je le veux dans mon équipe”, pivot.

7) Si ce chemin ne marche pas, voici le plan B
Plan B1 — “Agent Governance Toolkit” (lib + MCP)

Tu ne vends plus l’agent, tu vends : policy + logs + budget + redaction
=> intégré à Agent Framework / LangGraph / Agents SDK.

 

Pourquoi ça peut marcher : les entreprises veulent gouverner des stacks hétérogènes, et multi-modèles est la norme.

Plan B2 — 100% service + outil interne

Tu assumes que NEXUS est ton “exosquelette” pour missions d’archi/PM, et tu le monétises indirectement.

8) Plan d’action immédiat (ordre opératoire)
Étape 1 — Reserrer le scope produit (1–2 jours)

Le mot “Hive Mind / OS / agent framework” passe en arrière-plan.

Tu mets en avant : Evidence Pack (outputs, formats, intégration PR/CI).

Tu réduis la promesse : “des artefacts vérifiables, pas des agents magiques”.

Étape 2 — Un “killer workflow” (3–5 jours)

Choisis 1 seul flux :

“Analyse d’architecture d’un repo + ADR + risques + plan de migration”
OU

“PR review + risques + tests à ajouter + justification”

Étape 3 — Distribution MCP (1 jour)

Publier nexus-mcp de manière listable (registry)

Documentation install “idiot-proof”

Exemple Claude Desktop + VS Code

Tu es dans le bon timing : MCP est en train de devenir la plomberie standard, et l’écosystème se structure (AAIF + registries + IDE support).

Étape 4 — MCP App (option) (1–2 semaines)

Tu recrées Cerebro en MCP App : un viewer de trace/sources/graph.

Ma phrase “dure” pour t’aider à décider

Si tu essaies de vendre NEXUS comme framework agentique, tu vas te battre contre des standards et des plateformes (Microsoft Agent Framework, OpenAI Agents SDK, LangGraph, CrewAI) et tu vas t’épuiser.

 

Si tu vends Evidence Pack + gouvernance + distribution MCP, tu joues sur une demande réelle (qualité/observabilité) et tu utilises un canal de distribution qui grossit vite (MCP + registries + IDEs + MCP Apps).

Si tu veux, je peux te proposer 3 “produits exacts” (nom, persona, promesse, features MVP, packaging pip extras, commandes, démos, pricing initial, roadmap 6 semaines) — mais en restant strictement aligné avec cette trajectoire “wedge evidence + MCP”.

Okay fais cela, n'oublies pas que je dois proposer au moins deux options, de la R&D continue et une solution adaptative enterprise grade
Thought for 11m 38s

D’accord. Je vais te proposer 3 produits “exactement définis” (nom, persona, promesse, MVP, packaging/extras, commandes, démos, pricing, roadmap 6 semaines), puis 2 options de trajectoire (au moins) qui couvrent explicitement :

R&D continue (innovation + itérations, sans bloquer le produit)

Solution adaptative enterprise‑grade (gouvernance, sécurité, déploiement, intégration)

Je m’appuie sur ce que le marché “récompense” en 2026, et pas sur ce qui est “cool” techniquement.

1) Ce que dit le marché (et pourquoi ça change ton angle)
1) Les agents sont déjà “commoditisés”, mais la douleur #1 = qualité + preuves

Le rapport LangChain (1300+ répondants) montre que les agents passent massivement en prod, et que qualité/fiabilité + observabilité deviennent les vrais enjeux.
Conséquence : vendre “un framework agentique de plus” est très difficile.

2) MCP est en train de devenir la plomberie standard + un canal de distribution

MCP a été donné à la Linux Foundation via l’Agentic AI Foundation (AAIF), avec soutien de gros acteurs : c’est un signal “standard durable”.

GitHub a lancé une MCP Registry pour découvrir les serveurs MCP.

MCP est GA dans VS Code (donc diffusion massive côté dev).

Conséquence : ton meilleur “go‑to‑market” en tant que solo/indé, c’est MCP-first.

3) “Enterprise‑grade” veut dire gouvernance + policy + contrôle des serveurs MCP

VS Code mentionne que les orgs peuvent contrôler la disponibilité des MCP servers via policy.

Le MCP Registry insiste sur l’authenticité (noms reverse‑DNS, namespaces vérifiés) et clarifie qu’il est en preview (risque de breaking changes / resets).

Exemple concret : Box pousse son MCP server comme un “governed bridge” (permissions, policies, gouvernance).

Conséquence : ton offre enterprise ne doit pas être “plus de features agent”, mais plus de contrôle.

4) Compétition frontale sur “framework” = extrêmement violente

Microsoft pousse Agent Framework (state, middleware, telemetry, workflows).
OpenAI pousse Agents SDK (tools, handoffs, streaming, tracing).

 

Conséquence : si tu vends “NEXUS = framework”, tu combats des plateformes. Si tu vends evidence + gouvernance + distribution MCP, tu complètes ces stacks (plus intelligent).

2) Ton portefeuille produit recommandé (3 produits, très concrets)

Tu vends un portfolio cohérent : un cœur wedge OSS, une couche enterprise, et une offre R&D continue qui nourrit les deux.

Produit 1 — NEXUS Evidence Pack
Positionnement

“Transformer une question (repo/PR/doc) en livrables vérifiables” : rapport + sources + trace + graph + manifest.

 

Persona

Utilisateur : dev/tech lead qui veut des analyses actionnables et auditables

Acheteur (si pro) : lead dev / manager engineering

Promesse
“Je peux brancher NEXUS dans mon IDE/Claude Desktop via MCP et obtenir un pack de preuves exploitable en PR, en doc, en audit — même en mode mock sans clés.”

 

Pourquoi ça colle au marché
Parce que la douleur #1 en prod = qualité/fiabilité, et “preuve/trace” devient l’artefact qui permet l’adoption.

MVP (6 semaines) — ce qui doit exister

Format d’artefacts stabilisé (contrat) :

report.md

sources.json

trace.jsonl

reasoning_graph.mmd

metrics.json

manifest.sha256

Deux modes stables :

--mode mock (sans clés) : reproductible + rapide

--mode live (Claude/Gemini/...) : optionnel

1 use-case “killer demo” (pas 10) :

PR Review Evidence Pack ou Audit d’architecture repo

MCP server expose exactement 2 outils au départ :

research(query, path, limit, mode)

evidence_pack(query, inputs...)

Smoke tests wedge (CI) :

“génère un pack” + “manifest valide” + “pas d’import error”

Packaging (pip extras) — tu as déjà la base

Tu restes dans une distribution Python avec extras (c’est standard via optional-dependencies).
Dans ton repo, c’est déjà structuré (base, api, mcp, sdk, otel, dev, all).

 

Installation / commandes (copier‑coller)

# Local editable (dev)
pip install -e ".[dev]"

# Mode mock (zéro clés) — démo immédiate
nexus-research --mode mock "What is the NEXUS architecture?" --limit 3

# MCP server
pip install -e ".[mcp]"
nexus-mcp

(Le quickstart est déjà aligné sur ça.)

Démos (script 90 secondes)

“Je pointe un repo/PR -> je pose une question -> je récupère un pack de preuves -> je colle report.md dans la PR, et sources.json sert de justification.”

Pricing (proposition simple)

Community (MIT) : gratuit

Pro (à terme) : 20–40€ / dev / mois (feature : export PR comment, templates, bundles, support)

Team : 200–600€ / mois / équipe (artefacts signés, policies simples)

L’objectif du pricing ici n’est pas de “maximiser”, c’est de créer une marche vers l’enterprise.

Roadmap 6 semaines (Evidence Pack)

S1 : choisir 1 use-case, figer format artefacts + smoke tests

S2 : pack generator stable + manifest + docs examples

S3 : MCP server minimal (2 tools) + config “Claude Desktop / VS Code”

S4 : “PR Review Evidence Pack” (output prêt à coller)

S5 : export OTel optionnel (si tu as otel) + métriques pack

S6 : release + publication (registry/marketplaces) + 1 vidéo demo

Produit 2 — NEXUS Evidence Gateway
Positionnement

“Le pont gouverné entre tes clients MCP (VS Code / Copilot / Claude Desktop / ...) et tes systèmes (Git, Jira, Confluence, DB, etc.)”
Le mot clé enterprise : policy + audit + contrôle.

 

Persona

Utilisateur : Platform Eng / DevSecOps / Staff engineer

Acheteur : CTO / Head of Eng / CISO (selon org)

Promesse
“Tu peux autoriser l’IA à agir, sans perdre le contrôle : qui a fait quoi, avec quels accès, quelles sources, et sous quelles règles.”

 

Pourquoi ça colle au marché

VS Code MCP est GA et gérable via policy : les entreprises veulent “approved servers only”.

Le MCP Registry est preview (pas de garanties durabilité), donc enterprise a intérêt à avoir un contrôle interne et/ou un registre privé/agrégateur.

Box positionne déjà ce pattern “governed bridge” pour l’enterprise.

MVP (6 semaines) — ce qui doit exister

Policy engine minimal mais réel

allowlist tools

allowlist hosts/clients (si possible)

règles “data boundary” (ex: pas d’accès hors repo)

Audit log et traçabilité

trace structurée (JSONL)

export OpenTelemetry si activé

Budget caps / rate limits

budget par workspace / par utilisateur

Redaction / secrets hygiene minimal

masquage patterns (clés, tokens, emails) sur logs/artefacts

Déploiement simple

docker compose up ou uvicorn ... (mais stable)

Interfaçage

mode “proxy MCP” ou “gateway” (même si simple au début)

Tu n’essaies pas d’être un “framework”. Tu es le contrôleur de risque + preuve autour de n’importe quel agent.

Packaging / delivery

Python package + extras ([api,db,otel,mcp]) + container optionnel

Les extras existent déjà côté repo (api, db, otel, mcp).

Installation / commandes

pip install -e ".[api,db,otel,mcp]"
uvicorn core.api.cerebro.app:create_cerebro_app --factory --port 8080
curl http://localhost:8080/health

(Le quickstart Cerebro existe déjà, tu le rends “enterprise‑ready” via policy + audit + caps.)

Démo (5 minutes, “enterprise story”)

Dans VS Code (MCP GA), on n’autorise que des MCP servers approuvés (concept “policy”).

L’utilisateur lance une action -> le gateway applique policy -> produit trace + artefacts signables.

Pricing (proposition enterprise)

Starter : 1 000–3 000€ / mois (self-host + support email + mises à jour)

Enterprise : 15k–60k€ / an (SLA, SSO/SCIM roadmap, audit/compliance, private registry/aggregator, support)

On‑prem / air‑gapped : sur devis

Roadmap 6 semaines (Evidence Gateway)

S1 : policy minimale + logs + docs “threat model”

S2 : budget caps + rate limiting + audit JSONL stable

S3 : OTel export (si otel) + dashboards minimum

S4 : redaction + “approved tools” config simple

S5 : packaging déploiement (compose/helm minimal) + hardening

S6 : pilot avec 1 design partner (même une petite boîte) + itérations

Produit 3 — NEXUS Research Studio
Positionnement

R&D continue : “fabrique d’expériences + évaluations + itérations” (pour toi et/ou pour des clients).

 

Persona

Innovation lab / équipe R&D / consultant

Acheteur : Head of Innovation / CTO (si R&D contractuelle)

Promesse
“On améliore les agents comme un système logiciel : eval‑driven, traces, benchmarks, scénarios reproductibles.”

 

Pourquoi ça colle
OpenAI pousse explicitement des approches “governed agents” avec tracing + guardrails + eval-driven design comme base.
Et côté Microsoft, l’enterprise attend déjà telemetry/middleware/state dans les frameworks modernes.

MVP (6 semaines)

Registry d’expériences

scénario -> inputs -> outputs -> artefacts -> score

Runner (local + CI)

“run 20 scénarios, compare A/B modèles/modes”

Rapports

un tableau de résultats + diff des artefacts

Boucles d’amélioration

“on change une policy / un prompt / un mode -> on rerun -> on mesure”

Packaging

pip install -e ".[dev,otel,sdk]" (ou subsets)

output standardisé “Evidence Pack” = l’artefact R&D

Monétisation (très pragmatique)

R&D Retainer : 2–10k€ / mois selon intensité (2 sprints / mois)

Livrable : packs d’évidence + recommandations + PRs

Roadmap 6 semaines (Research Studio)

S1 : définir 20 scénarios, format score, runner

S2 : baseline mock + baseline live

S3 : A/B routing + cost/quality

S4 : intégration “CI eval nightly”

S5 : rapport auto + dashboard simple

S6 : “release note R&D” (ce qui s’améliore + ce qui régresse)

3) Deux options de trajectoire (tu dois en proposer au moins deux)

Je te donne deux chemins crédibles. Les deux incluent R&D continue et une cible enterprise‑grade, mais l’ordre change.

Option 1 (recommandée) — Wedge d’abord, enterprise ensuite
Ordre

Evidence Pack (OSS wedge)

Research Studio en parallèle (R&D qui nourrit le wedge)

Evidence Gateway une fois qu’un usage est adopté

Pourquoi je recommande

Distribution MCP est réelle (VS Code GA + registry + ecosystem).

Tu réduis le risque : tu vends un résultat concret très vite.

“Preuve que ça marche” en 6 semaines (OKRs)

1 killer workflow

1 MCP server installable

1 pack stable + manifest

5–10 utilisateurs externes qui l’installent et reviennent

Quand tu pivotes vers enterprise ?
Dès que tu as 2–3 équipes qui disent : “on veut policy + audit + cap”.

Option 2 — Enterprise pilot d’abord (revenu + contraintes fortes)
Ordre

Evidence Gateway avec 1 design partner (même petit)

Evidence Pack comme open-core (gratuit)

Research Studio comme moteur d’amélioration continue contractualisé

Pourquoi choisir ça

Si tu as déjà accès à 1 client potentiel, tu monétises plus vite.

Mais tu acceptes une contrainte : sécurité/déploiement/support dès le jour 1.

Preuve que ça marche

1 pilote déployé + 1 audit trail + 1 policy baseline + 1 incident drill

4) Et si ce chemin est faux ? Plan de repli (pivot intelligent)

Si tu n’arrives pas à créer d’adoption en wedge en 2–4 semaines, pivote vers :

Pivot A — “Governance addon” pour les frameworks dominants

Tu te positionnes comme couche “evidence + policy + audit” autour de :

Microsoft Agent Framework (enterprise features)

OpenAI Agents SDK (traces/streaming/handoffs)

Tu ne combats plus les plateformes : tu complètes.

Pivot B — “MCP Apps” au lieu d’un frontend lourd

MCP Apps permet aux serveurs de livrer des interfaces UI interactives dans les clients.
Tu peux reconstruire Cerebro comme Evidence Review App sans maintenir une SPA “à part”.

5) Comment tu l’exécutes sans te perdre (Superpowers, en mode “produit”)

Superpowers est justement fait pour “brainstorm -> plan -> exécution” au lieu de dériver.

Copie‑colle (kickoff) pour Claude Code + Superpowers
/superpowers:brainstorm

Nous sommes le 26 février 2026 (Europe/Paris).

But: choisir et livrer un portefeuille produit NEXUS en 6 semaines.
Tu dois produire 2 options de trajectoire:
- Option 1: Wedge OSS (Evidence Pack) -> Enterprise
- Option 2: Enterprise pilot -> Open-core

Contraintes:
- 1 seul "killer workflow" à livrer en 6 semaines.
- Le produit doit être MCP-first (distribution VS Code/Claude).
- Inclure une offre R&D continue (Research Studio) ET une offre enterprise adaptive (Evidence Gateway).
- À la fin: tu écris un DESIGN DOC + un PLAN exécutable (tâches 2–5 minutes) + critères de succès + risques.

Ensuite :

/superpowers:write-plan

Puis :

/superpowers:execute-plan
Ma recommandation finale (tranchée)

Si tu veux maximiser tes chances sans équipe :

Choisis Option 1 (Wedge d’abord)

Et vends Evidence Pack comme produit visible, puis Enterprise Gateway comme upsell naturel (policy/audit/caps)

Ce que tu “vends”, au fond, ce n’est pas “un OS agentique” :
Tu vends la capacité de faire confiance à un agent (preuves, trace, gouvernance) via un standard de distribution (MCP).