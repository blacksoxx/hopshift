"""Proxmox VE target: deterministic render of the multi-VM fixture and the per-module edge cases."""
from __future__ import annotations

import json
from pathlib import Path

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
from hopshift.pipeline.generation.deterministic import render_deterministic
from hopshift.pipeline.nodes.blocker_parser import blocker_parser
from hopshift.pipeline.nodes.cim_mapper import cim_mapper
from hopshift.pipeline.nodes.enricher import enricher
from hopshift.pipeline.nodes.ingest import ingest
from hopshift.pipeline.nodes.sizer import sizer
from hopshift.targets import registry as targets
from hopshift.targets.proxmox import config_id, dns_name, os_type, parse_vlan, proxmox_tag
from hopshift.targets.proxmox.compute import build_tags, render_compute
from hopshift.targets.proxmox.network import render_networking
from hopshift.targets.proxmox.placement import render_placement
from hopshift.targets.proxmox.sizing_table import get_instance_type
from hopshift.targets.proxmox.storage import render_storage

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "discovery_multi_vm.json"
TAGS = {"Environment": "test", "Owner": "platform", "MigratedFrom": "vmware-vcenter"}
ROOT = "proxmox-migration/"

EXPECTED_FILES = [
    "proxmox-migration/compute_db-01.tf",
    "proxmox-migration/compute_mgmt-jump.tf",
    "proxmox-migration/compute_web-01.tf",
    "proxmox-migration/firewall_db-01.tf",
    "proxmox-migration/firewall_mgmt-jump.tf",
    "proxmox-migration/firewall_web-01.tf",
    "proxmox-migration/network_vlans.tf",
    "proxmox-migration/placement_placement_groups.tf",
    "proxmox-migration/storage_db-01_disks.tf",
    "proxmox-migration/storage_mgmt-jump_disks.tf",
    "proxmox-migration/storage_web-01_disks.tf",
    "proxmox-migration/targets.tf",
    "proxmox-migration/variables.tf",
]


def _sized_cim(fixture: Path = FIXTURE) -> CanonicalInfrastructureModel:
    state = {
        "discovery_data": json.loads(fixture.read_text(encoding="utf-8")),
        "config": {"vsphere": {"hard_blockers": ["encrypted_vm_present", "rdm_disk_present", "shared_disk_present"]}},
        "target_provider": TargetProvider("proxmox"),
        "quarantine_queue": [],
        "messages": [],
        "status": "pending",
    }
    for node in (ingest, blocker_parser, enricher, cim_mapper, sizer):
        state = node(state)  # type: ignore[arg-type]
    return state["sized_cim"]


@pytest.fixture(scope="module")
def files() -> dict[str, str]:
    return render_deterministic(provider="proxmox", cim=_sized_cim(), required_tags=TAGS)


def _cim(
    units: list[ComputeUnit],
    clusters: list[ComputeCluster] | None = None,
    switches: list[DistributedSwitch] | None = None,
) -> CanonicalInfrastructureModel:
    return CanonicalInfrastructureModel(
        source_vcenter="vc.lab",
        target_provider=TargetProvider("proxmox"),
        network_topology=NetworkTopology(distributed_switches=switches or []),
        clusters=clusters or [],
        compute_units=units,
    )


def _unit(name: str = "web-01", **overrides) -> ComputeUnit:
    values = {
        "id": name,
        "name": name,
        "vcpus": 2,
        "ram_mb": 4096,
        "guest_os": "Ubuntu Linux (64-bit)",
        "firmware": "efi",
        "nics": [NIC(name="nic0", port_group_ref="pg-web", mac_address="00:50:56:aa:00:01")],
        "storage_volumes": [StorageVolume(id="[ds] web/web.vmdk", size_gb=40, datastore="ds", unit_number=0)],
    }
    values.update(overrides)
    return ComputeUnit(**values)


# ── registry ──────────────────────────────────────────────────────────────────


def test_target_is_registered_with_its_provider_source_and_connection() -> None:
    spec = targets.get("proxmox")
    assert spec.label == "Proxmox VE" and spec.package == "hopshift.targets.proxmox"
    assert spec.tier == "validated" and spec.tflint is False and spec.connection_provider == "proxmox"
    assert spec.root == "proxmox-migration" and spec.docs == "docs/targets/proxmox.md"
    assert spec.extra == {"provider_sources": {"bpg/proxmox"}}  # the pipeline guard reads this, no core entry
    assert "proxmox" in targets.names()


# ── fixture render ────────────────────────────────────────────────────────────


def test_fixture_renders_the_expected_flat_root_module(files: dict[str, str]) -> None:
    assert list(files) == EXPECTED_FILES
    for content in files.values():
        assert "\r" not in content and content.endswith("\n")


