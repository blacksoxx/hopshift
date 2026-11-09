"""Terraform deployments for a run: plan, apply and destroy with approval gates.

`build_deploy_service(platform)` is called by `vma.platform.Platform.from_config` when this
package is importable; importing the package registers the `deployments` table migration.
See docs/deployments.md.
"""
from __future__ import annotations

from typing import Any

from vma.deploy import store as _store  # noqa: F401 - registers the deployments migration
from vma.deploy.service import ConnectionContext, DeployService
from vma.deploy.store import ACTIONS, ACTIVE_STATUSES, TERMINAL_STATUSES, Deployment
from vma.deploy.terraform import TerraformRunner


def build_deploy_service(platform: Any) -> DeployService:
    return DeployService(platform)


__all__ = [
    "ACTIONS",
    "ACTIVE_STATUSES",
    "TERMINAL_STATUSES",
    "ConnectionContext",
    "DeployService",
    "Deployment",
    "TerraformRunner",
    "build_deploy_service",
]
