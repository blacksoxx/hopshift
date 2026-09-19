from __future__ import annotations

from pathlib import Path
from typing import cast

from loguru import logger

from agent.state import MigrationState, QuarantineItem
from validation.opa_client import evaluate_policies
from validation.tf_runner import validate_hcl


def validator(state: MigrationState) -> MigrationState:
    """Validate generated HCL as a deterministic final gate.

    Terraform init/validate and tflint are delegated to validation.tf_runner, which runs
    them inside the provider root directory (e.g. aws-migration/). Running them in the
    workspace root would validate an empty module and pass trivially.
    """
    next_state = cast(MigrationState, dict(state))

    hcl_output = next_state.get("hcl_output", {})
    if not isinstance(hcl_output, dict) or not hcl_output:
        if _is_empty_workload(next_state):
            messages = list(next_state.get("messages", []))
            warning_msg = "validator: skipped final validation because CIM workload is empty"
            messages.append(warning_msg)

            next_state["validation_result"] = {
                "passed": True,
                "terraform_validate_passed": True,
                "tflint_passed": True,
                "opa_passed": True,
                "errors": [],
                "warnings": [warning_msg],
            }
            next_state["messages"] = messages
            next_state["status"] = "running"

            logger.info("validator: skipped final validation because CIM workload is empty")
            return next_state

        messages = list(next_state.get("messages", []))
        error_msg = "validator: hcl_output is empty; generation failed before final validation"
        messages.append(error_msg)

        next_state["validation_result"] = {
            "passed": False,
            "terraform_validate_passed": False,
            "tflint_passed": False,
            "opa_passed": False,
            "errors": [error_msg],
            "warnings": [],
        }
        next_state["messages"] = messages
        next_state["status"] = "failed"

        logger.error("validator: no HCL output available for final validation")
        return next_state

    config = next_state.get("config", {})
    if not isinstance(config, dict):
        config = {}

    validation_cfg = _get_mapping(config, "validation")
    run_tf_validate = _get_bool(validation_cfg, "run_terraform_validate", True)
    run_tflint = _get_bool(validation_cfg, "run_tflint", True)
    run_opa = _get_bool(validation_cfg, "run_opa", True)

    if run_tflint and _is_openstack_hcl_output(hcl_output):
        if not _get_bool(validation_cfg, "run_tflint_openstack", False):
            logger.info(
                "validator: skipping tflint for openstack output (set validation.run_tflint_openstack=true to enable)"
            )
            run_tflint = False

    terraform_bin = _get_str(validation_cfg, "terraform_bin", "terraform")
    tflint_bin = _get_str(validation_cfg, "tflint_bin", "tflint")
    opa_bin = _get_str(validation_cfg, "opa_bin", "opa")
    opa_mode = _get_str(validation_cfg, "opa_mode", "binary")
    opa_server_url = _get_str(validation_cfg, "opa_server_url", "")
    policies_dir = Path(_get_str(validation_cfg, "policies_dir", "validation/policies")).resolve()

    tf_errors: list[str] = []
    tf_warnings: list[str] = []

    if run_tf_validate or run_tflint:
        tf_result = validate_hcl(
            hcl_output=hcl_output,
            terraform_bin=terraform_bin,
            tflint_bin=tflint_bin,
            run_tflint=run_tflint,
            run_terraform_validate=run_tf_validate,
        )
        tf_validate_passed = tf_result.terraform_validate_passed
        tflint_passed = tf_result.tflint_passed
        tf_errors = list(tf_result.errors)
        tf_warnings = list(tf_result.warnings)
    else:
        tf_validate_passed = True
        tflint_passed = True
        tf_warnings.append("validator: terraform validate skipped by config")

    if not run_tflint:
        tf_warnings.append("validator: tflint skipped by config")

    opa_passed, opa_errors, opa_warnings = _run_opa_validation(
        hcl_output=hcl_output,
        opa_mode=opa_mode,
        opa_bin=opa_bin,
        opa_server_url=opa_server_url,
        policies_dir=policies_dir,
        enabled=run_opa,
    )

    errors = [*tf_errors, *opa_errors]
    warnings = [*tf_warnings, *opa_warnings]

    passed = tf_validate_passed and tflint_passed and opa_passed

    validation_result = {
        "passed": passed,
        "terraform_validate_passed": tf_validate_passed,
        "tflint_passed": tflint_passed,
        "opa_passed": opa_passed,
        "errors": errors,
        "warnings": warnings,
    }
    next_state["validation_result"] = validation_result

    messages = list(next_state.get("messages", []))
    messages.append(
        "validator: passed={} terraform_validate_passed={} tflint_passed={} opa_passed={}".format(
            passed,
            tf_validate_passed,
            tflint_passed,
            opa_passed,
        )
    )

    if passed:
        next_state["messages"] = messages
        next_state["status"] = "running"
        logger.info("validator: validation passed")
        return next_state

    quarantine_queue = list(next_state.get("quarantine_queue", []))
    quarantine_queue.extend(_build_validator_quarantine_items(next_state, errors))

    messages.append("validator: final deterministic validation failed")

    next_state["quarantine_queue"] = quarantine_queue
    next_state["messages"] = messages
    next_state["status"] = "failed"

    logger.error("validator: final deterministic validation failed")
    return next_state


def _is_empty_workload(state: MigrationState) -> bool:
    cim = state.get("sized_cim") or state.get("cim")
    if cim is None:
        return False

    return (
        len(cim.compute_units) == 0
        and len(cim.clusters) == 0
        and len(cim.network_topology.distributed_switches) == 0
    )


def _is_openstack_hcl_output(hcl_output: dict[str, str]) -> bool:
    return any(str(path).replace("\\", "/").startswith("openstack-migration/") for path in hcl_output)


def _run_opa_validation(
    hcl_output: dict[str, str],
    opa_mode: str,
    opa_bin: str,
    opa_server_url: str,
    policies_dir: Path,
    enabled: bool,
) -> tuple[bool, list[str], list[str]]:
    if not enabled:
        return True, [], ["validator: OPA validation skipped by config"]

    if not policies_dir.exists():
        return False, [f"OPA policies directory not found: {policies_dir}"], []

    result = evaluate_policies(
        hcl_output=hcl_output,
        policies_dir=policies_dir,
        mode=opa_mode,
        opa_bin=opa_bin,
        opa_server_url=opa_server_url,
    )

    return result.passed, list(result.errors), list(result.warnings)


def _build_validator_quarantine_items(
    state: MigrationState,
    errors: list[str],
) -> list[QuarantineItem]:
    cim = state.get("sized_cim") or state.get("cim")
    if cim is None:
        return []

    reason_payload = ["validation_failed", *errors[:5]]

    items: list[QuarantineItem] = []
    for compute_unit in cim.compute_units:
        items.append(
            {
                "compute_unit_id": compute_unit.id,
                "compute_unit_name": compute_unit.name,
                "reasons": reason_payload,
                "stage": "validator",
            }
        )

    return items


def _get_mapping(source: dict[str, object], key: str) -> dict[str, object]:
    value = source.get(key)
    if isinstance(value, dict):
        return cast(dict[str, object], value)
    return {}


def _get_str(source: dict[str, object], key: str, default: str) -> str:
    value = source.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _get_bool(source: dict[str, object], key: str, default: bool) -> bool:
    value = source.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y", "on"}:
            return True
        if lowered in {"false", "0", "no", "n", "off"}:
            return False
    return default
