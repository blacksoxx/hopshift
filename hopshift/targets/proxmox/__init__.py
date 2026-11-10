"""Proxmox VE target: KVM virtual machines rendered for the bpg/proxmox Terraform provider.

The renderer modules (`compute`, `network`, `storage`, `placement`, `runtime`, `sizing_table`)
are resolved by the deterministic assembler through the TargetSpec registered in
`hopshift.targets.__init__`. This module holds the naming and lookup helpers they share:
Proxmox has its own rules for VM names (DNS labels), tags (lower-case `[a-z0-9_.+-]`),
HA group ids and guest OS types, and every renderer must agree on the Terraform identifier
of a VM because firewall, HA and disk resources reference the VM resource.
"""
from __future__ import annotations

import re

from hopshift.cim.schema import NIC, CanonicalInfrastructureModel, ClusterSemantics, ComputeCluster, ComputeUnit

ROOT = "proxmox-migration"

RESOURCE_VM = "proxmox_virtual_environment_vm"
RESOURCE_VLAN = "proxmox_virtual_environment_network_linux_vlan"
RESOURCE_FIREWALL_OPTIONS = "proxmox_virtual_environment_firewall_options"
RESOURCE_FIREWALL_RULES = "proxmox_virtual_environment_firewall_rules"
RESOURCE_HA_GROUP = "proxmox_virtual_environment_hagroup"
RESOURCE_HA_RESOURCE = "proxmox_virtual_environment_haresource"
RESOURCE_HA_RULE = "proxmox_virtual_environment_harule"

# Proxmox tags: lower-case, [a-z0-9_.+-]; everything else becomes a dash.
_TAG_UNSAFE = re.compile(r"[^a-z0-9_.+-]+")
_DNS_UNSAFE = re.compile(r"[^a-z0-9-]+")
_CONFIG_ID_UNSAFE = re.compile(r"[^A-Za-z0-9_-]+")
_VLAN_TAG = re.compile(r"^\d{1,4}$")

_WINDOWS_OS_TYPES: tuple[tuple[str, str], ...] = (
    ("2025", "win11"),
    ("2022", "win11"),
    ("windows 11", "win11"),
    ("2019", "win10"),
    ("2016", "win10"),
    ("windows 10", "win10"),
    ("2012", "win8"),
    ("windows 8", "win8"),
    ("2008 r2", "win7"),
    ("windows 7", "win7"),
    ("2008", "w2k8"),
    ("vista", "wvista"),
    ("2003", "w2k3"),
    ("xp", "wxp"),
    ("2000", "w2k"),
)
_LINUX_HINTS: tuple[str, ...] = (
    "linux", "ubuntu", "debian", "centos", "red hat", "rhel", "suse", "sles", "fedora", "oracle", "rocky", "alma",
    "photon", "amazon", "flatcar", "coreos",
)


def terraform_identifier(value: object, fallback: str = "resource") -> str:
    """Terraform resource label for a discovery name (same normalisation as the other targets)."""
    normalized = re.sub(r"[^a-zA-Z0-9_]", "_", str(value).strip())
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    if not normalized:
        return fallback
    if normalized[0].isdigit():
        normalized = f"r_{normalized}"
    return normalized.lower()


def dns_name(value: object, fallback: str = "vm") -> str:
    """Proxmox requires VM names to be valid DNS labels: lower-case letters, digits and dashes, 63 chars."""
    text = _DNS_UNSAFE.sub("-", str(value).strip().lower())
    text = re.sub(r"-+", "-", text).strip("-")
    if not text:
        return fallback
    return text[:63].rstrip("-") or fallback


def proxmox_tag(value: object) -> str:
    """A single tag component: lower-case `[a-z0-9_.+-]`, runs of other characters become one dash."""
    text = _TAG_UNSAFE.sub("-", str(value).strip().lower())
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text


def config_id(value: object, fallback: str = "group") -> str:
    """HA group / rule identifier: letters, digits, dash and underscore, starting with a letter."""
    text = _CONFIG_ID_UNSAFE.sub("-", str(value).strip())
    text = re.sub(r"-{2,}", "-", text).strip("-_")
    if not text:
        return fallback
    if not text[0].isalpha():
        text = f"c-{text}"
    return text[:64]