def test_provider_block_pins_bpg_proxmox_and_keeps_credentials_out_of_files(files: dict[str, str]) -> None:
    providers = files[ROOT + "targets.tf"]
    assert 'source  = "bpg/proxmox"' in providers and 'version = "~> 0.121"' in providers
    assert 'provider "proxmox" {' in providers and "endpoint = var.proxmox_endpoint" in providers and "insecure = var.proxmox_insecure" in providers
    assert "api_token" not in providers and "password" not in providers.replace("PROXMOX_VE_PASSWORD", "")
    for content in files.values():
        assert "PVEAPIToken" not in content

    variables = files[ROOT + "variables.tf"]
    names = {line.split('"')[1] for line in variables.splitlines() if line.startswith('variable "')}
    assert names == {
        "proxmox_endpoint", "proxmox_insecure", "proxmox_node", "datastore_id", "bridge", "nic_model", "image_overrides",
        "default_template_id", "management_cidrs", "ha_nodes", "ha_rules_enabled", "environment", "owner",
    }
    assert 'default     = "test"' in variables and 'default     = "platform"' in variables
    assert 'default     = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]' in variables
    assert 'type        = map(number)' in variables
    assert '!contains(var.management_cidrs, "0.0.0.0/0")' in variables


def test_vm_resource_carries_sizing_tags_firmware_agent_and_vlan(files: dict[str, str]) -> None:
    web = files[ROOT + "compute_web-01.tf"]
    assert 'resource "proxmox_virtual_environment_vm" "web_01" {' in web
    assert '  name        = "web-01"' in web and "  node_name   = var.proxmox_node" in web
    assert (
        '  tags        = ["env-${var.environment}", "migratedfrom-vmware-vcenter", "owner-${var.owner}", '
        '"source-vcenter-lab.example.internal"]'
    ) in web
    assert "(kvm-2c-8g)" in web and "    cores   = 2" in web and "    dedicated = 8192" in web
    assert '    type    = "x86-64-v2-AES"' in web
    assert '  bios = "ovmf"' in web and "    pre_enrolled_keys = true" in web and '    type              = "4m"' in web
    assert "  tpm_state {" in web and '    version      = "v2.0"' in web
    assert "  agent {\n    enabled = true\n  }" in web
    assert '    type = "l26"' in web
    assert "    vlan_id     = 110" in web and "    firewall    = true" in web and "    bridge      = var.bridge" in web
    assert '    mac_address = "00:50:56:AA:00:01"' in web
    assert "serial_device" not in web and "0.0.0.0/0" not in web


def test_vm_without_known_template_uses_dynamic_clone_lookup_and_stays_stopped(files: dict[str, str]) -> None:
    web = files[ROOT + "compute_web-01.tf"]
    assert '  web_01_template_id = lookup(var.image_overrides, "web-01", var.default_template_id)' in web
    assert 'dynamic "clone" {' in web and "for_each = local.web_01_template_id == null ? [] : [local.web_01_template_id]" in web
    assert "      vm_id = clone.value" in web and "  started = local.web_01_template_id != null" in web
    assert "TODO: no template or imported image" in web


def test_bios_vm_with_vtpm_keeps_seabios_and_gets_every_disk(files: dict[str, str]) -> None:
    db = files[ROOT + "compute_db-01.tf"]
    assert '  bios = "seabios"' in db and "efi_disk" not in db
    assert "  tpm_state {" in db  # has_vtpm on the source VM
    assert '    interface    = "scsi0"\n    datastore_id = var.datastore_id\n    size         = 60' in db
    assert '    interface    = "scsi1"\n    datastore_id = var.datastore_id\n    size         = 500' in db
    assert "    vlan_id     = 120" in db
    assert "(kvm-4c-16g)" in db

    inventory = files[ROOT + "storage_db-01_disks.tf"]
    assert all(line.startswith("#") for line in inventory.splitlines())
    assert "scsi1     500 GB  [vsan-ds] db-01/db-01_1.vmdk" in inventory and "compute_db-01.tf" in inventory


def test_vlan_interfaces_are_rendered_once_per_vlan_on_the_bridge(files: dict[str, str]) -> None:
    vlans = files[ROOT + "network_vlans.tf"]
    for tag in (10, 110, 120):
        assert f'resource "proxmox_virtual_environment_network_linux_vlan" "vlan_{tag}" {{' in vlans
        assert f'  name      = "${{var.bridge}}.{tag}"' in vlans
    assert vlans.count('resource "proxmox_virtual_environment_network_linux_vlan"') == 3
    assert "  node_name = var.proxmox_node" in vlans and "pg-web (dvs-prod)" in vlans
    assert "address" not in vlans.replace("address is assigned", "")


