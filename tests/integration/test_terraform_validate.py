"""End-to-end check: deterministic render -> real terraform init/validate (+ tflint) per provider.

Runs when the terraform binary is installed and HOPSHIFT_SKIP_TERRAFORM_INTEGRATION is not set.
`terraform init` downloads providers, so the first run needs network access; the plugin cache
under ~/.cache makes later runs fast.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from hopshift.cim.schema import TargetProvider
from hopshift.pipeline.generation.deterministic import render_deterministic
from hopshift.pipeline.nodes.blocker_parser import blocker_parser
from hopshift.pipeline.nodes.cim_mapper import cim_mapper
from hopshift.pipeline.nodes.enricher import enricher
from hopshift.pipeline.nodes.ingest import ingest
from hopshift.pipeline.nodes.sizer import sizer
from hopshift.services.compliance.controls import controls_for_cloud
from hopshift.validation.opa_client import evaluate_policies
from hopshift.validation.tf_runner import validate_hcl

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = [
    REPO_ROOT / "discovery-2.json",
    REPO_ROOT / "tests" / "fixtures" / "discovery_multi_vm.json",
]
PLUGIN_CACHE = Path.home() / ".cache" / "hopshift" / "terraform-plugins"
POLICIES_DIR = REPO_ROOT / "hopshift" / "validation" / "policies"
REQUIRED_TAGS = {"Environment": "test", "Owner": "platform", "MigratedFrom": "vmware-vcenter"}


def _opa_bin() -> str | None:
    found = shutil.which("opa")
    if found:
        return found
    sibling = Path(sys.executable).parent / "opa"
    return str(sibling) if sibling.exists() else None


OPA_BIN = _opa_bin()

pytestmark = [
    pytest.mark.skipif(shutil.which("terraform") is None, reason="terraform binary not installed"),
    pytest.mark.skipif(
        os.environ.get("HOPSHIFT_SKIP_TERRAFORM_INTEGRATION") == "1",
        reason="HOPSHIFT_SKIP_TERRAFORM_INTEGRATION=1",
    ),
]


def _sized_cim(fixture: Path, provider: str):
    state = {
        "discovery_data": json.loads(fixture.read_text(encoding="utf-8")),
        "config": {"vsphere": {"hard_blockers": ["encrypted_vm_present", "rdm_disk_present", "shared_disk_present"]}},
        "target_provider": TargetProvider(provider),
        "quarantine_queue": [],
        "messages": [],
        "status": "pending",
    }
    for node in (ingest, blocker_parser, enricher, cim_mapper, sizer):
        state = node(state)  # type: ignore[arg-type]
    return state["sized_cim"], state["quarantine_queue"]


@pytest.mark.parametrize("provider", ["aws", "azure", "gcp", "openstack", "proxmox"])
@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda p: p.name)
def test_deterministic_render_passes_terraform_validate(provider: str, fixture: Path) -> None:
    cim, _ = _sized_cim(fixture, provider)
    assert cim.compute_units, "fixture must contain at least one migratable VM"

    files = render_deterministic(provider=provider, cim=cim, required_tags=REQUIRED_TAGS)

    result = validate_hcl(
        hcl_output=files,
        run_tflint=shutil.which("tflint") is not None,
        plugin_cache_dir=str(PLUGIN_CACHE),
    )

    assert result.terraform_validate_passed, "\n".join(result.errors)
    assert result.tflint_passed, "\n".join(result.errors)


@pytest.mark.skipif(OPA_BIN is None, reason="opa binary not installed")
@pytest.mark.parametrize("provider", ["aws", "azure", "gcp", "openstack", "proxmox"])
@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda p: p.name)
def test_deterministic_render_passes_every_enforce_compliance_control(provider: str, fixture: Path) -> None:
    """Secure-by-default renderers: the real policy bundle reports zero enforce violations and
    the gate passes for every cloud. Advisory findings are allowed (they need account-level
    resources or subscription features the platform does not create)."""
    cim, _ = _sized_cim(fixture, provider)
    files = render_deterministic(provider=provider, cim=cim, required_tags=REQUIRED_TAGS)

    result = evaluate_policies(hcl_output=files, policies_dir=POLICIES_DIR, opa_bin=OPA_BIN or "opa")

    assert result.passed, "\n".join(result.deny_messages)
    assert result.enforce_violations == [], result.enforce_violations
    assert set(result.evaluated) == {control.id for control in controls_for_cloud(provider)}


def test_multi_vm_fixture_quarantines_rdm_vm_and_keeps_topology() -> None:
    cim, quarantine = _sized_cim(FIXTURES[1], "aws")

    assert [item["compute_unit_name"] for item in quarantine] == ["Legacy App Server (RDM)"]
    assert {unit.name for unit in cim.compute_units} == {"web-01", "db-01", "mgmt-jump"}
    switches = {switch.name: [pg.name for pg in switch.port_groups] for switch in cim.network_topology.distributed_switches}
    assert switches == {"dvs-mgmt": ["pg-mgmt"], "dvs-prod": ["pg-db", "pg-web"]}
    assert [cluster.name for cluster in cim.clusters] == ["prod-cluster"]
