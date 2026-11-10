"""Disks for the Proxmox VE target.

bpg/proxmox models disks as `disk {}` blocks inside `proxmox_virtual_environment_vm`; there is no
standalone disk resource to create and attach afterwards. `disk_blocks()` therefore renders the
blocks the compute renderer embeds in the VM resource (boot disk on scsi0, further volumes on
scsi1, scsi2, ...), and `render_storage()` writes the per-VM inventory file that records where each
disk came from and what still needs attention (shared disks, RDM / pass-through disks, import).
"""
from __future__ import annotations

from hopshift.cim.schema import CanonicalInfrastructureModel, ComputeUnit, StorageVolume
from hopshift.targets.common import hcl_string, safe_file_stem
from hopshift.targets.proxmox import ROOT, comment_text


def render_storage(
    cim: CanonicalInfrastructureModel,
    required_tags: dict[str, str] | None = None,
) -> dict[str, str]:
    """Render one disk inventory file per ComputeUnit (logical key proxmox-migration/storage/<name>_disks.tf)."""
    del required_tags  # disks carry no tags on Proxmox; the VM resource holds the ownership tags
    output: dict[str, str] = {}
    for compute_unit in cim.compute_units:
        path = f"{ROOT}/storage/{safe_file_stem(compute_unit.name)}_disks.tf"
        output[path] = _render_inventory(compute_unit, cim)
    return output


def ordered_volumes(compute_unit: ComputeUnit) -> list[StorageVolume]:
    """Volumes in bus order: the lowest unit number is the boot disk (unknown unit numbers go last)."""
    return sorted(
        compute_unit.storage_volumes,
        key=lambda volume: (volume.unit_number if volume.unit_number is not None else 10_000, volume.id),
    )


def disk_interface(index: int) -> str:
    return f"scsi{index}"


def disk_blocks(compute_unit: ComputeUnit, import_from: str | None = None) -> list[str]:
    """HCL lines (indented for the VM resource body) declaring every disk of the ComputeUnit.

    `import_from` is the Proxmox import image id (`<datastore>:import/<file>`) for the boot disk
    when the converted source disk has already been uploaded; the other disks are created empty.
    """
    volumes = ordered_volumes(compute_unit)
    if not volumes:
        return [
            "  # The source VM reports no disks. A clone inherits the template's disks; otherwise add a disk block",
            "  # before the first boot.",
        ]

    lines: list[str] = []
    for index, volume in enumerate(volumes):
        interface = disk_interface(index)
        role = "Boot disk" if index == 0 else "Data disk"
        provisioning = "thin" if volume.thin_provisioned else "thick"
        source = comment_text(volume.id) or "unknown source"
        datastore = comment_text(volume.datastore or "") or "unknown datastore"
        if index:
            lines.append("")
        lines.append(f"  # {role} {interface}: source {source} ({int(volume.size_gb)} GB, {provisioning}, datastore {datastore}).")
        if volume.is_shared:
            lines.append("  # TODO: the source disk is shared between VMs; Proxmox needs shared storage and manual review.")
        if volume.is_rdm:
            lines.append("  # TODO: the source disk is an RDM / pass-through device; map the LUN on the node manually.")
        lines.append("  disk {")
        lines.append(f'    interface    = "{interface}"')
        lines.append("    datastore_id = var.datastore_id")
        lines.append(f"    size         = {int(volume.size_gb)}")
        if index == 0 and import_from:
            lines.append(f"    import_from  = {hcl_string(import_from)}")
        lines.append("    iothread     = true")
        lines.append('    discard      = "on"')
        lines.append("  }")
    return lines


def _render_inventory(compute_unit: ComputeUnit, cim: CanonicalInfrastructureModel) -> str:
    name = comment_text(compute_unit.name)
    stem = safe_file_stem(compute_unit.name)
    lines = [
        f"# Disks of {name} (migrated from {cim.migrated_from} {comment_text(cim.source_vcenter)}).",
        "#",
        "# bpg/proxmox declares disks inside the VM resource, so the disk blocks live in",
        f"# compute_{stem}.tf. Every disk lands on var.datastore_id; the source datastore is kept here for",
        "# the import step.",
        "#",
    ]
    volumes = ordered_volumes(compute_unit)
    if not volumes:
        lines.append("#   (no disks reported by discovery)")
    for index, volume in enumerate(volumes):
        flags = []
        if volume.thin_provisioned:
            flags.append("thin")
        if volume.is_shared:
            flags.append("SHARED: manual review")
        if volume.is_rdm:
            flags.append("RDM: manual review")
        suffix = f" [{', '.join(flags)}]" if flags else ""
        lines.append(
            f"#   {disk_interface(index):<6} {int(volume.size_gb):>6} GB  {comment_text(volume.id)}"
            f"  (datastore {comment_text(volume.datastore or '') or 'unknown'}){suffix}"
        )
    lines.extend(
        [
            "#",
            "# Import: convert each VMDK (qemu-img convert -O qcow2|raw), upload it to a datastore with the",
            "# `import` content type and either set image_ref / var.image_overrides to a template VM that already",
            "# carries the converted disks, or attach the image with disk.import_from before the first boot.",
        ]
    )
    return "\n".join(lines) + "\n"
