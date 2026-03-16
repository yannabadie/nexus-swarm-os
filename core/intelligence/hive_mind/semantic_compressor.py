"""
NEXUS V12.4.1 - Semantic Context Compressor

SLM-based semantic compression for HiveMind inter-phase context.

Problem:
    Passing full context between HiveMind phases causes token explosion.
    Phase 1 -> 2 -> 3 -> ... accumulates 10k+ tokens, wasting costs.

Solution (from ArXiv 2502.00299 - ChunkKV):
    Treat semantic chunks (not tokens) as compression units.
    Use local SLM (Llama-3 8B) to compress phase outputs to dense summaries.

Architecture:
    [Phase 1 Output: 2000 tokens]
        ↓ Compress via SLM
    [Compressed Summary: 300 tokens] <- 85% reduction
        ↓ Pass to Phase 2
    [Phase 2 uses compressed context]

Expected Impact:
    - 70-85% token reduction on inter-phase context
    - Preserve semantic meaning (unlike truncation)
    - Use cheap local SLM, save expensive frontier model tokens

Usage:
    compressor = SemanticCompressor(ollama_driver)

    # Compress phase output
    compressed = await compressor.compress_phase_output(
        phase_name="analysis",
        content=analysis_output,
        max_output_tokens=300
    )

    # Pass compressed summary to next phase
    next_phase_context = build_context(compressed)

Author: Claude Opus 4.6 (NEXUS Architect)
Date: 2026-02-17
Epic: 1.1 (Context Compression - todo3.md)
Research: ChunkKV (ArXiv 2502.00299), CCF Framework
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.drivers.ollama_driver import OllamaDriver

logger = logging.getLogger(__name__)


@dataclass
class CompressionResult:
    """Result of semantic compression."""

    original_content: str
    compressed_content: str
    original_tokens: int
    compressed_tokens: int
    compression_ratio: float  # e.g., 0.85 = 85% reduction
    phase_name: str
    metadata: dict[str, Any]


# =============================================================================
# Compression Prompts (Optimized per Phase)
# =============================================================================

# Each phase has a specialized compression prompt that preserves essential info
COMPRESSION_PROMPTS = {
    "analysis": """You are a semantic compressor for analysis results.

INPUT ANALYSIS (may be verbose):
{content}

TASK: Extract and compress to essential facts only:
1. What is the task/problem?
2. What approach was proposed?
3. What complexity/risks were identified?
4. Key capabilities needed?

OUTPUT: Dense summary in 2-4 sentences. NO fluff, NO repetition.
Focus on DECISIONS and FACTS, not explanations.""",
    "debate": """You are a semantic compressor for debate discussions.

INPUT DEBATE HISTORY (may be lengthy):
{content}

TASK: Extract consensus and key disagreements:
1. What did agents AGREE on?
2. What DISAGREEMENTS remain (if any)?
3. Final consensus decision?

OUTPUT: Dense summary in 2-3 sentences. ONLY consensus and unresolved points.""",
    "architecture": """You are a semantic compressor for architectural plans.

INPUT PLAN (may be detailed):
{content}

TASK: Extract executable plan skeleton:
1. List steps (numbered, brief)
2. Critical dependencies
3. Success criteria

OUTPUT: Compressed plan. Keep step numbers, compress descriptions to 5-10 words each.""",
    "execution": """You are a semantic compressor for execution results.

INPUT EXECUTION LOG (may be verbose):
{content}

TASK: Extract outcomes only:
1. What succeeded?
2. What failed (if any)?
3. Final state/artifacts created?

OUTPUT: Dense summary in 2-3 sentences. Focus on RESULTS, not process.""",
    "diagnosis": """You are a semantic compressor for error diagnosis.

INPUT DIAGNOSIS (may be technical):
{content}

TASK: Extract root cause and fix:
1. Root cause (1 sentence)
2. Recommended fix (1 sentence)
3. Confidence level?

OUTPUT: Dense summary in 2-3 sentences. Technical precision required.""",
    "consolidation": """You are a semantic compressor for knowledge consolidation.

INPUT REFLECTION (may be philosophical):
{content}

TASK: Extract learnings only:
1. What worked well?
2. What to remember for future tasks?
3. Patterns identified?

