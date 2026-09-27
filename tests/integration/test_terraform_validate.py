"""End-to-end check: deterministic render -> real terraform init/validate (+ tflint) per provider.

Runs when the terraform binary is installed and VMA_SKIP_TERRAFORM_INTEGRATION is not set.
`terraform init` downloads providers, so the first run needs network access; the plugin cache
under ~/.cache makes later runs fast.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from agent.generation.deterministic import render_deterministic
from agent.nodes.blocker_parser import blocker_parser
from agent.nodes.cim_mapper import cim_mapper
from agent.nodes.enricher import enricher
from agent.nodes.ingest import ingest
from agent.nodes.sizer import sizer
from cim.schema import TargetProvider
from validation.tf_runner import validate_hcl

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = [
    REPO_ROOT / "discovery-2.json",
    REPO_ROOT / "tests" / "fixtures" / "discovery_multi_vm.json",
]
PLUGIN_CACHE = Path.home() / ".cache" / "vmware-migration-agent" / "terraform-plugins"

pytestmark = [
    pytest.mark.skipif(shutil.which("terraform") is None, reason="terraform binary not installed"),
    pytest.mark.skipif(
        os.environ.get("VMA_SKIP_TERRAFORM_INTEGRATION") == "1",
        reason="VMA_SKIP_TERRAFORM_INTEGRATION=1",
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


@pytest.mark.parametrize("provider", ["aws", "azure", "gcp", "openstack"])
@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda p: p.name)
def test_deterministic_render_passes_terraform_validate(provider: str, fixture: Path) -> None:
    cim, _ = _sized_cim(fixture, provider)
    assert cim.compute_units, "fixture must contain at least one migratable VM"

    files = render_deterministic(
        provider=provider,
        cim=cim,
        required_tags={"Environment": "test", "Owner": "platform", "MigratedFrom": "vmware-vcenter"},
    )

    result = validate_hcl(
        hcl_output=files,
        run_tflint=shutil.which("tflint") is not None,
        plugin_cache_dir=str(PLUGIN_CACHE),
    )

    assert result.terraform_validate_passed, "\n".join(result.errors)
    assert result.tflint_passed, "\n".join(result.errors)


def test_multi_vm_fixture_quarantines_rdm_vm_and_keeps_topology() -> None:
    cim, quarantine = _sized_cim(FIXTURES[1], "aws")

    assert [item["compute_unit_name"] for item in quarantine] == ["Legacy App Server (RDM)"]
    assert {unit.name for unit in cim.compute_units} == {"web-01", "db-01", "mgmt-jump"}
    switches = {switch.name: [pg.name for pg in switch.port_groups] for switch in cim.network_topology.distributed_switches}
    assert switches == {"dvs-mgmt": ["pg-mgmt"], "dvs-prod": ["pg-db", "pg-web"]}
    assert [cluster.name for cluster in cim.clusters] == ["prod-cluster"]
