# GCP compliance controls (CIS Google Cloud Platform Foundation Benchmark v3.0 references).
package vmwaremigration.compliance

import rego.v1

gcp_controls := {
	"GCP-VM-NO-EXTERNAL-IP": "enforce",
	"GCP-VM-SHIELDED": "enforce",
	"GCP-VM-OSLOGIN": "enforce",
	"GCP-VM-SERIAL-PORT-DISABLED": "enforce",
	"GCP-VM-BLOCK-PROJECT-SSH-KEYS": "enforce",
	"GCP-VM-NO-IP-FORWARD": "enforce",
	"GCP-VM-LIMITED-SCOPES": "enforce",
	"GCP-SUBNET-FLOW-LOGS": "enforce",
	"GCP-SUBNET-PRIVATE-GOOGLE-ACCESS": "enforce",
	"GCP-FW-NO-OPEN-MGMT-PORTS": "enforce",
	"GCP-VM-DEDICATED-SA": "advisory",
	"GCP-DISK-CMEK": "advisory",
}

evaluated contains id if {
	"gcp" in clouds
	some id, _ in gcp_controls
}

gcp_violation(id, r, message) := violation(id, gcp_controls[id], r, message)

truthy_metadata := {"TRUE", "1", "Y", "YES"}

# ── GCP-VM-NO-EXTERNAL-IP (CIS 4.9) ───────────────────────────────────────────

violations contains v if {
	some r in input.resources
	r.type == "google_compute_instance"
	some network_interface in object.get(r.config, "network_interface", [])
	some block_name in {"access_config", "ipv6_access_config"}
	count(object.get(network_interface, block_name, [])) > 0
	v := gcp_violation("GCP-VM-NO-EXTERNAL-IP", r, sprintf("network_interface declares %s (external IP)", [block_name]))
}

# ── GCP-VM-SHIELDED (CIS 4.8) ─────────────────────────────────────────────────

violations contains v if {
	some r in input.resources
	r.type == "google_compute_instance"
	count(object.get(r.config, "shielded_instance_config", [])) == 0
	v := gcp_violation("GCP-VM-SHIELDED", r, "shielded_instance_config block is missing")
}

violations contains v if {
	some r in input.resources
	r.type == "google_compute_instance"
	some shielded in object.get(r.config, "shielded_instance_config", [])
	some flag in {"enable_secure_boot", "enable_vtpm", "enable_integrity_monitoring"}
	object.get(shielded, flag, false) != true
	v := gcp_violation("GCP-VM-SHIELDED", r, sprintf("shielded_instance_config.%s must be true", [flag]))
}

# ── instance metadata helpers ─────────────────────────────────────────────────

instance_metadata(r) := metadata if {
	metadata := object.get(r.config, "metadata", {})
	is_object(metadata)
}

# Always defined when the metadata is a literal map ("" for a missing key) so it can be used
# inside negated membership tests; nested calls in `not` are hoisted and must not be undefined.
metadata_flag(r, key) := upper(trim_space(sprintf("%v", [object.get(instance_metadata(r), key, "")])))

# ── GCP-VM-OSLOGIN (CIS 4.4) ──────────────────────────────────────────────────

violations contains v if {
	some r in input.resources
	r.type == "google_compute_instance"
	not instance_metadata(r)
	v := gcp_violation("GCP-VM-OSLOGIN", r, "metadata must be a literal map so enable-oslogin can be verified")
}

violations contains v if {
	some r in input.resources
	r.type == "google_compute_instance"
	instance_metadata(r)
	not metadata_flag(r, "enable-oslogin") in truthy_metadata
	v := gcp_violation("GCP-VM-OSLOGIN", r, "metadata enable-oslogin must be \"TRUE\"")
}

# ── GCP-VM-SERIAL-PORT-DISABLED (CIS 4.5) ─────────────────────────────────────

violations contains v if {
	some r in input.resources
	r.type == "google_compute_instance"
	metadata_flag(r, "serial-port-enable") in truthy_metadata
	v := gcp_violation("GCP-VM-SERIAL-PORT-DISABLED", r, "metadata serial-port-enable must be \"FALSE\" or absent")
}

# ── GCP-VM-BLOCK-PROJECT-SSH-KEYS (CIS 4.3) ───────────────────────────────────

violations contains v if {
	some r in input.resources
	r.type == "google_compute_instance"
	instance_metadata(r)
	not metadata_flag(r, "block-project-ssh-keys") in truthy_metadata
	v := gcp_violation("GCP-VM-BLOCK-PROJECT-SSH-KEYS", r, "metadata block-project-ssh-keys must be \"TRUE\"")
}

# ── GCP-VM-NO-IP-FORWARD (CIS 4.6) ────────────────────────────────────────────

violations contains v if {
	some r in input.resources
	r.type == "google_compute_instance"
	object.get(r.config, "can_ip_forward", false) != false
	v := gcp_violation("GCP-VM-NO-IP-FORWARD", r, "can_ip_forward must be false")
}

