from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from loguru import logger

from agent.state import JSONValue, MigrationState


def ingest(state: MigrationState) -> MigrationState:
    """Load discovery data into MigrationState for downstream deterministic nodes."""
    next_state = cast(MigrationState, dict(state))

    existing_data = next_state.get("discovery_data")
    if _is_valid_discovery_payload(existing_data):
        discovery_data = existing_data
        logger.info("ingest: using discovery data already present in state")
    else:
        discovery_path = _resolve_discovery_path(next_state)
        discovery_data = _read_discovery_file(discovery_path)
        logger.info("ingest: loaded discovery data from {}", discovery_path)

    messages = list(next_state.get("messages", []))
    for warning in validate_discovery_payload(discovery_data):
        logger.warning("ingest: {}", warning)
        messages.append(f"ingest: warning: {warning}")
    messages.append("ingest: discovery data ready")

    next_state["discovery_data"] = discovery_data
    next_state["messages"] = messages
    next_state["status"] = "running"

    return next_state


def _resolve_discovery_path(state: MigrationState) -> Path:
    config = state.get("config", {})
    for key in ("discovery_json_path", "discovery_path", "input_path"):
        value = config.get(key) if isinstance(config, dict) else None
        if isinstance(value, str) and value.strip():
            return Path(value).expanduser().resolve()

    return Path("discovery.json").resolve()


def _read_discovery_file(path: Path) -> dict[str, JSONValue]:
    if not path.exists():
        raise FileNotFoundError(f"Discovery JSON file not found: {path}")

    with path.open("r", encoding="utf-8") as file_handle:
        raw_payload = json.load(file_handle)

    payload = _coerce_json_mapping(raw_payload)
    validate_discovery_payload(payload)

    return payload


EXPECTED_SCHEMA_NAME = "vmware-discovery-stage1"
SUPPORTED_SCHEMA_MAJOR = 1


def validate_discovery_payload(payload: object) -> list[str]:
    """Enforce the minimum discovery contract; raise on structural errors, return warnings.

    See docs/discovery-schema.md. Structural problems (not an object, VM entries that are
    not objects) raise ValueError so the run stops with a clear message instead of a
    silent empty result. Schema drift only warns.
    """
    if not isinstance(payload, dict):
        raise ValueError("Discovery JSON root must be an object")

    vms = payload.get("virtual_machines")
    if not isinstance(vms, list):
        raise ValueError("Discovery JSON must include a 'virtual_machines' list")

    bad_entries = [index for index, vm in enumerate(vms) if not isinstance(vm, dict)]
    if bad_entries:
        raise ValueError(
            f"Discovery JSON 'virtual_machines' entries must be objects; invalid at indexes {bad_entries[:10]}"
        )

    warnings: list[str] = []
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        warnings.append("metadata block is missing; schema name/version and generated_at are unknown")
        metadata = {}

    schema_name = str(metadata.get("schema_name") or "")
    if schema_name and schema_name != EXPECTED_SCHEMA_NAME:
        warnings.append(f"unexpected metadata.schema_name '{schema_name}' (expected '{EXPECTED_SCHEMA_NAME}')")
    elif not schema_name:
        warnings.append("metadata.schema_name is missing")

    schema_version = str(metadata.get("schema_version") or "")
    major = schema_version.split(".")[0] if schema_version else ""
    if major and (not major.isdigit() or int(major) != SUPPORTED_SCHEMA_MAJOR):
        warnings.append(f"unsupported metadata.schema_version '{schema_version}' (supported major: {SUPPORTED_SCHEMA_MAJOR})")

    missing_sizing = [
        str(vm.get("vm_name") or vm.get("name") or f"#{index}")
        for index, vm in enumerate(vms)
        if not vm.get("vcpus") or not vm.get("ram_mb")
    ]
    if missing_sizing:
        warnings.append(
            "vcpus/ram_mb missing for {} VM(s) (defaulted to 1; sizing will be wrong): {}".format(
                len(missing_sizing), ", ".join(missing_sizing[:5])
            )
        )

    if not vms:
        warnings.append("virtual_machines is empty; nothing to migrate")

    return warnings


def _coerce_json_mapping(value: object) -> dict[str, JSONValue]:
    if not isinstance(value, dict):
        raise ValueError("Discovery JSON root must be an object")
    return cast(dict[str, JSONValue], value)


def _is_valid_discovery_payload(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    return isinstance(value.get("virtual_machines"), list)
