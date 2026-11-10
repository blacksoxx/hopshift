"""Source registry: every discovery format hopshift can translate into the CIM.

A source is identified by the `metadata.schema_name` values its discovery payloads carry and
provides a translator `translate(discovery: dict, target: str) -> CanonicalInfrastructureModel`.
Built-in sources register in `hopshift.sources.__init__`; third-party packages use the
`hopshift.sources` entry-point group, resolving to a `SourceSpec` or a callable returning one.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import Any, Callable

from loguru import logger

from hopshift.cim.schema import CanonicalInfrastructureModel

ENTRY_POINT_GROUP = "hopshift.sources"
TIERS: tuple[str, ...] = ("tested", "validated", "experimental")

Translator = Callable[[dict, str], CanonicalInfrastructureModel]


@dataclass(frozen=True)
class SourceSpec:
    name: str                               # identifier, e.g. "vmware"
    label: str                              # human name
    blurb: str                              # one line: what is discovered
    schema_names: tuple[str, ...]           # metadata.schema_name values this source accepts
    translate: Translator                   # discovery payload + target name -> CIM
    platform: str = ""                      # SourcePlatform value set on the CIM
    tier: str = "experimental"
    collector: str = ""                     # how discovery is produced (e.g. "ansible collection ...")
    docs: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name or self.name != self.name.strip().lower():
            raise ValueError(f"source name must be a lower-case identifier, got {self.name!r}")
        if not self.schema_names:
            raise ValueError(f"source {self.name}: at least one schema name is required")
        if self.tier not in TIERS:
            raise ValueError(f"source {self.name}: tier must be one of {', '.join(TIERS)}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "label": self.label, "blurb": self.blurb, "schema_names": list(self.schema_names),
            "platform": self.platform, "tier": self.tier, "collector": self.collector, "docs": self.docs,
        }


class UnknownSource(ValueError):
    pass


_REGISTRY: dict[str, SourceSpec] = {}
_BY_SCHEMA: dict[str, SourceSpec] = {}
_LOCK = threading.Lock()
_PLUGINS_LOADED = False


def register(spec: SourceSpec, *, replace: bool = False) -> SourceSpec:
    with _LOCK:
        if spec.name in _REGISTRY and not replace and _REGISTRY[spec.name] != spec:
            raise ValueError(f"source {spec.name} is already registered")
        _REGISTRY[spec.name] = spec
        for schema in spec.schema_names:
            _BY_SCHEMA[schema.strip().lower()] = spec
    return spec


def load_plugins() -> list[str]:
    global _PLUGINS_LOADED
    with _LOCK:
        if _PLUGINS_LOADED:
            return []
        _PLUGINS_LOADED = True
    loaded: list[str] = []
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        try:
            obj = ep.load()
            spec = obj() if callable(obj) and not isinstance(obj, SourceSpec) else obj
            if not isinstance(spec, SourceSpec):
                raise TypeError(f"entry point {ep.name} did not produce a SourceSpec")
            register(spec, replace=True)
            loaded.append(spec.name)
        except Exception as exc:  # noqa: BLE001
            logger.error("sources: plugin {} failed to load: {}", ep.name, exc)
    return loaded


def get(name: str) -> SourceSpec:
    load_plugins()
    spec = _REGISTRY.get(str(name or "").strip().lower())
    if spec is None:
        raise UnknownSource(f"unknown source '{name}'; known: {', '.join(names())}")
    return spec


def for_schema(schema_name: str) -> SourceSpec:
    load_plugins()
    spec = _BY_SCHEMA.get(str(schema_name or "").strip().lower())
    if spec is None:
        raise UnknownSource(f"No translator registered for discovery schema '{schema_name}'; known: {', '.join(schema_names())}")
    return spec


def names() -> list[str]:
    load_plugins()
    return sorted(_REGISTRY)


def schema_names() -> list[str]:
    load_plugins()
    return sorted(_BY_SCHEMA)


def all_specs() -> list[SourceSpec]:
    load_plugins()
    return [_REGISTRY[name] for name in sorted(_REGISTRY)]
