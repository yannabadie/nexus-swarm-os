# OpenTelemetry Implementation Guide for NEXUS Multi-Agent System

**Version**: 1.0
**Date**: 2025-12-11
**Target**: NEXUS V8.3+ "TRUE HIVE MIND"

## Table of Contents

1. [Overview](#overview)
2. [Architecture Considerations](#architecture-considerations)
3. [OTLP Exporter Implementation](#otlp-exporter-implementation)
4. [GenAI Span Patterns](#genai-span-patterns)
5. [Token & Cost Tracking](#token--cost-tracking)
6. [Session Replay Capabilities](#session-replay-capabilities)
7. [Subprocess Context Propagation](#subprocess-context-propagation)
8. [Langfuse Integration](#langfuse-integration)
9. [Complete Implementation Example](#complete-implementation-example)
10. [Best Practices & Recommendations](#best-practices--recommendations)

---

## Overview

This guide provides concrete implementation patterns for integrating OpenTelemetry into NEXUS, a Python-based multi-agent orchestration system that uses subprocess-based LLM calls (CLI wrappers for Gemini/Claude).

### Key Challenges Addressed

- **Subprocess-based LLM calls**: Context propagation across process boundaries
- **Multi-agent collaboration**: Tracking spans across Gemini + Claude interactions
- **Token/cost tracking**: Capturing usage metrics for billing optimization
- **Session replay**: Reconstructing entire conversation flows for debugging
- **Swarm modes**: Tracing 6 different collaboration patterns (PARALLEL, SEQUENTIAL, etc.)

### Technology Stack

- **Python**: 3.11+
- **OpenTelemetry**: v1.37+ (GenAI semantic conventions)
- **Protocol**: OTLP over HTTP/protobuf (not gRPC for Langfuse compatibility)
- **Backend**: Langfuse (or any OTLP-compatible backend)

---

## Architecture Considerations

### Current NEXUS Architecture

```
NEXUS V8.3 Architecture:
+--------------------------------------------------------------+
| User Input                                                    |
|   ↓                                                           |
| FSM Orchestrator (orchestration_v7.py)                       |
|   +--> HiveMind Pipeline (7 phases) ---> SwarmBridge          |
|   |    Phase 1: ANALYSIS                                     |
|   |    Phase 2: DEBATE                                       |
|   |    Phase 3: ARCHITECTURE                                 |
|   |    Phase 4: EXECUTION (with Swarm delegation)            |
|   |    Phase 5: DIAGNOSIS                                    |
|   |    Phase 6: CONSOLIDATION                                |
|   |    Phase 7: COMPLETION                                   |
|   |                                                           |
|   +--> Swarm Engine (6 modes)                                |
|        - PARALLEL, SEQUENTIAL, LEAD_SUPPORT                  |
|        - PING_PONG, SPECIALIST, RED_BLUE                     |
|                                                               |
| LLM Drivers (CLI wrappers)                                   |
|   +--> Gemini Driver (JSON protocol)                          |
|   +--> Claude Driver (XML tools + natural language)           |
+--------------------------------------------------------------+
```

### Instrumentation Points

1. **Session Level**: Entire user request -> response cycle
2. **Phase Level**: Each HiveMind phase (ANALYSIS, DEBATE, etc.)
3. **Swarm Level**: Swarm mode execution (PARALLEL, SEQUENTIAL, etc.)
4. **Agent Level**: Individual Gemini/Claude invocations
5. **Tool Level**: Tool executions (read, write, bash, grep, etc.)

---

## OTLP Exporter Implementation

### 1. Installation

```bash
# Install core OpenTelemetry packages
pip install opentelemetry-api==1.37.0
pip install opentelemetry-sdk==1.37.0
pip install opentelemetry-exporter-otlp-proto-http==1.37.0

# For subprocess context propagation
pip install otel-extensions==0.2.4

# Optional: Auto-instrumentation for HTTP/requests
pip install opentelemetry-instrumentation-requests
```

### 2. Basic OTLP Setup

```python
# core/observability/otel_config.py
"""
OpenTelemetry configuration for NEXUS.
Initializes OTLP exporter with Langfuse-compatible settings.
"""

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION
from typing import Optional
import os


def initialize_otel(
    service_name: str = "nexus-multi-agent",
    service_version: str = "8.3.2",
    endpoint: Optional[str] = None,
    headers: Optional[dict] = None,
) -> trace.Tracer:
    """
    Initialize OpenTelemetry with OTLP HTTP exporter.

    Args:
        service_name: Name of the service (default: nexus-multi-agent)
        service_version: Version of the service
        endpoint: OTLP endpoint (default: http://localhost:4318/v1/traces)
        headers: Optional headers for authentication (e.g., Langfuse API keys)

    Returns:
        Configured Tracer instance
    """
    # Default endpoint (can be overridden by env var)
    if endpoint is None:
        endpoint = os.getenv(
            "OTEL_EXPORTER_OTLP_ENDPOINT",
            "http://localhost:4318/v1/traces"
        )

    # Configure resource with service metadata
    resource = Resource(attributes={
        SERVICE_NAME: service_name,
        SERVICE_VERSION: service_version,
        "deployment.environment": os.getenv("DEPLOYMENT_ENV", "development"),
        "nexus.branch": os.getenv("GIT_BRANCH", "unknown"),
    })

    # Create TracerProvider with resource
    provider = TracerProvider(resource=resource)

    # Configure OTLP exporter (HTTP/protobuf for Langfuse compatibility)
    otlp_exporter = OTLPSpanExporter(
        endpoint=endpoint,
        headers=headers or {},
        timeout=10,  # 10 second timeout
    )

    # Use BatchSpanProcessor for performance (async export)
    span_processor = BatchSpanProcessor(otlp_exporter)
    provider.add_span_processor(span_processor)

    # Set global tracer provider
    trace.set_tracer_provider(provider)

    # Return tracer instance
    return trace.get_tracer(__name__)


def get_tracer() -> trace.Tracer:
    """Get the global tracer instance."""
    return trace.get_tracer(__name__)


# Example: Initialize at application startup
# tracer = initialize_otel(
#     endpoint="https://cloud.langfuse.com/api/public/otel",
#     headers={
#         "Authorization": f"Bearer {LANGFUSE_PUBLIC_KEY}:{LANGFUSE_SECRET_KEY}"
#     }
# )
```

### 3. Environment Variable Configuration

```bash
# .env example for Langfuse
OTEL_EXPORTER_OTLP_ENDPOINT=https://cloud.langfuse.com/api/public/otel
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf  # NOT gRPC (Langfuse doesn't support it)
LANGFUSE_PUBLIC_KEY=pk-lf-xxx
LANGFUSE_SECRET_KEY=sk-lf-xxx
DEPLOYMENT_ENV=production
```

### 4. Langfuse-Specific Configuration

```python
# core/observability/langfuse_config.py
"""
Langfuse-specific OpenTelemetry configuration.
"""

from .otel_config import initialize_otel
import os


def initialize_langfuse_otel():
    """Initialize OpenTelemetry with Langfuse backend."""
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")

    if not public_key or not secret_key:
        raise ValueError("LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY must be set")

    # Langfuse uses HTTP/protobuf, not gRPC
    endpoint = os.getenv(
        "LANGFUSE_OTEL_ENDPOINT",
        "https://cloud.langfuse.com/api/public/otel"
    )

    # Authentication via headers
    headers = {
        "Authorization": f"Bearer {public_key}:{secret_key}"
    }

    return initialize_otel(
        service_name="nexus-hive-mind",
        service_version=os.getenv("NEXUS_VERSION", "8.3.2"),
        endpoint=endpoint,
        headers=headers,
    )
```

---

## GenAI Span Patterns

### 1. GenAI Semantic Conventions (v1.37+)

OpenTelemetry defines standardized attributes for GenAI spans:

| Attribute | Type | Description | Example |
|-----------|------|-------------|---------|
| `gen_ai.operation.name` | string | Operation type | `invoke_agent`, `chat`, `embeddings` |
| `gen_ai.request.model` | string | Model name | `claude-opus-4-5-20251101` |
| `gen_ai.provider.name` | string | Provider name | `anthropic`, `google` |
| `gen_ai.conversation.id` | string | Session/conversation ID | `session-abc123` |
| `gen_ai.agent.name` | string | Agent name | `nexus-hive-mind` |
| `gen_ai.agent.id` | string | Agent unique ID | `agent-gemini-001` |
| `gen_ai.usage.input_tokens` | int | Prompt tokens | 1024 |
| `gen_ai.usage.output_tokens` | int | Completion tokens | 512 |
| `gen_ai.usage.cost` | float | Total cost in USD | 0.0234 |

### 2. Span Naming Best Practices

```python
# Recommended span names:
# Format: "{operation} {model}"

"invoke_agent claude-opus-4-5"
"chat gemini-3-pro-preview"
"embeddings text-embedding-004"
"tool_execution bash"
```

### 3. Implementation: LLM Driver Spans

```python
# core/drivers/claude_driver_instrumented.py
"""
Instrumented Claude driver with OpenTelemetry GenAI spans.
"""

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from typing import Dict, Any
import json

tracer = trace.get_tracer(__name__)


class InstrumentedClaudeDriver:
    """Claude driver with OpenTelemetry instrumentation."""

    def __init__(self, model: str = "claude-opus-4-5-20251101"):
        self.model = model
        self.provider = "anthropic"

    def invoke(
        self,
        prompt: str,
        session_id: str,
        temperature: float = 1.0,
        max_tokens: int = 4096,
    ) -> Dict[str, Any]:
        """
        Invoke Claude with OpenTelemetry tracing.

        Creates a GenAI span following OpenTelemetry semantic conventions.
        """
        # Create GenAI span
        with tracer.start_as_current_span(
            f"invoke_agent {self.model}",
            kind=trace.SpanKind.CLIENT,  # External API call
        ) as span:
            try:
                # Set GenAI semantic convention attributes
                span.set_attribute("gen_ai.operation.name", "invoke_agent")
                span.set_attribute("gen_ai.request.model", self.model)
                span.set_attribute("gen_ai.provider.name", self.provider)
                span.set_attribute("gen_ai.conversation.id", session_id)
                span.set_attribute("gen_ai.agent.name", "claude-agent")
                span.set_attribute("gen_ai.agent.id", f"agent-claude-{session_id}")

                # Request parameters
                span.set_attribute("gen_ai.request.temperature", temperature)
                span.set_attribute("gen_ai.request.max_tokens", max_tokens)

                # Record input (optional: may contain PII - filter if needed)
                span.set_attribute("gen_ai.input.prompt", prompt[:500])  # Truncate

                # Execute actual LLM call (subprocess-based)
                result = self._execute_subprocess_call(prompt, temperature, max_tokens)

                # Record output
                span.set_attribute("gen_ai.output.completion", result["content"][:500])

                # Token usage tracking
                span.set_attribute("gen_ai.usage.input_tokens", result["usage"]["input_tokens"])
                span.set_attribute("gen_ai.usage.output_tokens", result["usage"]["output_tokens"])

                # Cost calculation (example rates for Claude Opus 4.5)
                input_cost = result["usage"]["input_tokens"] * 0.000015  # $15/1M tokens
                output_cost = result["usage"]["output_tokens"] * 0.000075  # $75/1M tokens
                total_cost = input_cost + output_cost
                span.set_attribute("gen_ai.usage.cost", total_cost)

                # Add Langfuse-specific attributes for cost breakdown
                span.set_attribute("langfuse.observation.cost_details", json.dumps({
                    "input_cost": input_cost,
                    "output_cost": output_cost,
                    "model": self.model,
                }))

                # Mark span as successful
                span.set_status(Status(StatusCode.OK))

                return result

            except Exception as e:
                # Record error
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.set_attribute("error.type", type(e).__name__)
                span.set_attribute("error.message", str(e))
                span.record_exception(e)
                raise

    def _execute_subprocess_call(self, prompt: str, temperature: float, max_tokens: int) -> Dict[str, Any]:
        """Execute subprocess call to Claude CLI (implementation detail)."""
        # Actual subprocess execution logic here
        # For now, return mock response
        return {
            "content": "Mock response from Claude",
            "usage": {
                "input_tokens": 1024,
                "output_tokens": 512,
            }
        }
```

### 4. Implementation: Gemini Driver Spans

```python
# core/drivers/gemini_driver_instrumented.py
"""
Instrumented Gemini driver with OpenTelemetry GenAI spans.
"""

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from typing import Dict, Any
import json

tracer = trace.get_tracer(__name__)


class InstrumentedGeminiDriver:
    """Gemini driver with OpenTelemetry instrumentation."""

    def __init__(self, model: str = "gemini-3-pro-preview"):
        self.model = model
        self.provider = "google"

    def invoke(
        self,
        message: Dict[str, Any],
        session_id: str,
    ) -> Dict[str, Any]:
        """
        Invoke Gemini with OpenTelemetry tracing.

        Gemini uses JSON protocol (LightMessageV7/HeavyMessageV7).
        """
        with tracer.start_as_current_span(
            f"invoke_agent {self.model}",
            kind=trace.SpanKind.CLIENT,
        ) as span:
            try:
                # GenAI semantic conventions
                span.set_attribute("gen_ai.operation.name", "invoke_agent")
                span.set_attribute("gen_ai.request.model", self.model)
                span.set_attribute("gen_ai.provider.name", self.provider)
                span.set_attribute("gen_ai.conversation.id", session_id)
                span.set_attribute("gen_ai.agent.name", "gemini-agent")
                span.set_attribute("gen_ai.agent.id", f"agent-gemini-{session_id}")

                # NEXUS-specific: Message type (LightMessageV7 vs HeavyMessageV7)
                span.set_attribute("nexus.message.type", message.get("type", "unknown"))
                span.set_attribute("nexus.message.phase", message.get("phase", "unknown"))

                # Record input (structured JSON message)
                span.set_attribute("gen_ai.input.messages", json.dumps([{
                    "role": "user",
                    "content": str(message.get("payload", ""))[:500]
                }]))

                # Execute subprocess call
                result = self._execute_subprocess_call(message)

                # Token usage
                span.set_attribute("gen_ai.usage.input_tokens", result["usage"]["input_tokens"])
                span.set_attribute("gen_ai.usage.output_tokens", result["usage"]["output_tokens"])

                # Cost calculation (Gemini 3 Pro pricing)
                input_cost = result["usage"]["input_tokens"] * 0.000003  # $3/1M tokens
                output_cost = result["usage"]["output_tokens"] * 0.000015  # $15/1M tokens
                total_cost = input_cost + output_cost
                span.set_attribute("gen_ai.usage.cost", total_cost)

                span.set_status(Status(StatusCode.OK))
                return result

            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.set_attribute("error.type", type(e).__name__)
                span.record_exception(e)
                raise

    def _execute_subprocess_call(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Execute subprocess call to Gemini CLI."""
        return {
            "content": "Mock response from Gemini",
            "usage": {"input_tokens": 800, "output_tokens": 400}
        }
```

---

## Token & Cost Tracking

### 1. Centralized Cost Tracking Service

```python
# core/observability/cost_tracker.py
"""
Centralized cost tracking service for NEXUS.
Aggregates token usage and calculates costs across all agents.
"""

from dataclasses import dataclass
from typing import Dict
from opentelemetry import trace
import json

tracer = trace.get_tracer(__name__)


@dataclass
class ModelPricing:
    """Pricing information for LLM models (per 1M tokens)."""
    input_price: float  # USD per 1M input tokens
    output_price: float  # USD per 1M output tokens


# Pricing table (2025 rates)
MODEL_PRICING: Dict[str, ModelPricing] = {
    "claude-opus-4-5-20251101": ModelPricing(15.0, 75.0),
    "claude-sonnet-4-5-20250929": ModelPricing(3.0, 15.0),
    "gemini-3-pro-preview": ModelPricing(3.0, 15.0),
    "gemini-flash-3-preview": ModelPricing(0.3, 1.5),
}


class CostTracker:
    """Tracks costs across all LLM calls in a session."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost = 0.0
        self.calls_by_model: Dict[str, int] = {}

    def record_usage(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        span: trace.Span = None,
    ) -> float:
        """
        Record token usage and calculate cost.

        Args:
            model: Model name
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            span: Optional span to attach cost attributes to

        Returns:
            Cost in USD for this call
        """
        pricing = MODEL_PRICING.get(model, ModelPricing(0.0, 0.0))

        # Calculate cost (pricing is per 1M tokens)
        input_cost = (input_tokens / 1_000_000) * pricing.input_price
        output_cost = (output_tokens / 1_000_000) * pricing.output_price
        call_cost = input_cost + output_cost

        # Update totals
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_cost += call_cost
        self.calls_by_model[model] = self.calls_by_model.get(model, 0) + 1

        # Attach to span if provided
        if span:
            span.set_attribute("gen_ai.usage.cost", call_cost)
            span.set_attribute("langfuse.observation.cost_details", json.dumps({
                "input_cost": input_cost,
                "output_cost": output_cost,
                "model": model,
                "pricing": {
                    "input_per_1m": pricing.input_price,
                    "output_per_1m": pricing.output_price,
                }
            }))

        return call_cost

    def get_summary(self) -> Dict[str, Any]:
        """Get cost summary for the session."""
        return {
            "session_id": self.session_id,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cost_usd": round(self.total_cost, 4),
            "calls_by_model": self.calls_by_model,
        }

    def record_to_span(self, span: trace.Span):
        """Record session summary to a span."""
        summary = self.get_summary()
        span.set_attribute("nexus.session.total_cost", summary["total_cost_usd"])
        span.set_attribute("nexus.session.total_tokens",
                          summary["total_input_tokens"] + summary["total_output_tokens"])
        span.set_attribute("nexus.session.calls_by_model", json.dumps(summary["calls_by_model"]))
```

### 2. Integration Example

```python
# Usage in orchestrator
from core.observability.cost_tracker import CostTracker

def execute_session(session_id: str):
    """Execute a NEXUS session with cost tracking."""
    cost_tracker = CostTracker(session_id)

    with tracer.start_as_current_span("nexus_session") as session_span:
        session_span.set_attribute("nexus.session.id", session_id)

        # Execute LLM calls...
        # Each call records usage
        cost_tracker.record_usage(
            model="claude-opus-4-5-20251101",
            input_tokens=1024,
            output_tokens=512,
            span=trace.get_current_span()
        )

        # At end, record summary
        cost_tracker.record_to_span(session_span)
```

---

## Session Replay Capabilities

### 1. Session Structure for Replay

To enable session replay, we need to capture:
- Conversation flow (user -> agents -> tools -> agents -> user)
- Full message history (prompts, completions)
- Tool calls and results
- Agent negotiations (Swarm mode selection)
- Errors and recoveries

```python
# core/observability/session_replay.py
"""
Session replay capabilities for NEXUS.
Captures full conversation flow for debugging and analysis.
"""

from opentelemetry import trace
from typing import Dict, Any, List
import json

tracer = trace.get_tracer(__name__)


class SessionRecorder:
    """Records session events for replay."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.events: List[Dict[str, Any]] = []

    def record_user_input(self, user_input: str, span: trace.Span = None):
        """Record user input."""
        event = {
            "type": "user_input",
            "content": user_input,
            "timestamp": self._get_timestamp(),
        }
        self.events.append(event)

        if span:
            span.add_event("user_input", attributes={
                "user.input": user_input,
            })

    def record_agent_response(
        self,
        agent: str,
        response: str,
        tokens: Dict[str, int],
        span: trace.Span = None
    ):
        """Record agent response."""
        event = {
            "type": "agent_response",
            "agent": agent,
            "content": response,
            "tokens": tokens,
            "timestamp": self._get_timestamp(),
        }
        self.events.append(event)

        if span:
            span.add_event("agent_response", attributes={
                "agent.name": agent,
                "agent.response": response[:500],
                "agent.input_tokens": tokens.get("input", 0),
                "agent.output_tokens": tokens.get("output", 0),
            })

    def record_tool_call(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        tool_output: str,
        span: trace.Span = None
    ):
        """Record tool execution."""
        event = {
            "type": "tool_call",
            "tool": tool_name,
            "input": tool_input,
            "output": tool_output,
            "timestamp": self._get_timestamp(),
        }
        self.events.append(event)

        if span:
            span.add_event("tool_execution", attributes={
                "tool.name": tool_name,
                "tool.input": json.dumps(tool_input),
                "tool.output": tool_output[:500],
            })

    def record_swarm_negotiation(
        self,
        mode_proposed: str,
        mode_selected: str,
        negotiation_turns: int,
        span: trace.Span = None
    ):
        """Record Swarm mode negotiation."""
        event = {
            "type": "swarm_negotiation",
            "mode_proposed": mode_proposed,
            "mode_selected": mode_selected,
            "negotiation_turns": negotiation_turns,
            "timestamp": self._get_timestamp(),
        }
        self.events.append(event)

        if span:
            span.add_event("swarm_negotiation", attributes={
                "swarm.mode_proposed": mode_proposed,
                "swarm.mode_selected": mode_selected,
                "swarm.negotiation_turns": negotiation_turns,
            })

    def get_replay_data(self) -> Dict[str, Any]:
        """Get full session replay data."""
        return {
            "session_id": self.session_id,
            "events": self.events,
            "event_count": len(self.events),
        }

    def export_to_span(self, span: trace.Span):
        """Export session replay data to a span."""
        replay_data = self.get_replay_data()
        span.set_attribute("nexus.session.replay_data", json.dumps(replay_data))
        span.set_attribute("nexus.session.event_count", replay_data["event_count"])

    def _get_timestamp(self) -> str:
        """Get current timestamp."""
        from datetime import datetime
        return datetime.utcnow().isoformat()
```

### 2. Langfuse Session Tracking

Langfuse natively supports session tracking via the `gen_ai.conversation.id` attribute:

```python
# core/observability/langfuse_session.py
"""
Langfuse-specific session tracking.
"""

from opentelemetry import trace

tracer = trace.get_tracer(__name__)


def create_session_span(session_id: str, user_id: str = None):
    """
    Create a root session span for Langfuse.

    Langfuse groups all spans with the same gen_ai.conversation.id
    into a session view for replay.
    """
    with tracer.start_as_current_span(
        f"nexus_session_{session_id}",
        kind=trace.SpanKind.SERVER,
    ) as span:
        # Session identifiers
        span.set_attribute("gen_ai.conversation.id", session_id)
        span.set_attribute("nexus.session.id", session_id)

        # User tracking (if available)
        if user_id:
            span.set_attribute("enduser.id", user_id)

        # NEXUS-specific metadata
        span.set_attribute("nexus.version", "8.3.2")
        span.set_attribute("nexus.mode", "hive_mind")

        return span
```

### 3. Complete Session Flow Example

```python
# Example: Traced session with replay
def execute_traced_session(user_input: str, session_id: str):
    """Execute a fully traced NEXUS session."""
    recorder = SessionRecorder(session_id)
    cost_tracker = CostTracker(session_id)

    with tracer.start_as_current_span("nexus_session") as session_span:
        # Session metadata
        session_span.set_attribute("gen_ai.conversation.id", session_id)
        session_span.set_attribute("nexus.session.id", session_id)

        try:
            # 1. Record user input
            recorder.record_user_input(user_input, session_span)

            # 2. Phase 1: ANALYSIS (both agents analyze)
            with tracer.start_as_current_span("phase_analysis") as phase_span:
                phase_span.set_attribute("nexus.phase", "ANALYSIS")

                # Gemini analysis
                gemini_result = gemini_driver.invoke({...}, session_id)
                recorder.record_agent_response(
                    "gemini", gemini_result["content"],
                    gemini_result["usage"], phase_span
                )
                cost_tracker.record_usage(
                    "gemini-3-pro-preview",
                    gemini_result["usage"]["input_tokens"],
                    gemini_result["usage"]["output_tokens"],
                    phase_span
                )

                # Claude analysis
                claude_result = claude_driver.invoke(user_input, session_id)
                recorder.record_agent_response(
                    "claude", claude_result["content"],
                    claude_result["usage"], phase_span
                )
                cost_tracker.record_usage(
                    "claude-opus-4-5-20251101",
                    claude_result["usage"]["input_tokens"],
                    claude_result["usage"]["output_tokens"],
                    phase_span
                )

            # 3. Phase 4: EXECUTION (with tool calls)
            with tracer.start_as_current_span("phase_execution") as phase_span:
                phase_span.set_attribute("nexus.phase", "EXECUTION")

                # Tool call (nested span)
                with tracer.start_as_current_span("tool_read_file") as tool_span:
                    tool_span.set_attribute("tool.name", "read")
                    tool_span.set_attribute("tool.file_path", "/path/to/file.py")

                    result = execute_tool("read", {"file_path": "/path/to/file.py"})

                    recorder.record_tool_call(
                        "read",
                        {"file_path": "/path/to/file.py"},
                        result,
                        tool_span
                    )

            # 4. Export session summary
            recorder.export_to_span(session_span)
            cost_tracker.record_to_span(session_span)

            session_span.set_status(trace.Status(trace.StatusCode.OK))

        except Exception as e:
            session_span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
            session_span.record_exception(e)
            raise
```

---

## Subprocess Context Propagation

### Challenge: NEXUS uses CLI wrappers for LLM calls

NEXUS invokes Gemini and Claude via subprocess (CLI wrappers), which breaks OpenTelemetry context propagation by default.

### Solution: `otel-extensions` with TRACEPARENT Environment Variable

The W3C Trace Context standard defines the `TRACEPARENT` environment variable for propagating trace context across process boundaries.

```python
# core/observability/subprocess_propagation.py
"""
Context propagation for subprocess-based LLM calls.
Uses otel-extensions to inject TRACEPARENT into subprocess environment.
"""

from opentelemetry import trace
from otel_extensions import TraceContextCarrier
from subprocess import Popen, PIPE
from typing import List, Dict, Any
import json

tracer = trace.get_tracer(__name__)


class InstrumentedSubprocessExecutor:
    """Execute subprocess calls with OpenTelemetry context propagation."""

    def execute_cli_command(
        self,
        command: List[str],
        span_name: str,
        span_attributes: Dict[str, Any] = None,
    ) -> str:
        """
        Execute CLI command with context propagation.

        Args:
            command: Command and arguments (e.g., ["claude", "chat", "Hello"])
            span_name: Name for the span
            span_attributes: Optional attributes to set on the span

        Returns:
            Command output (stdout)
        """
        with tracer.start_as_current_span(span_name) as span:
            # Set attributes
            if span_attributes:
                for key, value in span_attributes.items():
                    span.set_attribute(key, value)

            # Inject trace context into environment
            # This sets the TRACEPARENT env var with current trace context
            TraceContextCarrier.inject_to_env()

            try:
                # Execute subprocess (inherits TRACEPARENT)
                process = Popen(
                    command,
                    stdout=PIPE,
                    stderr=PIPE,
                    text=True,
                )

                stdout, stderr = process.communicate()

                if process.returncode != 0:
                    span.set_status(trace.Status(trace.StatusCode.ERROR, stderr))
                    span.set_attribute("error.message", stderr)
                    raise RuntimeError(f"Command failed: {stderr}")

                span.set_status(trace.Status(trace.StatusCode.OK))
                return stdout

            except Exception as e:
                span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                span.record_exception(e)
                raise


# Example usage in Claude driver
class ClaudeDriverWithPropagation:
    """Claude driver with subprocess context propagation."""

    def __init__(self):
        self.executor = InstrumentedSubprocessExecutor()

    def invoke(self, prompt: str, session_id: str) -> Dict[str, Any]:
        """Invoke Claude CLI with context propagation."""
        output = self.executor.execute_cli_command(
            command=["claude", "chat", prompt],
            span_name="invoke_agent claude-opus-4-5",
            span_attributes={
                "gen_ai.operation.name": "invoke_agent",
                "gen_ai.request.model": "claude-opus-4-5-20251101",
                "gen_ai.provider.name": "anthropic",
                "gen_ai.conversation.id": session_id,
            }
        )

        # Parse output and return
        return json.loads(output)
```

### Alternative: Manual Context Injection

If the CLI wrapper supports custom headers/metadata:

```python
# core/observability/manual_propagation.py
"""
Manual context propagation for CLI wrappers that support metadata.
"""

from opentelemetry import trace
from opentelemetry.propagate import inject
from typing import Dict


def inject_trace_context_to_metadata() -> Dict[str, str]:
    """
    Extract current trace context as metadata dictionary.

    Returns:
        Dictionary with traceparent/tracestate headers
    """
    carrier = {}
    inject(carrier)  # Injects W3C Trace Context headers
    return carrier


# Example usage:
def invoke_claude_with_metadata(prompt: str) -> str:
    """Invoke Claude CLI with trace context metadata."""
    context_headers = inject_trace_context_to_metadata()

    # If CLI supports --header flags:
    command = [
        "claude", "chat",
        "--header", f"traceparent:{context_headers.get('traceparent', '')}",
        "--header", f"tracestate:{context_headers.get('tracestate', '')}",
        prompt
    ]

    # Execute command...
    return execute_command(command)
```

---

## Langfuse Integration

### 1. Why Langfuse?

- **Native OpenTelemetry support**: Accepts OTLP spans via HTTP
- **GenAI-specific UI**: Built for LLM observability (prompts, completions, tokens, costs)
- **Session replay**: Groups spans by `gen_ai.conversation.id` for session views
- **Multi-agent support**: Tracks agent collaboration and tool calls
- **Cost analytics**: Automatic cost calculation from token usage

### 2. Setup

```bash
# Install Langfuse SDK (optional - can use pure OTel)
pip install langfuse
```

### 3. Configuration

```python
# core/observability/langfuse_config.py
"""
Langfuse integration for NEXUS.
"""

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
import os


def initialize_langfuse():
    """Initialize OpenTelemetry with Langfuse backend."""

    # Langfuse credentials
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    endpoint = os.getenv("LANGFUSE_OTEL_ENDPOINT", "https://cloud.langfuse.com/api/public/otel")

    if not public_key or not secret_key:
        raise ValueError("LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY required")

    # Resource configuration
    resource = Resource(attributes={
        SERVICE_NAME: "nexus-hive-mind",
        "service.version": "8.3.2",
        "deployment.environment": os.getenv("DEPLOYMENT_ENV", "production"),
    })

    # Tracer provider
    provider = TracerProvider(resource=resource)

    # OTLP exporter (HTTP/protobuf - NOT gRPC)
    exporter = OTLPSpanExporter(
        endpoint=endpoint,
        headers={
            "Authorization": f"Bearer {public_key}:{secret_key}"
        },
        timeout=10,
    )

    # Batch span processor
    processor = BatchSpanProcessor(exporter)
    provider.add_span_processor(processor)

    # Set global provider
    trace.set_tracer_provider(provider)

    return trace.get_tracer(__name__)
```

### 4. Langfuse-Specific Attributes

Langfuse supports additional attributes beyond OpenTelemetry standard:

```python
# Langfuse extensions
span.set_attribute("langfuse.observation.cost_details", json.dumps({
    "input_cost": 0.015,
    "output_cost": 0.038,
    "model": "claude-opus-4-5-20251101",
}))

# User tracking
span.set_attribute("enduser.id", "user-123")

# Session tracking (native OTel)
span.set_attribute("gen_ai.conversation.id", "session-abc")

# Prompt linking (Langfuse feature)
span.set_attribute("langfuse.prompt.id", "prompt-template-v2")
```

### 5. Langfuse Dashboard Features

Once integrated, Langfuse provides:
- **Session replay**: View entire conversation flows
- **Token analytics**: Track usage by model, user, session
- **Cost monitoring**: Real-time cost tracking with alerts
- **Prompt management**: Version and compare prompts
- **Agent tracing**: Visualize multi-agent collaboration
- **Error tracking**: Debug failed LLM calls

---

## Complete Implementation Example

### Full Orchestrator with OpenTelemetry

```python
# core/orchestration_v8_instrumented.py
"""
NEXUS V8 Orchestrator with complete OpenTelemetry instrumentation.
"""

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from core.observability.otel_config import initialize_otel
from core.observability.cost_tracker import CostTracker
from core.observability.session_replay import SessionRecorder
from core.drivers.claude_driver_instrumented import InstrumentedClaudeDriver
from core.drivers.gemini_driver_instrumented import InstrumentedGeminiDriver
from typing import Dict, Any
import uuid

# Initialize OpenTelemetry (do this once at startup)
tracer = initialize_otel(
    service_name="nexus-hive-mind",
    service_version="8.3.2",
)


class InstrumentedNEXUSOrchestrator:
    """
    NEXUS Orchestrator with full OpenTelemetry instrumentation.

    Traces:
    - Session-level spans (entire user request)
    - Phase-level spans (HiveMind 7 phases)
    - Agent-level spans (Gemini/Claude invocations)
    - Tool-level spans (tool executions)
    - Swarm-level spans (collaboration modes)
    """

    def __init__(self):
        self.claude_driver = InstrumentedClaudeDriver()
        self.gemini_driver = InstrumentedGeminiDriver()

    def execute_session(self, user_input: str, user_id: str = None) -> Dict[str, Any]:
        """
        Execute a full NEXUS session with OpenTelemetry tracing.

        Args:
            user_input: User's request
            user_id: Optional user identifier

        Returns:
            Session result
        """
        session_id = str(uuid.uuid4())
        cost_tracker = CostTracker(session_id)
        recorder = SessionRecorder(session_id)

        # Root span: Entire session
        with tracer.start_as_current_span(
            f"nexus_session",
            kind=trace.SpanKind.SERVER,
        ) as session_span:
            try:
                # Session metadata
                session_span.set_attribute("gen_ai.conversation.id", session_id)
                session_span.set_attribute("nexus.session.id", session_id)
                session_span.set_attribute("nexus.version", "8.3.2")
                session_span.set_attribute("nexus.mode", "hive_mind")

                if user_id:
                    session_span.set_attribute("enduser.id", user_id)

                # Record user input
                recorder.record_user_input(user_input, session_span)
                session_span.add_event("user_input_received", {
                    "input.length": len(user_input)
                })

                # HiveMind Pipeline: 7 phases
                analysis_result = self._execute_phase_1_analysis(
                    user_input, session_id, cost_tracker, recorder
                )

                debate_result = self._execute_phase_2_debate(
                    analysis_result, session_id, cost_tracker, recorder
                )

                architecture_result = self._execute_phase_3_architecture(
                    debate_result, session_id, cost_tracker, recorder
                )

                execution_result = self._execute_phase_4_execution(
                    architecture_result, session_id, cost_tracker, recorder
                )

                # ... phases 5, 6, 7 ...

                # Final result
                final_result = {
                    "session_id": session_id,
                    "result": execution_result,
                    "cost_summary": cost_tracker.get_summary(),
                    "replay_data": recorder.get_replay_data(),
                }

                # Record summary to span
                cost_tracker.record_to_span(session_span)
                recorder.export_to_span(session_span)

                session_span.set_status(Status(StatusCode.OK))
                session_span.add_event("session_completed")

                return final_result

            except Exception as e:
                session_span.set_status(Status(StatusCode.ERROR, str(e)))
                session_span.set_attribute("error.type", type(e).__name__)
                session_span.record_exception(e)
                raise

    def _execute_phase_1_analysis(
        self,
        user_input: str,
        session_id: str,
        cost_tracker: CostTracker,
        recorder: SessionRecorder,
    ) -> Dict[str, Any]:
        """Phase 1: ANALYSIS - Both agents analyze independently."""
        with tracer.start_as_current_span(
            "phase_analysis",
            kind=trace.SpanKind.INTERNAL,
        ) as phase_span:
            phase_span.set_attribute("nexus.phase", "ANALYSIS")
            phase_span.set_attribute("nexus.phase.number", 1)

            # Gemini analysis
            gemini_result = self.gemini_driver.invoke({
                "type": "LightMessageV7",
                "phase": "ANALYSIS",
                "payload": user_input,
            }, session_id)

            recorder.record_agent_response(
                "gemini",
                gemini_result["content"],
                gemini_result["usage"],
                phase_span
            )

            cost_tracker.record_usage(
                "gemini-3-pro-preview",
                gemini_result["usage"]["input_tokens"],
                gemini_result["usage"]["output_tokens"],
                trace.get_current_span()
            )

            # Claude analysis
            claude_result = self.claude_driver.invoke(
                user_input,
                session_id,
            )

            recorder.record_agent_response(
                "claude",
                claude_result["content"],
                claude_result["usage"],
                phase_span
            )

            cost_tracker.record_usage(
                "claude-opus-4-5-20251101",
                claude_result["usage"]["input_tokens"],
                claude_result["usage"]["output_tokens"],
                trace.get_current_span()
            )

            phase_span.set_status(Status(StatusCode.OK))

            return {
                "gemini_analysis": gemini_result,
                "claude_analysis": claude_result,
            }

    def _execute_phase_4_execution(
        self,
        architecture: Dict[str, Any],
        session_id: str,
        cost_tracker: CostTracker,
        recorder: SessionRecorder,
    ) -> Dict[str, Any]:
        """Phase 4: EXECUTION - Execute plan with tool calls."""
        with tracer.start_as_current_span(
            "phase_execution",
            kind=trace.SpanKind.INTERNAL,
        ) as phase_span:
            phase_span.set_attribute("nexus.phase", "EXECUTION")
            phase_span.set_attribute("nexus.phase.number", 4)

            # Example: Tool call
            with tracer.start_as_current_span(
                "tool_read_file",
                kind=trace.SpanKind.CLIENT,
            ) as tool_span:
                tool_span.set_attribute("tool.name", "read")
                tool_span.set_attribute("tool.file_path", "/path/to/file.py")

                # Execute tool
                result = self._execute_tool("read", {
                    "file_path": "/path/to/file.py"
                })

                tool_span.set_attribute("tool.result.length", len(result))

                recorder.record_tool_call(
                    "read",
                    {"file_path": "/path/to/file.py"},
                    result,
                    tool_span
                )

            phase_span.set_status(Status(StatusCode.OK))
            return {"status": "completed"}

    def _execute_tool(self, tool_name: str, tool_input: Dict[str, Any]) -> str:
        """Execute a tool (mock implementation)."""
        # Actual tool execution logic
        return "Tool result"


# Example usage
if __name__ == "__main__":
    orchestrator = InstrumentedNEXUSOrchestrator()
    result = orchestrator.execute_session(
        user_input="Analyze the authentication system",
        user_id="user-123"
    )
    print(f"Session completed: {result['session_id']}")
    print(f"Total cost: ${result['cost_summary']['total_cost_usd']}")
```

---

## Best Practices & Recommendations

### 1. Span Hierarchy Design

**Recommended hierarchy for NEXUS:**

```
nexus_session (root)
+-- phase_analysis
|   +-- invoke_agent gemini-3-pro
|   +-- invoke_agent claude-opus-4-5
+-- phase_debate
|   +-- invoke_agent gemini-3-pro
|   +-- invoke_agent claude-opus-4-5
+-- phase_architecture
|   +-- invoke_agent claude-opus-4-5
+-- phase_execution
|   +-- swarm_parallel
|   |   +-- invoke_agent gemini-3-pro
|   |   +-- invoke_agent claude-opus-4-5
|   +-- tool_read_file
|   +-- tool_grep
|   +-- tool_write_file
+-- phase_consolidation
    +-- invoke_agent claude-opus-4-5
```

### 2. Attribute Naming Convention

Use consistent naming for custom attributes:

```python
# NEXUS-specific attributes
"nexus.session.id"
"nexus.phase"
"nexus.phase.number"
"nexus.swarm.mode"
"nexus.agent.name"
"nexus.version"

# Follow GenAI semantic conventions
"gen_ai.operation.name"
"gen_ai.request.model"
"gen_ai.provider.name"
"gen_ai.conversation.id"
"gen_ai.usage.input_tokens"
"gen_ai.usage.output_tokens"
"gen_ai.usage.cost"
```

### 3. Privacy & Security

```python
# Filter PII before recording
def sanitize_prompt(prompt: str) -> str:
    """Remove PII from prompts before recording."""
    # Implement PII filtering (emails, phone numbers, etc.)
    return filtered_prompt

# Truncate long content
span.set_attribute("gen_ai.input.prompt", prompt[:500])  # Truncate to 500 chars
```

### 4. Performance Considerations

```python
# Use BatchSpanProcessor (async export)
from opentelemetry.sdk.trace.export import BatchSpanProcessor

processor = BatchSpanProcessor(
    exporter,
    max_queue_size=2048,
    schedule_delay_millis=5000,  # Export every 5 seconds
    export_timeout_millis=30000,
    max_export_batch_size=512,
)

# Use sampling for high-volume systems
from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

sampler = TraceIdRatioBased(0.1)  # Sample 10% of traces
provider = TracerProvider(sampler=sampler)
```

### 5. Error Handling

```python
# Always record errors on spans
try:
    result = execute_llm_call()
except Exception as e:
    span.set_status(Status(StatusCode.ERROR, str(e)))
    span.set_attribute("error.type", type(e).__name__)
    span.set_attribute("error.message", str(e))
    span.record_exception(e)  # Records full stack trace
    raise
```

### 6. Testing

```python
# core/observability/test_otel.py
"""
Test OpenTelemetry instrumentation.
"""

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, ConsoleSpanExporter

def test_instrumentation():
    """Test that spans are created correctly."""
    # Use console exporter for testing
    provider = TracerProvider()
    processor = SimpleSpanProcessor(ConsoleSpanExporter())
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)

    tracer = trace.get_tracer(__name__)

    with tracer.start_as_current_span("test_span") as span:
        span.set_attribute("test.attribute", "value")
        print("Span created successfully")

if __name__ == "__main__":
    test_instrumentation()
```

### 7. Migration Strategy

**Phase 1: Core instrumentation**
- Instrument FSM orchestrator (session-level spans)
- Instrument LLM drivers (agent-level spans)
- Set up OTLP exporter

**Phase 2: Detailed tracing**
- Add phase-level spans (HiveMind 7 phases)
- Add tool execution spans
- Implement cost tracking

**Phase 3: Advanced features**
- Add Swarm mode tracing
- Implement session replay
- Add subprocess context propagation

**Phase 4: Optimization**
- Add sampling strategies
- Implement custom metrics
- Set up dashboards and alerts

### 8. Monitoring Checklist

Track these key metrics in production:

- **Latency**: `phase_execution.duration`, `invoke_agent.duration`
- **Cost**: `gen_ai.usage.cost`, `nexus.session.total_cost`
- **Tokens**: `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`
- **Error rate**: `span.status == ERROR`
- **Agent collaboration**: `nexus.swarm.mode`, `nexus.swarm.negotiation_turns`
- **Tool usage**: `tool.name`, `tool.execution_count`

---

## References & Sources

### OpenTelemetry Documentation
- [AI Agent Observability - OpenTelemetry](https://opentelemetry.io/blog/2025/ai-agent-observability/)
- [OpenTelemetry for AI Systems - Uptrace](https://uptrace.dev/blog/opentelemetry-ai-systems)
- [Python Documentation - OpenTelemetry](https://opentelemetry.io/docs/languages/python/)
- [OTLP Exporters - OpenTelemetry Python](https://opentelemetry-python.readthedocs.io/en/latest/exporter/otlp/otlp.html)

### GenAI Semantic Conventions
- [Semantic Conventions for GenAI Spans - OpenTelemetry](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/)
- [GenAI Agent Spans - OpenTelemetry](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/)
- [GenAI Metrics - OpenTelemetry](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-metrics/)
- [Datadog LLM Observability GenAI Support](https://www.datadoghq.com/blog/llm-otel-semantic-convention/)

### Token & Cost Tracking
- [LLM Observability Introduction - OpenTelemetry](https://opentelemetry.io/blog/2024/llm-observability/)
- [Visualizing LLM Performance - Traceloop](https://www.traceloop.com/blog/visualizing-llm-performance-with-opentelemetry-tools-for-tracing-cost-and-latency)
- [LLM Observability Guide - Grafana](https://grafana.com/blog/2024/07/18/a-complete-guide-to-llm-observability-with-opentelemetry-and-grafana-cloud/)

### Langfuse Integration
- [Langfuse OpenTelemetry Integration](https://langfuse.com/integrations/native/opentelemetry)
- [OpenTelemetry SDK with Langfuse](https://langfuse.com/guides/cookbook/otel_integration_python_sdk)
- [Distributed Tracing with FastMCP and Langfuse](https://timvw.be/2025/06/27/distributed-tracing-with-fastmcp-combining-opentelemetry-and-langfuse/)

### Context Propagation
- [Propagation - OpenTelemetry Python](https://opentelemetry.io/docs/languages/python/propagation/)
- [otel-extensions PyPI](https://pypi.org/project/otel-extensions/)
- [Context Propagation Documentation - OpenTelemetry](https://opentelemetry.io/docs/concepts/context-propagation/)

### Multi-Agent Systems
- [OpenLLMetry GitHub](https://github.com/traceloop/openllmetry)
- [AI Agent Monitoring Guide - Medium](https://medium.com/@Sunil_Naga/ai-agent-monitoring-using-opentelemetry-simple-practical-guide-94bcc823f848)

---

**Document Status**: Draft v1.0
**Next Review**: After Phase 1 implementation
**Maintainer**: NEXUS Core Team
