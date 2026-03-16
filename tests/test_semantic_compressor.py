"""
Tests for Semantic Context Compressor (V12.4.1 - Epic 1.1)

Testing strategy:
1. Compression with mock Ollama driver
2. Fallback to truncation when Ollama unavailable
3. Per-phase compression prompt validation
4. Compression ratio verification
5. Integration with HiveMind context flow

Author: Claude Opus 4.6
Date: 2026-02-17
Epic: 1.1 (Context Compression)
"""

from unittest.mock import AsyncMock

import pytest

from core.drivers.protocol import DriverResponse, DriverResponseStatus
from core.intelligence.hive_mind.semantic_compressor import (
    COMPRESSION_PROMPTS,
    CompressionResult,
    SemanticCompressor,
)


@pytest.fixture
def mock_ollama_driver():
    """Create mock Ollama driver for testing."""
    driver = AsyncMock()
    driver.provider = "ollama"
    driver.model = "llama3.1"
    return driver


@pytest.fixture
def compressor(mock_ollama_driver):
    """Create SemanticCompressor with mock driver."""
    return SemanticCompressor(
        ollama_driver=mock_ollama_driver,
        compression_target=0.80,  # 80% reduction target
    )


class TestCompressionPrompts:
    """Test compression prompts for each phase."""

    def test_all_phases_have_prompts(self):
        """Verify all HiveMind phases have compression prompts."""
        expected_phases = [
            "analysis",
            "debate",
            "architecture",
            "execution",
            "diagnosis",
            "consolidation",
        ]

        for phase in expected_phases:
            assert phase in COMPRESSION_PROMPTS, f"Missing compression prompt for {phase}"
            prompt = COMPRESSION_PROMPTS[phase]
            assert "{content}" in prompt, f"Prompt for {phase} missing {{content}} placeholder"
            assert len(prompt) > 100, f"Prompt for {phase} suspiciously short"

    def test_prompts_are_distinct(self):
        """Verify each phase has a unique compression strategy."""
        prompts = list(COMPRESSION_PROMPTS.values())
        unique_prompts = set(prompts)

        assert len(unique_prompts) == len(prompts), "Duplicate compression prompts found"


class TestBasicCompression:
    """Test basic compression functionality."""

    @pytest.mark.asyncio
    async def test_compress_analysis_success(self, compressor, mock_ollama_driver):
        """Test successful compression of analysis output."""
        # Mock successful compression
        mock_ollama_driver.invoke.return_value = DriverResponse(
            status=DriverResponseStatus.SUCCESS,
            content="Task: Implement auth. Approach: JWT tokens. Complexity: MODERATE. Risks: Token expiry.",
            input_tokens=500,
            output_tokens=50,
        )

        original_content = (
            """
        ANALYSIS RESULT:
        The task requires implementing user authentication for the web application.
        After careful consideration, I propose using JWT (JSON Web Tokens) for stateless
        authentication. This approach has several advantages including scalability and
        flexibility. The complexity is MODERATE as it requires setting up token generation,
        validation, and refresh mechanisms. Key risks include token expiration handling
        and secure storage of secrets. Required capabilities include cryptography libraries
        and middleware integration.
        """
            * 5
        )  # Make it verbose

        result = await compressor.compress_phase_output(
            phase_name="analysis",
            content=original_content,
            max_output_tokens=100,
        )

        assert isinstance(result, CompressionResult)
        assert (
            result.compressed_content
            == "Task: Implement auth. Approach: JWT tokens. Complexity: MODERATE. Risks: Token expiry."
        )
        assert result.original_tokens > result.compressed_tokens
        assert result.compression_ratio > 0.5  # At least 50% reduction
        assert result.phase_name == "analysis"

    @pytest.mark.asyncio
    async def test_compress_debate_success(self, compressor, mock_ollama_driver):
        """Test compression of debate history."""
        mock_ollama_driver.invoke.return_value = DriverResponse(
            status=DriverResponseStatus.SUCCESS,
            content="AGREED: Use PostgreSQL. DISAGREEMENT: Index strategy unresolved.",
            input_tokens=800,
            output_tokens=40,
        )

        debate_history = (
            """
        GEMINI: I think we should use PostgreSQL for the database.
        CLAUDE: I agree with PostgreSQL, it's battle-tested and reliable.
        GEMINI: For indexing, we could use B-tree indexes on primary keys.
        CLAUDE: I'm not sure B-tree is optimal. We might need hash indexes for equality lookups.
        GEMINI: That's a valid point. Let's discuss the tradeoffs.
        """
            * 3
        )

        result = await compressor.compress_phase_output(
            phase_name="debate",
            content=debate_history,
        )

        assert result.compressed_tokens < result.original_tokens
        assert result.compression_ratio > 0.0


