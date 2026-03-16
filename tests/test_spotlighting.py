"""Tests for Spotlighter - RAG content protection via spotlighting techniques."""

from core.memory_pkg.memory.spotlighting import (
    DELIMITER_TEMPLATES,
    SpotlightedContent,
    Spotlighter,
    SpotlightTechnique,
    get_spotlighter,
    reset_spotlighter,
    spotlight_content,
)

# =============================================================================
# SpotlightTechnique Enum
# =============================================================================


class TestSpotlightTechnique:
    def test_four_techniques(self):
        assert len(SpotlightTechnique) == 4

    def test_values(self):
        assert SpotlightTechnique.DELIMITER.value == "delimiter"
        assert SpotlightTechnique.BASE64.value == "base64"
        assert SpotlightTechnique.XML_TAG.value == "xml_tag"
        assert SpotlightTechnique.DATAMARK.value == "datamark"

    def test_all_have_templates(self):
        for technique in SpotlightTechnique:
            assert technique in DELIMITER_TEMPLATES


# =============================================================================
# SpotlightedContent
# =============================================================================


class TestSpotlightedContent:
    def test_creation(self):
        sc = SpotlightedContent(
            original="test content",
            spotlighted="<<UNTRUSTED>>test content<</UNTRUSTED>>",
            technique=SpotlightTechnique.DELIMITER,
        )
        assert sc.original == "test content"
        assert sc.technique == SpotlightTechnique.DELIMITER

    def test_str_returns_spotlighted(self):
        sc = SpotlightedContent(
            original="test",
            spotlighted="marked_test",
            technique=SpotlightTechnique.DELIMITER,
        )
        assert str(sc) == "marked_test"

    def test_metadata_default_empty(self):
        sc = SpotlightedContent(
            original="x",
            spotlighted="y",
            technique=SpotlightTechnique.DELIMITER,
        )
        assert sc.metadata == {}

    def test_with_source_and_metadata(self):
        sc = SpotlightedContent(
            original="x",
            spotlighted="y",
            technique=SpotlightTechnique.DELIMITER,
            source="wikipedia",
            metadata={"score": 0.9},
        )
        assert sc.source == "wikipedia"
        assert sc.metadata["score"] == 0.9


# =============================================================================
# Delimiter Technique
# =============================================================================


class TestDelimiterTechnique:
    def setup_method(self):
        self.spotlighter = Spotlighter(
            technique=SpotlightTechnique.DELIMITER,
            include_instruction=False,
        )

    def test_wraps_content(self):
        result = self.spotlighter.spotlight("test content")
        assert "<<UNTRUSTED_CONTENT>>" in result
        assert "<</UNTRUSTED_CONTENT>>" in result
        assert "test content" in result

    def test_empty_content_passthrough(self):
        assert self.spotlighter.spotlight("") == ""

    def test_multiline_content(self):
        content = "Line 1\nLine 2\nLine 3"
        result = self.spotlighter.spotlight(content)
        assert "Line 1" in result
        assert "Line 3" in result

    def test_with_instruction(self):
        s = Spotlighter(technique=SpotlightTechnique.DELIMITER, include_instruction=True)
        result = s.spotlight("test")
        assert "EXTERNAL DATA" in result
        assert "DATA ONLY" in result

    def test_with_source(self):
        s = Spotlighter(technique=SpotlightTechnique.DELIMITER, include_instruction=True)
        result = s.spotlight("test", source="wiki")
        assert "(Source: wiki)" in result


# =============================================================================
# XML Tag Technique
# =============================================================================


class TestXmlTagTechnique:
    def setup_method(self):
        self.spotlighter = Spotlighter(
            technique=SpotlightTechnique.XML_TAG,
            include_instruction=False,
        )

    def test_wraps_with_xml(self):
        result = self.spotlighter.spotlight("document content")
        assert "<retrieved_data" in result
        assert "</retrieved_data>" in result
        assert "document content" in result

    def test_includes_trust_level(self):
        result = self.spotlighter.spotlight("test")
        assert 'trust_level="untrusted"' in result


# =============================================================================
# Datamark Technique
# =============================================================================


class TestDatamarkTechnique:
    def setup_method(self):
        self.spotlighter = Spotlighter(
            technique=SpotlightTechnique.DATAMARK,
            include_instruction=False,
        )

    def test_prefixes_each_line(self):
        content = "First line\nSecond line\nThird line"
        result = self.spotlighter.spotlight(content)
        lines = result.split("\n")
        for line in lines:
            assert line.startswith("[D] ")

    def test_single_line(self):
        result = self.spotlighter.spotlight("single line")
        assert result == "[D] single line"

    def test_preserves_content(self):
        result = self.spotlighter.spotlight("important data")
        assert "important data" in result


# =============================================================================
# Base64 Technique
# =============================================================================


