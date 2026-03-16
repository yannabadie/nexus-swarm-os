"""
NEXUS V9.1.1 - Robust JSON Parser for HiveMind Phases

Handles various response formats from LLM drivers:
- Standard JSON
- Python dict literals (single quotes, True/False/None)
- Mixed formats with text around JSON

Usage:
    from core.intelligence.hive_mind.json_parser import parse_json_response

    data = parse_json_response(response, "gemini")
    if data is None:
        # Use fallback
"""

import ast
import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def _smart_quote_replace(json_str: str) -> str:
    """
    V10 FIX F6: Smart single-to-double quote replacement.

    Replaces single quotes used as JSON string delimiters,
    but preserves apostrophes within strings (e.g., "It's working").

    Args:
        json_str: JSON-like string with single quotes

    Returns:
        String with smart quote replacement
    """
    result = []
    i = 0
    in_string = False
    string_char = None

    while i < len(json_str):
        c = json_str[i]

        if not in_string:
            if c == '"':
                # Start of double-quoted string
                in_string = True
                string_char = '"'
                result.append(c)
            elif c == "'":
                # Single quote as string delimiter - check context
                # Look for pattern: {'key': or , 'value' or ['item'
                prev_non_ws = _find_prev_non_ws(json_str, i)
                if prev_non_ws in ("{", ",", "[", ":"):
                    # This is likely a string delimiter, convert to "
                    in_string = True
                    string_char = "'"
                    result.append('"')
                else:
                    # Keep as-is (might be in content)
                    result.append(c)
            else:
                result.append(c)
        else:
            # Inside a string
            if c == "\\":
                # Escape sequence - keep next char as-is
                result.append(c)
                if i + 1 < len(json_str):
                    i += 1
                    result.append(json_str[i])
            elif c == string_char:
                # End of string
                if string_char == "'":
                    result.append('"')  # Convert closing quote too
                else:
                    result.append(c)
                in_string = False
                string_char = None
            elif c == "'" and string_char == '"':
                # Apostrophe inside double-quoted string - keep it
                result.append(c)
            elif c == '"' and string_char == "'":
                # Double quote inside single-quoted string - escape it
                result.append('\\"')
            else:
                result.append(c)

        i += 1

    return "".join(result)


def _find_prev_non_ws(s: str, pos: int) -> str:
    """Find previous non-whitespace character before position."""
    pos -= 1
    while pos >= 0:
        if not s[pos].isspace():
            return s[pos]
        pos -= 1
    return ""


def parse_json_response(
    response: Any, agent_id: str = "unknown", default: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """
    Parse JSON from an LLM response using multiple strategies.

    Args:
        response: Raw response (dict, string, or other)
        agent_id: Agent identifier for logging
        default: Default value if all parsing fails

    Returns:
        Parsed dict or default value
    """
    # Handle dict response from drivers
    if isinstance(response, dict):
        # Check if it's already the data we want
        if "content" in response or "text" in response:
            response = response.get("content", response.get("text", str(response)))
        else:
            # It's already a parsed dict
            return response

    # Ensure we have a string
    if not isinstance(response, str):
        response = str(response)

    # Try to extract JSON from response
    json_match = re.search(r"\{[\s\S]*\}", response)
    if not json_match:
        logger.debug(f"{agent_id} response not in JSON format")
        return default

    json_str = json_match.group()

    # Strategy 1: Standard JSON
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        pass

    # Strategy 2: Python dict literal (single quotes, True/False/None)
    try:
        result = ast.literal_eval(json_str)
        if isinstance(result, dict):
            return result
    except (ValueError, SyntaxError):
        pass

    # Strategy 3: Fix common JSON issues (V10 FIX F6: Smart quote handling)
    try:
        fixed = _smart_quote_replace(json_str)
        # Fix Python booleans/None
        fixed = re.sub(r"\bTrue\b", "true", fixed)
        fixed = re.sub(r"\bFalse\b", "false", fixed)
        fixed = re.sub(r"\bNone\b", "null", fixed)
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # Strategy 4: Try to find a valid JSON object more carefully
    try:
        # Find all potential JSON objects
        brace_count = 0
        start = -1
        for i, c in enumerate(response):
            if c == "{":
                if brace_count == 0:
                    start = i
                brace_count += 1
            elif c == "}":
                brace_count -= 1
                if brace_count == 0 and start != -1:
                    candidate = response[start : i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        # Try with fixes (V10 FIX F6: Use smart quote replace)
                        fixed = _smart_quote_replace(candidate)
                        fixed = re.sub(r"\bTrue\b", "true", fixed)
                        fixed = re.sub(r"\bFalse\b", "false", fixed)
                        fixed = re.sub(r"\bNone\b", "null", fixed)
                        try:
                            return json.loads(fixed)
                        except json.JSONDecodeError:
                            pass
                    start = -1
    except Exception:
        pass

    logger.warning(f"All JSON parse strategies failed for {agent_id}")
    return default


def extract_json_field(response: Any, field: str, default: Any = None, agent_id: str = "unknown") -> Any:
    """
    Extract a specific field from a JSON response.

    Args:
        response: Raw response
        field: Field name to extract
        default: Default value if not found
        agent_id: Agent identifier for logging

    Returns:
        Field value or default
    """
    data = parse_json_response(response, agent_id)
    if data is None:
        return default
    return data.get(field, default)