# ── GCP-VM-LIMITED-SCOPES (CIS 4.2) ───────────────────────────────────────────

violations contains v if {
	some r in input.resources
	r.type == "google_compute_instance"
	count(object.get(r.config, "service_account", [])) == 0
	v := gcp_violation("GCP-VM-LIMITED-SCOPES", r, "service_account block with explicit, limited scopes is missing")
}

violations contains v if {
	some r in input.resources
	r.type == "google_compute_instance"
	some service_account in object.get(r.config, "service_account", [])
	scopes := object.get(service_account, "scopes", [])
	not is_array(scopes)
	v := gcp_violation("GCP-VM-LIMITED-SCOPES", r, "service_account.scopes must be a literal list")
}

violations contains v if {
	some r in input.resources
	r.type == "google_compute_instance"
	some service_account in object.get(r.config, "service_account", [])
	some scope in object.get(service_account, "scopes", [])
	contains(lower(scope), "cloud-platform")
	v := gcp_violation("GCP-VM-LIMITED-SCOPES", r, "service_account.scopes grants cloud-platform (full API access)")
}

# ── GCP-VM-DEDICATED-SA (CIS 4.1, advisory) ───────────────────────────────────

uses_dedicated_service_account(service_account) if {
	email := object.get(service_account, "email", "")
	is_string(email)
	email != ""
	not startswith(email, "${")
	not endswith(email, "-compute@developer.gserviceaccount.com")
}

uses_dedicated_service_account(service_account) if {
	email := object.get(service_account, "email", "")
	expression_backed_by_variable_default(email, "service_account_email")
}

violations contains v if {
	some r in input.resources
	r.type == "google_compute_instance"
	count(object.get(r.config, "service_account", [])) == 0
	v := gcp_violation("GCP-VM-DEDICATED-SA", r, "no service_account block; the instance runs as the default Compute Engine service account")
}

violations contains v if {
	some r in input.resources
	r.type == "google_compute_instance"
	some service_account in object.get(r.config, "service_account", [])
	not uses_dedicated_service_account(service_account)
	v := gcp_violation("GCP-VM-DEDICATED-SA", r, "service_account.email is empty or the default Compute Engine service account; set var.service_account_email to a dedicated service account")
}

# ── GCP-SUBNET-FLOW-LOGS (CIS 3.8) ────────────────────────────────────────────

violations contains v if {
	some r in input.resources
	r.type == "google_compute_subnetwork"
	count(object.get(r.config, "log_config", [])) == 0
	v := gcp_violation("GCP-SUBNET-FLOW-LOGS", r, "log_config block (VPC flow logs) is missing")
}

# ── GCP-SUBNET-PRIVATE-GOOGLE-ACCESS ──────────────────────────────────────────

violations contains v if {
	some r in input.resources
	r.type == "google_compute_subnetwork"
	object.get(r.config, "private_ip_google_access", false) != true
	v := gcp_violation("GCP-SUBNET-PRIVATE-GOOGLE-ACCESS", r, "private_ip_google_access must be true")
}

# ── GCP-FW-NO-OPEN-MGMT-PORTS (CIS 3.6 SSH / 3.7 RDP) ─────────────────────────

firewall_allow_covers_port(allow, port) if {
	lower(object.get(allow, "protocol", "")) in {"tcp", "all"}
	ports := object.get(allow, "ports", [])
	count(ports) == 0
}

firewall_allow_covers_port(allow, port) if {
	lower(object.get(allow, "protocol", "")) in {"tcp", "all"}
	some spec in object.get(allow, "ports", [])
	port_spec_covers(spec, port)
}

violations contains v if {
	some r in input.resources
	r.type == "google_compute_firewall"
	lower(object.get(r.config, "direction", "INGRESS")) == "ingress"
	some src in object.get(r.config, "source_ranges", [])
	src in open_cidrs
	some allow in object.get(r.config, "allow", [])
	some port in management_ports
	firewall_allow_covers_port(allow, port)
	v := gcp_violation("GCP-FW-NO-OPEN-MGMT-PORTS", r, sprintf("allows port %d from %s", [port, src]))
}

# ── GCP-DISK-CMEK (CIS 4.7, advisory) ─────────────────────────────────────────

disk_uses_cmek(disk) if {
	some key in object.get(disk.config, "disk_encryption_key", [])
	object.get(key, "kms_key_self_link", "") != ""
}

disk_uses_cmek(disk) if {
	some dynamic in object.get(disk.config, "dynamic", [])
	block := dynamic.disk_encryption_key
	some content in object.get(block, "content", [])
	expression_backed_by_variable_default(object.get(content, "kms_key_self_link", ""), "default_kms_key_self_link")
}

violations contains v if {
	some r in input.resources
	r.type == "google_compute_disk"
	not disk_uses_cmek(r)
	v := gcp_violation("GCP-DISK-CMEK", r, "no customer-managed KMS key; the disk uses Google-managed encryption (set var.default_kms_key_self_link)")
}
