# Strategic Prompt Caching Implementation Plan

**Priority**: P0 (Immediate)
**Expected Impact**: 41-90% cost reduction (ArXiv validated)
**Date**: 2026-02-17

---

## Problem Analysis

### Current State (Inefficient)
```python
# HiveMind Phase 1 (phase_analysis.py)
ANALYSIS_PROMPT = """You are analyzing a task for NEXUS Hive Mind.

TASK: {task}

Analyze this task INDEPENDENTLY...
[500+ tokens of static instructions]
"""

# All sent as user message:
prompt = ANALYSIS_PROMPT.format(task=task)
response = await driver.send_message_async(prompt)  # NO CACHING
```

**Problems:**
1. Static instructions (500+ tokens) sent on EVERY request
2. No separation between static (cacheable) and dynamic (task) content
3. Legacy `send_message_async()` API doesn't support system prompts
4. SDK drivers already support caching but aren't being used optimally

---

## Solution Architecture

### Optimal Prompt Structure (ArXiv 2601.06007)
```
[Static System Prompt - CACHED]      <- 500+ tokens (cached after first request)
[Dynamic User Prompt - NOT CACHED]   <- ~50 tokens (task description)
```

**Savings:**
- **Without caching**: 550 tokens/request
- **With caching**: 50 tokens/request (cached tokens cost 10% of regular)
- **Effective reduction**: ~90% cost reduction

### Implementation Pattern

**BEFORE (Inefficient):**
```python
# phase_analysis.py
ANALYSIS_PROMPT = """You are analyzing a task...
TASK: {task}
[instructions...]
"""

prompt = ANALYSIS_PROMPT.format(task=task)
response = await driver.send_message_async(prompt)
```

**AFTER (Optimal):**
```python
# phase_analysis.py
ANALYSIS_SYSTEM_PROMPT = """You are an agent in NEXUS HiveMind Phase 1: ANALYSIS.

Your role is to analyze tasks INDEPENDENTLY without assuming what the other agent thinks.

Respond in this EXACT JSON format:
{
    "task_understanding": "Your understanding of what needs to be done",
    "complexity_assessment": "TRIVIAL | MODERATE | COMPLEX | EXPERT",
    "proposed_approach": "Your proposed strategy to solve this",
    "required_capabilities": ["capability1", "capability2", ...],
    "potential_risks": ["risk1", "risk2", ...],
    "confidence": 0.0 to 1.0,
    "reasoning": "Why you chose this approach"
}

Consider:
- What tools/skills are needed?
- What could go wrong?
- How complex is this really?
- What's the best strategy?
"""

# Dynamic user prompt (just the task)
prompt = f"TASK: {task}"

# Principles if available
if principles_context:
    prompt += f"\n\nRELEVANT PRINCIPLES:\n{principles_context}"

# SDK driver handles caching automatically
response = await driver.invoke(
    prompt,
    system_prompt=ANALYSIS_SYSTEM_PROMPT,  # <- CACHED by SDK
)
```

---

## Files to Modify

### Phase 1: HiveMind Phases (7 files)

**Template for all phases:**

| File | Static Prompt (Cached) | Dynamic Prompt |
|------|------------------------|----------------|
| `phase_analysis.py` | Role + JSON schema + instructions (500+ tokens) | Task + principles (50-200 tokens) |
| `phase_debate.py` | Debate rules + format + protocols (600+ tokens) | Disagreements + analyses (100-300 tokens) |
| `phase_architecture.py` | Architecture guidelines + format (700+ tokens) | Task + analysis results (100-400 tokens) |
| `phase_execution.py` | Execution protocol + error handling (500+ tokens) | Step description + context (50-200 tokens) |
| `phase_diagnosis.py` | Diagnosis framework + questions (600+ tokens) | Error + stack trace + context (100-500 tokens) |
| `phase_retry.py` | Retry decision framework (400+ tokens) | Failure history + context (100-300 tokens) |
| `phase_consolidation.py` | Consolidation criteria + format (500+ tokens) | Session results + metrics (100-400 tokens) |

**Total Cacheable**: ~4000 tokens across 7 phases
**Expected Savings**: 70-85% on multi-phase HiveMind tasks

---

### Phase 2: Update Driver Invocation

**Current (Legacy):**
```python
# phase_analysis.py line 352, 391
response = await self.gemini.send_message_async(prompt, session_uuid=session_uuid)
response = await self.claude.send_message_async(prompt, session_uuid=session_uuid)
```

