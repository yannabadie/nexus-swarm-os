"""
Tests for V12.4 Versioned Prompt Registry - Version tracking for prompt templates.

Validates:
- PromptVersion dataclass (hashing, serialization, auto-fields)
- PromptEntry management (version list, latest, lookup)
- PromptRegistry registration, update, get
- Version diffing (unified diff)
- Rollback (creates new version from old content)
- Search (by name, tags, description)
- Persistence (registry.json + content files)
- Error handling (duplicate register, missing prompt, identical content)
- Module exports
"""

import pytest

from core.memory_pkg.prompts.versioned_registry import (
    PromptEntry,
    PromptRegistry,
    PromptVersion,
)

# =============================================================================
# PromptVersion Tests
# =============================================================================


class TestPromptVersion:
    """Test PromptVersion dataclass."""

    def test_basic_creation(self):
        v = PromptVersion(version=1, content="Hello {name}", content_hash="abc123")
        assert v.version == 1
        assert v.content == "Hello {name}"
        assert v.content_hash == "abc123"

    def test_auto_created_at(self):
        v = PromptVersion(version=1, content="test", content_hash="x")
        assert v.created_at != ""
        assert "T" in v.created_at  # ISO format

    def test_auto_line_count(self):
        v = PromptVersion(version=1, content="line1\nline2\nline3", content_hash="x")
        assert v.line_count == 3

    def test_single_line_count(self):
        v = PromptVersion(version=1, content="single line", content_hash="x")
        assert v.line_count == 1

    def test_empty_content_line_count(self):
        v = PromptVersion(version=1, content="", content_hash="x")
        assert v.line_count == 0

    def test_explicit_created_at_preserved(self):
        v = PromptVersion(version=1, content="test", content_hash="x", created_at="2025-01-01T00:00:00Z")
        assert v.created_at == "2025-01-01T00:00:00Z"

    def test_to_dict(self):
        v = PromptVersion(
            version=2,
            content="Hello",
            content_hash="abc",
            author="claude",
            changelog="update",
            variables=["name"],
        )
        d = v.to_dict()
        assert d["version"] == 2
        assert d["content_hash"] == "abc"
        assert d["author"] == "claude"
        assert d["changelog"] == "update"
        assert d["variables"] == ["name"]
        # Content should NOT be in dict (stored separately)
        assert "content" not in d

    def test_from_dict(self):
        data = {
            "version": 3,
            "content_hash": "def456",
            "author": "gemini",
            "changelog": "refactor",
            "created_at": "2025-06-01T12:00:00Z",
            "variables": ["task", "mode"],
            "line_count": 10,
        }
        v = PromptVersion.from_dict(data, content="restored content")
        assert v.version == 3
        assert v.content == "restored content"
        assert v.content_hash == "def456"
        assert v.author == "gemini"
        assert v.variables == ["task", "mode"]

    def test_from_dict_minimal(self):
        data = {"version": 1}
        v = PromptVersion.from_dict(data)
        assert v.version == 1
        assert v.content == ""
        assert v.content_hash == ""

    def test_defaults(self):
        v = PromptVersion(version=1, content="x", content_hash="y")
        assert v.author == ""
        assert v.changelog == ""
        assert v.variables == []


# =============================================================================
# PromptEntry Tests
# =============================================================================


class TestPromptEntry:
    """Test PromptEntry dataclass."""

    def test_empty_entry(self):
        entry = PromptEntry(name="test_prompt")
        assert entry.name == "test_prompt"
        assert entry.current_version == 0
        assert entry.versions == []
        assert entry.latest is None
        assert entry.version_count == 0

    def test_latest_returns_last_version(self):
        v1 = PromptVersion(version=1, content="v1", content_hash="a")
        v2 = PromptVersion(version=2, content="v2", content_hash="b")
        entry = PromptEntry(name="test", versions=[v1, v2], current_version=2)
        assert entry.latest == v2

    def test_version_count(self):
        versions = [PromptVersion(version=i, content=f"v{i}", content_hash=f"h{i}") for i in range(1, 6)]
        entry = PromptEntry(name="test", versions=versions, current_version=5)
        assert entry.version_count == 5

    def test_get_version_found(self):
        v1 = PromptVersion(version=1, content="v1", content_hash="a")
        v2 = PromptVersion(version=2, content="v2", content_hash="b")
        entry = PromptEntry(name="test", versions=[v1, v2])
        assert entry.get_version(1) == v1
        assert entry.get_version(2) == v2

    def test_get_version_not_found(self):
        v1 = PromptVersion(version=1, content="v1", content_hash="a")
        entry = PromptEntry(name="test", versions=[v1])
        assert entry.get_version(99) is None

    def test_to_dict(self):
        v1 = PromptVersion(version=1, content="v1", content_hash="a")
        entry = PromptEntry(name="my_prompt", current_version=1, versions=[v1], tags=["system"], description="A prompt")
        d = entry.to_dict()
        assert d["name"] == "my_prompt"
        assert d["current_version"] == 1
        assert d["version_count"] == 1
        assert d["tags"] == ["system"]
        assert d["description"] == "A prompt"
        assert len(d["versions"]) == 1

    def test_tags_and_description_defaults(self):
        entry = PromptEntry(name="test")
        assert entry.tags == []
        assert entry.description == ""


