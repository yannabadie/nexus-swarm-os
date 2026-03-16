"""
FSM States - États de la Machine à États NEXUS V7

États possibles de l'orchestrateur:
- IDLE: En attente d'input utilisateur
- BRAINSTORMING: Agents échangent des idées (TALK messages)
- EXECUTING_TOOL: Nexus Core exécute un outil
- VALIDATING_CFL: Agent valide le résultat d'outil (Cognitive Feedback Loop)
- WAITING_USER: Tâche terminée, en attente du prochain input
- ERROR: Erreur récupérable (peut revenir à IDLE avec /reset)
- PANIC: Erreur fatale (doit redémarrer la session)
- HIBERNATE: V12.2 IRONCLAD - État dormant (WebSocket déconnecté pendant workflow actif)
"""

from enum import Enum, auto


class OrchestratorState(Enum):
    """États possibles de l'orchestrateur FSM"""

    IDLE = auto()
    """En attente d'input utilisateur (état initial)"""

    BRAINSTORMING = auto()
    """
    Agents échangent des messages TALK pour s'aligner sur la stratégie.
    Peut basculer entre Gemini et Claude plusieurs fois.
    """

    EXECUTING_TOOL = auto()
    """
    Nexus Core exécute un outil (bash, read, write, edit, etc.)
    Synchrone - bloque jusqu'à ce que l'outil termine.
    """

    VALIDATING_CFL = auto()
    """
    Agent actif valide le résultat de l'outil avec post_action_review.
    CFL (Cognitive Feedback Loop) - garantit que l'outil a fonctionné comme prévu.
    """

    EVOLUTION_BRAINSTORM = auto()
    """
    Mode spécial: Agents débattent pour concevoir mutations émergentes.
    Limite: 30 tours max. Output: JSON avec propositions de mutations.
    """

    WAITING_USER = auto()
    """
    Tâche terminée (status=FINISHED), en attente du prochain input utilisateur.
    """

    ERROR = auto()
    """
    Erreur récupérable détectée:
    - Parse JSON échoué après retries
    - Stagnation détectée
    - Agent ne répond pas
    User peut utiliser /reset pour revenir à IDLE.
    """

    PANIC = auto()
    """
    Erreur fatale non récupérable:
    - Circuit breaker ouvert (trop d'erreurs consécutives)
    - CLI crash
    - Corruption de state
    Session doit être redémarrée.
    """

    # ====================================================================
    # HYBRID SWARM STATES (Sprint 9) - ACTIVE
    # ====================================================================
    # V7.6: Ces états sont ACTIFS et utilisés par /swarm et /swarm-fsm.
    # Transitions définies dans TRANSITION_MATRIX.
    # Usage: /swarm <task> ou SWARM_AUTO_ROUTE=True dans .env

    SWARM_ANALYZING = auto()
    """
    [ACTIVE] Swarm Engine analyse la tâche utilisateur:
    - Déterminer la complexité (TRIVIAL -> EXPERT)
    - Identifier les domaines (CODING, RESEARCH, etc.)
    - Calculer les scores de fit Gemini/Claude
    """

    SWARM_NEGOTIATING = auto()
    """
    [ACTIVE] Agents négocient le mode de collaboration optimal:
    - Débat en langage naturel avec <negotiate> JSON
    - Maximum 4 tours de négociation
    - Consensus ou fallback vers mode initial
    """

    SWARM_EXECUTING = auto()
    """
    [ACTIVE] Exécution du mode de collaboration négocié:
    - PARALLEL: Travail simultané
    - SEQUENTIAL: Enchaînement ordonné
    - LEAD_SUPPORT: Lead + Support
    - PING_PONG: Alternance rapide
    - SPECIALIST: Expert unique
    - RED_BLUE: Adversarial propose/attack
    """

    # ====================================================================
    # V12.2 IRONCLAD - HIBERNATE STATE
    # ====================================================================

    HIBERNATE = auto()
    """
    V12.2 IRONCLAD: Async dormant state for workflow preservation.

    Entered when:
    - WebSocket disconnects during active workflow (BRAINSTORMING, EXECUTING_TOOL, etc.)
    - User explicitly requests pause

    State is persisted to Redis with:
    - Previous FSM state
    - Workflow context
    - HITL pending requests

    Exits to:
    - Previous state on WebSocket reconnect (resume)
    - IDLE after timeout (24h default)
    - IDLE on user cancel

    Example Flow:
    1. User starts workflow (IDLE -> BRAINSTORMING)
    2. Network disconnects (BRAINSTORMING -> HIBERNATE)
    3. User reconnects (HIBERNATE -> BRAINSTORMING, resume from context)
    """


