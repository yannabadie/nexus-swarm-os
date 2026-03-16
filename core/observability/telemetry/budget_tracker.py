"""
NEXUS Budget Tracker - V12.4 COGNITIVE BOOST

Financial circuit breaker to prevent runaway API costs.
Tracks token usage and enforces daily spending limits.

Usage:
    tracker = BudgetTracker(config, workspace_path)
    tracker.track_cost("claude-opus", input_tokens=1000, output_tokens=500)
    tracker.check_budget()  # Raises BudgetExceededError if over limit

Pricing (Feb 2026 - OFFICIAL, verified 2026-02-26):
    Claude Opus 4.6:    $5/1M input, $25/1M output
                        $6.25/1M cache write, $0.50/1M cache read
    Claude Sonnet 4.5:  $3/1M input, $15/1M output
                        $3.75/1M cache write, $0.30/1M cache read
    Claude Haiku 4.5:   $1/1M input, $5/1M output
                        $1.25/1M cache write, $0.10/1M cache read
    Gemini 3 Pro:       $2/1M input, $12/1M output (no caching)
    Gemini 2.5 Flash:   $0.30/1M input, $2.50/1M output (no caching)
"""

import json
import logging
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from threading import Lock

_logger = logging.getLogger(__name__)

# =============================================================================
# PRICING CONSTANTS (Feb 2026)
# =============================================================================

# Cost per 1 MILLION tokens (USD)
# Official pricing as of Feb 2026
# Sources:
#   Anthropic: platform.claude.com/docs/en/about-claude/pricing
#   Google: ai.google.dev/gemini-api/docs/pricing
# Note: Anthropic cache formula: write = 1.25x input (5min TTL), read = 0.1x input
# Last verified: 2026-02-26
PRICING = {
    # Claude models (Opus 4.6, Sonnet 4.5, Haiku 4.5) - WITH PROMPT CACHING
    "claude-opus-4-6-20250116": {
        "input": 5.00,  # $5/MTok (CORRECTED from 15.00)
        "output": 25.00,  # $25/MTok (CORRECTED from 75.00)
        "cache_creation": 6.25,  # $6.25/MTok (25% premium over input)
        "cache_read": 0.50,  # $0.50/MTok (90% savings vs input)
    },
    "claude-opus-4-6": {
        "input": 5.00,
        "output": 25.00,
        "cache_creation": 6.25,
        "cache_read": 0.50,
    },
    "claude-opus-4-5-20251101": {  # Legacy
        "input": 5.00,
        "output": 25.00,
        "cache_creation": 6.25,
        "cache_read": 0.50,
    },
    "claude-opus": {
        "input": 5.00,
        "output": 25.00,
        "cache_creation": 6.25,
        "cache_read": 0.50,
    },
    "claude-sonnet-4-6-20260217": {
        "input": 3.00,  # $3/MTok
        "output": 15.00,  # $15/MTok
        "cache_creation": 3.75,  # $3.75/MTok (1.25x input, 5min TTL)
        "cache_read": 0.30,  # $0.30/MTok (0.1x input)
    },
    "claude-sonnet-4-6": {
        "input": 3.00,
        "output": 15.00,
        "cache_creation": 3.75,
        "cache_read": 0.30,
    },
    "claude-sonnet-4-5-20250929": {
        "input": 3.00,
        "output": 15.00,
        "cache_creation": 3.75,
        "cache_read": 0.30,
    },
    "claude-sonnet": {
        "input": 3.00,
        "output": 15.00,
        "cache_creation": 3.75,
        "cache_read": 0.30,
    },
    "claude-haiku-4-5-20251001": {
        "input": 1.00,  # $1/MTok
        "output": 5.00,  # $5/MTok
        "cache_creation": 1.25,  # $1.25/MTok (1.25x input)
        "cache_read": 0.10,  # $0.10/MTok (0.1x input)
    },
    "claude-haiku": {
        "input": 1.00,
        "output": 5.00,
        "cache_creation": 1.25,
        "cache_read": 0.10,
    },
    # Gemini models (no prompt caching as of Feb 2026)
    "gemini-3.1-pro-preview": {
        "input": 2.00,  # $2/MTok (ai.google.dev, 2026-02-19)
        "output": 12.00,  # $12/MTok
    },
    "gemini-3.1-pro": {"input": 2.00, "output": 12.00},
    "gemini-3-pro-preview": {"input": 2.00, "output": 12.00},
    "gemini-3-pro": {"input": 2.00, "output": 12.00},
    "gemini-pro": {"input": 2.00, "output": 12.00},
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
    "gemini-3-flash": {
        "input": 0.50,  # $0.50/MTok (CORRECTED from 0.075)
        "output": 3.00,  # $3/MTok (CORRECTED from 0.30)
    },
    "gemini-flash": {"input": 0.30, "output": 2.50},  # Alias (2.5-flash)
    # Local models (zero cost)
    "ollama": {"input": 0.0, "output": 0.0},
    "llama3.1": {"input": 0.0, "output": 0.0},
    # Default fallback (conservative estimate)
    "default": {"input": 5.00, "output": 20.00},
}