**New (SDK Protocol):**
```python
# Use invoke() method from BaseAsyncDriver protocol
response = await self.gemini.invoke(
    prompt,
    session_id=session_uuid,
    system_prompt=ANALYSIS_SYSTEM_PROMPT,  # Static, cached
)

response = await self.claude.invoke(
    prompt,
    session_id=session_uuid,
    system_prompt=ANALYSIS_SYSTEM_PROMPT,  # Static, cached
)
```

**Note**: Need to update response parsing since `invoke()` returns `DriverResponse`, not raw string.

---

## Implementation Steps

### Step 1: Create Prompt Constants Module (NEW)
```python
# core/hive_mind/prompts.py (NEW FILE)
"""
HiveMind Static Prompts for Prompt Caching.

All system prompts are defined here as constants to enable SDK-level caching.
Dynamic content (task, context, results) is passed as user prompts.

Author: Claude (V12.4.1 - ArXiv 2601.06007)
Date: 2026-02-17
"""

# Phase 1: Analysis
ANALYSIS_SYSTEM_PROMPT = """..."""

# Phase 2: Debate
DEBATE_SYSTEM_PROMPT = """..."""

# Phase 3: Architecture
ARCHITECTURE_SYSTEM_PROMPT = """..."""

# ... (all 7 phases)
```

### Step 2: Update Phase 1 (Analysis) - REFERENCE IMPLEMENTATION
```python
# phase_analysis.py

from ..prompts import ANALYSIS_SYSTEM_PROMPT

class IndependentAnalysisPhase:
    async def _analyze_with_gemini(self, task: str, session_uuid: Optional[str] = None):
        # Build dynamic user prompt
        prompt = f"TASK: {task}"

        # Add principles if available
        if self._principles_context:
            prompt += f"\n\nRELEVANT PRINCIPLES:\n{self._principles_context}"

        # Invoke with system prompt (cached automatically)
        response = await self.gemini.invoke(
            prompt,
            session_id=session_uuid,
            system_prompt=ANALYSIS_SYSTEM_PROMPT,  # <- CACHED
            agent_name="gemini",
            agent_id="gemini",
        )

        # Parse DriverResponse
        if not response.is_success:
            raise RuntimeError(f"Gemini analysis failed: {response.error_message}")

        # Parse JSON from response.content
        analysis_data = self._parse_analysis_response(response.content, "gemini")

        # Record actual token usage
        self.cost_estimator.record_tokens(
            "independent_analysis_gemini",
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )

        return IndependentAnalysis(agent_id="gemini", **analysis_data)
```

### Step 3: Replicate Pattern for All 7 Phases
- Extract static instructions -> `prompts.py`
- Update `_analyze_with_gemini()` and `_analyze_with_claude()` methods
- Change `send_message_async()` -> `invoke(system_prompt=...)`
- Update response parsing (`DriverResponse.content` instead of raw string)
- Update cost tracking (use actual `input_tokens`/`output_tokens`)

### Step 4: Verify SDK Caching Metrics
```python
# Anthropic SDK driver already tracks cache metrics (anthropic_sdk_driver.py:601-604)
cache_creation = getattr(usage, "cache_creation_input_tokens", 0)
cache_read = getattr(usage, "cache_read_input_tokens", 0)

# Add logging to verify caching is working:
logger.info(
    f"Phase {phase_name} - Cache stats: "
    f"creation={cache_creation}, read={cache_read}, "
    f"savings={(cache_read * 0.9) if cache_read else 0:.0f} tokens"
)
```

---

## Testing & Validation

### Test 1: Cache Hit Rate
```python
# tests/test_prompt_caching.py

async def test_phase1_analysis_cache_hit():
    """Verify Phase 1 system prompt is cached on 2nd request."""
    phase = IndependentAnalysisPhase(...)

    # First request: cache MISS (creation)
    result1 = await phase.execute("Analyze this code")
    assert result1.gemini_analysis.cache_creation_tokens > 0
    assert result1.gemini_analysis.cache_read_tokens == 0

    # Second request: cache HIT (read)
    result2 = await phase.execute("Analyze this other code")
    assert result2.gemini_analysis.cache_creation_tokens == 0
    assert result2.gemini_analysis.cache_read_tokens > 400  # ~500 token prompt
```

