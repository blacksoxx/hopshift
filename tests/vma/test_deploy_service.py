"""DeployService with a fake `terraform` on PATH (tests/fixtures/fake_terraform.sh)."""
from __future__ import annotations

import json
import os
import shutil
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from agent.runtime import MigrationRuntime, RunRecord
from vma.deploy import DeployService, build_deploy_service
from vma.deploy.terraform import (
    render_backend_override,
    summarize_output,
    summarize_plan,
)
from vma.deploy.variables import parse_variables_tf
from vma.errors import Conflict, Forbidden, Invalid, NotFound
from vma.platform import Platform

REPO_ROOT = Path(__file__).resolve().parents[2]
FAKE_TERRAFORM = REPO_ROOT / "tests" / "fixtures" / "fake_terraform.sh"

VARIABLES_TF = """\
variable "aws_region" {
  type        = string
  description = "AWS region for all migrated resources."
  default     = "us-east-1"
}

variable "image_overrides" {
  type        = map(string)
  description = "AMI id per VMware VM name."
  default     = {}
}

variable "db_password" {
  type        = string
  description = "Database password."
  sensitive   = true
}

variable "instance_count" {
  type    = number
  default = 2
}
"""

PROVIDERS_TF = """\
terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}
"""


@dataclass
class FakeTerraform:
    log_path: Path
    monkeypatch: pytest.MonkeyPatch

    def calls(self) -> list[dict[str, str]]:
        if not self.log_path.is_file():
            return []
        calls = []
        for line in self.log_path.read_text(encoding="utf-8").splitlines():
            calls.append(dict(part.split("=", 1) for part in line.split("\t")))
        return calls

    def argv(self) -> list[str]:
        return [call["argv"] for call in self.calls()]

    def mode(self, name: str) -> None:
        self.monkeypatch.setenv("FAKE_TF_MODE", name)


@dataclass
class FakeConnections:
    """Minimal stand-in for workstream B's connection service."""

    records: dict[str, dict[str, Any]] = field(default_factory=dict)
    env: dict[str, dict[str, str]] = field(default_factory=dict)

    def get(self, connection_id: str) -> dict[str, Any]:
        if connection_id not in self.records:
            raise NotFound(f"unknown connection {connection_id}")
        return self.records[connection_id]

    def terraform_env(self, connection_id: str) -> dict[str, str]:
        self.get(connection_id)
        return dict(self.env.get(connection_id, {}))

    def secret_values(self, connection_id: str) -> list[str]:
        env = self.env.get(connection_id, {})
        return [value for key, value in env.items() if "SECRET" in key or "TOKEN" in key]


