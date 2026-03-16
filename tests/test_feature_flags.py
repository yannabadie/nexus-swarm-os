"""
Tests for V12.4 Feature Flag System.

Validates:
- Flag definition and defaults
- is_enabled / is_defined queries
- Runtime overrides (set/unset/clear)
- Percentage-based rollout (deterministic)
- Tag-based filtering
- Flag listing and status
- Persistence (save/load)
- Global singleton
- Module exports
"""

import tempfile

from core.utils.feature_flags import (
    FeatureFlags,
    FlagDefinition,
    FlagOverride,
    FlagStatus,
    get_flags,
    reset_flags,
)

# =============================================================================
# FlagDefinition Tests
# =============================================================================


class TestFlagDefinition:
    """Test FlagDefinition dataclass."""

    def test_basic_creation(self):
        f = FlagDefinition(name="test_flag", default=True)
        assert f.name == "test_flag"
        assert f.default is True
        assert f.rollout_pct == 100

    def test_rollout_clamped(self):
        f = FlagDefinition(name="test", rollout_pct=150)
        assert f.rollout_pct == 100
        f2 = FlagDefinition(name="test", rollout_pct=-10)
        assert f2.rollout_pct == 0

    def test_to_dict(self):
        f = FlagDefinition(name="test", default=True, tags=["v12"])
        d = f.to_dict()
        assert d["name"] == "test"
        assert d["default"] is True
        assert d["tags"] == ["v12"]

    def test_from_dict(self):
        data = {"name": "test", "default": True, "rollout_pct": 50}
        f = FlagDefinition.from_dict(data)
        assert f.name == "test"
        assert f.rollout_pct == 50


# =============================================================================
# Define and Query Tests
# =============================================================================


class TestDefineAndQuery:
    """Test flag definition and querying."""

    def test_define_flag(self):
        flags = FeatureFlags(persist=False)
        defn = flags.define("new_feature", default=False, description="A new feature")
        assert defn.name == "new_feature"
        assert flags.flag_count == 1

    def test_is_enabled_default_true(self):
        flags = FeatureFlags(persist=False)
        flags.define("feature", default=True)
        assert flags.is_enabled("feature") is True

    def test_is_enabled_default_false(self):
        flags = FeatureFlags(persist=False)
        flags.define("feature", default=False)
        assert flags.is_enabled("feature") is False

    def test_is_enabled_undefined(self):
        flags = FeatureFlags(persist=False)
        assert flags.is_enabled("nonexistent") is False

    def test_is_defined(self):
        flags = FeatureFlags(persist=False)
        flags.define("feature")
        assert flags.is_defined("feature") is True
        assert flags.is_defined("missing") is False

    def test_get_status(self):
        flags = FeatureFlags(persist=False)
        flags.define("feature", default=True, description="Test feature")
        status = flags.get_status("feature")
        assert status is not None
        assert status.enabled is True
        assert status.source == "default"
        assert status.definition.description == "Test feature"

    def test_get_status_not_found(self):
        flags = FeatureFlags(persist=False)
        assert flags.get_status("missing") is None


# =============================================================================
# Override Tests
# =============================================================================


class TestOverrides:
    """Test runtime overrides."""

    def test_set_override(self):
        flags = FeatureFlags(persist=False)
        flags.define("feature", default=False)
        assert flags.set("feature", True, reason="testing") is True
        assert flags.is_enabled("feature") is True

    def test_set_override_undefined(self):
        flags = FeatureFlags(persist=False)
        assert flags.set("nonexistent", True) is False

    def test_override_supersedes_default(self):
        flags = FeatureFlags(persist=False)
        flags.define("feature", default=True)
        flags.set("feature", False)
        assert flags.is_enabled("feature") is False

    def test_unset_override(self):
        flags = FeatureFlags(persist=False)
        flags.define("feature", default=True)
        flags.set("feature", False)
        assert flags.is_enabled("feature") is False
        assert flags.unset("feature") is True
        assert flags.is_enabled("feature") is True

    def test_unset_nonexistent(self):
        flags = FeatureFlags(persist=False)
        assert flags.unset("missing") is False

    def test_clear_overrides(self):
        flags = FeatureFlags(persist=False)
        flags.define("a", default=True)
        flags.define("b", default=True)
        flags.set("a", False)
        flags.set("b", False)
        count = flags.clear_overrides()
        assert count == 2
        assert flags.is_enabled("a") is True
        assert flags.is_enabled("b") is True

    def test_override_count(self):
        flags = FeatureFlags(persist=False)
        flags.define("a")
        flags.define("b")
        flags.set("a", True)
        assert flags.override_count == 1

    def test_status_shows_override(self):
        flags = FeatureFlags(persist=False)
        flags.define("feature", default=False)
        flags.set("feature", True, reason="experiment")
        status = flags.get_status("feature")
        assert status.source == "override"
        assert status.override is not None


# =============================================================================
# Rollout Tests
# =============================================================================


