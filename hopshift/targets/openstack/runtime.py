from __future__ import annotations

from hopshift.cim.schema import CanonicalInfrastructureModel
from hopshift.targets.runtime_common import image_overrides_block, tag_variable_blocks, variable_block
from hopshift.targets.runtime_common import literal_default as _literal

PROVIDER_VERSION = "~> 2.1"


def render_runtime(
    cim: CanonicalInfrastructureModel,
    required_tags: dict[str, str] | None = None,
) -> dict[str, str]:
    """Render targets.tf and variables.tf for the OpenStack root module."""
    del cim
    tags = required_tags or {}
    providers_tf = "\n".join(
        [
            "terraform {",
            '  required_version = ">= 1.5.0"',
            "  required_providers {",
            "    openstack = {",
            '      source  = "terraform-provider-openstack/openstack"',
            f'      version = "{PROVIDER_VERSION}"',
            "    }",
            "  }",
            "}",
            "",
            'provider "openstack" {',
            "  auth_url    = var.auth_url",
            "  user_name   = var.user_name",
            "  password    = var.password",
            "  tenant_name = var.tenant_name",
            "  domain_name = var.domain_name",
            "  region      = var.region",
            "}",
            "",
        ]
    )
    variables_tf = "\n".join(
        [
            variable_block("auth_url", "string", "Keystone identity endpoint (v3)."),
            variable_block("user_name", "string", "OpenStack user name."),
            variable_block("password", "string", "OpenStack password; pass via TF_VAR_password.", sensitive=True),
            variable_block("tenant_name", "string", "OpenStack project (tenant) name."),
            variable_block("domain_name", "string", "Keystone domain name.", "Default"),
            variable_block("region", "string", "OpenStack region name."),
            variable_block("external_network_id", "string", "External (provider) network id for routers."),
            variable_block(
                "default_image_name",
                "string",
                "Fallback Glance image used when a VM has no entry in image_overrides.",
                "",
            ),
            image_overrides_block("Glance image name per VMware VM name, produced by converting the migrated VMDKs."),
            variable_block("key_pair_name", "string", "Nova key pair injected into instances.", ""),
            variable_block(
                "encrypted_volume_type",
                "string",
                "Cinder volume type backed by an encryption provider.",
                "encrypted",
            ),
            tag_variable_blocks(_literal(tags.get("Environment"), "dev"), _literal(tags.get("Owner"), "platform-team")),
        ]
    )
    return {
        "openstack-migration/targets.tf": providers_tf,
        "openstack-migration/variables.tf": variables_tf,
    }
