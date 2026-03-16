"""
Simple smoke tests for Google GenAI SDK Driver Structured Outputs (V12.4.1 - Epic 1.2)

These are lightweight tests that validate the API exists and has the correct signatures.
Full integration testing requires a real Google GenAI API key and is done manually.

Author: Claude Opus 4.6
Date: 2026-02-17
Epic: 1.2 (Structured Outputs)
"""

from pydantic import BaseModel

# Validates that the imports work
from core.drivers.google_genai_sdk_driver import GoogleGenAISDKDriver
from core.intelligence.hive_mind.schemas import AnalysisOutput


class SimpleTestModel(BaseModel):
    """Simple model for API validation."""

    result: str
    score: float


class TestGoogleGenAIStructuredOutputsAPI:
    """Validate that structured output methods exist with correct signatures."""

    def test_driver_has_invoke_structured_method(self):
        """Driver should expose invoke_structured method."""
        assert hasattr(GoogleGenAISDKDriver, "invoke_structured")
        assert callable(GoogleGenAISDKDriver.invoke_structured)

    def test_driver_has_invoke_json_schema_method(self):
        """Driver should expose invoke_json_schema method."""
        assert hasattr(GoogleGenAISDKDriver, "invoke_json_schema")
        assert callable(GoogleGenAISDKDriver.invoke_json_schema)

    def test_invoke_structured_signature(self):
        """invoke_structured should have correct signature."""
        import inspect

        sig = inspect.signature(GoogleGenAISDKDriver.invoke_structured)
        params = list(sig.parameters.keys())

        # Should have: self, prompt, output_type, system_prompt, timeout, kwargs
        assert "self" in params
        assert "prompt" in params
        assert "output_type" in params
        assert "system_prompt" in params
        assert "timeout" in params
        assert "kwargs" in params

    def test_invoke_json_schema_signature(self):
        """invoke_json_schema should have correct signature."""
        import inspect

        sig = inspect.signature(GoogleGenAISDKDriver.invoke_json_schema)
        params = list(sig.parameters.keys())

        # Should have: self, prompt, json_schema, system_prompt, timeout, kwargs
        assert "self" in params
        assert "prompt" in params
        assert "json_schema" in params
        assert "system_prompt" in params
        assert "timeout" in params
        assert "kwargs" in params

    def test_schemas_are_importable(self):
        """HiveMind schemas should be importable for use with structured outputs."""
        # All schemas should be Pydantic BaseModels
        from pydantic import BaseModel

        from core.intelligence.hive_mind.schemas import (
            AnalysisOutput,
            ArchitectureOutput,
            ConsolidationOutput,
            DebateOutput,
            DiagnosisOutput,
            ExecutionOutput,
            get_schema_for_phase,
        )

        assert issubclass(AnalysisOutput, BaseModel)
        assert issubclass(DebateOutput, BaseModel)
        assert issubclass(ArchitectureOutput, BaseModel)
        assert issubclass(ExecutionOutput, BaseModel)
        assert issubclass(DiagnosisOutput, BaseModel)
        assert issubclass(ConsolidationOutput, BaseModel)

        # get_schema_for_phase should work
        schema = get_schema_for_phase("analysis")
        assert schema == AnalysisOutput

    def test_pydantic_models_are_valid_schemas(self):
        """Pydantic models should generate valid JSON schemas."""
        # Test simple model
        schema = SimpleTestModel.model_json_schema()
        assert "properties" in schema
        assert "result" in schema["properties"]
        assert "score" in schema["properties"]

        # Test HiveMind schema
        analysis_schema = AnalysisOutput.model_json_schema()
        assert "properties" in analysis_schema
        assert "task_understanding" in analysis_schema["properties"]
        assert "complexity_assessment" in analysis_schema["properties"]


# Note: Full integration tests require a real Google AI API key.
# These can be run manually with:
#
# export GOOGLE_API_KEY="your-key"
# pytest tests/test_google_genai_structured_manual.py -v
#
# See tests/test_google_genai_structured_manual.py (to be created) for
# integration tests that actually call the Google AI API.
