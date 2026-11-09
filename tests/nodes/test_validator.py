from __future__ import annotations

import shutil

import pytest

from agent.nodes.validator import validator
from cim.schema import (
    CanonicalInfrastructureModel,
    ComputeUnit,
    MigrationStatus,
    NetworkTopology,
    TargetProvider,
)


def _empty_cim() -> CanonicalInfrastructureModel:
    return CanonicalInfrastructureModel(
        source_vcenter="vc01.local",
        target_provider=TargetProvider.AWS,
        network_topology=NetworkTopology(distributed_switches=[]),
        compute_units=[],
    )


def _non_empty_cim() -> CanonicalInfrastructureModel:
    return CanonicalInfrastructureModel(
        source_vcenter="vc01.local",
        target_provider=TargetProvider.AWS,
        network_topology=NetworkTopology(distributed_switches=[]),
        compute_units=[
            ComputeUnit(
                id="cu-1",
                name="app-1",
                vcpus=2,
                ram_mb=4096,
                migration_status=MigrationStatus.READY,
            )
        ],
    )


def test_validator_skips_when_workload_is_empty() -> None:
    state = {
        "sized_cim": _empty_cim(),
        "hcl_output": {},
        "messages": [],
        "status": "pending",
    }

    updated = validator(state)  # type: ignore[arg-type]

    assert updated["status"] == "running"
    assert updated["validation_result"]["passed"] is True
    assert updated["validation_result"]["errors"] == []
    # a compliance report exists for every outcome; nothing was evaluated here
    compliance = updated["compliance_result"]
    assert compliance["cloud"] == "aws"
    assert compliance["summary"]["not_applicable"] == compliance["summary"]["controls"] > 0


def test_validator_fails_empty_hcl_when_workload_exists() -> None:
    state = {
        "sized_cim": _non_empty_cim(),
        "hcl_output": {},
        "messages": [],
        "status": "pending",
    }

    updated = validator(state)  # type: ignore[arg-type]

    assert updated["status"] == "failed"
    assert updated["validation_result"]["passed"] is False
    assert "hcl_output is empty" in updated["validation_result"]["errors"][0]


