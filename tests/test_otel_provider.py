"""
Tests for V12.4 OpenTelemetry Provider.

Validates:
- OTel init respects feature flag
- No-op fallbacks work when OTel packages are not installed
- Tracer and meter are accessible
- LLM call tracing helper works
- FSM transition tracing works
"""

import os
from unittest.mock import patch

import pytest


class TestOTelFeatureFlag:
    """Test OTel activation respects feature flag."""

    def test_otel_disabled_by_default(self):
        """OTel should be disabled when flag is not set."""
        from core.observability.telemetry.otel_provider import _is_otel_enabled

        with patch.dict(os.environ, {}, clear=True):
            # Remove the env var if it exists
            os.environ.pop("NEXUS_FF_OTEL_ENABLED", None)
            assert _is_otel_enabled() is False

    def test_otel_enabled_with_flag(self):
        """OTel should be enabled when flag is true."""
        from core.observability.telemetry.otel_provider import _is_otel_enabled

        with patch.dict(os.environ, {"NEXUS_FF_OTEL_ENABLED": "true"}):
            assert _is_otel_enabled() is True

    def test_otel_enabled_with_1(self):
        """OTel should be enabled with '1'."""
        from core.observability.telemetry.otel_provider import _is_otel_enabled

        with patch.dict(os.environ, {"NEXUS_FF_OTEL_ENABLED": "1"}):
            assert _is_otel_enabled() is True

    def test_init_returns_false_when_disabled(self):
        """init_otel should return False when flag is off."""
        import core.observability.telemetry.otel_provider as otel_mod

        # Reset state
        otel_mod._initialized = False
        with patch.dict(os.environ, {"NEXUS_FF_OTEL_ENABLED": "false"}):
            result = otel_mod.init_otel()
            assert result is False


class TestNoOpFallbacks:
    """Test no-op objects work when OTel is not installed."""

    def test_noop_tracer_start_span(self):
        """No-op tracer should return no-op span."""
        from core.observability.telemetry.otel_provider import _NoOpTracer

        tracer = _NoOpTracer()
        span = tracer.start_span("test")
        span.set_attribute("key", "value")
        span.end()

    def test_noop_tracer_context_manager(self):
        """No-op tracer context manager should work."""
        from core.observability.telemetry.otel_provider import _NoOpTracer

        tracer = _NoOpTracer()
        with tracer.start_as_current_span("test") as span:
            span.set_attribute("key", "value")

    def test_noop_meter(self):
        """No-op meter should create no-op instruments."""
        from core.observability.telemetry.otel_provider import _NoOpMeter

        meter = _NoOpMeter()
        counter = meter.create_counter("test")
        counter.add(1)
        histogram = meter.create_histogram("test")
        histogram.record(42)

    def test_get_tracer_returns_noop_when_not_initialized(self):
        """get_tracer should return working tracer even without OTel."""
        import core.observability.telemetry.otel_provider as otel_mod

        old_tracer = otel_mod._tracer
        otel_mod._tracer = None
        try:
            tracer = otel_mod.get_tracer()
            # Should not raise
            span = tracer.start_span("test")
            span.end()
        finally:
            otel_mod._tracer = old_tracer

    def test_get_meter_returns_noop_when_not_initialized(self):
        """get_meter should return working meter even without OTel."""
        import core.observability.telemetry.otel_provider as otel_mod

        old_meter = otel_mod._meter
        otel_mod._meter = None
        try:
            meter = otel_mod.get_meter()
            counter = meter.create_counter("test")
            counter.add(1)
        finally:
            otel_mod._meter = old_meter


class TestTraceLLMCall:
    """Test the LLM call tracing helper."""

    def test_trace_llm_call_as_context_manager(self):
        """trace_llm_call should work as context manager."""
        from core.observability.telemetry.otel_provider import trace_llm_call

        with trace_llm_call("anthropic", "claude-sonnet-4-5-20250929") as span:
            span.set_attribute("gen_ai.usage.input_tokens", 100)
            span.set_attribute("gen_ai.usage.output_tokens", 50)

    def test_trace_llm_call_with_exception(self):
        """trace_llm_call should handle exceptions gracefully."""
        from core.observability.telemetry.otel_provider import trace_llm_call

        with pytest.raises(ValueError), trace_llm_call("anthropic", "claude-sonnet-4-5-20250929"):
            raise ValueError("test error")

    def test_trace_llm_call_custom_operation(self):
        """trace_llm_call should accept custom operation name."""
        from core.observability.telemetry.otel_provider import trace_llm_call

        with trace_llm_call("gcp.vertex_ai", "gemini-3-pro", operation="embeddings") as span:
            span.set_attribute("gen_ai.usage.input_tokens", 50)


class TestTraceFSMTransition:
    """Test FSM transition tracing."""

    def test_trace_fsm_transition_when_not_initialized(self):
        """trace_fsm_transition should not raise when OTel is off."""
        import core.observability.telemetry.otel_provider as otel_mod

        old_init = otel_mod._initialized
        otel_mod._initialized = False
        try:
            otel_mod.trace_fsm_transition(
                from_state="IDLE",
                to_state="BRAINSTORMING",
                trigger="user_input",
                session_id="test-123",
            )
        finally:
            otel_mod._initialized = old_init


class TestTelemetryModuleExports:
    """Test that OTel is properly exported from telemetry module."""

    def test_init_otel_importable(self):
        """init_otel should be importable from core.observability.telemetry."""
        from core.observability.telemetry import init_otel

        assert callable(init_otel)

    def test_get_tracer_importable(self):
        """get_tracer should be importable from core.observability.telemetry."""
        from core.observability.telemetry import get_tracer

        assert callable(get_tracer)

    def test_trace_llm_call_importable(self):
        """trace_llm_call should be importable from core.observability.telemetry."""
        from core.observability.telemetry import trace_llm_call

        assert callable(trace_llm_call)

    def test_trace_fsm_transition_importable(self):
        """trace_fsm_transition should be importable from core.observability.telemetry."""
        from core.observability.telemetry import trace_fsm_transition

        assert callable(trace_fsm_transition)
