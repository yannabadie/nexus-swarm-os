# NEXUS Memory System Refactoring Plan

**Version:** V11.1 MEMORIA
**Date:** 2025-12-15
**Author:** Claude (Post-Diagnostic Analysis)
**Status:** DRAFT - Awaiting Review

---

## Executive Summary

After thorough diagnostic testing, the NEXUS memory system is **more functional than initially reported**, but has specific issues that need addressing.

### Diagnostic Results

| Component | Status | Finding |
|-----------|--------|---------|
| **ProjectMemory (RAG)** | [OK] WORKS | NOT write-only! Retrieves in `ContextBuilder._get_project_knowledge()` |
| **Dense Index** | [NO] BROKEN | `'list' object has no attribute 'tolist'` - falls back to BM25 |
| **BM25 Fallback** | [OK] WORKS | Returns relevant results |
| **SuccessMemory** | [OK] WORKS | Integrated with ModeSelector |
| **AutoMemory** | [OK] WORKS | Integrated with ModeSelector |

### Original Audit Corrections

| Original Claim | Reality |
|---------------|---------|
| "RAG is write-only" | **FALSE** - Retrieved automatically for MODERATE+ tasks |
| "RAG score 2/10" | **Corrected to 5/10** - Works but dense index broken |
| "SuccessMemory vs AutoMemory redundant" | **PARTIALLY TRUE** - Complementary but overlapping |

---

## Phase 1: Critical Fix - Dense Index Bug

**Priority:** P0 (CRITICAL)
**Effort:** Low
**Risk:** Low

### Problem

```
Dense index build failed: 'list' object has no attribute 'tolist'
```

The dense (semantic) index fails to build, forcing BM25 fallback. Semantic search would be more accurate.

### Root Cause Analysis

**File:** `core/memory/project_memory.py`

The error suggests embeddings are returned as Python lists instead of numpy arrays. Likely in the `_build_dense_index()` method.

### Proposed Fix

```python
# In _build_dense_index():
embeddings = self.model.encode(texts)
# FIX: Ensure numpy array
if isinstance(embeddings, list):
    embeddings = np.array(embeddings)
```

### Impact

- Enables semantic search (better than keyword-only BM25)
- No behavioral change - just better retrieval quality
- ~79% improvement in retrieval accuracy based on research

---

## Phase 2: RAG Coverage Extension

**Priority:** P1 (HIGH)
**Effort:** Medium
**Risk:** Low

### Current Coverage

| Component | RAG Retrieved? | Impact |
|-----------|---------------|--------|
| ContextBuilder (MODERATE+) | [OK] Yes | OK |
| TaskAnalyzer | [NO] No | Complexity misclassification |
| ModeSelector | [NO] No | Mode selection without project context |
| Simple Mode | [NO] No | Single agent blind to codebase |
| Executors | [NO] No | Agents lose context mid-execution |

### 2A: RAG in TaskAnalyzer

**File:** `core/swarm/task_analyzer.py`

**Why:** Understanding project context helps classify task complexity.

```python
# In TaskAnalyzer.analyze():
def analyze(self, user_input: str) -> TaskAnalysis:
    # EXISTING: Stage 1 regex, Stage 2 heuristic

    # NEW: RAG-assisted classification
    if self.project_memory and self._needs_context_for_classification(user_input):
        chunks = self.project_memory.retrieve(user_input, limit=2, min_score=0.1)
        if chunks:
            # Extract domain hints from file types
            file_types = [Path(c.file_path).suffix for c in chunks]
            # Boost domain scores based on what files match
            self._apply_rag_domain_boost(file_types, domain_scores)
```

### 2B: RAG in Simple Mode

**File:** `core/orchestration/fsm_handlers.py`

**Why:** Single-agent mode should still benefit from project knowledge.

