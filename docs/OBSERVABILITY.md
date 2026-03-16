# NEXUS V12.4 Observability Guide

**Epic 4.3**: OpenTelemetry + Jaeger Integration

This guide covers the observability stack for NEXUS V12.4, including distributed tracing with OpenTelemetry and Jaeger visualization.

---

## Overview

NEXUS V12.4 includes production-ready observability powered by:
- **OpenTelemetry Collector**: Receives and processes telemetry data
- **Jaeger**: Distributed tracing visualization UI
- **HiveMind Instrumentation**: 7-phase pipeline tracing
- **Swarm Engine Tracing**: Multi-agent collaboration spans
- **GenAI Semantic Conventions**: LLM call metadata (tokens, model, latency)

---

## Quick Start

### 1. Enable Observability

**Edit `.env`:**
```bash
# Enable OpenTelemetry
NEXUS_FF_OTEL_ENABLED=true

# Optional: Set environment
NEXUS_ENV=development
```

### 2. Start Observability Stack

**Start with observability profile:**
```bash
docker compose --profile observability up -d
```

This starts:
- `otel-collector` (port 4317 gRPC, 4318 HTTP)
- `jaeger` (port 16686 UI)
- `redis` (if not running)
- `nexus` (with OTel enabled)

### 3. Access Jaeger UI

Open your browser to:
```
http://localhost:16686
```

Search for service: `nexus-backend`

### 4. Run a Task

Execute a task in NEXUS:
```bash
python nexus7.py
nexus> /swarm "Analyze the codebase structure"
```

### 5. View Traces

In Jaeger UI:
1. Select service: `nexus-backend`
2. Click "Find Traces"
3. Explore the HiveMind phase spans

---

## Architecture

```
NEXUS Backend
    |
    +- OTel SDK (Python)
    |   +- Traces, Metrics, Logs
    |
    v
OTel Collector (port 4317)
    |
    +- Batch processing
    +- Memory limits
    +- Resource attributes
    |
    v
Jaeger (port 16686)
    |
    +- Trace Visualization UI
```

---

## HiveMind Phase Tracing

NEXUS instruments all 7 HiveMind phases:

| Phase | Span Name | Attributes |
|-------|-----------|------------|
| **Phase 1** | `hive_mind.phase.analysis` | `nexus.analysis.gemini_complexity`, `nexus.analysis.claude_complexity` |
| **Phase 2** | `hive_mind.phase.debate` | `nexus.debate.rounds`, `nexus.debate.resolved` |
| **Phase 3** | `hive_mind.phase.architecture` | `nexus.architecture.steps_count` |
| **Phase 4** | `hive_mind.phase.execution` | `nexus.execution.step_index`, `nexus.execution.swarm_mode` |
| **Phase 5** | `hive_mind.phase.diagnosis` | `nexus.diagnosis.error_category`, `nexus.diagnosis.root_cause` |
| **Phase 6** | `hive_mind.phase.retry` | `nexus.retry.attempt`, `nexus.retry.decision` |
| **Phase 7** | `hive_mind.phase.consolidation` | `nexus.consolidation.artifacts_archived` |

**Trace Structure:**
```
hive_mind.execution (parent)
  +- hive_mind.phase.analysis
  |   +- llm.anthropic (Claude analysis)
  |   +- llm.gemini (Gemini analysis)
  +- hive_mind.phase.debate (if needed)
  +- hive_mind.phase.architecture
  +- hive_mind.phase.execution
  |   +- swarm.ping_pong (if delegated to Swarm)
  +- hive_mind.phase.diagnosis (if error)
  +- hive_mind.phase.retry (if retry)
  +- hive_mind.phase.consolidation
```

---

## GenAI Semantic Conventions

NEXUS uses OpenTelemetry Semantic Conventions for GenAI (v1.36.0+):

**LLM Call Spans:**
```
llm.anthropic (operation: chat)
+- gen_ai.operation.name: "chat"
+- gen_ai.system: "anthropic"
+- gen_ai.request.model: "claude-sonnet-4-5-20250929"
+- gen_ai.usage.input_tokens: 1523
+- gen_ai.usage.output_tokens: 847
+- gen_ai.response.id: "msg_01abc123..."
+- gen_ai.response.finish_reasons: ["end_turn"]
+- nexus.driver.cache_hit: false
```

**Key Attributes**:
- **Token Usage**: `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`
- **Model**: `gen_ai.request.model` (requested), `gen_ai.response.model` (actual)
- **System**: `gen_ai.system` (provider: `anthropic`, `gcp.gemini`)
- **Cost Tracking**: Calculate from token counts

---

## Swarm Collaboration Tracing

Swarm modes are instrumented with nested spans:

**Example: PING_PONG mode**
```
swarm.ping_pong
  +- swarm.negotiation
  |   +- llm.anthropic (Claude proposes mode)
  +- swarm.execution
      +- swarm.round.1
      |   +- llm.gemini (Gemini responds)
      +- swarm.round.2
      |   +- llm.anthropic (Claude responds)
      +- swarm.round.3
          +- llm.gemini (Gemini finalizes)
```

**Attributes**:
- `nexus.swarm.mode`: Collaboration mode (PARALLEL, SEQUENTIAL, etc.)
- `nexus.swarm.task_id`: Task identifier
- `nexus.swarm.agents`: List of agents involved
- `nexus.swarm.rounds`: Number of exchange rounds
- `nexus.swarm.success`: Boolean result

