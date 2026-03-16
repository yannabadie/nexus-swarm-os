"""
Plan Health Monitoring - Détecte les plans zombies et stagnants

V7 Architecture: Proper implementation for zombie detection.
"""


class PlanHealthMonitor:
    """
    Monitore la santé du plan stratégique

    Détecte 4 niveaux de problèmes:
    1. HEALTHY - Plan actif et progresse
    2. WARNING - Plan n'a pas progressé depuis N tours
    3. STAGNANT - Aucune étape complétée depuis trop longtemps
    4. ZOMBIE - Plan complètement mort (toutes étapes PENDING > seuil)
    """

    def __init__(self, warning_threshold: int = 10, stagnant_threshold: int = 20, zombie_threshold: int = 30):
        """
        Args:
            warning_threshold: Nombre de tours sans progrès -> WARNING
            stagnant_threshold: Nombre de tours sans completion -> STAGNANT
            zombie_threshold: Nombre de tours sans aucun progrès -> ZOMBIE
        """
        self.warning_threshold = warning_threshold
        self.stagnant_threshold = stagnant_threshold
        self.zombie_threshold = zombie_threshold

        # State tracking
        self.last_progress_turn = 0
        self.last_completion_turn = 0
        self.plan_created_turn = 0
        self.current_turn = 0

        # Previous plan state for comparison
        self.previous_plan: list[dict] | None = None

    def reset(self):
        """Reset monitoring for new plan"""
        self.last_progress_turn = self.current_turn
        self.last_completion_turn = self.current_turn
        self.plan_created_turn = self.current_turn
        self.previous_plan = None

    def check_health(self, current_plan: list[dict] | None, current_turn: int) -> dict:
        """
        Vérifie la santé du plan

        Args:
            current_plan: Liste des étapes du plan actuel
            current_turn: Numéro du tour actuel

        Returns:
            {
                "status": "HEALTHY|WARNING|STAGNANT|ZOMBIE",
                "message": "Description du problème",
                "turns_since_progress": int,
                "turns_since_completion": int,
                "turns_since_creation": int,
                "recommendation": "Action recommandée"
            }
        """
        self.current_turn = current_turn

        # No plan = healthy (not monitoring)
        if not current_plan or len(current_plan) == 0:
            return {
                "status": "HEALTHY",
                "message": "No active plan (not monitoring)",
                "turns_since_progress": 0,
                "turns_since_completion": 0,
                "turns_since_creation": 0,
                "recommendation": None,
            }

        # Check if this is a new plan
        if self.previous_plan is None or len(current_plan) != len(self.previous_plan):
            self.reset()
            self.previous_plan = self._copy_plan(current_plan)

        # Detect progress
        has_progress = self._has_progress(self.previous_plan, current_plan)
        has_completion = self._has_completion(self.previous_plan, current_plan)

        if has_progress:
            self.last_progress_turn = current_turn
        if has_completion:
            self.last_completion_turn = current_turn

        # Update previous plan
        self.previous_plan = self._copy_plan(current_plan)

        # Calculate time deltas
        turns_since_progress = current_turn - self.last_progress_turn
        turns_since_completion = current_turn - self.last_completion_turn
        turns_since_creation = current_turn - self.plan_created_turn

        # Determine health status
        status, message, recommendation = self._determine_status(
            turns_since_progress, turns_since_completion, turns_since_creation, current_plan
        )

        return {
            "status": status,
            "message": message,
            "turns_since_progress": turns_since_progress,
            "turns_since_completion": turns_since_completion,
            "turns_since_creation": turns_since_creation,
            "recommendation": recommendation,
        }

    def _has_progress(self, prev_plan: list[dict] | None, curr_plan: list[dict]) -> bool:
        """Détecte si au moins une étape a changé de statut"""
        if not prev_plan:
            return False

        for i, curr_step in enumerate(curr_plan):
            if i >= len(prev_plan):
                return True  # New step added

            prev_step = prev_plan[i]
            if prev_step.get("status") != curr_step.get("status"):
                return True

        return False

    def _has_completion(self, prev_plan: list[dict] | None, curr_plan: list[dict]) -> bool:
        """Détecte si au moins une étape est passée à COMPLETED"""
        if not prev_plan:
            return False

        for i, curr_step in enumerate(curr_plan):
            if i >= len(prev_plan):
                continue

            prev_step = prev_plan[i]
            if prev_step.get("status") != "COMPLETED" and curr_step.get("status") == "COMPLETED":
                return True

        return False

    def _determine_status(
        self,
        turns_since_progress: int,
        turns_since_completion: int,
        turns_since_creation: int,
        current_plan: list[dict],
    ) -> tuple:
        """Détermine le statut de santé"""

        # Check for ZOMBIE (most severe)
        all_pending = all(step.get("status") == "PENDING" for step in current_plan)
        if all_pending and turns_since_creation > self.zombie_threshold:
            return (
                "ZOMBIE",
                f"Plan zombie détecté: toutes les étapes PENDING depuis {turns_since_creation} tours",
                "CRITICAL: Réinitialiser le plan ou forcer une décision immédiate",
            )

        # Check for STAGNANT
        if turns_since_completion > self.stagnant_threshold:
            return (
                "STAGNANT",
                f"Plan stagnant: aucune étape complétée depuis {turns_since_completion} tours",
                "WARNING: Forcer une étape à complétion ou ajuster la stratégie",
            )

        # Check for WARNING
        if turns_since_progress > self.warning_threshold:
            return (
                "WARNING",
                f"Plan n'a pas progressé depuis {turns_since_progress} tours",
                "Vérifier si les agents sont bloqués ou si le plan doit être ajusté",
            )

        # HEALTHY
        return ("HEALTHY", "Plan progresse normalement", None)

    def _copy_plan(self, plan: list[dict]) -> list[dict]:
        """Copie profonde du plan pour comparaison"""
        return [
            {
                "id": step.get("id"),
                "description": step.get("description"),
                "status": step.get("status"),
                "assigned_agent": step.get("assigned_agent"),
            }
            for step in plan
        ]
