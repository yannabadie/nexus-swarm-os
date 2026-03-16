"""
Tests for V12.4 Config Manager.

Validates:
- ConfigEntry creation and to_dict
- ConfigValidation to_dict
- Set operations (set, set_many, load_dict)
- Get operations (get, get_str, get_int, get_float, get_bool)
- Default values for missing keys
- Has and get_entry
- Delete operations
- Validation (require, validate)
- Listing (sections, keys, get_section, get_all)
- State management
- Global singleton
- Module exports
"""

from core.utils.config_manager import (
    ConfigEntry,
    ConfigManager,
    ConfigValidation,
    get_config_manager,
    reset_config_manager,
)

# =============================================================================
# ConfigEntry Tests
# =============================================================================


class TestConfigEntry:
    """Test ConfigEntry dataclass."""

    def test_basic(self):
        e = ConfigEntry(section="swarm", key="mode", value="parallel")
        assert e.section == "swarm"
        assert e.key == "mode"
        assert e.value == "parallel"

    def test_auto_type(self):
        assert ConfigEntry(section="s", key="k", value=42).value_type == "int"
        assert ConfigEntry(section="s", key="k", value="hi").value_type == "str"
        assert ConfigEntry(section="s", key="k", value=True).value_type == "bool"

    def test_to_dict(self):
        e = ConfigEntry(section="s", key="k", value=42, description="count")
        d = e.to_dict()
        assert d["section"] == "s"
        assert d["value"] == 42
        assert d["description"] == "count"


# =============================================================================
# ConfigValidation Tests
# =============================================================================


class TestConfigValidation:
    """Test ConfigValidation."""

    def test_valid(self):
        v = ConfigValidation(is_valid=True)
        assert v.is_valid is True

    def test_to_dict(self):
        v = ConfigValidation(is_valid=False, missing_keys=["swarm.mode"])
        d = v.to_dict()
        assert d["is_valid"] is False
        assert "swarm.mode" in d["missing_keys"]


# =============================================================================
# Set Tests
# =============================================================================


class TestSet:
    """Test set operations."""

    def test_set(self):
        cfg = ConfigManager()
        cfg.set("swarm", "auto_route", True)
        assert cfg.get("swarm", "auto_route") is True

    def test_set_with_description(self):
        cfg = ConfigManager()
        cfg.set("limits", "max_tokens", 128000, description="Max context size")
        entry = cfg.get_entry("limits", "max_tokens")
        assert entry.description == "Max context size"

    def test_set_overwrite(self):
        cfg = ConfigManager()
        cfg.set("s", "k", 1)
        cfg.set("s", "k", 2)
        assert cfg.get("s", "k") == 2

    def test_set_many(self):
        cfg = ConfigManager()
        count = cfg.set_many("models", {"provider": "claude", "tier": "opus"})
        assert count == 2
        assert cfg.get("models", "provider") == "claude"

    def test_load_dict(self):
        cfg = ConfigManager()
        count = cfg.load_dict(
            {
                "swarm": {"mode": "parallel", "depth": 3},
                "models": {"provider": "claude"},
            }
        )
        assert count == 3
        assert cfg.get("swarm", "mode") == "parallel"
        assert cfg.get("models", "provider") == "claude"


# =============================================================================
# Get Tests
# =============================================================================


class TestGet:
    """Test get operations."""

    def test_get(self):
        cfg = ConfigManager()
        cfg.set("s", "k", "value")
        assert cfg.get("s", "k") == "value"

    def test_get_default(self):
        cfg = ConfigManager()
        assert cfg.get("s", "missing", "default") == "default"

    def test_get_none(self):
        cfg = ConfigManager()
        assert cfg.get("s", "missing") is None

    def test_get_str(self):
        cfg = ConfigManager()
        cfg.set("s", "k", 42)
        assert cfg.get_str("s", "k") == "42"

    def test_get_str_default(self):
        cfg = ConfigManager()
        assert cfg.get_str("s", "missing", "fallback") == "fallback"

    def test_get_int(self):
        cfg = ConfigManager()
        cfg.set("s", "k", "100")
        assert cfg.get_int("s", "k") == 100

    def test_get_int_default(self):
        cfg = ConfigManager()
        assert cfg.get_int("s", "missing", 42) == 42

    def test_get_int_invalid(self):
        cfg = ConfigManager()
        cfg.set("s", "k", "not_a_number")
        assert cfg.get_int("s", "k", 0) == 0

    def test_get_float(self):
        cfg = ConfigManager()
        cfg.set("s", "k", "3.14")
        assert abs(cfg.get_float("s", "k") - 3.14) < 0.001

    def test_get_float_default(self):
        cfg = ConfigManager()
        assert cfg.get_float("s", "missing", 1.5) == 1.5

    def test_get_bool_true(self):
        cfg = ConfigManager()
        cfg.set("s", "k", True)
        assert cfg.get_bool("s", "k") is True

    def test_get_bool_string_true(self):
        cfg = ConfigManager()
        for val in ("true", "1", "yes"):
            cfg.set("s", "k", val)
            assert cfg.get_bool("s", "k") is True

    def test_get_bool_false(self):
        cfg = ConfigManager()
        cfg.set("s", "k", False)
        assert cfg.get_bool("s", "k") is False

    def test_get_bool_string_false(self):
        cfg = ConfigManager()
        cfg.set("s", "k", "false")
        assert cfg.get_bool("s", "k") is False

    def test_get_bool_default(self):
        cfg = ConfigManager()
        assert cfg.get_bool("s", "missing", True) is True

    def test_has(self):
        cfg = ConfigManager()
        cfg.set("s", "k", "v")
        assert cfg.has("s", "k") is True
        assert cfg.has("s", "missing") is False

    def test_get_entry(self):
        cfg = ConfigManager()
        cfg.set("s", "k", 42)
        entry = cfg.get_entry("s", "k")
        assert entry is not None
        assert entry.value == 42

    def test_get_entry_not_found(self):
        cfg = ConfigManager()
        assert cfg.get_entry("s", "missing") is None


