"""Compliance controls (validation/policies/compliance) evaluated with the real opa binary.

Each test builds a small hcl_output mapping, runs it through hopshift.validation.opa_client.evaluate_policies
and asserts on the violations / denies per control id. Skipped when opa is not installed.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from hopshift.services.compliance.controls import CONTROLS, CONTROLS_BY_ID
from hopshift.validation.opa_client import OPAEvaluationResult, evaluate_policies

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICIES_DIR = REPO_ROOT / "hopshift" / "validation" / "policies"


def _opa_bin() -> str | None:
    found = shutil.which("opa")
    if found:
        return found
    sibling = Path(sys.executable).parent / "opa"
    return str(sibling) if sibling.exists() else None


OPA_BIN = _opa_bin()

pytestmark = pytest.mark.skipif(OPA_BIN is None, reason="opa binary not installed")


def _evaluate(files: dict[str, str]) -> OPAEvaluationResult:
    assert OPA_BIN is not None
    return evaluate_policies(hcl_output=files, policies_dir=POLICIES_DIR, opa_bin=OPA_BIN)


def _controls(result: OPAEvaluationResult, level: str | None = None) -> set[str]:
    return {str(v["control"]) for v in result.violations if level is None or v["level"] == level}


def _messages(result: OPAEvaluationResult, control: str) -> list[str]:
    return [str(v["message"]) for v in result.violations if v["control"] == control]


TAGS = """
  tags = {
    Name          = "x"
    Environment   = var.environment
    Owner         = var.owner
    MigratedFrom  = "vmware-vcenter"
  }
"""

LABELS = """
  labels = {
    environment   = var.environment
    owner         = var.owner
    migrated_from = "vmware-vcenter"
  }
"""

# ── AWS ───────────────────────────────────────────────────────────────────────

AWS_HARDENED = {
    "aws-migration/providers.tf": """
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}
provider "aws" {
  region = "us-east-1"
}
""",
    "aws-migration/network.tf": f"""
resource "aws_vpc" "main" {{
  cidr_block = "10.10.0.0/16"
{TAGS}
}}

resource "aws_default_security_group" "main" {{
  vpc_id = aws_vpc.main.id
{TAGS}
}}

resource "aws_security_group" "compute_unit" {{
  vpc_id = aws_vpc.main.id
  ingress {{
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/8"]
  }}
{TAGS}
}}
""",
    "aws-migration/compute.tf": f"""
resource "aws_instance" "web" {{
  ami                         = "ami-123"
  instance_type               = "t3.medium"
  associate_public_ip_address = false
  ebs_optimized               = true
  metadata_options {{
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }}
  root_block_device {{
    encrypted = true
  }}
{TAGS}
}}

resource "aws_ebs_volume" "data" {{
  availability_zone = "us-east-1a"
  size              = 40
  encrypted         = true
{TAGS}
}}
""",
}

AWS_INSECURE = {
    "aws-migration/network.tf": f"""
resource "aws_vpc" "main" {{
  cidr_block = "10.10.0.0/16"
{TAGS}
}}

resource "aws_security_group" "open" {{
  vpc_id = aws_vpc.main.id
  ingress {{
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }}
{TAGS}
}}
""",
    "aws-migration/compute.tf": f"""
resource "aws_instance" "web" {{
  ami           = "ami-123"
  instance_type = "t3.medium"
  metadata_options {{
    http_endpoint               = "enabled"
    http_tokens                 = "optional"
    http_put_response_hop_limit = 2
  }}
{TAGS}
}}

