# UI Module

## Synopsis
The UI module provides the console interface for NEXUS using Rich library for styled terminal output. ConsoleV7 handles all user-facing display including banners, status messages, results, errors, help text, and markdown rendering with syntax highlighting.

## Component Map
| File | Purpose | Key Exports |
|------|---------|-------------|
| `console_v7.py` | Main console interface with Rich integration | `ConsoleV7` |
| `__init__.py` | Module initialization with public exports | `ConsoleV7` |

## Key Interfaces

**`ConsoleV7`**
- Minimalist console interface powered by Rich library
- Handles all terminal output with consistent styling
- Supports verbose mode for debugging

**Key Methods:**
- `print_banner(gemini_model: str, claude_model: str, version: str = "V7", codename: str = "CHRYSALIS")`: Display NEXUS startup banner with model info
- `display_result(result: Dict)`: Display orchestration result (final_response, state, etc.)
- `print_status(status: Dict)`: Display status information (FSM state, session, etc.)
- `print_doctor_results(results: Dict)`: Display /doctor diagnostic results
- `print_help(help_message: str)`: Display help text
- `print_error(error: str)`: Display error messages in red
- `print(message: str, style: Optional[str] = None)`: Print message with optional Rich style
- `clear()`: Clear terminal screen
- `show_spinner(text: str)`: Show spinner (context manager)
- `print_markdown(markdown_text: str)`: Render markdown with syntax highlighting

## Dependencies & Integration

### External Dependencies
- `rich` - Terminal styling, markdown rendering, progress indicators

### Internal Dependencies
- None (self-contained UI layer)

### Integration Points
- **REPL**: Uses ConsoleV7 for all user interactions
- **Orchestrators**: Call `display_result()` to show outcomes
- **Commands**: Use `print_help()`, `print_status()`, `print_error()`
- **TelemetryService**: Uses `print_markdown()` for reports

### Usage Examples

```python
from core.ui import ConsoleV7

# Initialize console
console = ConsoleV7(verbose=True)

# Print startup banner
console.print_banner(
    gemini_model="gemini-3-pro-preview",
    claude_model="claude-opus-4-6-20250116",
    version="V12.4",
    codename="COGNITIVE BOOST"
)

# Display result from orchestrator
console.display_result({
    "state": "HIVE_SUCCESS",
    "final_response": "Task completed successfully",
    "steps_taken": 5,
    "duration": 12.3
})

# Print status
console.print_status({
    "fsm_state": "IDLE",
    "session_id": "abc123",
    "swarm_mode": "PARALLEL"
})

# Print error
console.print_error("Failed to connect to API")

# Print with style
console.print("Task completed", style="bold green")

# Show spinner during operation
with console.show_spinner("Processing..."):
    # Long-running task
    pass

# Render markdown report
markdown = "# Report\\n\\n```python\\nprint('hello')\\n```"
console.print_markdown(markdown)
```

## Design Notes

- **Rich Integration**: All output styled via Rich for modern terminal experience
- **Verbose Mode**: Optional flag for debug/diagnostic output
- **Minimalist**: Simple API focused on essential display functions
- **Markdown Support**: Syntax-highlighted code blocks in output
- **Consistent Styling**: Errors (red), success (green), info (cyan), etc.
