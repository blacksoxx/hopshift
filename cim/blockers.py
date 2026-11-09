"""Single source of truth for migration blocker names.

Blocker vocabularies are keyed by source platform. The discovery playbook, the config file and
the code historically used different spellings (`rdm_disk_present` vs `rdm_disk`), so every
spelling is normalized here and blocker_parser, the translators and the risk assessor agree.
"""
from __future__ import annotations

from cim.schema import Architecture, SourcePlatform

# Canonical names. Hard blockers quarantine the VM; soft blockers mark it needs_review.
HARD_BLOCKERS: frozenset[str] = frozenset(
    {"encrypted_vm_present", "rdm_disk", "shared_disk", "vm_template", "unsupported_architecture"}
)
SOFT_BLOCKERS: frozenset[str] = frozenset(
    {"vapp_config", "vtpm_present", "mounted_iso_present", "snapshots_present", "powered_off"}
)
KNOWN_BLOCKERS: frozenset[str] = HARD_BLOCKERS | SOFT_BLOCKERS

__all__ = ["HARD_BLOCKERS", "SOFT_BLOCKERS", "KNOWN_BLOCKERS", "normalize_blocker", "blockers_for_vm", "is_hard"]

_ALIASES: dict[str, str] = {
    "encrypted_vm_present": "encrypted_vm_present",
    "encrypted_vm": "encrypted_vm_present",
    "encrypted": "encrypted_vm_present",
    "rdm_disk": "rdm_disk",
    "rdm_disk_present": "rdm_disk",
    "rdm": "rdm_disk",
    "passthrough_disk": "rdm_disk",
    "raw_device_mapping": "rdm_disk",
    "shared_disk": "shared_disk",
    "shared_disk_present": "shared_disk",
    "shared_disks_present": "shared_disk",
    "vm_template": "vm_template",
    "template": "vm_template",
    "is_template": "vm_template",
    "unsupported_architecture": "unsupported_architecture",
    "architecture_unsupported": "unsupported_architecture",
    "vapp_config": "vapp_config",
    "vapp_config_present": "vapp_config",
    "vtpm_present": "vtpm_present",
    "vtpm": "vtpm_present",
    "mounted_iso_present": "mounted_iso_present",
    "mounted_iso": "mounted_iso_present",
    "snapshots_present": "snapshots_present",
    "snapshot_present": "snapshots_present",
    "powered_off": "powered_off",
}

# VM-level boolean flags emitted by the discovery playbooks and the blocker they imply.
# Platform-specific collectors can extend this table.
FLAG_TO_BLOCKER: dict[SourcePlatform, tuple[tuple[str, str], ...]] = {
    SourcePlatform.VMWARE_VSPHERE: (
        ("is_encrypted", "encrypted_vm_present"),
        ("has_rdm_disks", "rdm_disk"),
        ("has_shared_disks", "shared_disk"),
        ("is_template", "vm_template"),
        ("vapp_config_present", "vapp_config"),
        ("has_vtpm", "vtpm_present"),
        ("mounted_iso_present", "mounted_iso_present"),
    ),
}
_GENERIC_FLAGS: tuple[tuple[str, str], ...] = (
    ("is_encrypted", "encrypted_vm_present"),
    ("has_passthrough_disks", "rdm_disk"),
    ("has_shared_disks", "shared_disk"),
    ("is_template", "vm_template"),
)

_X86_ARCHITECTURES = {"", "x86_64", "amd64", "x64", Architecture.X86_64.value, Architecture.UNKNOWN.value}


def normalize_blocker(value: object) -> str | None:
    """Return the canonical blocker name for any known spelling, else None."""
    key = str(value).strip().lower()
    return _ALIASES.get(key)


def blockers_for_vm(
    vm: dict[str, object],
    platform: SourcePlatform = SourcePlatform.VMWARE_VSPHERE,
) -> list[str]:
    """Canonical, de-duplicated blockers for a discovery VM record (explicit list plus flags)."""
    found: list[str] = []

    def add(blocker: str) -> None:
        if blocker not in found:
            found.append(blocker)

    raw_list = vm.get("migration_blockers", [])
    if isinstance(raw_list, list):
        for item in raw_list:
            canonical = normalize_blocker(item)
            if canonical:
                add(canonical)

    for flag, blocker in FLAG_TO_BLOCKER.get(platform, _GENERIC_FLAGS):
        if bool(vm.get(flag)):
            add(blocker)

    power_state = str(vm.get("power_state") or "").strip().lower()
    if power_state in {"poweredoff", "off", "stopped"}:
        add("powered_off")

    snapshots = vm.get("snapshots")
    snapshot_count = vm.get("snapshot_count")
    if (isinstance(snapshot_count, int) and snapshot_count > 0) or (isinstance(snapshots, list) and snapshots):
        add("snapshots_present")

    architecture = str(vm.get("architecture") or "").strip().lower()
    if architecture not in _X86_ARCHITECTURES:
        add("unsupported_architecture")

    return found


def is_hard(blocker: str) -> bool:
    return blocker in HARD_BLOCKERS
