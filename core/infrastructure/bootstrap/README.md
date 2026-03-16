# Bootstrap

## Synopsis
Project deployment and agent loading infrastructure. Generates NEXUS.md when deployed to new projects, discovers spawned agents, and provides service layer for bootstrap/spinoff operations.

## Component Map
| File | Purpose | Key Exports |
|------|---------|-------------|
| `auto_bootstrap.py` | Auto-generate NEXUS.md for new projects | `AutoBootstrap`, `ProjectAnalysis` |
| `agent_loader.py` | Discover spawned agents from workspace/agents/ | `SpawnedAgentLoader`, `SpawnedAgentConfig`, `discover_and_register_spawned_agents` |
| `service.py` | Service layer for bootstrap/spinoff | `BootstrapService`, `SpinoffService` |
| `__init__.py` | Module exports | All above |

## Key Interfaces

### AutoBootstrap
Auto-generates NEXUS.md when deployed to a new project.

**Workflow:**
```python
bootstrap = AutoBootstrap(project_path)
analysis = bootstrap.analyze()  # Scan project structure
content = bootstrap.generate_nexus_md(analysis)
path = bootstrap.save(content)
```

**ProjectAnalysis Fields:**
- `languages`: Detected languages (Python, JS, etc.)
- `frameworks`: Detected frameworks (FastAPI, React, etc.)
- `databases`: Detected databases (PostgreSQL, MongoDB, etc.)
- `tools`: Detected tools (Docker, pytest, etc.)
- `key_files`: Important files (README, package.json, etc.)
- `commands`: Discovered commands (npm start, pytest, etc.)
- `indentation`, `naming_style`: Code conventions
- `has_tests`, `has_docs`, `has_ci`: Booleans

**Detection Patterns:**
- Languages: File extensions, shebang lines
- Frameworks: Import patterns, config files
- Databases: Connection strings, config files
- Tools: Presence of Docker, Makefile, pyproject.toml, etc.

### SpawnedAgentLoader
Discovers and loads spawned agents from workspace/agents/.

**Usage:**
```python
loader = SpawnedAgentLoader(workspace_path)
agents = loader.discover_spawned_agents()  # Returns List[AgentProfile]

config = loader.load_agent_config("security_expert")
prompt = loader.load_system_prompt("security_expert")
workspace = loader.get_agent_workspace("security_expert")
```

**SpawnedAgentConfig:**
- `agent_id`: URL-safe identifier
- `role`: Original role string
- `created_at`: ISO timestamp
- `parent`: Parent agent/system ID
- `mission`: Agent's mission statement
- `domains`: Detected domain list
- `tools_priority`: Preferred tools
- `workspace_path`: Agent's workspace directory
- `system_prompt_path`: Path to system_prompt.md
- `uuid`: Unique identifier
- `inference`: Provider/model configuration

**BIRTH_CERTIFICATE.json:**
Spawned agents have a birth certificate containing metadata:
```json
{
  "agent_id": "security_expert",
  "uuid": "abc-123",
  "role": "Security Expert",
  "created_at": "2025-12-17T10:30:42.123Z",
  "parent": "NEXUS_V8.1.8_HIVE_MIND",
  "generation_method": "brainstorm",
  "inference": {
    "provider": "claude",
    "model": "claude-sonnet-4-6-20250929",
    "reasoning": "Security analysis requires deep reasoning"
  },
  "specialization": {
    "mission": "Specialized agent for: Security Expert",
    "domains": ["security", "analysis"],
    "tools_priority": []
  }
}
```

### BootstrapService (V9.1)
Service layer for bootstrap operations.

```python
service = BootstrapService(console, interaction)
result = service.bootstrap(project_path)  # ServiceResult
```

**Features:**
- Interactive confirmation for overwrite
- Error handling with ServiceResult
- Console output integration

### SpinoffService (V9.1)
Service layer for specialization/spinoff operations.

```python
service = SpinoffService(orchestrator, console, workspace_path, nexus_root)
result = service.specialize(mission="SQL Expert for PostgreSQL")
```

**Features:**
- Brainstorm spinoff via EVOLUTION_BRAINSTORM
- Mutation generation for specialized children

## Dependencies
- **Internal**: `core.evolution.phases.brainstorm`, `core.telemetry.service`, `core.interaction`
- **External**: `pathlib`, `json`, `re`, `glob`

## Integration Points

**Used By:**
- `core.agents.service` - Agent spawning discovers and registers
- `core.interface.repl` - `/bootstrap`, `/specialize` commands
- `core.orchestration_v7` - Startup agent discovery

**Deploy Flow:**
```
1. Clone NEXUS into project
2. Run nexus7.py
3. AutoBootstrap detects missing NEXUS.md
4. Generates NEXUS.md based on project analysis
5. SpawnedAgentLoader discovers existing agents (if any)
6. User: "/specialize SQL Expert"
7. SpinoffService creates specialized variant
```

## V12.4 COGNITIVE BOOST Additions

| File | Purpose | Key Exports |
|------|---------|-------------|
| `startup_analytics.py` | Tracks bootstrap and startup performance including component initialization times, startup ordering, failure detection and profiling, and total boot time aggregation | `get_startup_analytics`, `StartupAnalytics` |

## Version History
- V7.5: SpawnedAgentLoader
- V8.1: AutoBootstrap
- V9.1: BootstrapService, SpinoffService extracted to service layer
- V12.4: Startup analytics for boot performance tracking
