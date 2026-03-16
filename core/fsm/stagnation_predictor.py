"""
StagnationPredictor - Proactive Stagnation Detection via Trajectory Analysis.

NEXUS V8.4.4 - Blind Spot Remediation Phase 5

The existing StagnationDetector is REACTIVE - it detects stagnation AFTER
3+ similar messages have already occurred. This wastes cycles.

StagnationPredictor is PROACTIVE - it predicts stagnation BEFORE it happens
using leading indicators and trajectory analysis.

Leading Indicators (from web research):
- "let me think" / "réfléchissons" -> hesitation signal
- "we should consider" / "on pourrait" -> indecision signal
- "I agree but" / "d'accord mais" -> non-commitment signal
- "perhaps" / "peut-être" -> uncertainty signal

Trajectory Signals:
- Message length decreasing over time -> running out of ideas
- Similarity increasing over time -> converging without action
- Tool mentions without tool use -> discussing instead of doing

Action Thresholds (V12.4 COGNITIVE BOOST - lowered for proactivity):
- < 0.15: CONTINUE (normal)
- 0.15-0.25: MONITOR_CLOSELY
- 0.25-0.40: NUDGE_ACTION (gentle reminder)
- > 0.40: INTERVENE (full intervention)

Author: Claude (NEXUS V8.4.4)
Date: 2025-12-10
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from enum import Enum

# =============================================================================
# PREDICTION LEVELS
# =============================================================================


class PredictionLevel(Enum):
    """Stagnation prediction levels with recommended actions."""

    CONTINUE = "continue"  # < 0.15 - Normal operation
    MONITOR = "monitor"  # 0.15-0.25 - Watch closely
    NUDGE = "nudge"  # 0.25-0.40 - Gentle reminder
    INTERVENE = "intervene"  # > 0.40 - Full intervention


# =============================================================================
# LEADING INDICATORS
# =============================================================================

# Pattern -> weight (higher = more stagnation signal)
LEADING_INDICATORS_EN = [
    (r"\blet me think\b", 0.15),
    (r"\bwe should consider\b", 0.15),
    (r"\bi agree but\b", 0.20),
    (r"\bperhaps\b", 0.10),
    (r"\bmaybe\b", 0.10),
    (r"\bI'm not sure\b", 0.15),
    (r"\blet's discuss\b", 0.20),
    (r"\bwhat if\b", 0.10),
    (r"\bwe could\b", 0.10),
    (r"\bon the other hand\b", 0.15),
]

LEADING_INDICATORS_FR = [
    (r"\bréfléchissons\b", 0.15),
    (r"\bon pourrait\b", 0.15),
    (r"\bd'accord mais\b", 0.20),
    (r"\bpeut-être\b", 0.10),
    (r"\bje pense que\b", 0.10),
    (r"\bje ne suis pas sûr\b", 0.15),
    (r"\bdiscutons\b", 0.20),
    (r"\bet si\b", 0.10),
    (r"\bon devrait\b", 0.10),
    (r"\bd'un autre côté\b", 0.15),
]

LEADING_INDICATORS = LEADING_INDICATORS_EN + LEADING_INDICATORS_FR

# Tool mention patterns (discussing tools without using them)
TOOL_MENTION_PATTERNS = [
    r"\bread\b.*\bfile\b",
    r"\bwrite\b.*\bfile\b",
    r"\bedit\b",
    r"\bgrep\b",
    r"\bglob\b",
    r"\bbash\b",
    r"\blire\b.*\bfichier\b",
    r"\bécrire\b",
    r"\bmodifier\b",
    r"\brechercher\b",
]


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class MessageMetrics:
    """Metrics computed for a single message."""

    length: int
    has_tool_use: bool
    has_tool_mention: bool
    leading_indicator_score: float
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class PredictionResult:
    """Result of stagnation prediction."""

    probability: float  # 0.0 to 1.0
    level: PredictionLevel
    factors: dict[str, float]  # Which factors contributed
    recommendation: str
    nudge_message: str | None = None


# =============================================================================
# STAGNATION PREDICTOR
# =============================================================================


class StagnationPredictor:
    """
    Proactive stagnation predictor using trajectory analysis.

    Unlike StagnationDetector (reactive), this predicts stagnation
    BEFORE it happens using leading indicators and message patterns.

    Usage:
        predictor = StagnationPredictor()

        # Add messages as they come in
        predictor.add_message("Let me think about this approach...")
        predictor.add_message("Maybe we should consider reading the file")

        # Check prediction
        result = predictor.predict()
        if result.level == PredictionLevel.NUDGE:
            # Send gentle reminder
            ...
    """

    # Thresholds for prediction levels
    # V12.4 COGNITIVE BOOST: Lowered thresholds for proactive detection
    # Original (too conservative): 0.4, 0.6, 0.8
    # Adjusted for earlier detection of stagnation signals
    MONITOR_THRESHOLD = 0.15
    NUDGE_THRESHOLD = 0.25
    INTERVENE_THRESHOLD = 0.40

    def __init__(self, window_size: int = 5, *, enable_trajectory: bool = True, enable_indicators: bool = True):
        """
        Initialize predictor.

        Args:
            window_size: Number of messages to analyze
            enable_trajectory: Enable trajectory analysis (length, similarity trends)
            enable_indicators: Enable leading indicator detection
        """
        self._window_size = window_size
        self._enable_trajectory = enable_trajectory
        self._enable_indicators = enable_indicators

        # Message history with metrics
        self._messages: list[str] = []
        self._metrics: list[MessageMetrics] = []

        # Compiled patterns for efficiency
        self._indicator_patterns = [
            (re.compile(pattern, re.IGNORECASE), weight) for pattern, weight in LEADING_INDICATORS
        ]
        self._tool_mention_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in TOOL_MENTION_PATTERNS]

    def add_message(self, content: str, has_tool_use: bool = False) -> None:
        """
        Add a message to the analysis window.

        Args:
            content: Message content
            has_tool_use: Whether the message contained actual tool use
        """
        normalized = content.lower().strip()
        self._messages.append(normalized)

        # Compute metrics
        metrics = MessageMetrics(
            length=len(content),
            has_tool_use=has_tool_use,
            has_tool_mention=self._has_tool_mention(content),
            leading_indicator_score=self._compute_indicator_score(content),
        )
        self._metrics.append(metrics)

        # Maintain window
        if len(self._messages) > self._window_size:
            self._messages = self._messages[-self._window_size :]
            self._metrics = self._metrics[-self._window_size :]

    def predict(self) -> PredictionResult:
        """
        Predict likelihood of stagnation.

        Returns:
            PredictionResult with probability, level, and recommendations
        """
        if len(self._messages) < 2:
            return PredictionResult(
                probability=0.0,
                level=PredictionLevel.CONTINUE,
                factors={},
                recommendation="Not enough data for prediction",
            )

        factors = {}
        total_score = 0.0

        # Factor 1: Leading indicators in recent messages
        # V12.4 COGNITIVE BOOST: Increased weights for proactive detection
        # Original weights (0.35, 0.35, 0.15, 0.15) were too conservative
        if self._enable_indicators:
            indicator_score = self._compute_indicator_factor()
            factors["leading_indicators"] = indicator_score
            total_score += indicator_score * 0.70  # 70% weight (was 35%)

        # Factor 2: Trajectory analysis
        if self._enable_trajectory:
            trajectory_score = self._compute_trajectory_factor()
            factors["trajectory"] = trajectory_score
            total_score += trajectory_score * 0.70  # 70% weight (was 35%)

        # Factor 3: Tool mention without use
        tool_score = self._compute_tool_factor()
        factors["tool_mention_no_use"] = tool_score
        total_score += tool_score * 0.30  # 30% weight (was 15%)

        # Factor 4: Similarity increase
        similarity_score = self._compute_similarity_factor()
        factors["similarity_increase"] = similarity_score
        total_score += similarity_score * 0.30  # 30% weight (was 15%)

        # Clamp probability
        probability = min(total_score, 1.0)

        # Determine level
        if probability >= self.INTERVENE_THRESHOLD:
            level = PredictionLevel.INTERVENE
        elif probability >= self.NUDGE_THRESHOLD:
            level = PredictionLevel.NUDGE
        elif probability >= self.MONITOR_THRESHOLD:
            level = PredictionLevel.MONITOR
        else:
            level = PredictionLevel.CONTINUE

        # Generate recommendation and nudge
        recommendation, nudge = self._generate_recommendation(level, factors)

        return PredictionResult(
            probability=probability, level=level, factors=factors, recommendation=recommendation, nudge_message=nudge
        )

    # -------------------------------------------------------------------------
    # Factor Computations
    # -------------------------------------------------------------------------

    def _compute_indicator_score(self, text: str) -> float:
        """Compute leading indicator score for a single message."""
        score = 0.0
        for pattern, weight in self._indicator_patterns:
            if pattern.search(text):
                score += weight
        return min(score, 1.0)

    def _compute_indicator_factor(self) -> float:
        """Compute leading indicator factor over recent messages."""
        if not self._metrics:
            return 0.0

        recent = self._metrics[-min(3, len(self._metrics)) :]
        avg_score = sum(m.leading_indicator_score for m in recent) / len(recent)
        return avg_score

    def _compute_trajectory_factor(self) -> float:
        """
        Compute trajectory factor based on message length and pattern.

        Decreasing length = running out of ideas = stagnation signal
        """
        if len(self._metrics) < 3:
            return 0.0

        lengths = [m.length for m in self._metrics[-3:]]

        # Check for consistently decreasing length
        if lengths[2] < lengths[1] < lengths[0]:
            # Strong decreasing signal
            return 0.7
        elif lengths[2] < lengths[0]:
            # Mild decreasing signal
            return 0.3

        return 0.0

    def _compute_tool_factor(self) -> float:
        """
        Compute tool mention without use factor.

        Mentioning tools without using them = talking instead of doing
        """
        if len(self._metrics) < 2:
            return 0.0

        recent = self._metrics[-3:]
        mention_count = sum(1 for m in recent if m.has_tool_mention and not m.has_tool_use)

        if mention_count >= 2:
            return 0.8
        elif mention_count >= 1:
            return 0.4
        return 0.0

    def _has_tool_mention(self, text: str) -> bool:
        """Check if text mentions tools."""
        return any(pattern.search(text) for pattern in self._tool_mention_patterns)

    def _compute_similarity_factor(self) -> float:
        """
        Compute similarity increase factor.

        Increasing similarity over time = converging without action
        """
        if len(self._messages) < 3:
            return 0.0

        recent = self._messages[-3:]

        # Compute pairwise similarities
        sim_01 = SequenceMatcher(None, recent[0], recent[1]).ratio()
        sim_12 = SequenceMatcher(None, recent[1], recent[2]).ratio()

        # Increasing similarity is a stagnation signal
        if sim_12 > sim_01 and sim_12 > 0.6:
            return min(sim_12 * 0.8, 1.0)
        elif sim_12 > 0.7:
            return 0.5

        return 0.0

    # -------------------------------------------------------------------------
    # Recommendations
    # -------------------------------------------------------------------------

    def _generate_recommendation(self, level: PredictionLevel, factors: dict[str, float]) -> tuple[str, str | None]:
        """Generate recommendation and nudge message based on prediction."""

        if level == PredictionLevel.CONTINUE:
            return "Normal operation, no action needed", None

        if level == PredictionLevel.MONITOR:
            return "Monitor closely, potential stagnation forming", None

        # Find top contributing factor
        top_factor = max(factors.items(), key=lambda x: x[1]) if factors else ("unknown", 0)

        if level == PredictionLevel.NUDGE:
            nudge = self._get_nudge_message(top_factor[0])
            return f"Send gentle reminder (top factor: {top_factor[0]})", nudge

        # INTERVENE
        nudge = self._get_intervention_message(top_factor[0])
        return f"Full intervention needed (top factor: {top_factor[0]})", nudge

    def _get_nudge_message(self, factor: str) -> str:
        """Get a gentle nudge message based on the factor."""
        nudges = {
            "leading_indicators": (
                "💡 I notice some hesitation. Feel free to take action when ready - what tool would help us progress?"
            ),
            "trajectory": (
                "💡 Our messages are getting shorter. Let's move to concrete action - what's the next step?"
            ),
            "tool_mention_no_use": (
                "💡 We've discussed using tools. Shall we actually execute one? Which would be most helpful right now?"
            ),
            "similarity_increase": ("💡 We seem to be converging on an approach. Ready to take action?"),
        }
        return nudges.get(factor, "💡 Let's move forward with a concrete action.")

    def _get_intervention_message(self, factor: str) -> str:
        """Get a full intervention message."""
        return """
