from __future__ import annotations

from importlib import import_module
from typing import Callable, cast

from loguru import logger

from hopshift.pipeline.state import MigrationState
from hopshift.targets import registry as targets

SizingLookup = Callable[[int, int], str]


def sizer(state: MigrationState) -> MigrationState:
    """Apply provider sizing lookup for each ComputeUnit in the CIM."""
    next_state = cast(MigrationState, dict(state))

    cim = next_state.get("cim")
    if cim is None:
        raise ValueError("sizer: cim must be present before sizing")

    target_provider = next_state.get("target_provider")
    if target_provider is None:
        raise ValueError("sizer: target_provider is required")

    provider_key = _provider_key(target_provider)
    sizing_lookup = _load_sizing_lookup(provider_key)

    sized_cim = cim.model_copy(deep=True)

    sizing_messages: list[str] = []
    for compute_unit in sized_cim.compute_units:
        instance_type = sizing_lookup(compute_unit.vcpus, compute_unit.ram_mb)
        sizing_messages.append(
            "sizer: compute_unit_id={} vcpus={} ram_mb={} instance_type={}".format(
                compute_unit.id,
                compute_unit.vcpus,
                compute_unit.ram_mb,
                instance_type,
            )
        )

    messages = list(next_state.get("messages", []))
    messages.extend(sizing_messages)

    next_state["sized_cim"] = sized_cim
    next_state["messages"] = messages
    next_state["status"] = "running"

    logger.info(
        "sizer: resolved sizing for {} ComputeUnits using provider {}",
        len(sized_cim.compute_units),
        provider_key,
    )

    return next_state


def _provider_key(provider: object) -> str:
    return str(provider).strip().lower()


def _load_sizing_lookup(provider_key: str) -> SizingLookup:
    try:
        spec = targets.get(provider_key)
    except targets.UnknownTarget as exc:
        raise ValueError(f"sizer: unsupported target_provider '{provider_key}'") from exc
    module_name = f"{spec.package}.sizing_table"

    try:
        module = import_module(module_name)
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            f"sizer: sizing lookup module is missing for provider '{provider_key}'"
        ) from exc

    lookup = getattr(module, "get_instance_type", None)
    if not callable(lookup):
        raise AttributeError(
            f"sizer: module '{module_name}' must define get_instance_type(vcpus: int, ram_mb: int) -> str"
        )

    return cast(SizingLookup, lookup)