# =============================================================================
# PromptRegistry - Registration Tests
# =============================================================================


class TestRegistration:
    """Test prompt registration."""

    def test_register_new_prompt(self):
        registry = PromptRegistry()
        v = registry.register("greeting", content="Hello {name}!", author="claude")
        assert v.version == 1
        assert v.content == "Hello {name}!"
        assert v.author == "claude"
        assert v.changelog == "Initial version"

    def test_register_with_changelog(self):
        registry = PromptRegistry()
        v = registry.register("test", content="x", changelog="Custom init")
        assert v.changelog == "Custom init"

    def test_register_with_tags(self):
        registry = PromptRegistry()
        registry.register(
            "system_claude", content="You are helpful", tags=["system", "claude"], description="Claude system prompt"
        )
        entry = registry.get_entry("system_claude")
        assert entry.tags == ["system", "claude"]
        assert entry.description == "Claude system prompt"

    def test_register_extracts_variables(self):
        registry = PromptRegistry()
        v = registry.register("tmpl", content="Hello {name}, your {role} is ready")
        assert "name" in v.variables
        assert "role" in v.variables

    def test_register_computes_hash(self):
        registry = PromptRegistry()
        v = registry.register("test", content="some content")
        assert v.content_hash != ""
        assert len(v.content_hash) == 16  # sha256[:16]

    def test_register_duplicate_raises(self):
        registry = PromptRegistry()
        registry.register("test", content="v1")
        with pytest.raises(ValueError, match="already exists"):
            registry.register("test", content="v2")

    def test_register_sets_version_1(self):
        registry = PromptRegistry()
        v = registry.register("p", content="x")
        assert v.version == 1
        entry = registry.get_entry("p")
        assert entry.current_version == 1


# =============================================================================
# PromptRegistry - Update Tests
# =============================================================================


class TestUpdate:
    """Test prompt update (new version)."""

    def test_update_increments_version(self):
        registry = PromptRegistry()
        registry.register("test", content="v1")
        v2 = registry.update("test", content="v2", changelog="Updated")
        assert v2.version == 2
        assert v2.content == "v2"
        assert v2.changelog == "Updated"

    def test_update_preserves_history(self):
        registry = PromptRegistry()
        registry.register("test", content="v1")
        registry.update("test", content="v2")
        registry.update("test", content="v3")

        entry = registry.get_entry("test")
        assert entry.version_count == 3
        assert entry.current_version == 3
        assert entry.get_version(1).content == "v1"
        assert entry.get_version(2).content == "v2"
        assert entry.get_version(3).content == "v3"

    def test_update_nonexistent_raises(self):
        registry = PromptRegistry()
        with pytest.raises(KeyError, match="not found"):
            registry.update("missing", content="x")

    def test_update_identical_content_raises(self):
        registry = PromptRegistry()
        registry.register("test", content="same content")
        with pytest.raises(ValueError, match="identical"):
            registry.update("test", content="same content")

    def test_update_extracts_new_variables(self):
        registry = PromptRegistry()
        registry.register("test", content="Hello {name}")
        v2 = registry.update("test", content="Hello {name}, {greeting}")
        assert "greeting" in v2.variables
        assert "name" in v2.variables

    def test_multiple_updates(self):
        registry = PromptRegistry()
        registry.register("test", content="v1")
        for i in range(2, 11):
            registry.update("test", content=f"v{i}")
        entry = registry.get_entry("test")
        assert entry.current_version == 10
        assert entry.version_count == 10


# =============================================================================
# PromptRegistry - Get Tests
# =============================================================================


