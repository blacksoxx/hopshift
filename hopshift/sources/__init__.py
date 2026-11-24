"""Sources: one translator per discovery format, all producing the same CIM.

The translator is selected from `metadata.schema_name` in the discovery payload. Adding a
source means registering a `SourceSpec` (built in below, or through the `hopshift.sources`
entry-point group); nothing downstream of the CIM changes.
"""
from __future__ import annotations

from hopshift.cim.schema import CanonicalInfrastructureModel
from hopshift.sources import registry
from hopshift.sources.registry import SourceSpec, Translator, UnknownSource

DEFAULT_SCHEMA_NAME = "vmware-discovery-stage1"


def register_translator(schema_name: str, translator: Translator, *, name: str | None = None, **meta: object) -> None:
    """Compatibility helper: register a bare translator under one schema name."""
    key = schema_name.strip().lower()
    registry.register(SourceSpec(name=name or key, label=name or key, blurb="", schema_names=(key,), translate=translator, **meta), replace=True)  # type: ignore[arg-type]


def registered_schemas() -> list[str]:
    return registry.schema_names()


def resolve_translator(discovery_data: dict) -> tuple[str, Translator]:
    metadata = discovery_data.get("metadata") if isinstance(discovery_data, dict) else None
    schema_name = ""
    if isinstance(metadata, dict):
        schema_name = str(metadata.get("schema_name") or "").strip().lower()
    schema_name = schema_name or DEFAULT_SCHEMA_NAME
    try:
        spec = registry.for_schema(schema_name)
    except UnknownSource as exc:
        raise ValueError(str(exc)) from exc
    return schema_name, spec.translate


def translate(discovery_data: dict, target_provider: str) -> CanonicalInfrastructureModel:
    _, translator = resolve_translator(discovery_data)
    return translator(discovery_data, target_provider)


# Built-in sources
from hopshift.sources import vmware as _vmware  # noqa: E402  (import for side effect: registration)

registry.register(SourceSpec(
    name="vmware", label="VMware vSphere", blurb="VMs, disks, port groups, distributed switches, DRS clusters",
    schema_names=(_vmware.SCHEMA_NAME, "vmware-discovery"), translate=_vmware.translate_vmware_discovery_to_cim,
    platform=str(_vmware.PLATFORM.value), tier="validated",
    collector="Ansible collection (vmware-discovery-stage1 schema)", docs="docs/sources/vmware.md",
))