resource "aws_ebs_volume" "data" {{
  availability_zone = "us-east-1a"
  size              = 40
  encrypted         = false
{TAGS}
}}
""",
}


def test_aws_hardened_output_has_no_enforce_violations() -> None:
    result = _evaluate(AWS_HARDENED)

    assert result.passed, result.deny_messages
    assert _controls(result, "enforce") == set()
    # Advisory controls still report what is missing without failing the gate.
    assert _controls(result, "advisory") == {
        "AWS-VPC-FLOW-LOGS",
        "AWS-EBS-ENCRYPTION-BY-DEFAULT",
        "AWS-EC2-DETAILED-MONITORING",
    }
    assert set(result.evaluated) == {c.id for c in CONTROLS if "aws" in c.clouds}


def test_aws_insecure_output_fails_every_enforce_control() -> None:
    result = _evaluate(AWS_INSECURE)

    assert not result.passed
    assert _controls(result, "enforce") == {
        "AWS-EC2-IMDSV2",
        "AWS-EC2-NO-PUBLIC-IP",
        "AWS-EC2-EBS-OPTIMIZED",
        "AWS-EBS-ENCRYPTED",
        "AWS-VPC-DEFAULT-SG-RESTRICTED",
        "AWS-SG-NO-OPEN-INGRESS",
    }
    imdsv2 = _messages(result, "AWS-EC2-IMDSV2")
    assert any("http_tokens" in m for m in imdsv2)
    assert any("hop_limit" in m for m in imdsv2)
    # enforce violations become deny messages with the documented prefix
    assert any(m.startswith("compliance AWS-EC2-IMDSV2: ") and "(aws_instance.web)" in m for m in result.deny_messages)
    # advisory violations never become denies
    assert not any("AWS-VPC-FLOW-LOGS" in m for m in result.deny_messages)


def test_aws_default_security_group_with_rules_is_a_violation() -> None:
    files = dict(AWS_HARDENED)
    files["aws-migration/network.tf"] = files["aws-migration/network.tf"].replace(
        'resource "aws_default_security_group" "main" {\n  vpc_id = aws_vpc.main.id\n',
        'resource "aws_default_security_group" "main" {\n  vpc_id = aws_vpc.main.id\n'
        '  ingress {\n    from_port = 0\n    to_port = 0\n    protocol = "-1"\n    cidr_blocks = ["10.0.0.0/8"]\n  }\n',
    )

    result = _evaluate(files)

    assert "AWS-VPC-DEFAULT-SG-RESTRICTED" in _controls(result, "enforce")
    assert any("no ingress rules" in m for m in _messages(result, "AWS-VPC-DEFAULT-SG-RESTRICTED"))


def test_aws_flow_log_and_encryption_by_default_satisfy_advisories() -> None:
    files = dict(AWS_HARDENED)
    files["aws-migration/extra.tf"] = f"""
resource "aws_flow_log" "main" {{
  vpc_id          = aws_vpc.main.id
  traffic_type    = "ALL"
  log_destination = "arn:aws:logs:us-east-1:123456789012:log-group:vpc"
{TAGS}
}}

resource "aws_ebs_encryption_by_default" "this" {{
  enabled = true
}}
"""
    result = _evaluate(files)

    assert result.passed
    assert "AWS-VPC-FLOW-LOGS" not in _controls(result)
    assert "AWS-EBS-ENCRYPTION-BY-DEFAULT" not in _controls(result)


# ── Azure ─────────────────────────────────────────────────────────────────────

AZURE_BASE = f"""
resource "azurerm_network_interface" "nic" {{
  name                = "nic"
  location            = "westeurope"
  resource_group_name = "rg"
  ip_configuration {{
    name                          = "internal"
    subnet_id                     = "subnet"
    private_ip_address_allocation = "Dynamic"
  }}
{TAGS}
}}

resource "azurerm_linux_virtual_machine" "vm" {{
  name                  = "vm"
  location              = "westeurope"
  resource_group_name   = "rg"
  size                  = "Standard_B2s"
  admin_username        = "azureuser"
  network_interface_ids = [azurerm_network_interface.nic.id]
  boot_diagnostics {{}}
{TAGS}
}}
"""


def _azure_nsg(source: str, ports: str) -> str:
    return f"""
