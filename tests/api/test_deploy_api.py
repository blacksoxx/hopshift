"""Deployment endpoints over HTTP with a fake `terraform` on PATH (tests/fixtures/fake_terraform.sh)."""
from __future__ import annotations

import json
import os
import shutil
import stat
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hopshift.api.app import create_app
from hopshift.api.deps import Principal
from hopshift.pipeline.runtime import MigrationRuntime, RunRecord
from hopshift.services.errors import NotFound

REPO_ROOT = Path(__file__).resolve().parents[2]
FAKE_TERRAFORM = REPO_ROOT / "tests" / "fixtures" / "fake_terraform.sh"

VARIABLES_TF = """\
variable "aws_region" {
  type        = string
  description = "AWS region for all migrated resources."
  default     = "us-east-1"
}

variable "db_password" {
  type        = string
  description = "Database password."
  sensitive   = true
}
"""


class FakeConnections:
    def get(self, connection_id: str) -> dict[str, Any]:
        if connection_id != "conn-1":
            raise NotFound(f"unknown connection {connection_id}")
        return {"id": "conn-1", "name": "lab", "provider": "aws"}

    def terraform_env(self, connection_id: str) -> dict[str, str]:
        return {"AWS_ACCESS_KEY_ID": "AKIAFAKE", "AWS_SECRET_ACCESS_KEY": "verysecretvalue", "AWS_REGION": "us-east-1"}

    def secret_values(self, connection_id: str) -> list[str]:
        return ["verysecretvalue"]


class FakeAuth:
    """Returns a fixed principal; lets the tests exercise require_role without workstream A."""

    def __init__(self, role: str) -> None:
        self.role = role

    def authenticate(self, request: Any) -> Principal:
        return Principal(subject=f"{self.role}-user", kind="user", role=self.role)


def _config(tmp_path: Path) -> dict[str, Any]:
    return {
        "runtime": {"runs_dir": str(tmp_path / "runs"), "checkpoint_db": str(tmp_path / "cp.sqlite")},
        "validation": {"terraform_plugin_cache_dir": ""},
        "security": {"auth": {"mode": "disabled"}},  # the HTTP tests exercise the service, not sign-in
        "deploy": {"terraform_bin": "terraform", "timeout_minutes": 1, "allow_apply": True, "allow_destroy": True, "remote_state": {"enabled": False}},
    }


