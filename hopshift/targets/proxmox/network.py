"""Networking for the Proxmox VE target.

Proxmox networking is node-level: VM NICs attach to a Linux bridge and carry a VLAN tag, there is
no tenant network or subnet object. The renderer emits one node-level VLAN interface per VLAN the
VMware segments use (documenting the segment and giving the node an attachment point in it) and,
per VM, the Proxmox firewall: inbound denied by default, SSH or RDP and ICMP accepted only from the
management ranges (never from 0.0.0.0/0).
"""
from __future__ import annotations

from hopshift.cim.schema import CanonicalInfrastructureModel, ComputeUnit
from hopshift.targets.common import hcl_string, safe_file_stem
from hopshift.targets.proxmox import (
    RESOURCE_FIREWALL_OPTIONS,
    RESOURCE_FIREWALL_RULES,
    RESOURCE_VLAN,
    RESOURCE_VM,
    ROOT,
    comment_text,
    management_port,
    parse_vlan,
    terraform_identifier,
)


def render_networking(cim: CanonicalInfrastructureModel) -> dict[str, str]:
    """Render the VLAN interfaces (network/vlans.tf) and one firewall file per VM (firewall/<name>.tf)."""
    output = {f"{ROOT}/network/vlans.tf": _render_vlans(cim)}
    for compute_unit in cim.compute_units:
        output[f"{ROOT}/firewall/{safe_file_stem(compute_unit.name)}.tf"] = _render_firewall(compute_unit)
    return output


def _render_vlans(cim: CanonicalInfrastructureModel) -> str:
    tagged: dict[int, list[str]] = {}
    untagged: list[str] = []
    for switch in cim.network_topology.distributed_switches:
        for segment in switch.port_groups:
            label = f"{comment_text(segment.name)} ({comment_text(switch.name)})"
            tag = parse_vlan(segment.vlan_id)
            if tag is None:
                spec = comment_text(segment.vlan_id) or "untagged"
                untagged.append(f"{label}: {spec}")
            else:
                tagged.setdefault(tag, []).append(label)

    lines = [
        "# VMware port groups become 802.1Q tags on var.bridge: each VM NIC sets vlan_id, so the bridge must be",
        "# VLAN-aware (bridge-vlan-aware yes). The node-level VLAN interfaces below document every segment and",
        "# give the node an attachment point in the VLAN (no address is assigned); drop them if the node must",
        "# not be present in guest VLANs.",
    ]
    if untagged:
        lines.append("#")
        lines.append("# Segments without a single VLAN tag (NICs on them stay untagged on var.bridge):")
        lines.extend(f"#   - {entry}" for entry in untagged)
    if not tagged:
        lines.append("#")
        lines.append("# No VLAN-tagged segments discovered; no VLAN interfaces required.")
        return "\n".join(lines) + "\n"

    for tag in sorted(tagged):
        segments = ", ".join(tagged[tag])
        lines.append("")
        lines.append(f"# VLAN {tag}: VMware port group(s) {segments}.")
        lines.append(f'resource "{RESOURCE_VLAN}" "vlan_{tag}" {{')
        lines.append("  node_name = var.proxmox_node")
        lines.append(f'  name      = "${{var.bridge}}.{tag}"')
        lines.append(f"  comment   = {hcl_string(f'VMware VLAN {tag}: {segments}')}")
        lines.append("  autostart = true")
        lines.append("}")
    return "\n".join(lines) + "\n"


def _render_firewall(compute_unit: ComputeUnit) -> str:
    resource_name = terraform_identifier(compute_unit.name)
    port, service = management_port(compute_unit)
    vm_ref = f"{RESOURCE_VM}.{resource_name}"
    name = comment_text(compute_unit.name)

    lines = [
        f"# VM firewall for {name}: inbound denied by default; {service} and ICMP echo accepted only from",
        "# var.management_cidrs (RFC 1918 by default, never 0.0.0.0/0). Rules apply to the NICs that set",
        "# firewall = true on the VM resource.",
        f'resource "{RESOURCE_FIREWALL_OPTIONS}" "{resource_name}" {{',
        f"  node_name = {vm_ref}.node_name",
        f"  vm_id     = {vm_ref}.vm_id",
        "",
        "  enabled       = true",
        "  dhcp          = true",
        "  ipfilter      = false",
        "  macfilter     = true",
        "  ndp           = true",
        "  radv          = false",
        '  input_policy  = "DROP"',
        '  output_policy = "ACCEPT"',
        '  log_level_in  = "warning"',
        '  log_level_out = "nolog"',
        "}",
        "",
        f'resource "{RESOURCE_FIREWALL_RULES}" "{resource_name}" {{',
        f"  node_name = {vm_ref}.node_name",
        f"  vm_id     = {vm_ref}.vm_id",
        "",
        "  rule {",
        '    type    = "in"',
        '    action  = "ACCEPT"',
        f'    comment = "{service} from the management ranges only"',
        '    source  = join(",", var.management_cidrs)',
        '    proto   = "tcp"',
        f'    dport   = "{port}"',
        "  }",
        "",
        "  rule {",
        '    type    = "in"',
        '    action  = "ACCEPT"',
        '    comment = "ICMP echo from the management ranges"',
        '    source  = join(",", var.management_cidrs)',
        '    proto   = "icmp"',
        "  }",
        "}",
    ]
    return "\n".join(lines) + "\n"
