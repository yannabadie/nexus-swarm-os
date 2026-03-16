# NEXUS V7.5 HIVE MIND - API Reference

**Version**: 2.0 (HIVE MIND)
**Target Audience**: Developers
**Last Updated**: 2025-12-03

---

## 🐝 Module: `core.swarm.hybrid_swarm_engine`

Main engine for dynamic multi-agent collaboration.

### `class HybridSwarmEngine`

Orchestrates task analysis, mode selection, negotiation, and execution.

**Constructor**:
```python
HybridSwarmEngine(
    agent_pool: Optional[AgentPool] = None,
    model_router: Optional[ModelRouter] = None,
    config: Optional[Config] = None,
    invoke_agent: Optional[Callable] = None
)
```

**Methods**:

#### `process_task(...) -> SwarmResult`

Process a task through the full Hybrid Swarm pipeline.

**Parameters**:
- `task_input` (str): User's task description
- `blackboard` (Optional[Dict]): Shared state dictionary
- `force_mode` (Optional[CollaborationMode]): Force a specific mode
- `skip_negotiation` (bool): Skip negotiation phase

**Returns**:
- `SwarmResult`: Execution result with full trace

---

## 🧠 Module: `core.memory.auto_memory`

System for learning from task execution history.

### `class AutoMemory`

Manages persistence and retrieval of success/failure patterns.

**Methods**:

#### `record_success(...)`

Log a successful task execution.

**Parameters**:
- `task_type` (str): Type of task (e.g., "CODING")
- `task_description` (str): User input
- `swarm_mode` (str): Collaboration mode used
- `lead_agent` (str): Agent who led the task
- `duration_seconds` (float): Execution time
- `score` (float): Fitness score (0.0-1.0)

#### `get_recommendation(task_type: str) -> Dict`

Get recommended strategy based on history.

**Returns**:
- `Dict`: Recommendation with confidence score
  ```python
  {
      "suggested_mode": "LEAD_SUPPORT",
      "suggested_lead": "claude",
      "confidence": 0.85
  }
  ```

---

## 🏭 Module: `core.interface.repl` (Agent Factory)

Interactive shell handling Agent Spawning.

### `spawn_agent(role: str)`

Create a specialized agent that persists in `workspace/agents/`.

**Parameters**:
- `role` (str): Role description (e.g., "SQL Expert")

**Process**:
1. Uses `brainstorm_children_with_ais` to design the agent
2. Creates directory `workspace/agents/<role_slug>/`
3. Generates `BIRTH_CERTIFICATE.json` and `system_prompt.md`
4. Copies core files (preserving KERNEL.py)

---

## 🛡️ Module: `core.security.path_guardian`

Path validation for read/write operations.

**Zones**:
- `workspace/`: Read/Write
- `workspace/agents/`: Read/Write (New in V7.5)
- `GENERATION_ACTIVE/`: Read/Write (Evolution only)
- `core/`, `prompts/`: Read-Only

**Protected Files**:
- `KERNEL.py` (Immutable)
- `MISSION.md` (Immutable)
- `.env` (Sensitive)

---

## 🔧 Module: `core.utils.json_extractor`

Robust JSON extraction utility.

### `extract_json_safe(text: str) -> Tuple[Optional[Dict], Optional[str]]`

Extract JSON from text using multiple strategies.

**Strategies**:
1. `START_JSON` ... `END_JSON` markers
2. Markdown code blocks (```json)
3. Brute-force brace matching

---

## Reference

See `ROADMAP_HIVE_MIND.md` for architectural vision.