class TestGet:
    """Test getting prompt content."""

    def test_get_latest(self):
        registry = PromptRegistry()
        registry.register("test", content="v1")
        registry.update("test", content="v2")
        assert registry.get("test") == "v2"

    def test_get_specific_version(self):
        registry = PromptRegistry()
        registry.register("test", content="version one")
        registry.update("test", content="version two")
        assert registry.get("test", version=1) == "version one"
        assert registry.get("test", version=2) == "version two"

    def test_get_nonexistent_returns_none(self):
        registry = PromptRegistry()
        assert registry.get("missing") is None

    def test_get_nonexistent_version_returns_none(self):
        registry = PromptRegistry()
        registry.register("test", content="v1")
        assert registry.get("test", version=99) is None

    def test_get_version_info(self):
        registry = PromptRegistry()
        registry.register("test", content="Hello {name}", author="claude")
        info = registry.get_version_info("test")
        assert info.version == 1
        assert info.author == "claude"
        assert "name" in info.variables

    def test_get_version_info_specific(self):
        registry = PromptRegistry()
        registry.register("test", content="v1", author="claude")
        registry.update("test", content="v2", author="gemini")
        info = registry.get_version_info("test", version=1)
        assert info.author == "claude"

    def test_get_version_info_nonexistent(self):
        registry = PromptRegistry()
        assert registry.get_version_info("missing") is None

    def test_get_entry(self):
        registry = PromptRegistry()
        registry.register("test", content="v1", tags=["system"])
        entry = registry.get_entry("test")
        assert entry.name == "test"
        assert entry.tags == ["system"]

    def test_get_entry_nonexistent(self):
        registry = PromptRegistry()
        assert registry.get_entry("missing") is None


# =============================================================================
# PromptRegistry - Diff Tests
# =============================================================================


class TestDiff:
    """Test version diffing."""

    def test_basic_diff(self):
        registry = PromptRegistry()
        registry.register("test", content="line1\nline2\nline3")
        registry.update("test", content="line1\nmodified\nline3")
        diff = registry.diff("test", version_a=1, version_b=2)
        assert diff is not None
        assert "-line2" in diff
        assert "+modified" in diff

    def test_diff_header(self):
        registry = PromptRegistry()
        registry.register("test", content="a")
        registry.update("test", content="b")
        diff = registry.diff("test", version_a=1, version_b=2)
        assert "test v1" in diff
        assert "test v2" in diff

    def test_diff_nonexistent_prompt(self):
        registry = PromptRegistry()
        assert registry.diff("missing", 1, 2) is None

    def test_diff_nonexistent_version(self):
        registry = PromptRegistry()
        registry.register("test", content="v1")
        assert registry.diff("test", 1, 99) is None

    def test_diff_same_version(self):
        registry = PromptRegistry()
        registry.register("test", content="same")
        diff = registry.diff("test", version_a=1, version_b=1)
        assert diff is not None
        assert diff == ""  # No differences

    def test_diff_addition(self):
        registry = PromptRegistry()
        registry.register("test", content="line1")
        registry.update("test", content="line1\nline2\nline3")
        diff = registry.diff("test", 1, 2)
        assert "+line2" in diff
        assert "+line3" in diff

    def test_diff_removal(self):
        registry = PromptRegistry()
        registry.register("test", content="line1\nline2\nline3")
        registry.update("test", content="line1")
        diff = registry.diff("test", 1, 2)
        assert "-line2" in diff
        assert "-line3" in diff


# =============================================================================
# PromptRegistry - Rollback Tests
# =============================================================================


class TestRollback:
    """Test version rollback."""

    def test_rollback_creates_new_version(self):
        registry = PromptRegistry()
        registry.register("test", content="original")
        registry.update("test", content="modified")
        v3 = registry.rollback("test", target_version=1)
        assert v3.version == 3
        assert v3.changelog == "Rollback to v1"
        assert v3.author == "system"

    def test_rollback_restores_content(self):
        registry = PromptRegistry()
        registry.register("test", content="original content")
        registry.update("test", content="new content")
        registry.rollback("test", target_version=1)
        assert registry.get("test") == "original content"

    def test_rollback_nonexistent_prompt(self):
        registry = PromptRegistry()
        with pytest.raises(KeyError, match="not found"):
            registry.rollback("missing", target_version=1)

    def test_rollback_nonexistent_version(self):
        registry = PromptRegistry()
        registry.register("test", content="v1")
        with pytest.raises(ValueError, match="not found"):
            registry.rollback("test", target_version=99)

    def test_rollback_preserves_history(self):
        registry = PromptRegistry()
        registry.register("test", content="v1")
        registry.update("test", content="v2")
        registry.update("test", content="v3")
        registry.rollback("test", target_version=1)

        entry = registry.get_entry("test")
        assert entry.version_count == 4  # v1, v2, v3, v4(rollback)
        assert entry.current_version == 4


