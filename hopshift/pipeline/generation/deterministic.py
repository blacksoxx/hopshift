from __future__ import annotations

import re
from collections import defaultdict
from importlib import import_module
from typing import Callable, cast

from hopshift.cim.schema import SUPPORTED_ARCHITECTURES_FOR_X86_TARGETS, CanonicalInfrastructureModel
from hopshift.targets import registry as targets
from hopshift.targets.common import is_bare_expression, safe_file_stem

# Renderers emit logical keys like "<root>/<resource_type>/<name>.tf". Terraform only loads .tf
# files at the root of a module, so the assembler flattens them to "<root>/<resource_type>_<name>.tf".
_LOGICAL_KEY = re.compile(r"^(?P<root>[a-z]+-migration)/(?P<type>[a-z_]+)/(?P<name>[^/]+\.tf)$")

_RENDERER_SPECS: tuple[tuple[str, str, bool], ...] = (
    # (module suffix, function name, accepts required_tags)
    ("network", "render_networking", False),
    ("compute", "render_compute", True),
    ("storage", "render_storage", True),
    ("placement", "render_placement", True),
)



class DeterministicRenderError(ValueError):
    """Raised when the CIM cannot be rendered deterministically for the target provider."""


def render_deterministic(
    provider: str,
    cim: CanonicalInfrastructureModel,
    required_tags: dict[str, str],
) -> dict[str, str]:
    """Render a complete, flat Terraform root module for `provider` from the CIM.

    Returns a mapping of on-disk relative paths to file contents. Raises
    DeterministicRenderError for unsupported providers or CIMs that cannot produce
    unambiguous file names.
    """
    try:
        spec = targets.get(provider)
    except targets.UnknownTarget as exc:
        raise DeterministicRenderError(f"deterministic: unsupported provider '{provider}'") from exc
    normalized_provider = spec.name

    _ensure_unique_compute_unit_names(cim)
    _ensure_supported_architecture(cim)

    # Environment/Owner are emitted as var.environment / var.owner on every resource so operators
    # can override them at plan time; the literal values from the CLI become the variable defaults
    # (rendered by the runtime module, which receives the untouched tags).
    resource_tags = dict(required_tags)
    for tag_key, variable_ref in (("Environment", "var.environment"), ("Owner", "var.owner")):
        if tag_key in resource_tags and not is_bare_expression(resource_tags[tag_key]):
            resource_tags[tag_key] = variable_ref

    logical: dict[str, str] = {}
    for module_suffix, function_name, accepts_tags in _RENDERER_SPECS:
        renderer = _load_renderer(normalized_provider, module_suffix, function_name)
        rendered = renderer(cim, required_tags=resource_tags) if accepts_tags else renderer(cim)
        for key, content in cast(dict[str, str], rendered).items():
            if key in logical:
                raise DeterministicRenderError(f"deterministic: renderer produced duplicate logical key {key}")
            logical[key] = content

    files = _flatten(normalized_provider, logical)

    runtime = _load_renderer(normalized_provider, "runtime", "render_runtime")
    for key, content in cast(dict[str, str], runtime(cim, required_tags=required_tags)).items():
        if key in files:
            raise DeterministicRenderError(f"deterministic: runtime file collides with rendered file {key}")
        files[key] = content

    return dict(sorted(files.items()))


def _flatten(provider: str, logical: dict[str, str]) -> dict[str, str]:
    root = f"{provider}-migration"
    flat: dict[str, str] = {}
    sources: dict[str, str] = {}

    for key, content in logical.items():
        match = _LOGICAL_KEY.match(key)
        if match is None or match.group("root") != root:
            raise DeterministicRenderError(
                f"deterministic: renderer for {provider} produced an unexpected key {key}; "
                f"expected {root}/<resource_type>/<name>.tf"
            )
        flat_name = f"{match.group('type')}_{match.group('name')}"
        flat_key = f"{root}/{flat_name}"
        if flat_key in flat:
            raise DeterministicRenderError(
                f"deterministic: {key} and {sources[flat_key]} both flatten to {flat_key}"
            )
        flat[flat_key] = content
        sources[flat_key] = key

    return flat


def _ensure_supported_architecture(cim: CanonicalInfrastructureModel) -> None:
    """The four supported clouds run x86_64 instances; a Power or Z guest must not be sized onto one."""
    unsupported = sorted(
        {f"{unit.name} ({unit.architecture.value})" for unit in cim.compute_units
         if unit.architecture not in SUPPORTED_ARCHITECTURES_FOR_X86_TARGETS}
    )
    if unsupported:
        raise DeterministicRenderError(
            f"deterministic: {cim.target_provider} cannot host non-x86 ComputeUnits: {', '.join(unsupported)}"
        )


def _ensure_unique_compute_unit_names(cim: CanonicalInfrastructureModel) -> None:
    """Two VMs whose names collapse to the same file stem or Terraform identifier would silently
    overwrite each other's resources; refuse and name them so the operator can rename upstream."""
    by_stem: dict[str, list[str]] = defaultdict(list)
    by_identifier: dict[str, list[str]] = defaultdict(list)

    for compute_unit in cim.compute_units:
        by_stem[safe_file_stem(compute_unit.name).lower()].append(compute_unit.name)
        by_identifier[_terraform_identifier(compute_unit.name)].append(compute_unit.name)

    collisions = {
        key: names for key, names in {**by_stem, **by_identifier}.items() if len(set(names)) > 1 or len(names) > 1
    }
    if collisions:
        detail = "; ".join(f"{key}: {sorted(set(names))}" for key, names in sorted(collisions.items()))
        raise DeterministicRenderError(
            f"deterministic: ComputeUnit names collide after sanitization ({detail}); rename the VMs or disambiguate upstream"
        )


def _load_renderer(provider: str, module_suffix: str, function_name: str) -> Callable[..., dict[str, str]]:
    module_name = f"{targets.get(provider).package}.{module_suffix}"
    try:
        module = import_module(module_name)
    except ModuleNotFoundError as exc:
        raise DeterministicRenderError(f"deterministic: missing renderer module {module_name}") from exc

    renderer = getattr(module, function_name, None)
    if not callable(renderer):
        raise DeterministicRenderError(f"deterministic: {module_name} must define {function_name}()")
    return cast(Callable[..., dict[str, str]], renderer)


def _terraform_identifier(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_]", "_", value.strip())
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    if not normalized:
        return "resource"
    if normalized[0].isdigit():
        normalized = f"r_{normalized}"
    return normalized.lower()
