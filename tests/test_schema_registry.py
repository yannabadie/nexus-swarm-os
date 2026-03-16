"""
Tests for V12.4 Schema Registry.

Validates:
- FieldSchema creation and to_dict
- SchemaDefinition properties and to_dict
- SchemaValidationError to_dict
- SchemaValidationResult to_dict
- Register and unregister schemas
- Validate required fields
- Validate field types (str, int, float, bool, list, dict, any)
- Validate choices
- Extra fields allowed
- Schema not registered error
- Listing (schemas, components)
- State management
- Global singleton
- Module exports
"""

from core.utils.schema_registry import (
    FieldSchema,
    SchemaDefinition,
    SchemaRegistry,
    SchemaValidationError,
    SchemaValidationResult,
    get_schema_registry,
    reset_schema_registry,
)

# =============================================================================
# FieldSchema Tests
# =============================================================================


class TestFieldSchema:
    """Test FieldSchema dataclass."""

    def test_basic(self):
        f = FieldSchema(name="task_id", field_type="str", required=True)
        assert f.name == "task_id"
        assert f.required is True

    def test_defaults(self):
        f = FieldSchema(name="k")
        assert f.field_type == "any"
        assert f.required is False
        assert f.choices == []

    def test_to_dict(self):
        f = FieldSchema(name="mode", field_type="str", choices=["a", "b"])
        d = f.to_dict()
        assert d["name"] == "mode"
        assert d["choices"] == ["a", "b"]


# =============================================================================
# SchemaDefinition Tests
# =============================================================================


class TestSchemaDefinition:
    """Test SchemaDefinition dataclass."""

    def test_required_fields(self):
        s = SchemaDefinition(
            name="test",
            fields={
                "a": FieldSchema(name="a", required=True),
                "b": FieldSchema(name="b", required=False),
                "c": FieldSchema(name="c", required=True),
            },
        )
        assert sorted(s.required_fields) == ["a", "c"]

    def test_optional_fields(self):
        s = SchemaDefinition(
            name="test",
            fields={
                "a": FieldSchema(name="a", required=True),
                "b": FieldSchema(name="b", required=False),
            },
        )
        assert s.optional_fields == ["b"]

    def test_to_dict(self):
        s = SchemaDefinition(name="test", fields={}, component="swarm")
        d = s.to_dict()
        assert d["name"] == "test"
        assert d["component"] == "swarm"


# =============================================================================
# Validation Result Tests
# =============================================================================


class TestValidationResult:
    """Test validation result types."""

    def test_error_to_dict(self):
        e = SchemaValidationError(field="name", error="missing")
        d = e.to_dict()
        assert d["field"] == "name"
        assert d["error"] == "missing"

    def test_result_to_dict(self):
        r = SchemaValidationResult(schema_name="test", is_valid=True)
        d = r.to_dict()
        assert d["is_valid"] is True
        assert d["error_count"] == 0


# =============================================================================
# Register Tests
# =============================================================================


class TestRegister:
    """Test schema registration."""

    def test_register(self):
        reg = SchemaRegistry()
        s = reg.register("task", {"id": {"type": "str", "required": True}})
        assert s.name == "task"
        assert reg.schema_count == 1

    def test_register_with_component(self):
        reg = SchemaRegistry()
        s = reg.register("task", {}, component="swarm")
        assert s.component == "swarm"

    def test_register_field_types(self):
        reg = SchemaRegistry()
        s = reg.register(
            "test",
            {
                "name": {"type": "str", "required": True},
                "count": {"type": "int", "default": 0},
                "tags": {"type": "list"},
            },
        )
        assert s.fields["name"].field_type == "str"
        assert s.fields["count"].default == 0

    def test_is_registered(self):
        reg = SchemaRegistry()
        reg.register("test", {})
        assert reg.is_registered("test") is True
        assert reg.is_registered("missing") is False

    def test_get_schema(self):
        reg = SchemaRegistry()
        reg.register("test", {"k": {"type": "str"}})
        s = reg.get_schema("test")
        assert s is not None
        assert "k" in s.fields

    def test_get_schema_not_found(self):
        reg = SchemaRegistry()
        assert reg.get_schema("missing") is None

    def test_unregister(self):
        reg = SchemaRegistry()
        reg.register("test", {})
        assert reg.unregister("test") is True
        assert reg.schema_count == 0

    def test_unregister_not_found(self):
        reg = SchemaRegistry()
        assert reg.unregister("missing") is False


