"""Proxmox VE has no instance types: a KVM guest gets exactly the cores and memory it asks for.

`get_instance_type` keeps the sizing contract every target implements (the sizer node calls it and
the review notes quote it) and returns a descriptive shape label such as `kvm-4c-16g`. The compute
renderer takes cores and memory straight from the ComputeUnit; the label is never used in HCL.
"""
from __future__ import annotations


def get_instance_type(vcpus: int, ram_mb: int) -> str:
    """Return a descriptive KVM shape label (`kvm-<cores>c-<memory>`), pass-through sizing."""
    if vcpus <= 0:
        raise ValueError("vcpus must be > 0")
    if ram_mb <= 0:
        raise ValueError("ram_mb must be > 0")
    return f"kvm-{int(vcpus)}c-{format_memory(ram_mb)}"


def format_memory(ram_mb: int) -> str:
    if ram_mb % 1024 == 0:
        return f"{ram_mb // 1024}g"
    return f"{int(ram_mb)}m"
