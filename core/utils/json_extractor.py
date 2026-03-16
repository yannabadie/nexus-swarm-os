"""
Robust JSON Extractor - NEXUS V7.5 HIVE MIND

Centralized JSON extraction with multiple fallback strategies.
Eliminates parsing errors that were the #1 source of failures.

Extraction Priority:
1. START_JSON / END_JSON markers (explicit)
2. ```json code blocks (markdown)
3. Raw JSON object detection ({ ... })
"""

import json
import re
from typing import Any


def extract_json_safe(text: str, verbose: bool = False) -> tuple[dict[str, Any] | None, str | None]:
    """
    Extract JSON from text using multiple strategies.

    Args:
        text: Text potentially containing JSON
        verbose: If True, returns debug info in second element of tuple

    Returns:
        Tuple (json_dict, error_msg)
    """
    if not text:
        return None, "Empty input text"

    # Strategy 1: Explicit markers (Gemini/Claude convention)
    marker_pattern = r"START_JSON(.*?)END_JSON"
    match = re.search(marker_pattern, text, re.DOTALL)
    if match:
        try:
            content = match.group(1).strip()
            return json.loads(content), None
        except json.JSONDecodeError as e:
            if verbose:
                return None, f"Marker strategy failed: {e}"

    # Strategy 2: Markdown code blocks
    block_pattern = r"```(?:json)?(.*?)```"
    matches = re.findall(block_pattern, text, re.DOTALL)
    for content in matches:
        try:
            return json.loads(content.strip()), None
        except json.JSONDecodeError:
            continue

    # Strategy 3: Brute force brace detection
    # Find first '{' and last '}'
    start_idx = text.find("{")
    end_idx = text.rfind("}")

    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        candidate = text[start_idx : end_idx + 1]
        try:
            return json.loads(candidate), None
        except json.JSONDecodeError:
            # Try to clean up common issues (trailing commas, etc)
            pass

    return None, "No valid JSON found with any strategy"


def extract_code_block(text: str, language: str = None) -> str | None:
    """Extract content of a specific markdown code block."""
    if language:
        pattern = f"```{language}(.*?)```"
    else:
        pattern = r"```(.*?)```"

    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


def extract_json(text: str, required_keys: set = None) -> dict[str, Any] | None:
    """
    Convenience wrapper for extract_json_safe.

    Args:
        text: Text potentially containing JSON
        required_keys: Optional set of keys that must exist in result

    Returns:
        Extracted dict or None
    """
    result, _ = extract_json_safe(text)

    if result is None:
        return None

    # Validate required keys if specified
    if required_keys and isinstance(result, dict) and not required_keys.issubset(result.keys()):
        return None

    return result


def wrap_json(data: Any) -> str:
    """
    Wrap JSON data with START_JSON/END_JSON markers.

    Use this when generating JSON to ensure clean extraction.

    Args:
        data: Data to serialize as JSON

    Returns:
        JSON string wrapped with markers
    """
    json_str = json.dumps(data, ensure_ascii=False, indent=2)
    return f"START_JSON\n{json_str}\nEND_JSON"
