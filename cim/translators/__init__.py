"""Source translators: one per hypervisor / discovery schema, all producing the same CIM.

A translator is selected from `metadata.schema_name` in the discovery payload. Adding a source
means adding a module here and registering it; nothing downstream of the CIM changes.
"""
from __future__ import annotations

from typing import Callable

from cim.schema import CanonicalInfrastructureModel, TargetProvider

Translator = Callable[[dict, TargetProvider | str], CanonicalInfrastructureModel]

DEFAULT_SCHEMA_NAME = "vmware-discovery-stage1"

_REGISTRY: dict[str, Translator] = {}


def register_translator(schema_name: str, translator: Translator) -> None:
    _REGISTRY[schema_name.strip().lower()] = translator


def registered_schemas() -> list[str]:
    return sorted(_REGISTRY)


def resolve_translator(discovery_data: dict) -> tuple[str, Translator]:
    metadata = discovery_data.get("metadata") if isinstance(discovery_data, dict) else None
    schema_name = ""
    if isinstance(metadata, dict):
        schema_name = str(metadata.get("schema_name") or "").strip().lower()
    schema_name = schema_name or DEFAULT_SCHEMA_NAME

    translator = _REGISTRY.get(schema_name)
    if translator is None:
        raise ValueError(
            f"No translator registered for discovery schema '{schema_name}'; known: {', '.join(registered_schemas())}"
        )
    return schema_name, translator


def translate(discovery_data: dict, target_provider: TargetProvider | str) -> CanonicalInfrastructureModel:
    _, translator = resolve_translator(discovery_data)
    return translator(discovery_data, target_provider)


# Built-in sources
from cim.translators import vmware as _vmware  # noqa: E402  (import for side effect: registration)

register_translator(_vmware.SCHEMA_NAME, _vmware.translate_vmware_discovery_to_cim)
register_translator("vmware-discovery", _vmware.translate_vmware_discovery_to_cim)
