# NEXUS V12.4.1+ Optimization Roadmap

**Date**: 2026-02-17
**Strategy**: Python optimizations first (P0), then Rust migration (surgical ports)
**Timeline**: Feb 17 - May 31 (3.5 months)

---

## Phase A: Python Optimizations (P0-P2) - Feb 17-28

**Goal**: 41-90% cost reduction via prompt caching + observability improvements

### [OK] Week 1: Prompt Caching Infrastructure (Feb 17-21)

| Day | Task | Status | Files |
|-----|------|--------|-------|
| Mon | Meta-analysis complete | [OK] Done | `docs/meta_analysis_v12.4.1.md` |
| Mon | Create static prompts module | [OK] Done | `core/hive_mind/prompts.py` |
| Mon | Update Phase 1 (Analysis) | [OK] Done | `phase_analysis.py` |
| Tue | Update Phase 2 (Debate) | ⏳ Next | `phase_debate.py` |
| Tue | Update Phase 3 (Architecture) | 📋 Pending | `phase_architecture.py` |
| Wed | Update Phase 4 (Execution) | 📋 Pending | `phase_execution.py` |
| Thu | Update Phase 5 (Diagnosis) | 📋 Pending | `phase_diagnosis.py` |
| Thu | Update Phase 6 (Retry) | 📋 Pending | `phase_retry.py` |
| Fri | Update Phase 7 (Consolidation) | 📋 Pending | `phase_consolidation.py` |

**Expected Impact (Week 1):**
- [OK] Infrastructure: 70-85% cost reduction enabled
- [OK] Phase 1: Reference implementation complete
- 📋 Phases 2-7: Rollout in progress

### Week 2: Validation + Snapshots (Feb 24-28)

| Task | Effort | Status | Impact |
|------|--------|--------|--------|
| Write prompt caching tests | 1 day | 📋 Pending | Validate cache hit rate >60% |
| Run 100-task benchmark | 0.5 day | 📋 Pending | Measure actual cost reduction |
| Add cache metrics to OTel | 0.5 day | 📋 Pending | Observability |
| Event log snapshot mechanism | 2 days | 📋 Pending | <500ms crash recovery |
| Documentation update | 0.5 day | 📋 Pending | CHANGELOG, README |

**Success Metrics (Week 2):**
- [ ] Cache hit rate >60% on repeated tasks
- [ ] Cost reduction >50% measured on benchmark
- [ ] Snapshot recovery <500ms for 10k events
- [ ] All tests pass (2500+ test suite)

---

## Phase B: Rust Migration (Surgical Ports) - Mar-May

**Source**: `todomig.md` - Surgical guide, not rewrite
**Total Effort**: ~40 days spread over 3 months
**Goal**: Security (ReDoS immunity) + Batch throughput + Docker reduction

### Phase 1: RRF + BM25 Scoring (Mar 1-15, 12 days)

**Verdict**: GO (low-risk, high-ROI)
**Expected Impact**: 8-12× batch retrieval scoring throughput

| Task | Days | Status | Deliverable |
|------|------|--------|-------------|
| Extend `compute_rrf` for BM25 | 2 | 📋 Pending | `nexus_core/lib.rs` |
| Implement `batch_bm25_score` | 3 | 📋 Pending | Rayon parallel scoring |
| Python bindings via PyO3 | 2 | 📋 Pending | `hybrid_backend.py` integration |
| Benchmark validation | 2 | 📋 Pending | Verify 8-12× speedup |
| Feature flag testing | 1 | 📋 Pending | `NEXUS_FF_RUST_ACCELERATION` |
| Documentation | 2 | 📋 Pending | Module README |

**Crates**: `rayon` 1.10, `ordered-float` 4.0, `serde` 1.0

**Risk**: **Low** (pure math, already have RRF/TF-IDF working)

---

### Phase 2 (MOVED TO PHASE 3): Input/Output Guards - ReDoS Immunity (Mar 16-Apr 5, 15 days)

**Verdict**: CONDITIONAL GO (security-critical, high effort)
**Expected Impact**: **Eliminate ReDoS vulnerability class** (Cloudflare 2019 lesson)

| Task | Days | Status | Deliverable |
|------|------|--------|-------------|
| PyO3 0.22 -> 0.27 upgrade | 2 | 📋 Pending | Update existing `nexus_core` |
| Port patterns to Rust `RegexSet` | 5 | 📋 Pending | Single-pass pattern bank |
| Incremental migration (patterns first) | 3 | 📋 Pending | `rure` Python bindings |
| Full PyO3 port (detection logic) | 3 | 📋 Pending | `input_guard.py` -> Rust |
| Security validation | 2 | 📋 Pending | ReDoS immunity test suite |

