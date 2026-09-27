"""Single source of truth for migration blocker names.

The discovery playbook, the config file, and the code historically used different spellings
(`rdm_disk_present` vs `rdm_disk`). Everything is normalized here so blocker_parser, the
translator, and the risk assessor agree.
"""
from __future__ import annotations

# Canonical names. Hard blockers quarantine the VM; soft blockers mark it needs_review.
HARD_BLOCKERS: frozenset[str] = frozenset({"encrypted_vm_present", "rdm_disk", "shared_disk"})
SOFT_BLOCKERS: frozenset[str] = frozenset({"vapp_config", "vtpm_present", "mounted_iso_present", "snapshots_present"})
KNOWN_BLOCKERS: frozenset[str] = HARD_BLOCKERS | SOFT_BLOCKERS

_ALIASES: dict[str, str] = {
    "encrypted_vm_present": "encrypted_vm_present",
    "encrypted_vm": "encrypted_vm_present",
    "encrypted": "encrypted_vm_present",
    "rdm_disk": "rdm_disk",
    "rdm_disk_present": "rdm_disk",
    "rdm": "rdm_disk",
    "shared_disk": "shared_disk",
    "shared_disk_present": "shared_disk",
    "shared_disks_present": "shared_disk",
    "vapp_config": "vapp_config",
    "vapp_config_present": "vapp_config",
    "vtpm_present": "vtpm_present",
    "vtpm": "vtpm_present",
    "mounted_iso_present": "mounted_iso_present",
    "mounted_iso": "mounted_iso_present",
    "snapshots_present": "snapshots_present",
    "snapshot_present": "snapshots_present",
}

# VM-level boolean flags emitted by the discovery playbook and the blocker they imply.
FLAG_TO_BLOCKER: tuple[tuple[str, str], ...] = (
    ("is_encrypted", "encrypted_vm_present"),
    ("has_rdm_disks", "rdm_disk"),
    ("has_shared_disks", "shared_disk"),
    ("vapp_config_present", "vapp_config"),
    ("has_vtpm", "vtpm_present"),
    ("mounted_iso_present", "mounted_iso_present"),
)


def normalize_blocker(value: object) -> str | None:
    """Return the canonical blocker name for any known spelling, else None."""
    key = str(value).strip().lower()
    return _ALIASES.get(key)


def blockers_for_vm(vm: dict[str, object]) -> list[str]:
    """Canonical, de-duplicated blockers for a discovery VM record (explicit list plus flags)."""
    found: list[str] = []

    raw_list = vm.get("migration_blockers", [])
    if isinstance(raw_list, list):
        for item in raw_list:
            canonical = normalize_blocker(item)
            if canonical and canonical not in found:
                found.append(canonical)

    for flag, blocker in FLAG_TO_BLOCKER:
        if bool(vm.get(flag)) and blocker not in found:
            found.append(blocker)

    return found
