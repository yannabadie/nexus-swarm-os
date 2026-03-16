"""
Tests for V12.4 Structured Output Validator.

Validates:
- Field definition and constraints
- Schema creation and queries
- JSON parsing and validation
- Required/optional field checks
- Type validation (str, int, float, bool, dict, list, any)
- Value range constraints (min/max)
- Length constraints (min/max)
- Regex pattern matching
- Enum value constraints
- Extra field detection
- Custom validation rules
- Extract-and-validate from prose
- Schema registration and reuse
- Module exports
"""

from core.utils.output_validator import (
    VALID_TYPES,
    Field,
    OutputValidator,
    Schema,
    ValidationError,
    ValidationResult,
    _check_type,
)

# =============================================================================
# Field Tests
# =============================================================================


class TestField:
    """Test Field dataclass."""

    def test_basic_creation(self):
        f = Field("name", field_type="str", required=True)
        assert f.name == "name"
        assert f.field_type == "str"
        assert f.required is True

    def test_defaults(self):
        f = Field("x")
        assert f.field_type == "any"
        assert f.required is True
        assert f.default is None

    def test_to_dict(self):
        f = Field("score", field_type="float", min_value=0.0, max_value=1.0)
        d = f.to_dict()
        assert d["name"] == "score"
        assert d["type"] == "float"
        assert d["min_value"] == 0.0

    def test_enum_in_dict(self):
        f = Field("status", enum_values=["ok", "error"])
        d = f.to_dict()
        assert d["enum"] == ["ok", "error"]


# =============================================================================
# Schema Tests
# =============================================================================


class TestSchema:
    """Test Schema dataclass."""

    def test_basic_creation(self):
        s = Schema(
            name="test",
            fields=[
                Field("a", required=True),
                Field("b", required=False),
            ],
        )
        assert s.name == "test"
        assert len(s.fields) == 2

    def test_required_fields(self):
        s = Schema(
            name="test",
            fields=[
                Field("a", required=True),
                Field("b", required=False),
                Field("c", required=True),
            ],
        )
        assert s.required_fields == ["a", "c"]

    def test_field_names(self):
        s = Schema(
            name="test",
            fields=[
                Field("x"),
                Field("y"),
                Field("z"),
            ],
        )
        assert s.field_names == ["x", "y", "z"]

    def test_get_field(self):
        s = Schema(name="test", fields=[Field("name", field_type="str")])
        f = s.get_field("name")
        assert f is not None
        assert f.field_type == "str"

    def test_get_field_not_found(self):
        s = Schema(name="test", fields=[])
        assert s.get_field("missing") is None

    def test_to_dict(self):
        s = Schema(name="test", fields=[Field("a")])
        d = s.to_dict()
        assert d["name"] == "test"
        assert len(d["fields"]) == 1


# =============================================================================
# Type Checking Tests
# =============================================================================


class TestTypeChecking:
    """Test type checking utilities."""

    def test_str_type(self):
        assert _check_type("hello", "str") is True
        assert _check_type(123, "str") is False

    def test_int_type(self):
        assert _check_type(42, "int") is True
        assert _check_type(3.14, "int") is False
        assert _check_type(True, "int") is False  # bool is not int

    def test_float_type(self):
        assert _check_type(3.14, "float") is True
        assert _check_type(42, "float") is True  # int acceptable
        assert _check_type("3.14", "float") is False
        assert _check_type(True, "float") is False

    def test_bool_type(self):
        assert _check_type(True, "bool") is True
        assert _check_type(False, "bool") is True
        assert _check_type(1, "bool") is False

    def test_dict_type(self):
        assert _check_type({"a": 1}, "dict") is True
        assert _check_type([1, 2], "dict") is False

    def test_list_type(self):
        assert _check_type([1, 2], "list") is True
        assert _check_type({"a": 1}, "list") is False

    def test_any_type(self):
        assert _check_type("hello", "any") is True
        assert _check_type(42, "any") is True
        assert _check_type(None, "any") is True


