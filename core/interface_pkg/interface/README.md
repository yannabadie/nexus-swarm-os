# NEXUS Interface Module

## Synopsis

The **interface** module provides the user-facing components of NEXUS, including the interactive REPL (Read-Eval-Print Loop), slash command system, and tutorial system. It serves as the primary entry point for CLI-based interaction with the orchestrator.

## Architecture

```
+-------------------------------------------------------------------------+
|                      INTERFACE ARCHITECTURE                              |
+-------------------------------------------------------------------------+
|                                                                          |
|  +------------------------------------------------------------------+   |
|  |                          REPL                                     |   |
|  |              Main interactive loop (nexus7.py)                    |   |
|  +----------------------------+-------------------------------------+   |
|                               |                                          |
|         +---------------------+---------------------+                   |
|         |                     |                     |                   |
|         v                     v                     v                   |
|  +--------------+    +--------------+    +------------------+          |
|  |SlashCommands |    |  Tutorial    |    |   Commands/      |          |
|  | (/help, etc) |    |  System      |    |   (handlers)     |          |
|  +--------------+    +--------------+    +------------------+          |
|         |                     |                     |                   |
|         +---------------------+---------------------+                   |
|                               v                                          |
|  +------------------------------------------------------------------+   |
|  |                      OrchestratorV7                               |   |
|  |                    process_turn(input)                            |   |
|  +------------------------------------------------------------------+   |
|                                                                          |
+-------------------------------------------------------------------------+
```

## Component Map

| File | Purpose | Key Exports |
|------|---------|-------------|
| `repl.py` | Main REPL loop | `REPL`, `run_repl()` |
| `slash_commands.py` | Command dispatcher | `SlashCommandHandler`, command registry |
| `tutorial.py` | Interactive tutorial | `TutorialSystem` |
| `commands/` | Individual command handlers | Command implementations |

## Slash Commands

| Command | Description | Handler |
|---------|-------------|---------|
| `/help` | Show available commands | `help_command` |
| `/status` | System status | `status_command` |
| `/reset` | Reset orchestrator state | `reset_command` |
| `/hive` | Trigger HiveMind pipeline | `hive_command` |
| `/swarm` | Explicit swarm mode | `swarm_command` |
| `/evolve` | Trigger evolution | `evolve_command` |
| `/specialize` | Create specialized spinoff | `specialize_command` |
| `/spawn` | Spawn new agent | `spawn_command` |
| `/clear` | Clear screen | `clear_command` |
| `/history` | Show conversation history | `history_command` |
| `/save` | Save session | `save_command` |
| `/load` | Load session | `load_command` |

## Key Interfaces

### REPL
```python
class REPL:
    """Main Read-Eval-Print Loop."""

    def __init__(self, orchestrator: OrchestratorV7)
    async def run(self) -> None
    def handle_input(self, user_input: str) -> bool
```

### SlashCommandHandler
```python
class SlashCommandHandler:
    """Dispatches slash commands to handlers."""

    def register(self, command: str, handler: Callable) -> None
    async def execute(self, command: str, args: List[str]) -> CommandResult
    def is_command(self, input: str) -> bool
```

## REPL Flow

```
+-------------+
|  User Input |
+------+------+
       |
       v
+------------------+
| Is slash command?|
+------+-----------+
       |
  Yes  |  No
   +---+---+
   v       v
+-----+ +-------------+
|Slash| |Orchestrator |
|Cmd  | |process_turn |
+-----+ +-------------+
```

## Commands Directory

The `commands/` subdirectory contains individual command implementations:

```
commands/
+-- __init__.py
+-- help.py
+-- status.py
+-- reset.py
+-- hive.py
+-- swarm.py
+-- evolve.py
+-- specialize.py
+-- spawn.py
+-- ...
```

## Usage

```python
from core.interface import REPL
from core.orchestration_v7 import OrchestratorV7

# Create orchestrator
orchestrator = OrchestratorV7(config)

# Create and run REPL
repl = REPL(orchestrator)
await repl.run()
```

## Dependencies

### Internal
- `core.orchestration_v7` - Main orchestrator
- `core.ui` - Console output formatting
- `core.interaction` - User input abstraction

### External
- `prompt_toolkit` - Enhanced terminal input (optional)
- Standard library (readline)

## Version History

- **V7.0** - Initial REPL implementation
- **V8.0** - HiveMind commands
- **V9.0** - Swarm commands
- **V12.4** - Enhanced command registry
