# Agents

## Synopsis
Centralized agent management system providing unified registry, spawning service, and DyLAN performance tracking. Replaces 41+ hardcoded if/else chains with O(1) lookups for agent routing and metadata.

## Component Map
| File | Purpose | Key Exports |
|------|---------|-------------|
| `unified_registry.py` | Centralized agent registry with O(1) lookups | `UnifiedAgentRegistry`, `AgentDescriptor`, `AgentProvider`, `AgentCapability`, `DriverProtocol`, `get_registry` |
| `service.py` | Agent spawning & management service layer | `AgentService`, `SpawnResult`, `AgentInfo`, `PoolStats` |
| `__init__.py` | Module exports | All above types |

## Key Interfaces

### UnifiedAgentRegistry
O(1) registry for all agents (builtins: Gemini, Claude; spawned agents).

**Core Methods:**
```python
# Registration
register(agent: AgentDescriptor)
unregister(agent_id: str) -> bool
register_driver(agent_id: str, driver: DriverProtocol)

# Lookups (O(1))
get(agent_id: str) -> Optional[AgentDescriptor]
get_driver(agent_id: str) -> Optional[DriverProtocol]
get_display_name(agent_id: str) -> str
get_alternate(agent_id: str) -> Optional[str]  # For BRAINSTORMING alternation

# Provider checks (replaces 'if "gemini" in agent_id')
is_gemini(agent_id: str) -> bool
is_claude(agent_id: str) -> bool
is_builtin(agent_id: str) -> bool

# Querying
list_available() -> List[AgentDescriptor]
list_builtins() -> List[AgentDescriptor]
list_spawned() -> List[AgentDescriptor]

# DyLAN routing
select_for_capability(capability: AgentCapability) -> Optional[AgentDescriptor]
update_dylan_score(agent_id: str, capability: str, score: float) -> bool
```

**Multi-Tenant Support (V10 PRISM):**
- V10+: Returns tenant-scoped registry via `ServiceFactory`
- Fallback: Global singleton for backward compatibility

### AgentService
Service layer for agent spawning and management.

**spawn(role, force) -> SpawnResult:**
V8.1.8 true dynamic spawning via EVOLUTION_BRAINSTORM.

Workflow:
1. Budget check (brainstorming cost: ~$0.50-2.00)
2. Domain detection from role (heuristics)
3. Brainstorm specialized prompt (Gemini+Claude collaboration)
4. Extract inference config (provider/model)
5. Validate no hallucinated tools
6. RedTeam validation (if enabled)
7. Save BIRTH_CERTIFICATE.json + system_prompt.md
8. Register as Agent-as-Tool

**list_agents() -> List[AgentInfo]:**
List all spawned agents in workspace/agents/.

**get_pool_stats() -> Optional[PoolStats]:**
DyLAN importance scores (if AGENT_METRICS=True).

## Dependencies
- **Internal**: `core.evolution.phases.brainstorm`, `core.prompts`, `core.governance.red_team`, `core.bootstrap`, `core.telemetry`
- **Internal**: `core.context`, `core.factory` (V10 PRISM)
- **External**: `pathlib`, `json`, `uuid`, `re`, `shutil`

## Integration Points

**Replaces:**
- AgentRegistry (hive_mind/)
- AgentPool (swarm/)
- SpawnedAgentLoader (bootstrap/)
- AgentInvoker (orchestration/)
- 41+ hardcoded `if "gemini" in agent_id.lower()` chains

**Used By:**
- `core.orchestration_v7` - Driver routing
- `core.interface.repl` - `/spawn`, `/agents`, `/metrics` commands
- `core.swarm` - Agent selection for collaboration
- `core.api.cerebro` - V10 multi-tenant management

## Version History
- V8.4.0: UnifiedAgentRegistry
- V8.1.8: True dynamic spawning via brainstorming
- V8.2.0c: RedTeam validation
- V9.1: AgentService extracted from repl.py
- V10 PRISM: Multi-tenant support
