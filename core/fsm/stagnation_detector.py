"""
Stagnation Detector - Détection adaptative de stagnation dans le brainstorming

Problème: Agents peuvent discuter en boucle sans jamais agir
Solution: Détecte la similarité textuelle des messages TALK

Méthode:
1. Stocke les 3 derniers messages TALK
2. Compare la similarité pairwise (difflib.SequenceMatcher)
3. Si 2+ paires sont similaires (> 0.8) -> stagnation détectée
4. Injecte warning système pour forcer décision

V8.0 Integration: Feeds into StrategyBlacklist
- When stagnation detected, can report to blacklist
- Blacklist uses STAGNATION category
- Helps prevent same conversation loops across retries
"""

from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from core.intelligence.hive_mind.strategy_blacklist import StrategyBlacklist


class StagnationDetector:
    """
    Détecte la stagnation dans le brainstorming

    Usage:
        detector = StagnationDetector()
        detector.add_message("Je pense qu'on devrait lire auth.py")
        detector.add_message("Oui, lisons auth.py d'abord")
        detector.add_message("D'accord, lire auth.py")
        if detector.is_stagnant():
            # Force decision
    """

    # V11 FIX F5: Action verbs that indicate progress
    _PROGRESS_INDICATORS = {
        # Tool usage (strong progress)
        "<tool_use",
        "</tool_use>",
        "tool_use",
        # Action verbs
        "executing",
        "running",
        "reading",
        "writing",
        "editing",
        "created",
        "modified",
        "deleted",
        "found",
        "result:",
        # Decision markers
        "decided",
        "agreed",
        "confirmed",
        "proceeding",
        "done",
        # Artifact indicators
        "output:",
        "response:",
        "error:",
        "success:",
    }

    def __init__(
        self,
        similarity_threshold: float = 0.8,
        window_size: int = 3,
        strategy_blacklist: Optional["StrategyBlacklist"] = None,
        semantic_progress_threshold: float = 0.2,  # V11 F5
    ):
        """
        Initialize detector

        Args:
            similarity_threshold: Seuil de similarité (0.0 - 1.0)
                                0.8 = 80% similaire
            window_size: Nombre de messages à comparer (3 = derniers 3 messages)
            strategy_blacklist: V8.0 - Optional blacklist for stagnation reporting
            semantic_progress_threshold: V11 F5 - Minimum semantic progress to avoid stagnation
        """
        self.similarity_threshold = similarity_threshold
        self.window_size = window_size
        self.message_history: list[str] = []
        self._stagnation_count = 0  # V8.0: Track stagnation occurrences

        # V11 FIX F5: Semantic progress tracking
        self.semantic_progress_threshold = semantic_progress_threshold

        # V8.0: StrategyBlacklist integration
        self._strategy_blacklist: StrategyBlacklist | None = strategy_blacklist

    def set_strategy_blacklist(self, blacklist: "StrategyBlacklist"):
        """
        V8.0: Set the StrategyBlacklist for stagnation reporting.

        Args:
            blacklist: StrategyBlacklist instance
        """
        self._strategy_blacklist = blacklist

    def add_message(self, content: str):
        """
        Ajoute un message à l'historique

        Args:
            content: Contenu du message TALK
        """
        # Normalize: lowercase, strip whitespace
        normalized = content.lower().strip()
        self.message_history.append(normalized)

        # Keep only last N messages
        if len(self.message_history) > self.window_size:
            self.message_history = self.message_history[-self.window_size :]

    def is_stagnant(self) -> bool:
        """
        Détecte si la conversation stagne

        V11 FIX F5: Now uses BOTH text similarity AND semantic progress.
        Stagnation = high text similarity AND low semantic progress.
        This prevents false positives during productive brainstorming.

        Returns:
            True si les messages se répètent (stagnation)

        Example:
            Message 1: "Je pense qu'on devrait lire auth.py"
            Message 2: "Oui, lisons auth.py d'abord"
            Message 3: "D'accord, lire auth.py"
            -> Similarité élevée + no tool usage + no progress -> stagnation = True

            Message 1: "Je pense qu'on devrait lire auth.py"
            Message 2: "Oui, lisons auth.py d'abord"
            Message 3: "<tool_use>reading auth.py...</tool_use>"
            -> Even if similar, tool usage detected -> stagnation = False
        """
        if len(self.message_history) < self.window_size:
            return False

        # Compare last N messages pairwise
        recent = self.message_history[-self.window_size :]

        similarities = []
        for i in range(len(recent)):
            for j in range(i + 1, len(recent)):
                sim = self._similarity(recent[i], recent[j])
                similarities.append(sim)

        # Si au moins 2 paires sont très similaires -> potentielle stagnation
        high_similarity_pairs = [s for s in similarities if s > self.similarity_threshold]
        text_similarity_high = len(high_similarity_pairs) >= 2

        # V11 FIX F5: Also check semantic progress
        semantic_progress = self._compute_semantic_progress()
        semantic_progress_low = semantic_progress < self.semantic_progress_threshold

        # Stagnation = high text similarity AND low semantic progress
        return text_similarity_high and semantic_progress_low

    def _similarity(self, text1: str, text2: str) -> float:
        """
        Calcule similarité entre 2 textes

        Uses difflib.SequenceMatcher (Gestalt Pattern Matching)

        Args:
            text1: Premier texte
            text2: Deuxième texte

        Returns:
            Score 0.0 - 1.0 (0 = différent, 1 = identique)

        Example:
            _similarity("lire auth.py", "lisons auth.py") -> 0.85
            _similarity("lire auth.py", "écrire test.py") -> 0.30
        """
        return SequenceMatcher(None, text1, text2).ratio()

    def _compute_semantic_progress(self) -> float:
        """
        V11 FIX F5: Compute semantic progress in recent messages.

        Analyzes messages for:
        1. Tool usage indicators (<tool_use>, etc.)
        2. Action verbs (executing, reading, created, etc.)
        3. New unique words (vocabulary expansion)
        4. Length changes (longer messages may indicate elaboration)

        Returns:
            Progress score 0.0 - 1.0 (0 = no progress, 1 = high progress)
        """
        if len(self.message_history) < 2:
            return 1.0  # Not enough history, assume progress

        recent = self.message_history[-self.window_size :]
        progress_score = 0.0

        # 1. Check for progress indicators (strong signal)
        for msg in recent:
            for indicator in self._PROGRESS_INDICATORS:
                if indicator in msg:
                    progress_score += 0.3
                    break  # Only count once per message

        # 2. Check vocabulary expansion (new words in recent vs older)
        if len(recent) >= 2:
            older_words = set(recent[0].split())
            newer_words = set(recent[-1].split())
            new_words = newer_words - older_words

            # More new words = more progress
            if len(newer_words) > 0:
                expansion_ratio = len(new_words) / len(newer_words)
                progress_score += expansion_ratio * 0.3

        # 3. Check for significant length variation (discussion evolving)
        if len(recent) >= 2:
            lengths = [len(msg) for msg in recent]
            avg_length = sum(lengths) / len(lengths)
            if avg_length > 0:
                variance = sum((ln - avg_length) ** 2 for ln in lengths) / len(lengths)
                # High variance = evolving discussion
                normalized_variance = min(variance / (avg_length**2), 1.0)
                progress_score += normalized_variance * 0.2

        # Cap at 1.0
        return min(progress_score, 1.0)

    def reset(self):
        """Reset détecteur (appelé après switch agent ou action)"""
        self.message_history.clear()
        self._stagnation_count = 0

    def get_stagnation_message(self) -> str:
        """
        Message système à injecter en cas de stagnation

        Returns:
            Warning markdown à ajouter au contexte
        """
        return """
---

## [warning]️ ALERTE STAGNATION DÉTECTÉE

**Vous vous répétez depuis 3 tours sans prendre d'action concrète.**

**VOUS DEVEZ MAINTENANT:**
1. Prendre une décision claire (quel outil utiliser?)
2. Exécuter l'action (utiliser <tool_use>)
3. Arrêter de discuter

**Exemple de ce qui est attendu:**
```
<tool_use name="read">
{"file_path": "src/auth.py"}
</tool_use>
```

**Agissez immédiatement ou je passerai à l'agent suivant.**

---
"""

    def get_stats(self) -> dict:
        """
        Get detector statistics (pour debugging)

        Returns:
            {
                "message_count": int,
                "similarity_scores": List[float],
                "is_stagnant": bool
            }
        """
        recent = self.message_history[-self.window_size :] if len(self.message_history) >= self.window_size else []

        similarities = []
        if len(recent) >= 2:
            for i in range(len(recent)):
                for j in range(i + 1, len(recent)):
                    similarities.append(self._similarity(recent[i], recent[j]))

        return {
            "message_count": len(self.message_history),
            "recent_messages": recent,
            "similarity_scores": similarities,
            "is_stagnant": self.is_stagnant(),
            "stagnation_count": self._stagnation_count,
        }

    # =========================================================================
    # V8.0: StrategyBlacklist Integration
    # =========================================================================

    def extract_stagnant_strategy(self) -> str:
        """
        V8.0: Extract the strategy being stagnated on.

        Analyzes recent messages to find common themes/words
        that represent what agents are stuck discussing.

        Returns:
            A description of the stagnant strategy
        """
        if len(self.message_history) < 2:
            return "Unknown discussion topic"

        recent = self.message_history[-self.window_size :]

        # Find common words across messages
        word_sets = [set(msg.split()) for msg in recent]
        if not word_sets:
            return "Circular discussion without clear topic"

        # Find intersection (words in ALL messages)
        common_words = word_sets[0]
        for ws in word_sets[1:]:
            common_words &= ws

        # Remove stop words
        stop_words = {
            "je",
            "tu",
            "il",
            "nous",
            "vous",
            "ils",
            "le",
            "la",
            "les",
            "un",
            "une",
            "des",
            "de",
            "du",
            "à",
            "au",
            "aux",
            "en",
            "et",
            "ou",
            "mais",
            "donc",
            "car",
            "ni",
            "que",
            "qui",
            "quoi",
            "dont",
            "où",
            "the",
            "a",
            "an",
            "to",
            "for",
            "of",
            "in",
            "on",
            "is",
            "are",
            "was",
            "were",
            "be",
            "been",
            "i",
            "you",
            "he",
            "she",
            "we",
            "they",
            "this",
            "that",
            "it",
            "my",
            "your",
            "his",
            "her",
        }
        meaningful_words = [w for w in common_words if w not in stop_words and len(w) > 2]

        if meaningful_words:
            return f"Discussion stagnante sur: {', '.join(meaningful_words[:5])}"
        else:
            # Use first message as fallback
            return f"Discussion répétitive: {recent[0][:100]}..."

    def report_to_blacklist(self, task_context: str = "") -> bool:
        """
        V8.0: Report stagnation to StrategyBlacklist.

        Called when stagnation is detected to prevent
        the same circular discussion in future retries.

        Args:
            task_context: Optional context about the current task

        Returns:
            True if reported successfully, False if no blacklist set
        """
        if not self._strategy_blacklist:
            return False

        if not self.is_stagnant():
            return False

        self._stagnation_count += 1

        # Import here to avoid circular imports
        try:
            from core.intelligence.hive_mind.strategy_blacklist import FailureCategory
        except ImportError:
            return False

        strategy = self.extract_stagnant_strategy()
        diagnosis = (
            f"Detected {self._stagnation_count} stagnation(s). Messages: {self.message_history[-self.window_size :]}"
        )

        self._strategy_blacklist.add_failed_strategy(
            strategy=strategy,
            failure_reason="Agents stuck in circular discussion without action",
            diagnosis=diagnosis,
            failure_category=FailureCategory.STAGNATION,
            tags=["stagnation", "circular", f"count_{self._stagnation_count}"],
        )

        return True

    def check_and_report(self, task_context: str = "") -> bool:
        """
        V8.0: Convenience method - check stagnation AND report if detected.

        Args:
            task_context: Optional context about the current task

        Returns:
            True if stagnation was detected (and possibly reported)
        """
        if self.is_stagnant():
            self.report_to_blacklist(task_context)
            return True
        return False

    # =========================================================================
    # V8.0.1: Hot-Swap Lead Agent Support
    # =========================================================================

    def should_swap_lead(self, current_lead: str, failure_count: int = 2) -> bool:
        """
        V8.0.1: Determine if lead agent should be swapped due to stagnation.

        Called when stagnation is detected to recommend lead swap instead
        of just injecting a warning message.

        Args:
            current_lead: Current lead agent ("gemini" or "claude")
            failure_count: Number of consecutive failures (default: 2)

        Returns:
            True if lead should be swapped
        """
        # Swap if stagnation detected AND we've seen multiple stagnations
        return self.is_stagnant() and self._stagnation_count >= failure_count

    def get_swap_recommendation(self, current_lead: str) -> dict:
        """
        V8.0.1: Get recommendation for lead agent swap.

        Returns:
            Dict with swap recommendation and reason
        """
        if not self.should_swap_lead(current_lead):
            return {"should_swap": False, "reason": "No swap needed", "new_lead": None}

        from core.foundation.agents.unified_registry import get_registry
        new_lead = get_registry().get_alternate(current_lead.lower()) or current_lead.lower()

        return {
            "should_swap": True,
            "reason": f"Agent '{current_lead}' stagnated {self._stagnation_count} times. Swapping to '{new_lead}'.",
            "new_lead": new_lead,
            "stagnation_count": self._stagnation_count,
            "stagnant_strategy": self.extract_stagnant_strategy(),
        }

    def record_agent_failure(self, agent_id: str):
        """
        V8.0.1: Record a failure for an agent (for swap decision).

        Args:
            agent_id: Agent that failed
        """
        self._stagnation_count += 1
