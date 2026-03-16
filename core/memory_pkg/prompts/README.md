# Prompts Module

## Synopsis
The Prompts module provides a sophisticated prompt loading system with support for include directives and template variable substitution. It enables modular prompt composition by allowing prompts to reference shared components via `#include` directives, and supports dynamic content generation through template variables.

## Component Map
| File | Purpose | Key Exports |
|------|---------|-------------|
| `prompt_loader.py` | Prompt loading engine with include resolution and templating | `load_prompt()`, `resolve_includes()`, `apply_template()`, `get_prompt_info()`, `list_prompts()` |
| `__init__.py` | Module initialization with public API exports | `load_prompt`, `resolve_includes` |

## Key Interfaces

### Core Functions

**`load_prompt(prompt_name: str, variables: Optional[Dict[str, Any]] = None, prompts_dir: Optional[Path] = None) -> str`**
- Loads a prompt file, resolves all `#include` directives, and applies template variables
- Supports nested includes up to 10 levels deep
- Raises `FileNotFoundError` if prompt doesn't exist, `RecursionError` if includes nest too deeply
- Example: `load_prompt("system_gemini_v7", {"child_count": 3})`

**`resolve_includes(content: str, base_path: Path, depth: int = 0) -> str`**
- Recursively resolves `<!-- #include path/to/file.md -->` directives
- Maximum recursion depth of 10 to prevent infinite loops
- Returns error comments if includes fail or are not found

**`apply_template(content: str, variables: Dict[str, Any]) -> str`**
- Substitutes `{variable_name}` placeholders with actual values
- Simple string replacement without complex templating logic

**`get_prompt_info(prompt_name: str) -> Dict[str, Any]`**
- Returns metadata about a prompt: includes used, variables detected, line counts, expansion ratio
- Useful for debugging and validation

**`list_prompts() -> list`**
- Lists all available prompts (excludes `_` prefixed files and README.md)

## Dependencies & Integration

### Internal Dependencies
- `pathlib` - File path handling
- `re` - Regex for include directives and variable detection
- `typing` - Type hints

### Integration Points
- **Prompt Directory**: `prompts/` at project root (contains all system prompts)
- **Include Directive Pattern**: `<!-- #include _shared/file.md -->`
- **Template Variable Pattern**: `{variable_name}`

### Usage Pattern
```python
from core.prompts import load_prompt

# Load system prompts
gemini_prompt = load_prompt("system_gemini_v7")
claude_prompt = load_prompt("system_claude_v7")

# Load with template variables
evolution_prompt = load_prompt("evolution_brainstorm", {
    "child_count": 3,
    "parent_id": "NEXUS_V7",
    "lineage_context": "..."
})
```

### Design Notes
- **Include Resolution**: Recursive, supports nested includes up to 10 levels
- **Error Handling**: Graceful degradation with error comments in content
- **Base Directory**: Defaults to `prompts/` at project root, configurable
- **File Encoding**: UTF-8 for all prompt files
- **Modular Prompts**: Enables sharing common sections via `_shared/` includes
