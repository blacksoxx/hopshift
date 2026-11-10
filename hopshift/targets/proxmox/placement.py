"""Placement for the Proxmox VE target: HA groups, HA resources and affinity rules.

A VMware cluster becomes a Proxmox HA group whose node set is var.ha_nodes (var.proxmox_node when
empty); every VM of an HA-enabled cluster becomes an HA resource in that group. Affinity and
anti-affinity semantics are rendered as `proxmox_virtual_environment_harule` resources, which need
Proxmox VE 9 and are therefore gated by var.ha_rules_enabled (default false). Proxmox has no soft
anti-affinity: DRS-style spreading is documented as a TODO instead of a strict rule.
"""
from __future__ import annotations

from hopshift.cim.schema import CanonicalInfrastructureModel, ClusterSemantics, ComputeCluster, ComputeUnit
from hopshift.targets.common import hcl_string
from hopshift.targets.proxmox import (
    RESOURCE_HA_GROUP,
    RESOURCE_HA_RESOURCE,
    RESOURCE_HA_RULE,
    RESOURCE_VM,
    ROOT,
    cluster_members,
    clusters,
    comment_text,
    config_id,
    ha_managed,
    terraform_identifier,
)

_NODE_SET = "{ for node in (length(var.ha_nodes) > 0 ? var.ha_nodes : [var.proxmox_node]) : node => null }"


def render_placement(
    cim: CanonicalInfrastructureModel,
    required_tags: dict[str, str] | None = None,
) -> dict[str, str]:
    """Render HA groups, HA resources and affinity rules (logical key proxmox-migration/placement/placement_groups.tf)."""
    del required_tags  # HA objects carry no tags
    path = f"{ROOT}/placement/placement_groups.tf"
    all_clusters = clusters(cim)
    if not all_clusters:
        return {path: "# No clusters discovered; no HA groups, HA resources or affinity rules required.\n"}

    lines: list[str] = []
    for cluster in all_clusters:
        if lines:
            lines.append("")
        lines.extend(_render_cluster(cluster, cluster_members(cim, cluster.name)))
    return {path: "\n".join(lines).strip() + "\n"}


def _render_cluster(cluster: ComputeCluster, members: list[ComputeUnit]) -> list[str]:
    name = comment_text(cluster.name)
    group_ref = terraform_identifier(cluster.name, "cluster")
    group_id = config_id(cluster.name)
    ha_state = {True: "on", False: "off", None: "unknown"}[cluster.ha_enabled]
    member_names = ", ".join(comment_text(member.name) for member in members) or "no migratable VMs"

    lines = [f"# VMware cluster {name} (semantics: {cluster.semantics.value}, HA: {ha_state}); members: {member_names}."]
    if not ha_managed(cluster):
        lines.append(f"# VMware HA is disabled on {name}; no HA group or HA resources are rendered. Enable HA on the")
        lines.append("# Proxmox side by adding a proxmox_virtual_environment_hagroup and one haresource per VM.")
        return lines

    lines.append("# The group spans var.ha_nodes (var.proxmox_node alone when empty); give nodes a priority to prefer them.")
    lines.append(f'resource "{RESOURCE_HA_GROUP}" "{group_ref}" {{')
    lines.append(f'  group       = "{group_id}"')
    lines.append(f"  comment     = {hcl_string(f'Migrated from VMware cluster {name}')}")
    lines.append(f"  nodes       = {_NODE_SET}")
    lines.append("  restricted  = false")
    lines.append("  no_failback = false")
    lines.append("}")

    for member in members:
        member_ref = terraform_identifier(member.name)
        lines.append("")
        lines.append(f'resource "{RESOURCE_HA_RESOURCE}" "{member_ref}" {{')
        lines.append(f"  depends_on = [{RESOURCE_HA_GROUP}.{group_ref}]")
        lines.append("")
        lines.append(f'  resource_id = "vm:${{{RESOURCE_VM}.{member_ref}.vm_id}}"')
        lines.append(f"  group       = {RESOURCE_HA_GROUP}.{group_ref}.group")
        lines.append('  state       = "started"')
        lines.append(f"  comment     = {hcl_string(f'{comment_text(member.name)} (VMware cluster {name})')}")
        lines.append("}")

    lines.append("")
    lines.extend(_render_affinity(cluster, members, group_id))
    return lines


def _render_affinity(cluster: ComputeCluster, members: list[ComputeUnit], group_id: str) -> list[str]:
    name = comment_text(cluster.name)
    if len(members) < 2:
        return [f"# Affinity: {name} has fewer than two migratable VMs; no affinity rule applies."]

    if cluster.semantics == ClusterSemantics.AFFINITY:
        affinity, label = "positive", "keep the members on the same node"
    elif cluster.semantics == ClusterSemantics.ANTI_AFFINITY:
        affinity, label = "negative", "keep the members on different nodes"
    else:
        return [
            f"# TODO: VMware DRS spreads the members of {name} across hosts without a strict rule. Proxmox has no soft",
            "# anti-affinity; on Proxmox VE 9 a strict rule can be added as proxmox_virtual_environment_harule",
            '# { type = "resource-affinity", affinity = "negative" } (see docs/targets/proxmox.md). Proxmox VE 8 has',
            "# no anti-affinity at all.",
        ]

    rule_ref = f"{terraform_identifier(cluster.name, 'cluster')}_{cluster.semantics.value}"
    rule_id = config_id(f"{group_id}-{cluster.semantics.value.replace('_', '-')}")
    lines = [
        f"# {cluster.semantics.value}: {label}. HA affinity rules need Proxmox VE 9; set",
        "# var.ha_rules_enabled = true once the cluster runs 9.x. The rule is strict: with fewer nodes than",
        "# members, negative affinity keeps some VMs stopped.",
        f'resource "{RESOURCE_HA_RULE}" "{rule_ref}" {{',
        "  count = var.ha_rules_enabled ? 1 : 0",
        "",
        f'  rule     = "{rule_id}"',
        '  type     = "resource-affinity"',
        f'  affinity = "{affinity}"',
        f"  comment  = {hcl_string(f'Migrated from VMware cluster {name} ({cluster.semantics.value})')}",
        "  resources = [",
    ]
    lines.extend(f"    {RESOURCE_HA_RESOURCE}.{terraform_identifier(member.name)}.resource_id," for member in members)
    lines.append("  ]")
    lines.append("}")
    return lines
