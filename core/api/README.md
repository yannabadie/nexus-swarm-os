# API

## Synopsis
Rate limiting and concurrency control for API calls. Prevents 429 Too Many Requests errors and resource starvation in PARALLEL mode execution.

## Component Map
| File | Purpose | Key Exports |
|------|---------|-------------|
| `rate_limiter.py` | Token bucket rate limiter for API calls | `APIRateLimiter`, `RateLimitExceeded`, `RateLimiterRegistry`, `get_rate_limiter` |
| `concurrency_limiter.py` | Global concurrency limiting for agent invocations | `ConcurrencyLimiter`, `get_concurrency_limiter` |
| `__init__.py` | Module exports | `APIRateLimiter`, `RateLimitExceeded` |

## Key Interfaces

### APIRateLimiter
Token bucket rate limiter (60-second sliding window).

**Methods:**
```python
await limiter.acquire()            # V11 FIX: Alias for acquire_async()
await limiter.acquire_async(timeout=30.0)
limiter.acquire_sync(timeout=30.0)  # For ThreadPoolExecutor
limiter.get_stats() -> Dict
limiter.reset()
```

**Default Limits:**
- Gemini: 60 RPM, burst 10
- Claude: 50 RPM, burst 8
- Default: 30 RPM, burst 5

**V10 PRISM:** Tenant-scoped via `get_rate_limiter(provider)`.

### ConcurrencyLimiter
Global semaphore limiting concurrent agent invocations.

**Problem Solved:**
- MAX_PARALLEL_AGENTS=4 existed but was NEVER ENFORCED
- 50 parallel agents = server crash

**Methods:**
```python
async with limiter.acquire_async(timeout=60.0):
    result = await driver.invoke(...)

with limiter.acquire_sync_context(timeout=60.0):
    result = driver.invoke(...)

limiter.get_stats() -> dict
```

**Configuration:** `NEXUS_MAX_PARALLEL_AGENTS=4` (default: CPU count or 4)

## Dependencies
- **Internal**: `core.constants`, `core.context`, `core.factory` (V10)
- **External**: `asyncio`, `threading`, `time`, `collections`

## Integration Points

**Used By:**
- `core.drivers.base` - Rate limiting before API calls
- `core.swarm.executors.parallel` - Concurrency limiting
- `core.orchestration.agent_invoker` - Invocation limits

## Version History
- V8.4.5: APIRateLimiter
- V11 SYNCHROTRON: ConcurrencyLimiter
- V11 FIX F16: `acquire()` alias
- V10 PRISM: Multi-tenant support
