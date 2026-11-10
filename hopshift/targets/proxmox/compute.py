from __future__ import annotations

from hopshift.cim.schema import CanonicalInfrastructureModel, ComputeUnit
from hopshift.targets.common import hcl_string, is_bare_expression, safe_file_stem
from hopshift.targets.common import source_context_comments as _source_context_comments
from hopshift.targets.proxmox import (
    RESOURCE_VM,
    ROOT,
    comment_text,
    dns_name,
    guest_family,
    nic_vlan,
    os_type,
    proxmox_tag,
    terraform_identifier,
    vlan_lookup,
)
from hopshift.targets.proxmox.sizing_table import get_instance_type
from hopshift.targets.proxmox.storage import disk_blocks

# Required-tag keys of the other targets mapped onto the Proxmox tag prefixes.
_TAG_PREFIXES = {"environment": "env", "owner": "owner", "migratedfrom": "migratedfrom", "sourcevcenter": "source"}


def render_compute(
    cim: CanonicalInfrastructureModel,
    required_tags: dict[str, str] | None = None,
) -> dict[str, str]:
    """Render one proxmox_virtual_environment_vm per ComputeUnit (logical key proxmox-migration/compute/<name>.tf)."""
    tags = build_tags(cim, required_tags)
    vlans = vlan_lookup(cim)

    output: dict[str, str] = {}
    for compute_unit in cim.compute_units:
        path = f"{ROOT}/compute/{safe_file_stem(compute_unit.name)}.tf"
        output[path] = _render_compute_unit(compute_unit, cim, tags, vlans)
    return output


def build_tags(cim: CanonicalInfrastructureModel, required_tags: dict[str, str] | None) -> list[str]:
    """Proxmox tags as sorted HCL string literals: `env-<environment>`, `owner-<owner>`, `migratedfrom-<source>`,
    `source-<vcenter>` plus any extra required tag as `<key>-<value>`, all lower-case `[a-z0-9_.+-]`.

    Proxmox sorts a VM's tags, so the list is emitted sorted to avoid a permanent plan diff."""
    entries: dict[str, str] = {
        "env": "var.environment",
        "owner": "var.owner",
        "migratedfrom": cim.migrated_from,
        "source": cim.source_vcenter,
    }
    for key, value in (required_tags or {}).items():
        prefix = _TAG_PREFIXES.get(str(key).strip().lower()) or proxmox_tag(key)
        if prefix:
            entries[prefix] = str(value)

    rendered: list[str] = []
    for prefix, value in entries.items():
        text = value.strip()
        if is_bare_expression(text):
            rendered.append(f'"{prefix}-${{{text}}}"')
            continue
        tag_value = proxmox_tag(text)
        rendered.append(f'"{prefix}-{tag_value}"' if tag_value else f'"{prefix}"')
    return sorted(rendered)


def template_source(compute_unit: ComputeUnit) -> tuple[int | None, str | None]:
    """(template VM id, import image id) recorded on the ComputeUnit by the disk migration step.

    A numeric image_ref is the id of a template VM to clone; any other value is a Proxmox import
    image id (`<datastore>:import/<file>`) attached to the boot disk with disk.import_from."""
    reference = (compute_unit.image_ref or "").strip()
    if not reference:
        return None, None
    if reference.isdigit():
        return int(reference), None
    return None, reference


