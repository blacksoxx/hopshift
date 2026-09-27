from __future__ import annotations

import re

from cim.schema import CanonicalInfrastructureModel, ClusterSemantics
from providers.common import hcl_string, hcl_value


def render_placement(
    cim: CanonicalInfrastructureModel,
    required_tags: dict[str, str] | None = None,
) -> dict[str, str]:
    """Render Azure placement resources per DRS cluster.

    Affinity clusters become proximity placement groups; everything else (HA, anti-affinity,
    unknown) becomes an availability set so VMs are spread across fault domains.
    """
    clusters = _clusters(cim)
    path = "azure-migration/placement/placement_groups.tf"

    if not clusters:
        return {path: "# No DRS clusters discovered; no placement resources required.\n"}

    tags = _build_required_tags(cim.source_vcenter, required_tags)
    lines: list[str] = []
    for name, semantics in clusters:
        ref = _terraform_identifier(name)
        lines.append(f'# VMware cluster {name} (semantics: {semantics.value}).')
        if semantics == ClusterSemantics.AFFINITY:
            lines.append(f'resource "azurerm_proximity_placement_group" "{ref}" {{')
            lines.append(f'  name                = "${{var.name_prefix}}-ppg-{ref}"')
            lines.append('  location            = var.location')
            lines.append('  resource_group_name = var.resource_group_name')
        else:
            lines.append(f'resource "azurerm_availability_set" "{ref}" {{')
            lines.append(f'  name                         = "${{var.name_prefix}}-avset-{ref}"')
            lines.append('  location                     = var.location')
            lines.append('  resource_group_name          = var.resource_group_name')
            lines.append('  platform_fault_domain_count  = 2')
            lines.append('  platform_update_domain_count = 5')
            lines.append('  managed                      = true')
        lines.append('')
        lines.append('  tags = {')
        lines.append(f'    Name = {hcl_string(name)}')
        for key, value in tags.items():
            lines.append(f'    {key} = {hcl_value(value)}')
        lines.append('  }')
        lines.append('}')
        lines.append('')

    return {path: "\n".join(lines).strip() + "\n"}


def _clusters(cim: CanonicalInfrastructureModel) -> list[tuple[str, ClusterSemantics]]:
    semantics = {cluster.name: cluster.semantics for cluster in cim.clusters}
    for compute_unit in cim.compute_units:
        if compute_unit.cluster_ref and compute_unit.cluster_ref not in semantics:
            semantics[compute_unit.cluster_ref] = ClusterSemantics.UNKNOWN
    return sorted(semantics.items())


def _build_required_tags(source_vcenter: str, required_tags: dict[str, str] | None) -> dict[str, str]:
    defaults = {
        "Environment": "var.environment",
        "Owner": "var.owner",
        "MigratedFrom": "vmware-vcenter",
        "SourceVCenter": source_vcenter,
    }
    if not required_tags:
        return defaults
    merged = dict(defaults)
    for key, value in required_tags.items():
        merged[str(key)] = str(value)
    return merged


def _terraform_identifier(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_]", "_", value.strip())
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    if not normalized:
        return "cluster"
    if normalized[0].isdigit():
        normalized = f"r_{normalized}"
    return normalized.lower()
