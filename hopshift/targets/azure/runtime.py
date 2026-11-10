from __future__ import annotations

from hopshift.cim.schema import CanonicalInfrastructureModel
from hopshift.targets.runtime_common import image_overrides_block, tag_variable_blocks, variable_block
from hopshift.targets.runtime_common import literal_default as _literal

PROVIDER_VERSION = "~> 4.0"


def render_runtime(
    cim: CanonicalInfrastructureModel,
    required_tags: dict[str, str] | None = None,
) -> dict[str, str]:
    """Render targets.tf and variables.tf for the Azure root module."""
    del cim
    tags = required_tags or {}
    providers_tf = "\n".join(
        [
            "terraform {",
            '  required_version = ">= 1.5.0"',
            "  required_providers {",
            "    azurerm = {",
            '      source  = "hashicorp/azurerm"',
            f'      version = "{PROVIDER_VERSION}"',
            "    }",
            "  }",
            "}",
            "",
            'provider "azurerm" {',
            "  features {}",
            "}",
            "",
        ]
    )
    variables_tf = "\n".join(
        [
            variable_block("location", "string", "Azure region for all migrated resources.", "westeurope"),
            variable_block(
                "resource_group_name",
                "string",
                "Existing resource group that will hold the migrated resources.",
            ),
            variable_block("name_prefix", "string", "Prefix applied to Azure resource names.", "migr"),
            variable_block("admin_username", "string", "Admin user created on each Linux VM.", "azureuser"),
            variable_block("admin_public_key", "string", "SSH public key for the admin user."),
            image_overrides_block(
                "Managed image or gallery image id per VMware VM name (Azure Migrate / imported VHD). "
                "VMs without an entry use the marketplace reference in their compute file."
            ),
            tag_variable_blocks(_literal(tags.get("Environment"), "dev"), _literal(tags.get("Owner"), "platform-team")),
        ]
    )
    return {
        "azure-migration/targets.tf": providers_tf,
        "azure-migration/variables.tf": variables_tf,
    }