@pytest.fixture
def fake_terraform(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeTerraform:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    target = bin_dir / "terraform"
    shutil.copy(FAKE_TERRAFORM, target)
    target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    log_path = tmp_path / "fake-terraform.log"
    monkeypatch.setenv("FAKE_TF_LOG", str(log_path))
    monkeypatch.delenv("FAKE_TF_MODE", raising=False)
    return FakeTerraform(log_path=log_path, monkeypatch=monkeypatch)


def _config(tmp_path: Path, **deploy: Any) -> dict[str, Any]:
    return {
        "runtime": {"runs_dir": str(tmp_path / "runs"), "checkpoint_db": str(tmp_path / "cp.sqlite")},
        "validation": {"terraform_plugin_cache_dir": str(tmp_path / "plugin-cache")},
        "deploy": {"terraform_bin": "terraform", "timeout_minutes": 1, "allow_apply": True, "allow_destroy": True,
                   "remote_state": {"enabled": False, "type": "", "config": {}}, **deploy},
    }


@pytest.fixture
def runtime(tmp_path: Path) -> MigrationRuntime:
    return MigrationRuntime(_config(tmp_path), runs_dir=tmp_path / "runs", checkpoint_db=tmp_path / "cp.sqlite")


@pytest.fixture
def platform(tmp_path: Path, runtime: MigrationRuntime) -> Platform:
    platform = Platform.from_config(_config(tmp_path), db_path=tmp_path / "platform.sqlite")
    assert isinstance(platform.deployments, DeployService)
    platform.extras["runtime"] = runtime
    platform.connections = FakeConnections(
        records={"conn-aws": {"id": "conn-aws", "name": "lab aws", "provider": "aws"},
                 "conn-azure": {"id": "conn-azure", "name": "lab azure", "provider": "azure"}},
        env={"conn-aws": {"AWS_ACCESS_KEY_ID": "AKIAFAKEKEY", "AWS_SECRET_ACCESS_KEY": "s3cr3t-value-xyz", "AWS_SESSION_TOKEN": "tok-abcdef", "AWS_REGION": "us-east-1"}},
    )
    return platform


@pytest.fixture
def service(platform: Platform) -> DeployService:
    return platform.deployments


def make_run(runtime: MigrationRuntime, status: str = "succeeded", cloud: str = "aws", with_tf: bool = True) -> str:
    record = RunRecord(
        run_id=f"20260101T000000Z-{os.urandom(4).hex()}", created_at="2026-01-01T00:00:00+00:00", updated_at="2026-01-01T00:00:00+00:00",
        status=status, cloud=cloud, mode="deterministic", options={}, input_filename="discovery.json", run_dir="/app/output/runs/container-path",
    )
    runtime.store.create(record, {"virtual_machines": []})
    if with_tf:
        root = runtime.store.artifacts_dir(record.run_id) / f"{cloud}-migration"
        root.mkdir(parents=True)
        (root / "providers.tf").write_text(PROVIDERS_TF, encoding="utf-8")
        (root / "variables.tf").write_text(VARIABLES_TF, encoding="utf-8")
        (root / "networking_vpc.tf").write_text('resource "aws_vpc" "main" {\n  cidr_block = "10.0.0.0/16"\n}\n', encoding="utf-8")
    return record.run_id


def wait_done(service: DeployService, run_id: str, deployment_id: str, timeout: float = 15.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        record = service.get(run_id, deployment_id)
        if record["status"] in {"succeeded", "failed", "cancelled"}:
            return record
        time.sleep(0.05)
    raise AssertionError(f"deployment {deployment_id} did not finish: {service.get(run_id, deployment_id)}")


def wait_status(service: DeployService, run_id: str, deployment_id: str, status: str, timeout: float = 10.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        record = service.get(run_id, deployment_id)
        if record["status"] == status:
            return record
        time.sleep(0.05)
    raise AssertionError(f"deployment {deployment_id} did not reach {status}: {service.get(run_id, deployment_id)}")


# ── variables ────────────────────────────────────────────────────────────────


def test_parse_variables_tf_specs() -> None:
    specs = {spec["name"]: spec for spec in parse_variables_tf(VARIABLES_TF)}
    assert specs["aws_region"] == {"name": "aws_region", "type": "string", "description": "AWS region for all migrated resources.", "default": "us-east-1", "sensitive": False, "required": False}
    assert specs["image_overrides"]["type"] == "map(string)" and specs["image_overrides"]["default"] == {}
    assert specs["db_password"]["sensitive"] is True and specs["db_password"]["required"] is True and specs["db_password"]["default"] is None
    assert specs["instance_count"]["type"] == "number" and specs["instance_count"]["default"] == 2
    assert parse_variables_tf("") == []
    with pytest.raises(Invalid):
        parse_variables_tf('variable "x" {')


def test_variables_roundtrip_and_validation(service: DeployService, runtime: MigrationRuntime, platform: Platform) -> None:
    run_id = make_run(runtime)
    initial = service.variables(run_id)
    assert [item["name"] for item in initial] == ["aws_region", "image_overrides", "db_password", "instance_count"]
    assert all(item["set"] is False and item["value"] is None for item in initial)

    updated = {item["name"]: item for item in service.set_variables(run_id, {"aws_region": "eu-west-1", "db_password": "hunter2-xyz", "image_overrides": {"web-01": "ami-1"}}, actor="alice")}
    assert updated["aws_region"]["value"] == "eu-west-1" and updated["aws_region"]["set"] is True
    assert updated["db_password"]["value"] == "***"  # masked in the response
    assert updated["image_overrides"]["value"] == {"web-01": "ami-1"}
    tfvars = json.loads((runtime.store.run_dir(run_id) / "deploy" / "terraform.tfvars.json").read_text(encoding="utf-8"))
    assert tfvars == {"aws_region": "eu-west-1", "db_password": "hunter2-xyz", "image_overrides": {"web-01": "ami-1"}}

    with pytest.raises(Invalid, match="unknown variables: nope"):
        service.set_variables(run_id, {"nope": 1}, actor="alice")
    with pytest.raises(Invalid, match="expects number"):
        service.set_variables(run_id, {"instance_count": "two"}, actor="alice")
    with pytest.raises(Invalid, match="expects map"):
        service.set_variables(run_id, {"image_overrides": ["x"]}, actor="alice")

    after_unset = {item["name"]: item for item in service.set_variables(run_id, {"db_password": None}, actor="alice")}
    assert after_unset["db_password"]["set"] is False
    entries, _ = platform.audit.list(action="variables.updated")
    assert entries and entries[0].details["keys"] == ["db_password"] and entries[0].actor == "alice"


# ── plan ─────────────────────────────────────────────────────────────────────


def test_plan_lifecycle_records_summary_log_and_environment(
    service: DeployService, runtime: MigrationRuntime, platform: Platform, fake_terraform: FakeTerraform, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AWS_PROFILE", "stray-profile")  # must not leak into a connection-backed deployment
    run_id = make_run(runtime)
    service.set_variables(run_id, {"aws_region": "eu-west-1"}, actor="alice")
    artifacts_before = sorted(path.name for path in (runtime.store.artifacts_dir(run_id) / "aws-migration").iterdir())

    queued = service.create(run_id, action="plan", connection_id="conn-aws", actor="alice")
    assert queued["status"] == "queued" and queued["action"] == "plan" and queued["connection_name"] == "lab aws"
    assert queued["provider"] == "aws" and queued["requested_by"] == "alice" and queued["approved_by"] is None
    record = wait_done(service, run_id, queued["id"])

    assert record["status"] == "succeeded", record
    assert record["exit_code"] == 2 and record["error"] is None and record["started_at"] and record["finished_at"]
    assert record["summary"]["add"] == 2 and record["summary"]["change"] == 1 and record["summary"]["destroy"] == 1 and record["summary"]["replace"] == 1
    assert {item["address"] for item in record["summary"]["resources"]} == {"aws_vpc.main", "aws_subnet.a", "aws_instance.web", "aws_instance.old", "aws_ebs_volume.data"}
    assert record["artifacts_hash"]

    argv = fake_terraform.argv()
    assert argv == [
        "init -reconfigure -no-color -input=false",
        "plan -detailed-exitcode -no-color -input=false -out=tfplan",
        "show -json tfplan",
    ]
    run_dir = runtime.store.run_dir(run_id)
    workspace = run_dir / "deploy" / "workspace"
    for call in fake_terraform.calls():
        assert call["cwd"] == str(workspace)
        assert call["TF_DATA_DIR"] == str(run_dir / "deploy" / ".terraform")
        assert call["TF_IN_AUTOMATION"] == "1" and call["TF_INPUT"] == "0"
        assert call["TF_PLUGIN_CACHE_DIR"] == str(tmp_path / "plugin-cache")
        assert call["AWS_ACCESS_KEY_ID"] == "AKIAFAKEKEY"
        assert call["AWS_PROFILE"] == ""
    assert (tmp_path / "plugin-cache").is_dir()

    # workspace is a copy with the backend override and tfvars; artifacts untouched; lock file persisted
    assert (workspace / "providers.tf").is_file() and (workspace / "networking_vpc.tf").is_file()
    override = (workspace / "backend_override.tf").read_text(encoding="utf-8")
    assert 'backend "local"' in override and 'path = "../state/terraform.tfstate"' in override
    assert json.loads((workspace / "terraform.tfvars.json").read_text(encoding="utf-8")) == {"aws_region": "eu-west-1"}
    assert sorted(path.name for path in (runtime.store.artifacts_dir(run_id) / "aws-migration").iterdir()) == artifacts_before
    assert (run_dir / "deploy" / "terraform.lock.hcl").is_file()

    deployment_dir = run_dir / "deploy" / queued["id"]
    assert (deployment_dir / "tfplan").read_text(encoding="utf-8").strip() == "fake-plan"
    mirror = json.loads((deployment_dir / "deployment.json").read_text(encoding="utf-8"))
    assert mirror["status"] == "succeeded" and mirror["id"] == queued["id"]
    assert record["log_path"] == str(deployment_dir / "terraform.log")

    plan = service.plan_json(run_id, queued["id"])
    assert plan["variables"]["db_password"] == {"value": "***"}  # sensitive variable redacted
    assert plan["variables"]["aws_region"] == {"value": "us-east-1"}
    assert len(plan["resource_changes"]) == 6

    log = service.log(run_id, queued["id"])
    assert log["done"] is True and log["next"] == len(log["lines"])
    assert "$ terraform init -reconfigure -no-color -input=false" in log["lines"]
    assert "Plan: 2 to add, 1 to change, 1 to destroy." in log["lines"]
    assert any(line.startswith("## plan summary: 2 to add") for line in log["lines"])
    partial = service.log(run_id, queued["id"], since=log["next"] - 2)
    assert len(partial["lines"]) == 2 and partial["next"] == log["next"]

    listed = service.list(run_id)
    assert [item["id"] for item in listed] == [queued["id"]]
    assert service.has_active(run_id) is False
    actions = [entry.action for entry in platform.audit.iter_all()]
    assert actions[-2:] == ["deployment.requested", "deployment.finished"]
    finished = [entry for entry in platform.audit.iter_all() if entry.action == "deployment.finished"][0]
    assert finished.details["status"] == "succeeded" and finished.details["add"] == 2 and finished.details["deployment_id"] == queued["id"]


def test_plan_with_no_changes_exits_zero(service: DeployService, runtime: MigrationRuntime, fake_terraform: FakeTerraform) -> None:
    fake_terraform.mode("no_changes")
    run_id = make_run(runtime)
    record = wait_done(service, run_id, service.create(run_id, action="plan", connection_id="conn-aws", actor="alice")["id"])
    assert record["status"] == "succeeded" and record["exit_code"] == 0
    with pytest.raises(Invalid, match="no changes"):
        service.create(run_id, action="apply", connection_id="conn-aws", plan_id=record["id"], confirmation=run_id, actor="alice")


def test_init_failure_is_surfaced_in_record_and_log(service: DeployService, runtime: MigrationRuntime, fake_terraform: FakeTerraform) -> None:
    fake_terraform.mode("init_fail")
    run_id = make_run(runtime)
    record = wait_done(service, run_id, service.create(run_id, action="plan", connection_id="conn-aws", actor="alice")["id"])
    assert record["status"] == "failed" and record["exit_code"] == 1
    assert record["error"].startswith("terraform init failed with exit code 1: Error: Failed to query available provider packages")
    assert fake_terraform.argv() == ["init -reconfigure -no-color -input=false"]
    assert "## terraform init: exit code 1" in " ".join(service.log(run_id, record["id"])["lines"])


def test_plan_gates(service: DeployService, runtime: MigrationRuntime, platform: Platform, fake_terraform: FakeTerraform) -> None:
    with pytest.raises(Invalid, match="only a succeeded run"):
        service.create(make_run(runtime, status="paused"), action="plan", connection_id="conn-aws", actor="alice")
    with pytest.raises(Invalid, match="no Terraform root module"):
        service.create(make_run(runtime, with_tf=False), action="plan", connection_id="conn-aws", actor="alice")
    run_id = make_run(runtime)
    with pytest.raises(Invalid, match="action must be one of"):
        service.create(run_id, action="refresh", connection_id="conn-aws", actor="alice")
    with pytest.raises(Invalid, match="connection_id is required"):
        service.create(run_id, action="plan", connection_id=None, actor="alice")
    with pytest.raises(NotFound):
        service.create(run_id, action="plan", connection_id="missing", actor="alice")
    with pytest.raises(Invalid, match="is for azure"):
        service.create(run_id, action="plan", connection_id="conn-azure", actor="alice")
    with pytest.raises(ValueError, match="unknown run"):
        service.create("20260101T000000Z-nothere", action="plan", connection_id="conn-aws", actor="alice")
    denied = [entry for entry in platform.audit.iter_all() if entry.action == "deployment.denied"]
    assert len(denied) == 6 and all(entry.outcome == "denied" for entry in denied)
    assert fake_terraform.argv() == []


def test_only_one_active_deployment_per_run(service: DeployService, runtime: MigrationRuntime, fake_terraform: FakeTerraform) -> None:
    fake_terraform.mode("sleep")
    run_id = make_run(runtime)
    first = service.create(run_id, action="plan", connection_id="conn-aws", actor="alice")
    wait_status(service, run_id, first["id"], "running")
    assert service.has_active(run_id) is True
    with pytest.raises(Conflict, match="already has an active deployment"):
        service.create(run_id, action="plan", connection_id="conn-aws", actor="alice")
    cancelled = service.cancel(run_id, first["id"], actor="alice")
    assert cancelled["status"] == "cancelled"
    assert service.has_active(run_id) is False


# ── apply and destroy ────────────────────────────────────────────────────────


def test_apply_gates_then_apply_and_destroy(service: DeployService, runtime: MigrationRuntime, platform: Platform, fake_terraform: FakeTerraform) -> None:
    run_id = make_run(runtime)
    plan = wait_done(service, run_id, service.create(run_id, action="plan", connection_id="conn-aws", actor="alice")["id"])
    assert plan["status"] == "succeeded"

    with pytest.raises(Invalid, match="requires plan_id"):
        service.create(run_id, action="apply", connection_id="conn-aws", confirmation=run_id, actor="bob")
    with pytest.raises(Invalid, match="is not a plan of run"):
        service.create(run_id, action="apply", connection_id="conn-aws", plan_id="deadbeef", confirmation=run_id, actor="bob")
    with pytest.raises(Forbidden, match="confirmation must equal the run id"):
        service.create(run_id, action="apply", connection_id="conn-aws", plan_id=plan["id"], confirmation="nope", actor="bob")
    other_run = make_run(runtime)
    with pytest.raises(Invalid, match="is not a plan of run"):
        service.create(other_run, action="apply", connection_id="conn-aws", plan_id=plan["id"], confirmation=other_run, actor="bob")

    platform.settings.update({"deploy.allow_apply": False}, actor="admin")
    with pytest.raises(Forbidden, match="deploy.allow_apply"):
        service.create(run_id, action="apply", connection_id="conn-aws", plan_id=plan["id"], confirmation=run_id, actor="bob")
    platform.settings.update({"deploy.allow_apply": None}, actor="admin")

    # artifacts changed since the plan -> stale
    tf = runtime.store.artifacts_dir(run_id) / "aws-migration" / "networking_vpc.tf"
    original = tf.read_text(encoding="utf-8")
    tf.write_text(original + "\n# edited\n", encoding="utf-8")
    with pytest.raises(Invalid, match="changed since plan"):
        service.create(run_id, action="apply", connection_id="conn-aws", plan_id=plan["id"], confirmation=run_id, actor="bob")
    tf.write_text(original, encoding="utf-8")

    denied = [entry for entry in platform.audit.iter_all() if entry.action == "deployment.denied"]
    assert len(denied) == 6 and denied[-1].details["action"] == "apply" and denied[-1].details["plan_id"] == plan["id"]

    fake_terraform.log_path.unlink()
    applied = service.create(run_id, action="apply", connection_id="conn-aws", plan_id=plan["id"], confirmation=run_id, actor="bob")
    assert applied["plan_id"] == plan["id"] and applied["approved_by"] == "bob" and applied["requested_by"] == "bob"
    applied = wait_done(service, run_id, applied["id"])
    assert applied["status"] == "succeeded", applied
    assert fake_terraform.argv() == ["init -reconfigure -no-color -input=false", "apply -no-color -input=false tfplan"]
    assert applied["summary"]["add"] == 2 and applied["summary"]["change"] == 1 and applied["summary"]["destroy"] == 1
    assert len(applied["summary"]["resources"]) == 5  # carried over from the plan
    run_dir = runtime.store.run_dir(run_id)
    assert (run_dir / "deploy" / "workspace" / "tfplan").read_text(encoding="utf-8").strip() == "fake-plan"
    assert (run_dir / "deploy" / "state" / "terraform.tfstate").is_file()
    assert not (runtime.store.artifacts_dir(run_id) / "aws-migration" / "terraform.tfstate").exists()

    state = service.state_summary(run_id)
    assert state["exists"] is True and state["serial"] == 3 and state["terraform_version"] == "1.8.5"
    assert [item["address"] for item in state["resources"]] == ["aws_vpc.main", 'aws_subnet.a["x"]']

    platform.settings.update({"deploy.allow_destroy": False}, actor="admin")
    with pytest.raises(Forbidden, match="deploy.allow_destroy"):
        service.create(run_id, action="destroy", connection_id="conn-aws", confirmation=run_id, actor="bob")
    platform.settings.update({"deploy.allow_destroy": None}, actor="admin")
    with pytest.raises(Forbidden):
        service.create(run_id, action="destroy", connection_id="conn-aws", confirmation=None, actor="bob")

    fake_terraform.log_path.unlink()
    destroyed = wait_done(service, run_id, service.create(run_id, action="destroy", connection_id="conn-aws", confirmation=run_id, actor="bob")["id"])
    assert destroyed["status"] == "succeeded" and destroyed["summary"]["destroy"] == 2
    assert fake_terraform.argv() == ["init -reconfigure -no-color -input=false", "destroy -auto-approve -no-color -input=false"]
    assert service.state_summary(run_id)["resources"] == []
    assert [item["action"] for item in service.list(run_id)] == ["destroy", "apply", "plan"]


def test_apply_failure_keeps_error(service: DeployService, runtime: MigrationRuntime, fake_terraform: FakeTerraform) -> None:
    run_id = make_run(runtime)
    plan = wait_done(service, run_id, service.create(run_id, action="plan", connection_id="conn-aws", actor="alice")["id"])
    fake_terraform.mode("apply_fail")
    applied = wait_done(service, run_id, service.create(run_id, action="apply", connection_id="conn-aws", plan_id=plan["id"], confirmation=run_id, actor="alice")["id"])
    assert applied["status"] == "failed" and applied["exit_code"] == 1
    assert "UnauthorizedOperation" in applied["error"]
    with pytest.raises(NotFound, match="no plan output"):
        service.plan_json(run_id, applied["id"])


# ── cancel, timeout, masking, environment ────────────────────────────────────


def test_cancel_running_deployment(service: DeployService, runtime: MigrationRuntime, platform: Platform, fake_terraform: FakeTerraform) -> None:
    fake_terraform.mode("sleep")
    run_id = make_run(runtime)
    created = service.create(run_id, action="plan", connection_id="conn-aws", actor="alice")
    wait_status(service, run_id, created["id"], "running")
    time.sleep(0.2)  # let the fake reach its sleep
    started = time.monotonic()
    record = service.cancel(run_id, created["id"], actor="alice")
    assert record["status"] == "cancelled", record
    assert time.monotonic() - started < 5
    assert record["finished_at"] and record["exit_code"] is None
    lines = service.log(run_id, created["id"])["lines"]
    assert "## cancel requested" in lines and any("cancelled" in line for line in lines)
    with pytest.raises(Conflict, match="only queued or running"):
        service.cancel(run_id, created["id"], actor="alice")
    assert [entry.action for entry in platform.audit.iter_all()][-3:] == ["deployment.requested", "deployment.cancelled", "deployment.finished"]
    finished = list(platform.audit.iter_all())[-1]
    assert finished.outcome == "cancelled"


def test_timeout_kills_terraform_and_fails(tmp_path: Path, runtime: MigrationRuntime, fake_terraform: FakeTerraform) -> None:
    platform = Platform.from_config(_config(tmp_path, timeout_minutes=0.02), db_path=tmp_path / "p2.sqlite")  # 1.2 s
    platform.extras["runtime"] = runtime
    platform.connections = None
    service = platform.deployments
    fake_terraform.mode("sleep")
    run_id = make_run(runtime)
    record = wait_done(service, run_id, service.create(run_id, action="plan", actor="alice")["id"], timeout=20)
    assert record["status"] == "failed" and "timed out" in record["error"]
    assert "## timeout reached; killing terraform" in service.log(run_id, record["id"])["lines"]


def test_log_masks_connection_secrets_and_secret_assignments(service: DeployService, runtime: MigrationRuntime, fake_terraform: FakeTerraform) -> None:
    fake_terraform.mode("leak")
    run_id = make_run(runtime)
    record = wait_done(service, run_id, service.create(run_id, action="plan", connection_id="conn-aws", actor="alice")["id"])
    text = Path(record["log_path"]).read_text(encoding="utf-8")
    assert "s3cr3t-value-xyz" not in text and "tok-abcdef" not in text and "hunter2-plain" not in text
    assert "aws_secret_access_key = ***" in text and "session token: ***" in text and "db_password = ***" in text
    assert "region = us-east-1" in text
    assert "hunter2-plain" not in (Path(record["log_path"]).parent / "plan.json").read_text(encoding="utf-8")


def test_without_connection_service_the_process_environment_is_inherited(
    tmp_path: Path, runtime: MigrationRuntime, fake_terraform: FakeTerraform, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AWS_PROFILE", "local-profile")
    platform = Platform.from_config(_config(tmp_path), db_path=tmp_path / "p3.sqlite")
    platform.connections = None  # simulate a build without the connections service
    service = build_deploy_service(platform)
    service.bind_runtime(runtime)
    assert platform.connections is None
    run_id = make_run(runtime)
    with pytest.raises(Invalid, match="omit connection_id"):
        service.create(run_id, action="plan", connection_id="conn-aws", actor="alice")
    record = wait_done(service, run_id, service.create(run_id, action="plan", connection_id=None, actor="alice")["id"])
    assert record["status"] == "succeeded" and record["connection_id"] is None and record["provider"] == "aws"
    assert all(call["AWS_PROFILE"] == "local-profile" for call in fake_terraform.calls())


def test_interrupted_deployments_are_failed_on_restart(tmp_path: Path, runtime: MigrationRuntime, platform: Platform, fake_terraform: FakeTerraform) -> None:
    fake_terraform.mode("sleep")
    run_id = make_run(runtime)
    created = platform.deployments.create(run_id, action="plan", connection_id="conn-aws", actor="alice")
    wait_status(platform.deployments, run_id, created["id"], "running")
    restarted = DeployService(platform)  # a new process would see the row still "running"
    record = restarted.get(run_id, created["id"])
    assert record["status"] == "failed" and "interrupted" in record["error"]
    for runner in list(platform.deployments._runners.values()):  # stop the orphaned fake terraform
        runner.cancel()


# ── pure helpers ─────────────────────────────────────────────────────────────


def test_backend_override_rendering() -> None:
    local = render_backend_override({"enabled": False}, "../state/terraform.tfstate")
    assert 'backend "local"' in local and 'path = "../state/terraform.tfstate"' in local
    remote = render_backend_override(
        {"enabled": True, "type": "s3", "config": {"bucket": "tf-state", "key": "vma/run.tfstate", "region": "us-east-1", "encrypt": True, "max_retries": 3}},
        "../state/terraform.tfstate",
    )
    assert 'backend "s3"' in remote and 'bucket = "tf-state"' in remote and "encrypt = true" in remote and "max_retries = 3" in remote
    with pytest.raises(ValueError, match="must be one of s3, azurerm, gcs"):
        render_backend_override({"enabled": True, "type": "consul"}, "x")


def test_plan_and_output_summaries() -> None:
    plan = {"resource_changes": [
        {"address": "a.b", "type": "a", "change": {"actions": ["create"]}},
        {"address": "a.c", "type": "a", "change": {"actions": ["no-op"]}},
        {"address": "a.d", "type": "a", "change": {"actions": ["create", "delete"]}},
        {"address": "a.e", "type": "a", "change": {"actions": ["delete"]}},
    ]}
    summary = summarize_plan(plan)
    assert (summary["add"], summary["change"], summary["destroy"], summary["replace"]) == (1, 0, 1, 1)
    assert [item["address"] for item in summary["resources"]] == ["a.b", "a.d", "a.e"]
    assert summarize_output(["x", "Apply complete! Resources: 3 added, 2 changed, 1 destroyed."])["change"] == 2
    assert summarize_output(["Destroy complete! Resources: 4 destroyed."])["destroy"] == 4
    assert summarize_output(["nothing"])["add"] == 0


def test_remote_state_override_and_state_summary(tmp_path: Path, runtime: MigrationRuntime, fake_terraform: FakeTerraform) -> None:
    config = _config(tmp_path, remote_state={"enabled": True, "type": "gcs", "config": {"bucket": "state-bucket", "prefix": "vma"}})
    platform = Platform.from_config(config, db_path=tmp_path / "p4.sqlite")
    platform.connections = None  # inherit the process environment (no connection)
    platform.extras["runtime"] = runtime
    service = platform.deployments
    run_id = make_run(runtime)
    record = wait_done(service, run_id, service.create(run_id, action="plan", actor="alice")["id"])
    assert record["status"] == "succeeded"
    override = (runtime.store.run_dir(run_id) / "deploy" / "workspace" / "backend_override.tf").read_text(encoding="utf-8")
    assert 'backend "gcs"' in override and 'bucket = "state-bucket"' in override and f'prefix = "vma/{run_id}"' in override  # namespaced per run
    assert service.state_summary(run_id) == {"exists": False, "remote": True, "backend": "gcs"}


def test_remote_state_is_namespaced_per_run() -> None:
    from vma.deploy.terraform import namespace_remote_state, render_backend_override

    assert namespace_remote_state("s3", {"bucket": "b", "key": "envs/prod/terraform.tfstate"}, "run-1")["key"] == "envs/prod/run-1/terraform.tfstate"
    assert namespace_remote_state("azurerm", {"key": "prod.tfstate"}, "run-1")["key"] == "prod/run-1/terraform.tfstate"
    assert namespace_remote_state("gcs", {"bucket": "b"}, "run-1")["prefix"] == "vmware-migration-agent/run-1"
    rendered = render_backend_override({"enabled": True, "type": "s3", "config": {"bucket": "b", "key": "states", "use_lockfile": True}}, "../state/terraform.tfstate", run_id="r9")
    assert 'key = "states/r9/terraform.tfstate"' in rendered and "use_lockfile = true" in rendered
    local = render_backend_override({"enabled": False}, "../state/terraform.tfstate", run_id="r9")
    assert 'backend "local"' in local
