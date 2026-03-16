"""
Tests for Phase 15: Stream Parser

Tests the unified stream parser for Gemini CLI and Claude CLI formats.
"""

from core.utils.stream_parser import (
    extract_final_result,
    extract_stats,
    extract_tool_info,
    is_result_message,
    is_tool_message,
    parse_stream_chunk,
)

# ============================================================================
# Gemini Stream-JSON Tests
# ============================================================================


class TestGeminiStreamParser:
    """Test parsing of Gemini CLI stream-json format."""

    def test_gemini_init_message(self):
        """Test parsing Gemini init message."""
        line = '{"type":"init","timestamp":"2025-12-05T09:46:42.998Z","session_id":"8dee5df5-fcc5-4dfe-b8fd-9bf4777d9283","model":"auto"}'
        text, data = parse_stream_chunk(line, "gemini")

        assert text is None  # Not a text delta
        assert data is not None
        assert data["type"] == "init"
        assert data["session_id"] == "8dee5df5-fcc5-4dfe-b8fd-9bf4777d9283"

    def test_gemini_user_message(self):
        """Test parsing Gemini user message echo."""
        line = '{"type":"message","timestamp":"2025-12-05T09:46:42.999Z","role":"user","content":"Hello"}'
        text, data = parse_stream_chunk(line, "gemini")

        assert text is None  # User message, not assistant delta
        assert data["role"] == "user"

    def test_gemini_assistant_delta(self):
        """Test parsing Gemini assistant text delta."""
        line = '{"type":"message","timestamp":"2025-12-05T09:46:45.485Z","role":"assistant","content":"Bonjour","delta":true}'
        text, data = parse_stream_chunk(line, "gemini")

        assert text == "Bonjour"
        assert data["delta"] is True

    def test_gemini_assistant_no_delta(self):
        """Test parsing Gemini assistant message without delta flag."""
        line = '{"type":"message","role":"assistant","content":"Complete message"}'
        text, data = parse_stream_chunk(line, "gemini")

        assert text is None  # No delta flag
        assert data["content"] == "Complete message"

    def test_gemini_tool_use(self):
        """Test parsing Gemini tool_use message."""
        line = '{"type":"tool_use","timestamp":"...","tool_name":"read_file","tool_id":"read_file-xxx","parameters":{"file_path":"test.py"}}'
        text, data = parse_stream_chunk(line, "gemini")

        assert text is None
        assert is_tool_message(data, "gemini")
        tool_info = extract_tool_info(data, "gemini")
        assert tool_info["tool_name"] == "read_file"
        assert tool_info["parameters"]["file_path"] == "test.py"

    def test_gemini_result(self):
        """Test parsing Gemini result message."""
        line = '{"type":"result","timestamp":"...","status":"success","stats":{"total_tokens":18275,"input_tokens":18095,"output_tokens":45,"duration_ms":2498,"tool_calls":0}}'
        text, data = parse_stream_chunk(line, "gemini")

        assert text is None
        assert is_result_message(data, "gemini")
        stats = extract_stats(data, "gemini")
        assert stats["total_tokens"] == 18275
        assert stats["duration_ms"] == 2498

    def test_gemini_result_no_final_text(self):
        """Gemini result doesn't include accumulated text."""
        data = {"type": "result", "status": "success", "stats": {}}
        result = extract_final_result(data, "gemini")
        assert result is None  # Must accumulate from deltas


# ============================================================================
# Claude Stream-JSON Tests
# ============================================================================


class TestClaudeStreamParser:
    """Test parsing of Claude CLI stream-json format."""

    def test_claude_init_message(self):
        """Test parsing Claude system init message."""
        line = '{"type":"system","subtype":"init","session_id":"6c996e64-3353-4527-87f6-fec5e5a0a3f1","model":"claude-opus-4-6-20250116"}'
        text, data = parse_stream_chunk(line, "claude")

        assert text is None
        assert data["type"] == "system"
        assert data["subtype"] == "init"

    def test_claude_text_delta(self):
        """Test parsing Claude text delta."""
        line = '{"type":"stream_event","event":{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Python"}}}'
        text, data = parse_stream_chunk(line, "claude")

        assert text == "Python"
        assert data["type"] == "stream_event"

    def test_claude_text_delta_multiword(self):
        """Test parsing Claude text delta with multiple words."""
        line = '{"type":"stream_event","event":{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":" est un langage"}}}'
        text, data = parse_stream_chunk(line, "claude")

        assert text == " est un langage"

    def test_claude_tool_input_delta(self):
        """Test parsing Claude tool input JSON delta (ignored for text)."""
        line = '{"type":"stream_event","event":{"type":"content_block_delta","index":0,"delta":{"type":"input_json_delta","partial_json":"{\\"file_"}}}'
        text, data = parse_stream_chunk(line, "claude")

        assert text is None  # input_json_delta, not text_delta
        assert data is not None

    def test_claude_tool_use_start(self):
        """Test parsing Claude tool_use content block start."""
        line = '{"type":"stream_event","event":{"type":"content_block_start","index":0,"content_block":{"type":"tool_use","id":"toolu_xxx","name":"Read","input":{}}}}'
        text, data = parse_stream_chunk(line, "claude")

        assert text is None
        assert is_tool_message(data, "claude")
        tool_info = extract_tool_info(data, "claude")
        assert tool_info["tool_name"] == "Read"
        assert tool_info["tool_id"] == "toolu_xxx"

    def test_claude_result(self):
        """Test parsing Claude result message."""
        line = '{"type":"result","subtype":"success","is_error":false,"duration_ms":12876,"num_turns":2,"result":"Final response text","total_cost_usd":0.0823685,"usage":{"input_tokens":1000,"output_tokens":500}}'
        text, data = parse_stream_chunk(line, "claude")

        assert text is None
        assert is_result_message(data, "claude")

        result_text = extract_final_result(data, "claude")
        assert result_text == "Final response text"

        stats = extract_stats(data, "claude")
        assert stats["duration_ms"] == 12876
        assert stats["total_cost_usd"] == 0.0823685
        assert stats["num_turns"] == 2


