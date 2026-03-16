"""
NEXUS V12.4 COGNITIVE BOOST - OpenTelemetry Provider

Integrates OTel tracing with NEXUS SDK drivers and FSM orchestrator.
Feature-flagged via NEXUS_FF_OTEL_ENABLED.

Instrumentation layers:
1. Auto-instrumentation: Official Anthropic + Google GenAI instrumentors
2. Manual spans: FSM transitions, Swarm negotiations, evolution cycles
3. Metrics: Token usage, latency histograms, error counters

Usage:
    from core.observability.telemetry.otel_provider import init_otel, get_tracer

    # Initialize at boot (respects feature flag)
    init_otel(service_name="nexus-backend")

    # Manual span creation
    tracer = get_tracer()
    with tracer.start_as_current_span("fsm.transition") as span:
        span.set_attribute("nexus.from_state", "IDLE")
        span.set_attribute("nexus.to_state", "BRAINSTORMING")

Requirements:
    pip install opentelemetry-api opentelemetry-sdk
    pip install opentelemetry-exporter-otlp              # Optional: OTLP export
    pip install opentelemetry-instrumentation-anthropic   # Auto-instrument Claude
    pip install opentelemetry-instrumentation-google-genai # Auto-instrument Gemini

Author: Claude (NEXUS V12.4 COGNITIVE BOOST)
Date: 2026-02-15
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# =============================================================================
# Lazy imports - OTel packages are optional
# =============================================================================

_tracer = None
_meter = None
_initialized = False


def _is_otel_enabled() -> bool:
    """Check if OTel is enabled via feature flag."""
    return os.getenv("NEXUS_FF_OTEL_ENABLED", "false").lower() in ("true", "1", "yes")


def init_otel(
    service_name: str = "nexus-backend",
    service_version: str = "12.4.0",
    otlp_endpoint: str | None = None,
) -> bool:
    """
    Initialize OpenTelemetry tracing and metrics.

    Only activates if NEXUS_FF_OTEL_ENABLED=true and packages are installed.
    Safe to call multiple times (idempotent).

    Args:
        service_name: OTel service name
        service_version: Service version for resource attributes
        otlp_endpoint: OTLP collector endpoint (default: env or localhost:4317)

    Returns:
        True if OTel was initialized, False if skipped/unavailable
    """
    global _tracer, _meter, _initialized

    if _initialized:
        return True

    if not _is_otel_enabled():
        logger.debug("OTel disabled (NEXUS_FF_OTEL_ENABLED != true)")
        return False

    try:
        from opentelemetry import metrics, trace
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider

        resource = Resource.create(
            {
                "service.name": service_name,
                "service.version": service_version,
                "deployment.environment": os.getenv("NEXUS_ENV", "development"),
            }
        )

        # === Tracing ===
        tracer_provider = TracerProvider(resource=resource)

        # Add OTLP exporter if endpoint is configured
        endpoint = otlp_endpoint or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        if endpoint:
            try:
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
                from opentelemetry.sdk.trace.export import BatchSpanProcessor

                otlp_exporter = OTLPSpanExporter(endpoint=endpoint)
                tracer_provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
                logger.info(f"OTel OTLP exporter configured: {endpoint}")
            except ImportError:
                logger.debug("OTLP exporter not installed, using console only")

        # Always add console exporter for development
        if os.getenv("NEXUS_ENV", "development") == "development":
            try:
                from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

                tracer_provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
            except ImportError:
                pass

        trace.set_tracer_provider(tracer_provider)
        _tracer = trace.get_tracer("nexus", service_version)

        # === Metrics ===
        meter_provider = MeterProvider(resource=resource)
        metrics.set_meter_provider(meter_provider)
        _meter = metrics.get_meter("nexus", service_version)

        # === Auto-instrumentation for SDK drivers ===
        _instrument_anthropic()
        _instrument_google_genai()

        _initialized = True
        logger.info(f"OpenTelemetry initialized for {service_name} v{service_version}")
        return True

    except ImportError as e:
        logger.debug(f"OTel packages not installed: {e}")
        return False
    except Exception as e:
        logger.warning(f"OTel initialization failed: {e}")
        return False


def _instrument_anthropic() -> None:
    """Auto-instrument Anthropic SDK if available."""
    try:
        from opentelemetry.instrumentation.anthropic import AnthropicInstrumentor

        AnthropicInstrumentor().instrument()
        logger.info("OTel auto-instrumentation: Anthropic SDK enabled")
    except ImportError:
        logger.debug("opentelemetry-instrumentation-anthropic not installed")
    except Exception as e:
        logger.debug(f"Anthropic instrumentation failed: {e}")


def _instrument_google_genai() -> None:
    """Auto-instrument Google GenAI SDK if available."""
    try:
        from opentelemetry.instrumentation.google_genai import GoogleGenAiSdkInstrumentor

        GoogleGenAiSdkInstrumentor().instrument()
        logger.info("OTel auto-instrumentation: Google GenAI SDK enabled")
    except ImportError:
        logger.debug("opentelemetry-instrumentation-google-genai not installed")
    except Exception as e:
        logger.debug(f"Google GenAI instrumentation failed: {e}")


# =============================================================================
# Public API
# =============================================================================


def get_tracer():
    """
    Get the NEXUS OTel tracer.

    Returns a real tracer if OTel is initialized, or a no-op tracer otherwise.
    Safe to call even when OTel is not available.
    """
    if _tracer is not None:
        return _tracer

    try:
        from opentelemetry import trace

        return trace.get_tracer("nexus")
    except ImportError:
        return _NoOpTracer()


def get_meter():
    """
    Get the NEXUS OTel meter.

    Returns a real meter if OTel is initialized, or a no-op meter otherwise.
    """
    if _meter is not None:
        return _meter

    try:
        from opentelemetry import metrics

        return metrics.get_meter("nexus")
    except ImportError:
        return _NoOpMeter()


# =============================================================================
# LLM Call Span Helper
# =============================================================================


def trace_llm_call(
    provider: str,
    model: str,
    operation: str = "chat",
    *,
    agent_name: str = "",
    agent_id: str = "",
):
    """
    Context manager decorator for tracing LLM calls.

    Follows OTel GenAI semantic conventions (2025-2026 spec):
    - gen_ai.operation.name, gen_ai.provider.name, gen_ai.request.model
    - gen_ai.agent.name, gen_ai.agent.id (if provided)
    - Caller sets gen_ai.usage.input_tokens, gen_ai.usage.output_tokens,
      gen_ai.response.model on the returned span.

    Provider well-known values: "anthropic", "gcp.gemini"

    Usage:
        with trace_llm_call("anthropic", "claude-sonnet-4-5-20250929") as span:
            response = await driver.invoke(prompt)
            span.set_attribute("gen_ai.usage.input_tokens", 1000)
            span.set_attribute("gen_ai.usage.output_tokens", 500)
    """
    # Map provider names to OTel well-known values
    provider_map = {
        "claude": "anthropic",
        "anthropic": "anthropic",
        "gemini": "gcp.gemini",
        "google": "gcp.gemini",
    }
    otel_provider = provider_map.get(provider.lower(), provider)

    tracer = get_tracer()
    attrs = {
        "gen_ai.operation.name": operation,
        "gen_ai.system": otel_provider,
        "gen_ai.request.model": model,
    }
    if agent_name:
        attrs["gen_ai.agent.name"] = agent_name
    if agent_id:
        attrs["gen_ai.agent.id"] = agent_id

    span = tracer.start_span(f"{operation} {model}", attributes=attrs)
    return _SpanContextManager(span)


class _SpanContextManager:
    """Wrapper to use OTel spans as context managers."""

    def __init__(self, span):
        self._span = span

    def __enter__(self):
        return self._span

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self._span.set_attribute("error.type", exc_type.__name__)
            self._span.record_exception(exc_val)
        self._span.end()
        return False


# =============================================================================
# FSM Transition Span
# =============================================================================


def trace_fsm_transition(
    from_state: str,
    to_state: str,
    trigger: str,
    session_id: str | None = None,
) -> None:
    """
    Record an FSM transition as an OTel span event.

    Called from event_sourcing.record_transition() when OTel is enabled.
    """
    if not _initialized:
        return

    tracer = get_tracer()
    with tracer.start_as_current_span("fsm.transition") as span:
        span.set_attribute("nexus.fsm.from_state", from_state)
        span.set_attribute("nexus.fsm.to_state", to_state)
        span.set_attribute("nexus.fsm.trigger", trigger)
        if session_id:
            span.set_attribute("nexus.session_id", session_id)


# =============================================================================
# No-Op Fallbacks (when OTel is not installed)
# =============================================================================


class _NoOpSpan:
    """No-op span for when OTel is not available."""

    def set_attribute(self, key, value):
        pass

    def record_exception(self, exception):
        pass

    def end(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _NoOpTracer:
    """No-op tracer for when OTel is not available."""

    def start_span(self, name, **kwargs):
        return _NoOpSpan()

    def start_as_current_span(self, name, **kwargs):
        return _NoOpSpan()


class _NoOpMeter:
    """No-op meter for when OTel is not available."""

    def create_counter(self, name, **kwargs):
        return _NoOpInstrument()

    def create_histogram(self, name, **kwargs):
        return _NoOpInstrument()

    def create_up_down_counter(self, name, **kwargs):
        return _NoOpInstrument()


class _NoOpInstrument:
    """No-op metric instrument."""

    def add(self, amount, attributes=None):
        pass

    def record(self, amount, attributes=None):
        pass
