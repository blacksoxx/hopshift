from __future__ import annotations

from pathlib import Path
from typing import cast

from loguru import logger

from hopshift.pipeline.state import MigrationState, QuarantineItem
from hopshift.services.compliance.report import build_report
from hopshift.targets import registry as targets
from hopshift.validation.opa_client import evaluate_policies, resolve_policies_dir
from hopshift.validation.tf_runner import validate_hcl


def validator(state: MigrationState) -> MigrationState:
    """Validate generated HCL as a deterministic final gate.

    Terraform init/validate and tflint are delegated to hopshift.validation.tf_runner, which runs
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
            next_state["compliance_result"] = build_report(
                _detect_cloud(hcl_output, next_state), [], [], next_state["validation_result"]
            )
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
        next_state["compliance_result"] = build_report(
            _detect_cloud(hcl_output, next_state), [], [], next_state["validation_result"]
        )
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

    target_spec = _target_for_output(hcl_output)
    if run_tflint and target_spec is not None and not target_spec.tflint:
        if not _get_bool(validation_cfg, f"run_tflint_{target_spec.name}", False):
            logger.info(
                "validator: skipping tflint for {} output (no tflint ruleset; set validation.run_tflint_{}=true to force)",
                target_spec.name, target_spec.name,
            )
            run_tflint = False

    terraform_bin = _get_str(validation_cfg, "terraform_bin", "terraform")
    tflint_bin = _get_str(validation_cfg, "tflint_bin", "tflint")
    opa_bin = _get_str(validation_cfg, "opa_bin", "opa")
    opa_mode = _get_str(validation_cfg, "opa_mode", "binary")
    opa_server_url = _get_str(validation_cfg, "opa_server_url", "")
    policies_dir = resolve_policies_dir(_get_str(validation_cfg, "policies_dir", "hopshift/validation/policies"))

    tf_errors: list[str] = []
    tf_warnings: list[str] = []

    if run_tf_validate or run_tflint:
        tf_result = validate_hcl(
            hcl_output=hcl_output,
            terraform_bin=terraform_bin,
            tflint_bin=tflint_bin,
            run_tflint=run_tflint,
            run_terraform_validate=run_tf_validate,
            plugin_cache_dir=_get_str(validation_cfg, "terraform_plugin_cache_dir", "") or None,
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

    opa_outcome = _run_opa_validation(
        hcl_output=hcl_output,
        opa_mode=opa_mode,
        opa_bin=opa_bin,
        opa_server_url=opa_server_url,
        policies_dir=policies_dir,
        enabled=run_opa,
    )
    opa_passed, opa_errors, opa_warnings = opa_outcome.passed, opa_outcome.errors, opa_outcome.warnings

    errors = [*tf_errors, *opa_errors]
    warnings = [*tf_warnings, *opa_warnings]

    # Enforce-level compliance violations are already deny messages (opa_passed covers them);
    # the report adds the per-control view, including advisory findings that do not fail the gate.
    if not run_opa:
        warnings.append("validator: compliance controls not evaluated because OPA validation is disabled")
    elif not opa_outcome.evaluated:
        warnings.append("validator: compliance controls not evaluated (OPA evaluation failed or no supported cloud detected)")

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

    compliance_result = build_report(
        cloud=_detect_cloud(hcl_output, next_state),
        violations=opa_outcome.violations,
        evaluated=opa_outcome.evaluated,
        validation_result=validation_result,
    )
    next_state["compliance_result"] = compliance_result
    compliance_summary = compliance_result.get("summary", {})

    messages = list(next_state.get("messages", []))
    messages.append(
        "validator: passed={} terraform_validate_passed={} tflint_passed={} opa_passed={}".format(
            passed,
            tf_validate_passed,
            tflint_passed,
            opa_passed,
        )
    )
    messages.append(
        "validator: compliance controls={} passed={} failed={} advisory={} not_applicable={}".format(
            compliance_summary.get("controls", 0),
            compliance_summary.get("passed", 0),
            compliance_summary.get("failed", 0),
            compliance_summary.get("advisory", 0),
            compliance_summary.get("not_applicable", 0),
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


def _target_for_output(hcl_output: dict[str, str]):
    for path in hcl_output:
        spec = targets.by_root(str(path))
        if spec is not None:
            return spec
    return None


_CLOUD_ROOTS = {
    "aws-migration/": "aws",
    "azure-migration/": "azure",
    "gcp-migration/": "gcp",
    "openstack-migration/": "openstack",
}


def _detect_cloud(hcl_output: object, state: MigrationState) -> str:
    """Target cloud for the compliance report: the provider root of the output, else target_provider."""
    if isinstance(hcl_output, dict):
        for path in hcl_output:
            normalized = str(path).replace("\\", "/").lstrip("/")
            for root, cloud in _CLOUD_ROOTS.items():
                if normalized.startswith(root):
                    return cloud

    target = state.get("target_provider")
    if target is None:
        cim = state.get("sized_cim") or state.get("cim")
        target = getattr(cim, "target_provider", None)
    if target is None:
        config = state.get("config", {})
        target = config.get("target_cloud") if isinstance(config, dict) else None
    value = getattr(target, "value", target)
    return str(value).strip().lower() if value else ""


class _OPAOutcome:
    """OPA gate outcome plus the compliance data the report needs."""

    def __init__(
        self,
        passed: bool,
        errors: list[str],
        warnings: list[str],
        violations: list[dict[str, object]] | None = None,
        evaluated: list[str] | None = None,
    ) -> None:
        self.passed = passed
        self.errors = errors
        self.warnings = warnings
        self.violations = violations or []
        self.evaluated = evaluated or []


def _run_opa_validation(
    hcl_output: dict[str, str],
    opa_mode: str,
    opa_bin: str,
    opa_server_url: str,
    policies_dir: Path,
    enabled: bool,
) -> _OPAOutcome:
    if not enabled:
        return _OPAOutcome(True, [], ["validator: OPA validation skipped by config"])

    if not policies_dir.exists():
        return _OPAOutcome(False, [f"OPA policies directory not found: {policies_dir}"], [])

    result = evaluate_policies(
        hcl_output=hcl_output,
        policies_dir=policies_dir,
        mode=opa_mode,
        opa_bin=opa_bin,
        opa_server_url=opa_server_url,
    )

    return _OPAOutcome(
        result.passed,
        list(result.errors),
        list(result.warnings),
        list(result.violations),
        list(result.evaluated),
    )


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