resource "azurerm_network_security_group" "nsg" {{
  name                = "nsg"
  location            = "westeurope"
  resource_group_name = "rg"
  security_rule {{
    name                       = "mgmt"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    {ports}
    source_address_prefix      = "{source}"
    destination_address_prefix = "*"
  }}
{TAGS}
}}
"""


def test_azure_hardened_output_passes_enforce_controls() -> None:
    result = _evaluate({"azure-migration/main.tf": AZURE_BASE + _azure_nsg("VirtualNetwork", 'destination_port_range = "22"')})

    assert result.passed, result.deny_messages
    assert _controls(result, "enforce") == set()
    assert _controls(result, "advisory") == {"AZ-VM-ENCRYPTION-AT-HOST", "AZ-NSG-FLOW-LOGS"}


@pytest.mark.parametrize(
    "source, ports",
    [
        ("Internet", 'destination_port_range = "22"'),
        ("*", 'destination_port_range = "3389"'),
        ("0.0.0.0/0", 'destination_port_ranges = ["80", "3000-4000"]'),
        ("Any", 'destination_port_range = "*"'),
    ],
)
def test_azure_nsg_open_management_port_variants_are_denied(source: str, ports: str) -> None:
    result = _evaluate({"azure-migration/main.tf": AZURE_BASE + _azure_nsg(source, ports)})

    assert "AZ-NSG-NO-OPEN-MGMT-PORTS" in _controls(result, "enforce")
    assert not result.passed


def test_azure_nsg_open_non_management_port_is_not_flagged_by_this_control() -> None:
    result = _evaluate({"azure-migration/main.tf": AZURE_BASE + _azure_nsg("Internet", 'destination_port_range = "443"')})

    assert "AZ-NSG-NO-OPEN-MGMT-PORTS" not in _controls(result)


def test_azure_public_ip_on_nic_and_storage_account_defaults_are_denied() -> None:
    files = {
        "azure-migration/main.tf": AZURE_BASE.replace(
            'private_ip_address_allocation = "Dynamic"',
            'private_ip_address_allocation = "Dynamic"\n    public_ip_address_id = "pip-id"',
        )
        + f"""
resource "azurerm_storage_account" "sa" {{
  name                     = "sa"
  resource_group_name      = "rg"
  location                 = "westeurope"
  account_tier             = "Standard"
  account_replication_type = "LRS"
{TAGS}
}}
"""
    }
    result = _evaluate(files)

    enforce = _controls(result, "enforce")
    assert {"AZ-NIC-NO-PUBLIC-IP", "AZ-STORAGE-SECURE-TRANSPORT", "AZ-STORAGE-NO-PUBLIC-ACCESS"} <= enforce


def test_azure_hardened_storage_account_passes() -> None:
    files = {
        "azure-migration/main.tf": f"""
resource "azurerm_storage_account" "sa" {{
  name                            = "sa"
  resource_group_name             = "rg"
  location                        = "westeurope"
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  min_tls_version                 = "TLS1_2"
  https_traffic_only_enabled      = true
  allow_nested_items_to_be_public = false
  public_network_access_enabled   = false
{TAGS}
}}
"""
    }
    result = _evaluate(files)

    assert result.passed, result.deny_messages
    assert _controls(result, "enforce") == set()


# ── GCP ───────────────────────────────────────────────────────────────────────

GCP_HARDENED = {
    "gcp-migration/variables.tf": """
variable "service_account_email" {
  type    = string
  default = ""
}
variable "default_kms_key_self_link" {
  type    = string
  default = ""
}
""",
    "gcp-migration/network.tf": """
resource "google_compute_subnetwork" "app" {
  name                     = "app"
  network                  = "net"
  ip_cidr_range            = "10.60.1.0/24"
  private_ip_google_access = true
  log_config {
    aggregation_interval = "INTERVAL_5_SEC"
    flow_sampling        = 0.5
    metadata             = "INCLUDE_ALL_METADATA"
  }
}

resource "google_compute_firewall" "ssh_internal" {
  name          = "ssh-internal"
  network       = "net"
  direction     = "INGRESS"
  source_ranges = ["10.0.0.0/8"]
  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}
""",
    "gcp-migration/compute.tf": f"""