class TestBase64Technique:
    def setup_method(self):
        self.spotlighter = Spotlighter(
            technique=SpotlightTechnique.BASE64,
            include_instruction=False,
        )

    def test_encodes_content(self):
        result = self.spotlighter.spotlight("secret document")
        assert "<base64_encoded_data>" in result
        assert "</base64_encoded_data>" in result
        # Original text should NOT be visible
        assert "secret document" not in result

    def test_decodable(self):
        result = self.spotlighter.spotlight("hello world")
        decoded = Spotlighter.decode_base64_content(result)
        assert decoded == "hello world"

    def test_decode_invalid_returns_none(self):
        assert Spotlighter.decode_base64_content("no base64 here") is None

    def test_roundtrip(self):
        original = "This is sensitive data with special chars: <>&'"
        encoded = self.spotlighter.spotlight(original)
        decoded = Spotlighter.decode_base64_content(encoded)
        assert decoded == original


# =============================================================================
# Disabled Mode
# =============================================================================


class TestDisabledMode:
    def test_disabled_passthrough(self):
        s = Spotlighter(enabled=False)
        result = s.spotlight("unchanged content")
        assert result == "unchanged content"

    def test_disabled_batch(self):
        s = Spotlighter(enabled=False)
        results = s.spotlight_batch(["a", "b", "c"])
        assert results == ["a", "b", "c"]


# =============================================================================
# Batch Processing
# =============================================================================


class TestBatchProcessing:
    def test_batch_spotlight(self):
        s = Spotlighter(technique=SpotlightTechnique.DELIMITER, include_instruction=False)
        results = s.spotlight_batch(["doc1", "doc2", "doc3"])
        assert len(results) == 3
        for r in results:
            assert "UNTRUSTED_CONTENT" in r

    def test_batch_with_sources(self):
        s = Spotlighter(technique=SpotlightTechnique.DELIMITER, include_instruction=True)
        results = s.spotlight_batch(
            ["doc1", "doc2"],
            sources=["src1", "src2"],
        )
        assert "(Source: src1)" in results[0]
        assert "(Source: src2)" in results[1]

    def test_batch_empty(self):
        s = Spotlighter()
        results = s.spotlight_batch([])
        assert results == []


# =============================================================================
# RAG Results
# =============================================================================


class TestRagResults:
    def test_spotlight_rag_results(self):
        s = Spotlighter(technique=SpotlightTechnique.DELIMITER)
        docs = [
            {"content": "Document 1 content", "source": "wiki"},
            {"content": "Document 2 content", "source": "arxiv"},
        ]
        result = s.spotlight_rag_results(docs)
        assert "[wiki]" in result
        assert "[arxiv]" in result
        assert "Document 1 content" in result
        assert "Document 2 content" in result

    def test_rag_empty_docs(self):
        s = Spotlighter()
        result = s.spotlight_rag_results([])
        assert result == ""

    def test_rag_custom_keys(self):
        s = Spotlighter(technique=SpotlightTechnique.DATAMARK)
        docs = [{"text": "hello", "origin": "test"}]
        result = s.spotlight_rag_results(docs, content_key="text", source_key="origin")
        assert "[test]" in result
        assert "[D] hello" in result

    def test_rag_missing_source_gets_default(self):
        s = Spotlighter(technique=SpotlightTechnique.DELIMITER)
        docs = [{"content": "no source doc"}]
        result = s.spotlight_rag_results(docs)
        assert "[Document 1]" in result


# =============================================================================
# Structured Result
# =============================================================================


class TestSpotlightResult:
    def test_spotlight_result(self):
        s = Spotlighter(technique=SpotlightTechnique.XML_TAG)
        result = s.spotlight_result("test content", source="db", metadata={"id": 42})
        assert isinstance(result, SpotlightedContent)
        assert result.original == "test content"
        assert result.source == "db"
        assert result.metadata["id"] == 42
        assert result.technique == SpotlightTechnique.XML_TAG
        assert "<retrieved_data" in result.spotlighted


# =============================================================================
# Convenience Function
# =============================================================================


class TestConvenienceFunction:
    def test_spotlight_content_delimiter(self):
        result = spotlight_content("test data")
        assert "UNTRUSTED_CONTENT" in result

    def test_spotlight_content_base64(self):
        result = spotlight_content("test data", technique=SpotlightTechnique.BASE64)
        assert "<base64_encoded_data>" in result

    def test_spotlight_content_with_source(self):
        result = spotlight_content("test", source="api")
        assert "(Source: api)" in result


# =============================================================================
# Singleton
# =============================================================================


class TestSingleton:
    def test_get_returns_same(self):
        reset_spotlighter()
        s1 = get_spotlighter()
        s2 = get_spotlighter()
        assert s1 is s2

    def test_reset_creates_new(self):
        reset_spotlighter()
        s1 = get_spotlighter()
        reset_spotlighter()
        s2 = get_spotlighter()
        assert s1 is not s2

    def test_get_default_enabled(self):
        reset_spotlighter()
        s = get_spotlighter()
        assert s.enabled is True

    def test_get_default_technique(self):
        reset_spotlighter()
        s = get_spotlighter()
        assert s.technique == SpotlightTechnique.DELIMITER
