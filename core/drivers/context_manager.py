"""
Context Window Manager - Token budget and context utilization tracking.

V12.4 COGNITIVE BOOST - Task #41

Manages token budgets for LLM context windows. Tracks remaining capacity,
provides smart truncation of conversation history, and reports utilization
metrics. Prevents context overflow errors.

Model Context Windows:
- Claude Opus 4.5:     200K tokens
- Claude Sonnet 4.5:   200K tokens
- Gemini 3 Pro:        1M tokens
- Llama 3.1 (Ollama):  128K tokens

Usage:
    from core.drivers.context_manager import ContextManager

    ctx = ContextManager(model="claude-opus-4-6-20250116")
    ctx.add_message("system", system_prompt)     # ~2000 tokens
    ctx.add_message("user", user_input)          # ~500 tokens
    ctx.add_message("assistant", response)       # ~1000 tokens

    print(ctx.utilization)           # 0.0175 (1.75%)
    print(ctx.remaining_tokens)      # 196,500
    print(ctx.can_fit(5000))         # True

    # Smart truncation when approaching limit
    messages = ctx.get_truncated_history(reserve_tokens=4000)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Model Context Windows
# =============================================================================

# Known model context window sizes (tokens)
MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    # Claude models
    "claude-opus-4-6-20250116": 200_000,
    "claude-opus-4-6": 200_000,
    "claude-sonnet-4-6": 200_000,
    "claude-sonnet-4-5-20250929": 200_000,
    "claude-haiku-4-5-20251001": 200_000,
    # Gemini models
    "gemini-3.1-pro-preview": 1_000_000,
    "gemini-3-pro-preview": 1_000_000,
    "gemini-3-pro": 1_000_000,
    "gemini-2.5-pro-preview-05-06": 1_048_576,
    "gemini-2.0-flash": 1_048_576,
    # Ollama / local models
    "llama3.1": 128_000,
    "llama3.1:latest": 128_000,
    "codellama": 16_000,
    "codellama:latest": 16_000,
    "mistral": 32_000,
    "mistral:latest": 32_000,
}

DEFAULT_CONTEXT_WINDOW = 128_000

# Approximate characters per token (for estimation)
CHARS_PER_TOKEN = 4


# =============================================================================
# Types
# =============================================================================


@dataclass
class ContextMessage:
    """A message in the context window."""

    role: str  # "system", "user", "assistant", "tool"
    content: str
    token_count: int = 0
    pinned: bool = False  # Pinned messages are never truncated

    def __post_init__(self):
        if self.token_count == 0:
            self.token_count = estimate_tokens(self.content)

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "content_length": len(self.content),
            "token_count": self.token_count,
            "pinned": self.pinned,
        }


@dataclass
class ContextUtilization:
    """Context window utilization report."""

    model: str
    max_tokens: int
    used_tokens: int
    remaining_tokens: int
    utilization: float  # 0.0 - 1.0
    message_count: int
    pinned_tokens: int
    truncatable_tokens: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "used_tokens": self.used_tokens,
            "remaining_tokens": self.remaining_tokens,
            "utilization": round(self.utilization, 4),
            "message_count": self.message_count,
            "pinned_tokens": self.pinned_tokens,
            "truncatable_tokens": self.truncatable_tokens,
        }


# =============================================================================
# Token Estimation
# =============================================================================


def estimate_tokens(text: str) -> int:
    """
    Estimate token count from text.

    Uses a simple character-based heuristic (~4 chars per token).
    Not exact, but sufficient for budget tracking.

    Args:
        text: Input text

    Returns:
        Estimated token count
    """
    if not text:
        return 0
    return max(1, len(text) // CHARS_PER_TOKEN)


def get_context_window(model: str) -> int:
    """
    Get the context window size for a model.

    Args:
        model: Model name

    Returns:
        Context window in tokens
    """
    # Exact match first
    if model in MODEL_CONTEXT_WINDOWS:
        return MODEL_CONTEXT_WINDOWS[model]

    # Prefix match (e.g., "claude-opus" matches "claude-opus-4-5-...")
    model_lower = model.lower()
    for known_model, window in MODEL_CONTEXT_WINDOWS.items():
        if model_lower.startswith(known_model.split("-")[0]):
            return window

    return DEFAULT_CONTEXT_WINDOW


# =============================================================================
# Context Manager
# =============================================================================


class ContextManager:
    """
    Manages token budget and context window utilization for LLM conversations.

    Tracks messages, estimates token usage, and provides smart truncation
    when approaching the context limit.
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        max_tokens: int | None = None,
        reserve_tokens: int = 4000,
    ):
        """
        Initialize context manager.

        Args:
            model: Model name (determines context window size)
            max_tokens: Override context window size
            reserve_tokens: Tokens to reserve for response generation
        """
        self._model = model
        self._max_tokens = max_tokens or get_context_window(model)
        self._reserve_tokens = reserve_tokens
        self._messages: list[ContextMessage] = []

    @property
    def model(self) -> str:
        return self._model

    @property
    def max_tokens(self) -> int:
        return self._max_tokens

    @property
    def used_tokens(self) -> int:
        """Total tokens used by all messages."""
        return sum(m.token_count for m in self._messages)

    @property
    def remaining_tokens(self) -> int:
        """Tokens remaining in context window."""
        return max(0, self._max_tokens - self.used_tokens)

    @property
    def effective_remaining(self) -> int:
        """Remaining tokens minus reserve for response."""
        return max(0, self.remaining_tokens - self._reserve_tokens)

    @property
    def utilization(self) -> float:
        """Context window utilization (0.0 to 1.0)."""
        if self._max_tokens == 0:
            return 1.0
        return self.used_tokens / self._max_tokens

    @property
    def message_count(self) -> int:
        return len(self._messages)

    def add_message(
        self,
        role: str,
        content: str,
        *,
        token_count: int = 0,
        pinned: bool = False,
    ) -> ContextMessage:
        """
        Add a message to the context.

        Args:
            role: Message role ("system", "user", "assistant", "tool")
            content: Message content
            token_count: Exact token count (0 = estimate)
            pinned: If True, message won't be truncated

        Returns:
            The added ContextMessage
        """
        msg = ContextMessage(
            role=role,
            content=content,
            token_count=token_count,
            pinned=pinned,
        )
        self._messages.append(msg)
        return msg

    def can_fit(self, tokens: int) -> bool:
        """
        Check if additional tokens can fit in the context.

        Args:
            tokens: Number of tokens to check

        Returns:
            True if tokens fit within effective remaining
        """
        return tokens <= self.effective_remaining

    def get_messages(self) -> list[ContextMessage]:
        """Get all messages."""
        return list(self._messages)

    def get_truncated_history(
        self,
        reserve_tokens: int | None = None,
    ) -> list[ContextMessage]:
        """
        Get conversation history, truncating oldest non-pinned messages
        if context window is exceeded.

        Args:
            reserve_tokens: Override reserve tokens

        Returns:
            List of messages that fit within budget
        """
        reserve = reserve_tokens if reserve_tokens is not None else self._reserve_tokens
        budget = self._max_tokens - reserve

        if self.used_tokens <= budget:
            return list(self._messages)

        # Start with pinned messages (always included)
        pinned = [m for m in self._messages if m.pinned]
        unpinned = [m for m in self._messages if not m.pinned]

        pinned_tokens = sum(m.token_count for m in pinned)
        remaining_budget = budget - pinned_tokens

        if remaining_budget <= 0:
            return pinned

        # Keep most recent unpinned messages that fit
        kept = []
        used = 0
        for msg in reversed(unpinned):
            if used + msg.token_count <= remaining_budget:
                kept.insert(0, msg)
                used += msg.token_count
            else:
                break

        # Merge: pinned first (in original order), then kept unpinned
        result = []
        pinned_set = set(id(m) for m in pinned)
        kept_set = set(id(m) for m in kept)

        for msg in self._messages:
            if id(msg) in pinned_set or id(msg) in kept_set:
                result.append(msg)

        return result

    def clear(self) -> None:
        """Clear all messages."""
        self._messages.clear()

    def get_utilization_report(self) -> ContextUtilization:
        """Get detailed context utilization report."""
        pinned_tokens = sum(m.token_count for m in self._messages if m.pinned)
        truncatable = sum(m.token_count for m in self._messages if not m.pinned)

        return ContextUtilization(
            model=self._model,
            max_tokens=self._max_tokens,
            used_tokens=self.used_tokens,
            remaining_tokens=self.remaining_tokens,
            utilization=self.utilization,
            message_count=self.message_count,
            pinned_tokens=pinned_tokens,
            truncatable_tokens=truncatable,
        )

    def to_dict(self) -> dict[str, Any]:
        """Export context manager state."""
        return {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "used_tokens": self.used_tokens,
            "remaining_tokens": self.remaining_tokens,
            "utilization": round(self.utilization, 4),
            "message_count": self.message_count,
            "reserve_tokens": self._reserve_tokens,
        }
