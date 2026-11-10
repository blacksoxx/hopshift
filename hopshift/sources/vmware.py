"""VMware vSphere discovery (schema `vmware-discovery-stage1`) -> CIM 1.1.

This is the only module that knows VMware field names. Everything downstream consumes the CIM.
Optional 1.1 collections (`clusters[]` with DRS rules, `distributed_switches[]`) are used when
the playbook emits them and inferred from the VM records otherwise.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from hopshift.cim.blockers import HARD_BLOCKERS, blockers_for_vm
from hopshift.cim.schema import (
    NIC,
    Architecture,
    CanonicalInfrastructureModel,
    ClusterSemantics,
    ComputeCluster,
    ComputeUnit,
    MigrationStatus,
    NetworkSegment,
    NetworkTopology,
    SourceEndpoint,
    SourcePlatform,
    StorageVolume,
    TargetProvider,
    VirtualSwitch,
)

SCHEMA_NAME = "vmware-discovery-stage1"
PLATFORM = SourcePlatform.VMWARE_VSPHERE

# Blockers that make a ComputeUnit `blocked`; any other known blocker marks it `needs_review`.
SUPPORTED_BLOCKERS = set(HARD_BLOCKERS)

_LINUX_MARKERS = ("linux", "centos", "ubuntu", "rhel", "red hat", "debian", "sles", "suse", "rocky", "alma", "oracle", "fedora", "amazon")
_SWITCH_KEYS = ("switch_name", "distributed_switch", "vds_name", "dvs_name")
_SEGMENT_KEYS = ("network_name", "portgroup_name", "port_group", "label")


def translate_vmware_discovery_to_cim(
    discovery_data: dict[str, Any],
    target_provider: TargetProvider | str,
) -> CanonicalInfrastructureModel:
    """Translate VMware discovery JSON into a CIM document."""
    vms = discovery_data.get("virtual_machines", []) or []
    if not isinstance(vms, list):
        raise ValueError("Expected 'virtual_machines' to be a list in discovery data")

    metadata = discovery_data.get("metadata") if isinstance(discovery_data.get("metadata"), dict) else {}
    source = _build_source(vms, metadata)

    compute_units = [_build_compute_unit(vm) for vm in vms if isinstance(vm, dict)]

    return CanonicalInfrastructureModel(
        cim_schema_version="1.1",
        source_vcenter=source.name,
        source=source,
        target_provider=_to_target_provider(target_provider),
        network_topology=_build_network_topology(vms, discovery_data.get("distributed_switches")),
        clusters=_build_clusters(vms, discovery_data.get("clusters")),
        compute_units=compute_units,
    )


# ── source ────────────────────────────────────────────────────────────────────


def _build_source(vms: list[dict[str, Any]], metadata: dict[str, Any]) -> SourceEndpoint:
    name = ""
    hostname = None
    for vm in vms:
        if isinstance(vm, dict) and vm.get("source_vcenter"):
            name = str(vm["source_vcenter"])
            hostname = _optional_str(vm.get("source_vcenter_hostname"))
            break
    if not name:
        vcenters = metadata.get("vcenters_queried", []) or []
        if isinstance(vcenters, list) and vcenters:
            name = str(vcenters[0])

    return SourceEndpoint(
        platform=PLATFORM,
        name=name,
        hostname=hostname,
        schema_name=_optional_str(metadata.get("schema_name")),
        schema_version=_optional_str(metadata.get("schema_version")),
        discovered_at=_optional_str(metadata.get("generated_at")),
    )


# ── compute units ─────────────────────────────────────────────────────────────


def _build_compute_unit(vm: dict[str, Any]) -> ComputeUnit:
    blockers = blockers_for_vm(vm, platform=PLATFORM)
    cluster_ref_raw = vm.get("cluster")
    cluster_ref = str(cluster_ref_raw).strip() if cluster_ref_raw is not None else None
    guest_os = _optional_str(vm.get("guest_os"))
    guest_os_id = _optional_str(vm.get("guest_os_id"))

    return ComputeUnit(
        id=str(vm.get("discovery_key") or vm.get("moid") or vm.get("uuid") or ""),
        name=str(vm.get("vm_name") or vm.get("name") or "unknown-compute-unit"),
        vcpus=int(vm.get("vcpus") or 1),
        ram_mb=int(vm.get("ram_mb") or 1),
        migration_status=_infer_migration_status(vm, blockers),
        blockers=blockers,
        cluster_ref=cluster_ref or None,
        is_encrypted=bool(vm.get("is_encrypted", False)),
        has_vtpm=bool(vm.get("has_vtpm", False)),
        nics=_build_nics(vm),
        storage_volumes=_build_storage_volumes(vm),
        architecture=_architecture(vm),
        guest_os=guest_os,
        guest_os_id=guest_os_id,
        guest_family=_guest_family(guest_os, guest_os_id),
        firmware=_firmware(vm.get("firmware")),
        power_state=_power_state(vm.get("power_state")),
        is_template=bool(vm.get("is_template", False)),
        snapshot_count=_snapshot_count(vm),
        ip_addresses=_ip_addresses(vm),
        source_tags=_source_tags(vm.get("tags")),
        custom_attributes=_custom_attributes(vm.get("custom_attributes")),
        annotation=_optional_str(vm.get("annotation")),
        cpu_reservation_mhz=_optional_int(vm.get("cpu_reservation_mhz")),
        memory_reservation_mb=_optional_int(vm.get("memory_reservation_mb")),
        cores_per_socket=_optional_int(vm.get("cores_per_socket")),
        source_endpoint=_optional_str(vm.get("source_vcenter")),
        image_ref=_optional_str(vm.get("image_ref")),
    )


def _infer_migration_status(vm: dict[str, Any], blockers: list[str]) -> MigrationStatus:
    if any(blocker in SUPPORTED_BLOCKERS for blocker in blockers) or vm.get("migration_blocked"):
        return MigrationStatus.BLOCKED
    if blockers or vm.get("has_vtpm"):
        return MigrationStatus.NEEDS_REVIEW
    return MigrationStatus.READY


def _architecture(vm: dict[str, Any]) -> Architecture:
    raw = str(vm.get("architecture") or "").strip().lower()
    if raw in {"", "x86_64", "amd64", "x64"}:
        # vSphere runs x86 hosts; the ESXi-on-Arm fling is the only exception and is not
        # something the playbook reports today.
        return Architecture.X86_64
    if raw in {"aarch64", "arm64"}:
        return Architecture.AARCH64
    if raw in {"ppc64le", "ppc64"}:
        return Architecture.PPC64LE
    if raw == "s390x":
        return Architecture.S390X
    return Architecture.UNKNOWN


def _guest_family(guest_os: str | None, guest_os_id: str | None) -> str | None:
    haystack = f"{guest_os or ''} {guest_os_id or ''}".lower()
    if not haystack.strip():
        return None
    if "windows" in haystack:
        return "windows"
    if any(marker in haystack for marker in _LINUX_MARKERS):
        return "linux"
    return "other"


def _firmware(value: object) -> str | None:
    text = str(value or "").strip().lower()
    if text in {"bios"}:
        return "bios"
    if text in {"efi", "uefi"}:
        return "efi"
    return None


def _power_state(value: object) -> str | None:
    text = str(value or "").strip().lower()
    if text in {"poweredon", "on", "running"}:
        return "on"
    if text in {"poweredoff", "off", "stopped"}:
        return "off"
    if text in {"suspended", "paused"}:
        return "suspended"
    return None


def _snapshot_count(vm: dict[str, Any]) -> int:
    count = vm.get("snapshot_count")
    if isinstance(count, int) and count >= 0:
        return count
    snapshots = vm.get("snapshots")
    return len(snapshots) if isinstance(snapshots, list) else 0


def _ip_addresses(vm: dict[str, Any]) -> list[str]:
    addresses: list[str] = []
    candidates = list(vm.get("all_ip_addresses") or []) if isinstance(vm.get("all_ip_addresses"), list) else []
    if vm.get("ip_address"):
        candidates.insert(0, vm["ip_address"])
    for item in candidates:
        text = str(item).strip()
        if text and text not in addresses:
            addresses.append(text)
    return addresses


def _source_tags(value: object) -> dict[str, str]:
    tags: dict[str, str] = {}
    if not isinstance(value, list):
        return tags
    for item in value:
        if isinstance(item, dict):
            key = str(item.get("category") or item.get("key") or item.get("name") or "").strip()
            val = str(item.get("name") or item.get("value") or "").strip()
            if key:
                tags[key] = val
        elif isinstance(item, str) and item.strip():
            key, _, val = item.partition("=")
            tags[key.strip()] = val.strip()
    return tags


def _custom_attributes(value: object) -> dict[str, str]:
    attributes: dict[str, str] = {}
    if isinstance(value, dict):
        return {str(k): str(v) for k, v in value.items()}
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                key = str(item.get("key") or item.get("name") or "").strip()
                if key:
                    attributes[key] = str(item.get("value") or "")
    return attributes


# ── storage ───────────────────────────────────────────────────────────────────


def _build_storage_volumes(vm: dict[str, Any]) -> list[StorageVolume]:
    volumes: list[StorageVolume] = []
    is_vm_encrypted = bool(vm.get("is_encrypted", False))

    for idx, disk in enumerate(vm.get("disks", []) or []):
        if not isinstance(disk, dict):
            continue
        backing_type = str(disk.get("backing_type", "")).lower()
        # An absent/empty sharing value means "unknown", not "shared".
        sharing = str(disk.get("sharing") or "").strip().lower()
        disk_id = str(disk.get("filename") or disk.get("label") or disk.get("unit_number") or f"disk-{idx + 1}")
        size_gb = max(1, int(round(float(disk.get("size_gb", 1) or 1))))

        volumes.append(
            StorageVolume(
                id=disk_id,
                size_gb=size_gb,
                datastore=_optional_str(disk.get("datastore")),
                thin_provisioned=disk.get("thin_provisioned"),
                is_encrypted=is_vm_encrypted,
                is_shared=bool(disk.get("multi_writer")) or sharing not in {"", "sharingnone"},
                is_rdm="rdm" in backing_type or "rawdiskmapping" in backing_type,
                disk_mode=_optional_str(disk.get("disk_mode")),
                controller_type=_optional_str(disk.get("controller_type")),
                unit_number=_optional_int(disk.get("unit_number")),
                backing_type=_optional_str(disk.get("backing_type")),
            )
        )

    return volumes


# ── network ───────────────────────────────────────────────────────────────────


def _segment_name(network: dict[str, Any], fallback_index: int) -> str:
    for key in _SEGMENT_KEYS:
        value = network.get(key)
        if value:
            return str(value)
    return f"port-group-{fallback_index}"


def _switch_name(network: dict[str, Any]) -> str:
    for key in _SWITCH_KEYS:
        value = network.get(key)
        if value:
            return str(value)
    return "default-dvs"


def _build_nics(vm: dict[str, Any]) -> list[NIC]:
    nics: list[NIC] = []
    for idx, network in enumerate(vm.get("networks", []) or [], start=1):
        if not isinstance(network, dict):
            continue
        ips = network.get("ip_addresses")
        nics.append(
            NIC(
                name=str(network.get("label") or f"nic-{idx}"),
                port_group_ref=_segment_name(network, idx),
                mac_address=_optional_str(network.get("mac_address")),
                connected=network.get("connected") if isinstance(network.get("connected"), bool) else None,
                ip_addresses=[str(ip) for ip in ips if str(ip).strip()] if isinstance(ips, list) else [],
                network_type=_optional_str(network.get("network_type") or network.get("backing_type")),
            )
        )
    return nics


def _build_network_topology(vms: list[dict[str, Any]], declared_switches: object) -> NetworkTopology:
    switch_to_segments: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    switch_types: dict[str, str | None] = {}

    # 1.1 top-level declaration takes precedence when the playbook emits it.
    if isinstance(declared_switches, list):
        for switch in declared_switches:
            if not isinstance(switch, dict) or not switch.get("name"):
                continue
            name = str(switch["name"])
            switch_types[name] = _optional_str(switch.get("switch_type"))
            for segment in switch.get("port_groups") or switch.get("segments") or []:
                if isinstance(segment, dict) and segment.get("name"):
                    switch_to_segments[name][str(segment["name"])] = {
                        "vlan_id": str(segment.get("vlan_id") or ""),
                        "segment_type": _optional_str(segment.get("segment_type") or segment.get("vlan_type")),
                        "key": _optional_str(segment.get("key")),
                    }

    for vm in vms:
        if not isinstance(vm, dict):
            continue
        for idx, network in enumerate(vm.get("networks", []) or [], start=1):
            if not isinstance(network, dict):
                continue
            switch_name = _switch_name(network)
            segment_name = _segment_name(network, idx)
            existing = switch_to_segments[switch_name].get(segment_name)
            if existing is None:
                switch_to_segments[switch_name][segment_name] = {
                    "vlan_id": str(network.get("vlan_id") or ""),
                    "segment_type": _optional_str(network.get("network_type")),
                    "key": _optional_str(network.get("portgroup_key")),
                }
            switch_types.setdefault(switch_name, _optional_str(network.get("switch_type")))

    switches: list[VirtualSwitch] = []
    for switch_name in sorted(switch_to_segments):
        segments = [
            NetworkSegment(name=name, vlan_id=spec["vlan_id"], segment_type=spec["segment_type"], key=spec["key"])
            for name, spec in sorted(switch_to_segments[switch_name].items())
        ]
        switches.append(VirtualSwitch(name=switch_name, port_groups=segments, switch_type=switch_types.get(switch_name)))

    return NetworkTopology(distributed_switches=switches)


# ── clusters ──────────────────────────────────────────────────────────────────


def _build_clusters(vms: list[dict[str, Any]], declared_clusters: object) -> list[ComputeCluster]:
    specs: dict[str, dict[str, Any]] = {}

    if isinstance(declared_clusters, list):
        for cluster in declared_clusters:
            if isinstance(cluster, dict) and cluster.get("name"):
                specs[str(cluster["name"]).strip()] = cluster

    for vm in vms:
        if isinstance(vm, dict) and vm.get("cluster") is not None and str(vm.get("cluster")).strip():
            specs.setdefault(str(vm.get("cluster")).strip(), {})

    clusters: list[ComputeCluster] = []
    for name in sorted(specs):
        spec = specs[name]
        clusters.append(
            ComputeCluster(
                name=name,
                semantics=_cluster_semantics(spec),
                ha_enabled=spec.get("ha_enabled") if isinstance(spec.get("ha_enabled"), bool) else None,
                drs_enabled=spec.get("drs_enabled") if isinstance(spec.get("drs_enabled"), bool) else None,
                datacenter=_optional_str(spec.get("datacenter")),
            )
        )
    return clusters


def _cluster_semantics(spec: dict[str, Any]) -> ClusterSemantics:
    """DRS rules decide placement semantics; anti-affinity wins over affinity when both exist."""
    rule_types: set[str] = set()
    for rule in spec.get("drs_rules") or []:
        if not isinstance(rule, dict) or rule.get("enabled") is False:
            continue
        rule_type = str(rule.get("type") or "").strip().lower().replace("-", "_")
        if rule_type in {"anti_affinity", "shouldnotrunonsamehost", "mustnotrunonsamehost", "vm_anti_affinity"}:
            rule_types.add("anti_affinity")
        elif rule_type in {"affinity", "shouldrunonsamehost", "mustrunonsamehost", "vm_affinity"}:
            rule_types.add("affinity")

    if "anti_affinity" in rule_types:
        return ClusterSemantics.ANTI_AFFINITY
    if "affinity" in rule_types:
        return ClusterSemantics.AFFINITY
    if spec.get("ha_enabled") is True:
        return ClusterSemantics.HA
    return ClusterSemantics.UNKNOWN


# ── helpers ───────────────────────────────────────────────────────────────────


def _to_target_provider(provider: object) -> str:
    return str(TargetProvider(provider))


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None
