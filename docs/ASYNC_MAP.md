# NEXUS V8.0 - Async/Sync Function Map

**Purpose**: Quick reference for async vs sync functions to avoid mixing issues.
**Last Updated**: 2025-12-08
**Version**: 1.0

---

## CRITICAL ISSUE: Sync-in-Async Problem

The HiveMind pipeline is async, but drivers are sync. This causes:
- Event loop blocking during LLM calls
- PARALLEL mode runs sequentially
- No true concurrency

See ROADMAP V8.1.6 for fix plan.

---

## 1. ASYNC Functions

### HiveMind Orchestrator

| Function | File | Line | Calls |
|----------|------|------|-------|
| `TrueHiveMind.process_task()` | orchestrator.py | 235 | All phases |

### HiveMind Phases

| Function | File | Line | Notes |
|----------|------|------|-------|
| `PhaseAnalysis.execute()` | phase_analysis.py | 108 | Entry point |
| `PhaseAnalysis._analyze_with_gemini()` | phase_analysis.py | 187 | Calls SYNC driver! |
| `PhaseAnalysis._analyze_with_claude()` | phase_analysis.py | 211 | Calls SYNC driver! |
| `PhaseDebate.execute()` | phase_debate.py | 175 | Entry point |
| `PhaseDebate._get_argument()` | phase_debate.py | 351 | |
| `PhaseDebate._check_consensus()` | phase_debate.py | 453 | |
| `PhaseDebate._force_vote()` | phase_debate.py | 497 | |
| `PhaseArchitecture.execute()` | phase_architecture.py | 151 | Entry point |
| `PhaseArchitecture._generate_architecture()` | phase_architecture.py | 262 | |
| `PhaseArchitecture._spawn_agents()` | phase_architecture.py | 417 | |
| `PhaseExecution.execute()` | phase_execution.py | 135 | Entry point |
| `PhaseExecution._execute_step()` | phase_execution.py | 268 | |
| `PhaseExecution._verify_artifacts()` | phase_execution.py | 492 | |
| `PhaseDiagnosis.execute()` | phase_diagnosis.py | 151 | Entry point |
| `PhaseDiagnosis._diagnose_with_gemini()` | phase_diagnosis.py | 255 | Calls SYNC driver! |
| `PhaseDiagnosis._diagnose_with_claude()` | phase_diagnosis.py | 266 | Calls SYNC driver! |
| `PhaseDiagnosis._synthesize_diagnoses()` | phase_diagnosis.py | 277 | |
| `PhaseConsolidation.execute()` | phase_consolidation.py | 161 | Entry point |
| `PhaseConsolidation._reflect_with_gemini()` | phase_consolidation.py | 298 | Calls SYNC driver! |
| `PhaseConsolidation._reflect_with_claude()` | phase_consolidation.py | 309 | Calls SYNC driver! |
| `PhaseConsolidation._debate_consolidation()` | phase_consolidation.py | 320 | |

### User Interaction

| Function | File | Line | Notes |
|----------|------|------|-------|
| `UserInteractionHandler.request_breakpoint()` | user_interaction.py | 152 | Async user prompt |

---

## 2. SYNC Functions (BLOCKING)

### LLM Drivers (CRITICAL - Block Event Loop)

| Function | File | Line | Impact |
|----------|------|------|--------|
| `GeminiDriverV7.invoke()` | gemini_driver_v7.py | 122 | **BLOCKS 10-60s** |
| `GeminiDriverV7.invoke_stream()` | gemini_driver_v7.py | 149 | **BLOCKS** |
| `GeminiDriverV7._invoke_subprocess()` | gemini_driver_v7.py | 178 | **BLOCKS** |
| `ClaudeDriverHybrid.invoke()` | claude_driver_hybrid.py | 97 | **BLOCKS 10-60s** |
| `ClaudeDriverHybrid.invoke_stream()` | claude_driver_hybrid.py | 231 | **BLOCKS** |
| `ClaudeDriverHybrid.invoke_with_retry()` | claude_driver_hybrid.py | 444 | **BLOCKS** |

### Swarm Engine (All SYNC)

