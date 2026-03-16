# NEXUS V8.0 - Known Issues & Workarounds

**Last Updated**: 2025-12-08
**Maintainer**: NEXUS Team

---

## KI-001: HuggingFace Model Download SSL Failure

**Date Discovered**: 2025-12-08
**Severity**: HIGH
**Component**: Dense Embeddings Backend (Phase 10g)
**Status**: DOCUMENTED (workaround available)

### Description

Corporate networks with SSL inspection/proxy can block downloads from HuggingFace Hub. This affects the `all-MiniLM-L6-v2` model required for semantic search (Dense backend).

### Error Signature

```
SSLError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed
requests.exceptions.SSLError: HTTPSConnectionPool(host='huggingface.co', ...)
```

### Impact

| Component | Impact |
|-----------|--------|
| `DenseBackend` | Cannot load embeddings model |
| `ProjectMemory` | Falls back to BM25S or TF-IDF |
| Semantic Search | DISABLED |

### Workarounds

#### Option 1: Pre-download Model (Recommended)

Download the model on a non-corporate network, then copy to cache:

```bash
# On unrestricted network
pip install huggingface_hub
huggingface-cli download sentence-transformers/all-MiniLM-L6-v2

# Copy cache to corporate machine
# Windows: %USERPROFILE%\.cache\huggingface\hub\
# Linux: ~/.cache/huggingface/hub/
```

#### Option 2: Set HuggingFace Cache Path

```bash
export HF_HOME=/path/to/pre-downloaded/cache
export TRANSFORMERS_CACHE=/path/to/pre-downloaded/cache
```

#### Option 3: Disable SSL Verification (NOT RECOMMENDED)

```python
import os
os.environ['CURL_CA_BUNDLE'] = ''
os.environ['REQUESTS_CA_BUNDLE'] = ''
```

#### Option 4: Force BM25S Backend

```bash
export PROJECT_MEMORY_BACKEND=bm25
```

### Verification

```python
from sentence_transformers import SentenceTransformer
model = SentenceTransformer('all-MiniLM-L6-v2')
print(f"Model dimension: {model.get_sentence_embedding_dimension()}")
# Expected: 384
```

### References

- [HuggingFace Hub Docs](https://huggingface.co/docs/huggingface_hub/guides/download)
- [Sentence-Transformers](https://www.sbert.net/)
- Phase 10g: `core/memory/backends/dense.py`

---

## KI-002: Phase 5b Hardcoded Agent Lookups

**Date Discovered**: 2025-12-08
**Severity**: LOW (for current 2-agent setup)
**Component**: Orchestration
**Status**: DOCUMENTED (tech debt)

### Description

20+ hardcoded `if agent == "Claude"` / `if agent == "Gemini"` lookups exist in orchestration code. This works for the current 2-agent setup but would require refactoring for N>2 primary agents.

### Files Affected

| File | Occurrences |
|------|-------------|
| `fsm_handlers.py` | 8 |
| `agent_invoker.py` | 4 |
| `context_builder.py` | 3 |
| Others | 5 |

### Impact

- **Current**: None (2-agent system works)
- **Future**: Refactoring needed if adding 3rd primary agent

### Resolution

Planned for Phase 5b.1 - Create `AgentRegistry` abstraction.

---

## Index

| ID | Title | Severity | Status |
|----|-------|----------|--------|
| KI-001 | HuggingFace SSL Failure | HIGH | DOCUMENTED |
| KI-002 | Phase 5b Hardcoded Lookups | LOW | DOCUMENTED |