# =============================================================================
# PromptRegistry - Search Tests
# =============================================================================


class TestSearch:
    """Test prompt search."""

    def test_search_by_name(self):
        registry = PromptRegistry()
        registry.register("system_claude", content="a")
        registry.register("system_gemini", content="b")
        registry.register("user_template", content="c")
        results = registry.search("system")
        assert "system_claude" in results
        assert "system_gemini" in results
        assert "user_template" not in results

    def test_search_by_tag(self):
        registry = PromptRegistry()
        registry.register("prompt1", content="a", tags=["coding", "python"])
        registry.register("prompt2", content="b", tags=["research"])
        results = registry.search("python")
        assert "prompt1" in results
        assert "prompt2" not in results

    def test_search_by_description(self):
        registry = PromptRegistry()
        registry.register("p1", content="a", description="For security audits")
        registry.register("p2", content="b", description="For coding tasks")
        results = registry.search("security")
        assert "p1" in results
        assert "p2" not in results

    def test_search_case_insensitive(self):
        registry = PromptRegistry()
        registry.register("MyPrompt", content="a")
        results = registry.search("myprompt")
        assert "MyPrompt" in results

    def test_search_no_results(self):
        registry = PromptRegistry()
        registry.register("test", content="a")
        results = registry.search("nonexistent")
        assert results == []


# =============================================================================
# PromptRegistry - List Tests
# =============================================================================


class TestList:
    """Test listing prompts and versions."""

    def test_list_prompts(self):
        registry = PromptRegistry()
        registry.register("p1", content="a", tags=["sys"])
        registry.register("p2", content="b", description="Desc")
        lst = registry.list_prompts()
        assert len(lst) == 2
        names = [p["name"] for p in lst]
        assert "p1" in names
        assert "p2" in names

    def test_list_prompts_empty(self):
        registry = PromptRegistry()
        assert registry.list_prompts() == []

    def test_list_versions(self):
        registry = PromptRegistry()
        registry.register("test", content="v1")
        registry.update("test", content="v2")
        versions = registry.list_versions("test")
        assert len(versions) == 2
        assert versions[0]["version"] == 1
        assert versions[1]["version"] == 2

    def test_list_versions_nonexistent(self):
        registry = PromptRegistry()
        assert registry.list_versions("missing") == []


# =============================================================================
# PromptRegistry - Remove Tests
# =============================================================================


class TestRemove:
    """Test prompt removal."""

    def test_remove_existing(self):
        registry = PromptRegistry()
        registry.register("test", content="v1")
        assert registry.remove("test") is True
        assert registry.get("test") is None

    def test_remove_nonexistent(self):
        registry = PromptRegistry()
        assert registry.remove("missing") is False

    def test_remove_clears_all_versions(self):
        registry = PromptRegistry()
        registry.register("test", content="v1")
        registry.update("test", content="v2")
        registry.remove("test")
        assert registry.get_entry("test") is None


# =============================================================================
# PromptRegistry - Persistence Tests
# =============================================================================