resource "google_compute_instance" "web" {{
  name           = "web"
  machine_type   = "e2-medium"
  zone           = "europe-west1-b"
  can_ip_forward = false
  boot_disk {{
    initialize_params {{
      image = "debian-12"
    }}
  }}
  network_interface {{
    subnetwork = google_compute_subnetwork.app.id
  }}
  shielded_instance_config {{
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }}
  service_account {{
    email  = var.service_account_email != "" ? var.service_account_email : null
    scopes = ["https://www.googleapis.com/auth/logging.write", "https://www.googleapis.com/auth/monitoring.write"]
  }}
  metadata = {{
    enable-oslogin         = "TRUE"
    block-project-ssh-keys = "TRUE"
    serial-port-enable     = "FALSE"
  }}
{LABELS}
}}

resource "google_compute_disk" "data" {{
  name = "data"
  zone = "europe-west1-b"
  size = 40
  dynamic "disk_encryption_key" {{
    for_each = var.default_kms_key_self_link == "" ? [] : [1]
    content {{
      kms_key_self_link = var.default_kms_key_self_link
    }}
  }}
{LABELS}
}}
""",
}

GCP_INSECURE = {
    "gcp-migration/network.tf": """
resource "google_compute_subnetwork" "app" {
  name          = "app"
  network       = "net"
  ip_cidr_range = "10.60.1.0/24"
}

resource "google_compute_firewall" "rdp_open" {
  name          = "rdp-open"
  network       = "net"
  source_ranges = ["0.0.0.0/0"]
  allow {
    protocol = "tcp"
    ports    = ["3000-4000"]
  }
}
""",
    "gcp-migration/compute.tf": f"""
resource "google_compute_instance" "web" {{
  name           = "web"
  machine_type   = "e2-medium"
  zone           = "europe-west1-b"
  can_ip_forward = true
  boot_disk {{
    initialize_params {{
      image = "debian-12"
    }}
  }}
  network_interface {{
    subnetwork = google_compute_subnetwork.app.id
    access_config {{}}
  }}
  service_account {{
    scopes = ["cloud-platform"]
  }}
  metadata = {{
    serial-port-enable = "TRUE"
  }}
{LABELS}
}}
""",
}


def test_gcp_hardened_output_has_no_enforce_violations() -> None:
    result = _evaluate(GCP_HARDENED)

    assert result.passed, result.deny_messages
    assert _controls(result, "enforce") == set()
    assert _controls(result, "advisory") == {"GCP-VM-DEDICATED-SA", "GCP-DISK-CMEK"}
    assert set(result.evaluated) == {c.id for c in CONTROLS if "gcp" in c.clouds}


def test_gcp_insecure_output_fails_every_enforce_control() -> None:
    result = _evaluate(GCP_INSECURE)

    assert not result.passed
    assert _controls(result, "enforce") == {
        "GCP-VM-NO-EXTERNAL-IP",
        "GCP-VM-SHIELDED",
        "GCP-VM-OSLOGIN",
        "GCP-VM-SERIAL-PORT-DISABLED",
        "GCP-VM-BLOCK-PROJECT-SSH-KEYS",
        "GCP-VM-NO-IP-FORWARD",
        "GCP-VM-LIMITED-SCOPES",
        "GCP-SUBNET-FLOW-LOGS",
        "GCP-SUBNET-PRIVATE-GOOGLE-ACCESS",
        "GCP-FW-NO-OPEN-MGMT-PORTS",
    }
    assert any("3389" in m for m in _messages(result, "GCP-FW-NO-OPEN-MGMT-PORTS"))


def test_gcp_instance_without_metadata_fails_oslogin_and_project_ssh_keys() -> None:
    files = dict(GCP_HARDENED)
    compute = files["gcp-migration/compute.tf"]
    start = compute.index("  metadata = {")
    end = compute.index("}", start) + 2
    files["gcp-migration/compute.tf"] = compute[:start] + compute[end:]

    result = _evaluate(files)

    enforce = _controls(result, "enforce")
    assert {"GCP-VM-OSLOGIN", "GCP-VM-BLOCK-PROJECT-SSH-KEYS"} <= enforce
    assert "GCP-VM-SERIAL-PORT-DISABLED" not in enforce


def test_gcp_variable_defaults_satisfy_dedicated_sa_and_cmek_advisories() -> None:
    files = dict(GCP_HARDENED)
    files["gcp-migration/variables.tf"] = """
