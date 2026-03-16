"""
NexusJSONEncoder - Robust JSON serialization for NEXUS types.

NEXUS V8.4.4 - Blind Spot Remediation Phase 0

This module provides JSON serialization for complex Python types used throughout
NEXUS, including datetime, Enum, UUID, dataclasses, and Pydantic models.

Usage:
    import json
    from core.utils.serialization import NexusJSONEncoder, nexus_dumps

    # Using encoder directly
    json.dumps(data, cls=NexusJSONEncoder)

    # Using convenience function
    nexus_dumps(data)

    # Deserializing with datetime support
    nexus_loads(json_string)

Author: Claude (NEXUS V8.4.4)
Date: 2025-12-10
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID


class NexusJSONEncoder(json.JSONEncoder):
    """
    Custom JSON encoder for NEXUS types.

    Handles serialization of:
    - datetime, date, time -> ISO 8601 format
    - timedelta -> total seconds
    - Enum -> value
    - UUID -> string
    - Path -> string
    - dataclass -> dict (via to_dict() if available, else asdict())
    - Pydantic models -> dict (via model_dump() or dict())
    - Objects with to_dict() method -> dict
    - Sets -> list
    - bytes -> base64 string

    Example:
        >>> import json
        >>> from datetime import datetime
        >>> from enum import Enum
        >>>
        >>> class Status(Enum):
        ...     ACTIVE = "active"
        ...
        >>> data = {"time": datetime.now(), "status": Status.ACTIVE}
        >>> json.dumps(data, cls=NexusJSONEncoder)
        '{"time": "2025-12-10T...", "status": "active"}'
    """

    def default(self, obj: Any) -> Any:
        """
        Convert non-serializable objects to JSON-serializable types.

        Args:
            obj: Object to serialize

        Returns:
            JSON-serializable representation

        Raises:
            TypeError: If object cannot be serialized
        """
        # datetime types -> ISO 8601
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, date):
            return obj.isoformat()
        if isinstance(obj, time):
            return obj.isoformat()
        if isinstance(obj, timedelta):
            return obj.total_seconds()

        # Enum -> value
        if isinstance(obj, Enum):
            return obj.value

        # UUID -> string
        if isinstance(obj, UUID):
            return str(obj)

        # Path -> string
        if isinstance(obj, Path):
            return str(obj)

        # Sets -> list (JSON doesn't support sets)
        if isinstance(obj, (set, frozenset)):
            return list(obj)

        # bytes -> base64
        if isinstance(obj, bytes):
            import base64

            return base64.b64encode(obj).decode("ascii")

        # Objects with to_dict() method (NEXUS convention)
        if hasattr(obj, "to_dict") and callable(obj.to_dict):
            return obj.to_dict()

        # Pydantic models (v2)
        if hasattr(obj, "model_dump") and callable(obj.model_dump):
            return obj.model_dump()

        # Pydantic models (v1)
        if hasattr(obj, "dict") and callable(obj.dict) and hasattr(obj, "__fields__"):
            return obj.dict()

        # Dataclasses without to_dict()
        if is_dataclass(obj) and not isinstance(obj, type):
            return asdict(obj)

        # Fallback to default behavior (will raise TypeError)
        return super().default(obj)


def nexus_dumps(
    obj: Any, *, indent: int | None = 2, ensure_ascii: bool = False, sort_keys: bool = False, **kwargs
) -> str:
    """
    Serialize object to JSON string using NexusJSONEncoder.

    Args:
        obj: Object to serialize
        indent: Indentation level (default: 2 for readability)
        ensure_ascii: If False, allow non-ASCII characters (default: False)
        sort_keys: Sort dictionary keys (default: False)
        **kwargs: Additional arguments passed to json.dumps

    Returns:
        JSON string representation

    Example:
        >>> from datetime import datetime
        >>> nexus_dumps({"time": datetime.now()})
        '{\n  "time": "2025-12-10T..."\n}'
    """
    return json.dumps(
        obj, cls=NexusJSONEncoder, indent=indent, ensure_ascii=ensure_ascii, sort_keys=sort_keys, **kwargs
    )


def nexus_loads(s: str | bytes, *, parse_dates: bool = True, **kwargs) -> Any:
    """
    Deserialize JSON string with optional datetime parsing.

    Args:
        s: JSON string or bytes
        parse_dates: If True, attempt to parse ISO 8601 date strings (default: True)
        **kwargs: Additional arguments passed to json.loads

    Returns:
        Deserialized Python object

    Note:
        Date parsing is best-effort and won't affect non-date strings.
    """

    def object_hook(dct: dict) -> dict:
        """Attempt to parse ISO 8601 date strings in dict values."""
        if not parse_dates:
            return dct

        for key, value in dct.items():
            if isinstance(value, str):
                # Try parsing as datetime
                try:
                    if "T" in value and len(value) >= 19:
                        dct[key] = datetime.fromisoformat(value.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    pass
        return dct

    return json.loads(s, object_hook=object_hook if parse_dates else None, **kwargs)


def serialize_for_checkpoint(obj: Any) -> dict[str, Any]:
    """
    Serialize an object for SagaManager checkpoint storage.

    This function ensures deep serialization of nested objects,
    suitable for atomic JSON storage.

    Args:
        obj: Object to serialize (typically a phase result)

    Returns:
        Dictionary safe for JSON serialization

    Example:
        >>> from core.intelligence.hive_mind.types import IndependentAnalysis
        >>> result = IndependentAnalysis(...)
        >>> checkpoint_data = serialize_for_checkpoint(result)
        >>> json.dumps(checkpoint_data)  # Will not raise TypeError
    """
    if obj is None:
        return None

    # Already a dict
    if isinstance(obj, dict):
        return {k: serialize_for_checkpoint(v) for k, v in obj.items()}

    # List/tuple
    if isinstance(obj, (list, tuple)):
        return [serialize_for_checkpoint(item) for item in obj]

    # Primitive types
    if isinstance(obj, (str, int, float, bool)):
        return obj

    # Use NexusJSONEncoder logic for complex types
    try:
        # First try to_dict() if available
        if hasattr(obj, "to_dict") and callable(obj.to_dict):
            return serialize_for_checkpoint(obj.to_dict())

        # Encode and decode to ensure clean serialization
        json_str = json.dumps(obj, cls=NexusJSONEncoder)
        return json.loads(json_str)
    except (TypeError, ValueError):
        # Last resort: string representation
        return str(obj)


# Type alias for serializable data
SerializableData = dict | list | str | int | float | bool | None


__all__ = [
    "NexusJSONEncoder",
    "nexus_dumps",
    "nexus_loads",
    "serialize_for_checkpoint",
    "SerializableData",
]
