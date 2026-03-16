# Telemetry Module

## Synopsis
The Telemetry module provides comprehensive file-based telemetry and budget tracking for NEXUS operations. It tracks API calls, tokens, latency, costs, session metrics, swarm collaboration, error rates, and enforces budget caps. Features CSV export, reporting, Redis log bridging, and service layer (V9.1) for centralized telemetry and budget management. Future-ready for export to Langfuse, OTLP, or other backends.

## Component Map
| File | Purpose | Key Exports |
|------|---------|-------------|
| `metrics.py` | Core telemetry collector tracking API calls, swarm tasks, tools, errors, evolution | `TelemetryCollector`, `MetricType`, `APICallMetric`, `SwarmTaskMetric`, `SessionMetric` |
| `budget_tracker.py` | Budget tracking with daily limits, cost calculation, and quota enforcement (Phase 14d) | `BudgetTracker`, `BudgetState`, `CostRecord`, `BudgetExceededError`, `BudgetWarning` |
| `exporter.py` | Telemetry export to CSV and report generation (Phase 13c) | `TelemetryExporter`, `TelemetryEvent` |
| `redis_bridge.py` | Redis log handler for distributed logging (V10 CEREBRO) | `RedisLogHandler` |
| `service.py` | Service layer with TelemetryService and BudgetService (V9.1) | `TelemetryService`, `ServiceResult` |
| `__init__.py` | Module initialization with public exports | All classes from submodules |

## Key Interfaces

### TelemetryCollector

**`TelemetryCollector`**
- Core telemetry collection engine
- Tracks all NEXUS operations: API calls, swarm tasks, tools, errors, evolution
- Integrates BudgetTracker for cost tracking and enforcement
- File-based JSONL output for persistence

**Recording Methods:**
- `record_api_call(provider, model, tokens_in, tokens_out, latency_seconds, success, task_type, error, input_text, output_text)`: Track LLM API calls with automatic cost calculation
- `record_swarm_task(mode, rounds, duration_seconds, success, agents_used, negotiation_turns)`: Track swarm collaboration metrics
- `record_tool_execution(tool_name, duration_seconds, success, error)`: Track tool usage
- `record_error(error_type, message, context)`: Track errors with context
- `record_evolution(generation, child_id, parent_score, child_score, promoted, mutations)`: Track agent evolution

**Session Management:**
- `get_session_summary() -> SessionMetric`: Get current session summary
- `write_session_summary()`: Persist session summary to file
- `print_summary()`: Print human-readable session summary

**Budget Integration:**
- `enforce_budget() -> bool`: Check and enforce budget cap (raises BudgetExceededError if exceeded)
- `get_budget_stats() -> Dict`: Get current budget status
- `get_budget_warning_level() -> Optional[str]`: Get warning level ("info", "warning", "critical", or None)

### BudgetTracker (Phase 14d)

**`BudgetTracker`**
- Daily budget tracking with automatic daily reset
- Model-specific pricing (Opus, Sonnet, Gemini Pro, etc.)
- Token estimation from text
- Lifecycle tracking (daily spend, total lifetime spend)

**Key Methods:**
- `estimate_tokens(text: str) -> int`: Estimate token count (4 chars/token heuristic)
- `get_model_pricing(model: str) -> Dict[str, float]`: Get input/output pricing for model
- `calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float`: Calculate cost in USD
- `track_cost(model, input_tokens, output_tokens, input_text, output_text) -> float`: Track cost and check budget
- `check_budget() -> bool`: Check if under budget (raises BudgetExceededError if not)
- `get_budget_status() -> Tuple[float, float, float]`: Get (spent_today, limit, remaining)
- `get_remaining() -> float`: Get remaining budget
- `get_warning_level() -> Optional[str]`: Get warning level based on spend percentage
- `reset_daily()`: Manual daily reset
- `add_credit(amount_usd: float)`: Add credit to budget (reduces daily spend)

**Pricing Table (USD):**
| Model | Input (per 1M tokens) | Output (per 1M tokens) |
|-------|----------------------|------------------------|
| Claude Opus 4.5 | $15.00 | $75.00 |
| Claude Sonnet 4.5 | $3.00 | $15.00 |
| Gemini 3 Pro | $1.25 | $5.00 |
| Gemini 2.5 Flash | $0.075 | $0.30 |

### TelemetryExporter (Phase 13c)

**`TelemetryExporter`**
- Reads JSONL telemetry files and exports to CSV or reports
- Filters by date range and event types
- Generates human-readable reports

**Key Methods:**
- `get_event_count() -> int`: Count total events in telemetry file
- `read_events(days: int = 7, event_types: Optional[List[str]] = None) -> List[TelemetryEvent]`: Read recent events
- `export_to_csv(output_dir: Optional[Path] = None, days: Optional[int] = None) -> Path`: Export to CSV
- `generate_report(days: int = 7) -> Dict[str, Any]`: Generate summary report
- `format_report_for_console(report: Dict[str, Any]) -> str`: Format report for display

**Report Metrics:**
- Total API calls
- Total tokens (input/output)
- Total cost (USD)
- Average latency
- Success rate
- Error count
- Swarm tasks
- Tool executions
- Top models used
- Top error types

### RedisLogHandler (V10 CEREBRO)

**`RedisLogHandler`**
- Async log handler for distributed logging via Redis
- Tenant and workspace scoped
- Queue-based with background worker thread
- Graceful degradation if Redis unavailable

**Key Methods:**
- `start() -> bool`: Start background worker
- `stop(timeout: float = 5.0)`: Stop worker and flush queue
- `emit(record: logging.LogRecord)`: Queue log record
- `get_stats() -> Dict`: Get handler statistics
- `flush()`: Force flush queue
- `close()`: Clean shutdown