def test_firewall_denies_inbound_by_default_and_allows_ssh_only_from_management_ranges(files: dict[str, str]) -> None:
    firewall = files[ROOT + "firewall_web-01.tf"]
    assert 'resource "proxmox_virtual_environment_firewall_options" "web_01" {' in firewall
    assert "  vm_id     = proxmox_virtual_environment_vm.web_01.vm_id" in firewall
    assert "  enabled       = true" in firewall and '  input_policy  = "DROP"' in firewall
    assert 'resource "proxmox_virtual_environment_firewall_rules" "web_01" {' in firewall
    assert '    dport   = "22"' in firewall and '    proto   = "icmp"' in firewall
    assert firewall.count('    source  = join(",", var.management_cidrs)') == 2
    assert "0.0.0.0/0" not in firewall.replace("never 0.0.0.0/0", "")
    assert 'source = "' not in firewall  # a literal source would trip the generator's module-source guard


def test_placement_renders_ha_group_and_resources_for_the_cluster_only(files: dict[str, str]) -> None:
    placement = files[ROOT + "placement_placement_groups.tf"]
    assert 'resource "proxmox_virtual_environment_hagroup" "prod_cluster" {' in placement
    assert '  group       = "prod-cluster"' in placement
    assert "nodes       = { for node in (length(var.ha_nodes) > 0 ? var.ha_nodes : [var.proxmox_node]) : node => null }" in placement
    for ref in ("web_01", "db_01"):
        assert f'resource "proxmox_virtual_environment_haresource" "{ref}" {{' in placement
        assert f'  resource_id = "vm:${{proxmox_virtual_environment_vm.{ref}.vm_id}}"' in placement
    assert "mgmt_jump" not in placement  # not in a cluster
    assert "proxmox_virtual_environment_harule" in placement  # mentioned in the TODO
    assert 'resource "proxmox_virtual_environment_harule"' not in placement  # unknown semantics: no strict rule
    assert "TODO: VMware DRS spreads the members of prod-cluster" in placement


# ── module edge cases ─────────────────────────────────────────────────────────


def test_windows_guest_gets_windows_os_type_and_rdp_rule() -> None:
    unit = _unit("app-w", guest_os="Microsoft Windows Server 2022 (64-bit)", firmware="bios")
    cim = _cim([unit])
    compute = render_compute(cim, TAGS)["proxmox-migration/compute/app-w.tf"]
    firewall = render_networking(cim)["proxmox-migration/firewall/app-w.tf"]
    assert '    type = "win11"' in compute
    assert '    dport   = "3389"' in firewall and "RDP from the management ranges only" in firewall
    assert "22" not in firewall.split("rule {")[1]


@pytest.mark.parametrize(
    "guest_os, family, expected",
    [
        ("Ubuntu Linux (64-bit)", None, "l26"),
        ("Microsoft Windows Server 2019 (64-bit)", None, "win10"),
        ("Microsoft Windows Server 2012 (64-bit)", "windows", "win8"),
        ("Microsoft Windows 11 (64-bit)", None, "win11"),
        ("Oracle Solaris 11 (64-bit)", "other", "solaris"),
        ("FreeBSD 13 (64-bit)", None, "other"),
        (None, "windows", "win10"),
    ],
)
def test_os_type_mapping(guest_os: str | None, family: str | None, expected: str) -> None:
    assert os_type(_unit(guest_os=guest_os, guest_family=family)) == expected


def test_numeric_image_ref_renders_a_static_clone_and_an_import_id_the_boot_disk_import() -> None:
    cim = _cim([_unit("web-01", image_ref="9001"), _unit("db-01", image_ref="local:import/db-01.qcow2")])
    rendered = render_compute(cim, TAGS)
    web = rendered["proxmox-migration/compute/web-01.tf"]
    assert '    vm_id = lookup(var.image_overrides, "web-01", 9001)' in web and "dynamic" not in web and "started" not in web
    db = rendered["proxmox-migration/compute/db-01.tf"]
    assert '    import_from  = "local:import/db-01.qcow2"' in db and "# Boot disk imported from local:import/db-01.qcow2" in db
    assert "clone {" not in db and "dynamic" not in db and "started" not in db


def test_segment_without_vlan_tag_renders_untagged_nic_and_no_vlan_interface() -> None:
    switch = DistributedSwitch(name="default-dvs", port_groups=[PortGroup(name="VM Network", vlan_id="")])
    unit = _unit("centos", nics=[NIC(name="nic0", port_group_ref="VM Network")])
    cim = _cim([unit], switches=[switch])
    compute = render_compute(cim, TAGS)["proxmox-migration/compute/centos.tf"]
    vlans = render_networking(cim)["proxmox-migration/network/vlans.tf"]
    assert "vlan_id" not in compute and "has no single VLAN tag" in compute and "mac_address" not in compute
    assert "resource " not in vlans and "VM Network (default-dvs): untagged" in vlans


