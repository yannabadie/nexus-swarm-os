# NEXUS Interface Commands Module

## Synopsis

The **commands** module contains the implementations of all slash commands available in the NEXUS REPL. Commands are organized by domain (system, agents, evolution, memory, swarm, workspace) and registered via a central registry.

## Architecture

```
+-------------------------------------------------------------------------+
|                      COMMAND ARCHITECTURE                                |
+-------------------------------------------------------------------------+
|                                                                          |
|  +------------------------------------------------------------------+   |
|  |                     CommandRegistry                               |   |
|  |              Central command registration                         |   |
|  +----------------------------+-------------------------------------+   |
|                               |                                          |
|    +--------------------------+----------------------------------+      |
|    |           |              |              |              |    |      |
|    v           v              v              v              v    v      |
| +------+  +--------+  +----------+  +------+  +-----+  +----------+   |
| |system|  |agents  |  |evolution |  |memory|  |swarm|  |workspace |   |
| |      |  |        |  |          |  |      |  |     |  |          |   |
| +------+  +--------+  +----------+  +------+  +-----+  +----------+   |
|                                                                          |
+-------------------------------------------------------------------------+
```

## Component Map

| File | Domain | Commands |
|------|--------|----------|
| `registry.py` | - | `CommandRegistry`, command decorator |
| `system.py` | System | `/help`, `/status`, `/reset`, `/clear`, `/quit` |
| `agents.py` | Agents | `/spawn`, `/list-agents`, `/kill-agent` |
| `evolution.py` | Evolution | `/evolve`, `/specialize`, `/lineage` |
| `memory.py` | Memory | `/memory`, `/forget`, `/search` |
| `swarm.py` | Swarm | `/swarm`, `/hive`, `/mode` |
| `workspace.py` | Workspace | `/save`, `/load`, `/snapshot` |
| `misc.py` | Misc | `/history`, `/tokens`, `/config` |

## Command Interface

```python
@dataclass
class CommandResult:
    success: bool
    message: str
    data: Optional[Dict] = None

class Command(Protocol):
    """Command handler protocol."""

    name: str
    description: str
    aliases: List[str]

    async def execute(
        self,
        args: List[str],
        context: CommandContext
    ) -> CommandResult
```

## Command Registry

```python
from core.interface.commands import CommandRegistry, command

registry = CommandRegistry()

# Register via decorator
@command(name="help", aliases=["?", "h"], description="Show help")
async def help_command(args: List[str], context: CommandContext) -> CommandResult:
    # Implementation
    return CommandResult(success=True, message=help_text)

# Execute command
result = await registry.execute("/help", context)
```

## Available Commands

### System Commands
| Command | Aliases | Description |
|---------|---------|-------------|
| `/help` | `/?`, `/h` | Show available commands |
| `/status` | `/s` | Show system status |
| `/reset` | `/r` | Reset orchestrator state |
| `/clear` | `/cls` | Clear terminal |
| `/quit` | `/exit`, `/q` | Exit NEXUS |

### Agent Commands
| Command | Description |
|---------|-------------|
| `/spawn <type>` | Spawn new specialized agent |
| `/list-agents` | List active agents |
| `/kill-agent <id>` | Terminate agent |

### Evolution Commands
| Command | Description |
|---------|-------------|
| `/evolve` | Trigger evolution brainstorm |
| `/specialize <mission>` | Create specialized spinoff |
| `/lineage` | Show evolution tree |

### Memory Commands
| Command | Description |
|---------|-------------|
| `/memory` | Show memory status |
| `/search <query>` | Search memory |
| `/forget <key>` | Remove from memory |

### Swarm Commands
| Command | Description |
|---------|-------------|
| `/swarm <task>` | Execute with swarm |
| `/hive <task>` | Execute with HiveMind |
| `/mode` | Show current mode |

### Workspace Commands
| Command | Description |
|---------|-------------|
| `/save [name]` | Save session |
| `/load <name>` | Load session |
| `/snapshot` | Create workspace snapshot |

## Usage

```python
from core.interface.commands import CommandRegistry

# Create registry
registry = CommandRegistry()

# Check if input is command
if registry.is_command(user_input):
    result = await registry.execute(user_input, context)
    print(result.message)
```

## Dependencies

### Internal
- `core.orchestration_v7` - Orchestrator access
- `core.evolution` - Evolution commands
- `core.swarm` - Swarm commands
- `core.memory` - Memory commands

## Version History

- **V7.0** - Initial command system
- **V8.0** - HiveMind commands
- **V9.0** - Swarm commands
- **V12.4** - Enhanced registry, command aliases
