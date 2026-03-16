"""
Interactive Tutorial - NEXUS V8.3.x TRUE HIVE MIND

Guide interactif pour les nouveaux utilisateurs.
Présente les fonctionnalités clés de NEXUS en 6 étapes.
"""

from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class TutorialStep:
    """A single step in the tutorial."""

    title: str
    explanation: str
    suggested_command: str | None = None
    tip: str | None = None


# =============================================================================
# TUTORIAL CONTENT (V8.3.x)
# =============================================================================

TUTORIAL_STEPS: list[TutorialStep] = [
    TutorialStep(
        title="Bienvenue dans NEXUS TRUE HIVE MIND",
        explanation="""
NEXUS est une plateforme de collaboration multi-agents.

🐝 PHILOSOPHIE HIVE MIND:
   - Gemini et Claude travaillent ENSEMBLE, pas en hiérarchie
   - 6 modes de collaboration (Swarm) selon la complexité
   - Génération d'agents spécialisés qui coexistent

🎯 VOTRE RÔLE:
   - Posez des questions ou décrivez des tâches
   - NEXUS choisit automatiquement le meilleur mode
   - Les agents collaborent pour résoudre votre problème

🆕 V8.3: Les agents peuvent maintenant déléguer au Swarm!
""",
        tip="NEXUS analyse automatiquement la complexité de vos tâches",
    ),
    TutorialStep(
        title="Mode Swarm - Collaboration Intelligente",
        explanation="""
Le Swarm Engine orchestre la collaboration entre agents.

📊 6 MODES DE COLLABORATION:
   - PARALLEL    - Travail simultané, résultats fusionnés
   - SEQUENTIAL  - Pipeline ordonné (Agent1 -> Agent2)
   - LEAD_SUPPORT - Un lead (80%), un support (20%)
   - PING_PONG   - Alternance rapide jusqu'à convergence
   - SPECIALIST  - Un seul expert pour les tâches pointues
   - RED_BLUE    - Adversarial (proposer/attaquer/défendre)

🆕 V8.3 SwarmBridge: Le HiveMind peut déléguer des sous-tâches
   au Swarm pour une exécution tactique optimale!

💡 NEXUS choisit automatiquement le mode optimal!
""",
        suggested_command='/swarm "Analyse ce projet et suggère des améliorations"',
        tip="Utilisez /swarm-status pour voir le mode actif",
    ),
    TutorialStep(
        title="Agents Spécialisés - Génération Dynamique",
        explanation="""
NEXUS V8.1.8+ génère des agents vraiment spécialisés.

🧬 DYNAMIC SPAWN (V8.1.8):
   - Le HiveMind brainstorme le system prompt
   - Pas de templates statiques - prompts sur mesure
   - Validation anti-hallucination des outils

🎯 MODEL SELECTION (V8.1.8-B):
   - Chaque agent choisit son LLM optimal
   - Gemini Flash pour vitesse, Claude Opus pour raisonnement
   - Configuration dans BIRTH_CERTIFICATE.json

📝 COMMANDES:
   - /spawn "SQL Expert"     - Crée un agent spécialisé
   - /agents                 - Liste vos agents
   - /invoke sql_expert ...  - Utilise un agent

[warning]️ Le spawn utilise le brainstorming - surveiller /budget!
""",
        suggested_command='/spawn "Python testing expert"',
        tip="Les agents spawnés persistent dans workspace/agents/",
    ),
    TutorialStep(
        title="Mémoire & RAG - Intelligence Persistante",
        explanation="""
NEXUS apprend de vos succès et retient le contexte projet.

📚 PROJECT MEMORY (RAG):
   - Indexe automatiquement votre codebase
   - Retrieval sémantique (Dense) + lexical (TF-IDF)
   - Commandes: /rag init, /rag clear, /rag query

🧠 SUCCESS MEMORY (V8.2.0):
   - Enregistre les tâches réussies
   - Réutilise les modes qui ont fonctionné
   - Decay temporel (préfère expériences récentes)

💡 Plus vous utilisez NEXUS, plus il devient efficace!
""",
        suggested_command="/rag init",
        tip="Utilisez /rag query 'auth' pour tester le retrieval",
    ),
    TutorialStep(
        title="Budget & Télémétrie - Contrôle des Coûts",
        explanation="""
NEXUS surveille vos dépenses API en temps réel.

💰 BUDGET:
   - Limite quotidienne configurable (défaut: $50)
   - Alertes à 80% et 90% du budget
   - Blocage automatique à 100%

📈 TÉLÉMÉTRIE:
   - Tokens utilisés par modèle
   - Latence moyenne des appels
   - Historique des 7 derniers jours

🔄 SELF-HEALING (V8.1.3):
   - Fallback automatique si un mode échoue
   - PARALLEL -> SEQUENTIAL si race condition
   - Hot-Swap du lead agent si stagnation (V8.0.1)
""",
        suggested_command="/budget",
        tip="Utilisez /budget reset en cas d'urgence",
    ),
    TutorialStep(
        title="Architecture Avancée - Pour Aller Plus Loin",
        explanation="""
Fonctionnalités avancées pour utilisateurs expérimentés.

🐝 HIVE MIND PIPELINE (7 phases):
   1. Analysis    - Analyse indépendante
   2. Debate      - Débat stratégique
   3. Architecture - Plan d'exécution
   4. Execution   - Exécution surveillée (+ Swarm V8.3)
   5. Diagnosis   - Diagnostic des échecs
   6. Retry       - Nouvelle tentative adaptée
   7. Consolidation - Apprentissage

🔧 SWARM TOOL (V8.3.1):
   Les agents peuvent invoquer swarm_delegate pour déléguer
   des sous-tâches au Swarm Engine à n'importe quelle phase!

🛡️ SÉCURITÉ:
   - SandboxPolicy pour commandes dangereuses
   - RedTeam validation des agents spawnés (V8.2.0c)
   - Depth Guard anti-récursion (max 2 niveaux)

📖 Voir ROADMAP.md pour la liste complète des features!
""",
        suggested_command="/status",
        tip="Consultez docs/ pour la documentation technique",
    ),
]


