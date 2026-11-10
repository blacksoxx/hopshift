from __future__ import annotations

import re

from hopshift.cim.schema import CanonicalInfrastructureModel, ComputeUnit
from hopshift.targets.aws.sizing_table import get_instance_type
from hopshift.targets.common import hcl_string, hcl_value, safe_file_stem
from hopshift.targets.common import source_context_comments as _source_context_comments


def render_compute(
    cim: CanonicalInfrastructureModel,
    required_tags: dict[str, str] | None = None,
) -> dict[str, str]:
    """Render one AWS compute HCL file per ComputeUnit.

    Keys are logical paths (aws-migration/compute/<name>.tf); the deterministic assembler
    decides the on-disk layout.
    """
    tags = _build_required_tags(cim, required_tags)

    output: dict[str, str] = {}
    for compute_unit in cim.compute_units:
        path = f"aws-migration/compute/{safe_file_stem(compute_unit.name)}.tf"
        output[path] = _render_compute_unit(compute_unit, tags)

    return output


def _render_compute_unit(compute_unit: ComputeUnit, tags: dict[str, str]) -> str:
    resource_name = _terraform_identifier(compute_unit.name)
    instance_type = get_instance_type(compute_unit.vcpus, compute_unit.ram_mb)
    name_literal = hcl_string(compute_unit.name)

    lines: list[str] = []
    lines.append(f'resource "aws_instance" "{resource_name}" {{')
    lines.extend(_source_context_comments(compute_unit))
    default_image = hcl_string(compute_unit.image_ref) if compute_unit.image_ref else "var.default_ami_id"
    lines.append(f'  # Image: the AMI imported for this VM (var.image_overrides[{name_literal}]) or the fallback.')
    lines.append(f'  ami                    = lookup(var.image_overrides, {name_literal}, {default_image})')
    lines.append(f'  instance_type          = "{instance_type}"')
    lines.append(f'  subnet_id              = aws_subnet.{_subnet_ref(compute_unit)}.id')
    lines.append('  vpc_security_group_ids = [aws_security_group.compute_unit.id]')
    # Secure by default: private addressing only and dedicated EBS bandwidth.
    lines.append('  associate_public_ip_address = false')
    lines.append('  ebs_optimized               = true')

    if compute_unit.cluster_ref:
        lines.append(
            f'  placement_group        = aws_placement_group.{_terraform_identifier(compute_unit.cluster_ref)}.name'
        )

    if compute_unit.has_vtpm:
        lines.append('  # TODO: ComputeUnit has vTPM and needs manual review (NitroTPM requires a UEFI AMI).')

    lines.append('')
    lines.append('  # IMDSv2 only (CIS AWS 5.6): token-backed metadata requests, no forwarding past the instance.')
    lines.append('  metadata_options {')
    lines.append('    http_endpoint               = "enabled"')
    lines.append('    http_tokens                 = "required"')
    lines.append('    http_put_response_hop_limit = 1')
    lines.append('  }')
    lines.append('')
    lines.append('  root_block_device {')
    lines.append('    encrypted = true')
    lines.append('  }')
    lines.append('')
    lines.append('  tags = {')
    lines.append(f'    Name = {name_literal}')
    for key, value in tags.items():
        lines.append(f'    {key} = {hcl_value(value)}')
    lines.append('  }')
    lines.append('}')

    return "\n".join(lines) + "\n"


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
