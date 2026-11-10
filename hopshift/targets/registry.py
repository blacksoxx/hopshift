"""Target registry: every destination hopshift can render for, built in or installed as a plugin.

A target is a Python package that exposes the renderer modules the deterministic assembler
calls (`network`, `compute`, `storage`, `placement`, `runtime`) and a `sizing_table` with
`get_instance_type(vcpus, ram_mb)`. The registry only holds metadata; the pipeline resolves
modules through `TargetSpec.package`.

Built-in targets register themselves in `hopshift.targets.__init__`. Third-party packages
register through the `hopshift.targets` entry-point group; the entry point must resolve to a
`TargetSpec` or to a zero-argument callable returning one:

    [project.entry-points."hopshift.targets"]
    proxmox = "hopshift_proxmox:TARGET"
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from importlib import import_module
from importlib.metadata import entry_points
from typing import Any, Callable

from loguru import logger

ENTRY_POINT_GROUP = "hopshift.targets"
TIERS: tuple[str, ...] = ("tested", "validated", "experimental")


@dataclass(frozen=True)
class TargetSpec:
    name: str                     # identifier used everywhere: config, API, CLI, file names
    label: str                    # human name shown in the UI
    blurb: str                    # one line: what gets rendered
    package: str                  # python package with network/compute/storage/placement/runtime/sizing_table
    tier: str = "experimental"    # tested | validated | experimental (see docs/support-matrix.md)
    tflint: bool = False          # tflint has rulesets for this target's provider
    connection_provider: str | None = None  # key in the connections catalog, None when deploy is not supported
    architectures: frozenset[str] = frozenset({"x86_64", "unknown"})  # guest architectures the target can host
    docs: str = ""                # relative docs path
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name or self.name != self.name.strip().lower() or "/" in self.name:
            raise ValueError(f"target name must be a lower-case identifier, got {self.name!r}")
        if self.tier not in TIERS:
            raise ValueError(f"target {self.name}: tier must be one of {', '.join(TIERS)}")

    @property
    def root(self) -> str:
        """Root module directory the renderers emit (`<name>-migration/`)."""
        return f"{self.name}-migration"

    def module(self, suffix: str) -> Any:
        return import_module(f"{self.package}.{suffix}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "label": self.label, "blurb": self.blurb, "tier": self.tier, "root": self.root,
            "tflint": self.tflint, "connection_provider": self.connection_provider,
            "architectures": sorted(self.architectures), "docs": self.docs,
        }


class UnknownTarget(ValueError):
    pass


_REGISTRY: dict[str, TargetSpec] = {}
_LOCK = threading.Lock()
_PLUGINS_LOADED = False


def register(spec: TargetSpec, *, replace: bool = False) -> TargetSpec:
    with _LOCK:
        if spec.name in _REGISTRY and not replace and _REGISTRY[spec.name] != spec:
            raise ValueError(f"target {spec.name} is already registered")
        _REGISTRY[spec.name] = spec
    return spec


def load_plugins() -> list[str]:
    """Discover entry points once; returns the names loaded this call."""
    global _PLUGINS_LOADED
    with _LOCK:
        if _PLUGINS_LOADED:
            return []
        _PLUGINS_LOADED = True
    loaded: list[str] = []
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        try:
            obj = ep.load()
            spec = obj() if callable(obj) and not isinstance(obj, TargetSpec) else obj
            if not isinstance(spec, TargetSpec):
                raise TypeError(f"entry point {ep.name} did not produce a TargetSpec")
            register(spec, replace=True)
            loaded.append(spec.name)
        except Exception as exc:  # noqa: BLE001 - a broken plugin must not take the platform down
            logger.error("targets: plugin {} failed to load: {}", ep.name, exc)
    return loaded


def get(name: str) -> TargetSpec:
    load_plugins()
    key = str(name or "").strip().lower()
    spec = _REGISTRY.get(key)
    if spec is None:
        raise UnknownTarget(f"unknown target '{name}'; known: {', '.join(names())}")
    return spec


def names() -> list[str]:
    load_plugins()
    return sorted(_REGISTRY)


def all_specs() -> list[TargetSpec]:
    load_plugins()
    return [_REGISTRY[name] for name in sorted(_REGISTRY)]


def by_root(path: str) -> TargetSpec | None:
    """Find the target whose root directory prefixes a generated file path."""
    normalized = str(path).replace("\\", "/")
    for spec in all_specs():
        if normalized.startswith(spec.root + "/"):
            return spec
    return None


def normalize(name: str) -> str:
    return get(name).name


Loader = Callable[[str], TargetSpec]
