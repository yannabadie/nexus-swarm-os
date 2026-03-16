"""
NEXUS V7.8 - Context Builder Module (Phase 14c)

Extracted from orchestration_v7.py to follow Single Responsibility Principle.

This module handles all context building operations:
- _build_context(): Full brainstorming context
- _build_context_with_tool_result(): CFL validation context
- _build_swarm_context(): Swarm execution context
- _build_simple_context(): Simple task context

Usage:
    builder = ContextBuilder(orchestrator)
    context = builder.build_context()
"""

import json
import logging
from typing import TYPE_CHECKING

from core.foundation.agents.unified_registry import get_registry
from core.intelligence.swarm import TaskAnalysis, TaskComplexity
from core.memory_pkg.prompts import load_prompt

_logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from core.orchestration_v7 import OrchestratorV7


class ContextBuilder:
    """
    Context builder for NEXUS orchestrator.

    Handles construction of markdown contexts for different execution modes:
    - Brainstorming (full context with history)
    - CFL Validation (lightweight, focused)
    - Swarm Execution (enriched with task info)
    - Simple Tasks (minimal overhead)

    Phase 14c: Extracted from OrchestratorV7 for better maintainability.
    """

    def __init__(self, orchestrator: "OrchestratorV7"):
        """
        Initialize context builder with orchestrator reference.

        Uses composition pattern - builder accesses orchestrator state
        but doesn't own it.

        Args:
            orchestrator: Parent OrchestratorV7 instance
        """
        self._orch = orchestrator
        self._registry = get_registry()

    def build_context(self) -> str:
        """
        Build full context markdown for agent brainstorming.

        Includes:
        - System prompt for active agent
        - Current objective
        - Strategic plan
        - Available tools
        - Recent history (last 50 messages)
        - Compressed history summary
        - CoT enforcement for EXPERT tasks

        Returns:
            Markdown context string
        """
        # Load system prompt (V7.5: with includes resolved, V8.4.0: via registry)
        prompt_name = "system_gemini_v7" if self._registry.is_gemini(self._orch.active_agent) else "system_claude_v7"
        try:
            system_prompt = load_prompt(prompt_name)
        except Exception as e:
            _logger.debug("Failed to load prompt %s: %s", prompt_name, e)
            system_prompt = f"You are {self._registry.get_display_name(self._orch.active_agent)}."

        # Get available tools from manager dynamically
        tools_list = list(self._orch.tool_manager.tools.keys())

        context = f"""# NEXUS V7.0 "Chrysalis" - Tour {self._orch.iteration}

{system_prompt}

---

## OBJECTIF UTILISATEUR
{self._orch.blackboard.get("objective", "Non défini")}

---

## MODE
{self._orch.blackboard.get("mode", "Normal")}

---

## PLAN STRATÉGIQUE
{json.dumps(self._orch.blackboard.get("strategic_plan", []), indent=2, ensure_ascii=False)}

---

## CAPABILITIES (TOOLS)
{json.dumps(tools_list, indent=2, ensure_ascii=False)}

---
"""
        # V7.8 Phase 10c: Inject relevant project knowledge for MODERATE+ tasks
        project_knowledge = self._get_project_knowledge()
        if project_knowledge:
            context += f"\n{project_knowledge}\n---\n"

        context += """
## HISTORIQUE RÉCENT
"""
        # Add compressed history summary if available (preserves long-term context)
        compressed = self._orch.blackboard.get("compressed_history_summary", "")
        if compressed:
            context += f"\n**[Résumé des échanges précédents]:**\n{compressed}\n\n---\n"

        # Add last 50 messages (increased from 30 to improve context retention)
        for msg in self._orch.blackboard.get("recent_history", [])[-50:]:
            sender = msg.get("sender", "Unknown")
            content = msg.get("content", "")
            context += f"\n**{sender}:** {content}\n"

        # V7.7 Phase 14e: Force Chain-of-Thought for EXPERT complexity tasks
        if self._orch._current_complexity == TaskComplexity.EXPERT:
            context += "\n\n<instruction>BEFORE answering or using tools, you MUST wrap your step-by-step reasoning in <thinking>...</thinking> tags.</instruction>"

        return context

    def build_context_with_tool_result(self) -> str:
        """
        Build LIGHTWEIGHT context for CFL validation (fast, focused).

        CFL should be FAST - only include what's needed for validation:
        - Current objective
        - Tool that was executed
        - Tool result
        - Simple validation instructions

        Does NOT include:
        - Full history
        - System prompts
        - Strategic plans

        Returns:
            Markdown context for CFL validation
        """
        objective = self._orch.blackboard.get("objective", "Task in progress")

        # Get the last message (tool request)
        last_msg = self._orch.memory.get_last_message() if self._orch.memory else {}
        tool_request = last_msg.get("tool_use", {})
        tool_name = tool_request.get("tool_name", "unknown")
        tool_args = tool_request.get("arguments", {})

        # Get tool result
        result_dict = self._orch.pending_tool_result.to_dict() if self._orch.pending_tool_result else {}

        # Truncate output if too long (CFL doesn't need full output)
        output = result_dict.get("output", "")
        if len(output) > 2000:
            output = output[:1000] + "\n...[truncated]...\n" + output[-500:]

        context = f"""# CFL VALIDATION - Quick Check

## Your Role
You are validating a tool execution. Be BRIEF and FAST.

## Task Context
User objective: {objective}

## Tool Executed
- Tool: {tool_name}
- Arguments: {json.dumps(tool_args, ensure_ascii=False)[:500]}

## Tool Result
- Status: {result_dict.get("status", "UNKNOWN")}
- Output:
```
{output}
```
- Error: {result_dict.get("error", "None")}

## YOUR TASK (IMPORTANT)
1. Check if the tool executed successfully
2. If SUCCESS: Say "[OK]" and briefly note what was accomplished
3. If FAILURE: Say "[NO]" and note the error
4. If task is COMPLETE: Add "FINISHED" to your response

**DO NOT:**
- Analyze the full task
- Propose next steps
- Ask questions to the other agent
- Do deep research

**JUST VALIDATE** the tool result in 1-2 sentences, then stop.
"""
        return context

    def build_swarm_context(self, task_context: str, task_type: str, target_agent: str | None = None) -> str:
        """
        Build enriched context for swarm execution.

        Combines the task-specific context from executors with:
        - System prompt for the active agent
        - Workspace information
        - Available tools
        - Current objective
        - Recent history (limited for swarm focus)

        Args:
            task_context: Context from swarm executor (mode + subtask)
            task_type: Type of task (negotiation, execution, etc.)
            target_agent: "Claude" or "Gemini" (for thread-safe operation)

        Returns:
            Enriched markdown context
        """
        # Use target_agent if provided (thread-safe), otherwise fallback to active_agent
        agent = target_agent or self._orch.active_agent or "gemini"

        # Load system prompt (V7.5: with includes resolved, V8.4.0: via registry)
        prompt_name = "system_gemini_v7" if self._registry.is_gemini(agent) else "system_claude_v7"
        try:
            system_prompt = load_prompt(prompt_name)
        except Exception as e:
            _logger.debug("Failed to load prompt %s: %s", prompt_name, e)
            system_prompt = f"You are {self._registry.get_display_name(agent)}, a collaborative AI agent."

        # Get available tools
        tools_list = list(self._orch.tool_manager.tools.keys())

        # Build enriched context
        enriched = f"""# NEXUS V7.0 "Chrysalis" - Swarm Execution

{system_prompt}

---

## WORKSPACE
Path: {self._orch.workspace_path}

---

## OBJECTIF UTILISATEUR
{self._orch.blackboard.get("objective", "Non défini")}

---

## SWARM TASK CONTEXT
{task_context}

---

## AVAILABLE TOOLS
{json.dumps(tools_list, indent=2, ensure_ascii=False)}

---

## INSTRUCTIONS
- You are working in SWARM mode with collaborative execution
- Task type: {task_type}
- Use the tools available to accomplish your subtask
- Coordinate with other agents via your responses
- Use <tool_use name="tool_name">{{...}}</tool_use> for tool calls (Claude)
- Use JSON tool format for tool calls (Gemini)
"""

        # Add recent history for context (last 10 messages only to keep it focused)
        recent = self._orch.blackboard.get("recent_history", [])[-10:]
        if recent:
            enriched += "\n---\n\n## RECENT CONTEXT\n"
            for msg in recent:
                sender = msg.get("sender", "Unknown")
                content = msg.get("content", "")[:500]  # Truncate for swarm
                enriched += f"\n**{sender}:** {content}\n"

        return enriched

    def build_simple_context(self, user_input: str, task_analysis: TaskAnalysis) -> str:
        """
        Build lightweight context for SIMPLE task execution.

        Simpler than full brainstorming context - focused on task completion.
        Used for single-agent execution without CFL validation.

        Args:
            user_input: User's task description
            task_analysis: Pre-computed task analysis

        Returns:
            Markdown context for simple task
        """
        # V8.4.0: Use registry for agent identification
        agent = self._orch.active_agent
        prompt_name = "system_gemini_v7" if self._registry.is_gemini(agent) else "system_claude_v7"
        try:
            system_prompt = load_prompt(prompt_name)
        except Exception as e:
            _logger.debug("Failed to load prompt %s: %s", prompt_name, e)
            system_prompt = f"You are {self._registry.get_display_name(agent)}."

        tools_list = list(self._orch.tool_manager.tools.keys())

        return f"""# NEXUS V7 - SIMPLE TASK MODE

{system_prompt}

---

## MODE
**SIMPLE TASK** - Single agent, direct execution.
Complete the task efficiently. No need for extensive debate.

---

## TASK
{user_input}

---

## TASK ANALYSIS
- Complexity: {task_analysis.complexity.name}
- Primary Domain: {task_analysis.primary_domain.value}
- Requires Web: {task_analysis.requires_web}
- Requires Code: {task_analysis.requires_code_execution}

---

## AVAILABLE TOOLS
{json.dumps(tools_list, indent=2, ensure_ascii=False)}

---

## INSTRUCTIONS
1. Analyze the task
2. Use tools as needed to complete it
3. When done, say "FINISHED" or "Task complete"

Execute efficiently. You are the sole agent for this task.
"""

    # =========================================================================
    # Private Helpers
    # =========================================================================

    def _get_project_knowledge(self) -> str:
        """
        Retrieve relevant project knowledge for MODERATE+ complexity tasks.

        V7.8 Phase 10c: Project Memory RAG integration.
        V11 DIAGNOSTIC: Added logging to trace RAG usage.

        Returns:
            Formatted markdown string with relevant chunks, or empty string.
        """
        import logging

        logger = logging.getLogger("nexus.rag_diagnostic")

        # Only inject for MODERATE+ complexity tasks
        complexity = getattr(self._orch, "_current_complexity", None)
        if not complexity or complexity.value < TaskComplexity.MODERATE.value:
            logger.debug(f"[RAG] Skipped - complexity {complexity} < MODERATE")
            return ""

        # Check if project_memory is available
        if not hasattr(self._orch, "project_memory"):
            logger.warning("[RAG] ProjectMemory NOT AVAILABLE on orchestrator")
            return ""

        if self._orch.project_memory is None:
            logger.warning("[RAG] ProjectMemory is None")
            return ""

        # Get objective for query
        objective = self._orch.blackboard.get("objective", "")
        if not objective:
            logger.debug("[RAG] No objective in blackboard")
            return ""

        try:
            # V11 DIAGNOSTIC: Log retrieval attempt
            logger.info(f"[RAG] Retrieving for: '{objective[:80]}...'")

            # Check index status
            stats = self._orch.project_memory.get_stats()
            logger.info(f"[RAG] Index stats: {stats.total_chunks} chunks, {stats.total_files} files indexed")

            if stats.total_chunks == 0:
                logger.warning("[RAG] Index is EMPTY - no chunks to retrieve")
                return ""

            # Retrieve relevant chunks
            chunks = self._orch.project_memory.retrieve(objective, limit=3, min_score=0.05)

            if not chunks:
                logger.info("[RAG] No chunks matched (score < 0.05)")
                return ""

            # V12.4: Record access patterns for Ebbinghaus decay scoring
            try:
                from core.memory_pkg.memory.decay_scorer import get_decay_scorer

                scorer = get_decay_scorer()
                for chunk in chunks:
                    scorer.record_access(chunk.chunk_id)
            except Exception as e:
                _logger.debug(f"Decay scorer recording failed: {e}")

            # V11 DIAGNOSTIC: Log retrieved chunks
            logger.info(f"[RAG] Retrieved {len(chunks)} chunks:")
            for i, chunk in enumerate(chunks):
                source = getattr(chunk, "file_path", getattr(chunk, "source_path", "unknown"))
                logger.info(f"[RAG]   [{i + 1}] {source}:{chunk.start_line}-{chunk.end_line}")

            # Format for context
            formatted = self._orch.project_memory.format_chunks_for_context(chunks, max_chars=2000)
            logger.info(f"[RAG] Injecting {len(formatted)} chars into context")
            return formatted

        except Exception as e:
            # V11 DIAGNOSTIC: Log exceptions instead of silent fail
            logger.error(f"[RAG] Exception during retrieval: {e}", exc_info=True)
            return ""
