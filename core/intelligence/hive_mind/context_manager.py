"""
NEXUS V9.2 - Hive Mind Context Manager

Sliding window context management to prevent token explosion.
Maintains essential context while discarding old/irrelevant information.

V9.2 Enhancement: Scoped Context for Controlled Inheritance
- create_scoped_context() for phase transitions
- summarize_for_inheritance() for result extraction
- Model-aware context (capability reminders)

Integration with ProjectMemory RAG:
- Important insights are indexed for long-term retrieval
- Context can be enriched from RAG before operations

Usage:
    manager = HiveMindContextManager(max_tokens=30000)

    # Add to context
    manager.add_analysis("gemini", analysis_dict)
    manager.add_debate_turn(debate_argument)

    # Get context for an operation
    context = manager.get_context_for("debate", max_tokens=8000)

    # V9.2: Create scoped context for phase transition
    scoped = manager.create_scoped_context(
        scope=ContextScope.TASK_PLUS_RESULTS,
        from_phase="analysis",
        session_uuid="abc-123"
    )

    # Archive important insights to RAG
    manager.archive_to_rag(project_memory, session_id)
"""

import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.memory_pkg.memory.project_memory import ProjectMemory

# V9.2: Import scoped context types
from .context_scope import ContextScope, ScopedContext

logger = logging.getLogger(__name__)


class ContextPriority(Enum):
    """Priority levels for context items."""

    CRITICAL = 4  # Never evict (task definition, final decisions)
    HIGH = 3  # Evict last (current analysis, active debate)
    MEDIUM = 2  # Standard eviction (historical debate turns)
    LOW = 1  # Evict first (verbose tool outputs, logs)


@dataclass
class ContextItem:
    """A single item in the context window."""

    category: str  # "analysis", "debate", "execution", "diagnosis", etc.
    source: str  # "gemini", "claude", "system", "tool"
    content: str
    priority: ContextPriority = ContextPriority.MEDIUM
    timestamp: datetime = field(default_factory=datetime.now)
    token_estimate: int = 0
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.token_estimate == 0:
            # Rough estimate: ~4 chars per token
            self.token_estimate = len(self.content) // 4


@dataclass
class ContextSnapshot:
    """Snapshot of context for a specific operation."""

    items: list[ContextItem]
    total_tokens: int
    categories_included: list[str]
    truncated: bool = False


