# NEXUS V12.4 - Observability Package

**P5.6 Phase 1: Package Consolidation for Reduced Cognitive Load**

This package consolidates all observability-related components into a unified domain, reducing the number of top-level packages from 40 to 18.

## 📦 Package Structure

```
core/observability/
+-- __init__.py           # Unified exports for all subpackages
+-- README.md             # This file
+-- audit/                # Audit logging and HITL persistence
|   +-- __init__.py
|   +-- audit_logger.py   # AuditLogger service
|   +-- models.py         # AuditLog, HITLRequest models
|   +-- README.md
+-- logging/              # Structured logging
|   +-- __init__.py
|   +-- logger_v7.py      # NexusLogger (main system logger)
|   +-- driver_logger.py  # Lightweight driver logger
|   +-- README.md
+-- telemetry/            # Metrics, profiling, budget tracking
|   +-- __init__.py
|   +-- metrics.py        # TelemetryCollector, MetricType
|   +-- exporter.py       # TelemetryExporter (CSV, reports)
|   +-- budget_tracker.py # BudgetTracker, cost tracking
|   +-- service.py        # TelemetryService, BudgetService
|   +-- otel_provider.py  # OpenTelemetry integration
|   +-- performance_profiler.py    # PerformanceProfiler
|   +-- health_aggregator.py       # HealthAggregator
|   +-- error_pattern_analyzer.py  # ErrorPatternAnalyzer
|   +-- redis_bridge.py   # Redis log handler
|   +-- README.md
+-- events/               # Event bus, analytics, telemetry bridge
    +-- __init__.py
    +-- types.py          # CerebroEvent, CerebroEventType
    +-- redis_bus.py      # RedisEventBus for external UIs
    +-- event_analytics.py # EventAnalytics (V12.4)
    +-- telemetry_bridge.py # TelemetryBridge (Synapse)
    +-- event_store.py    # Event persistence
    +-- README.md
```

## 🎯 Domain Purpose

The observability package provides **comprehensive system visibility** through:

1. **Audit Logging** - Immutable audit trail for compliance and debugging
2. **Structured Logging** - Hierarchical, filterable logging for system events
3. **Telemetry** - Metrics, performance profiling, cost tracking, OpenTelemetry
4. **Event Analytics** - Real-time event streaming and analytics for external UIs

## 📊 Key Components

### Audit Subsystem

```python
from core.observability import AuditLogger, AuditAction, HITLRequest

# Log audit event
await AuditLogger.log(
    tenant_id=tenant_id,
    user_id=user_id,
    action=AuditAction.FILE_WRITE,
    resource_type="file",
    resource_id="/path/to/file.txt",
    status="success"
)

# Query audit logs
logs = await AuditLogger.query(
    tenant_id=tenant_id,
    action=AuditAction.PERMISSION_DENIED,
    limit=100
)
```

**Features:**
- Append-only (immutable) audit log
- HITL (Human-in-the-Loop) persistence for workflow interruptions
- Multi-tenant isolation
- TTL-based expiration for HITL requests

### Logging Subsystem

```python
from core.observability import init_logger, get_logger, LogLevel

# Initialize system logger
init_logger(level=LogLevel.INFO)

# Get logger instance
logger = get_logger()
logger.info("System initialized", extra={"component": "orchestrator"})

# Get driver logger (lightweight)
from core.observability import get_driver_logger
driver_logger = get_driver_logger("gemini")
driver_logger.debug("API call", latency_ms=42)
```

**Features:**
- Hierarchical structured logging (JSONL format)
- Automatic log rotation and cleanup
- Driver-specific logging (Gemini, Claude, DeepSeek, Kimi)
- Event-based logging for FSM transitions

### Telemetry Subsystem

```python
from core.observability import (
    TelemetryCollector,
    BudgetTracker,
    get_profiler,
    init_otel
)

# Track API calls
TelemetryCollector.record_llm_call(
    model="claude-sonnet-4-6-20250929",
    tokens_in=150,
    tokens_out=300,
    latency_ms=1200
)

# Budget tracking
tracker = get_budget_tracker()
tracker.set_budget(budget_usd=10.0, period="daily")
tracker.check_budget(cost_usd=0.05)  # Raises BudgetExceededError if exceeded

# Performance profiling
profiler = get_profiler()
with profiler.trace("function_name"):
    # ... code to profile ...
    pass

# OpenTelemetry
init_otel(service_name="nexus", otlp_endpoint="http://localhost:4317")
```

**Features:**
- Multi-model cost tracking (Claude Opus/Sonnet, Gemini, DeepSeek, Kimi)
- Budget caps with warnings and hard limits
- Performance profiling with bottleneck detection
- OpenTelemetry (OTel) integration for distributed tracing
- Health aggregation across all subsystems
- Error pattern analysis for debugging

### Events Subsystem

```python
from core.observability import (
    CerebroEvent,
    CerebroEventType,
    get_redis_bus,
    get_event_analytics
)

# Publish event to Redis (for external UIs like CEREBRO)
event = CerebroEvent(
    event_type=CerebroEventType.INTERACTION_ASK,
    tenant_id="tenant_123",
    workspace_id="default",
    payload={"prompt": "Continue?"}
)
await get_redis_bus().publish(event)

# Event analytics
analytics = get_event_analytics()
stats = analytics.get_stats()
print(f"Total events: {stats.total_events}")
```

**Features:**
- Redis-based event bus for real-time UI updates
- Event analytics for monitoring and debugging
- Telemetry bridge for external observability platforms
- Event persistence for replay and debugging

## 🔧 Migration Impact

**Before P5.6 Phase 1:**
```python
from core.audit import AuditLogger
from core.logging import get_logger
from core.telemetry import BudgetTracker
from core.events import CerebroEvent
```

**After P5.6 Phase 1:**
```python
# All imports from unified package
from core.observability import (
    AuditLogger,
    get_logger,
    BudgetTracker,
    CerebroEvent
)

# Or from subpackages
from core.observability.audit import AuditLogger
from core.observability.logging import get_logger
from core.observability.telemetry import BudgetTracker
from core.observability.events import CerebroEvent
```

**Statistics:**
- **Files migrated:** 25 Python files + 4 READMEs
- **Import updates:** 86 files across codebase
- **Commits:** 4 atomic commits (191c3d1, 16916f9, 0bfe993, 7c45b0c)
- **Impact:** 100 files changed, +1194/-1131 lines

## 📚 Related Documentation

- [Audit README](audit/README.md) - Audit logging and HITL persistence
- [Logging README](logging/README.md) - Structured logging system
- [Telemetry README](telemetry/README.md) - Metrics, profiling, budget tracking
- [Events README](events/README.md) - Event bus and analytics

## 🚀 Next Steps (P5.6 Phase 2-8)

Phase 1 (Observability) is complete. Remaining phases:

- **Phase 2**: Infrastructure (db, resilience, session, context)
- **Phase 3**: Interface (interface, workspace, notifications, mcp)
- **Phase 4**: Security (security, governance, interaction)
- **Phase 5**: Memory (memory, prompts, skills)
- **Phase 6**: Execution (DEFERRED - high complexity)
- **Phase 7**: Intelligence (DEFERRED - high complexity)
- **Phase 8**: Final validation and documentation

---

**Version:** NEXUS V12.4 COGNITIVE BOOST
**Status:** P5.6 Phase 1 COMPLETE [OK]
**Date:** 2026-02-19