class TestPersistence:
    """Test save/load to disk."""

    def test_save_and_load(self, tmp_path):
        # Create and populate registry
        r1 = PromptRegistry(storage_path=tmp_path / "prompts")
        r1.register(
            "greeting", content="Hello {name}!", author="claude", tags=["system"], description="Greeting template"
        )
        r1.update("greeting", content="Hi {name}!", author="gemini", changelog="Shorter greeting")

        # Load into new registry
        r2 = PromptRegistry(storage_path=tmp_path / "prompts")
        assert r2.get("greeting") == "Hi {name}!"
        assert r2.get("greeting", version=1) == "Hello {name}!"

        entry = r2.get_entry("greeting")
        assert entry.tags == ["system"]
        assert entry.description == "Greeting template"
        assert entry.current_version == 2

    def test_registry_json_created(self, tmp_path):
        registry = PromptRegistry(storage_path=tmp_path / "prompts")
        registry.register("test", content="hello")
        assert (tmp_path / "prompts" / "registry.json").exists()

    def test_content_files_created(self, tmp_path):
        registry = PromptRegistry(storage_path=tmp_path / "prompts")
        registry.register("test", content="v1 content")
        registry.update("test", content="v2 content")
        content_dir = tmp_path / "prompts" / "content"
        assert (content_dir / "test_v1.txt").exists()
        assert (content_dir / "test_v2.txt").exists()
        assert (content_dir / "test_v1.txt").read_text(encoding="utf-8") == "v1 content"

    def test_persistence_multiple_prompts(self, tmp_path):
        r1 = PromptRegistry(storage_path=tmp_path / "prompts")
        r1.register("p1", content="prompt one")
        r1.register("p2", content="prompt two")

        r2 = PromptRegistry(storage_path=tmp_path / "prompts")
        assert r2.get("p1") == "prompt one"
        assert r2.get("p2") == "prompt two"

    def test_empty_storage_path(self, tmp_path):
        """Loading from non-existent path should work (empty registry)."""
        registry = PromptRegistry(storage_path=tmp_path / "nonexistent")
        assert registry.list_prompts() == []

    def test_corrupted_registry_json(self, tmp_path):
        """Corrupted JSON should be handled gracefully."""
        storage = tmp_path / "prompts"
        storage.mkdir()
        (storage / "registry.json").write_text("not valid json", encoding="utf-8")
        registry = PromptRegistry(storage_path=storage)
        assert registry.list_prompts() == []

    def test_in_memory_mode(self):
        """No storage_path = in-memory only."""
        registry = PromptRegistry()
        registry.register("test", content="hello")
        assert registry.get("test") == "hello"
        # No files should be created (no way to verify absence, but no error)


# =============================================================================
# PromptRegistry - Hash Tests
# =============================================================================


class TestHashing:
    """Test content hashing."""

    def test_same_content_same_hash(self):
        registry = PromptRegistry()
        h1 = registry._hash_content("hello world")
        h2 = registry._hash_content("hello world")
        assert h1 == h2

    def test_different_content_different_hash(self):
        registry = PromptRegistry()
        h1 = registry._hash_content("hello")
        h2 = registry._hash_content("world")
        assert h1 != h2

    def test_hash_length(self):
        registry = PromptRegistry()
        h = registry._hash_content("test")
        assert len(h) == 16


# =============================================================================
# PromptRegistry - Variable Extraction Tests
# =============================================================================


class TestVariableExtraction:
    """Test {variable} placeholder extraction."""

    def test_single_variable(self):
        registry = PromptRegistry()
        vars_ = registry._extract_variables("Hello {name}")
        assert vars_ == ["name"]

    def test_multiple_variables(self):
        registry = PromptRegistry()
        vars_ = registry._extract_variables("{greeting} {name}, your {role}")
        assert vars_ == ["greeting", "name", "role"]

    def test_duplicate_variables(self):
        registry = PromptRegistry()
        vars_ = registry._extract_variables("{name} and {name} again")
        assert vars_ == ["name"]  # Deduplicated

    def test_no_variables(self):
        registry = PromptRegistry()
        vars_ = registry._extract_variables("No variables here")
        assert vars_ == []

    def test_sorted_output(self):
        registry = PromptRegistry()
        vars_ = registry._extract_variables("{zebra} {alpha} {middle}")
        assert vars_ == ["alpha", "middle", "zebra"]


# =============================================================================
# PromptRegistry - State Export Tests
# =============================================================================


class TestStateExport:
    """Test registry state export."""

    def test_to_dict_empty(self):
        registry = PromptRegistry()
        d = registry.to_dict()
        assert d["prompt_count"] == 0
        assert d["total_versions"] == 0
        assert d["prompts"] == {}

    def test_to_dict_with_data(self):
        registry = PromptRegistry()
        registry.register("p1", content="v1")
        registry.update("p1", content="v2")
        registry.register("p2", content="a")

        d = registry.to_dict()
        assert d["prompt_count"] == 2
        assert d["total_versions"] == 3
        assert "p1" in d["prompts"]
        assert "p2" in d["prompts"]


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test that versioned registry types are importable."""

    def test_from_prompts_package(self):
        from core.memory_pkg.prompts import PromptEntry, PromptRegistry, PromptVersion

        assert PromptRegistry is not None
        assert PromptVersion is not None
        assert PromptEntry is not None

    def test_from_module(self):
        from core.memory_pkg.prompts.versioned_registry import (
            PromptEntry,
            PromptRegistry,
            PromptVersion,
        )

        assert all([PromptRegistry, PromptVersion, PromptEntry])
