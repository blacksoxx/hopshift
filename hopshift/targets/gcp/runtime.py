from __future__ import annotations

from hopshift.cim.schema import CanonicalInfrastructureModel
from hopshift.targets.runtime_common import image_overrides_block, tag_variable_blocks, variable_block
from hopshift.targets.runtime_common import literal_default as _literal

PROVIDER_VERSION = "~> 6.0"


def render_runtime(
    cim: CanonicalInfrastructureModel,
    required_tags: dict[str, str] | None = None,
) -> dict[str, str]:
    """Render providers.tf and variables.tf for the GCP root module."""
    del cim
    tags = required_tags or {}
    providers_tf = "\n".join(
        [
            "terraform {",
            '  required_version = ">= 1.5.0"',
            "  required_providers {",
            "    google = {",
            '      source  = "hashicorp/google"',
            f'      version = "{PROVIDER_VERSION}"',
            "    }",
            "  }",
            "}",
            "",
            'provider "google" {',
            "  project = var.project_id",
            "  region  = var.region",
            "  zone    = var.zone",
            "}",
            "",
        ]
    )
    variables_tf = "\n".join(
        [
            variable_block("project_id", "string", "GCP project that will hold the migrated resources."),
            variable_block("region", "string", "GCP region for subnetworks and placement policies.", "europe-west1"),
            variable_block("zone", "string", "GCP zone for instances and disks; must be in var.region.", "europe-west1-b"),
            variable_block(
                "default_image",
                "string",
                "Fallback boot image used when a VM has no entry in image_overrides.",
                "projects/debian-cloud/global/images/family/debian-12",
            ),
            image_overrides_block(
                "Image self link per VMware VM name, produced by Migrate to Virtual Machines or an image import."
            ),
            variable_block(
                "service_account_email",
                "string",
                "Dedicated service account for the migrated instances (CIS GCP 4.1). Empty uses the default "
                "Compute Engine service account with limited scopes.",
                "",
            ),
            variable_block(
                "default_kms_key_self_link",
                "string",
                "Optional Cloud KMS key for customer-managed disk encryption. Empty uses Google-managed keys.",
                "",
            ),
            tag_variable_blocks(_literal(tags.get("Environment"), "dev"), _literal(tags.get("Owner"), "platform-team")),
        ]
    )
    return {
        "gcp-migration/providers.tf": providers_tf,
        "gcp-migration/variables.tf": variables_tf,
    }
