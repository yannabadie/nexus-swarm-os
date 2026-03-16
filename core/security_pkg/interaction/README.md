# NEXUS Interaction Module

## Synopsis

The **interaction** module provides a clean abstraction layer for user interaction, enabling NEXUS to run in both interactive CLI and headless server modes. It supports ask/confirm/choose patterns with configurable defaults for non-interactive execution.

## Architecture

```
+-------------------------------------------------------------------------+
|                    INTERACTION ABSTRACTION                               |
+-------------------------------------------------------------------------+
|                                                                          |
|  +------------------------------------------------------------------+   |
|  |                  InteractionProvider (ABC)                        |   |
|  |  ask(), confirm(), choose(), announce()                           |   |
|  +----------------------------+-------------------------------------+   |
|                               |                                          |
|         +---------------------+---------------------+                   |
|         |                     |                     |                   |
|         v                     v                     v                   |
|  +--------------+    +--------------+    +------------------+          |
|  | CLIProvider  |    | Headless     |    | API Provider     |          |
|  | (Terminal)   |    | Provider     |    | (WebSocket)      |          |
|  +--------------+    +--------------+    +------------------+          |
|                               |                                          |
|                               v                                          |
|  +------------------------------------------------------------------+   |
|  |                    HITL Persistence (V12.2)                       |   |
|  |              Persist interaction state across restarts            |   |
|  +------------------------------------------------------------------+   |
|                                                                          |
+-------------------------------------------------------------------------+
```

## Component Map

| File | Purpose | Key Exports |
|------|---------|-------------|
| `base.py` | Abstract interface | `InteractionProvider`, `Choice`, `InteractionLevel` |
| `cli_provider.py` | Terminal input | `CLIProvider` |
| `headless_provider.py` | Non-blocking defaults | `HeadlessProvider` |
| `hitl_persistence.py` | V12.2 state persistence | HITL request storage |

## Key Interfaces

### InteractionProvider (ABC)
```python
class InteractionProvider(ABC):
    """Abstract interface for user interaction."""

    async def ask(
        self,
        prompt: str,
        default: Optional[str] = None
    ) -> str

    async def confirm(
        self,
        prompt: str,
        default: bool = False
    ) -> bool

    async def choose(
        self,
        prompt: str,
        choices: List[Choice],
        default: Optional[str] = None
    ) -> str

    async def announce(self, message: str) -> None
```

### Choice
```python
@dataclass
class Choice:
    key: str          # Selection key (e.g., "a", "b")
    description: str  # Display text
```

### InteractionLevel
```python
class InteractionLevel(Enum):
    SILENT = 0      # No output
    MINIMAL = 1     # Errors only
    NORMAL = 2      # Standard output
    VERBOSE = 3     # Debug output
```

## Configuration

Set `NEXUS_INTERACTION_MODE` environment variable:

| Mode | Provider | Behavior |
|------|----------|----------|
| `cli` (default) | CLIProvider | Interactive terminal |
| `headless` | HeadlessProvider | Returns defaults silently |
| `strict` | HeadlessProvider(strict=True) | Raises on missing defaults |

## Usage

```python
from core.interaction import get_interaction_provider

async def my_function():
    provider = get_interaction_provider()

    # Ask for input
    name = await provider.ask("Enter name", default="Anonymous")

    # Confirm action
    if await provider.confirm("Proceed?", default=True):
        await provider.announce("Processing...")

    # Multiple choice
    choice = await provider.choose(
        "Select option",
        choices=[
            Choice("a", "Option A"),
            Choice("b", "Option B"),
        ],
        default="a"
    )
```

## Multi-Tenant Support (V10)

```python
# V10 PRISM: Tenant-scoped provider via ServiceFactory
from core.context import has_active_session
from core.factory import ServiceFactory

if has_active_session():
    provider = ServiceFactory.get_interaction_provider()
else:
    provider = get_interaction_provider()  # Global fallback
```

## Dependencies

### Internal
- `core.context` - Session context (V10)
- `core.factory` - ServiceFactory (V10)
- `core.db.models` - HITLRequest model (V12.2)

### External
- Standard library (os, threading)

## V12.4 COGNITIVE BOOST Additions

| File | Purpose | Key Exports |
|------|---------|-------------|
| `interaction_quality_tracker.py` | Tracks HITL interaction quality metrics including per-type profiles (ask/confirm/choose/announce), user response latency distribution, satisfaction signals, and session engagement patterns for data-driven interaction improvements | `get_interaction_tracker`, `InteractionQualityTracker` |

## Version History

- **V9.8** - DETOX: Headless refactoring
- **V10.0** - PRISM: Multi-tenant provider access
- **V12.2** - IRONCLAD: HITL persistence
- **V12.4** - Interaction quality tracking
