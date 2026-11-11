from __future__ import annotations

import json
from pathlib import Path

from hopshift.sources import translate
from hopshift.targets.openstack import runtime

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "discovery_multi_vm.json"
CREDENTIAL_VARIABLES = ("auth_url", "user_name", "password", "tenant_name", "domain_name", "region")


def _rendered() -> dict[str, str]:
    cim = translate(json.loads(FIXTURE.read_text(encoding="utf-8")), "openstack")
    return runtime.render_runtime(cim, {"Environment": "prod", "Owner": "platform"})


def test_provider_credentials_default_to_null_so_the_connection_environment_applies() -> None:
    files = _rendered()
    variables = files["openstack-migration/variables.tf"]
    for name in CREDENTIAL_VARIABLES:
        block = variables.split(f'variable "{name}" {{', 1)[1].split("}", 1)[0]
        assert "default     = null" in block, name
    assert "sensitive   = true" in variables.split('variable "password" {', 1)[1].split("}", 1)[0]
    assert "default     = null" not in variables.split('variable "external_network_id" {', 1)[1].split("}", 1)[0]


def test_provider_block_binds_every_credential_variable() -> None:
    providers = _rendered()["openstack-migration/providers.tf"]
    assert 'provider "openstack" {' in providers
    for name in CREDENTIAL_VARIABLES:
        assert f"var.{name}" in providers, name
    assert "OS_* environment" in providers
