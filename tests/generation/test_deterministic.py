from __future__ import annotations

import pytest

from hopshift.cim.schema import (
    NIC,
    CanonicalInfrastructureModel,
    ClusterSemantics,
    ComputeCluster,
    ComputeUnit,
    DistributedSwitch,
    NetworkTopology,
    PortGroup,
    StorageVolume,
    TargetProvider,
)
from hopshift.pipeline.generation.deterministic import DeterministicRenderError, render_deterministic

TAGS = {"Environment": "dev", "Owner": "platform", "MigratedFrom": "vmware-vcenter"}


def _cim(provider: str, names: tuple[str, ...] = ("web-01", "db-01")) -> CanonicalInfrastructureModel:
    return CanonicalInfrastructureModel(
        source_vcenter="vc01",
        target_provider=TargetProvider(provider),
        network_topology=NetworkTopology(
            distributed_switches=[
                DistributedSwitch(name="dvs-prod", port_groups=[PortGroup(name="pg-app", vlan_id="100")])
            ]
        ),
        clusters=[ComputeCluster(name="prod-cluster", semantics=ClusterSemantics.ANTI_AFFINITY)],
        compute_units=[
            ComputeUnit(
                id=f"cu-{index}",
                name=name,
                vcpus=2,
                ram_mb=4096,
                cluster_ref="prod-cluster",
                nics=[NIC(name="nic0", port_group_ref="pg-app")],
                storage_volumes=[StorageVolume(id=f"{name}.vmdk", size_gb=40, datastore="ds1")],
            )
            for index, name in enumerate(names, start=1)
        ],
    )


@pytest.mark.parametrize("provider", ["aws", "azure", "gcp", "openstack"])
def test_render_produces_flat_root_module(provider: str) -> None:
    files = render_deterministic(provider=provider, cim=_cim(provider), required_tags=TAGS)

    root = f"{provider}-migration/"
    assert all(path.startswith(root) and "/" not in path[len(root):] for path in files), sorted(files)
    assert f"{root}targets.tf" in files
    assert f"{root}variables.tf" in files
    assert f"{root}networking_vpc.tf" in files
    assert f"{root}compute_web-01.tf" in files
    assert f"{root}storage_db-01_disks.tf" in files
    assert f"{root}placement_placement_groups.tf" in files
    assert 'variable "image_overrides"' in files[f"{root}variables.tf"]


def test_render_is_deterministic_for_identical_input() -> None:
    first = render_deterministic("aws", _cim("aws"), TAGS)
    second = render_deterministic("aws", _cim("aws"), TAGS)
    assert first == second


@pytest.mark.parametrize(
    "provider, expected",
    [
        ("aws", 'resource "aws_placement_group" "prod_cluster"'),
        ("azure", 'resource "azurerm_availability_set" "prod_cluster"'),
        ("gcp", 'resource "google_compute_resource_policy" "prod_cluster"'),
        ("openstack", 'resource "openstack_compute_servergroup_v2" "prod_cluster"'),
    ],
)
def test_clusters_render_placement_resources_referenced_by_compute(provider: str, expected: str) -> None:
    files = render_deterministic(provider=provider, cim=_cim(provider), required_tags=TAGS)
    placement = files[f"{provider}-migration/placement_placement_groups.tf"]
    compute = files[f"{provider}-migration/compute_web-01.tf"]

    assert expected in placement
    assert "prod_cluster" in compute


def test_affinity_cluster_uses_affinity_constructs() -> None:
    cim = _cim("azure")
    cim.clusters[0].semantics = ClusterSemantics.AFFINITY
    files = render_deterministic("azure", cim, TAGS)

    assert 'resource "azurerm_proximity_placement_group" "prod_cluster"' in files["azure-migration/placement_placement_groups.tf"]
    assert "proximity_placement_group_id" in files["azure-migration/compute_web-01.tf"]


def test_rejects_unsupported_provider() -> None:
    with pytest.raises(DeterministicRenderError, match="unsupported provider"):
        render_deterministic("alicloud", _cim("aws"), TAGS)


def test_rejects_vm_names_that_collide_after_sanitization() -> None:
    with pytest.raises(DeterministicRenderError, match="collide"):
        render_deterministic("aws", _cim("aws", names=("web 01", "web-01")), TAGS)


def test_vm_names_are_quoted_safely() -> None:
    cim = _cim("aws", names=('evil"} ${var.x}',))
    files = render_deterministic("aws", cim, TAGS)
    compute = next(content for path, content in files.items() if path.startswith("aws-migration/compute_"))

    assert 'Name = "evil\\"} $${var.x}"' in compute
    assert "${var.x}" not in compute.replace("$${var.x}", "")


def test_tags_reference_variables_and_literals_become_defaults() -> None:
    files = render_deterministic("aws", _cim("aws"), {"Environment": "prod", "Owner": "sre", "Team": "core"})
    vpc = files["aws-migration/networking_vpc.tf"]
    compute = files["aws-migration/compute_web-01.tf"]
    variables = files["aws-migration/variables.tf"]

    assert "Environment = var.environment" in vpc
    assert "Owner = var.owner" in compute
    assert 'Team = "core"' in compute
    assert 'default     = "prod"' in variables
    assert 'default     = "sre"' in variables