class TestFallbackBehavior:
    """Test fallback behavior when Ollama unavailable."""

    @pytest.mark.asyncio
    async def test_truncation_fallback_on_driver_failure(self, compressor, mock_ollama_driver):
        """Test fallback to truncation when driver fails."""
        # Mock driver failure
        mock_ollama_driver.invoke.return_value = DriverResponse(
            status=DriverResponseStatus.ERROR,
            content="",
            error_message="Connection refused",
        )

        original_content = "A" * 1000  # 1000 chars = ~250 tokens

        result = await compressor.compress_phase_output(
            phase_name="execution",
            content=original_content,
            max_output_tokens=50,
        )

        # Should fall back to truncation
        assert "fallback" in result.metadata
        assert result.metadata["fallback"] == "truncation"
        assert result.compressed_tokens < result.original_tokens
        assert "[... truncated ...]" in result.compressed_content

    @pytest.mark.asyncio
    async def test_truncation_fallback_disabled_compressor(self):
        """Test truncation fallback when compressor is disabled."""
        compressor = SemanticCompressor(ollama_driver=None)
        compressor._enabled = False

        original_content = "Test content " * 100

        result = await compressor.compress_phase_output(
            phase_name="analysis",
            content=original_content,
        )

        assert "fallback" in result.metadata
        assert result.compressed_tokens < result.original_tokens


class TestCompressionMetrics:
    """Test compression ratio and metrics calculation."""

    @pytest.mark.asyncio
    async def test_compression_ratio_calculation(self, compressor, mock_ollama_driver):
        """Test accurate compression ratio calculation."""
        # Original: 400 tokens, Compressed: 100 tokens = 75% reduction
        mock_ollama_driver.invoke.return_value = DriverResponse(
            status=DriverResponseStatus.SUCCESS,
            content="Compressed summary " * 25,  # ~100 tokens
            input_tokens=400,
            output_tokens=100,
        )

        original_content = "Original content " * 100  # ~400 tokens

        result = await compressor.compress_phase_output(
            phase_name="architecture",
            content=original_content,
        )

        # Should be approximately 75% reduction
        assert 0.65 < result.compression_ratio < 0.85, f"Got {result.compression_ratio}"

    @pytest.mark.asyncio
    async def test_token_estimates(self, compressor, mock_ollama_driver):
        """Test token estimation (4 chars = 1 token rule)."""
        mock_ollama_driver.invoke.return_value = DriverResponse(
            status=DriverResponseStatus.SUCCESS,
            content="Short",
            input_tokens=100,
            output_tokens=10,
        )

        original_content = "Test " * 100  # 500 chars = ~125 tokens

        result = await compressor.compress_phase_output(
            phase_name="diagnosis",
            content=original_content,
        )

        assert result.original_tokens == len(original_content) // 4
        assert result.compressed_tokens == len(result.compressed_content) // 4


