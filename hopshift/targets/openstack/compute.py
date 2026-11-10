from __future__ import annotations

import re

from hopshift.cim.schema import CanonicalInfrastructureModel, ComputeUnit
from hopshift.targets.common import hcl_string, hcl_value, safe_file_stem
from hopshift.targets.common import source_context_comments as _source_context_comments
from hopshift.targets.openstack.sizing_table import get_instance_type


def render_compute(
    cim: CanonicalInfrastructureModel,
    required_tags: dict[str, str] | None = None,
) -> dict[str, str]:
    """Render one OpenStack compute HCL file per ComputeUnit (logical key openstack-migration/compute/<name>.tf)."""
    metadata = _build_required_metadata(cim, required_tags)
    port_group_to_network_ref, default_network_ref = _build_network_ref_lookup(cim)

    output: dict[str, str] = {}
    for compute_unit in cim.compute_units:
        path = f"openstack-migration/compute/{safe_file_stem(compute_unit.name)}.tf"
        network_ref = _network_ref(
            compute_unit,
            port_group_to_network_ref=port_group_to_network_ref,
            default_network_ref=default_network_ref,
        )
        output[path] = _render_compute_unit(compute_unit, metadata, network_ref=network_ref)

    return output


def _render_compute_unit(
    compute_unit: ComputeUnit,
    metadata: dict[str, str],
    network_ref: str,
) -> str:
    resource_name = _terraform_identifier(compute_unit.name)
    flavor_name = get_instance_type(compute_unit.vcpus, compute_unit.ram_mb)
    name_literal = hcl_string(compute_unit.name)

    lines: list[str] = []
    lines.append(f'resource "openstack_compute_instance_v2" "{resource_name}" {{')
    lines.extend(_source_context_comments(compute_unit))
    lines.append(f'  name            = {name_literal}')
    lines.append(f'  flavor_name     = "{flavor_name}"')
    lines.append(f'  # Image: the Glance image migrated for this VM (var.image_overrides[{name_literal}]) or the default.')
    lines.append(f'  image_name      = lookup(var.image_overrides, {name_literal}, {hcl_string(compute_unit.image_ref) if compute_unit.image_ref else "var.default_image_name"})')
    lines.append('  key_pair        = var.key_pair_name')
    lines.append('  security_groups = [openstack_networking_secgroup_v2.compute_unit.name]')
    lines.append('')
    lines.append('  network {')
    lines.append(f'    name = openstack_networking_network_v2.{network_ref}.name')
    lines.append('  }')

    if compute_unit.cluster_ref:
        cluster_ref = _terraform_identifier(compute_unit.cluster_ref)
        lines.append('')
        lines.append('  scheduler_hints {')
        lines.append(f'    group = openstack_compute_servergroup_v2.{cluster_ref}.id')
        lines.append('  }')

    if compute_unit.has_vtpm:
        lines.append('')
        lines.append('  # TODO: ComputeUnit has vTPM and needs manual review (requires a flavor/image with vTPM traits).')

    lines.append('')
    lines.append('  metadata = {')
    lines.append(f'    Name = {name_literal}')
    for key, value in metadata.items():
        lines.append(f'    {key} = {hcl_value(value)}')
    lines.append('  }')
    lines.append('}')

    return "\n".join(lines) + "\n"


def _build_required_metadata(
    cim: CanonicalInfrastructureModel,
    required_tags: dict[str, str] | None,
) -> dict[str, str]:
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


def _build_network_ref_lookup(
    cim: CanonicalInfrastructureModel,
) -> tuple[dict[str, str], str]:
    lookup: dict[str, str] = {}
    default_ref = "default_dvs"

    switches = list(cim.network_topology.distributed_switches)
    if not switches:
        return lookup, default_ref

    default_ref = _terraform_identifier(switches[0].name)

    for switch in switches:
        switch_ref = _terraform_identifier(switch.name)
        lookup[switch.name.strip().lower()] = switch_ref
        lookup[_terraform_identifier(switch.name)] = switch_ref

        for port_group in switch.port_groups:
            lookup[port_group.name.strip().lower()] = switch_ref
            lookup[_terraform_identifier(port_group.name)] = switch_ref

    return lookup, default_ref


def _network_ref(
    compute_unit: ComputeUnit,
    port_group_to_network_ref: dict[str, str],
    default_network_ref: str,
) -> str:
    for nic in compute_unit.nics:
        raw = nic.port_group_ref.strip()
        if not raw:
            continue

        by_name = port_group_to_network_ref.get(raw.lower())
        if by_name:
            return by_name

        by_identifier = port_group_to_network_ref.get(_terraform_identifier(raw))
        if by_identifier:
            return by_identifier

    return default_network_ref


def _terraform_identifier(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_]", "_", value.strip())
    normalized = re.sub(r"_+", "_", normalized).strip("_")

    if not normalized:
        return "resource"
    if normalized[0].isdigit():
        normalized = f"r_{normalized}"

    return normalized.lower()
