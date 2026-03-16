"""
NEXUS V12.4 P5.1 - Task Router Module

Extracted from orchestration_v7.py (Phase 2 of decomposition).

Provides task routing logic including fast path detection for trivial inputs.
Centralizes routing decisions for the orchestrator.

Usage:
    router = TaskRouter()
    if router.is_fast_path(user_input):
        response = router.handle_fast_path(user_input)
        # ... direct response without HiveMind/Swarm

Phase 2 extraction (low-medium risk, pure logic).
"""

from dataclasses import dataclass
from enum import Enum

from core.fsm.states import OrchestratorState


class RouteType(Enum):
    """Types of routing decisions."""

    FAST_PATH = "fast_path"  # Direct response, no agent invocation
    SIMPLE = "simple"  # Single agent, direct execution
    MODERATE = "moderate"  # Swarm or Brainstorming
    COMPLEX = "complex"  # HiveMind multi-phase processing
    SWARM = "swarm"  # Explicit swarm mode
    ERROR = "error"  # Error handling


@dataclass
class RouteDecision:
    """
    Routing decision for a task.

    Attributes:
        route_type: Type of route (FAST_PATH, SIMPLE, etc.)
        reason: Human-readable explanation
        metadata: Additional routing information
    """

    route_type: RouteType
    reason: str = ""
    metadata: dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

    @property
    def is_fast_path(self) -> bool:
        """Check if this is a fast path route."""
        return self.route_type == RouteType.FAST_PATH


class TaskRouter:
    """
    Task routing logic for orchestrator.

    Implements fast path detection and routing decisions.

    Responsibilities:
    - Detect trivial inputs (greetings, commands)
    - Provide fast path responses
    - Route decisions based on input characteristics

    V8.8: Extracted from OrchestratorV7 as part of P5.1 decomposition.
    """

    def __init__(self):
        """Initialize task router."""
        # Fast path patterns (instant commands)
        self._instant_patterns = ["/help", "/status", "/exit", "/quit", "help", "status", "quit", "exit"]

        # Fast path patterns (conversational trivial)
        self._trivial_patterns = [
            "hello",
            "hi",
            "hey",
            "bonjour",
            "salut",
            "bye",
            "goodbye",
            "au revoir",
            "ciao",
            "ok",
            "okay",
            "thanks",
            "merci",
            "thank you",
            "test",
            "ping",
            "pong",
        ]

    def is_fast_path(self, user_input: str | None) -> bool:
        """
        Check if input should use fast path.

        Fast path is used for trivial inputs that don't require
        agent invocation (greetings, instant commands, etc.).

        Args:
            user_input: User input string

        Returns:
            True if fast path should be used, False otherwise

        Examples:
            >>> router = TaskRouter()
            >>> router.is_fast_path("hello")
            True
            >>> router.is_fast_path("implement authentication")
            False
        """
        if not user_input:
            return False

        import re

        input_stripped = user_input.strip()
        input_lower = input_stripped.lower()

        # Check slash-commands (always instant regardless of length)
        slash_commands = [cmd for cmd in self._instant_patterns if cmd.startswith("/")]
        if any(cmd in input_lower for cmd in slash_commands):
            return True

        # Check word-based instant commands only when input is short and standalone
        # (prevents "help" matching inside "I need help implementing something complex")
        word_commands = [cmd for cmd in self._instant_patterns if not cmd.startswith("/")]
        if len(input_lower) < 30 and any(
            re.search(r"^\s*" + re.escape(cmd) + r"\s*$", input_lower) for cmd in word_commands
        ):
            return True

        # Check conversational trivial (simple greetings/acknowledgments)
        # Only fast path if input is short AND trivial pattern appears as whole word
        # Use whole-word match to avoid false positives (e.g. "hi" in "this")
        if len(input_lower) >= 50:
            return False

        trivial_match = any(
            re.search(r"\b" + re.escape(pattern) + r"\b", input_lower) for pattern in self._trivial_patterns
        )
        return trivial_match

    def handle_fast_path(self, user_input: str) -> str:
        """
        Handle fast path input and generate direct response.

        Provides simple responses for trivial inputs without
        invoking HiveMind or Swarm engines.

        Args:
            user_input: Trivial user input

        Returns:
            Direct response string
        """
        input_lower = user_input.strip().lower()

        # Greetings
        if any(g in input_lower for g in ["hello", "hi", "hey", "bonjour", "salut"]):
            return "Hello! I'm NEXUS, your multi-agent orchestrator. How can I help you today?"

        # Farewells
        if any(f in input_lower for f in ["bye", "goodbye", "au revoir", "ciao"]):
            return "Goodbye! Feel free to return anytime."

        # Acknowledgments
        if any(a in input_lower for a in ["ok", "okay", "thanks", "merci", "thank you"]):
            return "You're welcome! Let me know if you need anything else."

        # Test/ping
        if any(t in input_lower for t in ["test", "ping", "pong"]):
            return "Pong! NEXUS is responsive."

        # Instant commands (basic fallback)
        if any(cmd in input_lower for cmd in ["help", "status"]):
            return "Command acknowledged. Processing..."

        # Default for other fast path inputs
        return "I'm here and ready to assist. What would you like to work on?"

    def determine_route(self, user_input: str | None, state: OrchestratorState) -> RouteDecision:
        """
        Determine routing decision for a task.

        Analyzes input and current state to decide routing strategy.

        Args:
            user_input: User input string
            state: Current orchestrator state

        Returns:
            RouteDecision with routing type and metadata
        """
        # No input -> no routing
        if not user_input:
            return RouteDecision(route_type=RouteType.ERROR, reason="No user input provided")

        # Fast path check
        if self.is_fast_path(user_input):
            return RouteDecision(
                route_type=RouteType.FAST_PATH,
                reason="Trivial input detected (greeting/command)",
                metadata={"input_length": len(user_input)},
            )

        # Default: delegate to complexity analysis in handlers
        return RouteDecision(
            route_type=RouteType.MODERATE,
            reason="Requires complexity analysis",
            metadata={"input_length": len(user_input)},
        )


# Module exports
__all__ = [
    "TaskRouter",
    "RouteDecision",
    "RouteType",
]
