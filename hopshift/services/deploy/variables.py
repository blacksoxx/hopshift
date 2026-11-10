"""Root-module variables: parse `variables.tf` and read / write `terraform.tfvars.json`.

The generated root module declares its inputs in `variables.tf` (see providers/runtime_common.py).
The UI renders a form from the parsed declarations; the values an operator enters are written
to `<run_dir>/deploy/terraform.tfvars.json`, which is copied into the workspace before every
Terraform command (Terraform auto-loads that file name).
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

import hcl2

from hopshift.services.errors import Invalid

MASKED = "***"

# Terraform type constructors we can check cheaply; anything else is accepted as-is.
_PYTHON_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "number": (int, float),
    "bool": (bool,),
    "list": (list,),
    "set": (list,),
    "tuple": (list,),
    "map": (dict,),
    "object": (dict,),
}


def parse_variables_tf(text: str) -> list[dict[str, Any]]:
    """Return one spec per `variable` block: {name, type, description, default, sensitive, required}."""
    if not text.strip():
        return []
    try:
        data = hcl2.loads(text)
    except Exception as exc:  # the lark parser raises several exception types
        raise Invalid(f"variables.tf cannot be parsed: {exc}") from exc

    specs: list[dict[str, Any]] = []
    for block in data.get("variable") or []:
        if not isinstance(block, dict):
            continue
        for name, body in block.items():
            attrs = body if isinstance(body, dict) else {}
            specs.append(
                {
                    "name": str(name),
                    "type": _clean_type(attrs.get("type")),
                    "description": str(attrs.get("description") or ""),
                    "default": attrs.get("default") if "default" in attrs else None,
                    "sensitive": bool(attrs.get("sensitive", False)),
                    "required": "default" not in attrs,
                }
            )
    return specs


def read_tfvars(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise Invalid(f"{path.name} is not valid JSON: {exc}") from exc
    return data if isinstance(data, dict) else {}


def write_tfvars(path: Path, values: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(values, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def merge_values(specs: list[dict[str, Any]], current: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    """Apply `updates` to `current`: unknown names and type mismatches raise Invalid; None unsets."""
    by_name = {spec["name"]: spec for spec in specs}
    unknown = sorted(name for name in updates if name not in by_name)
    if unknown:
        raise Invalid(f"unknown variables: {', '.join(unknown)}; declared: {', '.join(sorted(by_name)) or 'none'}")
    merged = dict(current)
    for name, value in updates.items():
        if value is None:
            merged.pop(name, None)
            continue
        check_value(by_name[name], value)
        merged[name] = value
    return merged


def check_value(spec: dict[str, Any], value: Any) -> None:
    base = str(spec.get("type") or "any").split("(", 1)[0].strip()
    expected = _PYTHON_TYPES.get(base)
    if expected is None:
        return
    ok = isinstance(value, expected) and not (base == "number" and isinstance(value, bool))
    if not ok:
        raise Invalid(f"variable {spec['name']} expects {spec['type']}, got {type(value).__name__}")


def merged_view(specs: list[dict[str, Any]], values: dict[str, Any]) -> list[dict[str, Any]]:
    """Specs plus the current tfvars value for each; sensitive values are masked."""
    items: list[dict[str, Any]] = []
    for spec in specs:
        item = dict(spec)
        is_set = spec["name"] in values
        item["set"] = is_set
        value = values.get(spec["name"]) if is_set else None
        item["value"] = MASKED if (is_set and spec["sensitive"]) else value
        items.append(item)
    return items


def _clean_type(raw: Any) -> str:
    if raw is None:
        return "any"
    text = str(raw).strip()
    if text.startswith("${") and text.endswith("}"):
        text = text[2:-1].strip()
    return text or "any"
