from __future__ import annotations

import re

from hopshift.cim.schema import CanonicalInfrastructureModel, ClusterSemantics
from hopshift.targets.common import hcl_string


def render_placement(
    cim: CanonicalInfrastructureModel,
    required_tags: dict[str, str] | None = None,
) -> dict[str, str]:
    """Render one openstack_compute_servergroup_v2 per DRS cluster."""
    del required_tags  # server groups do not support metadata
    clusters = _clusters(cim)
    path = "openstack-migration/placement/placement_groups.tf"

    if not clusters:
        return {path: "# No DRS clusters discovered; no server groups required.\n"}

    lines: list[str] = []
    for name, semantics in clusters:
        policy = "affinity" if semantics == ClusterSemantics.AFFINITY else "soft-anti-affinity"
        lines.append(f'# VMware cluster {name} (semantics: {semantics.value}).')
        lines.append(f'resource "openstack_compute_servergroup_v2" "{_terraform_identifier(name)}" {{')
        lines.append(f'  name     = {hcl_string(name)}')
        lines.append(f'  policies = ["{policy}"]')
        lines.append('}')
        lines.append('')

    return {path: "\n".join(lines).strip() + "\n"}


def _clusters(cim: CanonicalInfrastructureModel) -> list[tuple[str, ClusterSemantics]]:
    semantics = {cluster.name: cluster.semantics for cluster in cim.clusters}
    for compute_unit in cim.compute_units:
        if compute_unit.cluster_ref and compute_unit.cluster_ref not in semantics:
            semantics[compute_unit.cluster_ref] = ClusterSemantics.UNKNOWN
    return sorted(semantics.items())


def _terraform_identifier(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_]", "_", value.strip())
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    if not normalized:
        return "cluster"
    if normalized[0].isdigit():
        normalized = f"r_{normalized}"
    return normalized.lower()