@pytest.fixture
def fake_terraform(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    target = bin_dir / "terraform"
    shutil.copy(FAKE_TERRAFORM, target)
    target.chmod(target.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("FAKE_TF_LOG", str(tmp_path / "fake-terraform.log"))
    monkeypatch.delenv("FAKE_TF_MODE", raising=False)
    return target


@pytest.fixture
def runtime(tmp_path: Path) -> MigrationRuntime:
    return MigrationRuntime(_config(tmp_path), runs_dir=tmp_path / "runs", checkpoint_db=tmp_path / "cp.sqlite")


@pytest.fixture
def client(runtime: MigrationRuntime, fake_terraform: Path) -> TestClient:
    app = create_app(runtime=runtime)
    app.state.platform.connections = FakeConnections()
    return TestClient(app)


def make_run(runtime: MigrationRuntime, status: str = "succeeded") -> str:
    record = RunRecord(
        run_id=f"20260101T000000Z-{os.urandom(4).hex()}", created_at="2026-01-01T00:00:00+00:00", updated_at="2026-01-01T00:00:00+00:00",
        status=status, cloud="aws", mode="deterministic", options={}, input_filename="discovery.json", run_dir="unused",
    )
    runtime.store.create(record, {"virtual_machines": []})
    root = runtime.store.artifacts_dir(record.run_id) / "aws-migration"
    root.mkdir(parents=True)
    (root / "targets.tf").write_text('provider "aws" {\n  region = var.aws_region\n}\n', encoding="utf-8")
    (root / "variables.tf").write_text(VARIABLES_TF, encoding="utf-8")
    return record.run_id


def wait_done(client: TestClient, run_id: str, deployment_id: str, timeout: float = 15.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        payload = client.get(f"/api/runs/{run_id}/deployments/{deployment_id}").json()
        if payload["status"] in {"succeeded", "failed", "cancelled"}:
            return payload
        time.sleep(0.05)
    raise AssertionError(f"deployment {deployment_id} did not finish")


def test_plan_apply_destroy_over_http(client: TestClient, runtime: MigrationRuntime) -> None:
    run_id = make_run(runtime)
    assert client.get(f"/api/runs/{run_id}/deployments").json() == []

    variables = client.get(f"/api/runs/{run_id}/deploy/variables").json()
    assert [item["name"] for item in variables] == ["aws_region", "db_password"]
    put = client.put(f"/api/runs/{run_id}/deploy/variables", json={"values": {"aws_region": "eu-west-1", "db_password": "pw-123456"}})
    assert put.status_code == 200
    by_name = {item["name"]: item for item in put.json()}
    assert by_name["aws_region"]["value"] == "eu-west-1" and by_name["db_password"]["value"] == "***"
    response = client.put(f"/api/runs/{run_id}/deploy/variables", json={"values": {"nope": 1}})
    assert response.status_code == 400
    assert client.get(f"/api/runs/{run_id}/deploy/state").json() == {"exists": False, "remote": False}

    # plan
    response = client.post(f"/api/runs/{run_id}/deployments", json={"action": "plan"})
    assert response.status_code == 400  # connection required
    response = client.post(f"/api/runs/{run_id}/deployments", json={"action": "plan", "connection_id": "nope"})
    assert response.status_code == 404
    response = client.post(f"/api/runs/{run_id}/deployments", json={"action": "bogus", "connection_id": "conn-1"})
    assert response.status_code == 400
    created = client.post(f"/api/runs/{run_id}/deployments", json={"action": "plan", "connection_id": "conn-1"})
    assert created.status_code == 202, created.text
    plan_id = created.json()["id"]
    assert created.json()["status"] in {"queued", "running"}  # the worker may already have picked it up
    assert created.json()["requested_by"] == "anonymous"
    plan = wait_done(client, run_id, plan_id)
    assert plan["status"] == "succeeded" and plan["summary"]["add"] == 2 and plan["exit_code"] == 2

    log = client.get(f"/api/runs/{run_id}/deployments/{plan_id}/log").json()
    assert log["done"] is True and "Plan: 2 to add, 1 to change, 1 to destroy." in log["lines"]
    assert client.get(f"/api/runs/{run_id}/deployments/{plan_id}/log", params={"since": log["next"]}).json()["lines"] == []
    with client.stream("GET", f"/api/runs/{run_id}/deployments/{plan_id}/log/stream") as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())
    assert "event: done" in body and '"status": "succeeded"' in body
    assert json.loads(body.split("data: ", 1)[1].split("\n", 1)[0])["index"] == 0
    plan_json = client.get(f"/api/runs/{run_id}/deployments/{plan_id}/plan").json()
    assert len(plan_json["resource_changes"]) == 6 and plan_json["variables"]["db_password"] == {"value": "***"}
    assert client.get(f"/api/runs/{run_id}/deployments/{plan_id}/plan").status_code == 200
    assert client.get(f"/api/runs/{run_id}/deployments/nope/plan").status_code == 404
    response = client.post(f"/api/runs/{run_id}/deployments/{plan_id}/cancel")
    assert response.status_code == 409  # already finished

    # apply gates
    response = client.post(f"/api/runs/{run_id}/deployments", json={"action": "apply", "connection_id": "conn-1", "plan_id": plan_id})
    assert response.status_code == 403
    response = client.post(f"/api/runs/{run_id}/deployments", json={"action": "apply", "connection_id": "conn-1", "confirmation": run_id})
    assert response.status_code == 400
    applied = client.post(f"/api/runs/{run_id}/deployments", json={"action": "apply", "connection_id": "conn-1", "plan_id": plan_id, "confirmation": run_id})
    assert applied.status_code == 202, applied.text
    applied = wait_done(client, run_id, applied.json()["id"])
    assert applied["status"] == "succeeded" and applied["plan_id"] == plan_id and applied["approved_by"] == "anonymous"
    state = client.get(f"/api/runs/{run_id}/deploy/state").json()
    assert state["exists"] is True and [item["address"] for item in state["resources"]] == ["aws_vpc.main", 'aws_subnet.a["x"]']

    # destroy
    response = client.post(f"/api/runs/{run_id}/deployments", json={"action": "destroy", "connection_id": "conn-1"})
    assert response.status_code == 403
    destroyed = client.post(f"/api/runs/{run_id}/deployments", json={"action": "destroy", "connection_id": "conn-1", "confirmation": run_id})
    assert destroyed.status_code == 202
    assert wait_done(client, run_id, destroyed.json()["id"])["status"] == "succeeded"
    assert [item["action"] for item in client.get(f"/api/runs/{run_id}/deployments").json()] == ["destroy", "apply", "plan"]

    actions = [entry.action for entry in client.app.state.platform.audit.iter_all()]
    assert actions.count("deployment.requested") == 3 and actions.count("deployment.finished") == 3
    assert actions.count("deployment.denied") >= 4 and "variables.updated" in actions


def test_cancel_and_conflicts_over_http(client: TestClient, runtime: MigrationRuntime, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_TF_MODE", "sleep")
    run_id = make_run(runtime)
    created = client.post(f"/api/runs/{run_id}/deployments", json={"action": "plan", "connection_id": "conn-1"}).json()
    deadline = time.time() + 10
    while client.get(f"/api/runs/{run_id}/deployments/{created['id']}").json()["status"] != "running" and time.time() < deadline:
        time.sleep(0.05)
    response = client.post(f"/api/runs/{run_id}/deployments", json={"action": "plan", "connection_id": "conn-1"})
    assert response.status_code == 409
    response = client.delete(f"/api/runs/{run_id}")
    assert response.status_code == 409  # has_active
    time.sleep(0.2)
    cancelled = client.post(f"/api/runs/{run_id}/deployments/{created['id']}/cancel")
    assert cancelled.status_code == 202 and cancelled.json()["status"] == "cancelled"
    response = client.delete(f"/api/runs/{run_id}")
    assert response.status_code == 204


def test_unknown_run_and_not_succeeded(client: TestClient, runtime: MigrationRuntime) -> None:
    assert client.get("/api/runs/nope/deployments").status_code == 404
    assert client.get("/api/runs/nope/deploy/variables").status_code == 404
    assert client.get("/api/runs/nope/deploy/state").status_code == 404
    paused = make_run(runtime, status="paused")
    response = client.post(f"/api/runs/{paused}/deployments", json={"action": "plan", "connection_id": "conn-1"})
    assert response.status_code == 400 and "only a succeeded run" in response.text
    assert client.get(f"/api/runs/{paused}/deployments/missing").status_code == 404


def test_roles_are_enforced(runtime: MigrationRuntime, fake_terraform: Path) -> None:
    app = create_app(runtime=runtime)
    app.state.platform.connections = FakeConnections()
    app.state.platform.config.setdefault("security", {}).setdefault("auth", {})["mode"] = "required"
    app.state.platform.auth = FakeAuth("viewer")
    client = TestClient(app)
    run_id = make_run(runtime)
    assert client.get(f"/api/runs/{run_id}/deployments").status_code == 200
    assert client.get(f"/api/runs/{run_id}/deploy/variables").status_code == 200
    response = client.post(f"/api/runs/{run_id}/deployments", json={"action": "plan", "connection_id": "conn-1"})
    assert response.status_code == 403
    response = client.put(f"/api/runs/{run_id}/deploy/variables", json={"values": {}})
    assert response.status_code == 403

    app.state.platform.auth = FakeAuth("operator")
    created = client.post(f"/api/runs/{run_id}/deployments", json={"action": "plan", "connection_id": "conn-1"})
    assert created.status_code == 202 and created.json()["requested_by"] == "operator-user"
    assert wait_done(client, run_id, created.json()["id"])["status"] == "succeeded"


def test_deployments_unavailable_returns_503(runtime: MigrationRuntime) -> None:
    app = create_app(runtime=runtime)
    app.state.platform.deployments = None
    client = TestClient(app)
    assert client.get(f"/api/runs/{make_run(runtime)}/deployments").status_code == 503
