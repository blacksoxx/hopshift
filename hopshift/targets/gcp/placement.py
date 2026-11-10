from __future__ import annotations

import re

from hopshift.cim.schema import CanonicalInfrastructureModel, ClusterSemantics


def render_placement(
    cim: CanonicalInfrastructureModel,
    required_tags: dict[str, str] | None = None,
) -> dict[str, str]:
    """Render one google_compute_resource_policy (group placement) per DRS cluster.

    Spread placement across availability domains is used for every semantics value; GCP
    collocated placement has machine-type constraints that need manual review.
    """
    del required_tags  # resource policies do not support labels
    clusters = _clusters(cim)
    path = "gcp-migration/placement/placement_groups.tf"

    if not clusters:
        return {path: "# No DRS clusters discovered; no placement policies required.\n"}

    lines: list[str] = []
    for name, semantics in clusters:
        ref = _terraform_identifier(name)
        lines.append(f'# VMware cluster {name} (semantics: {semantics.value}).')
        if semantics == ClusterSemantics.AFFINITY:
            lines.append('# TODO: affinity semantics; consider collocation = "COLLOCATED" after checking machine-type support.')
        lines.append(f'resource "google_compute_resource_policy" "{ref}" {{')
        lines.append(f'  name    = "{_policy_name(name)}"')
        lines.append('  project = var.project_id')
        lines.append('  region  = var.region')
        lines.append('')
        lines.append('  group_placement_policy {')
        lines.append('    availability_domain_count = 2')
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


def _terraform_identifier(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_]", "_", value.strip())
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    if not normalized:
        return "cluster"
    if normalized[0].isdigit():
        normalized = f"r_{normalized}"
    return normalized.lower()


def _policy_name(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9-]", "-", value.strip().lower())
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    if not normalized:
        return "placement"
    if not normalized[0].isalpha():
        normalized = f"p-{normalized}"
    return normalized[:63].rstrip("-")
