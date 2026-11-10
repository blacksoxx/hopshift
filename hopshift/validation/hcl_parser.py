"""Parse generated Terraform into a structure policies can reason about.

python-hcl2 returns a faithful tree: block labels and string literals keep their quotes,
blocks are lists of dicts tagged `__is_block__`, and expressions are `${...}` strings.
This module normalizes that into flat lists of resources, data sources, modules and
providers so OPA rules can check attributes per resource instead of matching substrings
in the raw file text.
"""
from __future__ import annotations

import json
from typing import Any

import hcl2

_META_PREFIX = "__"
EXPRESSION_PREFIX = "${"


def parse_hcl_files(hcl_output: dict[str, str]) -> dict[str, Any]:
    """Return the normalized model for a path -> content mapping of .tf files."""
    model: dict[str, Any] = {
        "resources": [],
        "data_sources": [],
        "modules": [],
        "providers": [],
        "required_providers": [],
        "variables": [],
        "outputs": [],
        "parse_errors": [],
    }

    for path in sorted(hcl_output):
        content = hcl_output[path]
        if not str(path).replace("\\", "/").endswith(".tf"):
            continue
        try:
            document = hcl2.loads(content)
        except Exception as exc:  # lark raises several exception types
            model["parse_errors"].append({"file": path, "error": _summarize_error(exc)})
            continue

        for entry in _blocks(document.get("resource")):
            for block_type, named in _labelled_items(entry):
                for name, body in _labelled_items(named):
                    model["resources"].append(_addressed(path, block_type, name, body))

        for entry in _blocks(document.get("data")):
            for block_type, named in _labelled_items(entry):
                for name, body in _labelled_items(named):
                    model["data_sources"].append(_addressed(path, block_type, name, body))

        for section, target in (("module", "modules"), ("provider", "providers"), ("variable", "variables"), ("output", "outputs")):
            for entry in _blocks(document.get(section)):
                for name, body in _labelled_items(entry):
                    model[target].append({"file": path, "name": name, "config": normalize(body)})

        for terraform_block in _blocks(document.get("terraform")):
            for required in _blocks(terraform_block.get("required_providers")):
                for local_name, spec in _labelled_items(required):
                    normalized_spec = normalize(spec) if isinstance(spec, dict) else {"source": normalize(spec)}
                    model["required_providers"].append(
                        {
                            "file": path,
                            "local_name": local_name,
                            "source": normalized_spec.get("source"),
                            "version": normalized_spec.get("version"),
                        }
                    )

    return model


def normalize(value: Any) -> Any:
    """Strip python-hcl2 bookkeeping and quoting so literals become plain values."""
    if isinstance(value, dict):
        return {
            _label(key): normalize(item)
            for key, item in value.items()
            if not str(key).startswith(_META_PREFIX)
        }
    if isinstance(value, list):
        return [normalize(item) for item in value]
    if isinstance(value, str):
        return _unquote(value)
    return value


def is_expression(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(EXPRESSION_PREFIX)


def _addressed(path: str, block_type: str, name: str, body: Any) -> dict[str, Any]:
    return {
        "file": path,
        "type": block_type,
        "name": name,
        "address": f"{block_type}.{name}",
        "config": normalize(body) if isinstance(body, dict) else {},
    }


def _blocks(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _labelled_items(mapping: Any) -> list[tuple[str, Any]]:
    if not isinstance(mapping, dict):
        return []
    return [(_label(key), item) for key, item in mapping.items() if not str(key).startswith(_META_PREFIX)]


def _label(key: Any) -> str:
    return _unquote(str(key))


def _unquote(text: str) -> str:
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        try:
            decoded = json.loads(text)
        except ValueError:
            return text[1:-1]
        return decoded if isinstance(decoded, str) else text[1:-1]
    return text


def _summarize_error(exc: Exception) -> str:
    text = str(exc).strip().splitlines()
    return (text[0] if text else exc.__class__.__name__)[:500]
