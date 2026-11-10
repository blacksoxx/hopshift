# Deny ingress open to the whole internet, evaluated per resource on parsed HCL.
package hopshift

import rego.v1

open_cidrs := {"0.0.0.0/0", "::/0"}

azure_open_prefixes := {"*", "0.0.0.0/0", "::/0", "internet", "any"}

# ── AWS ───────────────────────────────────────────────────────────────────────

deny contains msg if {
	some r in input.resources
	r.type == "aws_security_group"
	some rule in object.get(r.config, "ingress", [])
	some cidr in array.concat(
		object.get(rule, "cidr_blocks", []),
		object.get(rule, "ipv6_cidr_blocks", []),
	)
	cidr in open_cidrs
	msg := sprintf("no_open_ingress: %s ingress allows %s (%s)", [r.address, cidr, r.file])
}

deny contains msg if {
	some r in input.resources
	r.type == "aws_security_group_rule"
	lower(object.get(r.config, "type", "")) == "ingress"
	some cidr in array.concat(
		object.get(r.config, "cidr_blocks", []),
		object.get(r.config, "ipv6_cidr_blocks", []),
	)
	cidr in open_cidrs
	msg := sprintf("no_open_ingress: %s allows %s (%s)", [r.address, cidr, r.file])
}

deny contains msg if {
	some r in input.resources
	r.type == "aws_vpc_security_group_ingress_rule"
	some attr in {"cidr_ipv4", "cidr_ipv6"}
	object.get(r.config, attr, "") in open_cidrs
	msg := sprintf("no_open_ingress: %s %s is open to the internet (%s)", [r.address, attr, r.file])
}

# ── Azure ─────────────────────────────────────────────────────────────────────

azure_rule_is_open(rule) if {
	lower(object.get(rule, "direction", "")) == "inbound"
	lower(object.get(rule, "access", "allow")) == "allow"
	some prefix in array.concat(
		[object.get(rule, "source_address_prefix", "")],
		object.get(rule, "source_address_prefixes", []),
	)
	lower(prefix) in azure_open_prefixes
}

deny contains msg if {
	some r in input.resources
	r.type == "azurerm_network_security_group"
	some rule in object.get(r.config, "security_rule", [])
	azure_rule_is_open(rule)
	msg := sprintf("no_open_ingress: %s has an inbound rule open to the internet (%s)", [r.address, r.file])
}

deny contains msg if {
	some r in input.resources
	r.type == "azurerm_network_security_rule"
	azure_rule_is_open(r.config)
	msg := sprintf("no_open_ingress: %s is an inbound rule open to the internet (%s)", [r.address, r.file])
}

# ── GCP ───────────────────────────────────────────────────────────────────────

deny contains msg if {
	some r in input.resources
	r.type == "google_compute_firewall"
	lower(object.get(r.config, "direction", "INGRESS")) == "ingress"
	count(object.get(r.config, "allow", [])) > 0
	some src in object.get(r.config, "source_ranges", [])
	src in open_cidrs
	msg := sprintf("no_open_ingress: %s allows ingress from %s (%s)", [r.address, src, r.file])
}

# ── OpenStack ─────────────────────────────────────────────────────────────────

deny contains msg if {
	some r in input.resources
	r.type == "openstack_networking_secgroup_rule_v2"
	lower(object.get(r.config, "direction", "ingress")) == "ingress"
	object.get(r.config, "remote_ip_prefix", "") in open_cidrs
	msg := sprintf("no_open_ingress: %s allows ingress from the internet (%s)", [r.address, r.file])
}

# ── Proxmox VE ────────────────────────────────────────────────────────────────
# Firewall rule sources are comma-separated lists; an empty source matches every address.

proxmox_source_is_open(spec) if {
	spec == ""
}

proxmox_source_is_open(spec) if {
	is_string(spec)
	some part in split(spec, ",")
	trim_space(part) in open_cidrs
}

deny contains msg if {
	some r in input.resources
	r.type == "proxmox_virtual_environment_firewall_rules"
	some rule in object.get(r.config, "rule", [])
	lower(object.get(rule, "type", "")) == "in"
	upper(object.get(rule, "action", "")) == "ACCEPT"
	proxmox_source_is_open(object.get(rule, "source", ""))
	msg := sprintf("no_open_ingress: %s accepts inbound traffic from the internet (%s)", [r.address, r.file])
}
