from __future__ import annotations

import re

from cim.schema import CanonicalInfrastructureModel, ClusterSemantics
from providers.common import hcl_string, hcl_value


def render_placement(
    cim: CanonicalInfrastructureModel,
    required_tags: dict[str, str] | None = None,
) -> dict[str, str]:
    """Render one aws_placement_group per DRS cluster (logical key aws-migration/placement/placement_groups.tf)."""
    clusters = _clusters(cim)
    path = "aws-migration/placement/placement_groups.tf"

    if not clusters:
        return {path: "# No DRS clusters discovered; no placement groups required.\n"}

    tags = _build_required_tags(cim, required_tags)
    lines: list[str] = []
    for name, semantics in clusters:
        strategy = "cluster" if semantics == ClusterSemantics.AFFINITY else "spread"
        lines.append(f'# VMware cluster {name} (semantics: {semantics.value}).')
        if strategy == "spread":
            lines.append('# spread placement groups hold at most 7 instances per Availability Zone; review for large clusters.')
        lines.append(f'resource "aws_placement_group" "{_terraform_identifier(name)}" {{')
        lines.append(f'  name     = {hcl_string(name)}')
        lines.append(f'  strategy = "{strategy}"')
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


def _build_required_tags(cim: CanonicalInfrastructureModel, required_tags: dict[str, str] | None) -> dict[str, str]:
    defaults = {
        "Environment": "var.environment",
        "Owner": "var.owner",
        "MigratedFrom": cim.migrated_from,
        "SourceVCenter": cim.source_vcenter,
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
