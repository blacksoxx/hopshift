# Azure compliance controls (CIS Microsoft Azure Foundations Benchmark v3.0 references).
package hopshift.compliance

import rego.v1

azure_controls := {
	"AZ-NIC-NO-PUBLIC-IP": "enforce",
	"AZ-NSG-NO-OPEN-MGMT-PORTS": "enforce",
	"AZ-STORAGE-SECURE-TRANSPORT": "enforce",
	"AZ-STORAGE-NO-PUBLIC-ACCESS": "enforce",
	"AZ-VM-ENCRYPTION-AT-HOST": "advisory",
	"AZ-VM-BOOT-DIAGNOSTICS": "advisory",
	"AZ-DISK-CMK": "advisory",
	"AZ-NSG-FLOW-LOGS": "advisory",
}

evaluated contains id if {
	"azure" in clouds
	some id, _ in azure_controls
}

azure_violation(id, r, message) := violation(id, azure_controls[id], r, message)

azure_vm_types := {"azurerm_linux_virtual_machine", "azurerm_windows_virtual_machine", "azurerm_virtual_machine"}

azure_open_prefixes := {"*", "0.0.0.0/0", "::/0", "internet", "any"}

# ── AZ-NIC-NO-PUBLIC-IP ───────────────────────────────────────────────────────

violations contains v if {
	some r in input.resources
	r.type == "azurerm_network_interface"
	some ip_configuration in object.get(r.config, "ip_configuration", [])
	object.get(ip_configuration, "public_ip_address_id", null) != null
	v := azure_violation("AZ-NIC-NO-PUBLIC-IP", r, "ip_configuration attaches a public IP (public_ip_address_id)")
}

# ── AZ-NSG-NO-OPEN-MGMT-PORTS (CIS 7.1 RDP / 7.2 SSH) ─────────────────────────

nsg_rule_sources(rule) := array.concat(
	[object.get(rule, "source_address_prefix", "")],
	object.get(rule, "source_address_prefixes", []),
)

nsg_rule_destination_ports(rule) := array.concat(
	[object.get(rule, "destination_port_range", "")],
	object.get(rule, "destination_port_ranges", []),
)

nsg_rule_opens_management_port(rule, port) if {
	lower(object.get(rule, "direction", "")) == "inbound"
	lower(object.get(rule, "access", "allow")) == "allow"
	not lower(object.get(rule, "protocol", "Tcp")) in {"udp", "icmp"}
	some prefix in nsg_rule_sources(rule)
	lower(prefix) in azure_open_prefixes
	some spec in nsg_rule_destination_ports(rule)
	port_spec_covers(spec, port)
}

violations contains v if {
	some r in input.resources
	r.type == "azurerm_network_security_group"
	some rule in object.get(r.config, "security_rule", [])
	some port in management_ports
	nsg_rule_opens_management_port(rule, port)
	v := azure_violation("AZ-NSG-NO-OPEN-MGMT-PORTS", r, sprintf("security_rule %q allows inbound port %d from the internet", [object.get(rule, "name", ""), port]))
}

violations contains v if {
	some r in input.resources
	r.type == "azurerm_network_security_rule"
	some port in management_ports
	nsg_rule_opens_management_port(r.config, port)
	v := azure_violation("AZ-NSG-NO-OPEN-MGMT-PORTS", r, sprintf("allows inbound port %d from the internet", [port]))
}

# ── AZ-STORAGE-SECURE-TRANSPORT (CIS 4.1 / 4.15) ──────────────────────────────

violations contains v if {
	some r in input.resources
	r.type == "azurerm_storage_account"
	not object.get(r.config, "min_tls_version", "") in {"TLS1_2", "TLS1_3"}
	v := azure_violation("AZ-STORAGE-SECURE-TRANSPORT", r, "min_tls_version must be set to \"TLS1_2\" or newer")
}

violations contains v if {
	some r in input.resources
	r.type == "azurerm_storage_account"
	object.get(r.config, "https_traffic_only_enabled", object.get(r.config, "enable_https_traffic_only", null)) != true
	v := azure_violation("AZ-STORAGE-SECURE-TRANSPORT", r, "https_traffic_only_enabled must be set to true")
}

# ── AZ-STORAGE-NO-PUBLIC-ACCESS (CIS 4.6 / 4.17) ──────────────────────────────

violations contains v if {
	some r in input.resources
	r.type == "azurerm_storage_account"
	object.get(r.config, "allow_nested_items_to_be_public", null) != false
	v := azure_violation("AZ-STORAGE-NO-PUBLIC-ACCESS", r, "allow_nested_items_to_be_public must be set to false")
}

violations contains v if {
	some r in input.resources
	r.type == "azurerm_storage_account"
	object.get(r.config, "public_network_access_enabled", null) != false
	v := azure_violation("AZ-STORAGE-NO-PUBLIC-ACCESS", r, "public_network_access_enabled must be set to false")
}

# ── AZ-VM-ENCRYPTION-AT-HOST (CIS 8.9, advisory) ──────────────────────────────

violations contains v if {
	some r in input.resources
	r.type in azure_vm_types
	object.get(r.config, "encryption_at_host_enabled", false) != true
	v := azure_violation("AZ-VM-ENCRYPTION-AT-HOST", r, "encryption_at_host_enabled is not true (requires the EncryptionAtHost subscription feature)")
}

# ── AZ-VM-BOOT-DIAGNOSTICS (advisory) ─────────────────────────────────────────

violations contains v if {
	some r in input.resources
	r.type in azure_vm_types
	count(object.get(r.config, "boot_diagnostics", [])) == 0
	v := azure_violation("AZ-VM-BOOT-DIAGNOSTICS", r, "boot_diagnostics block is missing")
}

# ── AZ-DISK-CMK (CIS 8.3, advisory) ───────────────────────────────────────────

violations contains v if {
	some r in input.resources
	r.type == "azurerm_managed_disk"
	object.get(r.config, "disk_encryption_set_id", "") == ""
	v := azure_violation("AZ-DISK-CMK", r, "disk_encryption_set_id is not set; the disk uses platform-managed keys")
}

# ── AZ-NSG-FLOW-LOGS (CIS 7.6, advisory) ──────────────────────────────────────

flow_log_for_nsg(nsg) := fl if {
	some fl in input.resources
	fl.type == "azurerm_network_watcher_flow_log"
	some attr in {"network_security_group_id", "target_resource_id"}
	target := object.get(fl.config, attr, "")
	is_string(target)
	contains(target, sprintf("azurerm_network_security_group.%s.id", [nsg.name]))
}

violations contains v if {
	some r in input.resources
	r.type == "azurerm_network_security_group"
	not flow_log_for_nsg(r)
	v := azure_violation("AZ-NSG-FLOW-LOGS", r, "no azurerm_network_watcher_flow_log targets this network security group")
}