class TransitionGuard:
    """
    Guards pour les transitions FSM
    Conditions qui doivent être vraies pour permettre une transition
    """

    @staticmethod
    def can_start_brainstorming(user_input: str) -> bool:
        """User input valide pour démarrer brainstorming"""
        return bool(user_input and user_input.strip())

    @staticmethod
    def can_execute_tool(message: dict) -> bool:
        """Message contient une requête d'outil valide"""
        return message.get("action_type") == "TOOL_USE" and "tool_use" in message and message["tool_use"] is not None

    @staticmethod
    def is_task_finished(message: dict) -> bool:
        """Tâche marquée comme terminée"""
        return message.get("status") == "FINISHED"

    @staticmethod
    def should_switch_agent(message: dict, current_agent: str) -> bool:
        """Agent demande de basculer vers son partenaire"""
        next_agent = message.get("next_agent")
        return next_agent and next_agent != current_agent

    @staticmethod
    def is_brainstorm_message(message: dict) -> bool:
        """Message est un TALK (pas une action)"""
        return message.get("action_type") in ["TALK", "DELEGATE"]


# Matrice de transitions (pour référence)
TRANSITION_MATRIX = {
    OrchestratorState.IDLE: {"user_input": OrchestratorState.BRAINSTORMING},
    OrchestratorState.BRAINSTORMING: {
        "tool_use": OrchestratorState.EXECUTING_TOOL,
        "finished": OrchestratorState.WAITING_USER,
        "stagnation": OrchestratorState.ERROR,
        "ws_disconnect": OrchestratorState.HIBERNATE,  # V12.2 IRONCLAD
    },
    OrchestratorState.EXECUTING_TOOL: {
        "tool_completed": OrchestratorState.VALIDATING_CFL,
        "ws_disconnect": OrchestratorState.HIBERNATE,  # V12.2 IRONCLAD
    },
    OrchestratorState.VALIDATING_CFL: {
        "success": OrchestratorState.IDLE,
        "failure": OrchestratorState.BRAINSTORMING,
        "stalemate": OrchestratorState.ERROR,
        "ws_disconnect": OrchestratorState.HIBERNATE,  # V12.2 IRONCLAD
    },
    OrchestratorState.WAITING_USER: {
        "user_input": OrchestratorState.BRAINSTORMING,
        "ws_disconnect": OrchestratorState.HIBERNATE,  # V12.2 IRONCLAD
    },
    OrchestratorState.ERROR: {"reset": OrchestratorState.IDLE, "timeout": OrchestratorState.PANIC},
    OrchestratorState.PANIC: {
        # V9.3 ISSUE-002: Recovery path via /reset command
        # Before V9.3: No transitions - user must restart entire session (bad UX)
        # After V9.3: User can recover via /reset without losing work
        "recovery": OrchestratorState.IDLE,
    },
    # ====================================================================
    # HYBRID SWARM TRANSITIONS (Sprint 9)
    # ====================================================================
    OrchestratorState.SWARM_ANALYZING: {
        "analysis_complete": OrchestratorState.SWARM_NEGOTIATING,
        "skip_negotiation": OrchestratorState.SWARM_EXECUTING,
        "error": OrchestratorState.ERROR,
        "ws_disconnect": OrchestratorState.HIBERNATE,  # V12.2 IRONCLAD
    },
    OrchestratorState.SWARM_NEGOTIATING: {
        "consensus": OrchestratorState.SWARM_EXECUTING,
        "timeout": OrchestratorState.SWARM_EXECUTING,  # Fallback to initial mode
        "error": OrchestratorState.ERROR,
        "ws_disconnect": OrchestratorState.HIBERNATE,  # V12.2 IRONCLAD
    },
    OrchestratorState.SWARM_EXECUTING: {
        "execution_complete": OrchestratorState.VALIDATING_CFL,
        "continue": OrchestratorState.SWARM_EXECUTING,
        "error": OrchestratorState.ERROR,
        "ws_disconnect": OrchestratorState.HIBERNATE,  # V12.2 IRONCLAD
    },
    # ====================================================================
    # V12.2 IRONCLAD - HIBERNATE TRANSITIONS
    # ====================================================================
    OrchestratorState.HIBERNATE: {
        "ws_reconnect": None,  # Returns to previous_state (dynamic)
        "timeout": OrchestratorState.IDLE,
        "user_cancel": OrchestratorState.IDLE,
    },
}

# V12.2 IRONCLAD: States that can enter HIBERNATE on WebSocket disconnect
ACTIVE_STATES = {
    OrchestratorState.BRAINSTORMING,
    OrchestratorState.EXECUTING_TOOL,
    OrchestratorState.VALIDATING_CFL,
    OrchestratorState.WAITING_USER,
    OrchestratorState.SWARM_ANALYZING,
    OrchestratorState.SWARM_NEGOTIATING,
    OrchestratorState.SWARM_EXECUTING,
}