class TestRollout:
    """Test percentage-based rollout."""

    def test_rollout_deterministic(self):
        flags = FeatureFlags(persist=False)
        flags.define("experiment", default=True, rollout_pct=50)
        # Same context key should always get same result
        r1 = flags.is_enabled("experiment", context_key="user_123")
        r2 = flags.is_enabled("experiment", context_key="user_123")
        assert r1 == r2

    def test_rollout_100_always_enabled(self):
        flags = FeatureFlags(persist=False)
        flags.define("feature", default=True, rollout_pct=100)
        # 100% rollout should always return default
        for i in range(20):
            assert flags.is_enabled("feature", context_key=f"user_{i}") is True

    def test_rollout_0_always_disabled(self):
        flags = FeatureFlags(persist=False)
        flags.define("feature", default=True, rollout_pct=0)
        for i in range(20):
            assert flags.is_enabled("feature", context_key=f"user_{i}") is False

    def test_rollout_no_context_uses_default(self):
        flags = FeatureFlags(persist=False)
        flags.define("feature", default=True, rollout_pct=50)
        # Without context_key, should use default
        assert flags.is_enabled("feature") is True

    def test_rollout_distribution(self):
        """Test that rollout roughly matches expected percentage."""
        flags = FeatureFlags(persist=False)
        flags.define("experiment", default=True, rollout_pct=50)
        enabled_count = sum(1 for i in range(1000) if flags.is_enabled("experiment", context_key=f"user_{i}"))
        # Should be roughly 50% (with some tolerance)
        assert 350 < enabled_count < 650


# =============================================================================
# Listing and Filtering Tests
# =============================================================================


class TestListingAndFiltering:
    """Test listing and filtering flags."""

    def test_list_names(self):
        flags = FeatureFlags(persist=False)
        flags.define("c_feature")
        flags.define("a_feature")
        flags.define("b_feature")
        assert flags.list_names() == ["a_feature", "b_feature", "c_feature"]

    def test_list_flags(self):
        flags = FeatureFlags(persist=False)
        flags.define("a", default=True)
        flags.define("b", default=False)
        statuses = flags.list_flags()
        assert len(statuses) == 2

    def test_list_flags_by_tag(self):
        flags = FeatureFlags(persist=False)
        flags.define("a", tags=["v12"])
        flags.define("b", tags=["v13"])
        flags.define("c", tags=["v12", "experimental"])
        statuses = flags.list_flags(tag="v12")
        assert len(statuses) == 2

    def test_list_flags_enabled_only(self):
        flags = FeatureFlags(persist=False)
        flags.define("a", default=True)
        flags.define("b", default=False)
        flags.define("c", default=True)
        statuses = flags.list_flags(enabled_only=True)
        assert len(statuses) == 2

    def test_list_tags(self):
        flags = FeatureFlags(persist=False)
        flags.define("a", tags=["v12", "experimental"])
        flags.define("b", tags=["v12", "stable"])
        tags = flags.list_tags()
        assert tags == ["experimental", "stable", "v12"]


# =============================================================================
# Persistence Tests
# =============================================================================


class TestPersistence:
    """Test flag persistence."""

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            flags_file = f"{tmpdir}/flags.json"

            # Define and override
            flags1 = FeatureFlags(flags_file=flags_file)
            flags1.define("feature", default=True, description="Test")
            flags1.set("feature", False, reason="experiment")

            # Load in new instance
            flags2 = FeatureFlags(flags_file=flags_file)
            assert flags2.is_defined("feature") is True
            assert flags2.is_enabled("feature") is False

    def test_persist_false_no_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            flags_file = f"{tmpdir}/flags.json"
            flags = FeatureFlags(flags_file=flags_file, persist=False)
            flags.define("feature")
            from pathlib import Path

            assert not Path(flags_file).exists()


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_flag_count(self):
        flags = FeatureFlags(persist=False)
        assert flags.flag_count == 0
        flags.define("a")
        flags.define("b")
        assert flags.flag_count == 2

    def test_clear(self):
        flags = FeatureFlags(persist=False)
        flags.define("a")
        flags.set("a", True)
        flags.clear()
        assert flags.flag_count == 0
        assert flags.override_count == 0

    def test_to_dict(self):
        flags = FeatureFlags(persist=False)
        flags.define("feature", default=True)
        d = flags.to_dict()
        assert d["flag_count"] == 1
        assert "feature" in d["flags"]

    def test_status_to_dict(self):
        flags = FeatureFlags(persist=False)
        flags.define("feature", default=True)
        status = flags.get_status("feature")
        d = status.to_dict()
        assert d["name"] == "feature"
        assert d["enabled"] is True
        assert d["source"] == "default"


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global flags."""

    def test_get_flags(self):
        reset_flags()
        f = get_flags()
        assert isinstance(f, FeatureFlags)

    def test_singleton(self):
        reset_flags()
        f1 = get_flags()
        f2 = get_flags()
        assert f1 is f2

    def test_reset(self):
        reset_flags()
        f1 = get_flags()
        reset_flags()
        f2 = get_flags()
        assert f1 is not f2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_utils_package(self):
        from core.utils import FeatureFlags, FlagDefinition, get_flags, reset_flags

        assert all([FeatureFlags, FlagDefinition, get_flags, reset_flags])

    def test_from_module(self):
        from core.utils.feature_flags import (
            FeatureFlags,
            FlagDefinition,
        )

        assert all([FeatureFlags, FlagDefinition, FlagOverride, FlagStatus])
