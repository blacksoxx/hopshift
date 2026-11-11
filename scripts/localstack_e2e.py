"""Drive hopshift end to end against LocalStack through the HTTP API.

Setup (first run only), sign-in, an AWS connection pointed at LocalStack, a deterministic run with
both approvals, the LocalStack override files, plan, apply, state and destroy. Exits non-zero when
the run, the plan or the apply fails; destroy always runs after an apply so nothing is left behind.

    docker run -d --name localstack -p 4566:4566 -e SERVICES=ec2,sts,iam localstack/localstack:4.9
    python ui/e2e/serve.py --port 8765 --state-dir /tmp/hopshift-localstack &
    python scripts/localstack_e2e.py --state-dir /tmp/hopshift-localstack --discovery discovery-2.json

See docs/deployments.md, section "LocalStack".
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
import time
from pathlib import Path
from typing import Any

import boto3
import httpx

TERMINAL_RUN = {"succeeded", "completed", "failed", "cancelled"}
TERMINAL_DEPLOYMENT = {"succeeded", "failed", "cancelled"}
PROVIDER_OVERRIDE = """provider "aws" {
  region                      = var.aws_region
  skip_credentials_validation = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true
  s3_use_path_style           = true
}
"""
INSTANCE_OVERRIDE = """resource "aws_instance" "{name}" {{
  root_block_device {{
    encrypted   = true
    volume_size = 20
  }}
}}

