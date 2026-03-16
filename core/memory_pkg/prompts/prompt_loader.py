"""
NEXUS V7.5 HIVE MIND - Prompt Loader

Loads prompts and resolves <!-- #include _shared/file.md --> directives.
Supports template variable substitution.

Usage:
    from core.memory_pkg.prompts import load_prompt

    # Simple load
    gemini_prompt = load_prompt("system_gemini_v7")

    # With template variables
    evolution_prompt = load_prompt("evolution_brainstorm", {
        "child_count": 3,
        "parent_id": "NEXUS_V7",
        "lineage_context": "..."
    })
"""

import re
from pathlib import Path
from typing import Any

# Base path for prompts (relative to project root)
PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"

# Include directive pattern: <!-- #include _shared/file.md -->
INCLUDE_PATTERN = re.compile(r"<!--\s*#include\s+(\S+)\s*-->")


def resolve_includes(content: str, base_path: Path, depth: int = 0) -> str:
    """
    Resolve all #include directives in content.

    Args:
        content: Prompt content with include directives
        base_path: Base path for resolving relative includes
        depth: Current recursion depth (max 10 to prevent infinite loops)

    Returns:
        Content with all includes resolved
    """
    if depth > 10:
        raise RecursionError("Too many nested includes (max 10 levels)")

    def replace_include(match: re.Match) -> str:
        include_path = match.group(1)
        full_path = base_path / include_path

        if not full_path.exists():
            return f"<!-- ERROR: Include not found: {include_path} -->"

        try:
            included_content = full_path.read_text(encoding="utf-8")
            # Recursively resolve includes in the included file
            return resolve_includes(included_content, full_path.parent, depth + 1)
        except Exception as e:
            return f"<!-- ERROR: Failed to include {include_path}: {e} -->"

    return INCLUDE_PATTERN.sub(replace_include, content)


def apply_template(content: str, variables: dict[str, Any]) -> str:
    """
    Apply template variables to content.

    Replaces {variable_name} with values from variables dict.

    Args:
        content: Content with {placeholders}
        variables: Dict of variable_name -> value

    Returns:
        Content with variables substituted
    """
    for key, value in variables.items():
        placeholder = "{" + key + "}"
        content = content.replace(placeholder, str(value))

    return content


def load_prompt(prompt_name: str, variables: dict[str, Any] | None = None, prompts_dir: Path | None = None) -> str:
    """
    Load a prompt file, resolve includes, and apply template variables.

    Args:
        prompt_name: Name of prompt file (without .md extension)
        variables: Optional dict of template variables to substitute
        prompts_dir: Optional custom prompts directory

    Returns:
        Assembled prompt with all includes resolved

    Raises:
        FileNotFoundError: If prompt file doesn't exist
        RecursionError: If includes nest too deeply (>10 levels)

    Example:
        >>> prompt = load_prompt("system_gemini_v7")
        >>> prompt = load_prompt("evolution_brainstorm", {"child_count": 3})
    """
    base_dir = prompts_dir or PROMPTS_DIR
    prompt_path = base_dir / f"{prompt_name}.md"

    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt not found: {prompt_path}")

    # Read raw content
    content = prompt_path.read_text(encoding="utf-8")

    # Resolve includes
    content = resolve_includes(content, base_dir)

    # Apply template variables if provided
    if variables:
        content = apply_template(content, variables)

    return content


def get_prompt_info(prompt_name: str) -> dict[str, Any]:
    """
    Get metadata about a prompt (includes, variables, line count).

    Useful for debugging and validation.

    Args:
        prompt_name: Name of prompt file (without .md extension)

    Returns:
        Dict with prompt metadata
    """
    prompt_path = PROMPTS_DIR / f"{prompt_name}.md"

    if not prompt_path.exists():
        return {"error": f"Prompt not found: {prompt_path}"}

    content = prompt_path.read_text(encoding="utf-8")

    # Find all includes
    includes = INCLUDE_PATTERN.findall(content)

    # Find all template variables
    variables = set(re.findall(r"\{(\w+)\}", content))

    # Calculate line counts
    raw_lines = len(content.splitlines())
    resolved = resolve_includes(content, PROMPTS_DIR)
    resolved_lines = len(resolved.splitlines())

    return {
        "name": prompt_name,
        "path": str(prompt_path),
        "raw_lines": raw_lines,
        "resolved_lines": resolved_lines,
        "includes": includes,
        "variables": list(variables),
        "expansion_ratio": resolved_lines / raw_lines if raw_lines > 0 else 0,
    }


def list_prompts() -> list:
    """
    List all available prompts in the prompts directory.

    Returns:
        List of prompt names (without .md extension)
    """
    return [p.stem for p in PROMPTS_DIR.glob("*.md") if not p.name.startswith("_") and p.name != "README.md"]
