from __future__ import annotations

from typing import Any

from pydantic import BaseModel


def jsonable(value: Any) -> Any:
    """Pydantic models to dicts, enums to values, recursively."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if hasattr(value, "value") and not isinstance(value, (str, int, float, bool)):
        return getattr(value, "value")
    return value