**Crates**: `regex` 1.11, `regex-automata` 0.4, `unicode-normalization` 0.1

**Risk**: **Medium-High** (924 LOC, complex surface area)

**Rationale for Priority**: Security fix > performance optimization. Cloudflare's 27-minute global outage (2019) was caused by single malicious regex. This is the highest-ROI security improvement for NEXUS.

---

### Phase 3 (MOVED FROM PHASE 2): JSON Extraction (Apr 6-20, 13 days)

**Verdict**: GO (security + performance)
**Expected Impact**: 4-6× parse speed + type safety

| Task | Days | Status | Deliverable |
|------|------|--------|-------------|
| Define Rust structs for LLM schemas | 2 | 📋 Pending | `#[derive(Deserialize)]` |
| Heuristic JSON extraction (regex) | 3 | 📋 Pending | Find JSON in free-text |
| `serde_json` typed parsing | 3 | 📋 Pending | Type-safe deserialization |
| Python bindings | 2 | 📋 Pending | Return dicts via PyO3 |
| Benchmark + validation | 3 | 📋 Pending | Verify 4-6× speedup |

**Crates**: `serde_json` 1.0, `regex` 1.11, `once_cell` 1.19

**Risk**: **Medium** (untrusted LLM output parsing)

---

### Phase 4: ONNX Embedding Backend (Apr 21-May 10, 15 days)

**Verdict**: CONDITIONAL GO (Docker/RAM, not speed)
**Expected Impact**: 2.5GB -> 600MB Docker (70% reduction)

| Task | Days | Status | Deliverable |
|------|------|--------|-------------|
| Export model to ONNX + INT8 quantization | 2 | 📋 Pending | `model.onnx` |
| Validate retrieval quality (<3% loss) | 2 | 📋 Pending | Benchmark suite |
| Replace `sentence-transformers` -> `fastembed` | 3 | 📋 Pending | Python path (easier) |
| OR: Rust `ort` + PyO3 (harder path) | 5 | 📋 Pending | Rust path (smaller) |
| Docker image optimization | 2 | 📋 Pending | Verify 70% reduction |
| RAM profiling | 1 | 📋 Pending | Confirm ~250-400 MB |

**Crates** (if Rust): `ort` 2.0, `ndarray` 0.16, `tokenizers` 0.20

**Risk**: **Medium** (model quality validation critical)

---

## DO NOT PORT (Permanent Python) - todomig.md Guidance

These modules remain in **Python permanently**. Porting would increase maintenance burden with zero benefit:

| Module | LOC | Reason | Bottleneck |
|--------|-----|--------|------------|
| **FSM Event Sourcing** | 371 | I/O-bound (Redis, JSONL) | Redis latency |
| **Budget Tracker** | 427 | Simple arithmetic, changes with pricing | None |
| **Message Protocol** | 384 | Already Pydantic v2 (Rust-backed) | I/O-bound |
| **MCP Protocol** | ~400 | JSON-RPC over stdio, I/O-bound | Stdio transport |
| **FastAPI CEREBRO** | — | Web framework, rapid iteration needed | HTTP I/O |
| **Prompt Templates** | — | Changes weekly, prompt engineering | N/A |
| **HiveMind Pipeline** | — | Business logic, orchestration | LLM API (15-60s) |
| **Swarm Engine** | — | Orchestration, LLM-bound | LLM API |

**Key Insight (todomig.md)**: "LLM API calls dominate wall-clock time by two orders of magnitude. Python overhead for orchestration is 1-50ms vs 15-60s waiting on API responses. Even 10× Python speedup = imperceptible."

---

## Timeline Overview

```
Feb 17-21  [====== Python P0: Prompt Caching ======]
Feb 24-28  [=== Validation + Snapshots ===]
Mar 1-15   [======= Rust Phase 1: RRF+BM25 =======]
Mar 16-Apr 5 [========== Rust Phase 2: ReDoS Immunity ==========]
Apr 6-20   [======= Rust Phase 3: JSON Extraction =======]
Apr 21-May 10 [======== Rust Phase 4: ONNX Embedding ========]
May 11-31  [=== Buffer + Documentation ===]
```

**Total**: 3.5 months
- **Python optimizations**: 2 weeks (immediate ROI)
- **Rust migration**: 3 months (spread to avoid velocity drop)

---

## Expected Impact Summary

