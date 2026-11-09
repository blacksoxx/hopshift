from __future__ import annotations

from agent.nodes.risk_assessor import risk_assessor
from cim.schema import (
    NIC,
    CanonicalInfrastructureModel,
    ComputeUnit,
    DistributedSwitch,
    MigrationStatus,
    NetworkTopology,
    PortGroup,
    StorageVolume,
    TargetProvider,
)


def _sample_cim() -> CanonicalInfrastructureModel:
    return CanonicalInfrastructureModel(
        source_vcenter="vc01.local",
        target_provider=TargetProvider.AWS,
        network_topology=NetworkTopology(
            distributed_switches=[
                DistributedSwitch(
                    name="dvs-main",
                    port_groups=[PortGroup(name="pg-app", vlan_id="100")],
                )
            ]
        ),
        compute_units=[
            ComputeUnit(
                id="cu-1",
                name="app-1",
                vcpus=2,
                ram_mb=4096,
                migration_status=MigrationStatus.READY,
                nics=[NIC(name="nic-1", port_group_ref="pg-app", mac_address="00:11:22:33:44:55")],
                storage_volumes=[
                    StorageVolume(
                        id="disk-1",
                        size_gb=100,
                        datastore="ds-1",
                    )
                ],
            )
        ],
    )


def test_risk_assessor_populates_assessment_result() -> None:
    state = {
        "discovery_data": {"metadata": {}, "virtual_machines": []},
        "cim": _sample_cim(),
        "messages": [],
        "status": "pending",
    }

    updated = risk_assessor(state)  # type: ignore[arg-type]

    assert "assessment_result" in updated
    result = updated["assessment_result"]
    assert result["summary"]["total_resources"] >= 1
    assert len(result["resources"]) >= 1


def test_risk_assessor_handles_generic_top_level_resources() -> None:
    state = {
        "discovery_data": {
            "metadata": {},
            "virtual_machines": [],
            "route_tables": [{"id": "rt-1", "migration_blocked": True}],
        },
        "cim": _sample_cim(),
        "messages": [],
        "status": "pending",
    }

    updated = risk_assessor(state)  # type: ignore[arg-type]
    resources = updated["assessment_result"]["resources"]

    assert any(resource["resource_type"] == "route_table" for resource in resources)