# =============================================================================
# JSON Validation Tests
# =============================================================================


class TestJSONValidation:
    """Test JSON parsing and validation."""

    def test_valid_json_no_schema(self):
        v = OutputValidator()
        result = v.validate_json('{"key": "value"}')
        assert result.valid is True
        assert result.data == {"key": "value"}

    def test_invalid_json(self):
        v = OutputValidator()
        result = v.validate_json("not json at all")
        assert result.valid is False
        assert result.error_count > 0

    def test_valid_with_schema(self):
        v = OutputValidator()
        schema = Schema(
            name="test",
            fields=[
                Field("name", field_type="str", required=True),
                Field("value", field_type="int", required=True),
            ],
        )
        result = v.validate_json('{"name": "hello", "value": 42}', schema)
        assert result.valid is True

    def test_missing_required_field(self):
        v = OutputValidator()
        schema = Schema(
            name="test",
            fields=[
                Field("name", field_type="str", required=True),
                Field("value", field_type="int", required=True),
            ],
        )
        result = v.validate_json('{"name": "hello"}', schema)
        assert result.valid is False
        assert any("value" in e.message for e in result.errors)

    def test_optional_field_missing(self):
        v = OutputValidator()
        schema = Schema(
            name="test",
            fields=[
                Field("name", field_type="str", required=True),
                Field("desc", field_type="str", required=False),
            ],
        )
        result = v.validate_json('{"name": "hello"}', schema)
        assert result.valid is True

    def test_wrong_type(self):
        v = OutputValidator()
        schema = Schema(
            name="test",
            fields=[
                Field("count", field_type="int", required=True),
            ],
        )
        result = v.validate_json('{"count": "not a number"}', schema)
        assert result.valid is False

    def test_json_array_rejected_for_schema(self):
        v = OutputValidator()
        schema = Schema(name="test", fields=[Field("x")])
        result = v.validate_json("[1, 2, 3]", schema)
        assert result.valid is False
        assert any("object" in e.message.lower() for e in result.errors)


# =============================================================================
# Constraint Tests
# =============================================================================


class TestConstraints:
    """Test field constraints."""

    def test_min_value(self):
        v = OutputValidator()
        schema = Schema(
            name="test",
            fields=[
                Field("score", field_type="float", min_value=0.0),
            ],
        )
        result = v.validate_json('{"score": -0.5}', schema)
        assert result.valid is False

    def test_max_value(self):
        v = OutputValidator()
        schema = Schema(
            name="test",
            fields=[
                Field("score", field_type="float", max_value=1.0),
            ],
        )
        result = v.validate_json('{"score": 1.5}', schema)
        assert result.valid is False

    def test_value_in_range(self):
        v = OutputValidator()
        schema = Schema(
            name="test",
            fields=[
                Field("score", field_type="float", min_value=0.0, max_value=1.0),
            ],
        )
        result = v.validate_json('{"score": 0.75}', schema)
        assert result.valid is True

    def test_min_length(self):
        v = OutputValidator()
        schema = Schema(
            name="test",
            fields=[
                Field("name", field_type="str", min_length=3),
            ],
        )
        result = v.validate_json('{"name": "ab"}', schema)
        assert result.valid is False

    def test_max_length(self):
        v = OutputValidator()
        schema = Schema(
            name="test",
            fields=[
                Field("name", field_type="str", max_length=5),
            ],
        )
        result = v.validate_json('{"name": "toolong"}', schema)
        assert result.valid is False

    def test_length_in_range(self):
        v = OutputValidator()
        schema = Schema(
            name="test",
            fields=[
                Field("name", field_type="str", min_length=2, max_length=10),
            ],
        )
        result = v.validate_json('{"name": "hello"}', schema)
        assert result.valid is True

    def test_list_length(self):
        v = OutputValidator()
        schema = Schema(
            name="test",
            fields=[
                Field("items", field_type="list", min_length=1, max_length=3),
            ],
        )
        result = v.validate_json('{"items": []}', schema)
        assert result.valid is False

    def test_pattern_match(self):
        v = OutputValidator()
        schema = Schema(
            name="test",
            fields=[
                Field("email", field_type="str", pattern=r"^\S+@\S+\.\S+$"),
            ],
        )
        result = v.validate_json('{"email": "test@example.com"}', schema)
        assert result.valid is True

    def test_pattern_mismatch(self):
        v = OutputValidator()
        schema = Schema(
            name="test",
            fields=[
                Field("email", field_type="str", pattern=r"^\S+@\S+\.\S+$"),
            ],
        )
        result = v.validate_json('{"email": "not-an-email"}', schema)
        assert result.valid is False

    def test_enum_valid(self):
        v = OutputValidator()
        schema = Schema(
            name="test",
            fields=[
                Field("status", field_type="str", enum_values=["ok", "error", "pending"]),
            ],
        )
        result = v.validate_json('{"status": "ok"}', schema)
        assert result.valid is True

    def test_enum_invalid(self):
        v = OutputValidator()
        schema = Schema(
            name="test",
            fields=[
                Field("status", field_type="str", enum_values=["ok", "error"]),
            ],
        )
        result = v.validate_json('{"status": "unknown"}', schema)
        assert result.valid is False