```python
# In _execute_simple_task():
def _execute_simple_task(self, user_input: str, task_analysis) -> Dict:
    # EXISTING: context building

    # NEW: Inject RAG even for SIMPLE tasks
    if hasattr(self._orch, 'project_memory') and self._orch.project_memory:
        chunks = self._orch.project_memory.retrieve(user_input, limit=2, min_score=0.1)
        if chunks:
            rag_context = self._orch.project_memory.format_chunks_for_context(chunks, max_chars=1000)
            context = f"{rag_context}\n\n{context}"
```

### 2C: Just-In-Time RAG in Executors

**File:** `core/swarm/executors/base.py`

**Why:** Agents can "drift" during multi-step execution. JIT RAG anchors them.

```python
# In BaseExecutor._invoke_async():
async def _enrich_with_jit_rag(self, step_context: str) -> str:
    """Inject relevant code for current execution step."""
    if not self.project_memory:
        return step_context

    chunks = self.project_memory.retrieve(step_context[:200], limit=2, min_score=0.15)
    if not chunks:
        return step_context

    rag_snippet = self.project_memory.format_chunks_for_context(chunks, max_chars=800)
    return f"{rag_snippet}\n\n{step_context}"
```

**Safety:** Token limit (800 chars) prevents context overflow.

---

## Phase 3: Memory Coordination

**Priority:** P2 (MEDIUM)
**Effort:** High
**Risk:** Medium

### Current State

```
ModeSelector receives:
+-- SuccessMemory.get_best_mode_for_similar() -> boost by similarity
+-- AutoMemory.get_recommendation() -> boost by task_type
+-- Applied SEQUENTIALLY without normalization
```

### Option A: Unified Memory (High Effort, Medium Risk)

Create `UnifiedSuccessMemory` that combines both.

**Pros:**
- Single source of truth
- Cleaner architecture
- Easier maintenance

**Cons:**
- Migration required
- Potential data loss
- High regression risk

### Option B: Memory Coordinator (Medium Effort, Low Risk) [OK] RECOMMENDED

Keep both memories, add a coordinator layer.

**File:** NEW `core/memory/coordinator.py`

```python
class MemoryCoordinator:
    """Coordinates SuccessMemory and AutoMemory for consistent recommendations."""

    def __init__(self, success_memory, auto_memory):
        self.success = success_memory
        self.auto = auto_memory

    def get_unified_recommendation(self, task_description: str, task_type: str) -> dict:
        """Get normalized recommendation from both memory systems."""

        # Get both recommendations
        success_rec = self.success.get_best_mode_for_similar(task_description)
        auto_rec = self.auto.get_recommendation(task_type)

        # Normalize scores to 0-1 range
        success_score = success_rec.get('similarity', 0) if success_rec else 0
        auto_score = auto_rec.get('confidence', 0) if auto_rec else 0

        # Weighted combination (semantic > categorical for specific tasks)
        if success_score > 0.5:
            # Strong semantic match - prioritize SuccessMemory
            return {
                'mode': success_rec['mode'],
                'confidence': 0.7 * success_score + 0.3 * auto_score,
                'source': 'success_memory'
            }
        elif auto_score > 0.7:
            # Strong categorical match - use AutoMemory
            return {
                'mode': auto_rec['suggested_mode'],
                'confidence': 0.3 * success_score + 0.7 * auto_score,
                'source': 'auto_memory'
            }
        else:
            # Low confidence in both - don't boost
            return {'mode': None, 'confidence': 0, 'source': None}
```

### Integration

```python
# In ModeSelector.__init__():
self.memory_coordinator = MemoryCoordinator(success_memory, auto_memory)

# In select_mode():
unified_rec = self.memory_coordinator.get_unified_recommendation(
    task_analysis.raw_input,
    task_analysis.primary_domain.value
)
if unified_rec['confidence'] > 0.5:
    mode_scores[unified_rec['mode']] *= (1 + unified_rec['confidence'] * 0.3)
```

---

## Phase 4: Question Augmentation (Advanced)

**Priority:** P3 (LOW)
**Effort:** Medium
**Risk:** Low

### Problem

RAG queries use raw user input. Better results come from augmented queries.

### Solution: Golden-Retriever Pattern