variable "service_account_email" {
  type    = string
  default = "migrated-vms@my-project.iam.gserviceaccount.com"
}
variable "default_kms_key_self_link" {
  type    = string
  default = "projects/p/locations/europe/keyRings/r/cryptoKeys/k"
}
"""
    result = _evaluate(files)

    assert result.passed
    assert _controls(result) == set()


# ── OpenStack ─────────────────────────────────────────────────────────────────


def _openstack_files(remote_ip_prefix: str, port_min: int | None, port_max: int | None, volume_type: str) -> dict[str, str]:
    ports = ""
    if port_min is not None and port_max is not None:
        ports = f"  port_range_min    = {port_min}\n  port_range_max    = {port_max}\n"
    return {
        "openstack-migration/variables.tf": """
variable "encrypted_volume_type" {
  type    = string
  default = "encrypted"
}
""",
        "openstack-migration/main.tf": f"""
resource "openstack_networking_secgroup_v2" "sg" {{
  name = "sg"
}}

resource "openstack_networking_secgroup_rule_v2" "rule" {{
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
{ports}  remote_ip_prefix  = "{remote_ip_prefix}"
  security_group_id = openstack_networking_secgroup_v2.sg.id
}}

resource "openstack_blockstorage_volume_v3" "data" {{
  name        = "data"
  size        = 40
  volume_type = {volume_type}
  metadata = {{
    Environment  = var.environment
    Owner        = var.owner
    MigratedFrom = "vmware-vcenter"
  }}
}}
""",
    }


def test_openstack_hardened_output_passes() -> None:
    result = _evaluate(_openstack_files("10.0.0.0/8", 22, 22, "var.encrypted_volume_type"))

    assert result.passed, result.deny_messages
    assert _controls(result) == set()
    assert set(result.evaluated) == {c.id for c in CONTROLS if "openstack" in c.clouds}


@pytest.mark.parametrize("port_min, port_max", [(22, 22), (3000, 4000), (None, None)])
def test_openstack_open_management_ports_are_denied(port_min: int | None, port_max: int | None) -> None:
    result = _evaluate(_openstack_files("0.0.0.0/0", port_min, port_max, "var.encrypted_volume_type"))

    assert "OS-SG-NO-OPEN-MGMT-PORTS" in _controls(result, "enforce")
    assert not result.passed


def test_openstack_open_https_is_not_a_management_port_finding() -> None:
    result = _evaluate(_openstack_files("0.0.0.0/0", 443, 443, "var.encrypted_volume_type"))

    assert "OS-SG-NO-OPEN-MGMT-PORTS" not in _controls(result)
    # the base no_open_ingress rule still fails the gate for any 0.0.0.0/0 ingress
    assert not result.passed


def test_openstack_unverifiable_volume_type_is_advisory_only() -> None:
    result = _evaluate(_openstack_files("10.0.0.0/8", 22, 22, '"standard"'))

    assert result.passed
    assert _controls(result) == {"OS-VOLUME-ENCRYPTED-TYPE"}
    assert _controls(result, "enforce") == set()


# ── Proxmox VE ────────────────────────────────────────────────────────────────

PROXMOX_VARIABLES = """
variable "datastore_id" {
  type    = string
  default = "zfs-encrypted"
}
variable "management_cidrs" {
  type    = list(string)
  default = ["10.0.0.0/8", "192.168.0.0/16"]
}
variable "environment" {
  type    = string
  default = "test"
}
variable "owner" {
  type    = string
  default = "platform"
}
"""

PROXMOX_TAGS = '["env-${var.environment}", "migratedfrom-vmware-vcenter", "owner-${var.owner}"]'

PROXMOX_SECURE_BOOT = """
  efi_disk {
    datastore_id      = var.datastore_id
    type              = "4m"
    pre_enrolled_keys = true
  }
  tpm_state {
    datastore_id = var.datastore_id
    version      = "v2.0"
  }
