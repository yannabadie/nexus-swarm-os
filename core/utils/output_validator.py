"""
Structured Output Validator - Validates LLM responses against expected schemas.

V12.4 COGNITIVE BOOST - Task #44

Catches malformed LLM outputs before they propagate through the system.
Validates JSON structure, required fields, type constraints, and custom rules.

Complements the existing json_extractor.py (which extracts JSON from raw text)
by adding schema-level validation on the extracted data.

Usage:
    from core.utils.output_validator import OutputValidator, Schema, Field

    schema = Schema(
        name="tool_call",
        fields=[
            Field("name", field_type="str", required=True),
            Field("arguments", field_type="dict", required=True),
            Field("confidence", field_type="float", required=False,
                  min_value=0.0, max_value=1.0),
        ],
    )

    validator = OutputValidator()
    result = validator.validate_json('{"name": "read", "arguments": {}}', schema)
    assert result.valid
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

# Supported type names
VALID_TYPES: set[str] = {
    "str",
    "int",
    "float",
    "bool",
    "dict",
    "list",
    "any",
}

# Max nesting depth to prevent infinite recursion
MAX_NESTING_DEPTH = 20


# =============================================================================
# Types
# =============================================================================


@dataclass
class Field:
    """Schema field definition."""

    name: str
    field_type: str = "any"  # str, int, float, bool, dict, list, any
    required: bool = True
    default: Any = None
    min_value: float | None = None
    max_value: float | None = None
    min_length: int | None = None
    max_length: int | None = None
    pattern: str | None = None  # regex pattern for str fields
    enum_values: list[Any] | None = None  # allowed values
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "type": self.field_type,
            "required": self.required,
        }
        if self.min_value is not None:
            d["min_value"] = self.min_value
        if self.max_value is not None:
            d["max_value"] = self.max_value
        if self.enum_values:
            d["enum"] = self.enum_values
        return d


@dataclass
class Schema:
    """Validation schema for structured output."""

    name: str
    fields: list[Field] = field(default_factory=list)
    allow_extra_fields: bool = True
    description: str = ""

    def get_field(self, name: str) -> Field | None:
        for f in self.fields:
            if f.name == name:
                return f
        return None

    @property
    def required_fields(self) -> list[str]:
        return [f.name for f in self.fields if f.required]

    @property
    def field_names(self) -> list[str]:
        return [f.name for f in self.fields]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "fields": [f.to_dict() for f in self.fields],
            "allow_extra_fields": self.allow_extra_fields,
        }


@dataclass
class ValidationError:
    """A single validation error."""

    field: str
    message: str
    value: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "message": self.message,
        }


@dataclass
class ValidationResult:
    """Result of validating structured output."""

    valid: bool
    errors: list[ValidationError] = field(default_factory=list)
    data: dict[str, Any] | None = None  # parsed data if valid
    schema_name: str = ""

    @property
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def error_messages(self) -> list[str]:
        return [e.message for e in self.errors]

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "error_count": self.error_count,
            "errors": [e.to_dict() for e in self.errors],
            "schema_name": self.schema_name,
        }


# =============================================================================
# Type Checking
# =============================================================================

_TYPE_MAP = {
    "str": str,
    "int": int,
    "float": (int, float),  # int is acceptable for float
    "bool": bool,
    "dict": dict,
    "list": list,
    "any": object,
}


def _check_type(value: Any, expected_type: str) -> bool:
    """Check if value matches expected type."""
    if expected_type == "any":
        return True
    if expected_type not in _TYPE_MAP:
        return True  # unknown type, skip check
    expected = _TYPE_MAP[expected_type]
    # Special case: bool is subclass of int in Python
    if expected_type == "int" and isinstance(value, bool):
        return False
    if expected_type == "float" and isinstance(value, bool):
        return False
    return isinstance(value, expected)


# =============================================================================
# Output Validator
# =============================================================================


class OutputValidator:
    """
    Validates LLM output against schemas.

    Supports:
    - JSON parsing and validation
    - Required/optional field checks
    - Type validation (str, int, float, bool, dict, list)
    - Value range constraints (min/max for numbers)
    - Length constraints (min/max for strings and lists)
    - Regex pattern matching for strings
    - Enum value constraints
    - Extra field detection
    - Custom validation rules
    """

    def __init__(self):
        self._schemas: dict[str, Schema] = {}
        self._custom_rules: dict[str, list[Callable]] = {}

    # =========================================================================
    # Schema Registration
    # =========================================================================

    def register_schema(self, schema: Schema) -> None:
        """Register a schema for reuse."""
        self._schemas[schema.name] = schema

    def get_schema(self, name: str) -> Schema | None:
        """Get a registered schema by name."""
        return self._schemas.get(name)

    def add_rule(
        self,
        schema_name: str,
        rule: Callable[[dict[str, Any]], str | None],
    ) -> None:
        """
        Add a custom validation rule for a schema.

        The rule function takes the parsed data dict and returns
        an error message string, or None if valid.
        """
        if schema_name not in self._custom_rules:
            self._custom_rules[schema_name] = []
        self._custom_rules[schema_name].append(rule)

    # =========================================================================
    # Validation
    # =========================================================================

    def validate_json(
        self,
        text: str,
        schema: Schema | None = None,
        *,
        schema_name: str | None = None,
    ) -> ValidationResult:
        """
        Validate JSON text against a schema.

        Args:
            text: JSON string to validate
            schema: Schema to validate against
            schema_name: Name of registered schema (alternative to passing schema)

        Returns:
            ValidationResult
        """
        # Resolve schema
        if schema is None and schema_name:
            schema = self._schemas.get(schema_name)
        if schema is None and schema_name:
            return ValidationResult(
                valid=False,
                errors=[ValidationError("", f"Schema '{schema_name}' not registered")],
                schema_name=schema_name or "",
            )

        # Parse JSON
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            return ValidationResult(
                valid=False,
                errors=[ValidationError("", f"Invalid JSON: {e}")],
                schema_name=schema.name if schema else "",
            )

        if schema is None:
            # No schema - just verify it's valid JSON
            return ValidationResult(valid=True, data=data)

        # Must be a dict for schema validation
        if not isinstance(data, dict):
            return ValidationResult(
                valid=False,
                errors=[ValidationError("", f"Expected object, got {type(data).__name__}")],
                schema_name=schema.name,
            )

        return self._validate_dict(data, schema)

    def validate_dict(
        self,
        data: dict[str, Any],
        schema: Schema,
    ) -> ValidationResult:
        """Validate a dictionary against a schema."""
        return self._validate_dict(data, schema)

    def _validate_dict(
        self,
        data: dict[str, Any],
        schema: Schema,
    ) -> ValidationResult:
        errors: list[ValidationError] = []

        # Check required fields
        for field_name in schema.required_fields:
            if field_name not in data:
                errors.append(
                    ValidationError(
                        field=field_name,
                        message=f"Required field '{field_name}' is missing",
                    )
                )

        # Validate each field that's present
        for f in schema.fields:
            if f.name not in data:
                continue
            value = data[f.name]
            field_errors = self._validate_field(value, f)
            errors.extend(field_errors)

        # Check for extra fields
        if not schema.allow_extra_fields:
            known = set(schema.field_names)
            for key in data:
                if key not in known:
                    errors.append(
                        ValidationError(
                            field=key,
                            message=f"Unexpected field '{key}'",
                            value=key,
                        )
                    )

        # Run custom rules
        rules = self._custom_rules.get(schema.name, [])
        for rule in rules:
            error_msg = rule(data)
            if error_msg:
                errors.append(
                    ValidationError(
                        field="",
                        message=error_msg,
                    )
                )

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            data=data if len(errors) == 0 else None,
            schema_name=schema.name,
        )

    def _validate_field(
        self,
        value: Any,
        f: Field,
    ) -> list[ValidationError]:
        errors = []

        # Type check
        if not _check_type(value, f.field_type):
            errors.append(
                ValidationError(
                    field=f.name,
                    message=f"Field '{f.name}' expected type '{f.field_type}', got '{type(value).__name__}'",
                    value=value,
                )
            )
            return errors  # Skip further checks if type is wrong

        # Numeric range
        if (
            f.min_value is not None
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
            and value < f.min_value
        ):
            errors.append(
                ValidationError(
                    field=f.name,
                    message=f"Field '{f.name}' value {value} below minimum {f.min_value}",
                    value=value,
                )
            )
        if (
            f.max_value is not None
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
            and value > f.max_value
        ):
            errors.append(
                ValidationError(
                    field=f.name,
                    message=f"Field '{f.name}' value {value} above maximum {f.max_value}",
                    value=value,
                )
            )

        # String/list length
        if f.min_length is not None and hasattr(value, "__len__") and len(value) < f.min_length:
            errors.append(
                ValidationError(
                    field=f.name,
                    message=f"Field '{f.name}' length {len(value)} below minimum {f.min_length}",
                    value=value,
                )
            )
        if f.max_length is not None and hasattr(value, "__len__") and len(value) > f.max_length:
            errors.append(
                ValidationError(
                    field=f.name,
                    message=f"Field '{f.name}' length {len(value)} above maximum {f.max_length}",
                    value=value,
                )
            )

        # Regex pattern
        if f.pattern and isinstance(value, str) and not re.search(f.pattern, value):
            errors.append(
                ValidationError(
                    field=f.name,
                    message=f"Field '{f.name}' does not match pattern '{f.pattern}'",
                    value=value,
                )
            )

        # Enum values
        if f.enum_values is not None and value not in f.enum_values:
            errors.append(
                ValidationError(
                    field=f.name,
                    message=f"Field '{f.name}' value '{value}' not in allowed values {f.enum_values}",
                    value=value,
                )
            )

        return errors

    # =========================================================================
    # Convenience Methods
    # =========================================================================

    def is_valid_json(self, text: str) -> bool:
        """Quick check if text is valid JSON."""
        try:
            json.loads(text)
            return True
        except (json.JSONDecodeError, TypeError):
            return False

    def extract_and_validate(
        self,
        text: str,
        schema: Schema,
    ) -> ValidationResult:
        """
        Extract JSON from text (possibly with surrounding prose) and validate.

        Tries to find JSON object in text by looking for { ... }.
        """
        # Try direct parse first
        result = self.validate_json(text, schema)
        if result.valid:
            return result

        # Try extracting JSON from text
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            candidate = text[start : end + 1]
            result = self.validate_json(candidate, schema)
            if result.valid:
                return result

        # Return the original failure
        return self.validate_json(text, schema)

    @property
    def schema_count(self) -> int:
        return len(self._schemas)

    def list_schemas(self) -> list[str]:
        return sorted(self._schemas.keys())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_count": self.schema_count,
            "schemas": {name: schema.to_dict() for name, schema in sorted(self._schemas.items())},
        }