# =============================================================================
# Validate Tests - Required Fields
# =============================================================================


class TestValidateRequired:
    """Test required field validation."""

    def test_all_required_present(self):
        reg = SchemaRegistry()
        reg.register(
            "test",
            {
                "a": {"type": "str", "required": True},
                "b": {"type": "str", "required": True},
            },
        )
        result = reg.validate("test", {"a": "x", "b": "y"})
        assert result.is_valid is True

    def test_missing_required(self):
        reg = SchemaRegistry()
        reg.register(
            "test",
            {
                "a": {"type": "str", "required": True},
            },
        )
        result = reg.validate("test", {})
        assert result.is_valid is False
        assert len(result.errors) == 1
        assert "missing" in result.errors[0].error.lower()

    def test_optional_missing_ok(self):
        reg = SchemaRegistry()
        reg.register(
            "test",
            {
                "a": {"type": "str", "required": False},
            },
        )
        result = reg.validate("test", {})
        assert result.is_valid is True


# =============================================================================
# Validate Tests - Type Checking
# =============================================================================


class TestValidateTypes:
    """Test type checking validation."""

    def test_str_valid(self):
        reg = SchemaRegistry()
        reg.register("t", {"k": {"type": "str"}})
        assert reg.validate("t", {"k": "hello"}).is_valid is True

    def test_str_invalid(self):
        reg = SchemaRegistry()
        reg.register("t", {"k": {"type": "str"}})
        assert reg.validate("t", {"k": 123}).is_valid is False

    def test_int_valid(self):
        reg = SchemaRegistry()
        reg.register("t", {"k": {"type": "int"}})
        assert reg.validate("t", {"k": 42}).is_valid is True

    def test_int_invalid(self):
        reg = SchemaRegistry()
        reg.register("t", {"k": {"type": "int"}})
        assert reg.validate("t", {"k": "not_int"}).is_valid is False

    def test_bool_not_int(self):
        reg = SchemaRegistry()
        reg.register("t", {"k": {"type": "int"}})
        result = reg.validate("t", {"k": True})
        assert result.is_valid is False

    def test_float_valid(self):
        reg = SchemaRegistry()
        reg.register("t", {"k": {"type": "float"}})
        assert reg.validate("t", {"k": 3.14}).is_valid is True

    def test_float_accepts_int(self):
        reg = SchemaRegistry()
        reg.register("t", {"k": {"type": "float"}})
        assert reg.validate("t", {"k": 42}).is_valid is True

    def test_bool_valid(self):
        reg = SchemaRegistry()
        reg.register("t", {"k": {"type": "bool"}})
        assert reg.validate("t", {"k": True}).is_valid is True

    def test_list_valid(self):
        reg = SchemaRegistry()
        reg.register("t", {"k": {"type": "list"}})
        assert reg.validate("t", {"k": [1, 2, 3]}).is_valid is True

    def test_dict_valid(self):
        reg = SchemaRegistry()
        reg.register("t", {"k": {"type": "dict"}})
        assert reg.validate("t", {"k": {"a": 1}}).is_valid is True

    def test_any_accepts_anything(self):
        reg = SchemaRegistry()
        reg.register("t", {"k": {"type": "any"}})
        assert reg.validate("t", {"k": "str"}).is_valid is True
        assert reg.validate("t", {"k": 42}).is_valid is True
        assert reg.validate("t", {"k": [1]}).is_valid is True


# =============================================================================
# Validate Tests - Choices
# =============================================================================