"""


def _proxmox_vm(
    name: str,
    *,
    bios: str = "ovmf",
    firmware: str = PROXMOX_SECURE_BOOT,
    agent: bool = True,
    tags: str = PROXMOX_TAGS,
    firewall_nic: bool = True,
    datastore: str = "var.datastore_id",
    extra: str = "",
) -> str:
    agent_block = "  agent {\n    enabled = true\n  }\n" if agent else ""
    return f"""
resource "proxmox_virtual_environment_vm" "{name}" {{
  name      = "{name}"
  node_name = "pve"
  tags      = {tags}
  bios      = "{bios}"
{firmware if bios == "ovmf" else ""}{agent_block}
  cpu {{
    cores = 2
  }}
  memory {{
    dedicated = 2048
  }}
  operating_system {{
    type = "l26"
  }}
  disk {{
    interface    = "scsi0"
    datastore_id = {datastore}
    size         = 40
  }}
  network_device {{
    bridge   = "vmbr0"
    vlan_id  = 110
    firewall = {str(firewall_nic).lower()}
  }}
{extra}}}
"""


def _proxmox_rule(
    *,
    source: str | None = 'join(",", var.management_cidrs)',
    dport: str | None = '"22"',
    macro: str | None = None,
    proto: str | None = '"tcp"',
    action: str = "ACCEPT",
    direction: str = "in",
) -> str:
    lines = ["  rule {", f'    type    = "{direction}"', f'    action  = "{action}"', '    comment = "mgmt"']
    if source is not None:
        lines.append(f"    source  = {source}")
    if proto is not None:
        lines.append(f"    proto   = {proto}")
    if dport is not None:
        lines.append(f"    dport   = {dport}")
    if macro is not None:
        lines.append(f'    macro   = "{macro}"')
    lines.append("  }")
    return "\n".join(lines) + "\n"


def _proxmox_firewall(name: str, rules: str, *, enabled: bool = True, input_policy: str = "DROP") -> str:
    return f"""
resource "proxmox_virtual_environment_firewall_options" "{name}" {{
  node_name     = proxmox_virtual_environment_vm.{name}.node_name
  vm_id         = proxmox_virtual_environment_vm.{name}.vm_id
  enabled       = {str(enabled).lower()}
  input_policy  = "{input_policy}"
  output_policy = "ACCEPT"
}}

resource "proxmox_virtual_environment_firewall_rules" "{name}" {{
  node_name = proxmox_virtual_environment_vm.{name}.node_name
  vm_id     = proxmox_virtual_environment_vm.{name}.vm_id
{rules}}}
"""


PROXMOX_HA = """
resource "proxmox_virtual_environment_hagroup" "prod" {
  group = "prod"
  nodes = { pve = null }
}