# Warning thresholds (percentage of limit)
BUDGET_WARNING_THRESHOLD = 0.80  # 80% -> warning
BUDGET_CRITICAL_THRESHOLD = 0.90  # 90% -> critical alert
BUDGET_LIMIT_THRESHOLD = 1.00  # 100% -> hard stop


# =============================================================================
# EXCEPTIONS
# =============================================================================


class BudgetExceededError(Exception):
    """Raised when daily budget limit is exceeded."""

    def __init__(self, spent: float, limit: float, message: str = None):
        self.spent = spent
        self.limit = limit
        self.message = message or f"Budget exceeded: ${spent:.2f} / ${limit:.2f} limit"
        super().__init__(self.message)


class BudgetWarning(Warning):
    """Warning when approaching budget limit."""

    pass


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class BudgetState:
    """Persisted budget state."""

    spent_today_usd: float = 0.0
    reset_date: str = ""  # ISO date (YYYY-MM-DD)
    total_lifetime_usd: float = 0.0
    api_calls_today: int = 0
    last_updated: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "BudgetState":
        return cls(
            spent_today_usd=data.get("spent_today_usd", 0.0),
            reset_date=data.get("reset_date", ""),
            total_lifetime_usd=data.get("total_lifetime_usd", 0.0),
            api_calls_today=data.get("api_calls_today", 0),
            last_updated=data.get("last_updated", ""),
        )


@dataclass
class CostRecord:
    """Record of a single API cost."""

    timestamp: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


# =============================================================================
# BUDGET TRACKER
# =============================================================================


