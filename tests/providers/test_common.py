from __future__ import annotations

import pytest

from providers.common import safe_file_stem


@pytest.mark.parametrize(
    "name, expected",
    [
        ("app-1", "app-1"),
        ("centos", "centos"),
        ("web.prod.01", "web.prod.01"),
        ("../../etc/passwd", "etc_passwd"),
        ("VM Network/one", "VM_Network_one"),
        (".hidden", "hidden"),
        ("", "resource"),
        ("///", "resource"),
    ],
)
def test_safe_file_stem(name: str, expected: str) -> None:
    assert safe_file_stem(name) == expected


def test_safe_file_stem_truncates_long_names() -> None:
    assert len(safe_file_stem("a" * 500)) == 100


def test_provider_renderers_sanitize_vm_names_in_paths() -> None:
    from cim.schema import CanonicalInfrastructureModel, ComputeUnit, NetworkTopology, TargetProvider
    from providers.aws.compute import render_compute
    from providers.aws.storage import render_storage

    cim = CanonicalInfrastructureModel(
        source_vcenter="vc",
        target_provider=TargetProvider.AWS,
        network_topology=NetworkTopology(),
        compute_units=[ComputeUnit(id="1", name="../../escape", vcpus=1, ram_mb=1024)],
    )

    assert set(render_compute(cim)) == {"aws-migration/compute/escape.tf"}
    assert set(render_storage(cim)) == {"aws-migration/storage/escape_disks.tf"}
