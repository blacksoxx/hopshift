from __future__ import annotations

from cim.schema import CanonicalInfrastructureModel
from providers.runtime_common import image_overrides_block, tag_variable_blocks, variable_block
from providers.runtime_common import literal_default as _literal

PROVIDER_VERSION = "~> 6.0"


def render_runtime(
    cim: CanonicalInfrastructureModel,
    required_tags: dict[str, str] | None = None,
) -> dict[str, str]:
    """Render providers.tf and variables.tf for the AWS root module."""
    del cim
    tags = required_tags or {}
    providers_tf = "\n".join(
        [
            "terraform {",
            '  required_version = ">= 1.5.0"',
            "  required_providers {",
            "    aws = {",
            '      source  = "hashicorp/aws"',
            f'      version = "{PROVIDER_VERSION}"',
            "    }",
            "  }",
            "}",
            "",
            'provider "aws" {',
            "  region = var.aws_region",
            "}",
            "",
        ]
    )
    variables_tf = "\n".join(
        [
            variable_block("aws_region", "string", "AWS region for all migrated resources.", "us-east-1"),
            variable_block(
                "default_availability_zone",
                "string",
                "Availability Zone for EBS volumes; must be in var.aws_region.",
                "us-east-1a",
            ),
            variable_block(
                "default_ami_id",
                "string",
                "Fallback AMI used when a VM has no entry in image_overrides. Leave empty to force per-VM images.",
                "",
            ),
            image_overrides_block(
                "AMI id per VMware VM name, produced by AWS VM Import/Export from the migrated VMDKs."
            ),
            tag_variable_blocks(_literal(tags.get("Environment"), "dev"), _literal(tags.get("Owner"), "platform-team")),
        ]
    )
    return {
        "aws-migration/providers.tf": providers_tf,
        "aws-migration/variables.tf": variables_tf,
    }
