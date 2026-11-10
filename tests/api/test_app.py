from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import hopshift.pipeline.nodes.reporter as reporter_module
from hopshift.api.app import create_app
from hopshift.pipeline.runtime import MigrationRuntime

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "discovery_multi_vm.json"


class _FakeLLMClient:
    def __init__(self, config: dict[str, object]) -> None:
        pass

    def generate_review_notes(self, prompt: str, system_prompt: str | None = None) -> str:
        return "# notes"


def _config() -> dict[str, object]:
    return {
        "generation": {"mode": "deterministic"},
        "mcp": {"enabled": False},
        "validation": {"run_terraform_validate": False, "run_tflint": False, "run_opa": False},
        "output": {"base_dir": "output"},
        "required_tags": {"MigratedFrom": "vmware-vcenter"},
        "runtime": {"default_pause_points": ["review_cim"]},
        "security": {"auth": {"mode": "disabled"}},
    }


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(reporter_module, "LLMClient", _FakeLLMClient)
    runtime = MigrationRuntime(_config(), runs_dir=tmp_path / "runs", checkpoint_db=tmp_path / "runs" / "cp.sqlite")
    return TestClient(create_app(runtime=runtime))


def _wait(client: TestClient, run_id: str, until: set[str], timeout: float = 30.0) -> dict[str, object]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        payload = client.get(f"/api/runs/{run_id}").json()
        if payload["status"] in until and not payload["executing"]:
            return payload
        time.sleep(0.1)
    raise AssertionError(f"run {run_id} did not reach {until} in time")


def _discovery() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_meta_and_health(client: TestClient) -> None:
    assert client.get("/api/health").json()["ok"] is True
    meta = client.get("/api/meta").json()
    assert meta["clouds"] == ["aws", "azure", "gcp", "openstack"]
    assert meta["pause_points"]["review_cim"] == "hcl_generator"
    assert meta["nodes"][0] == "ingest"


def test_full_run_lifecycle_over_http(client: TestClient) -> None:
    created = client.post(
        "/api/runs",
        json={"discovery": _discovery(), "options": {"cloud": "aws", "environment": "dev", "owner": "platform"}, "start": True},
    )
    assert created.status_code == 201
    run_id = created.json()["run_id"]

    paused = _wait(client, run_id, {"paused"})
    assert paused["pause_point"] == "review_cim"

    state = client.get(f"/api/runs/{run_id}/state").json()
    assert state["next"] == ["hcl_generator"]
    cim = state["values"]["sized_cim"]
    cim["compute_units"][0]["name"] = "web-01-edited"

    patched = client.patch(f"/api/runs/{run_id}/state", json={"values": {"sized_cim": cim}})
    assert patched.status_code == 200

    resumed = client.post(f"/api/runs/{run_id}/resume")
    assert resumed.status_code == 202 and resumed.json()["resumed_from"] == "review_cim"

    done = _wait(client, run_id, {"succeeded", "failed", "error"})
    assert done["status"] == "succeeded", done

    artifacts = {item["path"] for item in client.get(f"/api/runs/{run_id}/artifacts").json()}
    assert "aws-migration/compute_web-01-edited.tf" in artifacts
    content = client.get(f"/api/runs/{run_id}/artifacts/aws-migration/compute_web-01-edited.tf").text
    assert 'resource "aws_instance" "web_01_edited"' in content

    events = client.get(f"/api/runs/{run_id}/events").json()
    assert events[0]["type"] == "start" and events[-1]["type"] == "end"

    with client.stream("GET", f"/api/runs/{run_id}/events/stream") as response:
        body = "".join(response.iter_text())
    assert "event: done" in body and '"type": "end"' in body

    listed = client.get("/api/runs").json()
    assert [run["run_id"] for run in listed] == [run_id]


def test_lifecycle_errors_map_to_http_codes(client: TestClient) -> None:
    assert client.get("/api/runs/nope").status_code == 404
    assert client.get("/api/runs/nope/artifacts/x.tf").status_code == 404

    bad = client.post("/api/runs", json={"discovery": {"x": 1}, "options": {"cloud": "aws", "environment": "d", "owner": "o"}})
    assert bad.status_code == 400 and "virtual_machines" in bad.text

    created = client.post("/api/runs", json={"discovery": _discovery(), "options": {"cloud": "aws", "environment": "d", "owner": "o"}})
    run_id = created.json()["run_id"]
    response = client.post(f"/api/runs/{run_id}/resume")
    assert response.status_code == 400
    response = client.patch(f"/api/runs/{run_id}/state", json={"values": {"sized_cim": {}}})
    assert response.status_code == 400
    response = client.post(f"/api/runs/{run_id}/rerun", json={"node": "sizer"})
    assert response.status_code == 400


def test_assess_endpoint_runs_synchronously(client: TestClient) -> None:
    response = client.post("/api/assess", json={"discovery": _discovery(), "cloud": "aws"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["total_resources"] > 0
    assert any(item["resource_name"] == "Legacy App Server (RDM)" and item["risk_level"] == "elevated" for item in payload["resources"])