### Test 2: Cost Reduction
```python
async def test_hivemind_cost_reduction_with_caching():
    """Measure cost reduction on 100 HiveMind tasks."""
    tasks = generate_test_tasks(100)

    # Run with caching DISABLED
    total_cost_no_cache = run_hivemind_tasks(tasks, enable_caching=False)

    # Run with caching ENABLED
    total_cost_with_cache = run_hivemind_tasks(tasks, enable_caching=True)

    # Calculate savings
    savings = (total_cost_no_cache - total_cost_with_cache) / total_cost_no_cache

    assert savings > 0.50, f"Expected >50% cost reduction, got {savings:.0%}"
    print(f"Cost reduction: {savings:.0%}")
```

### Test 3: Latency Improvement
```python
async def test_ttft_improvement_with_caching():
    """Measure time-to-first-token improvement."""
    # First request: no cache
    start = time.monotonic()
    result1 = await phase.execute("Task 1")
    ttft_no_cache = (time.monotonic() - start) * 1000

    # Second request: cache hit
    start = time.monotonic()
    result2 = await phase.execute("Task 2")
    ttft_with_cache = (time.monotonic() - start) * 1000

    improvement = (ttft_no_cache - ttft_with_cache) / ttft_no_cache

    assert improvement > 0.10, f"Expected >10% TTFT improvement, got {improvement:.0%}"
```

---

## Expected Results

### Metrics (Post-Implementation)

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| **Phase 1 cost** | $0.10/task | $0.02/task | -80% |
| **7-phase HiveMind cost** | $0.50/task | $0.15/task | -70% |
| **Cache hit rate** | 0% | 60-80% | +60-80pp |
| **TTFT (average)** | 2.0s | 1.4s | -30% |
| **Input tokens (cached)** | 4000/task | 400/task | -90% |

### ArXiv Validation
- **Paper**: 2601.06007 - "Don't Break the Cache"
- **Provider**: Anthropic Claude Sonnet 4.5
- **Measured Savings**: 78-79% cost reduction
- **NEXUS Expected**: 70-85% (multi-phase overhead)

---

## Rollout Plan

### Week 1 (Feb 17-21)
- Day 1: Create `prompts.py` with all 7 phase system prompts
- Day 2: Update Phase 1 (analysis) - reference implementation
- Day 3: Update Phases 2-4 (debate, architecture, execution)
- Day 4: Update Phases 5-7 (diagnosis, retry, consolidation)
- Day 5: Write tests + validation benchmarks

### Week 2 (Feb 24-28)
- Day 1: Run 100-task benchmark, measure cost reduction
- Day 2: Fix any cache invalidation issues
- Day 3: Add cache metrics to telemetry (OTel spans)
- Day 4: Document findings + update CHANGELOG
- Day 5: Deploy to production (feature flag: `NEXUS_FF_PROMPT_CACHING`)

---

## Risks & Mitigations

### Risk 1: Cache Invalidation Due to Dynamic Content
**Symptom**: Cache hit rate <30% (expected 60-80%)
**Cause**: Principles or other dynamic content mixed into system prompt
**Mitigation**: Keep system prompts 100% static, ALL dynamic content in user prompt

### Risk 2: Legacy Driver Compatibility
**Symptom**: `send_message_async()` doesn't exist on new SDK drivers
**Cause**: HiveMind phases use legacy API
**Mitigation**: Use `invoke()` method from `BaseAsyncDriver` protocol (already implemented)

### Risk 3: Response Format Changes
**Symptom**: JSON parsing fails after switching to `invoke()`
**Cause**: `invoke()` returns `DriverResponse.content`, not raw string
**Mitigation**: Extract `response.content` and parse as before

---

## Success Criteria

[OK] **P0 (Must Have):**
1. All 7 HiveMind phases use split system/user prompts
2. Cache hit rate >60% on repeated tasks
3. Cost reduction >50% on 100-task benchmark
4. No regressions in test suite (2500+ tests pass)

[OK] **P1 (Should Have):**
5. TTFT improvement >15%
6. Cache metrics in OTel spans
7. Feature flag for gradual rollout

[OK] **P2 (Nice to Have):**
8. Swarm Engine tool definitions cached
9. Orchestrator system prompts cached
10. Automatic cache invalidation on prompt changes

---

**Implementation Start**: Now (Feb 17, 2026)
**Target Completion**: Feb 28, 2026 (2 weeks)
**Owner**: Claude Opus 4.6 (with Gemini review)
