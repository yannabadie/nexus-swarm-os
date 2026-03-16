"""
NEXUS V8.8 - Adaptive Fallback Selector (GROK-004)

Dynamically selects fallback modes based on context instead of static chains.

The Problem (static fallbacks):
    PARALLEL -> SEQUENTIAL -> SPECIALIST (always)

The Solution (adaptive fallbacks):
    PARALLEL -> depends on:
        - If stagnation predicted: SPECIALIST (skip intermediate)
        - If domain is CODING: LEAD_SUPPORT (pair programming works)
        - If domain is RESEARCH: SEQUENTIAL (depth over breadth)
        - Default: SEQUENTIAL

Key Inputs:
- StagnationPredictor: Trajectory analysis to detect early signs of failure
- TaskAnalysis: Domain and complexity information
- SuccessMemory: Historical performance for mode+domain combinations
- Agent metrics: DyLAN scores (importance, success_rate)

Usage:
    selector = AdaptiveFallbackSelector()
    fallback = selector.get_adaptive_fallback(
        current_mode=CollaborationMode.PARALLEL,
        context=FallbackContext(
            domains=["coding"],
            complexity="moderate",
            stagnation_level=PredictionLevel.MODERATE
        )
    )
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from core.intelligence.swarm.collaboration_modes import CollaborationMode

# Optional imports for enhanced functionality
try:
    from core.fsm.stagnation_predictor import PredictionLevel, StagnationPredictor

    PREDICTOR_AVAILABLE = True
except ImportError:
    PREDICTOR_AVAILABLE = False
    PredictionLevel = None

try:
    from core.memory_pkg.memory import SuccessMemory  # V2 via backward compat alias

    MEMORY_AVAILABLE = True
except ImportError:
    MEMORY_AVAILABLE = False

logger = logging.getLogger(__name__)


# =============================================================================
# Context for Adaptive Fallback Selection
# =============================================================================


@dataclass
class FallbackContext:
    """
    Context for adaptive fallback selection.

    Captures all relevant information for choosing the optimal fallback mode.
    """

    # Task information
    domains: list[str] = field(default_factory=list)
    complexity: str = "moderate"  # trivial, simple, moderate, complex, expert
    raw_input: str = ""

    # Stagnation signals
    stagnation_level: str | None = None  # none, low, moderate, high, critical
    messages_since_progress: int = 0

    # Agent state
    current_lead: str = "gemini"
    agent_metrics: dict[str, dict[str, float]] = field(default_factory=dict)

    # Execution history (this task)
    modes_tried: list[str] = field(default_factory=list)
    errors_encountered: list[str] = field(default_factory=list)

    # Optional: Historical performance
    domain_mode_performance: dict[str, dict[str, float]] = field(default_factory=dict)


@dataclass
class FallbackDecision:
    """Result of adaptive fallback selection."""

    fallback_mode: CollaborationMode | None
    reason: str
    confidence: float  # 0.0 - 1.0
    skip_intermediate: bool = False  # True if we're skipping the normal chain
    recommended_lead: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "fallback_mode": self.fallback_mode.value if self.fallback_mode else None,
            "reason": self.reason,
            "confidence": self.confidence,
            "skip_intermediate": self.skip_intermediate,
            "recommended_lead": self.recommended_lead,
        }


# =============================================================================
# Adaptive Fallback Rules
# =============================================================================

# Domain-aware fallback preferences
# Maps: current_mode -> domain -> preferred_fallback
DOMAIN_FALLBACK_PREFERENCES: dict[str, dict[str, str]] = {
    "parallel": {
        "coding": "lead_support",  # Pair programming pattern
        "research": "sequential",  # Depth over breadth
        "security": "red_blue",  # Adversarial review
        "architecture": "lead_support",  # Design leadership
        "default": "sequential",
    },
    "red_blue": {
        "coding": "lead_support",  # Collaborative refactor
        "security": "specialist",  # Expert deep-dive
        "default": "lead_support",
    },
    "lead_support": {
        "coding": "specialist",  # Single expert
        "research": "specialist",  # Deep research
        "default": "specialist",
    },
    "ping_pong": {
        "coding": "lead_support",  # Stable pair
        "research": "sequential",  # Ordered research
        "default": "sequential",
    },
    "sequential": {
        "default": "specialist"  # Terminal fallback
    },
    "specialist": {
        "default": None  # No further fallback
    },
}

# Stagnation-aware shortcuts
# When stagnation is high, skip intermediate modes
STAGNATION_SHORTCUTS: dict[str, str] = {
    "parallel": "specialist",  # Skip SEQUENTIAL
    "red_blue": "specialist",  # Skip LEAD_SUPPORT
    "lead_support": "specialist",  # Already close
    "ping_pong": "specialist",  # Skip SEQUENTIAL
    "sequential": "specialist",  # Already close
}


# =============================================================================
# Adaptive Fallback Selector
# =============================================================================


class AdaptiveFallbackSelector:
    """
    Selects fallback modes adaptively based on context.

    V8.8 (GROK-004): Replaces static fallback chains with context-aware selection.

    Selection factors (in order of priority):
    1. Stagnation level - High stagnation triggers shortcuts
    2. Domain affinity - Certain modes work better for certain domains
    3. Historical performance - What worked before for this domain
    4. Agent metrics - Which agent is better suited for the fallback
    5. Complexity - Simpler tasks may not need complex modes
    """

    def __init__(
        self, predictor: Optional["StagnationPredictor"] = None, success_memory: Optional["SuccessMemory"] = None
    ):
        """
        Initialize selector.

        Args:
            predictor: Optional StagnationPredictor for trajectory analysis
            success_memory: Optional SuccessMemory for historical performance
        """
        self.predictor = predictor
        self.success_memory = success_memory

    def get_adaptive_fallback(self, current_mode: CollaborationMode, context: FallbackContext) -> FallbackDecision:
        """
        Get the best fallback mode for the current context.

        Args:
            current_mode: Mode that just failed
            context: Contextual information for decision making

        Returns:
            FallbackDecision with recommended mode and reasoning
        """
        mode_key = current_mode.value.lower()

        # 1. Check if we're at terminal mode
        if mode_key == "specialist":
            return FallbackDecision(
                fallback_mode=None, reason="SPECIALIST is terminal mode - no further fallback", confidence=1.0
            )

        # 2. Stagnation shortcut - skip intermediate modes if stagnation is high
        if self._should_use_shortcut(context):
            shortcut_mode = STAGNATION_SHORTCUTS.get(mode_key)
            if shortcut_mode:
                return FallbackDecision(
                    fallback_mode=CollaborationMode.from_string(shortcut_mode),
                    reason=f"High stagnation ({context.stagnation_level}) - skipping to {shortcut_mode}",
                    confidence=0.85,
                    skip_intermediate=True,
                )

        # 3. Domain-aware selection
        domain_fallback = self._get_domain_fallback(mode_key, context.domains)
        if domain_fallback:
            return domain_fallback

        # 4. Historical performance (if SuccessMemory available)
        if self.success_memory and context.domains:
            history_fallback = self._get_history_fallback(mode_key, context)
            if history_fallback:
                return history_fallback

        # 5. Default to static chain
        return self._get_static_fallback(current_mode)

    def _should_use_shortcut(self, context: FallbackContext) -> bool:
        """Determine if stagnation warrants skipping intermediate modes."""
        if not context.stagnation_level:
            return False

        high_stagnation = context.stagnation_level in ("high", "critical")
        many_messages = context.messages_since_progress >= 4
        multiple_errors = len(context.errors_encountered) >= 2

        return high_stagnation or (many_messages and multiple_errors)

    def _get_domain_fallback(self, mode_key: str, domains: list[str]) -> FallbackDecision | None:
        """Get fallback based on domain affinity."""
        if not domains:
            return None

        mode_prefs = DOMAIN_FALLBACK_PREFERENCES.get(mode_key, {})

        # Check each domain (priority order)
        for domain in domains:
            domain_lower = domain.lower()
            if domain_lower in mode_prefs:
                fallback_key = mode_prefs[domain_lower]
                if fallback_key:
                    return FallbackDecision(
                        fallback_mode=CollaborationMode.from_string(fallback_key),
                        reason=f"Domain '{domain}' prefers {fallback_key} for fallback",
                        confidence=0.75,
                    )

        return None

    def _get_history_fallback(self, mode_key: str, context: FallbackContext) -> FallbackDecision | None:
        """Get fallback based on historical success for this domain."""
        if not self.success_memory:
            return None

        # Query SuccessMemory for best mode in this domain
        try:
            result = self.success_memory.get_best_mode_for_similar(
                query=context.raw_input or " ".join(context.domains),
                min_similarity=0.3,
                apply_decay=True,
                query_domains=context.domains,
            )

            if result:
                recommended_mode, task_id, similarity = result
                # Don't recommend the same mode that just failed
                if recommended_mode.lower() != mode_key:
                    return FallbackDecision(
                        fallback_mode=CollaborationMode.from_string(recommended_mode),
                        reason=f"Historical success: {recommended_mode} worked for similar tasks (sim={similarity:.2f})",
                        confidence=min(0.9, 0.5 + similarity),
                    )
        except Exception as e:
            logger.debug(f"SuccessMemory lookup failed: {e}")

        return None

    def _get_static_fallback(self, current_mode: CollaborationMode) -> FallbackDecision:
        """Fall back to the static chain."""
        static_fallback = current_mode.fallback_mode

        if static_fallback:
            return FallbackDecision(
                fallback_mode=static_fallback,
                reason=f"Static fallback chain: {current_mode.value} -> {static_fallback.value}",
                confidence=0.6,
            )

        return FallbackDecision(
            fallback_mode=None, reason=f"No fallback available for {current_mode.value}", confidence=1.0
        )

    def update_with_prediction(self, context: FallbackContext, messages: list[str]) -> FallbackContext:
        """
        Update context with StagnationPredictor analysis.

        Args:
            context: Current context
            messages: Recent messages for trajectory analysis

        Returns:
            Updated context with stagnation prediction
        """
        if not PREDICTOR_AVAILABLE or not self.predictor:
            return context

        try:
            for msg in messages:
                self.predictor.add_message(msg)

            prediction = self.predictor.predict()
            context.stagnation_level = prediction.level.value
            context.messages_since_progress = len(messages)

        except Exception as e:
            logger.debug(f"StagnationPredictor error: {e}")

        return context


# =============================================================================
# Singleton for Global Access
# =============================================================================

_adaptive_fallback_selector: AdaptiveFallbackSelector | None = None
_selector_lock = None


def get_adaptive_fallback_selector() -> AdaptiveFallbackSelector:
    """Get or create the global AdaptiveFallbackSelector singleton."""
    global _adaptive_fallback_selector, _selector_lock

    if _selector_lock is None:
        import threading

        _selector_lock = threading.Lock()

    if _adaptive_fallback_selector is None:
        with _selector_lock:
            if _adaptive_fallback_selector is None:
                # Initialize with optional components
                predictor = None
                memory = None

                if PREDICTOR_AVAILABLE:
                    try:
                        from core.fsm.stagnation_predictor import StagnationPredictor

                        predictor = StagnationPredictor()
                    except Exception:
                        pass

                if MEMORY_AVAILABLE:
                    try:
                        from pathlib import Path

                        from core.memory_pkg.memory import SuccessMemory  # V2 via backward compat alias

                        nexus_root = Path(__file__).parent.parent.parent
                        memory = SuccessMemory(nexus_root)
                    except Exception:
                        pass

                _adaptive_fallback_selector = AdaptiveFallbackSelector(predictor=predictor, success_memory=memory)

    return _adaptive_fallback_selector


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "AdaptiveFallbackSelector",
    "FallbackContext",
    "FallbackDecision",
    "get_adaptive_fallback_selector",
    "DOMAIN_FALLBACK_PREFERENCES",
    "STAGNATION_SHORTCUTS",
]
