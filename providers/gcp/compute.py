from __future__ import annotations

import re

from cim.schema import CanonicalInfrastructureModel, ComputeUnit
from providers.common import hcl_string, is_bare_expression, safe_file_stem
from providers.common import source_context_comments as _source_context_comments
from providers.gcp.sizing_table import get_instance_type


def render_compute(
    cim: CanonicalInfrastructureModel,
    required_tags: dict[str, str] | None = None,
) -> dict[str, str]:
    """Render one GCP compute HCL file per ComputeUnit (logical key gcp-migration/compute/<name>.tf)."""
    labels = _build_required_labels(cim, required_tags)

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
    lines.extend(_source_context_comments(compute_unit))
    lines.append(f'  name         = "{_gcp_resource_name(compute_unit.name)}"')
    lines.append('  project      = var.project_id')
    lines.append('  zone         = var.zone')
    lines.append(f'  machine_type = "{machine_type}"')
    lines.append('  can_ip_forward = false')

    if compute_unit.cluster_ref:
        cluster_ref = _terraform_identifier(compute_unit.cluster_ref)
        lines.append(f'  resource_policies = [google_compute_resource_policy.{cluster_ref}.self_link]')

    lines.append('')
    lines.append('  boot_disk {')
    lines.append('    initialize_params {')
    lines.append(f'      # Image: the image migrated for this VM (var.image_overrides[{name_literal}]) or the default family.')
    lines.append(f'      image = lookup(var.image_overrides, {name_literal}, {hcl_string(compute_unit.image_ref) if compute_unit.image_ref else "var.default_image"})')
    lines.append('      size  = 20')
    lines.append('      type  = "pd-balanced"')
    lines.append('    }')
    lines.append('  }')
    lines.append('')
    lines.append('  network_interface {')
    lines.append(f'    subnetwork = google_compute_subnetwork.{subnet_ref}.id')
    lines.append('    # No access_config block: the instance gets no external IP (CIS GCP 4.9).')
    lines.append('  }')
    lines.append('')
    lines.append('  # Shielded VM (CIS GCP 4.8). Imported images must carry the UEFI_COMPATIBLE guest OS feature.')
    lines.append('  shielded_instance_config {')
    lines.append('    enable_secure_boot          = true')
    lines.append('    enable_vtpm                 = true')
    lines.append('    enable_integrity_monitoring = true')
    lines.append('  }')
    lines.append('')
    lines.append('  # Least privilege (CIS GCP 4.1/4.2): a dedicated service account when var.service_account_email is set,')
    lines.append('  # otherwise the default Compute Engine account restricted to logging/monitoring scopes.')
    lines.append('  service_account {')
    lines.append('    email  = var.service_account_email != "" ? var.service_account_email : null')
    lines.append('    scopes = [')
    lines.append('      "https://www.googleapis.com/auth/logging.write",')
    lines.append('      "https://www.googleapis.com/auth/monitoring.write",')
    lines.append('      "https://www.googleapis.com/auth/devstorage.read_only",')
    lines.append('    ]')
    lines.append('  }')
    lines.append('')
    lines.append('  # CIS GCP 4.3 / 4.4 / 4.5: project-wide SSH keys blocked, OS Login on, serial console off.')
    lines.append('  metadata = {')
    lines.append('    enable-oslogin         = "TRUE"')
    lines.append('    block-project-ssh-keys = "TRUE"')
    lines.append('    serial-port-enable     = "FALSE"')
    lines.append('  }')

    if compute_unit.has_vtpm:
        lines.append('')
        lines.append('  # TODO: ComputeUnit has vTPM and needs manual review (Shielded VM is enabled above; confirm the imported image supports UEFI).')

    lines.append('')
    lines.append('  labels = {')
    lines.append(f'    name = "{_label_value(compute_unit.name)}"')
    for key, value in labels.items():
        lines.append(f'    {key} = {_label_expression(value)}')
    lines.append('  }')
    lines.append('}')

    return "\n".join(lines) + "\n"


def _build_required_labels(
    cim: CanonicalInfrastructureModel,
    required_tags: dict[str, str] | None,
) -> dict[str, str]:
    defaults = {
        "environment": "var.environment",
        "owner": "var.owner",
        "migrated_from": cim.migrated_from,
        "source_vcenter": cim.source_vcenter,
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
