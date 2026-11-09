"""Catalog of compliance controls evaluated by validation/policies/compliance/*.rego.

Each control id and level here must match the rego bundle (data.vmwaremigration.compliance.controls);
tests/validation/test_compliance_policies.py checks that. Framework references point to the
section that covers the same objective:

- cis:   CIS Foundations Benchmarks (AWS v3.0, Azure v3.0, GCP v3.0). CIS publishes no OpenStack
         benchmark, so OpenStack controls carry no CIS reference.
- soc2:  SOC 2 Trust Services Criteria (2017, 2022 points of focus) common criteria ids.
- hipaa: HIPAA Security Rule, 45 CFR 164.308 / 164.310 / 164.312.

SOC 2 and HIPAA are organisational attestations; a control passing here is technical evidence
for the mapped criterion, not a certification. See docs/compliance.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Level = Literal["enforce", "advisory"]

ALL_CLOUDS: tuple[str, ...] = ("aws", "azure", "gcp", "openstack")
FRAMEWORKS: tuple[str, ...] = ("cis", "soc2", "hipaa")

# Shorthand for the SOC 2 / HIPAA references used repeatedly below.
_SOC2_ACCESS = ["CC6.1", "CC6.6"]
_SOC2_ENCRYPTION = ["CC6.1", "CC6.7"]
_SOC2_MONITORING = ["CC7.1", "CC7.2"]
_HIPAA_ACCESS = ["164.312(a)(1)", "164.312(e)(1)"]
_HIPAA_ENCRYPTION = ["164.312(a)(2)(iv)", "164.312(e)(2)(ii)"]
_HIPAA_AUDIT = ["164.312(b)", "164.308(a)(1)(ii)(D)"]


@dataclass(frozen=True)
class Control:
    id: str
    title: str
    description: str
    clouds: tuple[str, ...]
    level: Level
    remediation: str
    frameworks: dict[str, list[str]] = field(default_factory=dict)

    def applies_to(self, cloud: str) -> bool:
        return cloud.strip().lower() in self.clouds

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "clouds": list(self.clouds),
            "level": self.level,
            "frameworks": {name: list(self.frameworks.get(name, [])) for name in FRAMEWORKS},
            "remediation": self.remediation,
        }


def _frameworks(cis: list[str] | None = None, soc2: list[str] | None = None, hipaa: list[str] | None = None) -> dict[str, list[str]]:
    return {"cis": list(cis or []), "soc2": list(soc2 or []), "hipaa": list(hipaa or [])}


CONTROLS: tuple[Control, ...] = (
    # ── all clouds ────────────────────────────────────────────────────────────
    Control(
        id="ALL-TAGS-REQUIRED",
        title="Required ownership tags on every resource",
        description=(
            "Every taggable resource carries Environment, Owner and MigratedFrom (lowercase labels on GCP, "
            "Key=Value list entries on OpenStack networks) so ownership and provenance are auditable."
        ),
        clouds=ALL_CLOUDS,
        level="enforce",
        frameworks=_frameworks(soc2=["CC6.1", "CC3.2"], hipaa=["164.308(a)(1)(ii)(A)", "164.310(d)(1)"]),
        remediation="Add the missing keys to the resource's tags/labels/metadata map (the renderers emit var.environment and var.owner).",
    ),
    # ── AWS ───────────────────────────────────────────────────────────────────
    Control(
        id="AWS-EC2-IMDSV2",
        title="EC2 instances require IMDSv2",
        description="aws_instance sets metadata_options { http_endpoint = \"enabled\", http_tokens = \"required\", http_put_response_hop_limit = 1 } so credentials in the instance metadata cannot be read through SSRF.",
        clouds=("aws",),
        level="enforce",
        frameworks=_frameworks(cis=["AWS 5.6"], soc2=_SOC2_ACCESS, hipaa=_HIPAA_ACCESS),
        remediation="Add a metadata_options block with http_tokens = \"required\", http_endpoint = \"enabled\" and http_put_response_hop_limit = 1 to every aws_instance.",
    ),
    Control(
        id="AWS-EC2-NO-PUBLIC-IP",
        title="EC2 instances have no public IP",
        description="aws_instance sets associate_public_ip_address = false and no Elastic IP is attached; migrated workloads are reached through private connectivity.",
        clouds=("aws",),
        level="enforce",
        frameworks=_frameworks(soc2=_SOC2_ACCESS, hipaa=_HIPAA_ACCESS),
        remediation="Set associate_public_ip_address = false, remove aws_eip / aws_eip_association resources that target migrated instances and publish services through a load balancer or VPN instead.",
    ),
    Control(
        id="AWS-EC2-EBS-OPTIMIZED",
        title="EC2 instances are EBS-optimized",
        description="aws_instance sets ebs_optimized = true so block storage traffic uses dedicated bandwidth; this is a platform baseline rather than a CIS item.",
        clouds=("aws",),
        level="enforce",
        frameworks=_frameworks(soc2=["A1.1"]),
        remediation="Set ebs_optimized = true (every instance type in the sizing table supports it).",
    ),
    Control(
        id="AWS-EBS-ENCRYPTED",
        title="EBS volumes and root devices are encrypted",
        description="aws_ebs_volume sets encrypted = true and every aws_instance declares root_block_device / ebs_block_device with encrypted = true.",
        clouds=("aws",),
        level="enforce",
        frameworks=_frameworks(cis=["AWS 2.2.1"], soc2=_SOC2_ENCRYPTION, hipaa=_HIPAA_ENCRYPTION),
        remediation="Set encrypted = true on the volume or block device (optionally kms_key_id for a customer-managed key).",
    ),
    Control(
        id="AWS-VPC-DEFAULT-SG-RESTRICTED",
        title="Default security group of every VPC restricts all traffic",
        description="Every aws_vpc is paired with an aws_default_security_group that declares no ingress or egress rules, so the implicit default group cannot be used to open traffic.",
        clouds=("aws",),
        level="enforce",
        frameworks=_frameworks(cis=["AWS 5.4"], soc2=_SOC2_ACCESS, hipaa=_HIPAA_ACCESS),
        remediation="Add resource \"aws_default_security_group\" { vpc_id = aws_vpc.<name>.id } with no ingress/egress blocks for each VPC.",
    ),
    Control(
        id="AWS-SG-NO-OPEN-INGRESS",
        title="No security group ingress from the internet",
        description="aws_security_group ingress, aws_security_group_rule and aws_vpc_security_group_ingress_rule never allow 0.0.0.0/0 or ::/0.",
        clouds=("aws",),
        level="enforce",
        frameworks=_frameworks(cis=["AWS 5.2", "AWS 5.3"], soc2=_SOC2_ACCESS, hipaa=_HIPAA_ACCESS),
        remediation="Restrict cidr_blocks / ipv6_cidr_blocks to the corporate or VPC ranges; expose services through a load balancer with its own security group.",
    ),
    Control(
        id="AWS-VPC-FLOW-LOGS",
        title="VPC flow logs enabled",
        description="Every aws_vpc has an aws_flow_log so network traffic metadata is captured for monitoring and forensics.",
        clouds=("aws",),
        level="advisory",
        frameworks=_frameworks(cis=["AWS 3.7"], soc2=_SOC2_MONITORING, hipaa=_HIPAA_AUDIT),
        remediation="Add an aws_flow_log per VPC (vpc_id = aws_vpc.<name>.id) delivering to CloudWatch Logs or S3; it needs a log destination and IAM role, which this platform does not create.",
    ),
    Control(
        id="AWS-EBS-ENCRYPTION-BY-DEFAULT",
        title="Account-level EBS encryption by default",
        description="An aws_ebs_encryption_by_default resource enables encryption for every new volume in the region, catching volumes created outside this module.",
        clouds=("aws",),
        level="advisory",
        frameworks=_frameworks(cis=["AWS 2.2.1"], soc2=_SOC2_ENCRYPTION, hipaa=_HIPAA_ENCRYPTION),
        remediation="Add resource \"aws_ebs_encryption_by_default\" \"this\" { enabled = true } (account/region-wide setting; coordinate with the account owner).",
    ),
    Control(
        id="AWS-EC2-DETAILED-MONITORING",
        title="EC2 detailed monitoring",
        description="aws_instance sets monitoring = true for one-minute CloudWatch metrics.",
        clouds=("aws",),
        level="advisory",
        frameworks=_frameworks(soc2=_SOC2_MONITORING, hipaa=_HIPAA_AUDIT),
        remediation="Set monitoring = true on instances that need one-minute metrics (additional CloudWatch cost).",
    ),
    # ── Azure ─────────────────────────────────────────────────────────────────
    Control(
        id="AZ-NIC-NO-PUBLIC-IP",
        title="Network interfaces have no public IP",
        description="azurerm_network_interface ip_configuration blocks never set public_ip_address_id.",
        clouds=("azure",),
        level="enforce",
        frameworks=_frameworks(soc2=_SOC2_ACCESS, hipaa=_HIPAA_ACCESS),
        remediation="Remove public_ip_address_id from the NIC and reach the VM through Azure Bastion, VPN or a load balancer.",
    ),
    Control(
        id="AZ-NSG-NO-OPEN-MGMT-PORTS",
        title="No SSH/RDP from the internet in network security groups",
        description="Inbound Allow rules whose source is Internet, Any, * or 0.0.0.0/0 never cover port 22 or 3389.",
        clouds=("azure",),
        level="enforce",
        frameworks=_frameworks(cis=["Azure 7.1", "Azure 7.2"], soc2=_SOC2_ACCESS, hipaa=_HIPAA_ACCESS),
        remediation="Restrict source_address_prefix to VirtualNetwork or a corporate range, or use Azure Bastion / just-in-time access.",
    ),
    Control(
        id="AZ-STORAGE-SECURE-TRANSPORT",
        title="Storage accounts require TLS 1.2 and HTTPS",
        description="azurerm_storage_account sets min_tls_version = \"TLS1_2\" and https_traffic_only_enabled = true.",
        clouds=("azure",),
        level="enforce",
        frameworks=_frameworks(cis=["Azure 4.1", "Azure 4.15"], soc2=["CC6.7"], hipaa=["164.312(e)(1)", "164.312(e)(2)(ii)"]),
        remediation="Set min_tls_version = \"TLS1_2\" and https_traffic_only_enabled = true on the storage account.",
    ),
    Control(
        id="AZ-STORAGE-NO-PUBLIC-ACCESS",
        title="Storage accounts block public access",
        description="azurerm_storage_account sets allow_nested_items_to_be_public = false and public_network_access_enabled = false.",
        clouds=("azure",),
        level="enforce",
        frameworks=_frameworks(cis=["Azure 4.6", "Azure 4.17"], soc2=_SOC2_ACCESS, hipaa=_HIPAA_ACCESS),
        remediation="Set allow_nested_items_to_be_public = false and public_network_access_enabled = false; use private endpoints for access.",
    ),
    Control(
        id="AZ-VM-ENCRYPTION-AT-HOST",
        title="Encryption at host for virtual machines",
        description="Virtual machines set encryption_at_host_enabled = true so temp disks and caches are encrypted; the subscription must have the Microsoft.Compute/EncryptionAtHost feature registered first.",
        clouds=("azure",),
        level="advisory",
        frameworks=_frameworks(cis=["Azure 8.9"], soc2=_SOC2_ENCRYPTION, hipaa=_HIPAA_ENCRYPTION),
        remediation="Register the EncryptionAtHost feature on the subscription, then set encryption_at_host_enabled = true on each VM.",
    ),
    Control(
        id="AZ-VM-BOOT-DIAGNOSTICS",
        title="Boot diagnostics enabled",
        description="Virtual machines declare a boot_diagnostics block (managed storage when storage_account_uri is omitted) so boot failures can be investigated.",
        clouds=("azure",),
        level="advisory",
        frameworks=_frameworks(soc2=_SOC2_MONITORING, hipaa=_HIPAA_AUDIT),
        remediation="Add boot_diagnostics {} to the VM (managed storage account) or point storage_account_uri at a diagnostics account.",
    ),
    Control(
        id="AZ-DISK-CMK",
        title="Managed disks use customer-managed keys",
        description="azurerm_managed_disk sets disk_encryption_set_id so data is encrypted with a key the organisation controls instead of platform-managed keys.",
        clouds=("azure",),
        level="advisory",
        frameworks=_frameworks(cis=["Azure 8.3"], soc2=_SOC2_ENCRYPTION, hipaa=_HIPAA_ENCRYPTION),
        remediation="Create an azurerm_disk_encryption_set backed by Key Vault and set disk_encryption_set_id on each managed disk.",
    ),
    Control(
        id="AZ-NSG-FLOW-LOGS",
        title="NSG flow logs enabled",
        description="Every azurerm_network_security_group is the target of an azurerm_network_watcher_flow_log.",
        clouds=("azure",),
        level="advisory",
        frameworks=_frameworks(cis=["Azure 7.6"], soc2=_SOC2_MONITORING, hipaa=_HIPAA_AUDIT),
        remediation="Add an azurerm_network_watcher_flow_log per NSG with a storage account and retention policy; it needs Network Watcher in the region, which this platform does not create.",
    ),
    # ── GCP ───────────────────────────────────────────────────────────────────
    Control(
        id="GCP-VM-NO-EXTERNAL-IP",
        title="Compute instances have no external IP",
        description="google_compute_instance network_interface blocks declare no access_config / ipv6_access_config.",
        clouds=("gcp",),
        level="enforce",
        frameworks=_frameworks(cis=["GCP 4.9"], soc2=_SOC2_ACCESS, hipaa=_HIPAA_ACCESS),
        remediation="Remove access_config from network_interface and use IAP TCP forwarding, Cloud VPN or a load balancer.",
    ),
    Control(
        id="GCP-VM-SHIELDED",
        title="Shielded VM enabled",
        description="google_compute_instance sets shielded_instance_config { enable_secure_boot, enable_vtpm, enable_integrity_monitoring } to true; imported images need the UEFI_COMPATIBLE guest OS feature.",
        clouds=("gcp",),
        level="enforce",
        frameworks=_frameworks(cis=["GCP 4.8"], soc2=["CC6.8", "CC7.1"], hipaa=["164.312(c)(1)"]),
        remediation="Add shielded_instance_config with all three flags true and import VM images with --guest-os-features=UEFI_COMPATIBLE.",
    ),
    Control(
        id="GCP-VM-OSLOGIN",
        title="OS Login enabled",
        description="Instance metadata sets enable-oslogin = \"TRUE\" so SSH access is governed by IAM instead of metadata-managed keys.",
        clouds=("gcp",),
        level="enforce",
        frameworks=_frameworks(cis=["GCP 4.4"], soc2=["CC6.1", "CC6.2", "CC6.3"], hipaa=["164.312(a)(1)", "164.312(d)"]),
        remediation="Set metadata = { enable-oslogin = \"TRUE\" } on the instance (or at project level) and grant roles/compute.osLogin to operators.",
    ),
    Control(
        id="GCP-VM-SERIAL-PORT-DISABLED",
        title="Serial port access disabled",
        description="Instance metadata never sets serial-port-enable to TRUE.",
        clouds=("gcp",),
        level="enforce",
        frameworks=_frameworks(cis=["GCP 4.5"], soc2=_SOC2_ACCESS, hipaa=_HIPAA_ACCESS),
        remediation="Remove serial-port-enable from metadata or set it to \"FALSE\".",
    ),
    Control(
        id="GCP-VM-BLOCK-PROJECT-SSH-KEYS",
        title="Project-wide SSH keys blocked",
        description="Instance metadata sets block-project-ssh-keys = \"TRUE\" so project-level keys cannot log in to migrated VMs.",
        clouds=("gcp",),
        level="enforce",
        frameworks=_frameworks(cis=["GCP 4.3"], soc2=["CC6.1", "CC6.2"], hipaa=["164.312(a)(1)", "164.312(d)"]),
        remediation="Set metadata block-project-ssh-keys = \"TRUE\" on the instance.",
    ),
    Control(
        id="GCP-VM-NO-IP-FORWARD",
        title="IP forwarding disabled",
        description="google_compute_instance keeps can_ip_forward = false so instances cannot route traffic for other hosts.",
        clouds=("gcp",),
        level="enforce",
        frameworks=_frameworks(cis=["GCP 4.6"], soc2=_SOC2_ACCESS, hipaa=_HIPAA_ACCESS),
        remediation="Set can_ip_forward = false; use Cloud NAT or a dedicated appliance for routing.",
    ),
    Control(
        id="GCP-VM-LIMITED-SCOPES",
        title="Service account scopes limited",
        description="google_compute_instance declares a service_account block whose scopes never include cloud-platform (full API access).",
        clouds=("gcp",),
        level="enforce",
        frameworks=_frameworks(cis=["GCP 4.2"], soc2=["CC6.1", "CC6.3"], hipaa=["164.312(a)(1)", "164.308(a)(4)(ii)(B)"]),
        remediation="Declare service_account { scopes = [logging.write, monitoring.write, devstorage.read_only] } and grant permissions through IAM roles rather than scopes.",
    ),
    Control(
        id="GCP-VM-DEDICATED-SA",
        title="Dedicated service account per workload",
        description="Instances run as a dedicated service account (var.service_account_email) rather than the default Compute Engine service account.",
        clouds=("gcp",),
        level="advisory",
        frameworks=_frameworks(cis=["GCP 4.1"], soc2=["CC6.1", "CC6.3"], hipaa=["164.308(a)(3)(i)", "164.308(a)(4)(ii)(B)"]),
        remediation="Create a service account with least-privilege roles and set var.service_account_email; empty keeps the default Compute Engine account with limited scopes.",
    ),
    Control(
        id="GCP-SUBNET-FLOW-LOGS",
        title="Subnetwork flow logs enabled",
        description="google_compute_subnetwork declares a log_config block so VPC flow logs are captured.",
        clouds=("gcp",),
        level="enforce",
        frameworks=_frameworks(cis=["GCP 3.8"], soc2=_SOC2_MONITORING, hipaa=_HIPAA_AUDIT),
        remediation="Add log_config { aggregation_interval = \"INTERVAL_5_SEC\" flow_sampling = 0.5 metadata = \"INCLUDE_ALL_METADATA\" } to each subnetwork.",
    ),
    Control(
        id="GCP-SUBNET-PRIVATE-GOOGLE-ACCESS",
        title="Private Google Access enabled",
        description="google_compute_subnetwork sets private_ip_google_access = true so instances without external IPs reach Google APIs privately.",
        clouds=("gcp",),
        level="enforce",
        frameworks=_frameworks(soc2=_SOC2_ACCESS, hipaa=["164.312(e)(1)"]),
        remediation="Set private_ip_google_access = true on each subnetwork.",
    ),
    Control(
        id="GCP-FW-NO-OPEN-MGMT-PORTS",
        title="No SSH/RDP from the internet in firewall rules",
        description="Ingress google_compute_firewall rules with source 0.0.0.0/0 or ::/0 never allow TCP 22 or 3389.",
        clouds=("gcp",),
        level="enforce",
        frameworks=_frameworks(cis=["GCP 3.6", "GCP 3.7"], soc2=_SOC2_ACCESS, hipaa=_HIPAA_ACCESS),
        remediation="Restrict source_ranges to internal or corporate ranges, or use IAP TCP forwarding (35.235.240.0/20).",
    ),
    Control(
        id="GCP-DISK-CMEK",
        title="Persistent disks use customer-managed keys",
        description="google_compute_disk declares disk_encryption_key.kms_key_self_link (var.default_kms_key_self_link) so data is encrypted with an organisation-controlled key.",
        clouds=("gcp",),
        level="advisory",
        frameworks=_frameworks(cis=["GCP 4.7"], soc2=_SOC2_ENCRYPTION, hipaa=_HIPAA_ENCRYPTION),
        remediation="Create a Cloud KMS key, grant the Compute Engine service agent the encrypter/decrypter role and set var.default_kms_key_self_link.",
    ),
    # ── OpenStack ─────────────────────────────────────────────────────────────
    Control(
        id="OS-SG-NO-OPEN-MGMT-PORTS",
        title="No SSH/RDP from the internet in security group rules",
        description="Ingress openstack_networking_secgroup_rule_v2 rules with remote_ip_prefix 0.0.0.0/0 or ::/0 never cover port 22 or 3389.",
        clouds=("openstack",),
        level="enforce",
        frameworks=_frameworks(soc2=_SOC2_ACCESS, hipaa=_HIPAA_ACCESS),
        remediation="Set remote_ip_prefix to an internal range or use remote_group_id for east-west traffic.",
    ),
    Control(
        id="OS-VOLUME-ENCRYPTED-TYPE",
        title="Volumes use an encryption-backed volume type",
        description="openstack_blockstorage_volume_v3 uses a volume_type that is backed by a Cinder encryption provider; types are opaque names, so this can only be confirmed by name or variable default.",
        clouds=("openstack",),
        level="advisory",
        frameworks=_frameworks(soc2=_SOC2_ENCRYPTION, hipaa=_HIPAA_ENCRYPTION),
        remediation="Ask the cloud operator for the LUKS-backed volume type and set var.encrypted_volume_type to it.",
    ),
)

CONTROLS_BY_ID: dict[str, Control] = {control.id: control for control in CONTROLS}


def get_control(control_id: str) -> Control | None:
    return CONTROLS_BY_ID.get(control_id)


def controls_for_cloud(cloud: str) -> list[Control]:
    normalized = cloud.strip().lower()
    return [control for control in CONTROLS if control.applies_to(normalized)]