---
## [warning]️ PROACTIVE STAGNATION WARNING

**Analysis shows high probability of unproductive discussion loop.**

**Detected signals:**
- Leading indicators of hesitation
- Decreasing message engagement
- Tool discussion without execution

**REQUIRED ACTION:**
Execute a concrete tool use NOW or explicitly decide to move on.

**Example:**
```
<tool_use name="read">
{"file_path": "path/to/relevant/file"}
</tool_use>
```

---
"""

    # -------------------------------------------------------------------------
    # State Management
    # -------------------------------------------------------------------------

    def reset(self) -> None:
        """Reset predictor state."""
        self._messages.clear()
        self._metrics.clear()

    def get_stats(self) -> dict:
        """Get predictor statistics for debugging."""
        return {
            "message_count": len(self._messages),
            "recent_lengths": [m.length for m in self._metrics[-3:]] if self._metrics else [],
            "recent_indicator_scores": [m.leading_indicator_score for m in self._metrics[-3:]] if self._metrics else [],
            "tool_mentions_without_use": sum(1 for m in self._metrics if m.has_tool_mention and not m.has_tool_use),
        }


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    "StagnationPredictor",
    "PredictionLevel",
    "PredictionResult",
    "MessageMetrics",
    "LEADING_INDICATORS",
]