# =============================================================================
# Delete Tests
# =============================================================================


class TestDelete:
    """Test delete operations."""

    def test_delete(self):
        cfg = ConfigManager()
        cfg.set("s", "k", "v")
        assert cfg.delete("s", "k") is True
        assert cfg.get("s", "k") is None

    def test_delete_not_found(self):
        cfg = ConfigManager()
        assert cfg.delete("s", "missing") is False

    def test_delete_section(self):
        cfg = ConfigManager()
        cfg.set("s", "a", 1)
        cfg.set("s", "b", 2)
        assert cfg.delete_section("s") is True
        assert cfg.section_count == 0

    def test_delete_section_not_found(self):
        cfg = ConfigManager()
        assert cfg.delete_section("missing") is False

    def test_delete_cleans_empty_section(self):
        cfg = ConfigManager()
        cfg.set("s", "k", "v")
        cfg.delete("s", "k")
        assert cfg.section_count == 0


# =============================================================================
# Validation Tests
# =============================================================================


class TestValidation:
    """Test validation."""

    def test_valid(self):
        cfg = ConfigManager()
        cfg.require("models", "provider")
        cfg.set("models", "provider", "claude")
        result = cfg.validate()
        assert result.is_valid is True

    def test_missing_required(self):
        cfg = ConfigManager()
        cfg.require("models", "provider")
        result = cfg.validate()
        assert result.is_valid is False
        assert "models.provider" in result.missing_keys

    def test_multiple_required(self):
        cfg = ConfigManager()
        cfg.require("models", "provider")
        cfg.require("models", "tier")
        cfg.set("models", "provider", "claude")
        result = cfg.validate()
        assert result.is_valid is False
        assert len(result.missing_keys) == 1


# =============================================================================
# Listing Tests
# =============================================================================


class TestListing:
    """Test listing operations."""

    def test_list_sections(self):
        cfg = ConfigManager()
        cfg.set("beta", "k", 1)
        cfg.set("alpha", "k", 2)
        assert cfg.list_sections() == ["alpha", "beta"]

    def test_list_keys(self):
        cfg = ConfigManager()
        cfg.set("s", "b", 1)
        cfg.set("s", "a", 2)
        assert cfg.list_keys("s") == ["a", "b"]

    def test_list_keys_empty(self):
        cfg = ConfigManager()
        assert cfg.list_keys("missing") == []

    def test_get_section(self):
        cfg = ConfigManager()
        cfg.set("s", "a", 1)
        cfg.set("s", "b", 2)
        section = cfg.get_section("s")
        assert section == {"a": 1, "b": 2}

    def test_get_all(self):
        cfg = ConfigManager()
        cfg.set("s1", "k", 1)
        cfg.set("s2", "k", 2)
        all_cfg = cfg.get_all()
        assert "s1" in all_cfg
        assert "s2" in all_cfg


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_section_count(self):
        cfg = ConfigManager()
        cfg.set("a", "k", 1)
        cfg.set("b", "k", 2)
        assert cfg.section_count == 2

    def test_key_count(self):
        cfg = ConfigManager()
        cfg.set("s", "a", 1)
        cfg.set("s", "b", 2)
        cfg.set("t", "c", 3)
        assert cfg.key_count == 3

    def test_clear(self):
        cfg = ConfigManager()
        cfg.set("s", "k", "v")
        cfg.require("s", "k")
        cfg.clear()
        assert cfg.section_count == 0
        assert cfg.key_count == 0

    def test_to_dict(self):
        cfg = ConfigManager()
        cfg.set("s", "k", "v")
        d = cfg.to_dict()
        assert d["section_count"] == 1
        assert d["key_count"] == 1
        assert "s" in d["sections"]


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global config manager."""

    def test_get_config_manager(self):
        reset_config_manager()
        mgr = get_config_manager()
        assert isinstance(mgr, ConfigManager)

    def test_singleton(self):
        reset_config_manager()
        m1 = get_config_manager()
        m2 = get_config_manager()
        assert m1 is m2

    def test_reset(self):
        reset_config_manager()
        m1 = get_config_manager()
        reset_config_manager()
        m2 = get_config_manager()
        assert m1 is not m2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_utils_package(self):
        from core.utils import (
            ConfigEntry,
            ConfigManager,
            get_config_manager,
            reset_config_manager,
        )

        assert all(
            [
                ConfigManager,
                ConfigEntry,
                get_config_manager,
                reset_config_manager,
            ]
        )

    def test_from_module(self):
        from core.utils.config_manager import (
            ConfigEntry,
            ConfigManager,
            ConfigValidation,
        )

        assert all([ConfigManager, ConfigEntry, ConfigValidation])
