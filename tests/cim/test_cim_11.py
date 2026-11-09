from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from cim import schema_export
from cim.schema import (
    Architecture,
    ClusterSemantics,
    DistributedSwitch,
    MigrationStatus,
    NetworkSegment,
    NetworkTopology,
    PortGroup,
    SourcePlatform,
    StorageVolume,
    TargetProvider,
    VirtualSwitch,
)
from cim.translators import registered_schemas, resolve_translator, translate

REPO_ROOT = Path(__file__).resolve().parents[2]


def _vm(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "discovery_key": "vc::moid::1", "vm_name": "app-1", "vcpus": 2, "ram_mb": 4096,
        "source_vcenter": "vc01", "source_vcenter_hostname": "10.0.0.5",
        "guest_os": "CentOS 7 (64-bit)", "guest_os_id": "centos7_64Guest", "firmware": "efi",
        "power_state": "poweredOn", "is_template": False, "snapshot_count": 0,
        "all_ip_addresses": ["10.1.2.3"], "ip_address": "10.1.2.3",
        "tags": [{"category": "owner", "name": "platform"}], "custom_attributes": [{"key": "CostCenter", "value": "CC-42"}],
        "annotation": "prod web", "cpu_reservation_mhz": 500, "memory_reservation_mb": 1024, "cores_per_socket": 2,
        "disks": [{"filename": "[ds1] a.vmdk", "size_gb": 40, "datastore": "ds1", "disk_mode": "persistent", "controller_type": "paravirtual", "unit_number": 0, "backing_type": "FlatVer2"}],
        "networks": [{"label": "Network adapter 1", "network_name": "pg-app", "vlan_id": "100", "connected": True, "ip_addresses": ["10.1.2.3"]}],
    }
    base.update(overrides)
    return base


def _payload(*vms: dict[str, object], **extra: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "metadata": {"schema_name": "vmware-discovery-stage1", "schema_version": "1.0.0", "generated_at": "2026-09-27 10:00:00"},
        "virtual_machines": list(vms),
    }
    payload.update(extra)
    return payload


def test_translator_populates_source_and_11_fields() -> None:
    cim = translate(_payload(_vm()), "aws")

    assert cim.cim_schema_version == "1.1"
    assert cim.source.platform == SourcePlatform.VMWARE_VSPHERE
    assert cim.source.name == "vc01" and cim.source.hostname == "10.0.0.5"
    assert cim.source.schema_name == "vmware-discovery-stage1"
    assert cim.migrated_from == "vmware-vcenter"

    unit = cim.compute_units[0]
    assert unit.architecture == Architecture.X86_64
    assert unit.guest_os == "CentOS 7 (64-bit)" and unit.guest_family == "linux"
    assert unit.firmware == "efi" and unit.power_state == "on"
    assert unit.ip_addresses == ["10.1.2.3"]
    assert unit.source_tags == {"owner": "platform"}
    assert unit.custom_attributes == {"CostCenter": "CC-42"}
    assert unit.cpu_reservation_mhz == 500 and unit.cores_per_socket == 2
    assert unit.storage_volumes[0].disk_mode == "persistent" and unit.storage_volumes[0].unit_number == 0
    assert unit.nics[0].connected is True and unit.nics[0].ip_addresses == ["10.1.2.3"]


def test_windows_guest_family_and_template_blocker() -> None:
    cim = translate(_payload(_vm(guest_os="Microsoft Windows Server 2019 (64-bit)", is_template=True)), "aws")
    unit = cim.compute_units[0]

    assert unit.guest_family == "windows"
    assert unit.is_template is True
    assert "vm_template" in unit.blockers
    assert unit.migration_status == MigrationStatus.BLOCKED


def test_powered_off_and_snapshots_are_soft_blockers() -> None:
    cim = translate(_payload(_vm(power_state="poweredOff", snapshot_count=2)), "aws")
    unit = cim.compute_units[0]

    assert set(unit.blockers) == {"powered_off", "snapshots_present"}
    assert unit.migration_status == MigrationStatus.NEEDS_REVIEW