class HiveMindContextManager:
    """
    Manages context window for Hive Mind operations.

    Uses a sliding window with priority-based eviction:
    - CRITICAL items never evicted
    - Older LOW priority items evicted first
    - Maintains coherence by keeping related items together
    """

    # Token budgets by operation type
    OPERATION_BUDGETS = {
        "analysis": 10000,  # Independent analysis
        "debate": 8000,  # Each debate turn
        "architecture": 6000,  # Architecture generation
        "execution": 5000,  # Execution context
        "diagnosis": 12000,  # Failure diagnosis (needs more context)
        "consolidation": 15000,  # Knowledge consolidation
        "swarm_delegation": 8000,  # V8.3.0: Context for Swarm Bridge delegation
        "swarm_tool_invocation": 6000,  # V8.3.1: Tool invocation from any phase
        "default": 8000,
    }

    # V10 FIX F12: Hard cap for CRITICAL items to prevent overflow
    # CRITICAL items are never evicted, so large ones can saturate context
    CRITICAL_MAX_TOKENS = 5000

    def __init__(self, max_tokens: int = 50000):
        """
        Initialize context manager.

        Args:
            max_tokens: Maximum total tokens to maintain
        """
        self.max_tokens = max_tokens
        self._items: deque[ContextItem] = deque()
        self._current_tokens = 0
        self._archived_insights: list[dict] = []  # Insights to index in RAG
        # V12.4 FIX F23: RLock for thread-safe concurrent access
        # RLock allows reentrant calls (e.g., add_analysis -> add_item)
        self._lock = threading.RLock()

    @property
    def current_tokens(self) -> int:
        """Get current token count."""
        return self._current_tokens

    @property
    def available_tokens(self) -> int:
        """Get available token space."""
        return max(0, self.max_tokens - self._current_tokens)

    def add_item(
        self,
        category: str,
        source: str,
        content: str,
        priority: ContextPriority = ContextPriority.MEDIUM,
        metadata: dict = None,
    ):
        """
        Add an item to context.

        Args:
            category: Item category (analysis, debate, etc.)
            source: Source agent/system
            content: Content text
            priority: Priority level
            metadata: Additional metadata
        """
        # V12.4 FIX F23: Thread-safe access to shared state
        with self._lock:
            item = ContextItem(
                category=category, source=source, content=content, priority=priority, metadata=metadata or {}
            )

            # V10 FIX F12: Truncate CRITICAL items if too large
            # CRITICAL items are never evicted, so we must cap them upfront
            if priority == ContextPriority.CRITICAL and item.token_estimate > self.CRITICAL_MAX_TOKENS:
                logger.warning(
                    f"CRITICAL item too large ({item.token_estimate} tokens), "
                    f"truncating to {self.CRITICAL_MAX_TOKENS} tokens"
                )
                ratio = self.CRITICAL_MAX_TOKENS / item.token_estimate
                new_len = int(len(item.content) * ratio * 0.95)  # 5% margin
                item.content = item.content[:new_len] + "...[CRITICAL TRUNCATED]"
                item.token_estimate = self.CRITICAL_MAX_TOKENS

            # Evict if needed before adding
            while self._current_tokens + item.token_estimate > self.max_tokens:
                if not self._evict_one():
                    # Can't evict anything, truncate new item
                    logger.warning(f"Cannot fit item ({item.token_estimate} tokens), truncating content")
                    # Truncate to fit
                    available = self.max_tokens - self._current_tokens
                    if available > 100:
                        ratio = available / item.token_estimate
                        new_len = int(len(item.content) * ratio * 0.9)
                        item.content = item.content[:new_len] + "... [truncated]"
                        item.token_estimate = available
                    else:
                        logger.error("No space for item even after truncation")
                        return
                    break

            self._items.append(item)
            self._current_tokens += item.token_estimate
            logger.debug(
                f"Added context item: {category}/{source} ({item.token_estimate} tokens, total: {self._current_tokens})"
            )

    def _evict_one(self) -> bool:
        """
        Evict one item based on priority and age.

        Returns:
            True if an item was evicted, False if nothing to evict
        """
        # Find lowest priority, oldest item
        candidates = []
        for i, item in enumerate(self._items):
            if item.priority != ContextPriority.CRITICAL:
                candidates.append((i, item))

        if not candidates:
            return False

        # Sort by priority (ascending), then age (oldest first)
        candidates.sort(key=lambda x: (x[1].priority.value, x[1].timestamp))

        # Remove the best candidate
        idx, item = candidates[0]
        del self._items[idx]
        self._current_tokens -= item.token_estimate

        logger.debug(
            f"Evicted context item: {item.category}/{item.source} "
            f"(priority: {item.priority.name}, {item.token_estimate} tokens)"
        )
        return True

    # Convenience methods for common operations

    def add_task(self, task: str):
        """Add task definition (CRITICAL priority)."""
        self.add_item(
            category="task",
            source="user",
            content=task,
            priority=ContextPriority.CRITICAL,
            metadata={"type": "task_definition"},
        )

    def add_analysis(self, agent_id: str, analysis: dict):
        """Add independent analysis result."""
        content = self._format_analysis(analysis)
        self.add_item(
            category="analysis",
            source=agent_id,
            content=content,
            priority=ContextPriority.HIGH,
            metadata={"agent": agent_id, "type": "independent_analysis"},
        )

    def add_debate_turn(self, turn_number: int, agent_id: str, argument: str):
        """Add a debate turn."""
        # Earlier turns get lower priority
        priority = ContextPriority.HIGH if turn_number >= 3 else ContextPriority.MEDIUM
        self.add_item(
            category="debate",
            source=agent_id,
            content=f"[Turn {turn_number}] {argument}",
            priority=priority,
            metadata={"turn": turn_number, "agent": agent_id},
        )

    def add_execution_result(self, step_name: str, result: str, success: bool):
        """Add execution step result."""
        priority = ContextPriority.MEDIUM if success else ContextPriority.HIGH
        self.add_item(
            category="execution",
            source="system",
            content=f"[{step_name}] {'SUCCESS' if success else 'FAILED'}: {result}",
            priority=priority,
            metadata={"step": step_name, "success": success},
        )

    def add_diagnosis(self, agent_id: str, diagnosis: str):
        """Add failure diagnosis (HIGH priority for debugging)."""
        self.add_item(
            category="diagnosis",
            source=agent_id,
            content=diagnosis,
            priority=ContextPriority.HIGH,
            metadata={"agent": agent_id, "type": "diagnosis"},
        )

    def add_insight(self, category: str, content: str, tags: list[str] = None):
        """
        Add a learned insight (will be archived to RAG).

        Args:
            category: Insight category (pattern, antipattern, recipe, etc.)
            content: The insight content
            tags: Tags for indexing
        """
        self.add_item(
            category="insight",
            source="hive_mind",
            content=content,
            priority=ContextPriority.MEDIUM,
            metadata={"insight_category": category, "tags": tags or []},
        )
        # Queue for RAG archival
        self._archived_insights.append(
            {"category": category, "content": content, "tags": tags or [], "timestamp": datetime.now().isoformat()}
        )

    def get_context_for(
        self,
        operation: str,
        max_tokens: int = None,
        include_categories: list[str] = None,
        exclude_categories: list[str] = None,
    ) -> ContextSnapshot:
        """
        Get context snapshot for a specific operation.

        Args:
            operation: Operation type (analysis, debate, etc.)
            max_tokens: Max tokens (defaults to operation budget)
            include_categories: Only include these categories
            exclude_categories: Exclude these categories

        Returns:
            ContextSnapshot with relevant items
        """
        budget = max_tokens or self.OPERATION_BUDGETS.get(operation, self.OPERATION_BUDGETS["default"])

        # Filter items
        filtered = []
        for item in self._items:
            if include_categories and item.category not in include_categories:
                continue
            if exclude_categories and item.category in exclude_categories:
                continue
            filtered.append(item)

        # Sort by priority (descending) then recency
        filtered.sort(key=lambda x: (-x.priority.value, x.timestamp), reverse=True)

        # Select items within budget
        selected = []
        total = 0
        truncated = False

        for item in filtered:
            if total + item.token_estimate <= budget:
                selected.append(item)
                total += item.token_estimate
            else:
                truncated = True

        # Sort selected by timestamp for chronological order
        selected.sort(key=lambda x: x.timestamp)

        categories = list(set(item.category for item in selected))

        return ContextSnapshot(items=selected, total_tokens=total, categories_included=categories, truncated=truncated)

    def get_full_context_string(self, operation: str = "default") -> str:
        """Get context as a formatted string."""
        snapshot = self.get_context_for(operation)
        lines = []

        current_category = None
        for item in snapshot.items:
            if item.category != current_category:
                current_category = item.category
                lines.append(f"\n=== {current_category.upper()} ===")
            lines.append(f"[{item.source}] {item.content}")

        if snapshot.truncated:
            lines.append("\n[Context truncated due to token limit]")

        return "\n".join(lines)

    def _format_analysis(self, analysis: dict) -> str:
        """Format analysis dict as string."""
        parts = []
        if "task_understanding" in analysis:
            parts.append(f"Understanding: {analysis['task_understanding']}")
        if "complexity_assessment" in analysis:
            parts.append(f"Complexity: {analysis['complexity_assessment']}")
        if "proposed_approach" in analysis:
            parts.append(f"Approach: {analysis['proposed_approach']}")
        if "required_capabilities" in analysis:
            caps = ", ".join(analysis["required_capabilities"])
            parts.append(f"Capabilities: {caps}")
        if "potential_risks" in analysis:
            risks = ", ".join(analysis["potential_risks"])
            parts.append(f"Risks: {risks}")
        if "confidence" in analysis:
            parts.append(f"Confidence: {analysis['confidence']:.1%}")
        if "reasoning" in analysis:
            parts.append(f"Reasoning: {analysis['reasoning']}")
        return "\n".join(parts)

    # RAG Integration

    def archive_to_rag(self, project_memory: "ProjectMemory", session_id: str) -> int:
        """
        Archive accumulated insights to ProjectMemory RAG.

        Args:
            project_memory: ProjectMemory instance
            session_id: Current session identifier

        Returns:
            Number of insights archived
        """
        if not self._archived_insights:
            return 0

        archived = 0
        for insight in self._archived_insights:
            try:
                # Create a document for the insight
                doc_content = f"""
# Hive Mind Insight: {insight["category"]}

{insight["content"]}

Tags: {", ".join(insight["tags"])}
Session: {session_id}
Timestamp: {insight["timestamp"]}
"""
                # Use project_memory's add_document if available
                if hasattr(project_memory, "add_document"):
                    project_memory.add_document(
                        content=doc_content,
                        metadata={
                            "type": "hive_mind_insight",
                            "category": insight["category"],
                            "tags": insight["tags"],
                            "session": session_id,
                        },
                    )
                    archived += 1
                    logger.info(f"Archived insight to RAG: {insight['category']}")
            except Exception as e:
                logger.warning(f"Failed to archive insight: {e}")

        # Clear archived insights
        self._archived_insights.clear()
        return archived

    def get_pending_insights(self) -> list[dict]:
        """Get insights pending RAG archival."""
        return self._archived_insights.copy()

    # State management

    def compress_with_afm(self, target_budget: int | None = None) -> dict:
        """
        Compress context using Adaptive Focus Memory (arxiv:2511.12712).

        Uses 3-tier fidelity (FULL/COMPRESSED/PLACEHOLDER) to reduce
        context size while preserving high-importance items verbatim.

        Args:
            target_budget: Target token budget (default: 60% of max)

        Returns:
            Dict with compression stats
        """
        try:
            from core.memory_pkg.memory.adaptive_focus import AdaptiveFocusManager

            budget = target_budget or int(self.max_tokens * 0.6)
            afm = AdaptiveFocusManager(token_budget=budget)

            # Feed context items into AFM
            with self._lock:
                items = list(self._items)

            for item in items:
                afm.add_item(
                    content=item.content,
                    role=item.source,
                    importance=item.priority.value / 3.0,  # Normalize 1-3 to ~0.33-1.0
                    pinned=item.priority == ContextPriority.CRITICAL,
                )

            result = afm.assign_fidelity()
            logger.debug(
                f"AFM compression: {result.total_tokens_before} -> {result.total_tokens_after} tokens "
                f"({result.compression_ratio:.0%} reduction, "
                f"{result.items_full} full / {result.items_compressed} compressed / "
                f"{result.items_placeholder} placeholder)"
            )
            return result.to_dict()
        except Exception as e:
            logger.debug(f"AFM compression failed: {e}")
            return {"error": str(e)}

    def spotlight_external_content(self, content: str, source: str = "") -> str:
        """
        Apply spotlighting to external/RAG content before adding to context.

        Protects against indirect prompt injection by marking untrusted
        content with delimiters (arxiv:2403.14720).

        Args:
            content: External content to spotlight
            source: Content source identifier

        Returns:
            Spotlighted content string
        """
        try:
            from core.memory_pkg.memory.spotlighting import get_spotlighter

            spotlighter = get_spotlighter()
            return spotlighter.spotlight(content, source=source)
        except Exception:
            return content

    def clear(self, keep_critical: bool = True):
        """
        Clear context.

        Args:
            keep_critical: Whether to keep CRITICAL items
        """
        # V12.4 FIX F23: Thread-safe access to shared state
        with self._lock:
            if keep_critical:
                critical = [item for item in self._items if item.priority == ContextPriority.CRITICAL]
                self._items = deque(critical)
                self._current_tokens = sum(item.token_estimate for item in critical)
            else:
                self._items.clear()
                self._current_tokens = 0

    def get_stats(self) -> dict:
        """Get context statistics."""
        category_counts = {}
        priority_counts = {p.name: 0 for p in ContextPriority}

        for item in self._items:
            category_counts[item.category] = category_counts.get(item.category, 0) + 1
            priority_counts[item.priority.name] += 1

        return {
            "total_items": len(self._items),
            "total_tokens": self._current_tokens,
            "max_tokens": self.max_tokens,
            "utilization_percent": round(self._current_tokens / self.max_tokens * 100, 1),
            "category_counts": category_counts,
            "priority_counts": priority_counts,
            "pending_insights": len(self._archived_insights),
        }

    # ===== V9.2: Scoped Context for Controlled Inheritance =====

    def create_scoped_context(
        self,
        scope: ContextScope,
        from_phase: str | None = None,
        session_uuid: str | None = None,
        relevant_files: list[str] | None = None,
        model_id: str | None = None,
        max_summary_tokens: int = 2000,
    ) -> ScopedContext:
        """
        Create a scoped context for phase transitions or agent spawning.

        V9.2: Controlled inheritance - only pass what's needed.

        Args:
            scope: The scope level to apply
            from_phase: Source phase for summarization (e.g., "analysis")
            session_uuid: Session UUID for isolation
            relevant_files: Files to include in context
            model_id: Model identifier for capability context
            max_summary_tokens: Max tokens for parent summary

        Returns:
            ScopedContext with appropriate content

        Example:
            # Phase 1 -> Phase 2 transition
            scoped = manager.create_scoped_context(
                scope=ContextScope.TASK_PLUS_RESULTS,
                from_phase="analysis",
                session_uuid="abc-123"
            )
        """
        # Get task description (CRITICAL priority items)
        task_description = self._get_task_description()

        # Get parent summary based on phase
        parent_summary = ""
        if scope in [ContextScope.FULL, ContextScope.TASK_PLUS_RESULTS, ContextScope.RESULTS_ONLY]:
            parent_summary = self.summarize_for_inheritance(from_phase=from_phase, max_tokens=max_summary_tokens)

        # Get full history only for FULL scope
        full_history = []
        if scope == ContextScope.FULL:
            full_history = [
                {
                    "category": item.category,
                    "source": item.source,
                    "content": item.content,
                    "timestamp": item.timestamp.isoformat(),
                }
                for item in self._items
            ]

        # Model-specific context
        model_context = self._get_model_context(model_id) if model_id else None

        return ScopedContext(
            scope=scope,
            task_description=task_description if scope != ContextScope.FRESH else "",
            relevant_files=relevant_files or [],
            parent_summary=parent_summary,
            full_history=full_history,
            session_uuid=session_uuid,
            model_context=model_context,
            metadata={"from_phase": from_phase, "created_by": "HiveMindContextManager"},
        )

    async def compress_for_next_phase(
        self,
        from_phase: str,
        max_tokens: int = 300,
        use_semantic_compression: bool = True,
    ) -> str:
        """
        Compress context for next phase using semantic compression.

        V12.4.1 Enhancement: Uses SLM-based semantic compression (70-85% reduction)
        instead of simple summarization. Falls back to summarization if SLM unavailable.

        Args:
            from_phase: Phase to compress from (analysis, debate, etc.)
            max_tokens: Maximum tokens for compressed output
            use_semantic_compression: Use SLM compression (True) or basic summarization (False)

        Returns:
            Compressed context string
        """
        # Get content for this phase
        content = self.summarize_for_inheritance(from_phase, max_tokens=max_tokens * 3)

        if not use_semantic_compression or not content:
            return content  # Fall back to basic summarization

        try:
            from .semantic_compressor import get_semantic_compressor

            compressor = get_semantic_compressor()

            # Check if Ollama is available
            if not await compressor.is_available():
                logger.debug("Semantic compression unavailable - using basic summarization")
                return content

            # Compress via SLM
            result = await compressor.compress_phase_output(
                phase_name=from_phase,
                content=content,
                max_output_tokens=max_tokens,
            )

            logger.info(
                f"Semantic compression: {result.original_tokens} -> {result.compressed_tokens} tokens "
                f"({result.compression_ratio:.1%} reduction)"
            )

            return result.compressed_content

        except Exception as e:
            logger.warning(f"Semantic compression failed: {e} - using basic summarization")
            return content

    def summarize_for_inheritance(self, from_phase: str | None = None, max_tokens: int = 2000) -> str:
        """
        Summarize context for inheritance to next phase/agent.

        Extracts only the essential results, not the full history.

        NOTE: V12.4.1 - Consider using compress_for_next_phase() for semantic compression.

        Args:
            from_phase: Phase to summarize from (filters by category)
            max_tokens: Maximum tokens for summary

        Returns:
            Concise summary string
        """
        # Map phase names to categories
        phase_categories = {
            "analysis": ["analysis"],
            "debate": ["debate", "analysis"],
            "architecture": ["architecture", "debate"],
            "execution": ["execution", "architecture"],
            "diagnosis": ["diagnosis", "execution"],
            "consolidation": ["consolidation", "execution"],
        }

        # Get relevant categories
        if from_phase and from_phase in phase_categories:
            include_categories = phase_categories[from_phase]
        else:
            include_categories = None

        # Build summary from high-priority items
        summary_parts = []
        token_count = 0

        for item in reversed(list(self._items)):  # Most recent first
            # Filter by category
            if include_categories and item.category not in include_categories:
                continue

            # Skip low priority verbose items
            if item.priority == ContextPriority.LOW:
                continue

            # Check token budget
            if token_count + item.token_estimate > max_tokens:
                break

            # Add to summary
            summary_parts.append(f"[{item.category.upper()}:{item.source}] {item.content[:500]}")
            token_count += item.token_estimate

        if not summary_parts:
            return "No prior context available."

        return "\n\n".join(reversed(summary_parts))  # Chronological order

    def _get_task_description(self) -> str:
        """Extract task description from CRITICAL items."""
        for item in self._items:
            if item.category == "task" and item.priority == ContextPriority.CRITICAL:
                return item.content
        return ""

    def _get_model_context(self, model_id: str) -> str:
        """
        Get model-specific context (capabilities reminder).

        Helps models understand what they can/cannot do.
        """
        model_capabilities = {
            "claude-opus-4-5": (
                "You are Claude Opus 4.5, Anthropic's most capable model. "
                "Strengths: Complex reasoning, nuanced analysis, creative solutions, "
                "long-form generation, safety considerations."
            ),
            "claude-sonnet-4-5": (
                "You are Claude Sonnet 4.5, optimized for speed and efficiency. "
                "Strengths: Fast responses, tool execution, code generation, "
                "straightforward tasks."
            ),
            "gemini-3-pro": (
                "You are Gemini 3 Pro. "
                "Strengths: Multimodal understanding, code execution, "
                "structured outputs, large context handling."
            ),
            "gemini-3-flash": (
                "You are Gemini 3 Flash, optimized for speed. Strengths: Fast responses, simple tasks, high throughput."
            ),
        }

        # Match by prefix
        for prefix, context in model_capabilities.items():
            if model_id and model_id.startswith(prefix):
                return context

        return None

    def get_scoped_prompt(
        self,
        instruction: str,
        scope: ContextScope,
        from_phase: str | None = None,
        session_uuid: str | None = None,
        relevant_files: list[str] | None = None,
        model_id: str | None = None,
    ) -> str:
        """
        Create a complete prompt with scoped context prefix.

        Convenience method combining create_scoped_context + instruction.

        Args:
            instruction: The actual instruction/prompt for the agent
            scope: Context scope to apply
            from_phase: Source phase
            session_uuid: Session UUID
            relevant_files: Relevant files
            model_id: Model identifier

        Returns:
            Complete prompt with context prefix
        """
        scoped = self.create_scoped_context(
            scope=scope,
            from_phase=from_phase,
            session_uuid=session_uuid,
            relevant_files=relevant_files,
            model_id=model_id,
        )

        prefix = scoped.to_prompt_prefix()
        return f"{prefix}{instruction}"