"""


class Driver:
    def __init__(self, base_url: str) -> None:
        # The CSRF guard requires an Origin on cookie-authenticated requests, like a browser sends.
        self.client = httpx.Client(base_url=base_url, timeout=60, headers={"Origin": base_url, "Referer": base_url + "/"})

    def call(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self.client.request(method, path, **kwargs)
        if response.status_code >= 400:
            raise SystemExit(f"{method} {path} -> {response.status_code}: {response.text[:500]}")
        return response.json() if response.content else None

    def sign_in(self, username: str, password: str) -> None:
        status = self.call("GET", "/api/auth/status")
        if status.get("setup_required") or status.get("needs_setup") or status.get("users") == 0:
            self.call("POST", "/api/auth/setup", json={"username": username, "password": password, "name": "Admin"})
        self.call("POST", "/api/auth/login", json={"username": username, "password": password})
        print("signed in as", self.call("GET", "/api/auth/me")["username"])

    def connection(self, name: str, endpoint: str) -> dict[str, Any]:
        listed = self.call("GET", "/api/connections")
        items = listed.get("connections", listed) if isinstance(listed, dict) else listed
        for item in items:
            if item.get("name") == name:
                return item
        return self.call("POST", "/api/connections", json={
            "name": name, "provider": "aws", "auth_method": "access_keys",
            "config": {"access_key_id": "test", "region": "us-east-1", "endpoint_url": endpoint},
            "secret": {"secret_access_key": "test"},
        })

    def run(self, discovery: Path, connection_id: str, deadline: float) -> dict[str, Any]:
        created = self.call("POST", "/api/runs", json={
            "discovery": json.loads(discovery.read_text(encoding="utf-8")), "input_filename": discovery.name,
            "start": True, "name": f"localstack {discovery.stem}", "tags": ["localstack"], "connection_id": connection_id,
            "options": {"cloud": "aws", "environment": "prod", "owner": "platform-team", "mode": "deterministic",
                        "llm_review_notes": False, "no_mcp": True},
        })
        run_id = created.get("id") or created["run_id"]
        print("run", run_id)
        started = time.time()
        while time.time() - started < deadline:
            record = self.call("GET", f"/api/runs/{run_id}")
            if record["status"] == "paused":
                print(f"  paused at {record.get('pause_point')}: approving")
                self.call("POST", f"/api/runs/{run_id}/resume")
            elif record["status"] in TERMINAL_RUN:
                return record
            time.sleep(2)
        raise SystemExit(f"run {run_id} did not finish within {deadline:.0f}s")

    def deployment(self, run_id: str, body: dict[str, Any], deadline: float) -> dict[str, Any]:
        created = self.call("POST", f"/api/runs/{run_id}/deployments", json=body)
        started = time.time()
        while time.time() - started < deadline:
            record = self.call("GET", f"/api/runs/{run_id}/deployments/{created['id']}")
            if record["status"] in TERMINAL_DEPLOYMENT:
                return record
            time.sleep(3)
        raise SystemExit(f"deployment {created['id']} did not finish within {deadline:.0f}s")

    def log_tail(self, run_id: str, deployment_id: str, lines: int = 25) -> str:
        payload = self.call("GET", f"/api/runs/{run_id}/deployments/{deployment_id}/log")
        return "\n".join(payload.get("lines", [])[-lines:]) if isinstance(payload, dict) else str(payload)[-2000:]


def first_ami(endpoint: str) -> str:
    ec2 = boto3.client("ec2", region_name="us-east-1", endpoint_url=endpoint, aws_access_key_id="test", aws_secret_access_key="test")
    images = ec2.describe_images()["Images"]
    if not images:
        raise SystemExit("LocalStack returned no AMIs; it validates ids against its catalog")
    return sorted(images, key=lambda image: image.get("Name") or "")[0]["ImageId"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--state-dir", required=True, type=Path, help="the --state-dir given to ui/e2e/serve.py")
    parser.add_argument("--discovery", default="discovery-2.json", type=Path)
    parser.add_argument("--endpoint", default="http://localhost:4566", help="LocalStack endpoint as seen by the platform")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default=os.environ.get("HOPSHIFT_E2E_PASSWORD") or f"Localstack-{secrets.token_urlsafe(12)}")
    parser.add_argument("--timeout", type=float, default=600.0, help="seconds per run or deployment")
    args = parser.parse_args()

    driver = Driver(args.base_url)
    driver.sign_in(args.username, args.password)
    connection = driver.connection("localstack", args.endpoint)
    test = driver.call("POST", f"/api/connections/{connection['id']}/test")
    print("connection:", test.get("message"))
    if not test.get("ok"):
        return 1

    record = driver.run(args.discovery, connection["id"], args.timeout)
    print("run:", record["status"], record.get("error") or "")
    if record["status"] not in ("succeeded", "completed"):
        return 1
    run_id = record["id"] if "id" in record else record["run_id"]
    artifacts = [item["path"] for item in driver.call("GET", f"/api/runs/{run_id}/artifacts")]
    compliance = driver.call("GET", f"/api/runs/{run_id}/compliance")
    print("artifacts:", len(artifacts), "| compliance:", compliance.get("summary") if isinstance(compliance, dict) else compliance)

    instances: list[str] = []
    for path in artifacts:
        if path.startswith("aws-migration/compute_") and path.endswith(".tf"):
            instances += re.findall(r'resource "aws_instance" "([^"]+)"', driver.client.get(f"/api/runs/{run_id}/artifacts/{path}").text)
    root = args.state_dir / "runs" / run_id / "artifacts" / "aws-migration"
    if not root.is_dir():
        raise SystemExit(f"root module not found at {root}; pass the server's --state-dir")
    (root / "localstack_override.tf").write_text(PROVIDER_OVERRIDE + "\n" + "".join(INSTANCE_OVERRIDE.format(name=name) for name in instances), encoding="utf-8")
    ami = first_ami(args.endpoint)
    driver.call("PUT", f"/api/runs/{run_id}/deploy/variables", json={"values": {"default_ami_id": ami}})
    print("override for", len(instances), "instance(s); default_ami_id", ami)

    plan = driver.deployment(run_id, {"action": "plan", "connection_id": connection["id"]}, args.timeout)
    summary = plan.get("summary") if isinstance(plan.get("summary"), dict) else {}
    print("plan:", plan["status"], {key: summary.get(key) for key in ("add", "change", "destroy")})
    if plan["status"] != "succeeded":
        print(driver.log_tail(run_id, plan["id"]))
        return 1

    apply = driver.deployment(run_id, {"action": "apply", "connection_id": connection["id"], "plan_id": plan["id"], "confirmation": run_id}, args.timeout)
    print("apply:", apply["status"], (apply.get("error") or "")[:300])
    if apply["status"] != "succeeded":
        print(driver.log_tail(run_id, apply["id"]))
    state = driver.call("GET", f"/api/runs/{run_id}/deploy/state")
    resources = state.get("resources") if isinstance(state, dict) else None
    print("state:", len(resources) if isinstance(resources, list) else state)
    for resource in resources or []:
        print("   ", resource.get("address") or resource.get("type"))

    destroy = driver.deployment(run_id, {"action": "destroy", "connection_id": connection["id"], "confirmation": run_id}, args.timeout)
    print("destroy:", destroy["status"], (destroy.get("error") or "")[:300])
    if destroy["status"] != "succeeded":
        print(driver.log_tail(run_id, destroy["id"]))
    print("RESULT: apply", apply["status"], "/ destroy", destroy["status"])
    return 0 if apply["status"] == "succeeded" and destroy["status"] == "succeeded" else 1


if __name__ == "__main__":
    sys.exit(main())
