from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from cim.schema import MigrationStatus, TargetProvider
from cim.vmware_translator import translate_vmware_discovery_to_cim

REPO_ROOT = Path(__file__).resolve().parents[2]


def _vm(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "discovery_key": "vc::moid::1",
        "vm_name": "app-1",
        "vcpus": 2,
        "ram_mb": 4096,
        "source_vcenter": "vc01",
        "disks": [
            {
                "filename": "[ds1] app-1/app-1.vmdk",
                "size_gb": 40.0,
                "datastore": "ds1",
                "thin_provisioned": True,
                "backing_type": "FlatVer2",
            }
        ],
        "networks": [{"label": "Network adapter 1", "network_name": "pg-app", "vlan_id": "100"}],
    }
    base.update(overrides)
    return base


def _translate(*vms: dict[str, object], provider: str = "aws"):
    return translate_vmware_discovery_to_cim({"virtual_machines": list(vms)}, provider)


def test_disk_without_sharing_key_is_not_marked_shared() -> None:
    """Regression: an absent `sharing` value used to compare unequal to 'sharingnone'
    and flag every disk as shared."""
    cim = _translate(_vm())

    assert cim.compute_units[0].storage_volumes[0].is_shared is False


@pytest.mark.parametrize("sharing", ["sharingNone", "SHARINGNONE", "", None])
def test_disk_with_default_sharing_is_not_shared(sharing: object) -> None:
    disk = {"filename": "d", "size_gb": 10, "sharing": sharing}
    cim = _translate(_vm(disks=[disk]))

    assert cim.compute_units[0].storage_volumes[0].is_shared is False


@pytest.mark.parametrize(
    "disk",
    [
        {"filename": "d", "size_gb": 10, "sharing": "sharingMultiWriter"},
        {"filename": "d", "size_gb": 10, "multi_writer": True},
    ],
)
def test_disk_with_explicit_sharing_is_shared(disk: dict[str, object]) -> None:
    cim = _translate(_vm(disks=[disk]))

    assert cim.compute_units[0].storage_volumes[0].is_shared is True


def test_rdm_backing_marks_volume_rdm() -> None:
    cim = _translate(_vm(disks=[{"filename": "d", "size_gb": 10, "backing_type": "RawDiskMappingVer1"}]))

    assert cim.compute_units[0].storage_volumes[0].is_rdm is True


def test_encrypted_vm_is_blocked_and_flagged() -> None:
    cim = _translate(_vm(is_encrypted=True))
    unit = cim.compute_units[0]

    assert unit.migration_status == MigrationStatus.BLOCKED
    assert "encrypted_vm_present" in unit.blockers
    assert unit.is_encrypted is True
    assert unit.storage_volumes[0].is_encrypted is True


def test_vtpm_without_blockers_needs_review() -> None:
    cim = _translate(_vm(has_vtpm=True))

    assert cim.compute_units[0].migration_status == MigrationStatus.NEEDS_REVIEW


def test_network_topology_groups_port_groups_by_switch() -> None:
    cim = _translate(
        _vm(networks=[{"network_name": "pg-a", "vlan_id": "10", "distributed_switch": "dvs-1"}]),
        _vm(vm_name="app-2", networks=[{"network_name": "pg-b", "vlan_id": "20", "distributed_switch": "dvs-1"}]),
        _vm(vm_name="app-3", networks=[{"network_name": "pg-c", "vlan_id": "30"}]),
    )

    switches = {switch.name: switch for switch in cim.network_topology.distributed_switches}
    assert set(switches) == {"dvs-1", "default-dvs"}
    assert [pg.name for pg in switches["dvs-1"].port_groups] == ["pg-a", "pg-b"]
    assert switches["default-dvs"].port_groups[0].vlan_id == "30"


def test_source_vcenter_falls_back_to_metadata() -> None:
    payload = {
        "metadata": {"vcenters_queried": ["vc-meta"]},
        "virtual_machines": [_vm(source_vcenter=None)],
    }
    cim = translate_vmware_discovery_to_cim(payload, TargetProvider.GCP)

    assert cim.source_vcenter == "vc-meta"
    assert cim.target_provider == TargetProvider.GCP


def test_rejects_non_list_virtual_machines() -> None:
    with pytest.raises(ValueError):
        translate_vmware_discovery_to_cim({"virtual_machines": {"not": "a list"}}, "aws")


def test_sample_discovery_file_translates_to_one_ready_unit() -> None:
    payload = json.loads((REPO_ROOT / "discovery-2.json").read_text(encoding="utf-8"))
    cim = translate_vmware_discovery_to_cim(copy.deepcopy(payload), "aws")

    assert len(cim.compute_units) == 1
    unit = cim.compute_units[0]
    assert unit.name == "centos"
    assert unit.migration_status == MigrationStatus.READY
    assert unit.storage_volumes[0].is_shared is False
    assert unit.storage_volumes[0].size_gb == 25


def test_blocker_spellings_are_normalized_and_deduplicated() -> None:
    cim = _translate(_vm(has_rdm_disks=True, migration_blockers=["rdm_disk_present", "RDM_DISK"]))
    unit = cim.compute_units[0]

    assert unit.blockers == ["rdm_disk"]
    assert unit.migration_status == MigrationStatus.BLOCKED


def test_soft_blocker_marks_needs_review_not_blocked() -> None:
    cim = _translate(_vm(vapp_config_present=True))
    unit = cim.compute_units[0]

    assert unit.blockers == ["vapp_config"]
    assert unit.migration_status == MigrationStatus.NEEDS_REVIEW
