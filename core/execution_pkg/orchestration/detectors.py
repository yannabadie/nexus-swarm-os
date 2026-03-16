"""
NEXUS V7.8 - Format Detectors Module (Phase 14c)

Extracted from orchestration_v7.py to follow Single Responsibility Principle.

This module handles format detection operations:
- detect_mutation_complete(): Detect valid mutation proposals
- detect_search_replace_format(): Detect SEARCH/REPLACE format
- detect_json_format(): Detect JSON mutation format

Used to signal end of EVOLUTION_BRAINSTORM when agents produce final output.

Usage:
    from core.execution_pkg.orchestration.detectors import MutationDetector

    detector = MutationDetector()
    if detector.detect_mutation_complete(content):
        # Process mutation
"""

import json
import logging
import re

_logger = logging.getLogger(__name__)


class MutationDetector:
    """
    Detector for mutation formats in agent responses.

    Supports two formats:
    1. SEARCH/REPLACE format (priority - per evolution prompt instructions)
    2. JSON array format (fallback - legacy support)

    Phase 14c: Extracted from OrchestratorV7 for better maintainability.
    """

    def __init__(self):
        """Initialize mutation detector."""
        self._logger = logging.getLogger("nexus.detectors")

    def detect_mutation_complete(self, content: str) -> bool:
        """
        Detect if content contains a valid mutation proposal.

        Supports BOTH formats (aligned with prompt instructions and legacy code):
        1. SEARCH/REPLACE format (PRIORITY - per evolution prompt instructions)
        2. JSON array format (FALLBACK - legacy support)

        Args:
            content: Agent response content to analyze

        Returns:
            True if valid mutation detected in either format, False otherwise
        """
        if not content:
            return False

        # PRIORITY 1: Check SEARCH/REPLACE format (per prompt instructions)
        # This is the format requested in the evolution prompts
        if self.detect_search_replace_format(content):
            self._logger.debug("[MUTATION] SEARCH/REPLACE format detected")
            return True

        # PRIORITY 2: Check JSON array format (legacy fallback)
        if self.detect_json_format(content):
            self._logger.debug("[MUTATION] JSON format detected")
            return True

        return False

    def detect_search_replace_format(self, content: str) -> bool:
        """
        Detect SEARCH/REPLACE mutation format.

        Expected format (from evolution prompts):
            FILE: path/to/file.py
            <<<<<<< SEARCH
            original code
            =======
            replacement code
            >>>>>>> REPLACE

        Args:
            content: Content to check

        Returns:
            True if valid SEARCH/REPLACE block found, False otherwise
        """
        # Must have FILE: header with a path
        has_file = bool(re.search(r"FILE:\s*\S+", content))

        # Must have complete SEARCH/REPLACE block markers
        has_search = "<<<<<<< SEARCH" in content
        has_separator = "=======" in content
        has_replace = ">>>>>>> REPLACE" in content

        # All markers must be present for valid format
        return has_file and has_search and has_separator and has_replace

    def detect_json_format(self, content: str) -> bool:
        """
        Detect JSON array mutation format (legacy support).

        Expected format:
            [{"file": "...", "change": "...", "reason": "...", "expected_asi_impact": ...}]

        Args:
            content: Content to check

        Returns:
            True if valid JSON mutation array found, False otherwise
        """
        # Quick check: must contain all required keys
        required_keys = ['"file"', '"change"', '"reason"', '"expected_asi_impact"']
        if not all(key in content for key in required_keys):
            return False

        # Must look like a JSON array starting with [{
        if not re.search(r"\[\s*\{", content):
            return False

        # Try to extract and parse JSON
        try:
            # Find JSON array boundaries
            for match in re.finditer(r"\[\s*\{", content):
                start = match.start()
                depth = 0
                in_string = False
                escape_next = False

                for i, char in enumerate(content[start:], start):
                    if escape_next:
                        escape_next = False
                        continue
                    if char == "\\" and in_string:
                        escape_next = True
                        continue
                    if char == '"' and not escape_next:
                        in_string = not in_string
                        continue
                    if in_string:
                        continue
                    if char == "[":
                        depth += 1
                    elif char == "]":
                        depth -= 1
                        if depth == 0:
                            candidate = content[start : i + 1]
                            try:
                                parsed = json.loads(candidate)
                                if isinstance(parsed, list) and len(parsed) > 0:
                                    # Verify all entries have required fields
                                    req_fields = {"file", "change", "reason", "expected_asi_impact"}
                                    if all(isinstance(p, dict) and req_fields.issubset(p.keys()) for p in parsed):
                                        return True
                            except json.JSONDecodeError:
                                pass
                            break
        except Exception as e:
            _logger.debug("Mutation detection failed: %s", e)

        return False


class ResponseDetector:
    """
    Detector for response patterns in agent output.

    Detects various patterns:
    - Finish signals (done, complete, finished, etc.)
    - Tool use patterns
    - Error patterns

    Phase 14c: Utility class for common detection patterns.
    """

    # Keywords indicating task completion
    FINISH_KEYWORDS = ["done", "complete", "finished", "terminé", "fini", "accomplished", "concluded", "task complete"]

    # Error patterns
    ERROR_PATTERNS = [r"error[:\s]", r"failed[:\s]", r"exception[:\s]", r"cannot\s+", r"unable\s+to"]

    @classmethod
    def is_finish_signal(cls, content: str) -> bool:
        """
        Check if content indicates task completion.

        Args:
            content: Content to check

        Returns:
            True if finish signal detected
        """
        if not content:
            return False

        content_lower = content.lower()
        return any(kw in content_lower for kw in cls.FINISH_KEYWORDS)

    @classmethod
    def has_error_pattern(cls, content: str) -> bool:
        """
        Check if content contains error patterns.

        Args:
            content: Content to check

        Returns:
            True if error pattern detected
        """
        if not content:
            return False

        content_lower = content.lower()
        return any(re.search(pattern, content_lower) for pattern in cls.ERROR_PATTERNS)


# Singleton instance for convenience
_mutation_detector: MutationDetector | None = None


def get_mutation_detector() -> MutationDetector:
    """Get or create global MutationDetector instance."""
    global _mutation_detector
    if _mutation_detector is None:
        _mutation_detector = MutationDetector()
    return _mutation_detector
