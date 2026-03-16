"""
NEXUS V8.0 - Strategy Blacklist

Anti-circular retry mechanism that tracks failed strategies.
Prevents the system from trying the same failing approach repeatedly.

Features:
- Tracks failed strategies with their failure context
- Similarity detection to catch variations of the same strategy
- Automatic expiration of old entries
- Suggestion engine for alternative approaches

Usage:
    blacklist = StrategyBlacklist()

    # Before trying a strategy
    if blacklist.is_blacklisted(strategy):
        # Try something else
        alternatives = blacklist.suggest_alternatives(strategy)

    # After failure
    blacklist.add_failed_strategy(strategy, failure_reason, diagnosis)

    # After success (clear related entries)
    blacklist.mark_success(strategy)
"""

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class FailureCategory(Enum):
    """Categories of strategy failures."""

    TIMEOUT = "timeout"
    CAPABILITY_MISSING = "capability_missing"
    HALLUCINATION = "hallucination"
    WRONG_APPROACH = "wrong_approach"
    TOOL_ERROR = "tool_error"
    RESOURCE_EXCEEDED = "resource_exceeded"
    LOGIC_ERROR = "logic_error"
    STAGNATION = "stagnation"  # V8.0: From StagnationDetector
    UNKNOWN = "unknown"


@dataclass
class BlacklistedStrategy:
    """A strategy that has been blacklisted."""

    strategy_hash: str
    strategy_description: str
    failure_category: FailureCategory
    failure_reason: str
    diagnosis: str
    attempt_count: int = 1
    first_failure: datetime = field(default_factory=datetime.now)
    last_failure: datetime = field(default_factory=datetime.now)
    related_strategies: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "strategy_hash": self.strategy_hash,
            "strategy_description": self.strategy_description,
            "failure_category": self.failure_category.value,
            "failure_reason": self.failure_reason,
            "diagnosis": self.diagnosis,
            "attempt_count": self.attempt_count,
            "first_failure": self.first_failure.isoformat(),
            "last_failure": self.last_failure.isoformat(),
            "related_strategies": self.related_strategies,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BlacklistedStrategy":
        return cls(
            strategy_hash=data["strategy_hash"],
            strategy_description=data["strategy_description"],
            failure_category=FailureCategory(data["failure_category"]),
            failure_reason=data["failure_reason"],
            diagnosis=data["diagnosis"],
            attempt_count=data.get("attempt_count", 1),
            first_failure=datetime.fromisoformat(data["first_failure"]),
            last_failure=datetime.fromisoformat(data["last_failure"]),
            related_strategies=data.get("related_strategies", []),
            tags=data.get("tags", []),
        )