class BudgetTracker:
    """
    Tracks API costs and enforces budget limits.

    Thread-safe with file-based persistence.
    Resets daily at local midnight.
    """

    def __init__(
        self,
        config=None,
        workspace_path: Path | None = None,
        budget_file: Path | None = None,
    ):
        """
        Initialize BudgetTracker.

        Args:
            config: NEXUS config (uses budget_limit_usd if available)
            workspace_path: Path to workspace directory
            budget_file: Override budget state file path
        """
        self._lock = Lock()

        # Get budget limit from config
        self.limit_usd = 50.0  # Default
        if config:
            self.limit_usd = getattr(config, "budget_limit_usd", 50.0)

        # Set up persistence path
        if budget_file:
            self.budget_file = budget_file
        elif workspace_path:
            self.budget_file = Path(workspace_path) / ".nexus" / "budget.json"
        else:
            self.budget_file = Path("workspace/.nexus/budget.json")

        # Ensure directory exists
        self.budget_file.parent.mkdir(parents=True, exist_ok=True)

        # Load or initialize state
        self._state = self._load_state()

        # Check for daily reset
        self._check_daily_reset()

    def _load_state(self) -> BudgetState:
        """Load budget state from file."""
        if self.budget_file.exists():
            try:
                data = json.loads(self.budget_file.read_text(encoding="utf-8"))
                return BudgetState.from_dict(data)
            except (json.JSONDecodeError, KeyError):
                pass
        return BudgetState(reset_date=date.today().isoformat())

    def _save_state(self):
        """Save budget state to file."""
        self._state.last_updated = datetime.now().isoformat()
        try:
            self.budget_file.write_text(json.dumps(self._state.to_dict(), indent=2), encoding="utf-8")
        except Exception as e:
            _logger.warning("BudgetTracker save error: %s", e)

    def _check_daily_reset(self):
        """Reset counters if it's a new day."""
        today = date.today().isoformat()
        if self._state.reset_date != today:
            with self._lock:
                self._state.spent_today_usd = 0.0
                self._state.api_calls_today = 0
                self._state.reset_date = today
                self._save_state()

    def estimate_tokens(self, text: str) -> int:
        """
        Estimate token count from text.

        Uses approximate ratio of 4 characters per token.
        This is a rough estimate - actual tokenization varies by model.

        Args:
            text: Input text

        Returns:
            Estimated token count
        """
        if not text:
            return 0
        # Rough estimate: ~4 chars per token for English text
        return max(1, len(text) // 4)

    def get_model_pricing(self, model: str) -> dict[str, float]:
        """
        Get pricing for a model.

        Args:
            model: Model name or alias

        Returns:
            Dict with 'input' and 'output' prices per 1M tokens
        """
        model_lower = model.lower()

        # Try exact match first
        if model_lower in PRICING:
            return PRICING[model_lower]

        # Try partial matches
        for key, pricing in PRICING.items():
            if key in model_lower or model_lower in key:
                return pricing

        # Fallback to default
        return PRICING["default"]

    def calculate_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_creation_tokens: int = 0,
        cache_read_tokens: int = 0,
    ) -> float:
        """
        Calculate cost for an API call.

        Args:
            model: Model name
            input_tokens: Number of input tokens (non-cached)
            output_tokens: Number of output tokens
            cache_creation_tokens: Tokens written to prompt cache (Anthropic only)
            cache_read_tokens: Tokens read from prompt cache (Anthropic only)

        Returns:
            Cost in USD

        Note:
            Prompt caching (Anthropic Claude models):
            - Cache creation: 25% premium over input price
            - Cache read: 90% discount vs input price
            - Only Claude models support caching as of Feb 2026
        """
        pricing = self.get_model_pricing(model)

        # Base cost (non-cached tokens)
        input_cost = (input_tokens / 1_000_000) * pricing["input"]
        output_cost = (output_tokens / 1_000_000) * pricing["output"]

        # Prompt caching cost (Anthropic Claude models only)
        cache_creation_cost = 0.0
        cache_read_cost = 0.0

        if cache_creation_tokens > 0 and "cache_creation" in pricing:
            cache_creation_cost = (cache_creation_tokens / 1_000_000) * pricing["cache_creation"]

        if cache_read_tokens > 0 and "cache_read" in pricing:
            cache_read_cost = (cache_read_tokens / 1_000_000) * pricing["cache_read"]

        return input_cost + output_cost + cache_creation_cost + cache_read_cost

    def track_cost(
        self,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        input_text: str | None = None,
        output_text: str | None = None,
        cache_creation_tokens: int = 0,
        cache_read_tokens: int = 0,
    ) -> float:
        """
        Track cost of an API call.

        Can provide either token counts or text for estimation.

        Args:
            model: Model name
            input_tokens: Input token count (or 0 to estimate from text)
            output_tokens: Output token count (or 0 to estimate from text)
            input_text: Input text for estimation (if tokens not provided)
            output_text: Output text for estimation (if tokens not provided)
            cache_creation_tokens: Tokens written to prompt cache (Anthropic only)
            cache_read_tokens: Tokens read from prompt cache (Anthropic only)

        Returns:
            Cost in USD for this call

        Note:
            For Anthropic Claude models with prompt caching enabled:
            - cache_creation_tokens: First time seeing prompt content (25% premium)
            - cache_read_tokens: Subsequent uses of cached content (90% savings)
            - Regular input_tokens: Non-cacheable content
        """
        # Estimate tokens from text if not provided
        if input_tokens == 0 and input_text:
            input_tokens = self.estimate_tokens(input_text)
        if output_tokens == 0 and output_text:
            output_tokens = self.estimate_tokens(output_text)

        # Calculate cost (with cache metrics)
        cost = self.calculate_cost(model, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens)

        # Update state
        with self._lock:
            self._check_daily_reset()
            self._state.spent_today_usd += cost
            self._state.total_lifetime_usd += cost
            self._state.api_calls_today += 1
            self._save_state()

        return cost

    def get_budget_status(self) -> tuple[float, float, float]:
        """
        Get current budget status.

        Returns:
            Tuple of (spent_today, limit, percentage_used)
        """
        self._check_daily_reset()
        spent = self._state.spent_today_usd
        pct = (spent / self.limit_usd * 100) if self.limit_usd > 0 else 0
        return spent, self.limit_usd, pct

    def check_budget(self) -> bool:
        """
        Check if budget is exceeded.

        Returns:
            True if within budget

        Raises:
            BudgetExceededError: If budget limit exceeded
        """
        self._check_daily_reset()
        spent = self._state.spent_today_usd

        if spent >= self.limit_usd * BUDGET_LIMIT_THRESHOLD:
            raise BudgetExceededError(spent, self.limit_usd)

        return True

    def get_warning_level(self) -> str | None:
        """
        Get current warning level.

        Returns:
            "warning" at 80%, "critical" at 90%, None if under 80%
        """
        self._check_daily_reset()
        spent = self._state.spent_today_usd
        pct = spent / self.limit_usd if self.limit_usd > 0 else 0

        if pct >= BUDGET_CRITICAL_THRESHOLD:
            return "critical"
        elif pct >= BUDGET_WARNING_THRESHOLD:
            return "warning"
        return None

    def get_remaining(self) -> float:
        """Get remaining budget for today in USD."""
        self._check_daily_reset()
        return max(0, self.limit_usd - self._state.spent_today_usd)

    def get_stats(self) -> dict:
        """
        Get comprehensive budget statistics.

        Returns:
            Dict with current budget stats
        """
        self._check_daily_reset()
        spent, limit, pct = self.get_budget_status()

        return {
            "spent_today_usd": round(spent, 4),
            "limit_usd": limit,
            "remaining_usd": round(self.get_remaining(), 4),
            "percentage_used": round(pct, 2),
            "api_calls_today": self._state.api_calls_today,
            "total_lifetime_usd": round(self._state.total_lifetime_usd, 4),
            "reset_date": self._state.reset_date,
            "warning_level": self.get_warning_level(),
        }

    def reset_daily(self):
        """Manually reset daily counters (for testing or emergency)."""
        with self._lock:
            self._state.spent_today_usd = 0.0
            self._state.api_calls_today = 0
            self._state.reset_date = date.today().isoformat()
            self._save_state()

    def add_credit(self, amount_usd: float):
        """
        Add credit to today's budget (for emergency unlock).

        Args:
            amount_usd: Amount to add to limit for today
        """
        with self._lock:
            self.limit_usd += amount_usd
            self._save_state()


# =============================================================================
# MODULE-LEVEL FUNCTIONS
# =============================================================================

_tracker: BudgetTracker | None = None


def get_budget_tracker(config=None, workspace_path: Path | None = None) -> BudgetTracker:
    """Get or create the global budget tracker."""
    global _tracker
    if _tracker is None:
        _tracker = BudgetTracker(config, workspace_path)
    return _tracker


def reset_budget_tracker():
    """Reset the global budget tracker (for testing)."""
    global _tracker
    _tracker = None