---

## Configuration

### OTel Collector Config

Location: `config/otel-collector-config.yaml`

**Receivers:**
- OTLP gRPC (port 4317)
- OTLP HTTP (port 4318)

**Processors:**
- Memory limiter (512 MiB)
- Batch processor (10s timeout)
- Resource attributes (environment, namespace)

**Exporters:**
- Jaeger (OTLP/gRPC)
- Logging (debug)

**Extensions:**
- Health check (port 13133)
- pprof (port 1777)
- zpages (port 55679)

### Environment Variables

**Required:**
```bash
NEXUS_FF_OTEL_ENABLED=true
```

**Optional (with defaults):**
```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
OTEL_SERVICE_NAME=nexus-backend
OTEL_SERVICE_VERSION=12.4.0
OTEL_RESOURCE_ATTRIBUTES=deployment.environment=development
OTEL_LOG_LEVEL=info
```

**Docker Compose Override:**
```yaml
# docker-compose.override.yml
services:
  nexus:
    environment:
      - NEXUS_FF_OTEL_ENABLED=true
      - NEXUS_ENV=production
```

---

## Monitoring & Debugging

### Health Checks

**OTel Collector:**
```bash
curl http://localhost:13133
# Response: {"status":"Server available","upSince":"..."}
```

**Jaeger:**
```bash
curl http://localhost:14269
# Response: {"status":"Server available"}
```

### Logs

**OTel Collector logs:**
```bash
docker compose logs -f otel-collector
```

**NEXUS logs with OTel:**
```bash
docker compose logs -f nexus | grep -i otel
```

### zpages (Debug)

Access OTel Collector debug pages:
```
http://localhost:55679/debug/tracez
http://localhost:55679/debug/pipelinez
```

---

## Common Issues

### Issue: No traces in Jaeger

**Symptoms**: Jaeger UI shows no traces for `nexus-backend`

**Troubleshooting**:
1. Check OTel is enabled:
   ```bash
   docker compose exec nexus env | grep NEXUS_FF_OTEL_ENABLED
   # Should be: NEXUS_FF_OTEL_ENABLED=true
   ```

2. Check OTel Collector is running:
   ```bash
   docker compose ps otel-collector
   # State should be: Up
   ```

3. Check NEXUS can reach collector:
   ```bash
   docker compose exec nexus nc -zv otel-collector 4317
   # Should succeed
   ```

4. Check OTel Collector logs for errors:
   ```bash
   docker compose logs otel-collector | grep -i error
   ```

### Issue: OTel Collector OOM

**Symptoms**: Collector crashes with `exit code 137` (SIGKILL)

**Solution**: Increase memory limit in `otel-collector-config.yaml`:
```yaml
processors:
  memory_limiter:
    limit_mib: 1024  # Increased from 512
    spike_limit_mib: 256  # Increased from 128
```

### Issue: High CPU usage

**Symptoms**: OTel Collector uses >50% CPU

**Solution**: Adjust batch processor settings:
```yaml
processors:
  batch:
    timeout: 30s  # Increased from 10s
    send_batch_size: 2048  # Increased from 1024
```

---

## Production Deployment

### Recommendations

1. **Use OTLP gRPC** (not HTTP) for better performance
2. **Enable TLS** for production:
   ```yaml
   exporters:
     otlp/jaeger:
       endpoint: jaeger:4317
       tls:
         insecure: false
         cert_file: /etc/certs/client.crt
         key_file: /etc/certs/client.key
   ```

3. **Add Prometheus** for metrics storage (optional)
4. **Add Grafana** for dashboards (optional)
5. **Use persistent storage** for Jaeger spans:
   ```yaml
   jaeger:
     environment:
       - SPAN_STORAGE_TYPE=elasticsearch
       - ES_SERVER_URLS=http://elasticsearch:9200
   ```

6. **Set resource limits**:
   ```yaml
   otel-collector:
     deploy:
       resources:
         limits:
           cpus: '2'
           memory: 1G
         reservations:
           cpus: '1'
           memory: 512M
   ```

### Scaling

For high-volume deployments:

1. **Use multiple OTel Collectors** (load balancing)
2. **Enable tail-based sampling** (reduce storage)
3. **Use remote storage** (Cassandra, Elasticsearch)
4. **Configure retention policies**

---

## Useful Queries (Jaeger UI)

### Find slow LLM calls

**Service**: `nexus-backend`
**Operation**: `llm.anthropic` or `llm.gemini`
**Tags**: `error=true`
**Min Duration**: `5s`

### Find failed HiveMind executions

**Service**: `nexus-backend`
**Operation**: `hive_mind.execution`
**Tags**: `nexus.phase.success=false`

### Track token usage

**Service**: `nexus-backend`
**Operation**: `llm.*`
**Tags**: `gen_ai.usage.output_tokens>1000`

---

## References

- [OpenTelemetry Documentation](https://opentelemetry.io/docs/)
- [Jaeger Documentation](https://www.jaegertracing.io/docs/)
- [GenAI Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/)
- [OTel Collector Configuration](https://opentelemetry.io/docs/collector/configuration/)

---

**Last Updated**: 2026-02-17
**NEXUS Version**: V12.4.0
**Epic**: 4.3 - OpenTelemetry & Deployment