class TestAvailabilityCheck:
    """Test Ollama availability detection."""

    @pytest.mark.asyncio
    async def test_is_available_success(self, compressor, mock_ollama_driver):
        """Test availability check when Ollama is running."""
        mock_ollama_driver.invoke.return_value = DriverResponse(
            status=DriverResponseStatus.SUCCESS,
            content="test",
        )

        available = await compressor.is_available()
        assert available is True

    @pytest.mark.asyncio
    async def test_is_available_failure(self, compressor, mock_ollama_driver):
        """Test availability check when Ollama is down."""
        mock_ollama_driver.invoke.side_effect = ConnectionError("Ollama not running")

        available = await compressor.is_available()
        assert available is False

    @pytest.mark.asyncio
    async def test_is_available_disabled(self):
        """Test availability check when compressor is disabled."""
        compressor = SemanticCompressor(ollama_driver=None)
        compressor._enabled = False

        available = await compressor.is_available()
        assert available is False


class TestMaxTokensCalculation:
    """Test automatic max_tokens calculation."""

    @pytest.mark.asyncio
    async def test_auto_max_tokens(self, compressor, mock_ollama_driver):
        """Test automatic max_tokens based on compression target."""
        mock_ollama_driver.invoke.return_value = DriverResponse(
            status=DriverResponseStatus.SUCCESS,
            content="Summary",
        )

        # 1000 chars = 250 tokens
        # With 80% target: max = 250 * 0.2 = 50 tokens
        original_content = "X" * 1000

        await compressor.compress_phase_output(
            phase_name="consolidation",
            content=original_content,
            # No max_output_tokens specified - should auto-calculate
        )

        # Should have called with max_tokens around 50
        # (with minimum of 200, so actual will be 200)
        call_kwargs = mock_ollama_driver.invoke.call_args.kwargs
        assert "max_tokens" in call_kwargs
        assert call_kwargs["max_tokens"] >= 200  # Min token floor

    @pytest.mark.asyncio
    async def test_explicit_max_tokens(self, compressor, mock_ollama_driver):
        """Test explicit max_tokens override."""
        mock_ollama_driver.invoke.return_value = DriverResponse(
            status=DriverResponseStatus.SUCCESS,
            content="Custom",
        )

        await compressor.compress_phase_output(
            phase_name="analysis",
            content="Content " * 100,
            max_output_tokens=150,  # Explicit
        )

        call_kwargs = mock_ollama_driver.invoke.call_args.kwargs
        assert call_kwargs["max_tokens"] == 150


class TestEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_empty_content(self, compressor, mock_ollama_driver):
        """Test compression of empty content."""
        mock_ollama_driver.invoke.return_value = DriverResponse(
            status=DriverResponseStatus.SUCCESS,
            content="",
        )

        result = await compressor.compress_phase_output(
            phase_name="analysis",
            content="",
        )

        assert result.original_tokens == 0
        assert result.compression_ratio == 0.0

    @pytest.mark.asyncio
    async def test_already_short_content(self, compressor, mock_ollama_driver):
        """Test compression of already-short content."""
        mock_ollama_driver.invoke.return_value = DriverResponse(
            status=DriverResponseStatus.SUCCESS,
            content="Short summary",
        )

        short_content = "Brief analysis result."

        result = await compressor.compress_phase_output(
            phase_name="analysis",
            content=short_content,
        )

        # Should still compress, but ratio will be smaller
        assert result.original_tokens < 10
        assert result.compressed_tokens >= 0

    @pytest.mark.asyncio
    async def test_unknown_phase_fallback(self, compressor, mock_ollama_driver):
        """Test fallback prompt for unknown phases."""
        mock_ollama_driver.invoke.return_value = DriverResponse(
            status=DriverResponseStatus.SUCCESS,
            content="Generic compression",
        )

        result = await compressor.compress_phase_output(
            phase_name="unknown_phase",
            content="Some content",
        )

        # Should use execution prompt as fallback
        assert result.phase_name == "unknown_phase"
        assert result.compressed_content == "Generic compression"
