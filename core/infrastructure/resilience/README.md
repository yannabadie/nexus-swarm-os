# Resilience Module

## Synopsis
The Resilience module provides fault tolerance and health monitoring for multi-agent orchestration. It implements the Circuit Breaker pattern to prevent cascading failures, a hierarchical breaker for global cascade detection, and a unified system health monitor for V9.5+ components. This module is critical for maintaining system stability under failure conditions.

## Component Map
| File | Purpose | Key Exports |
|------|---------|-------------|
| `circuit_breaker.py` | Circuit breaker with exponential backoff, hierarchical cascade detection | `CircuitBreaker`, `HierarchicalCircuitBreaker`, `CircuitState`, `CircuitOpenError`, `get_circuit_breaker()`, `get_hierarchical_breaker()` |
| `system_health.py` | Unified health monitoring for all V9.5 components | `SystemHealth`, `HealthStatus`, `ComponentHealth`, `HealthReport`, `get_system_health()`, `reset_system_health()` |
| `__init__.py` | Module initialization with public exports | All classes and functions from submodules |

## Key Interfaces

### Circuit Breaker Pattern

**`CircuitBreaker`** (dataclass)
- Three-state breaker: `CLOSED` (normal), `OPEN` (failures exceeded), `HALF_OPEN` (testing recovery)
- Exponential backoff with configurable thresholds and max backoff time
- Supports both async and sync function calls
- Key methods: `call()`, `call_sync()`, `reset()`, `get_status()`
- Prevents cascading failures by blocking requests when failure threshold is reached

**`CircuitState`** (enum)
- `CLOSED`: Normal operation, requests pass through
- `OPEN`: Too many failures, requests blocked with `CircuitOpenError`
- `HALF_OPEN`: Testing recovery after timeout

**`CircuitOpenError`** (exception)
- Raised when circuit is open and call is rejected
- Contains: `name`, `time_until_retry`, `failure_count`

**`get_circuit_breaker(name: str, failure_threshold: int = 3, recovery_timeout: float = 30.0, max_backoff: float = 300.0) -> CircuitBreaker`**
- Get or create a circuit breaker by name (e.g., "gemini", "claude", "hivemind")
- Shared by name - subsequent calls return same instance

### V11 Hierarchical Circuit Breaker (FIX F17)

**`HierarchicalCircuitBreaker`**
- Two-level hierarchy: global breaker + per-provider breakers
- Detects cascade failures when multiple providers fail within a time window
- Global breaker trips on widespread failures (e.g., network down)
- Per-provider breakers trip on provider-specific issues
- Key methods: `call()`, `call_sync()`, `reset_all()`, `get_status()`

**Cascade Detection**
- Monitors failures across providers within a `cascade_window` (default 30s)
- Trips global breaker when `cascade_threshold` providers fail (default 3)
- Prevents N independent recovery attempts during global failures

**`get_hierarchical_breaker() -> HierarchicalCircuitBreaker`**
- Get singleton hierarchical breaker instance
- Use for cascade-aware circuit breaking across multiple providers

### System Health Monitoring

**`SystemHealth`**
- Unified health monitor for V9.5+ components
- Checks: Constants, SafeTaskManager, EventBus, ToolRegistry, CircuitBreaker
- Async health check with aggregated reporting
- V10 PRISM: Tenant-scoped via ServiceFactory when context is active

**`HealthStatus`** (enum)
- `HEALTHY`: Component operating normally
- `DEGRADED`: Partial functionality
- `UNHEALTHY`: Component failed
- `UNKNOWN`: Cannot determine status

**`ComponentHealth`** (dataclass)
- Health status of a single component
- Fields: `name`, `status`, `message`, `details`, `checked_at`
- Serializable to dict for logging

**`HealthReport`** (dataclass)
- Aggregated report for all components
- Fields: `components`, `overall_status`, `checked_at`
- Properties: `healthy_count`, `unhealthy_count`
- Methods: `summary()` (human-readable), `to_dict()` (serialization)

**`get_system_health(workspace_path: Optional[Path] = None) -> SystemHealth`**
- Get system health monitor
- V10: Returns tenant-scoped monitor via ServiceFactory if context active
- Legacy: Returns global singleton

### Usage Examples

```python
# Basic circuit breaker
from core.resilience import get_circuit_breaker, CircuitOpenError

breaker = get_circuit_breaker("gemini")
try:
    result = await breaker.call(agent.invoke, prompt)
except CircuitOpenError as e:
    logger.warning(f"Circuit open: {e.time_until_retry}s until retry")
    # Use fallback logic

# Hierarchical breaker for cascade detection
from core.resilience import get_hierarchical_breaker

hcb = get_hierarchical_breaker()
result = await hcb.call("gemini", agent.invoke, prompt)

# System health check
from core.resilience import get_system_health

health = get_system_health()
report = await health.check_all()
print(report.summary())
# Output:
# System Health: HEALTHY
# Components: 5/5 healthy
#   [OK] Constants: v9.5.0 loaded
#   [OK] SafeTaskManager: 0 active tasks
#   [OK] EventBus: 142 events published
#   [OK] ToolRegistry: 11 tools registered
#   [OK] CircuitBreaker: State: closed
```

## Dependencies & Integration

### Internal Dependencies
- `core.constants` - Timeout and retry limits
- `core.async_primitives.safe_task_manager` - Task tracking
- `core.async_primitives.event_bus` - Event system
- `core.execution.tool_registry` - Tool availability
- `core.context` (V10) - Tenant context
- `core.factory` (V10) - Service factory for tenant scoping

### Integration Points
- **Orchestrators**: FSM, HiveMind, SwarmEngine wrap agent invocations in circuit breakers
- **Health Monitoring**: SystemHealth provides `/health` endpoint data
- **Cascade Protection**: HierarchicalCircuitBreaker prevents global failure cascades
- **V10 PRISM**: Tenant-scoped circuit breakers and health monitors

### Design Notes
- **Exponential Backoff**: Recovery timeout doubles on each HALF_OPEN failure (max 5-10 min)
- **Thread Safety**: All state mutations protected by locks
- **Async + Sync**: Both calling patterns supported
- **Global vs Per-Provider**: Use `HierarchicalCircuitBreaker` for cascade-aware protection
- **Health Check Components**: Constants, SafeTaskManager, EventBus, ToolRegistry, CircuitBreaker
- **V10 Integration**: Seamless tenant scoping when context module available
- **Testing Utilities**: `reset_all_circuits()`, `reset_system_health()`, `reset_hierarchical_breaker()`

## V12.4 COGNITIVE BOOST Additions

| File | Purpose | Key Exports |
|------|---------|-------------|
| `resilience_event_tracker.py` | Tracks resilience events (circuit breaker trips, rate limiter activations, checkpoint restorations, retries, failovers, recovery actions) with aggregate metrics per event type and component | `get_resilience_tracker`, `ResilienceEventTracker` |
| `request_deduplicator.py` | Prevents duplicate execution during retries via hash-based fingerprinting with TTL expiration, tracking in-flight and completed requests with cached result return | `get_deduplicator`, `RequestDeduplicator` |
| `checkpoint_manager.py` | Deterministic checkpoints at phase boundaries for long-running tasks enabling pause/resume, rewind-to-checkpoint, and replay for debugging | `get_checkpoint_manager`, `CheckpointManager` |
| `rate_limiter.py` | Per-provider token bucket rate limiting for API calls with configurable RPM and TPM limits, preventing upstream rate limit errors before calls are made | `RateLimiter`, `ProviderLimits` |