def test_validator_runs_terraform_inside_provider_root(monkeypatch) -> None:
    """Regression: validator used to run terraform in the workspace root, which has no
    .tf files, so terraform validate passed trivially."""
    import validation.tf_runner as tf_runner

    observed_cwds: list[str] = []

    def _fake_run_command(command: list[str], cwd, env=None) -> tf_runner.CommandResult:
        observed_cwds.append(str(cwd))
        return tf_runner.CommandResult(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(tf_runner, "_run_command", _fake_run_command)

    state = {
        "sized_cim": _non_empty_cim(),
        "hcl_output": {
            "aws-migration/main.tf": 'resource "aws_vpc" "main" { cidr_block = "10.0.0.0/16" }\n',
            "aws-migration/compute/app.tf": "# compute\n",
        },
        "config": {"validation": {"run_tflint": True, "run_opa": False}},
        "messages": [],
        "status": "running",
    }

    updated = validator(state)  # type: ignore[arg-type]

    assert updated["validation_result"]["passed"] is True
    assert updated["status"] == "running"
    # init, validate, tflint
    assert len(observed_cwds) == 3
    assert all(cwd.endswith("aws-migration") for cwd in observed_cwds), observed_cwds


def test_validator_reports_skips_when_all_tools_disabled() -> None:
    state = {
        "sized_cim": _non_empty_cim(),
        "hcl_output": {"aws-migration/main.tf": "# empty\n"},
        "config": {
            "validation": {
                "run_terraform_validate": False,
                "run_tflint": False,
                "run_opa": False,
            }
        },
        "messages": [],
        "status": "running",
    }

    updated = validator(state)  # type: ignore[arg-type]

    result = updated["validation_result"]
    assert result["passed"] is True
    assert any("terraform validate skipped" in w for w in result["warnings"])
    assert any("tflint skipped" in w for w in result["warnings"])
    assert any("OPA validation skipped" in w for w in result["warnings"])
    assert any("compliance controls not evaluated" in w for w in result["warnings"])

    compliance = updated["compliance_result"]
    assert compliance["cloud"] == "aws"
    assert {control["status"] for control in compliance["controls"]} == {"not_applicable"}
    assert compliance["summary"]["failed"] == 0
    assert any("validator: compliance controls=" in message for message in updated["messages"])


def test_validator_builds_compliance_report_from_opa_results(monkeypatch) -> None:
    """The validator turns OPA compliance violations into compliance_result; enforce violations
    are already deny messages, so they fail the gate, while advisory ones only show up in the
    report."""
    from agent.nodes import validator as validator_module
    from validation.opa_client import OPAEvaluationResult

    def _fake_evaluate_policies(**kwargs) -> OPAEvaluationResult:
        deny = 'compliance GCP-VM-OSLOGIN: metadata enable-oslogin must be "TRUE" (google_compute_instance.web)'
        return OPAEvaluationResult(
            passed=False,
            errors=[deny],
            deny_messages=[deny],
            violations=[
                {
                    "control": "GCP-VM-OSLOGIN",
                    "level": "enforce",
                    "resource": "google_compute_instance.web",
                    "file": "gcp-migration/compute_web.tf",
                    "message": 'metadata enable-oslogin must be "TRUE"',
                },
                {
                    "control": "GCP-DISK-CMEK",
                    "level": "advisory",
                    "resource": "google_compute_disk.data",
                    "file": "gcp-migration/storage_web_disks.tf",
                    "message": "no customer-managed KMS key",
                },
            ],
            evaluated=["ALL-TAGS-REQUIRED", "GCP-VM-OSLOGIN", "GCP-DISK-CMEK", "GCP-VM-SHIELDED"],
        )

    monkeypatch.setattr(validator_module, "evaluate_policies", _fake_evaluate_policies)

    state = {
        "sized_cim": _non_empty_cim(),
        "hcl_output": {"gcp-migration/compute_web.tf": "# compute\n"},
        "config": {"validation": {"run_terraform_validate": False, "run_tflint": False, "run_opa": True}},
        "messages": [],
        "quarantine_queue": [],
        "status": "running",
    }

    updated = validator(state)  # type: ignore[arg-type]

    assert updated["status"] == "failed"
    assert updated["validation_result"]["opa_passed"] is False

    compliance = updated["compliance_result"]
    assert compliance["cloud"] == "gcp"
    by_id = {control["id"]: control for control in compliance["controls"]}
    assert by_id["GCP-VM-OSLOGIN"]["status"] == "fail"
    assert by_id["GCP-VM-OSLOGIN"]["resources"] == ["google_compute_instance.web"]
    assert by_id["GCP-DISK-CMEK"]["status"] == "advisory"
    assert by_id["GCP-VM-SHIELDED"]["status"] == "pass"
    assert by_id["GCP-VM-NO-EXTERNAL-IP"]["status"] == "not_applicable"
    assert compliance["summary"]["failed"] == 1
    assert compliance["summary"]["advisory"] == 1
    assert compliance["gate_passed"] is False


@pytest.mark.skipif(shutil.which("terraform") is None, reason="terraform binary not installed")
def test_validator_rejects_broken_nested_hcl_with_real_terraform() -> None:
    """End-to-end regression with the real terraform binary: a syntactically broken file
    under the provider root must fail the final gate (init fails before any provider
    download, so this test needs no network)."""
    state = {
        "sized_cim": _non_empty_cim(),
        "hcl_output": {
            "aws-migration/main.tf": 'resource "aws_vpc" "x" { cidr_block = "10.0.0.0/16" invalid_attr = 1 }\n',
        },
        "config": {"validation": {"run_tflint": False, "run_opa": False}},
        "messages": [],
        "quarantine_queue": [],
        "status": "running",
    }

    updated = validator(state)  # type: ignore[arg-type]

    assert updated["validation_result"]["passed"] is False
    assert updated["validation_result"]["terraform_validate_passed"] is False
    assert updated["status"] == "failed"
    assert any(item["stage"] == "validator" for item in updated["quarantine_queue"])