# =============================================================================
# Extra Fields Tests
# =============================================================================


class TestExtraFields:
    """Test extra field detection."""

    def test_extra_allowed_by_default(self):
        v = OutputValidator()
        schema = Schema(
            name="test",
            fields=[
                Field("name", field_type="str"),
            ],
        )
        result = v.validate_json('{"name": "hello", "extra": 42}', schema)
        assert result.valid is True

    def test_extra_rejected(self):
        v = OutputValidator()
        schema = Schema(
            name="test",
            fields=[
                Field("name", field_type="str"),
            ],
            allow_extra_fields=False,
        )
        result = v.validate_json('{"name": "hello", "extra": 42}', schema)
        assert result.valid is False
        assert any("extra" in e.message.lower() for e in result.errors)


# =============================================================================
# Custom Rules Tests
# =============================================================================


class TestCustomRules:
    """Test custom validation rules."""

    def test_custom_rule_pass(self):
        v = OutputValidator()
        schema = Schema(
            name="test",
            fields=[
                Field("start", field_type="int"),
                Field("end", field_type="int"),
            ],
        )
        v.register_schema(schema)
        v.add_rule("test", lambda d: None if d.get("end", 0) > d.get("start", 0) else "end must be > start")
        result = v.validate_json('{"start": 1, "end": 10}', schema)
        assert result.valid is True

    def test_custom_rule_fail(self):
        v = OutputValidator()
        schema = Schema(
            name="test",
            fields=[
                Field("start", field_type="int"),
                Field("end", field_type="int"),
            ],
        )
        v.register_schema(schema)
        v.add_rule("test", lambda d: None if d.get("end", 0) > d.get("start", 0) else "end must be > start")
        result = v.validate_json('{"start": 10, "end": 1}', schema)
        assert result.valid is False
        assert any("end must be" in e.message for e in result.errors)


# =============================================================================
# Schema Registration Tests
# =============================================================================


class TestSchemaRegistration:
    """Test schema registration."""

    def test_register_and_retrieve(self):
        v = OutputValidator()
        schema = Schema(name="tool_call", fields=[Field("name")])
        v.register_schema(schema)
        retrieved = v.get_schema("tool_call")
        assert retrieved is not None
        assert retrieved.name == "tool_call"

    def test_validate_by_name(self):
        v = OutputValidator()
        schema = Schema(
            name="tool_call",
            fields=[
                Field("name", field_type="str", required=True),
            ],
        )
        v.register_schema(schema)
        result = v.validate_json('{"name": "read"}', schema_name="tool_call")
        assert result.valid is True

    def test_validate_unknown_schema_name(self):
        v = OutputValidator()
        result = v.validate_json('{"name": "read"}', schema_name="nonexistent")
        assert result.valid is False

    def test_schema_count(self):
        v = OutputValidator()
        assert v.schema_count == 0
        v.register_schema(Schema(name="a"))
        v.register_schema(Schema(name="b"))
        assert v.schema_count == 2

    def test_list_schemas(self):
        v = OutputValidator()
        v.register_schema(Schema(name="b"))
        v.register_schema(Schema(name="a"))
        assert v.list_schemas() == ["a", "b"]


