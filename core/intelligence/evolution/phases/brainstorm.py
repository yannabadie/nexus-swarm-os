"""
Brainstorm Phase - V7.5 Phase 0a

AI-driven mutation proposal generation.
Extracted from repl.py:brainstorm_children_with_ais()

This implements EVOLUTION_PROTOCOL.md Phase 1, Step 2:
"Design Mutation - Brainstorm with collaborator (Gemini <-> Claude)"
"""

import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from core.fsm.states import OrchestratorState
from core.intelligence.evolution.models import (
    BrainstormResult,
    MutationProposal,
)
from core.intelligence.evolution.mutation_parser import MutationParser
from core.memory_pkg.prompts import load_prompt
from core.utils.json_extractor import extract_json_safe as robust_extract_json

# Type alias for progress callback
ProgressCallback = Callable[[str, float], None]


class BrainstormPhase:
    """
    Phase 1: AI-driven mutation brainstorming.

    Uses Gemini + Claude EVOLUTION_BRAINSTORM mode to generate
    emergent mutations through collaborative debate.
    """

    def __init__(
        self,
        orchestrator: Any,
        workspace_path: Path,
        progress_callback: ProgressCallback | None = None,
    ):
        """
        Initialize brainstorm phase.

        Args:
            orchestrator: OrchestratorV7 instance
            workspace_path: Path to workspace directory
            progress_callback: Optional callback for progress updates
        """
        self.orchestrator = orchestrator
        self.workspace_path = workspace_path
        self.progress_callback = progress_callback
        self._abort_requested = False

    def _report_progress(self, message: str, progress: float = 0.0):
        """Report progress to callback if available"""
        if self.progress_callback:
            self.progress_callback(message, progress)

    def request_abort(self):
        """Request abort of current brainstorming"""
        self._abort_requested = True

    def _clear_context(self):
        """Clear short-term memory for focused brainstorming"""
        self._report_progress("Clearing short-term memory...", 0.05)
        self.orchestrator.blackboard["recent_history"] = []
        self.orchestrator.memory.save_to_disk()

    def _cleanup_hallucinations(self):
        """Remove hallucinated directories from previous sessions"""
        hallucination_dirs = ["_SHARED_CODE", "_temp"]
        for dirname in hallucination_dirs:
            cleanup_path = self.workspace_path / dirname
            if cleanup_path.exists():
                shutil.rmtree(cleanup_path)
                self._report_progress(f"Cleaned up: {dirname}/", 0.06)

    def _load_lineage_context(self, parent_path: Path) -> str:
        """Load lineage context for brainstorming"""
        lineage_path = parent_path.parent / "LINEAGE.json"
        if lineage_path.exists():
            return lineage_path.read_text(encoding="utf-8")[:2000]
        return ""

    def _extract_search_replace_blocks(self, text: str) -> list[dict]:
        """
        Extract mutations from SEARCH/REPLACE block format.
        This format preserves exact indentation (no \\n escaping issues).
        """
        parser = MutationParser()
        mutations = parser.parse(text)

        if not mutations:
            return []

        # Convert to legacy dict format for compatibility
        return [m.to_dict() for m in mutations]

    def _extract_generated_prompt(self, content: str, min_lines: int = 30) -> str | None:
        """
        Extract generated system prompt from brainstorm output.

        V8.1.8: For mode="prompt", extract markdown block starting with #.

        Args:
            content: Full brainstorm output
            min_lines: Minimum lines required (default 30)

        Returns:
            Extracted prompt string or None if not found/too short
        """
        import re

        # Strategy 1: Look for markdown code block with system prompt
        code_block_pattern = r"```(?:markdown)?\s*\n(#[^`]+)```"
        matches = re.findall(code_block_pattern, content, re.DOTALL)

        for match in matches:
            lines = match.strip().split("\n")
            if len(lines) >= min_lines:
                self._report_progress(f"Found prompt in code block ({len(lines)} lines)", 0.85)
                return match.strip()

        # Strategy 2: Look for standalone markdown starting with #
        # Find last substantial markdown section starting with #
        sections = re.split(r"\n(?=#\s+)", content)
        for section in reversed(sections):
            if section.startswith("#"):
                lines = section.strip().split("\n")
                if len(lines) >= min_lines:
                    self._report_progress(f"Found standalone prompt ({len(lines)} lines)", 0.85)
                    return section.strip()

        # Strategy 3: If nothing found, try to extract any # section with >20 lines
        for section in reversed(sections):
            if section.startswith("#"):
                lines = section.strip().split("\n")
                if len(lines) >= 20:  # Lower threshold for fallback
                    self._report_progress(f"Found fallback prompt ({len(lines)} lines)", 0.85)
                    return section.strip()

        self._report_progress("No valid prompt found in output", 0.85)
        return None

    def _extract_mutations(self, final_content: str, child_count: int) -> list[dict] | None:
        """
        Extract mutations from brainstorming output.

        Tries SEARCH/REPLACE format first, then JSON fallback.

        Args:
            final_content: Combined output from brainstorming
            child_count: Expected number of mutations

        Returns:
            List of mutation dicts or None if extraction failed
        """
        required_keys = {"file", "change", "reason", "expected_asi_impact"}

        for retry in range(3):
            # PRIORITY 1: Try SEARCH/REPLACE format first
            proposals = self._extract_search_replace_blocks(final_content)
            if proposals:
                self._report_progress(f"SEARCH/REPLACE: {len(proposals)} mutations", 0.9)
                return proposals

            # PRIORITY 2: Fallback to JSON format
            json_result, _ = robust_extract_json(final_content, verbose=False)

            if (
                json_result
                and isinstance(json_result, list)
                and all(isinstance(p, dict) and required_keys.issubset(p.keys()) for p in json_result)
            ):
                self._report_progress(f"JSON format: {len(json_result)} mutations", 0.9)
                return json_result

            # Check for wrapped format {"mutations": [...]}
            if (
                json_result
                and isinstance(json_result, dict)
                and "mutations" in json_result
                and isinstance(json_result["mutations"], list)
            ):
                proposals = json_result["mutations"]
                if all(isinstance(p, dict) and required_keys.issubset(p.keys()) for p in proposals):
                    self._report_progress(f"JSON format: {len(proposals)} mutations", 0.9)
                    return proposals

            self._report_progress(f"Retry {retry + 1}/3: extraction failed", 0.8)

            # Retry by continuing debate
            if retry < 2:
                reminder_msg = {
                    "sender": "System",
                    "action_type": "TALK",
                    "content": f"""REMINDER: Mutation format not parsed correctly.

EXPECTED SEARCH/REPLACE FORMAT:
```
FILE: core/file.py
REASON: Description
IMPACT: 0.03

<<<<<<< SEARCH
original exact code
=======
new code
>>>>>>> REPLACE
```

PRODUCE MUTATION BLOCKS NOW ({child_count} mutations required).""",
                    "status": "CONTINUE",
                }
                self.orchestrator.memory.add_to_history(reminder_msg)

                # Ensure we're in EVOLUTION_BRAINSTORM state
                if self.orchestrator.state != OrchestratorState.EVOLUTION_BRAINSTORM:
                    self.orchestrator._transition_to(OrchestratorState.EVOLUTION_BRAINSTORM)

                # Continue debate
                result = self.orchestrator.process_turn()
                new_output = result.get("output") or ""
                final_content = final_content + "\n" + new_output

        return None

    def run(
        self,
        parent_id: str,
        parent_path: Path,
        child_count: int = 3,
        focus_areas: list[str] | None = None,
        mode: str = "mutation",
        custom_task: str | None = None,
    ) -> BrainstormResult:
        """
        Run brainstorming phase.

        V8.1.8: Added mode="prompt" for system prompt generation.

        Args:
            parent_id: Current parent NEXUS ID
            parent_path: Path to parent NEXUS
            child_count: Number of children to propose
            focus_areas: Optional focus areas for mutations
            mode: "mutation" (default) or "prompt" for system prompt generation
            custom_task: Optional custom task string (required for mode="prompt")

        Returns:
            BrainstormResult with proposed mutations or generated_prompt
        """
        start_time = time.time()
        self._abort_requested = False

        is_prompt_mode = mode == "prompt"
        mode_label = "prompt generation" if is_prompt_mode else "mutation brainstorming"
        self._report_progress(f"Starting {mode_label}...", 0.1)

        # Clear context and cleanup
        self._clear_context()
        self._cleanup_hallucinations()

        # V8.1.8: Different max iterations for prompt mode (faster)
        max_iterations = 10 if is_prompt_mode else 30

        # Load task based on mode
        if is_prompt_mode:
            if not custom_task:
                return BrainstormResult(
                    mutations=[],
                    debate_turns=0,
                    consensus_reached=False,
                    duration_seconds=time.time() - start_time,
                    errors=["mode='prompt' requires custom_task parameter"],
                )
            brainstorm_task = custom_task
        else:
            # Load lineage context for mutation mode
            lineage_context = self._load_lineage_context(parent_path)
            try:
                brainstorm_task = load_prompt(
                    "evolution_brainstorm",
                    {"child_count": child_count, "parent_id": parent_id, "lineage_context": lineage_context[:500]},
                )
            except FileNotFoundError as e:
                return BrainstormResult(
                    mutations=[],
                    debate_turns=0,
                    consensus_reached=False,
                    duration_seconds=time.time() - start_time,
                    errors=[f"Missing prompt file: {e}"],
                )

        # Switch to EVOLUTION_BRAINSTORM mode
        original_state = self.orchestrator.state
        self.orchestrator._transition_to(OrchestratorState.EVOLUTION_BRAINSTORM)
        self._report_progress("Mode: EVOLUTION_BRAINSTORM", 0.15)

        # Start brainstorming
        result = self.orchestrator.process_turn(brainstorm_task)

        # Track outputs for extraction
        all_outputs = [result.get("output") or ""]
        iterations = 0

        # Continue until FINISHED, IDLE, or max turns
        while result["state"] not in ["IDLE", "ERROR", "PANIC"] and iterations < max_iterations:
            if self._abort_requested:
                self._report_progress("Abort requested", 0.5)
                break

            result = self.orchestrator.process_turn()
            iterations += 1

            output = result.get("output") or ""
            all_outputs.append(output)

            progress = 0.2 + (0.5 * (iterations / max_iterations))
            self._report_progress(f"Debate turn {iterations}/{max_iterations}", progress)

            # Check if finished
            if result.get("finished"):
                break

            # Check for consensus signals
            output_lower = output.lower()
            if (
                '"status": "FINISHED"' in output.upper()
                or '"status":"FINISHED"' in output.upper()
                or "consensus reached" in output_lower
                or "accord mutuel" in output_lower
            ):
                self._report_progress("Consensus reached", 0.75)
                break

            # V8.1.8: Mode-specific early exit detection
            if is_prompt_mode:
                # For prompt mode: detect when substantial markdown is generated
                if iterations >= 3:
                    combined = "\n".join(all_outputs)
                    if combined.count("\n#") >= 3 and len(combined) > 1500:
                        self._report_progress("System prompt detected", 0.75)
                        break
            else:
                # For mutation mode: detect SEARCH/REPLACE blocks
                if iterations >= 4:
                    if (
                        "FILE:" in output
                        and "<<<<<<< SEARCH" in output
                        and "=======" in output
                        and ">>>>>>> REPLACE" in output
                    ):
                        self._report_progress("Mutations detected", 0.75)
                        break

                    if (
                        '"file"' in output
                        and '"change"' in output
                        and '"reason"' in output
                        and '"expected_asi_impact"' in output
                    ):
                        self._report_progress("JSON mutations detected", 0.75)
                        break

        # Return to original state
        self.orchestrator._transition_to(original_state)

        # Check for errors
        if result["state"] in ["ERROR", "PANIC"]:
            return BrainstormResult(
                mutations=[],
                debate_turns=iterations,
                consensus_reached=False,
                duration_seconds=time.time() - start_time,
                errors=[f"Brainstorming failed with state: {result['state']}"],
            )

        # V8.1.8: Mode-specific extraction
        final_content = "\n".join(all_outputs)

        if is_prompt_mode:
            # Extract generated system prompt
            generated_prompt = self._extract_generated_prompt(final_content)

            if generated_prompt is None:
                return BrainstormResult(
                    mutations=[],
                    debate_turns=iterations,
                    consensus_reached=False,
                    duration_seconds=time.time() - start_time,
                    errors=["Failed to extract valid system prompt (min 20 lines required)"],
                )

            self._report_progress("Prompt generation complete", 1.0)

            return BrainstormResult(
                mutations=[],
                debate_turns=iterations,
                consensus_reached=True,
                duration_seconds=time.time() - start_time,
                errors=[],
                generated_prompt=generated_prompt,
            )

        # Mutation mode: Extract mutations
        proposals = self._extract_mutations(final_content, child_count)

        if proposals is None:
            return BrainstormResult(
                mutations=[],
                debate_turns=iterations,
                consensus_reached=False,
                duration_seconds=time.time() - start_time,
                errors=["Failed to extract valid mutations after 3 attempts"],
            )

        # Convert to MutationProposal objects
        mutations = []
        for i, p in enumerate(proposals):
            mutations.append(
                MutationProposal(
                    id=f"mutation_{i + 1}",
                    name=p.get("file", f"mutation_{i + 1}"),
                    description=p.get("reason", ""),
                    files_to_modify=[p.get("file", "")],
                    patches=[
                        {
                            "search": p.get("change", {}).get("search", "")
                            if isinstance(p.get("change"), dict)
                            else "",
                            "replace": p.get("change", {}).get("replace", "")
                            if isinstance(p.get("change"), dict)
                            else str(p.get("change", "")),
                        }
                    ],
                    rationale=p.get("reason", ""),
                    source_agent="consensus",
                    confidence=float(p.get("expected_asi_impact", 0.0)),
                    metadata=p,
                )
            )

        self._report_progress(f"Brainstorming complete: {len(mutations)} mutations", 1.0)

        return BrainstormResult(
            mutations=mutations,
            debate_turns=iterations,
            consensus_reached=True,
            duration_seconds=time.time() - start_time,
            errors=[],
        )


def run_brainstorm(
    orchestrator: Any,
    workspace_path: Path,
    parent_id: str,
    parent_path: Path,
    child_count: int = 3,
    progress_callback: ProgressCallback | None = None,
) -> BrainstormResult:
    """
    Convenience function to run brainstorming phase.

    Args:
        orchestrator: OrchestratorV7 instance
        workspace_path: Path to workspace directory
        parent_id: Current parent NEXUS ID
        parent_path: Path to parent NEXUS
        child_count: Number of children to propose
        progress_callback: Optional callback for progress updates

    Returns:
        BrainstormResult with proposed mutations
    """
    phase = BrainstormPhase(orchestrator, workspace_path, progress_callback)
    return phase.run(parent_id, parent_path, child_count)
