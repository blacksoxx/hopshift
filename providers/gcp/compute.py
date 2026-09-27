from __future__ import annotations

import re

from cim.schema import CanonicalInfrastructureModel, ComputeUnit
from providers.common import hcl_string, is_bare_expression, safe_file_stem
from providers.gcp.sizing_table import get_instance_type


def render_compute(
    cim: CanonicalInfrastructureModel,
    required_tags: dict[str, str] | None = None,
) -> dict[str, str]:
    """Render one GCP compute HCL file per ComputeUnit (logical key gcp-migration/compute/<name>.tf)."""
    labels = _build_required_labels(cim.source_vcenter, required_tags)

    output: dict[str, str] = {}
    for compute_unit in cim.compute_units:
        path = f"gcp-migration/compute/{safe_file_stem(compute_unit.name)}.tf"
        output[path] = _render_compute_unit(compute_unit, labels)

    return output


def _render_compute_unit(compute_unit: ComputeUnit, labels: dict[str, str]) -> str:
    resource_name = _terraform_identifier(compute_unit.name)
    machine_type = get_instance_type(compute_unit.vcpus, compute_unit.ram_mb)
    subnet_ref = _subnet_ref(compute_unit)
    name_literal = hcl_string(compute_unit.name)

    lines: list[str] = []
    lines.append(f'resource "google_compute_instance" "{resource_name}" {{')
    lines.append(f'  name         = "{_gcp_resource_name(compute_unit.name)}"')
    lines.append('  project      = var.project_id')
    lines.append('  zone         = var.zone')
    lines.append(f'  machine_type = "{machine_type}"')

    if compute_unit.cluster_ref:
        cluster_ref = _terraform_identifier(compute_unit.cluster_ref)
        lines.append(f'  resource_policies = [google_compute_resource_policy.{cluster_ref}.self_link]')

    lines.append('')
    lines.append('  boot_disk {')
    lines.append('    initialize_params {')
    lines.append(f'      # Image: the image migrated for this VM (var.image_overrides[{name_literal}]) or the default family.')
    lines.append(f'      image = lookup(var.image_overrides, {name_literal}, var.default_image)')
    lines.append('      size  = 20')
    lines.append('      type  = "pd-balanced"')
    lines.append('    }')
    lines.append('  }')
    lines.append('')
    lines.append('  network_interface {')
    lines.append(f'    subnetwork = google_compute_subnetwork.{subnet_ref}.id')
    lines.append('  }')

    if compute_unit.has_vtpm:
        lines.append('')
        lines.append('  # TODO: ComputeUnit has vTPM and needs manual review (shielded_instance_config requires a Shielded VM image).')

    lines.append('')
    lines.append('  labels = {')
    lines.append(f'    name = "{_label_value(compute_unit.name)}"')
    for key, value in labels.items():
        lines.append(f'    {key} = {_label_expression(value)}')
    lines.append('  }')
    lines.append('}')

    return "\n".join(lines) + "\n"


def _build_required_labels(
    source_vcenter: str,
    required_tags: dict[str, str] | None,
) -> dict[str, str]:
    defaults = {
        "environment": "var.environment",
        "owner": "var.owner",
        "migrated_from": "vmware-vcenter",
        "source_vcenter": source_vcenter,
    }

    if not required_tags:
        return defaults

    merged = dict(defaults)
    for key, value in required_tags.items():
        normalized_key = _label_key(str(key))
        merged[normalized_key] = str(value)

    return merged


def _label_expression(value: str) -> str:
    """Bare var./local. references stay bare; literals are lowercased into valid GCP label values."""
    if is_bare_expression(value):
        return str(value).strip()
    return f'"{_label_value(value)}"'


def _subnet_ref(compute_unit: ComputeUnit) -> str:
    if compute_unit.nics:
        return _terraform_identifier(compute_unit.nics[0].port_group_ref)
    return "default"


def _terraform_identifier(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_]", "_", value.strip())
    normalized = re.sub(r"_+", "_", normalized).strip("_")

    if not normalized:
        return "resource"
    if normalized[0].isdigit():
        normalized = f"r_{normalized}"

    return normalized.lower()


def _gcp_resource_name(value: str) -> str:
    # GCP instance names must match [a-z]([-a-z0-9]*[a-z0-9])? and be at most 63 chars.
    normalized = re.sub(r"[^a-z0-9-]", "-", value.strip().lower())
    normalized = re.sub(r"-+", "-", normalized).strip("-")

    if not normalized:
        return "instance"
    if not normalized[0].isalpha():
        normalized = f"vm-{normalized}"

    return normalized[:63].rstrip("-")


def _label_key(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_-]", "_", value.strip().lower())
    normalized = re.sub(r"_+", "_", normalized).strip("_")

    if not normalized:
        return "label"
    if normalized[0].isdigit():
        normalized = f"k_{normalized}"

    if len(normalized) > 63:
        return normalized[:63]

    return normalized


def _label_value(value: str) -> str:
    # GCP label values: lowercase letters, digits, underscore, dash; max 63 chars.
    normalized = re.sub(r"[^a-z0-9_-]", "_", str(value).strip().lower())
    if len(normalized) > 63:
        return normalized[:63]
    return normalized