resource "proxmox_virtual_environment_haresource" "web" {
  resource_id = "vm:${proxmox_virtual_environment_vm.web.vm_id}"
  group       = proxmox_virtual_environment_hagroup.prod.group
  state       = "started"
}
"""

PROXMOX_HARDENED = {
    "proxmox-migration/variables.tf": PROXMOX_VARIABLES,
    "proxmox-migration/main.tf": _proxmox_vm("web") + _proxmox_firewall("web", _proxmox_rule()) + PROXMOX_HA,
}

PROXMOX_INSECURE = {
    "proxmox-migration/main.tf": (
        _proxmox_vm("web", bios="seabios", agent=False, tags='["Env-Prod"]', firewall_nic=False, extra="  serial_device {}\n")
        + _proxmox_vm("db")  # no firewall_options resource at all
        + _proxmox_firewall("web", _proxmox_rule(source='"0.0.0.0/0"'), enabled=False, input_policy="ACCEPT")
    ),
}

PROXMOX_ENFORCE_CONTROLS = {
    "PVE-FW-NO-OPEN-MGMT-PORTS",
    "PVE-VM-FIREWALL-ENABLED",
    "PVE-VM-AGENT-ENABLED",
    "PVE-VM-OWNERSHIP-TAGS",
    "PVE-VM-NO-SERIAL-CONSOLE",
}


def _proxmox_files(rules: str, variables: str = PROXMOX_VARIABLES) -> dict[str, str]:
    return {
        "proxmox-migration/variables.tf": variables,
        "proxmox-migration/main.tf": _proxmox_vm("web") + _proxmox_firewall("web", rules) + PROXMOX_HA,
    }


def test_proxmox_hardened_output_passes_every_control() -> None:
    result = _evaluate(PROXMOX_HARDENED)

    assert result.passed, result.deny_messages
    assert _controls(result) == set()
    assert set(result.evaluated) == {c.id for c in CONTROLS if "proxmox" in c.clouds}
    assert "ALL-TAGS-REQUIRED" in result.evaluated


def test_proxmox_insecure_output_fails_every_enforce_control() -> None:
    result = _evaluate(PROXMOX_INSECURE)

    assert not result.passed
    assert _controls(result, "enforce") == PROXMOX_ENFORCE_CONTROLS | {"ALL-TAGS-REQUIRED"}
    assert _controls(result, "advisory") == {"PVE-DISK-ENCRYPTION", "PVE-VM-SECURE-BOOT", "PVE-HA-ENABLED"}
    firewall = _messages(result, "PVE-VM-FIREWALL-ENABLED")
    assert any("net0 must set firewall = true" in m for m in firewall)
    assert any("has no proxmox_virtual_environment_firewall_options" in m for m in firewall)
    assert any("enabled = true" in m for m in firewall) and any("input_policy" in m for m in firewall)
    tags = _messages(result, "PVE-VM-OWNERSHIP-TAGS")
    assert any('"Env-Prod" is not a lower-case Proxmox tag' in m for m in tags)
    assert {m for m in tags if "has no" in m} == {"tags list has no env-* tag", "tags list has no owner-* tag", "tags list has no migratedfrom-* tag"}
    assert any(m.startswith("compliance PVE-VM-AGENT-ENABLED: ") and "(proxmox_virtual_environment_vm.web)" in m for m in result.deny_messages)
    assert not any("PVE-HA-ENABLED" in m for m in result.deny_messages)


@pytest.mark.parametrize(
    "rule",
    [
        _proxmox_rule(source='"0.0.0.0/0"'),
        _proxmox_rule(source=None, dport='"3000:4000"'),
        _proxmox_rule(source='"::/0"', dport=None, macro="RDP", proto=None),
        _proxmox_rule(source='"10.0.0.0/8, 0.0.0.0/0"', dport='"80,ssh"'),
        _proxmox_rule(source=None, dport=None, proto=None),
    ],
    ids=["literal-open", "no-source-range", "ipv6-open-rdp-macro", "mixed-list-service-name", "everything-open"],
)
def test_proxmox_open_management_port_variants_are_denied(rule: str) -> None:
    result = _evaluate(_proxmox_files(rule))

    assert "PVE-FW-NO-OPEN-MGMT-PORTS" in _controls(result, "enforce")
    assert not result.passed


def test_proxmox_management_cidrs_variable_default_is_checked() -> None:
    open_default = PROXMOX_VARIABLES.replace('["10.0.0.0/8", "192.168.0.0/16"]', '["0.0.0.0/0"]')
    result = _evaluate(_proxmox_files(_proxmox_rule(), variables=open_default))

    assert "PVE-FW-NO-OPEN-MGMT-PORTS" in _controls(result, "enforce")
    # an expression the policy cannot trace to a variable default is treated as unverified, i.e. open
    untraceable = _evaluate(_proxmox_files(_proxmox_rule(source="local.ranges")))
    assert "PVE-FW-NO-OPEN-MGMT-PORTS" in _controls(untraceable, "enforce")


def test_proxmox_open_https_is_not_a_management_port_finding() -> None:
    result = _evaluate(_proxmox_files(_proxmox_rule(source='"0.0.0.0/0"', dport='"443"')))

    assert "PVE-FW-NO-OPEN-MGMT-PORTS" not in _controls(result)
    # the base no_open_ingress rule still fails the gate for any inbound ACCEPT from the internet
    assert not result.passed
    assert any(m.startswith("no_open_ingress: proxmox_virtual_environment_firewall_rules.web") for m in result.deny_messages)
    # outbound and dropped inbound rules are not ingress findings
    assert _evaluate(_proxmox_files(_proxmox_rule(source='"0.0.0.0/0"', direction="out"))).passed
    assert _evaluate(_proxmox_files(_proxmox_rule(source='"0.0.0.0/0"', action="DROP"))).passed


def test_proxmox_missing_ownership_tag_hits_both_tag_controls() -> None:
    files = dict(PROXMOX_HARDENED)
    files["proxmox-migration/main.tf"] = files["proxmox-migration/main.tf"].replace(', "owner-${var.owner}"', "", 1)

    result = _evaluate(files)

    assert {"ALL-TAGS-REQUIRED", "PVE-VM-OWNERSHIP-TAGS"} <= _controls(result, "enforce")
    assert "tags list missing owner-" in _messages(result, "ALL-TAGS-REQUIRED")
    assert "tags list has no owner-* tag" in _messages(result, "PVE-VM-OWNERSHIP-TAGS")


def test_proxmox_advisories_report_secure_boot_details_and_unverified_datastore() -> None:
    weak_efi = PROXMOX_SECURE_BOOT.replace('type              = "4m"', 'type              = "2m"').split("  tpm_state")[0]
    files = {
        "proxmox-migration/variables.tf": PROXMOX_VARIABLES,
        "proxmox-migration/main.tf": _proxmox_vm("web", firmware=weak_efi, datastore='"local-lvm"') + _proxmox_firewall("web", _proxmox_rule()),
    }
    result = _evaluate(files)

    assert result.passed
    assert _controls(result, "enforce") == set()
    secure_boot = _messages(result, "PVE-VM-SECURE-BOOT")
    assert any("efi_disk must set type" in m for m in secure_boot) and any("has no tpm_state" in m for m in secure_boot)
    assert _messages(result, "PVE-DISK-ENCRYPTION") == [
        "disk scsi0 uses datastore local-lvm, which cannot be confirmed as encrypted; place VM disks on a LUKS- or ZFS-encrypted datastore"
    ]
    assert _messages(result, "PVE-HA-ENABLED") and "PVE-HA-ENABLED" in _controls(result, "advisory")


# ── cross-cutting ─────────────────────────────────────────────────────────────


def test_missing_required_tags_are_an_enforce_violation() -> None:
    files = dict(AWS_HARDENED)
    files["aws-migration/compute.tf"] = files["aws-migration/compute.tf"].replace("    Owner         = var.owner\n", "", 1)

    result = _evaluate(files)

    assert "ALL-TAGS-REQUIRED" in _controls(result, "enforce")
    assert any("missing Owner" in m for m in _messages(result, "ALL-TAGS-REQUIRED"))


def test_nothing_is_evaluated_for_an_unknown_cloud() -> None:
    result = _evaluate({"other-migration/main.tf": 'resource "random_pet" "x" {}\n'})

    assert result.evaluated == []
    assert result.violations == []


def test_policy_bundle_controls_match_the_python_catalog() -> None:
    assert OPA_BIN is not None
    completed = subprocess.run(
        [OPA_BIN, "eval", "--format", "json", "--data", str(POLICIES_DIR), "data.hopshift.compliance.controls"],
        capture_output=True,
        text=True,
        check=True,
    )
    bundle_controls = json.loads(completed.stdout)["result"][0]["expressions"][0]["value"]

    assert set(bundle_controls) == set(CONTROLS_BY_ID)
    assert {cid: control.level for cid, control in CONTROLS_BY_ID.items()} == bundle_controls