class StrategyBlacklist:
    """
    Tracks failed strategies to prevent circular retry patterns.

    Thread-safe for concurrent access.
    """

    BLACKLIST_FILE = "strategy_blacklist.json"
    DEFAULT_EXPIRATION_HOURS = 24
    SIMILARITY_THRESHOLD = 0.7

    def __init__(self, workspace_path: Path = None, expiration_hours: int = None):
        """
        Initialize strategy blacklist.

        Args:
            workspace_path: Path to workspace (for persistence)
            expiration_hours: Hours before entries expire
        """
        self.workspace_path = Path(workspace_path) if workspace_path else None
        self.expiration_hours = expiration_hours or self.DEFAULT_EXPIRATION_HOURS
        self._blacklist: dict[str, BlacklistedStrategy] = {}
        self._success_patterns: set[str] = set()  # Strategies that eventually worked

        if self.workspace_path:
            self._load_blacklist()

    def _get_strategy_hash(self, strategy: str) -> str:
        """Generate a hash for a strategy."""
        # Normalize: lowercase, remove extra whitespace
        normalized = " ".join(strategy.lower().split())
        return hashlib.md5(normalized.encode(), usedforsecurity=False).hexdigest()[:12]

    def _extract_keywords(self, strategy: str) -> set[str]:
        """Extract keywords from a strategy for similarity matching."""
        # Remove common words and split
        stop_words = {
            "the",
            "a",
            "an",
            "to",
            "for",
            "of",
            "in",
            "on",
            "with",
            "and",
            "or",
            "is",
            "are",
            "be",
            "this",
            "that",
            "it",
            "we",
            "will",
            "should",
            "can",
            "use",
            "using",
            "try",
            "attempt",
        }
        words = strategy.lower().split()
        return {w for w in words if w not in stop_words and len(w) > 2}

    def _calculate_similarity(self, strategy1: str, strategy2: str) -> float:
        """Calculate similarity between two strategies using Jaccard index."""
        keywords1 = self._extract_keywords(strategy1)
        keywords2 = self._extract_keywords(strategy2)

        if not keywords1 and not keywords2:
            return 1.0
        if not keywords1 or not keywords2:
            return 0.0

        intersection = len(keywords1 & keywords2)
        union = len(keywords1 | keywords2)
        return intersection / union

    def is_blacklisted(self, strategy: str, check_similar: bool = True) -> BlacklistedStrategy | None:
        """
        Check if a strategy is blacklisted.

        Args:
            strategy: Strategy description to check
            check_similar: Also check for similar strategies

        Returns:
            BlacklistedStrategy if blacklisted, None otherwise
        """
        self._cleanup_expired()

        strategy_hash = self._get_strategy_hash(strategy)

        # Exact match
        if strategy_hash in self._blacklist:
            entry = self._blacklist[strategy_hash]
            logger.warning(
                f"Strategy blacklisted (exact match): {entry.strategy_description[:50]}... "
                f"({entry.attempt_count} failures)"
            )
            return entry

        # Similar match
        if check_similar:
            for entry in self._blacklist.values():
                similarity = self._calculate_similarity(strategy, entry.strategy_description)
                if similarity >= self.SIMILARITY_THRESHOLD:
                    logger.warning(
                        f"Strategy blacklisted (similar, {similarity:.0%}): {entry.strategy_description[:50]}..."
                    )
                    return entry

        return None

    def add_failed_strategy(
        self,
        strategy: str,
        failure_reason: str,
        diagnosis: str = "",
        failure_category: FailureCategory = FailureCategory.UNKNOWN,
        tags: list[str] = None,
    ):
        """
        Add a failed strategy to the blacklist.

        Args:
            strategy: Strategy description
            failure_reason: Why it failed
            diagnosis: Detailed diagnosis
            failure_category: Category of failure
            tags: Tags for categorization
        """
        strategy_hash = self._get_strategy_hash(strategy)

        if strategy_hash in self._blacklist:
            # Update existing entry
            entry = self._blacklist[strategy_hash]
            entry.attempt_count += 1
            entry.last_failure = datetime.now()
            if diagnosis and diagnosis not in entry.diagnosis:
                entry.diagnosis += f"\n[Attempt {entry.attempt_count}] {diagnosis}"
            logger.info(f"Updated blacklist entry: {strategy[:50]}... (now {entry.attempt_count} failures)")
        else:
            # Create new entry
            entry = BlacklistedStrategy(
                strategy_hash=strategy_hash,
                strategy_description=strategy,
                failure_category=failure_category,
                failure_reason=failure_reason,
                diagnosis=diagnosis,
                tags=tags or [],
            )
            self._blacklist[strategy_hash] = entry

            # Find related strategies
            for existing in self._blacklist.values():
                if existing.strategy_hash != strategy_hash:
                    similarity = self._calculate_similarity(strategy, existing.strategy_description)
                    if similarity >= 0.5:  # Lower threshold for "related"
                        entry.related_strategies.append(existing.strategy_hash)

            logger.info(f"Added to blacklist: {strategy[:50]}...")

        self._save_blacklist()

    def mark_success(self, strategy: str):
        """
        Mark a strategy as successful (removes from blacklist).

        Args:
            strategy: Strategy that succeeded
        """
        strategy_hash = self._get_strategy_hash(strategy)

        if strategy_hash in self._blacklist:
            del self._blacklist[strategy_hash]
            logger.info(f"Removed from blacklist (success): {strategy[:50]}...")
            self._save_blacklist()

        # Record as successful pattern
        self._success_patterns.add(strategy_hash)

    def suggest_alternatives(self, failed_strategy: str, task_context: str = "") -> list[str]:
        """
        Suggest alternative strategies based on failures.

        Args:
            failed_strategy: The strategy that failed/is blacklisted
            task_context: Context about the task

        Returns:
            List of suggested alternative approaches
        """
        suggestions = []
        entry = self.is_blacklisted(failed_strategy, check_similar=False)

        if not entry:
            return suggestions

        # Based on failure category
        category_suggestions = {
            FailureCategory.TIMEOUT: [
                "Break the task into smaller subtasks",
                "Increase timeout limits",
                "Use a simpler, faster approach",
                "Parallelize independent operations",
            ],
            FailureCategory.CAPABILITY_MISSING: [
                "Spawn a specialized agent with the missing capability",
                "Use a different tool that provides similar functionality",
                "Ask for human assistance on this part",
                "Simplify requirements to match available capabilities",
            ],
            FailureCategory.HALLUCINATION: [
                "Add explicit verification steps",
                "Use file system operations to verify existence",
                "Cross-check with multiple sources",
                "Request concrete evidence before proceeding",
            ],
            FailureCategory.WRONG_APPROACH: [
                "Analyze the problem from a different angle",
                "Consult documentation or examples",
                "Use a more established pattern",
                "Start from first principles",
            ],
            FailureCategory.TOOL_ERROR: [
                "Use an alternative tool for the same operation",
                "Check tool prerequisites are met",
                "Run in a different environment",
                "Verify file paths and permissions",
            ],
            FailureCategory.RESOURCE_EXCEEDED: [
                "Process data in batches",
                "Use streaming instead of loading everything",
                "Reduce scope of operation",
                "Clean up resources between operations",
            ],
            FailureCategory.LOGIC_ERROR: [
                "Add step-by-step reasoning",
                "Use chain-of-thought prompting",
                "Break down complex logic into simpler parts",
                "Add validation at each step",
            ],
            FailureCategory.STAGNATION: [
                "Stop discussing and take a concrete action",
                "Use a tool immediately without further deliberation",
                "Switch to a different agent or perspective",
                "Force a decision: pick the simplest viable option",
                "Break the impasse by reading a specific file",
            ],
            FailureCategory.UNKNOWN: [
                "Try a completely different approach",
                "Gather more information before proceeding",
                "Ask for clarification on requirements",
                "Start with a minimal working example",
            ],
        }

        suggestions.extend(
            category_suggestions.get(entry.failure_category, category_suggestions[FailureCategory.UNKNOWN])
        )

        # Based on related failures
        if entry.related_strategies:
            suggestions.append(
                "Note: Similar strategies have also failed. Consider a fundamentally different approach."
            )

        # Based on success patterns
        if self._success_patterns:
            suggestions.append("Consider adapting a previously successful strategy pattern.")

        return suggestions

    def get_failure_patterns(self) -> dict[str, int]:
        """Get statistics on failure patterns."""
        patterns = {}
        for entry in self._blacklist.values():
            cat = entry.failure_category.value
            patterns[cat] = patterns.get(cat, 0) + 1
        return patterns

    def _cleanup_expired(self):
        """Remove expired blacklist entries."""
        now = datetime.now()
        expiration_delta = timedelta(hours=self.expiration_hours)

        expired = [
            hash_id for hash_id, entry in self._blacklist.items() if (now - entry.last_failure) > expiration_delta
        ]

        for hash_id in expired:
            del self._blacklist[hash_id]
            logger.debug(f"Removed expired blacklist entry: {hash_id}")

        if expired:
            self._save_blacklist()

    def _load_blacklist(self):
        """Load blacklist from disk."""
        if not self.workspace_path:
            return

        file_path = self.workspace_path / ".nexus" / self.BLACKLIST_FILE
        if file_path.exists():
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                for entry_data in data.get("strategies", []):
                    entry = BlacklistedStrategy.from_dict(entry_data)
                    self._blacklist[entry.strategy_hash] = entry
                self._success_patterns = set(data.get("success_patterns", []))
                logger.info(f"Loaded {len(self._blacklist)} blacklist entries")
            except Exception as e:
                logger.warning(f"Failed to load blacklist: {e}")

    def _save_blacklist(self):
        """Save blacklist to disk."""
        if not self.workspace_path:
            return

        file_path = self.workspace_path / ".nexus" / self.BLACKLIST_FILE
        file_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "version": "8.0",
            "updated_at": datetime.now().isoformat(),
            "strategies": [entry.to_dict() for entry in self._blacklist.values()],
            "success_patterns": list(self._success_patterns),
        }

        file_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def clear(self, keep_success_patterns: bool = True):
        """Clear the blacklist."""
        self._blacklist.clear()
        if not keep_success_patterns:
            self._success_patterns.clear()
        self._save_blacklist()

    def get_stats(self) -> dict:
        """Get blacklist statistics."""
        return {
            "total_entries": len(self._blacklist),
            "success_patterns": len(self._success_patterns),
            "failure_patterns": self.get_failure_patterns(),
            "oldest_entry": min((e.first_failure for e in self._blacklist.values()), default=None),
            "most_failed": max(self._blacklist.values(), key=lambda e: e.attempt_count, default=None),
        }