OUTPUT: Dense summary in 2-3 sentences. Actionable insights only.""",
}


class SemanticCompressor:
    """
    Semantic compressor using local SLM for inter-phase context reduction.

    Uses Ollama (Llama-3 8B recommended) to compress phase outputs while
    preserving semantic meaning. Cheaper and faster than frontier models.
    """

    def __init__(
        self,
        ollama_driver: OllamaDriver | None = None,
        default_model: str = "llama3.1",
        compression_target: float = 0.80,  # Target 80% compression
    ):
        """
        Initialize semantic compressor.

        Args:
            ollama_driver: OllamaDriver instance (lazy-initialized if None)
            default_model: Ollama model to use (llama3.1, llama3.2, etc.)
            compression_target: Target compression ratio (0.8 = 80% reduction)
        """
        self._driver = ollama_driver
        self._default_model = default_model
        self._compression_target = compression_target
        self._enabled = True  # Can be disabled via config

        # Lazy initialization flag
        self._initialized = ollama_driver is not None

    def _ensure_driver(self) -> OllamaDriver:
        """Lazy-initialize Ollama driver if not provided."""
        if not self._initialized:
            try:
                from core.drivers.ollama_driver import OllamaDriver

                self._driver = OllamaDriver(
                    model=self._default_model,
                    temperature=0.3,  # Low temp for consistent compression
                    num_ctx=8192,  # Larger context for compression
                )
                self._initialized = True
                logger.info(f"Initialized SemanticCompressor with {self._default_model}")
            except Exception as e:
                logger.warning(f"Failed to initialize OllamaDriver: {e}")
                self._enabled = False
                raise RuntimeError(
                    f"SemanticCompressor requires Ollama running locally. "
                    f"Install from https://ollama.com and run: ollama pull {self._default_model}"
                ) from e
        return self._driver

    async def compress_phase_output(
        self,
        phase_name: str,
        content: str,
        max_output_tokens: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CompressionResult:
        """
        Compress phase output using semantic compression.

        Args:
            phase_name: HiveMind phase name (analysis, debate, etc.)
            content: Raw phase output to compress
            max_output_tokens: Max tokens for compressed output (auto-calculated if None)
            metadata: Additional metadata to attach

        Returns:
            CompressionResult with compressed content and metrics
        """
        if not self._enabled:
            # Fallback: truncation (worst case)
            logger.warning("SemanticCompressor disabled - using truncation fallback")
            return self._truncate_fallback(phase_name, content, max_output_tokens, metadata)

        try:
            driver = self._ensure_driver()
        except RuntimeError as e:
            logger.error(f"Compression failed: {e}")
            return self._truncate_fallback(phase_name, content, max_output_tokens, metadata)

        # Estimate original tokens
        original_tokens = len(content) // 4

        # Calculate target tokens
        if max_output_tokens is None:
            max_output_tokens = int(original_tokens * (1 - self._compression_target))
            max_output_tokens = max(200, max_output_tokens)  # Min 200 tokens

        # Get compression prompt for this phase
        prompt_template = COMPRESSION_PROMPTS.get(
            phase_name,
            COMPRESSION_PROMPTS["execution"],  # Default fallback
        )
        prompt = prompt_template.format(content=content)

        # Compress via SLM
        try:
            response = await driver.invoke(
                prompt,
                system_prompt="You are a precise semantic compressor. Extract only essential information.",
                max_tokens=max_output_tokens,
            )

            if not response.is_success:
                logger.warning(f"Compression failed: {response.error_message}")
                return self._truncate_fallback(phase_name, content, max_output_tokens, metadata)

            compressed_content = response.content.strip()
            compressed_tokens = len(compressed_content) // 4

            # Calculate actual compression ratio
            compression_ratio = 1.0 - (compressed_tokens / original_tokens) if original_tokens > 0 else 0.0

            logger.info(
                f"Compressed {phase_name}: {original_tokens} -> {compressed_tokens} tokens "
                f"({compression_ratio:.1%} reduction)"
            )

            return CompressionResult(
                original_content=content,
                compressed_content=compressed_content,
                original_tokens=original_tokens,
                compressed_tokens=compressed_tokens,
                compression_ratio=compression_ratio,
                phase_name=phase_name,
                metadata=metadata or {},
            )

        except Exception as e:
            logger.error(f"Compression error: {e}")
            return self._truncate_fallback(phase_name, content, max_output_tokens, metadata)

    def _truncate_fallback(
        self,
        phase_name: str,
        content: str,
        max_tokens: int | None,
        metadata: dict[str, Any] | None,
    ) -> CompressionResult:
        """
        Fallback: Simple truncation when SLM compression fails.

        Not ideal (loses semantic meaning) but ensures system continues working.
        """
        original_tokens = len(content) // 4

        if max_tokens is None:
            max_tokens = int(original_tokens * 0.5)  # 50% truncation

        max_chars = max_tokens * 4
        compressed_content = content[:max_chars]

        if len(content) > max_chars:
            compressed_content += "\n[... truncated ...]"

        compressed_tokens = len(compressed_content) // 4
        compression_ratio = 1.0 - (compressed_tokens / original_tokens) if original_tokens > 0 else 0.0

        logger.warning(f"Using truncation fallback for {phase_name}: {original_tokens} -> {compressed_tokens} tokens")

        return CompressionResult(
            original_content=content,
            compressed_content=compressed_content,
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            compression_ratio=compression_ratio,
            phase_name=phase_name,
            metadata={"fallback": "truncation", **(metadata or {})},
        )

    async def is_available(self) -> bool:
        """
        Check if Ollama is available and model is accessible.

        Returns:
            True if compression is available, False otherwise
        """
        if not self._enabled:
            return False

        try:
            driver = self._ensure_driver()
            # Try a minimal health check
            response = await driver.invoke(
                "test",
                system_prompt="You are a test.",
                max_tokens=10,
            )
            return response.is_success
        except Exception:
            return False


# =============================================================================
# Module-level singleton
# =============================================================================

_global_compressor: SemanticCompressor | None = None


def get_semantic_compressor(
    ollama_driver: OllamaDriver | None = None,
    model: str = "llama3.1",
) -> SemanticCompressor:
    """Get or create the global semantic compressor."""
    global _global_compressor
    if _global_compressor is None:
        _global_compressor = SemanticCompressor(
            ollama_driver=ollama_driver,
            default_model=model,
        )
    return _global_compressor