# ============================================================================
# Edge Cases & Error Handling
# ============================================================================


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_line(self):
        """Test handling empty line."""
        text, data = parse_stream_chunk("", "gemini")
        assert text is None
        assert data is None

    def test_whitespace_only(self):
        """Test handling whitespace-only line."""
        text, data = parse_stream_chunk("   \n\t  ", "claude")
        assert text is None
        assert data is None

    def test_invalid_json(self):
        """Test handling invalid JSON."""
        text, data = parse_stream_chunk("not valid json {", "gemini")
        assert text is None
        assert data is None

    def test_truncated_json(self):
        """Test handling truncated JSON."""
        text, data = parse_stream_chunk('{"type":"message","content":"', "claude")
        assert text is None
        assert data is None

    def test_unknown_source(self):
        """Test with unknown source - should return None for text."""
        line = '{"type":"message","role":"assistant","content":"test","delta":true}'
        text, data = parse_stream_chunk(line, "unknown_source")

        assert text is None
        assert data is not None  # JSON still parsed

    def test_empty_content(self):
        """Test handling empty content in delta."""
        line = '{"type":"message","role":"assistant","content":"","delta":true}'
        text, data = parse_stream_chunk(line, "gemini")

        assert text == ""  # Empty string, not None
        assert data["delta"] is True

    def test_none_data_for_helpers(self):
        """Test helper functions with None data."""
        assert is_result_message(None, "gemini") is False
        assert is_tool_message(None, "claude") is False

    def test_extract_tool_info_non_tool(self):
        """Test extract_tool_info on non-tool message."""
        data = {"type": "message", "content": "text"}
        info = extract_tool_info(data, "gemini")
        assert info is None


# ============================================================================
# Integration-Style Tests (Real Format Samples)
# ============================================================================


class TestRealFormatSamples:
    """Test with real format samples from documentation."""

    def test_gemini_full_conversation(self):
        """Test parsing a full Gemini conversation stream."""
        lines = [
            '{"type":"init","timestamp":"2025-12-05T09:46:42.998Z","session_id":"8dee5df5","model":"auto"}',
            '{"type":"message","timestamp":"2025-12-05T09:46:42.999Z","role":"user","content":"Say hello"}',
            '{"type":"message","timestamp":"2025-12-05T09:46:45.485Z","role":"assistant","content":"Hello","delta":true}',
            '{"type":"message","timestamp":"2025-12-05T09:46:45.490Z","role":"assistant","content":"!","delta":true}',
            '{"type":"result","timestamp":"2025-12-05T09:46:45.497Z","status":"success","stats":{"total_tokens":100,"duration_ms":2498}}',
        ]

        accumulated = []
        final_stats = None

        for line in lines:
            text, data = parse_stream_chunk(line, "gemini")
            if text is not None:
                accumulated.append(text)
            if is_result_message(data, "gemini"):
                final_stats = extract_stats(data, "gemini")

        assert "".join(accumulated) == "Hello!"
        assert final_stats["duration_ms"] == 2498

    def test_claude_full_conversation(self):
        """Test parsing a full Claude conversation stream."""
        lines = [
            '{"type":"system","subtype":"init","session_id":"6c996e64","model":"claude-opus-4-6-20250116"}',
            '{"type":"stream_event","event":{"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}}',
            '{"type":"stream_event","event":{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}}',
            '{"type":"stream_event","event":{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":" world"}}}',
            '{"type":"stream_event","event":{"type":"content_block_stop","index":0}}',
            '{"type":"result","subtype":"success","result":"Hello world","total_cost_usd":0.06,"duration_ms":5000}',
        ]

        accumulated = []
        final_result = None

        for line in lines:
            text, data = parse_stream_chunk(line, "claude")
            if text is not None:
                accumulated.append(text)
            if is_result_message(data, "claude"):
                final_result = extract_final_result(data, "claude")

        assert "".join(accumulated) == "Hello world"
        assert final_result == "Hello world"  # Claude includes result text