class TestValidateChoices:
    """Test choice validation."""

    def test_valid_choice(self):
        reg = SchemaRegistry()
        reg.register("t", {"mode": {"type": "str", "choices": ["a", "b"]}})
        assert reg.validate("t", {"mode": "a"}).is_valid is True

    def test_invalid_choice(self):
        reg = SchemaRegistry()
        reg.register("t", {"mode": {"type": "str", "choices": ["a", "b"]}})
        result = reg.validate("t", {"mode": "c"})
        assert result.is_valid is False
        assert "not in choices" in result.errors[0].error


# =============================================================================
# Validate Tests - Edge Cases
# =============================================================================


class TestValidateEdge:
    """Test edge cases."""

    def test_extra_fields_allowed(self):
        reg = SchemaRegistry()
        reg.register("t", {"a": {"type": "str"}})
        result = reg.validate("t", {"a": "x", "extra": 42})
        assert result.is_valid is True

    def test_schema_not_registered(self):
        reg = SchemaRegistry()
        result = reg.validate("missing", {"k": "v"})
        assert result.is_valid is False
        assert "not registered" in result.errors[0].error

    def test_empty_data_no_required(self):
        reg = SchemaRegistry()
        reg.register("t", {"k": {"type": "str"}})
        result = reg.validate("t", {})
        assert result.is_valid is True

    def test_multiple_errors(self):
        reg = SchemaRegistry()
        reg.register(
            "t",
            {
                "a": {"type": "str", "required": True},
                "b": {"type": "int", "required": True},
            },
        )
        result = reg.validate("t", {})
        assert len(result.errors) == 2


# =============================================================================
# Listing Tests
# =============================================================================


class TestListing:
    """Test schema listing."""

    def test_list_schemas(self):
        reg = SchemaRegistry()
        reg.register("b_schema", {})
        reg.register("a_schema", {})
        schemas = reg.list_schemas()
        assert [s.name for s in schemas] == ["a_schema", "b_schema"]

    def test_list_schemas_by_component(self):
        reg = SchemaRegistry()
        reg.register("s1", {}, component="swarm")
        reg.register("s2", {}, component="hive")
        reg.register("s3", {}, component="swarm")
        schemas = reg.list_schemas(component="swarm")
        assert len(schemas) == 2

    def test_list_components(self):
        reg = SchemaRegistry()
        reg.register("s1", {}, component="swarm")
        reg.register("s2", {}, component="hive")
        assert reg.list_components() == ["hive", "swarm"]

    def test_list_components_empty(self):
        reg = SchemaRegistry()
        reg.register("s", {})  # No component
        assert reg.list_components() == []


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_schema_count(self):
        reg = SchemaRegistry()
        reg.register("a", {})
        reg.register("b", {})
        assert reg.schema_count == 2

    def test_clear(self):
        reg = SchemaRegistry()
        reg.register("a", {})
        reg.clear()
        assert reg.schema_count == 0

    def test_to_dict(self):
        reg = SchemaRegistry()
        reg.register("test", {}, component="swarm")
        d = reg.to_dict()
        assert d["schema_count"] == 1
        assert "swarm" in d["components"]
        assert "test" in d["schemas"]


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global schema registry."""

    def test_get_schema_registry(self):
        reset_schema_registry()
        reg = get_schema_registry()
        assert isinstance(reg, SchemaRegistry)

    def test_singleton(self):
        reset_schema_registry()
        r1 = get_schema_registry()
        r2 = get_schema_registry()
        assert r1 is r2

    def test_reset(self):
        reset_schema_registry()
        r1 = get_schema_registry()
        reset_schema_registry()
        r2 = get_schema_registry()
        assert r1 is not r2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_utils_package(self):
        from core.utils import (
            SchemaDefinition,
            SchemaRegistry,
            SchemaValidationResult,
            get_schema_registry,
            reset_schema_registry,
        )

        assert all(
            [
                SchemaRegistry,
                SchemaDefinition,
                SchemaValidationResult,
                get_schema_registry,
                reset_schema_registry,
            ]
        )

    def test_from_module(self):
        from core.utils.schema_registry import (
            VALID_TYPES,
        )

        assert "str" in VALID_TYPES
        assert "any" in VALID_TYPES
