"""
Skill Crystallizer - Auto-compile repeated tool sequences into reusable skills.

V12.4 COGNITIVE BOOST - Task #29

Detects repeated tool execution patterns and crystallizes them into
parameterized, reusable skill templates. Skills are persisted to disk
and can be replayed with different parameters.

Usage:
    from core.memory_pkg.skills import SkillCrystallizer, ToolCallRecord

    crystallizer = SkillCrystallizer()

    # Record tool calls as they happen
    crystallizer.record(ToolCallRecord(tool_name="read", arguments={"path": "a.py"}))
    crystallizer.record(ToolCallRecord(tool_name="edit", arguments={"path": "a.py", "old": "x", "new": "y"}))
    crystallizer.record(ToolCallRecord(tool_name="bash", arguments={"command": "pytest"}))

    # Detect patterns and crystallize
    patterns = crystallizer.detect_patterns()
    skills = crystallizer.crystallize()
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Data Types
# =============================================================================


@dataclass
class ToolCallRecord:
    """Record of a single tool call execution."""

    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    success: bool = True
    output: str = ""
    error: str = ""
    duration_seconds: float = 0.0
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(UTC).isoformat()

    @property
    def signature(self) -> str:
        """Tool name + sorted argument keys = structural signature."""
        keys = sorted(self.arguments.keys())
        return f"{self.tool_name}({','.join(keys)})"

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "success": self.success,
            "output": self.output[:200] if self.output else "",
            "error": self.error,
            "duration_seconds": self.duration_seconds,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolCallRecord:
        return cls(
            tool_name=data["tool_name"],
            arguments=data.get("arguments", {}),
            success=data.get("success", True),
            output=data.get("output", ""),
            error=data.get("error", ""),
            duration_seconds=data.get("duration_seconds", 0.0),
            timestamp=data.get("timestamp", ""),
        )


@dataclass
class ToolSequencePattern:
    """A detected repeated sequence of tool calls."""

    pattern_id: str
    tool_names: list[str]
    signatures: list[str]
    occurrence_count: int
    occurrences: list[list[ToolCallRecord]] = field(default_factory=list)
    first_seen: str = ""
    last_seen: str = ""
    avg_duration_seconds: float = 0.0
    success_rate: float = 1.0

    def __post_init__(self):
        if not self.pattern_id:
            self.pattern_id = self._generate_id()

    @property
    def length(self) -> int:
        return len(self.tool_names)

    @property
    def sequence_hash(self) -> str:
        """Hash of the tool name sequence for comparison."""
        raw = "->".join(self.tool_names)
        return hashlib.sha256(raw.encode()).hexdigest()[:12]

    def _generate_id(self) -> str:
        raw = "->".join(self.tool_names)
        return hashlib.sha256(raw.encode()).hexdigest()[:8]

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "tool_names": self.tool_names,
            "signatures": self.signatures,
            "occurrence_count": self.occurrence_count,
            "length": self.length,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "avg_duration_seconds": round(self.avg_duration_seconds, 3),
            "success_rate": round(self.success_rate, 4),
        }


@dataclass
class CrystallizedSkill:
    """A reusable parameterized skill compiled from a pattern."""

    skill_id: str
    name: str
    description: str
    tool_steps: list[dict[str, Any]]
    parameters: list[dict[str, Any]] = field(default_factory=list)
    source_pattern_id: str = ""
    created_at: str = ""
    invocation_count: int = 0
    success_rate: float = 1.0
    tags: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.skill_id:
            self.skill_id = uuid.uuid4().hex[:8]
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat()

    @property
    def step_count(self) -> int:
        return len(self.tool_steps)

    def render_steps(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Render tool steps with concrete parameter values.

        Args:
            params: Parameter name -> value mapping

        Returns:
            List of tool call dicts with parameters substituted
        """
        rendered = []
        for step in self.tool_steps:
            rendered_step = {
                "tool_name": step["tool_name"],
                "arguments": self._substitute_params(step.get("arguments", {}), params),
            }
            rendered.append(rendered_step)
        return rendered

    def _substitute_params(self, arguments: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        """Replace {{param}} placeholders with actual values."""
        result = {}
        for key, value in arguments.items():
            if isinstance(value, str):
                for param_name, param_value in params.items():
                    placeholder = "{{" + param_name + "}}"
                    if placeholder in value:
                        value = value.replace(placeholder, str(param_value))
                result[key] = value
            else:
                result[key] = value
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "tool_steps": self.tool_steps,
            "parameters": self.parameters,
            "source_pattern_id": self.source_pattern_id,
            "created_at": self.created_at,
            "invocation_count": self.invocation_count,
            "success_rate": round(self.success_rate, 4),
            "step_count": self.step_count,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CrystallizedSkill:
        return cls(
            skill_id=data["skill_id"],
            name=data["name"],
            description=data.get("description", ""),
            tool_steps=data.get("tool_steps", []),
            parameters=data.get("parameters", []),
            source_pattern_id=data.get("source_pattern_id", ""),
            created_at=data.get("created_at", ""),
            invocation_count=data.get("invocation_count", 0),
            success_rate=data.get("success_rate", 1.0),
            tags=data.get("tags", []),
        )


# =============================================================================
# Skill Crystallizer Engine
# =============================================================================


class SkillCrystallizer:
    """
    Detects repeated tool execution patterns and crystallizes them
    into reusable parameterized skills.

    The crystallizer operates in three phases:
    1. record() - Accumulate tool call history
    2. detect_patterns() - Find repeated sequences
    3. crystallize() - Compile patterns into reusable skills

    Skills are persisted to disk and can be loaded across sessions.
    """

    DEFAULT_MIN_OCCURRENCES = 2
    DEFAULT_MIN_SEQUENCE_LENGTH = 2
    DEFAULT_MAX_SEQUENCE_LENGTH = 10
    DEFAULT_MAX_HISTORY = 500

    def __init__(
        self,
        storage_path: Path | None = None,
        min_occurrences: int = DEFAULT_MIN_OCCURRENCES,
        min_sequence_length: int = DEFAULT_MIN_SEQUENCE_LENGTH,
        max_sequence_length: int = DEFAULT_MAX_SEQUENCE_LENGTH,
        max_history: int = DEFAULT_MAX_HISTORY,
    ):
        """
        Initialize the skill crystallizer.

        Args:
            storage_path: Directory for persisting skills (None = in-memory only)
            min_occurrences: Minimum times a sequence must repeat to become a pattern
            min_sequence_length: Minimum tool calls in a sequence
            max_sequence_length: Maximum tool calls in a sequence
            max_history: Maximum tool call records to retain
        """
        self._storage_path = Path(storage_path) if storage_path else None
        self.min_occurrences = min_occurrences
        self.min_sequence_length = min_sequence_length
        self.max_sequence_length = max_sequence_length
        self.max_history = max_history

        self._history: list[ToolCallRecord] = []
        self._skills: dict[str, CrystallizedSkill] = {}
        self._patterns: dict[str, ToolSequencePattern] = {}

        # Load persisted skills
        if self._storage_path:
            self._load_skills()

    # =========================================================================
    # Recording
    # =========================================================================

    def record(self, call: ToolCallRecord) -> None:
        """
        Record a tool call execution.

        Args:
            call: The tool call record to add
        """
        self._history.append(call)

        # Trim history if over limit
        if len(self._history) > self.max_history:
            self._history = self._history[-self.max_history :]

    def record_batch(self, calls: list[ToolCallRecord]) -> None:
        """Record multiple tool calls at once."""
        for call in calls:
            self.record(call)

    @property
    def history_size(self) -> int:
        return len(self._history)

    def clear_history(self) -> None:
        """Clear all recorded tool calls."""
        self._history.clear()

    # =========================================================================
    # Pattern Detection
    # =========================================================================

    def detect_patterns(self) -> list[ToolSequencePattern]:
        """
        Scan history for repeated tool sequences.

        Uses n-gram analysis over tool name sequences to find
        subsequences that appear >= min_occurrences times.

        Returns:
            List of detected patterns sorted by occurrence count (descending)
        """
        if len(self._history) < self.min_sequence_length:
            return []

        tool_names = [r.tool_name for r in self._history]
        patterns: dict[str, ToolSequencePattern] = {}

        # Scan all n-gram lengths
        for length in range(self.min_sequence_length, self.max_sequence_length + 1):
            if length > len(tool_names):
                break

            ngram_positions = self._find_ngram_positions(tool_names, length)

            for _ngram_key, positions in ngram_positions.items():
                if len(positions) < self.min_occurrences:
                    continue

                names = tool_names[positions[0] : positions[0] + length]
                signatures = [self._history[positions[0] + i].signature for i in range(length)]

                # Build occurrences
                occurrences = []
                for pos in positions:
                    occurrence = self._history[pos : pos + length]
                    occurrences.append(occurrence)

                # Compute stats
                total_duration = 0.0
                total_success = 0
                total_calls = 0
                for occ in occurrences:
                    for call in occ:
                        total_duration += call.duration_seconds
                        total_calls += 1
                        if call.success:
                            total_success += 1

                avg_duration = total_duration / len(occurrences) if occurrences else 0.0
                success_rate = total_success / total_calls if total_calls > 0 else 1.0

                timestamps = []
                for occ in occurrences:
                    if occ:
                        timestamps.append(occ[0].timestamp)

                pattern = ToolSequencePattern(
                    pattern_id="",
                    tool_names=names,
                    signatures=signatures,
                    occurrence_count=len(positions),
                    occurrences=occurrences,
                    first_seen=min(timestamps) if timestamps else "",
                    last_seen=max(timestamps) if timestamps else "",
                    avg_duration_seconds=avg_duration,
                    success_rate=success_rate,
                )

                # Use sequence_hash to deduplicate
                patterns[pattern.sequence_hash] = pattern

        # Filter out sub-patterns that are fully contained in longer patterns
        result = self._remove_subpatterns(list(patterns.values()))

        # Sort by occurrence count descending
        result.sort(key=lambda p: p.occurrence_count, reverse=True)

        self._patterns = {p.pattern_id: p for p in result}
        return result

    def _find_ngram_positions(self, tool_names: list[str], length: int) -> dict[str, list[int]]:
        """Find all positions where each n-gram of given length occurs."""
        ngrams: dict[str, list[int]] = {}
        for i in range(len(tool_names) - length + 1):
            key = "->".join(tool_names[i : i + length])
            if key not in ngrams:
                ngrams[key] = []
            # Only add non-overlapping positions
            if not ngrams[key] or i >= ngrams[key][-1] + length:
                ngrams[key].append(i)
        return ngrams

    def _remove_subpatterns(self, patterns: list[ToolSequencePattern]) -> list[ToolSequencePattern]:
        """Remove patterns that are strict subsequences of longer patterns."""
        if not patterns:
            return []

        # Sort by length descending
        patterns.sort(key=lambda p: p.length, reverse=True)

        result = []
        seen_sequences: set[str] = set()

        for pattern in patterns:
            seq = "->".join(pattern.tool_names)
            is_subpattern = False

            for seen in seen_sequences:
                if seq in seen and seq != seen:
                    is_subpattern = True
                    break

            if not is_subpattern:
                result.append(pattern)
                seen_sequences.add(seq)

        return result

    # =========================================================================
    # Crystallization
    # =========================================================================

    def crystallize(self, patterns: list[ToolSequencePattern] | None = None) -> list[CrystallizedSkill]:
        """
        Compile detected patterns into reusable parameterized skills.

        Args:
            patterns: Patterns to crystallize (runs detect_patterns if None)

        Returns:
            List of newly crystallized skills
        """
        if patterns is None:
            patterns = self.detect_patterns()

        new_skills = []
        for pattern in patterns:
            # Skip if already crystallized
            if any(s.source_pattern_id == pattern.pattern_id for s in self._skills.values()):
                continue

            skill = self._compile_skill(pattern)
            if skill:
                self._skills[skill.skill_id] = skill
                new_skills.append(skill)

        # Persist if storage configured
        if self._storage_path and new_skills:
            self._save_skills()

        _logger.info(f"Crystallized {len(new_skills)} new skills from {len(patterns)} patterns")

        return new_skills

    def _compile_skill(self, pattern: ToolSequencePattern) -> CrystallizedSkill | None:
        """Compile a single pattern into a skill."""
        if not pattern.occurrences:
            return None

        # Extract parameter templates from occurrences
        tool_steps = []
        parameters = []
        param_index = 0

        for step_idx in range(pattern.length):
            # Collect all argument values for this step across occurrences
            step_args_across_occurrences = []
            for occ in pattern.occurrences:
                if step_idx < len(occ):
                    step_args_across_occurrences.append(occ[step_idx].arguments)

            tool_name = pattern.tool_names[step_idx]
            template_args, step_params, param_index = self._extract_parameters(
                tool_name, step_idx, step_args_across_occurrences, param_index
            )

            tool_steps.append(
                {
                    "tool_name": tool_name,
                    "arguments": template_args,
                    "step_index": step_idx,
                }
            )
            parameters.extend(step_params)

        # Generate name from tool sequence
        name = self._generate_skill_name(pattern.tool_names)

        # Generate description
        step_desc = " -> ".join(pattern.tool_names)
        description = (
            f"Auto-crystallized skill: {step_desc}. "
            f"Detected {pattern.occurrence_count} times with "
            f"{pattern.success_rate:.0%} success rate."
        )

        # Generate tags from tool names
        tags = list(set(pattern.tool_names))

        return CrystallizedSkill(
            skill_id="",
            name=name,
            description=description,
            tool_steps=tool_steps,
            parameters=parameters,
            source_pattern_id=pattern.pattern_id,
            tags=tags,
        )

    def _extract_parameters(
        self,
        tool_name: str,
        step_idx: int,
        args_list: list[dict[str, Any]],
        param_index: int,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], int]:
        """
        Analyze argument values across occurrences to find variable parts.

        Arguments that vary across occurrences become parameters.
        Arguments that are constant become fixed values.

        Returns:
            (template_args, new_parameters, updated_param_index)
        """
        if not args_list:
            return {}, [], param_index

        # Collect all keys
        all_keys: set[str] = set()
        for args in args_list:
            all_keys.update(args.keys())

        template_args: dict[str, Any] = {}
        new_params: list[dict[str, Any]] = []

        for key in sorted(all_keys):
            values = [args.get(key) for args in args_list if key in args]

            if not values:
                continue

            # Check if all values are the same (constant)
            unique_values = set()
            for v in values:
                if isinstance(v, (dict, list)):
                    unique_values.add(json.dumps(v, sort_keys=True))
                else:
                    unique_values.add(str(v))

            if len(unique_values) == 1:
                # Constant value - use as-is
                template_args[key] = values[0]
            else:
                # Variable value - create parameter
                param_name = f"{tool_name}_{step_idx}_{key}"
                template_args[key] = "{{" + param_name + "}}"

                # Infer type from values
                param_type = self._infer_param_type(values)

                new_params.append(
                    {
                        "name": param_name,
                        "key": key,
                        "step_index": step_idx,
                        "tool_name": tool_name,
                        "type": param_type,
                        "examples": [str(v) for v in values[:3]],
                    }
                )
                param_index += 1

        return template_args, new_params, param_index

    def _infer_param_type(self, values: list[Any]) -> str:
        """Infer parameter type from example values."""
        types = set()
        for v in values:
            if isinstance(v, bool):
                types.add("boolean")
            elif isinstance(v, int):
                types.add("integer")
            elif isinstance(v, float):
                types.add("number")
            elif isinstance(v, str):
                types.add("string")
            elif isinstance(v, list):
                types.add("array")
            elif isinstance(v, dict):
                types.add("object")

        if len(types) == 1:
            return types.pop()
        return "string"  # Default to string for mixed types

    def _generate_skill_name(self, tool_names: list[str]) -> str:
        """Generate a human-readable skill name from tool sequence."""
        # Count tool frequency
        counts = Counter(tool_names)
        parts = []
        seen = set()
        for name in tool_names:
            if name not in seen:
                if counts[name] > 1:
                    parts.append(f"{name}x{counts[name]}")
                else:
                    parts.append(name)
                seen.add(name)
        return "_".join(parts)

    # =========================================================================
    # Skill Management
    # =========================================================================

    def get_skill(self, skill_id: str) -> CrystallizedSkill | None:
        """Get a skill by ID."""
        return self._skills.get(skill_id)

    def get_skill_by_name(self, name: str) -> CrystallizedSkill | None:
        """Get a skill by name."""
        for skill in self._skills.values():
            if skill.name == name:
                return skill
        return None

    def list_skills(self) -> list[CrystallizedSkill]:
        """List all crystallized skills."""
        return list(self._skills.values())

    def remove_skill(self, skill_id: str) -> bool:
        """Remove a skill by ID."""
        if skill_id in self._skills:
            del self._skills[skill_id]
            if self._storage_path:
                self._save_skills()
            return True
        return False

    def find_matching_skill(self, tool_names: list[str]) -> CrystallizedSkill | None:
        """
        Find a skill that matches a tool name sequence.

        Args:
            tool_names: Sequence of tool names to match

        Returns:
            Matching skill or None
        """
        target_hash = hashlib.sha256("->".join(tool_names).encode()).hexdigest()[:12]

        for skill in self._skills.values():
            skill_names = [s["tool_name"] for s in skill.tool_steps]
            skill_hash = hashlib.sha256("->".join(skill_names).encode()).hexdigest()[:12]
            if skill_hash == target_hash:
                return skill
        return None

    def record_skill_invocation(self, skill_id: str, success: bool) -> None:
        """
        Record that a skill was invoked.

        Args:
            skill_id: The skill that was used
            success: Whether execution succeeded
        """
        skill = self._skills.get(skill_id)
        if skill:
            skill.invocation_count += 1
            # Rolling success rate
            total = skill.invocation_count
            old_success = skill.success_rate * (total - 1)
            skill.success_rate = (old_success + (1.0 if success else 0.0)) / total

            if self._storage_path:
                self._save_skills()

    # =========================================================================
    # Persistence
    # =========================================================================

    def _save_skills(self) -> None:
        """Save skills to disk."""
        if not self._storage_path:
            return

        self._storage_path.mkdir(parents=True, exist_ok=True)
        skills_file = self._storage_path / "skills.json"

        data = {
            "version": "1.0",
            "updated_at": datetime.now(UTC).isoformat(),
            "skills": {sid: skill.to_dict() for sid, skill in self._skills.items()},
        }

        skills_file.write_text(json.dumps(data, indent=2))
        _logger.debug(f"Saved {len(self._skills)} skills to {skills_file}")

    def _load_skills(self) -> None:
        """Load skills from disk."""
        if not self._storage_path:
            return

        skills_file = self._storage_path / "skills.json"
        if not skills_file.exists():
            return

        try:
            data = json.loads(skills_file.read_text())
            for sid, skill_data in data.get("skills", {}).items():
                self._skills[sid] = CrystallizedSkill.from_dict(skill_data)
            _logger.debug(f"Loaded {len(self._skills)} skills from {skills_file}")
        except (json.JSONDecodeError, KeyError) as e:
            _logger.warning(f"Failed to load skills: {e}")

    def to_dict(self) -> dict[str, Any]:
        """Export crystallizer state."""
        return {
            "history_size": self.history_size,
            "pattern_count": len(self._patterns),
            "skill_count": len(self._skills),
            "skills": {sid: skill.to_dict() for sid, skill in self._skills.items()},
            "config": {
                "min_occurrences": self.min_occurrences,
                "min_sequence_length": self.min_sequence_length,
                "max_sequence_length": self.max_sequence_length,
                "max_history": self.max_history,
            },
        }


# =============================================================================
# Global Instance
# =============================================================================

import threading as _threading  # noqa: E402  # singleton setup after class definition

_crystallizer: SkillCrystallizer | None = None
_crystallizer_lock = _threading.Lock()


def get_crystallizer() -> SkillCrystallizer:
    """Get or create the global SkillCrystallizer instance."""
    global _crystallizer
    if _crystallizer is None:
        with _crystallizer_lock:
            if _crystallizer is None:
                _crystallizer = SkillCrystallizer()
    return _crystallizer


def reset_crystallizer() -> None:
    """Reset the global SkillCrystallizer (for testing)."""
    global _crystallizer
    _crystallizer = None