| Function | File | Line | Notes |
|----------|------|------|-------|
| `HybridSwarmEngine.process_task()` | hybrid_swarm_engine.py | 193 | Main entry (SYNC) |
| `HybridSwarmEngine.execute_turn()` | hybrid_swarm_engine.py | ~300 | |
| `ModeSelector.select_mode()` | mode_selector.py | ~200 | |
| `TaskAnalyzer.analyze()` | task_analyzer.py | ~250 | |

### Memory (All SYNC)

| Function | File | Line | Notes |
|----------|------|------|-------|
| `SuccessMemory.record_success()` | success_memory.py | 164 | SYNC write |
| `SuccessMemory.get_best_mode_for_similar()` | success_memory.py | ~200 | SYNC read |
| `ProjectMemory.retrieve()` | project_memory.py | ~150 | SYNC RAG |

---

## 3. Call Graph: Async -> Sync Problem

```
ASYNC CONTEXT
|
+-- TrueHiveMind.process_task() [ASYNC]
    |
    +-- PhaseAnalysis.execute() [ASYNC]
    |   |
    |   +-- _analyze_with_gemini() [ASYNC]
    |   |   +-- self.gemini.invoke() [SYNC] <- BLOCKS EVENT LOOP!
    |   |
    |   +-- _analyze_with_claude() [ASYNC]
    |       +-- self.claude.invoke() [SYNC] <- BLOCKS EVENT LOOP!
    |
    +-- PhaseDebate.execute() [ASYNC]
    |   +-- ... same pattern ...
    |
    +-- ... other phases ...
```

---

## 4. Impact Analysis

### Current Behavior (Broken)

```python
# In PhaseAnalysis._analyze_with_gemini():
async def _analyze_with_gemini(self, prompt: str):
    result = self.gemini.invoke(prompt)  # SYNC call in async context
    # ↑ This BLOCKS the entire event loop for 10-60 seconds
    return result
```

### Expected Behavior (After V8.1.6)

```python
async def _analyze_with_gemini(self, prompt: str):
    result = await self.gemini.invoke_async(prompt)  # Non-blocking
    return result
```

### PARALLEL Mode Impact

| Mode | Current | After V8.1.6 |
|------|---------|--------------|
| PARALLEL | t1 + t2 (sequential) | max(t1, t2) (true parallel) |
| SEQUENTIAL | t1 + t2 | t1 + t2 (no change) |
| LEAD_SUPPORT | Mostly sequential | Can overlap |

**Estimated speedup in PARALLEL**: 40-50%

---

## 5. Safe Patterns

### DO: Use asyncio.gather with async functions

```python
# CORRECT (if invoke_async existed)
results = await asyncio.gather(
    gemini.invoke_async(prompt),
    claude.invoke_async(prompt)
)
```

### DON'T: Call sync functions in async context without executor

```python
# WRONG - blocks event loop
async def my_async_func():
    result = sync_function()  # BAD!
```

### DO: Use run_in_executor for sync functions

```python
# CORRECT - offloads to thread pool
async def my_async_func():
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, sync_function)
```

---

## 6. Migration Priority

| Module | Async Functions | Sync Calls | Priority |
|--------|-----------------|------------|----------|
| phase_analysis.py | 3 | 2 drivers | P1 |
| phase_debate.py | 4 | 2+ drivers | P1 |
| phase_diagnosis.py | 4 | 2 drivers | P1 |
| phase_consolidation.py | 4 | 2 drivers | P1 |
| phase_execution.py | 3 | Tools (OK) | P2 |
| phase_architecture.py | 3 | Spawner | P2 |

---

## 7. Quick Reference

### Is it Async?

| Class/Function | Async? |
|----------------|--------|
| TrueHiveMind.process_task | YES |
| HybridSwarmEngine.process_task | NO |
| PhaseXxx.execute | YES |
| GeminiDriverV7.invoke | NO |
| ClaudeDriverHybrid.invoke | NO |
| SuccessMemory.record_success | NO |
| ModeSelector.select_mode | NO |

### Can I await it?

```python
await truehive.process_task(task)     # YES
await swarm.process_task(task)        # NO - not async!
await phase.execute(task)             # YES
await gemini.invoke(prompt)           # NO - TypeError!
await claude.invoke(prompt)           # NO - TypeError!
```

---

*This map is essential for understanding the async/sync boundaries in NEXUS. Update when adding async functions.*