def _render_compute_unit(
    compute_unit: ComputeUnit,
    cim: CanonicalInfrastructureModel,
    tags: list[str],
    vlans: dict[str, int],
) -> str:
    resource_name = terraform_identifier(compute_unit.name)
    vm_name = dns_name(compute_unit.name)
    name_literal = hcl_string(compute_unit.name)
    shape = get_instance_type(compute_unit.vcpus, compute_unit.ram_mb)
    template_id, import_image = template_source(compute_unit)
    uses_efi = compute_unit.firmware == "efi"

    lines: list[str] = []

    if template_id is None and import_image is None:
        lines.append("locals {")
        lines.append(f"  # Template VM to clone for {comment_text(compute_unit.name)}: the per-VM override, else the shared default")
        lines.append("  # (null creates the VM with empty disks for a manual disk import).")
        lines.append(f"  {resource_name}_template_id = lookup(var.image_overrides, {name_literal}, var.default_template_id)")
        lines.append("}")
        lines.append("")

    lines.append(f'resource "{RESOURCE_VM}" "{resource_name}" {{')
    lines.extend(_source_context_comments(compute_unit))
    if vm_name != compute_unit.name:
        lines.append(f"  # Proxmox VM names must be DNS labels; {comment_text(compute_unit.name)} is rendered as {vm_name}.")
    lines.append(f'  name        = "{vm_name}"')
    lines.append(f"  description = {hcl_string(_description(compute_unit, cim))}")
    lines.append("  node_name   = var.proxmox_node")
    lines.append(f"  tags        = [{', '.join(tags)}]")

    lines.append("")
    lines.append(f"  # Sizing is pass-through ({shape}): cores and memory come straight from the source VM.")
    lines.append("  cpu {")
    lines.append(f"    cores   = {int(compute_unit.vcpus)}")
    lines.append("    sockets = 1")
    lines.append('    type    = "x86-64-v2-AES"')
    lines.append("  }")
    lines.append("")
    lines.append("  memory {")
    lines.append(f"    dedicated = {int(compute_unit.ram_mb)}")
    lines.append("  }")

    lines.append("")
    if uses_efi:
        lines.append("  # The source VM boots with EFI: OVMF with a 4m EFI disk and pre-enrolled keys enables Secure Boot")
        lines.append("  # (set pre_enrolled_keys = false if the guest loads unsigned kernel modules).")
        lines.append('  bios = "ovmf"')
        lines.append("")
        lines.append("  efi_disk {")
        lines.append("    datastore_id      = var.datastore_id")
        lines.append('    type              = "4m"')
        lines.append("    pre_enrolled_keys = true")
        lines.append("  }")
    else:
        lines.append("  # The source VM boots with legacy BIOS (SeaBIOS); Secure Boot needs a UEFI-capable guest (bios = \"ovmf\").")
        lines.append('  bios = "seabios"')
    if uses_efi or compute_unit.has_vtpm:
        if compute_unit.has_vtpm:
            lines.append("")
            lines.append("  # The source VM has a vTPM; its secrets do not migrate, re-enrol BitLocker / measured boot after the move.")
        lines.append("")
        lines.append("  tpm_state {")
        lines.append("    datastore_id = var.datastore_id")
        lines.append('    version      = "v2.0"')
        lines.append("  }")

    lines.append("")
    lines.append("  # The QEMU guest agent must run in the guest (install qemu-guest-agent before the cut-over).")
    lines.append("  agent {")
    lines.append("    enabled = true")
    lines.append("  }")
    lines.append("")
    lines.append("  operating_system {")
    lines.append(f'    type = "{os_type(compute_unit)}"')
    lines.append("  }")

    lines.append("")
    if template_id is not None:
        lines.append(f"  # Template: clone var.image_overrides[{name_literal}] when set, otherwise template VM {template_id}")
        lines.append("  # recorded on the ComputeUnit (image_ref) by the disk migration step.")
        lines.append("  clone {")
        lines.append(f"    vm_id = lookup(var.image_overrides, {name_literal}, {template_id})")
        lines.append("    full  = true")
        lines.append("  }")
    elif import_image is not None:
        lines.append(f"  # Boot disk imported from {comment_text(import_image)} (image_ref); no template clone.")
    else:
        lines.append("  # TODO: no template or imported image is known for this VM yet. Set var.image_overrides[<VM name>] or")
        lines.append("  # var.default_template_id to the template VM holding the converted disks; until then the VM is created")
        lines.append("  # stopped with empty disks so the converted VMDKs can be imported (qm importdisk / disk.import_from).")
        lines.append('  dynamic "clone" {')
        lines.append(f"    for_each = local.{resource_name}_template_id == null ? [] : [local.{resource_name}_template_id]")
        lines.append("    content {")
        lines.append("      vm_id = clone.value")
        lines.append("      full  = true")
        lines.append("    }")
        lines.append("  }")
        lines.append("")
        lines.append("  # Stay stopped until a template or an imported disk gives the VM something to boot.")
        lines.append(f"  started = local.{resource_name}_template_id != null")

    lines.append("")
    lines.extend(disk_blocks(compute_unit, import_from=import_image))

    if compute_unit.nics:
        for index, nic in enumerate(compute_unit.nics):
            lines.append("")
            lines.extend(_network_device(index, nic, vlans))
    else:
        lines.append("")
        lines.append("  # The source VM has no network adapter; add a network_device block if the guest needs connectivity.")

    lines.append("}")
    return "\n".join(lines) + "\n"


def _network_device(index: int, nic, vlans: dict[str, int]) -> list[str]:
    segment = comment_text(nic.port_group_ref) or "unknown port group"
    vlan = nic_vlan(nic, vlans)
    lines: list[str] = []
    if vlan is None:
        lines.append(f"  # net{index}: VMware port group {segment} has no single VLAN tag; the NIC is untagged on var.bridge.")
    else:
        lines.append(f"  # net{index}: VMware port group {segment}, VLAN {vlan} (var.bridge must be VLAN-aware).")
    if nic.mac_address:
        lines.append("  # The source MAC address is kept for DHCP reservations and licences; remove it to let Proxmox pick one.")
    lines.append("  network_device {")
    lines.append("    bridge      = var.bridge")
    lines.append("    model       = var.nic_model")
    if vlan is not None:
        lines.append(f"    vlan_id     = {vlan}")
    if nic.mac_address:
        lines.append(f"    mac_address = {hcl_string(nic.mac_address.strip().upper())}")
    lines.append("    firewall    = true")
    lines.append("  }")
    return lines


def _description(compute_unit: ComputeUnit, cim: CanonicalInfrastructureModel) -> str:
    parts = [f"Migrated from {cim.migrated_from} {comment_text(cim.source_vcenter)}: VM {comment_text(compute_unit.name)}"]
    if compute_unit.guest_os:
        parts.append(f"guest OS {comment_text(compute_unit.guest_os)} ({guest_family(compute_unit)})")
    if compute_unit.cluster_ref:
        parts.append(f"cluster {comment_text(compute_unit.cluster_ref)}")
    if compute_unit.annotation:
        parts.append(f"note: {comment_text(compute_unit.annotation)[:200]}")
    return "; ".join(parts) + ". Managed by hopshift."