### Service Layer (V9.1)

**`TelemetryService`**
- High-level service for telemetry operations
- Returns `ServiceResult` with success/error info

**Methods:**
- `report(days: int = 7) -> ServiceResult`: Generate and display report
- `status() -> ServiceResult`: Get current telemetry status
- `export(days: Optional[int] = None) -> ServiceResult`: Export to CSV

## Dependencies & Integration

### Internal Dependencies
- `core.config` - Configuration (budget limits, model IDs)
- `pathlib` - File path handling
- `json` - JSONL persistence
- `datetime` - Time tracking
- `threading` - Lock for thread safety
- `logging` - Python logging integration
- `queue` - Redis log handler queue

### Integration Points
- **Drivers**: Gemini and Claude drivers call `record_api_call()` after each invocation
- **SwarmEngine**: Calls `record_swarm_task()` for collaboration metrics
- **ExecutionEngine**: Calls `record_tool_execution()` for tool usage
- **EvolutionEngine**: Calls `record_evolution()` for agent mutations
- **Orchestrators**: Call `enforce_budget()` before expensive operations
- **CEREBRO (V10)**: RedisLogHandler bridges logs to Redis for distributed systems

### File Structure

```
workspace/
+-- telemetry.jsonl          # Main telemetry log (append-only)
+-- budget_state.json        # Budget state (daily spend, lifetime spend)
+-- reports/                 # Exported reports (CSV, etc.)
    +-- telemetry_YYYYMMDD.csv
```

### Usage Examples

```python
from core.telemetry import TelemetryCollector
from pathlib import Path

# Initialize collector
collector = TelemetryCollector(
    config=config,
    output_file=Path("workspace/telemetry.jsonl")
)

# Record API call with automatic cost tracking
collector.record_api_call(
    provider="anthropic",
    model="claude-opus-4-6-20250116",
    tokens_in=1500,
    tokens_out=800,
    latency_seconds=2.5,
    success=True,
    task_type="brainstorm"
)

# Record swarm task
collector.record_swarm_task(
    mode="PARALLEL",
    rounds=3,
    duration_seconds=15.2,
    success=True,
    agents_used=["gemini", "claude"],
    negotiation_turns=2
)

# Check budget before expensive operation
if not collector.enforce_budget():
    print("Budget exceeded, stopping")
    return

# Get budget warning level
warning = collector.get_budget_warning_level()
if warning == "critical":
    print("WARNING: 90%+ budget used!")

# Print session summary
collector.print_summary()
# Output:
# Session Summary (nexus_abc123)
# Duration: 1h 23m
# API Calls: 47 (45 successful, 2 failed)
# Tokens: 123,456 total (98,765 in, 24,691 out)
# Cost: $1.23 USD (of $10.00 daily limit)
# Swarm Tasks: 12
# Tool Executions: 23

# Export to CSV (Phase 13c)
from core.telemetry import TelemetryExporter

exporter = TelemetryExporter(Path("workspace"))
csv_path = exporter.export_to_csv(days=7)
print(f"Exported to {csv_path}")

# Generate report
report = exporter.generate_report(days=7)
formatted = exporter.format_report_for_console(report)
print(formatted)
```

## Design Notes

### Budget Enforcement (Phase 14d)

- **Daily Reset**: Automatically resets at midnight (based on last_updated date)
- **Lifecycle Tracking**: Tracks both daily and lifetime spend
- **Soft vs Hard Limits**: Warning levels at 50%, 75%, 90% usage
- **Exceptions**: Raises `BudgetExceededError` when limit exceeded
- **Credit System**: `add_credit()` allows refunds or adjustments

### File-Based Persistence

- **JSONL Format**: Append-only for reliability
- **Atomic Writes**: Budget state written atomically
- **No Database**: Simple file-based storage for portability
- **Future Export**: Designed for easy export to Langfuse, OTLP, etc.

### Thread Safety

- All write operations protected by threading.Lock
- Safe for concurrent access from multiple threads/agents

### V10 CEREBRO Integration

- RedisLogHandler enables distributed logging
- Tenant and workspace scoped for multi-tenancy
- Graceful degradation if Redis unavailable

### Service Layer (V9.1)

- `ServiceResult` pattern for consistent error handling
- High-level API for UI commands (report, status, export)
- Console integration for formatted output

## V12.4 COGNITIVE BOOST Additions

| File | Purpose | Key Exports |
|------|---------|-------------|
| `error_pattern_analyzer.py` | Detects recurring error patterns across subsystems, aggregates per-category metrics, and identifies cascading errors and agent-specific failure trends for DIAGNOSIS phase and CEREBRO dashboards | `get_error_analyzer`, `ErrorPatternAnalyzer` |
| `performance_profiler.py` | Execution timing and bottleneck detection for FSM state transitions, swarm negotiation latency, LLM driver calls, and arbitrary spans with timing reports | `get_profiler`, `PerformanceProfiler` |
| `health_aggregator.py` | Unified health dashboard aggregator collecting data from all subsystems (SystemHealth, TelemetryCollector, BudgetTracker, drivers) into a single-pane-of-glass health report for CEREBRO UI | `HealthAggregator` |
| `otel_provider.py` | OpenTelemetry integration with auto-instrumentation for Anthropic/Google GenAI, manual spans for FSM/Swarm/evolution, and token/latency/error metrics; feature-flagged via `NEXUS_FF_OTEL_ENABLED` | `init_otel`, `get_tracer` |