# =============================================================================
# Extract and Validate Tests
# =============================================================================


class TestExtractAndValidate:
    """Test extract-and-validate from prose."""

    def test_extract_from_prose(self):
        v = OutputValidator()
        schema = Schema(
            name="test",
            fields=[
                Field("action", field_type="str", required=True),
            ],
        )
        text = 'Here is my response: {"action": "read"} Hope that helps!'
        result = v.extract_and_validate(text, schema)
        assert result.valid is True
        assert result.data["action"] == "read"

    def test_extract_direct_json(self):
        v = OutputValidator()
        schema = Schema(name="test", fields=[Field("x")])
        result = v.extract_and_validate('{"x": 1}', schema)
        assert result.valid is True

    def test_extract_no_json(self):
        v = OutputValidator()
        schema = Schema(name="test", fields=[Field("x")])
        result = v.extract_and_validate("No JSON here at all", schema)
        assert result.valid is False


# =============================================================================
# Convenience Methods Tests
# =============================================================================


class TestConvenienceMethods:
    """Test convenience methods."""

    def test_is_valid_json_true(self):
        v = OutputValidator()
        assert v.is_valid_json('{"key": "value"}') is True

    def test_is_valid_json_false(self):
        v = OutputValidator()
        assert v.is_valid_json("not json") is False

    def test_is_valid_json_array(self):
        v = OutputValidator()
        assert v.is_valid_json("[1, 2, 3]") is True

    def test_validate_dict(self):
        v = OutputValidator()
        schema = Schema(
            name="test",
            fields=[
                Field("name", field_type="str", required=True),
            ],
        )
        result = v.validate_dict({"name": "hello"}, schema)
        assert result.valid is True

    def test_to_dict(self):
        v = OutputValidator()
        v.register_schema(Schema(name="test"))
        d = v.to_dict()
        assert d["schema_count"] == 1
        assert "test" in d["schemas"]


# =============================================================================
# ValidationResult Tests
# =============================================================================


class TestValidationResult:
    """Test ValidationResult dataclass."""

    def test_valid_result(self):
        r = ValidationResult(valid=True, data={"key": "value"})
        assert r.error_count == 0
        assert r.error_messages == []

    def test_invalid_result(self):
        r = ValidationResult(
            valid=False,
            errors=[
                ValidationError("field1", "missing"),
                ValidationError("field2", "wrong type"),
            ],
        )
        assert r.error_count == 2
        assert "missing" in r.error_messages

    def test_to_dict(self):
        r = ValidationResult(valid=True, schema_name="test")
        d = r.to_dict()
        assert d["valid"] is True
        assert d["schema_name"] == "test"

    def test_error_to_dict(self):
        e = ValidationError("name", "is required")
        d = e.to_dict()
        assert d["field"] == "name"
        assert d["message"] == "is required"


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_utils_package(self):
        from core.utils import (
            Field,
            OutputValidator,
            Schema,
            ValidationError,
            ValidationResult,
        )

        assert all([OutputValidator, Schema, Field, ValidationResult, ValidationError])

    def test_from_module(self):
        from core.utils.output_validator import (
            Field,
            OutputValidator,
            Schema,
            ValidationError,
            ValidationResult,
        )

        assert all([OutputValidator, Schema, Field, ValidationResult, ValidationError])
        assert "str" in VALID_TYPES