def test_non_x86_architecture_is_a_hard_blocker() -> None:
    cim = translate(_payload(_vm(architecture="ppc64le")), "aws")
    unit = cim.compute_units[0]

    assert unit.architecture == Architecture.PPC64LE
    assert "unsupported_architecture" in unit.blockers
    assert unit.migration_status == MigrationStatus.BLOCKED


def test_declared_clusters_with_drs_rules_set_semantics() -> None:
    payload = _payload(
        _vm(cluster="prod"), _vm(vm_name="app-2", discovery_key="vc::moid::2", cluster="db"),
        clusters=[
            {"name": "prod", "ha_enabled": True, "drs_rules": [{"type": "anti_affinity", "enabled": True, "vm_names": ["app-1"]}]},
            {"name": "db", "ha_enabled": True, "drs_rules": [{"type": "affinity", "enabled": True}]},
            {"name": "ha-only", "ha_enabled": True},
        ],
    )
    cim = translate(payload, "azure")
    semantics = {cluster.name: cluster.semantics for cluster in cim.clusters}

    assert semantics == {"prod": ClusterSemantics.ANTI_AFFINITY, "db": ClusterSemantics.AFFINITY, "ha-only": ClusterSemantics.HA}
    assert next(c for c in cim.clusters if c.name == "prod").ha_enabled is True


def test_declared_switches_merge_with_vm_derived_topology() -> None:
    payload = _payload(
        _vm(networks=[{"network_name": "pg-app", "vlan_id": "100", "switch_name": "dvs-prod"}]),
        distributed_switches=[{"name": "dvs-prod", "switch_type": "distributed", "port_groups": [
            {"name": "pg-app", "key": "dvportgroup-1", "vlan_id": "100", "vlan_type": "vlan"},
            {"name": "pg-idle", "key": "dvportgroup-2", "vlan_id": "200"},
        ]}],
    )
    cim = translate(payload, "gcp")
    switch = cim.network_topology.switches[0]

    assert switch.name == "dvs-prod" and switch.switch_type == "distributed"
    assert [segment.name for segment in switch.segments] == ["pg-app", "pg-idle"]
    assert switch.segments[0].key == "dvportgroup-1"


def test_neutral_aliases_construct_the_same_model() -> None:
    neutral = NetworkTopology(switches=[VirtualSwitch(name="sw", segments=[NetworkSegment(name="seg", vlan_id="1")])])
    legacy = NetworkTopology(distributed_switches=[DistributedSwitch(name="sw", port_groups=[PortGroup(name="seg", vlan_id="1")])])
    assert neutral == legacy

    volume = StorageVolume(id="d", size_gb=10, storage_pool="pool-a", is_passthrough=True)
    assert volume.datastore == "pool-a" and volume.is_rdm is True and volume.is_passthrough is True


def test_registry_rejects_unknown_schema() -> None:
    assert "vmware-discovery-stage1" in registered_schemas()
    with pytest.raises(ValueError, match="No translator registered"):
        resolve_translator({"metadata": {"schema_name": "hyperv-discovery-v1"}, "virtual_machines": []})


def test_json_schema_file_matches_models() -> None:
    """cim/cim.schema.json is generated from the Pydantic models; regenerate with python -m cim.schema_export."""
    current = (REPO_ROOT / "cim" / "cim.schema.json").read_text(encoding="utf-8")
    assert json.loads(current) == schema_export.build_json_schema()


def test_sample_discovery_still_translates() -> None:
    payload = json.loads((REPO_ROOT / "discovery-2.json").read_text(encoding="utf-8"))
    cim = translate(copy.deepcopy(payload), TargetProvider.AWS)

    unit = cim.compute_units[0]
    assert unit.guest_os == "CentOS 7 (64-bit)" and unit.firmware == "bios" and unit.power_state == "on"
    assert unit.architecture == Architecture.X86_64
    assert cim.source.hostname == "192.168.154.130"
