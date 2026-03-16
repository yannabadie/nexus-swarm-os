"""
Schema Registry - Centralized schema registration and validation.

V12.4 COGNITIVE BOOST - Task #63

Provides a centralized registry for validation schemas used across
NEXUS components. Supports field-level type checking and required fields.

Usage:
    from core.utils.schema_registry import get_schema_registry

    registry = get_schema_registry()

    # Register a schema
    registry.register("swarm_result", {
        "task_id": {"type": "str", "required": True},
        "mode": {"type": "str", "required": True, "choices": ["parallel", "sequential"]},
        "score": {"type": "float", "required": False, "default": 0.0},
    }, component="swarm")

    # Validate data against schema
    result = registry.validate("swarm_result", {"task_id": "t1", "mode": "parallel"})
    assert result.is_valid
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

VALID_TYPES = {"str", "int", "float", "bool", "list", "dict", "any"}


# =============================================================================
# Types
# =============================================================================


@dataclass
class FieldSchema:
    """Schema for a single field."""

    name: str
    field_type: str = "any"
    required: bool = False
    default: Any = None
    choices: list[Any] = field(default_factory=list)
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = {
            "name": self.name,
            "type": self.field_type,
            "required": self.required,
        }
        if self.default is not None:
            d["default"] = self.default
        if self.choices:
            d["choices"] = self.choices
        if self.description:
            d["description"] = self.description
        return d


@dataclass
class SchemaDefinition:
    """A registered schema definition."""

    name: str
    fields: dict[str, FieldSchema]
    component: str = ""
    version: str = "1.0"
    description: str = ""

    @property
    def required_fields(self) -> list[str]:
        return [f.name for f in self.fields.values() if f.required]

    @property
    def optional_fields(self) -> list[str]:
        return [f.name for f in self.fields.values() if not f.required]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "component": self.component,
            "version": self.version,
            "field_count": len(self.fields),
            "required_fields": self.required_fields,
            "optional_fields": self.optional_fields,
        }


@dataclass
class SchemaValidationError:
    """A single validation error."""

    field: str
    error: str
    value: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "error": self.error,
        }


@dataclass
class SchemaValidationResult:
    """Result of validating data against a schema."""

    schema_name: str
    is_valid: bool
    errors: list[SchemaValidationError] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_name": self.schema_name,
            "is_valid": self.is_valid,
            "error_count": len(self.errors),
            "errors": [e.to_dict() for e in self.errors],
        }


# =============================================================================
# Schema Registry
# =============================================================================


class SchemaRegistry:
    """
    Centralized schema registration and validation.

    Features:
    - Register schemas with typed fields
    - Validate data against registered schemas
    - Required/optional field support
    - Type checking (str, int, float, bool, list, dict)
    - Choice validation
    - Component-based organization
    - Schema listing and discovery
    """

    def __init__(self):
        self._schemas: dict[str, SchemaDefinition] = {}
        self._lock = threading.Lock()

    # =========================================================================
    # Register
    # =========================================================================

    def register(
        self,
        name: str,
        fields: dict[str, dict[str, Any]],
        *,
        component: str = "",
        version: str = "1.0",
        description: str = "",
    ) -> SchemaDefinition:
        """
        Register a schema.

        Args:
            name: Schema name (unique identifier)
            fields: Field definitions (name -> {type, required, default, choices})
            component: Component this schema belongs to
            version: Schema version
            description: Human-readable description

        Returns:
            The registered SchemaDefinition
        """
        parsed_fields = {}
        for field_name, field_def in fields.items():
            parsed_fields[field_name] = FieldSchema(
                name=field_name,
                field_type=field_def.get("type", "any"),
                required=field_def.get("required", False),
                default=field_def.get("default"),
                choices=field_def.get("choices", []),
                description=field_def.get("description", ""),
            )

        schema = SchemaDefinition(
            name=name,
            fields=parsed_fields,
            component=component,
            version=version,
            description=description,
        )
        with self._lock:
            self._schemas[name] = schema
        return schema

    def unregister(self, name: str) -> bool:
        """Remove a schema."""
        with self._lock:
            return self._schemas.pop(name, None) is not None

    def is_registered(self, name: str) -> bool:
        """Check if a schema exists."""
        return name in self._schemas

    def get_schema(self, name: str) -> SchemaDefinition | None:
        """Get a schema definition."""
        return self._schemas.get(name)

    # =========================================================================
    # Validate
    # =========================================================================

    def validate(
        self,
        schema_name: str,
        data: dict[str, Any],
    ) -> SchemaValidationResult:
        """
        Validate data against a registered schema.

        Args:
            schema_name: Schema to validate against
            data: Data to validate

        Returns:
            SchemaValidationResult with any errors
        """
        schema = self._schemas.get(schema_name)
        if schema is None:
            return SchemaValidationResult(
                schema_name=schema_name,
                is_valid=False,
                errors=[
                    SchemaValidationError(
                        field="",
                        error=f"Schema '{schema_name}' not registered",
                    )
                ],
            )

        errors = []

        # Check required fields
        for field_name, field_schema in schema.fields.items():
            if field_schema.required and field_name not in data:
                errors.append(
                    SchemaValidationError(
                        field=field_name,
                        error=f"Required field '{field_name}' is missing",
                    )
                )

        # Check field types and choices
        for field_name, value in data.items():
            field_schema = schema.fields.get(field_name)
            if field_schema is None:
                continue  # Extra fields allowed

            # Type check
            type_error = self._check_type(value, field_schema.field_type)
            if type_error:
                errors.append(
                    SchemaValidationError(
                        field=field_name,
                        error=type_error,
                        value=value,
                    )
                )

            # Choice check
            if field_schema.choices and value not in field_schema.choices:
                errors.append(
                    SchemaValidationError(
                        field=field_name,
                        error=f"Value '{value}' not in choices: {field_schema.choices}",
                        value=value,
                    )
                )

        return SchemaValidationResult(
            schema_name=schema_name,
            is_valid=len(errors) == 0,
            errors=errors,
        )

    def _check_type(self, value: Any, expected: str) -> str | None:
        """Check if a value matches the expected type. Returns error or None."""
        if expected == "any":
            return None

        type_map = {
            "str": str,
            "int": int,
            "float": (int, float),
            "bool": bool,
            "list": list,
            "dict": dict,
        }

        expected_type = type_map.get(expected)
        if expected_type is None:
            return None

        # Special case: bool is subclass of int, check bool before int
        if expected == "int" and isinstance(value, bool):
            return "Expected int, got bool"
        if expected == "float" and isinstance(value, bool):
            return "Expected float, got bool"

        if not isinstance(value, expected_type):
            return f"Expected {expected}, got {type(value).__name__}"
        return None

    # =========================================================================
    # Listing
    # =========================================================================

    def list_schemas(
        self,
        *,
        component: str | None = None,
    ) -> list[SchemaDefinition]:
        """List all registered schemas, optionally filtered by component."""
        schemas = list(self._schemas.values())
        if component:
            schemas = [s for s in schemas if s.component == component]
        return sorted(schemas, key=lambda s: s.name)

    def list_components(self) -> list[str]:
        """List all unique components."""
        components = set(s.component for s in self._schemas.values() if s.component)
        return sorted(components)

    # =========================================================================
    # State
    # =========================================================================

    @property
    def schema_count(self) -> int:
        return len(self._schemas)

    def clear(self) -> None:
        """Clear all schemas."""
        with self._lock:
            self._schemas.clear()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_count": self.schema_count,
            "components": self.list_components(),
            "schemas": {name: s.to_dict() for name, s in sorted(self._schemas.items())},
        }


# =============================================================================
# Global Instance
# =============================================================================

_registry: SchemaRegistry | None = None
_registry_lock = threading.Lock()


def get_schema_registry() -> SchemaRegistry:
    """Get or create the global schema registry."""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = SchemaRegistry()
    return _registry


def reset_schema_registry() -> None:
    """Reset the global schema registry (for testing)."""
    global _registry
    _registry = None