def comment_text(value: object) -> str:
    """One-line text safe to place after `#` in HCL (discovery names may contain line breaks)."""
    return " ".join(str(value).split())


# ── guest OS ──────────────────────────────────────────────────────────────────


def guest_family(compute_unit: ComputeUnit) -> str:
    """linux | windows | other, from the CIM field when set, otherwise from the guest OS text."""
    if compute_unit.guest_family:
        return compute_unit.guest_family
    text = (compute_unit.guest_os or "").lower()
    if "windows" in text:
        return "windows"
    if any(hint in text for hint in _LINUX_HINTS):
        return "linux"
    return "other"


def os_type(compute_unit: ComputeUnit) -> str:
    """Proxmox `operating_system.type`: l26 for Linux, winXX for Windows releases, other otherwise."""
    family = guest_family(compute_unit)
    if family == "linux":
        return "l26"
    if family == "windows":
        text = (compute_unit.guest_os or "").lower()
        for hint, value in _WINDOWS_OS_TYPES:
            if hint in text:
                return value
        return "win10"
    text = (compute_unit.guest_os or "").lower()
    if "solaris" in text:
        return "solaris"
    return "other"


def management_port(compute_unit: ComputeUnit) -> tuple[int, str]:
    """The administrative port the firewall allows from the management ranges: RDP on Windows, SSH elsewhere."""
    if guest_family(compute_unit) == "windows":
        return 3389, "RDP"
    return 22, "SSH"


# ── networking ────────────────────────────────────────────────────────────────


def parse_vlan(value: object) -> int | None:
    """A single 802.1Q tag (1-4094) or None for untagged / trunk / unknown VLAN specifications."""
    text = str(value or "").strip()
    if not _VLAN_TAG.match(text):
        return None
    tag = int(text)
    if tag < 1 or tag > 4094:
        return None
    return tag


def vlan_lookup(cim: CanonicalInfrastructureModel) -> dict[str, int]:
    """Segment (port group) name, lower-cased, to its VLAN tag when it has a single one."""
    lookup: dict[str, int] = {}
    for switch in cim.network_topology.distributed_switches:
        for segment in switch.port_groups:
            tag = parse_vlan(segment.vlan_id)
            if tag is None:
                continue
            lookup.setdefault(segment.name.strip().lower(), tag)
            if segment.key:
                lookup.setdefault(segment.key.strip().lower(), tag)
    return lookup


def nic_vlan(nic: NIC, lookup: dict[str, int]) -> int | None:
    return lookup.get(nic.port_group_ref.strip().lower())


# ── clusters ──────────────────────────────────────────────────────────────────


def clusters(cim: CanonicalInfrastructureModel) -> list[ComputeCluster]:
    """Every cluster referenced by the CIM, including ones only named by a ComputeUnit."""
    by_name: dict[str, ComputeCluster] = {cluster.name: cluster for cluster in cim.clusters}
    for compute_unit in cim.compute_units:
        if compute_unit.cluster_ref and compute_unit.cluster_ref not in by_name:
            by_name[compute_unit.cluster_ref] = ComputeCluster(name=compute_unit.cluster_ref, semantics=ClusterSemantics.UNKNOWN)
    return [by_name[name] for name in sorted(by_name)]


def cluster_members(cim: CanonicalInfrastructureModel, cluster_name: str) -> list[ComputeUnit]:
    return [compute_unit for compute_unit in cim.compute_units if compute_unit.cluster_ref == cluster_name]


def ha_managed(cluster: ComputeCluster) -> bool:
    """A VMware cluster is treated as HA unless discovery says HA is off (unknown counts as on)."""
    return cluster.ha_enabled is not False


def ha_members(cim: CanonicalInfrastructureModel) -> dict[str, list[ComputeUnit]]:
    """Cluster name to the ComputeUnits that get a Proxmox HA resource."""
    return {
        cluster.name: cluster_members(cim, cluster.name)
        for cluster in clusters(cim)
        if ha_managed(cluster)
    }
