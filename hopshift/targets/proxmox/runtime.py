from __future__ import annotations

from hopshift.cim.schema import CanonicalInfrastructureModel
from hopshift.targets.common import hcl_string
from hopshift.targets.proxmox import ROOT, proxmox_tag
from hopshift.targets.runtime_common import literal_default, variable_block

# bpg/proxmox: the proxmox_virtual_environment_* resource names stay until 1.0 (short aliases exist from 0.100).
PROVIDER_VERSION = "~> 0.121"

_TAG_PATTERN = "^[a-z0-9_.+-]+$"
_MANAGEMENT_CIDRS: tuple[str, ...] = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
_NIC_MODELS: tuple[str, ...] = ("virtio", "vmxnet3", "e1000", "e1000e", "rtl8139")


def render_runtime(
    cim: CanonicalInfrastructureModel,
    required_tags: dict[str, str] | None = None,
) -> dict[str, str]:
    """Render targets.tf (provider) and variables.tf for the Proxmox root module."""
    del cim
    tags = required_tags or {}
    providers_tf = "\n".join(
        [
            "terraform {",
            '  required_version = ">= 1.5.0"',
            "  required_providers {",
            "    proxmox = {",
            '      source  = "bpg/proxmox"',
            f'      version = "{PROVIDER_VERSION}"',
            "    }",
            "  }",
            "}",
            "",
            "# Credentials never live in this module. The stored connection exports PROXMOX_VE_API_TOKEN",
            "# (user@realm!token=secret) or PROXMOX_VE_USERNAME / PROXMOX_VE_PASSWORD, plus PROXMOX_VE_ENDPOINT and",
            "# PROXMOX_VE_INSECURE, which the provider reads when the two variables below stay null.",
            'provider "proxmox" {',
            "  endpoint = var.proxmox_endpoint",
            "  insecure = var.proxmox_insecure",
            "}",
            "",
        ]
    )
    variables_tf = "\n".join(
        [
            _nullable_variable(
                "proxmox_endpoint",
                "string",
                "Proxmox VE API endpoint (https://pve.example.internal:8006/); null reads PROXMOX_VE_ENDPOINT.",
            ),
            _nullable_variable(
                "proxmox_insecure",
                "bool",
                "Skip TLS verification of the API endpoint; null reads PROXMOX_VE_INSECURE.",
            ),
            variable_block("proxmox_node", "string", "Proxmox node that hosts the migrated VMs (and the HA node when ha_nodes is empty).", "pve"),
            variable_block(
                "datastore_id",
                "string",
                "Datastore for VM disks, EFI disks and TPM state. Proxmox has no per-disk encryption flag: use a LUKS- or ZFS-encrypted datastore.",
                "local-lvm",
            ),
            variable_block("bridge", "string", "Linux bridge the VM NICs attach to; must be VLAN-aware when segments carry VLAN tags.", "vmbr0"),
            _nic_model_variable(),
            variable_block(
                "image_overrides",
                "map(number)",
                "Template VM id to clone per source VM name (the VMware VM name is the key).",
                {},
            ),
            _nullable_variable(
                "default_template_id",
                "number",
                "Template VM cloned for VMs without an image_overrides entry; null creates them with empty disks.",
            ),
            _management_cidrs_variable(),
            variable_block("ha_nodes", "list(string)", "Nodes of the HA groups; empty means proxmox_node only.", list(())),
            variable_block(
                "ha_rules_enabled",
                "bool",
                "Create Proxmox VE 9 HA affinity rules (proxmox_virtual_environment_harule) for clusters with affinity semantics.",
                False,
            ),
            _tag_variable("environment", "Environment tag (env-<value>) applied to every VM.", _tag_default(tags.get("Environment"), "dev")),
            _tag_variable("owner", "Owner tag (owner-<value>) applied to every VM.", _tag_default(tags.get("Owner"), "platform-team")),
        ]
    )
    return {
        f"{ROOT}/targets.tf": providers_tf,
        f"{ROOT}/variables.tf": variables_tf,
    }


def _nullable_variable(name: str, type_: str, description: str) -> str:
    return "\n".join(
        [
            f'variable "{name}" {{',
            f"  type        = {type_}",
            f"  description = {hcl_string(description)}",
            "  default     = null",
            "}",
        ]
    ) + "\n"


def _nic_model_variable() -> str:
    options = ", ".join(f'"{model}"' for model in _NIC_MODELS)
    return "\n".join(
        [
            'variable "nic_model" {',
            "  type        = string",
            f"  description = {hcl_string('NIC model for every VM: virtio (needs VirtIO drivers in the guest) or vmxnet3 for the first boot of a VMware guest.')}",
            '  default     = "virtio"',
            "",
            "  validation {",
            f"    condition     = contains([{options}], var.nic_model)",
            f'    error_message = "nic_model must be one of {", ".join(_NIC_MODELS)}."',
            "  }",
            "}",
        ]
    ) + "\n"


def _management_cidrs_variable() -> str:
    default = ", ".join(f'"{cidr}"' for cidr in _MANAGEMENT_CIDRS)
    return "\n".join(
        [
            'variable "management_cidrs" {',
            "  type        = list(string)",
            f"  description = {hcl_string('Source ranges allowed to reach SSH/RDP and ICMP on the VMs (RFC 1918 by default); 0.0.0.0/0 and ::/0 are rejected.')}",
            f"  default     = [{default}]",
            "",
            "  validation {",
            '    condition     = length(var.management_cidrs) > 0 && !contains(var.management_cidrs, "0.0.0.0/0") && !contains(var.management_cidrs, "::/0")',
            '    error_message = "management_cidrs must list at least one range and must not contain 0.0.0.0/0 or ::/0."',
            "  }",
            "}",
        ]
    ) + "\n"


def _tag_variable(name: str, description: str, default: str) -> str:
    return "\n".join(
        [
            f'variable "{name}" {{',
            "  type        = string",
            f"  description = {hcl_string(description)}",
            f"  default     = {hcl_string(default)}",
            "",
            "  validation {",
            f'    condition     = can(regex("{_TAG_PATTERN}", var.{name}))',
            f'    error_message = "{name} becomes a Proxmox tag and must be lower-case [a-z0-9_.+-]."',
            "  }",
            "}",
        ]
    ) + "\n"


def _tag_default(value: object | None, fallback: str) -> str:
    """Tag variable default: the CLI value as a Proxmox tag component, or the fallback."""
    return proxmox_tag(literal_default(value, fallback)) or fallback