def test_cluster_semantics_drive_the_ha_affinity_rule() -> None:
    units = [_unit("a", cluster_ref="c1"), _unit("b", cluster_ref="c1"), _unit("c", cluster_ref="c2")]
    clusters = [
        ComputeCluster(name="c1", semantics=ClusterSemantics.ANTI_AFFINITY, ha_enabled=True),
        ComputeCluster(name="c2", semantics=ClusterSemantics.AFFINITY, ha_enabled=False),
    ]
    placement = render_placement(_cim(units, clusters), TAGS)["proxmox-migration/placement/placement_groups.tf"]
    assert 'resource "proxmox_virtual_environment_harule" "c1_anti_affinity" {' in placement
    assert "  count = var.ha_rules_enabled ? 1 : 0" in placement and '  affinity = "negative"' in placement
    assert "    proxmox_virtual_environment_haresource.a.resource_id," in placement
    assert "    proxmox_virtual_environment_haresource.b.resource_id," in placement
    # HA disabled on c2: documented, nothing rendered for it
    assert "VMware HA is disabled on c2" in placement and '"proxmox_virtual_environment_hagroup" "c2"' not in placement
    assert 'resource "proxmox_virtual_environment_haresource" "c"' not in placement

    positive = render_placement(
        _cim(units[:2], [ComputeCluster(name="c1", semantics=ClusterSemantics.AFFINITY)]), TAGS
    )["proxmox-migration/placement/placement_groups.tf"]
    assert '  affinity = "positive"' in positive


def test_no_clusters_renders_a_comment_only_placement_file() -> None:
    placement = render_placement(_cim([_unit()]), TAGS)["proxmox-migration/placement/placement_groups.tf"]
    assert placement.startswith("# No clusters discovered")


def test_names_and_tags_are_sanitised_for_proxmox() -> None:
    unit = _unit("Legacy App Server", storage_volumes=[])
    compute = render_compute(_cim([unit]), {"Environment": "Prod Env", "Owner": "Team/A", "CostCenter": "CC 42"})
    content = compute["proxmox-migration/compute/Legacy_App_Server.tf"]
    assert '  name        = "legacy-app-server"' in content and "is rendered as legacy-app-server" in content
    assert '"env-prod-env"' in content and '"owner-team-a"' in content and '"costcenter-cc-42"' in content
    assert "The source VM reports no disks" in content

    assert build_tags(_cim([unit]), TAGS) == [
        '"env-test"', '"migratedfrom-vmware-vcenter"', '"owner-platform"', '"source-vc.lab"',
    ]
    assert proxmox_tag("Prod Env!") == "prod-env" and proxmox_tag("a.b+c_d") == "a.b+c_d" and proxmox_tag("***") == ""
    assert dns_name("Web_01.prod") == "web-01-prod" and dns_name("---") == "vm" and len(dns_name("x" * 80)) == 63
    assert config_id("prod cluster") == "prod-cluster" and config_id("1st") == "c-1st"


def test_shared_and_rdm_volumes_are_flagged_in_disk_blocks_and_inventory() -> None:
    volumes = [
        StorageVolume(id="[ds] a/a.vmdk", size_gb=20, datastore="ds", unit_number=0),
        StorageVolume(id="[ds] a/a_1.vmdk", size_gb=100, datastore="ds", unit_number=1, is_shared=True),
        StorageVolume(id="[ds] a/a_2.vmdk", size_gb=200, datastore="ds", unit_number=2, is_rdm=True),
    ]
    cim = _cim([_unit("a", storage_volumes=volumes)])
    compute = render_compute(cim, TAGS)["proxmox-migration/compute/a.tf"]
    inventory = render_storage(cim, TAGS)["proxmox-migration/storage/a_disks.tf"]
    assert compute.count("  disk {") == 3 and "shared between VMs" in compute and "RDM / pass-through" in compute
    assert "[SHARED: manual review]" in inventory and "[RDM: manual review]" in inventory


@pytest.mark.parametrize(
    "value, expected",
    [("110", 110), ("0", None), ("", None), ("4095", None), ("10-20", None), (" 7 ", 7), (None, None)],
)
def test_parse_vlan(value: object, expected: int | None) -> None:
    assert parse_vlan(value) == expected


@pytest.mark.parametrize(
    "vcpus, ram_mb, expected",
    [(1, 1024, "kvm-1c-1g"), (4, 16384, "kvm-4c-16g"), (2, 1536, "kvm-2c-1536m"), (64, 1_048_576, "kvm-64c-1024g")],
)
def test_sizing_is_pass_through(vcpus: int, ram_mb: int, expected: str) -> None:
    assert get_instance_type(vcpus, ram_mb) == expected


def test_sizing_rejects_non_positive_shapes() -> None:
    with pytest.raises(ValueError):
        get_instance_type(0, 1024)
    with pytest.raises(ValueError):
        get_instance_type(2, 0)