### Python Optimizations (P0)
| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Cost per HiveMind task | $0.50 | $0.15 | **-70%** |
| Cache hit rate | 0% | 60-80% | **+60-80pp** |
| TTFT (time-to-first-token) | 2.0s | 1.4s | **-30%** |
| Crash recovery (10k events) | 10s | <0.5s | **20× faster** |

### Rust Migration (Phases 1-4)
| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Batch retrieval scoring (1K docs) | ~50-100ms | **~5-10ms** | **10× faster** |
| ReDoS vulnerability | Present | **Eliminated** | **Security fix** |
| JSON parse speed per response | ~1-5ms | **~0.2-1ms** | **5× faster** |
| Docker image size | ~2.5 GB | **~600 MB** | **70% reduction** |
| Runtime RAM | ~600-800 MB | **~250-400 MB** | **50% reduction** |
| **End-to-end latency** | 15-60s | 15-60s | **Unchanged** (LLM-bound) |

**Honest Conclusion (todomig.md)**: End-to-end latency will NOT change because LLM API calls dominate. Value is batch throughput, structural security, and deployment cost reduction.

---

## Maintenance Overhead

| Phase | Monthly Maintenance | PyO3 Upgrade Cost | Build Time |
|-------|---------------------|-------------------|------------|
| Pure Python (current) | ~2 hrs/month | N/A | ~2 min |
| After Python P0 | ~2 hrs/month | N/A | ~2 min |
| After Rust Phase 1-2 | ~4-5 hrs/month | ~0.5-1 day/release (every 2-3 months) | ~5 min |
| After all Rust phases | ~6-8 hrs/month | ~1 day/release | ~7 min |

**PyO3 Current Version**: 0.27.1 (Oct 2025)
**NEXUS Current**: 0.22 (needs upgrade before new work)
**Upgrade Budget**: 2-3 days for 0.22 -> 0.27 migration

---

## Risk Mitigation

### Python P0 Risks
- **Cache invalidation**: Keep system prompts 100% static, ALL dynamic content in user prompt
- **Legacy driver compat**: Use `invoke()` from `BaseAsyncDriver` protocol (already implemented)
- **Response format**: Extract `DriverResponse.content`, parse as before

### Rust Migration Risks
- **Velocity drop**: Spread 40 days over 3 months (avoid 30-50% typical velocity drop)
- **PyO3 breaking changes**: Budget 0.5-1 day per release, releases every 2-3 months
- **Build complexity**: Use `maturin` for transparent Rust compilation in CI/CD
- **Model quality (ONNX)**: Validate <3% accuracy loss on retrieval benchmarks
- **ReDoS migration**: Incremental approach - port patterns first via `rure` before full PyO3

---

## Success Criteria

### Week 1 (Prompt Caching)
- [x] Infrastructure complete (`prompts.py` created)
- [x] Phase 1 reference implementation
- [ ] Phases 2-7 updated
- [ ] Cache hit rate >60%
- [ ] No test regressions

### Week 2 (Validation)
- [ ] 100-task benchmark shows >50% cost reduction
- [ ] Event snapshots <500ms recovery
- [ ] OTel cache metrics visible
- [ ] Documentation updated

### Rust Phase 1 (RRF+BM25)
- [ ] 8-12× batch scoring speedup measured
- [ ] Feature flag fallback working
- [ ] Zero end-to-end latency change (LLM-bound)

### Rust Phase 2 (ReDoS)
- [ ] ReDoS vulnerability eliminated (test suite)
- [ ] No catastrophic backtracking possible
- [ ] Pattern scanning still functional

### Rust Phase 3 (JSON)
- [ ] 4-6× parse speed measured
- [ ] Type safety validated (no runtime errors)
- [ ] Recursion depth limited (DoS prevention)

### Rust Phase 4 (ONNX)
- [ ] Docker: 2.5GB -> 600MB (70% reduction)
- [ ] RAM: 600-800MB -> 250-400MB
- [ ] Retrieval quality: <3% accuracy loss

---

## Current Status (2026-02-17)

**Python P0**:
- [OK] Meta-analysis complete
- [OK] Prompts infrastructure created
- [OK] Phase 1 (Analysis) updated
- ⏳ Phases 2-7 in progress

**Rust Migration**:
- 📋 Planned, starts March 1
- 📋 todomig.md guide complete

**Next Action**: Continue Phase 2-7 prompt caching implementation

---

**Roadmap Version**: 1.0
**Last Updated**: 2026-02-17
**Maintained By**: Claude Opus 4.6 + Gemini 3-Pro