class InteractiveTutorial:
    """
    Interactive tutorial runner for NEXUS.

    Usage:
        tutorial = InteractiveTutorial()
        tutorial.run(console.print)
    """

    def __init__(self, steps: list[TutorialStep] | None = None):
        """
        Initialize tutorial with steps.

        Args:
            steps: Custom steps or use default TUTORIAL_STEPS
        """
        self.steps = steps or TUTORIAL_STEPS
        self.current_step = 0

    def get_step(self, index: int) -> TutorialStep | None:
        """Get step by index."""
        if 0 <= index < len(self.steps):
            return self.steps[index]
        return None

    def format_step(self, step: TutorialStep, index: int) -> str:
        """
        Format a tutorial step for display.

        Args:
            step: The step to format
            index: Step number (0-based)

        Returns:
            Formatted string for display
        """
        total = len(self.steps)
        lines = [
            "",
            "=" * 64,
            f"TUTORIAL ({index + 1}/{total}): {step.title}",
            "=" * 64,
            "",
            step.explanation,
        ]

        if step.suggested_command:
            lines.extend(
                [
                    "",
                    "Try this command:",
                    f"  {step.suggested_command}",
                ]
            )

        if step.tip:
            lines.extend(
                [
                    "",
                    f"Tip: {step.tip}",
                ]
            )

        lines.extend(
            [
                "",
                "-" * 64,
            ]
        )

        return "\n".join(lines)

    def run(self, print_fn: Callable[[str], None], input_fn: Callable[[str], str] | None = None) -> bool:
        """
        Run the interactive tutorial.

        Args:
            print_fn: Function to print output (e.g., console.print)
            input_fn: Function to get input (default: built-in input)

        Returns:
            True if completed, False if skipped/aborted
        """
        if input_fn is None:
            input_fn = input

        print_fn("\nWelcome to the NEXUS interactive tutorial.")
        print_fn("   Appuyez sur [Entrée] pour avancer, 'q' pour quitter, 's' pour sauter.\n")

        for i, step in enumerate(self.steps):
            self.current_step = i

            # Display step
            formatted = self.format_step(step, i)
            print_fn(formatted)

            # Wait for user input
            try:
                if i < len(self.steps) - 1:
                    prompt = "[Entrée = suivant | s = sauter | q = quitter] "
                else:
                    prompt = "[Entrée = terminer | q = quitter] "

                user_input = input_fn(prompt).strip().lower()

                if user_input == "q":
                    print_fn("\nTutorial interrupted. Use /tutorial to resume.\n")
                    return False
                elif user_input == "s":
                    print_fn("Step skipped.\n")
                    continue

            except (EOFError, KeyboardInterrupt):
                print_fn("\nTutorial interrupted.\n")
                return False

        # Tutorial complete
        print_fn("""
==============================================================
TUTORIAL COMPLETE
==============================================================
You are ready to use NEXUS TRUE HIVE MIND.

  /help      - Show all commands
  /swarm     - Launch a collaborative task
  /budget    - Check your spend
  /spawn     - Create a specialized agent
  /rag init  - Index your project

Good collaboration.
""")
        return True

    def get_quick_start(self) -> str:
        """
        Get a quick start summary (for /quickstart command).

        Returns:
            Formatted quick start guide
        """
        return """
==============================================================
NEXUS TRUE HIVE MIND - QUICK START
==============================================================

1. ASK A QUESTION
   > Analyse ce code et trouve les bugs

2. USE SWARM FOR COMPLEX TASKS
   > /swarm "Refactore le module auth avec tests"

3. INDEX YOUR PROJECT
   > /rag init

4. CREATE SPECIALIZED AGENTS
   > /spawn SQL Expert

5. REVIEW YOUR BUDGET
   > /budget

6. OPEN HELP
   > /help

Tip: use /tutorial for the guided version.
Docs: see docs/ and ROADMAP.md
"""
