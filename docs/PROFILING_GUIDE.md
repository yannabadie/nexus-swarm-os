# NEXUS Performance Profiling Guide

**Version**: V12.4 P4.1
**Purpose**: Identify hot paths for optimization (Rust migration, caching, etc.)

---

## Quick Start

```bash
# 1. Enable OpenTelemetry
export NEXUS_FF_OTEL_ENABLED=true

# 2. Start observability stack (Jaeger, Prometheus, Grafana)
docker compose --profile observability up -d

# 3. Run benchmark workload (100 tasks)
python scripts/benchmark_workload.py

# 4. Analyze traces
python scripts/analyze_traces.py

# 5. View in Jaeger UI
open http://localhost:16686
```

---

## Architecture

### OpenTelemetry Integration

NEXUS V12.4 includes full OTel instrumentation:

- **Traces**: Distributed traces across all components
- **Spans**: Function-level timing
- **Tags**: Contextual metadata (model, tokens, cost)
- **Export**: OTLP to Jaeger/Prometheus

### Observability Stack

The `docker-compose.yml` includes:

```yaml
services:
  jaeger:          # Trace visualization
  prometheus:      # Metrics aggregation
  grafana:         # Dashboards
  otel-collector:  # OTLP ingestion
```

**Access**:
- Jaeger: http://localhost:16686
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000

---

## Benchmark Workload

### Task Distribution

The `benchmark_workload.py` runs **100 tasks** across complexity levels:

| Complexity | Count | Examples |
|------------|-------|----------|
| TRIVIAL | 10 | "Hello", "Thanks" - Fast path, no LLM |
| SIMPLE | 20 | "Explain decorators" - Single agent |
| MODERATE | 30 | "Analyze codebase" - Swarm/HiveMind |
| COMPLEX | 30 | "Implement feature" - Multi-phase |
| EXPERT | 10 | "Design architecture" - Full pipeline |

### Execution

```python
# Orchestrator processes each task sequentially
orchestrator = OrchestratorV7()

for task in BENCHMARK_TASKS:
    result = orchestrator.process_turn(task)
    await asyncio.sleep(0.5)  # Rate limit
```

**Duration**: ~5-10 minutes (depending on task complexity)

---

## Trace Analysis

### Hot Path Criteria

The `analyze_traces.py` script identifies optimization candidates:

1. **Slow Average** (>100ms avg latency)
   - Blocking I/O
   - Slow algorithms
   - LLM calls without caching

2. **High Frequency** (>1000 calls)
   - Inner loops
   - Utility functions
   - Validation checks

3. **High Impact** (>10s total time)
   - Impact = avg_latency × call_count
   - Even fast functions matter if called often

### Output

```
🔥 HOT PATHS (Top 20 by Total Time)
Operation                                          Avg (ms)    Max (ms)    Count   Total (s)    Errors
---------------------------------------------------------------------------------------------------------
orchestrator.process_turn                           1250.00     5000.00      100      125.00         0
memory.retrieve                                       450.00     1200.00      300      135.00         0
driver.gemini.invoke                                  800.00     3000.00      150      120.00         0
driver.claude.invoke                                  750.00     2800.00      150      112.50         0

🎯 RUST MIGRATION CANDIDATES
  - memory.retrieve: slow avg (450ms), high frequency (300 calls)
  - bm25_scoring: high frequency (2000 calls), high impact (15.2s total)
  - embedding.encode: slow avg (200ms), high impact (12.5s total)
```

---

## Rust Migration Decision Tree

### Phase 1: RRF/BM25 Scoring (High Priority)

**Criteria Met**:
- [x] High frequency (>1000 calls)
- [x] Pure computation (no I/O)
- [x] Well-defined interface

**ROI**: ~10x speedup for lexical search

### Phase 2: RAG Chunking (Medium Priority)

**Criteria Met**:
- [x] CPU-bound (tokenization, parsing)
- [x] Frequent operation (every file indexed)

**ROI**: ~5x speedup for large codebases

### Phase 3: Embedding Batch (Medium Priority)

**Criteria Met**:
- [x] I/O-bound but parallelizable
- [x] Can leverage Rust async

**ROI**: ~3x speedup via async batching

### Phase 4: Validation/Guards (Lower Priority)

**Criteria Met**:
- [ ] Moderate frequency
- [ ] Simple logic

**ROI**: ~2x speedup, but low impact

---

## Profiling Best Practices

### Before Optimizing

1. **Measure First**
   - Don't optimize based on assumptions
   - Always profile with realistic workloads
   - Identify the actual bottleneck

2. **Set Baselines**
   - Record current metrics
   - Define success criteria
   - Compare before/after

3. **Isolate Variables**
   - Test one change at a time
   - Use same workload for comparisons
   - Control for LLM variance

### Optimization Order

1. **Algorithmic** (biggest gains)
   - O(n²) -> O(n log n)
   - Unnecessary work elimination

2. **Caching** (easiest wins)
   - Prompt caching (90% cost savings)
   - Response caching (100% latency savings)
   - Index caching

3. **Language-Level** (last resort)
   - Python -> Rust
   - Only for proven hot paths
   - Maintain Python interface

### Anti-Patterns

[NO] **Don't**:
- Optimize without profiling
- Rewrite everything in Rust
- Sacrifice readability for 1% gains
- Optimize rare code paths

[OK] **Do**:
- Profile realistic workloads
- Surgical optimizations (4 modules max)
- Maintain Python API compatibility
- Document trade-offs

---

## Next Steps

After identifying hot paths:

1. **Review** `todomig.md` for Rust migration guide
2. **Prioritize** based on ROI (impact × difficulty)
3. **Implement** surgically (one module at a time)
4. **Validate** with same benchmark workload
5. **Measure** improvement (before/after comparison)

**CRITICAL**: Always re-run profiling after changes to verify improvement.

---

## References

- `scripts/benchmark_workload.py` - Profiling workload
- `scripts/analyze_traces.py` - Trace analysis
- `todomig.md` - Rust migration guide
- `docker-compose.yml` - Observability stack
- Epic 4.3 (PHASE 4) - OTel implementation