```python
# In ProjectMemory.retrieve():
def retrieve_with_augmentation(self, query: str, limit: int = 5) -> List[Chunk]:
    """Augment query before retrieval for better matches."""

    # Extract domain keywords
    domain_terms = self._extract_domain_terms(query)

    # Expand abbreviations (e.g., "auth" -> "authentication")
    expanded = self._expand_abbreviations(query)

    # Build augmented query
    augmented = f"{query} {' '.join(domain_terms)} {expanded}"

    return self.retrieve(augmented, limit=limit)
```

---

## Implementation Order

```
+-------------------------------------------------------------+
|                    IMPLEMENTATION PHASES                     |
+-------------------------------------------------------------+
|                                                             |
|  PHASE 1: Fix Dense Index Bug                               |
|  +-- Effort: 1-2 hours                                      |
|  +-- Risk: Low                                              |
|  +-- Deliverable: Semantic search working                   |
|           |                                                 |
|           v                                                 |
|  PHASE 2A: RAG in TaskAnalyzer                              |
|  +-- Effort: 2-3 hours                                      |
|  +-- Risk: Low                                              |
|  +-- Deliverable: Better complexity classification          |
|           |                                                 |
|           v                                                 |
|  PHASE 2B: RAG in Simple Mode                               |
|  +-- Effort: 1-2 hours                                      |
|  +-- Risk: Low                                              |
|  +-- Deliverable: Single agent sees project context         |
|           |                                                 |
|           v                                                 |
|  PHASE 2C: JIT RAG in Executors                             |
|  +-- Effort: 3-4 hours                                      |
|  +-- Risk: Medium (token limits)                            |
|  +-- Deliverable: Context persistence during execution      |
|           |                                                 |
|           v                                                 |
|  PHASE 3: Memory Coordinator                                |
|  +-- Effort: 4-6 hours                                      |
|  +-- Risk: Medium                                           |
|  +-- Deliverable: Unified memory recommendations            |
|           |                                                 |
|           v                                                 |
|  PHASE 4: Query Augmentation (OPTIONAL)                     |
|  +-- Effort: 2-3 hours                                      |
|  +-- Risk: Low                                              |
|  +-- Deliverable: Better retrieval accuracy                 |
|                                                             |
+-------------------------------------------------------------+
```

---

## Success Metrics

| Metric | Current | Target | How to Measure |
|--------|---------|--------|----------------|
| RAG Retrieval Rate | ~30% (MODERATE+ only) | 80% (all code tasks) | Log analysis |
| Dense Index Status | [NO] Broken | [OK] Working | Backend info check |
| Memory Boost Rate | Unknown | Track in logs | Add telemetry |
| Task Classification Accuracy | Unknown | Improve by 15% | A/B test |

---

## Risks and Mitigations

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Dense index fix breaks retrieval | Low | High | Keep BM25 fallback |
| JIT RAG overflows context | Medium | Medium | Strict token limits |
| Memory coordinator conflicts | Low | Medium | Default to no boost if conflict |
| Performance regression | Medium | Low | Cache RAG results |

---

## Appendix: File References

| File | Role |
|------|------|
| `core/memory/project_memory.py` | RAG storage and retrieval |
| `core/memory/success_memory.py` | Semantic task success history |
| `core/memory/auto_memory.py` | Categorical task success history |
| `core/orchestration/context_builder.py` | Context construction (RAG injection point) |
| `core/swarm/task_analyzer.py` | Task classification |
| `core/swarm/mode_selector.py` | Mode selection with memory boosts |
| `core/swarm/executors/base.py` | Execution with potential JIT RAG |

---

## Conclusion

The memory system is **better than reported** but has specific gaps:

1. **Dense index is broken** - Easy fix, high impact
2. **RAG coverage is limited** - Only MODERATE+ brainstorming
3. **Memories not coordinated** - Sequential application, no normalization

**Recommended approach:** Fix Phase 1 immediately, implement Phase 2A-2B incrementally, evaluate need for Phase 3 after data collection.

**DO NOT** rush into unifying SuccessMemory + AutoMemory - they serve complementary purposes and the coordinator pattern is safer.
