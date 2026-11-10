# OpenStack compliance controls. CIS publishes no OpenStack benchmark; the SOC 2 / HIPAA
# references live in hopshift/services/compliance/controls.py.
package hopshift.compliance

import rego.v1

openstack_controls := {
	"OS-SG-NO-OPEN-MGMT-PORTS": "enforce",
	"OS-VOLUME-ENCRYPTED-TYPE": "advisory",
}

evaluated contains id if {
	"openstack" in clouds
	some id, _ in openstack_controls
}

openstack_violation(id, r, message) := violation(id, openstack_controls[id], r, message)

# ── OS-SG-NO-OPEN-MGMT-PORTS ──────────────────────────────────────────────────

secgroup_rule_covers_port(rule, port) if {
	# No port range means every port.
	object.get(rule, "port_range_min", null) == null
	object.get(rule, "port_range_max", null) == null
}

secgroup_rule_covers_port(rule, port) if {
	low := object.get(rule, "port_range_min", 0)
	high := object.get(rule, "port_range_max", 65535)
	is_number(low)
	is_number(high)
	low <= port
	port <= high
}

violations contains v if {
	some r in input.resources
	r.type == "openstack_networking_secgroup_rule_v2"
	lower(object.get(r.config, "direction", "ingress")) == "ingress"
	object.get(r.config, "remote_ip_prefix", "") in open_cidrs
	not lower(object.get(r.config, "protocol", "tcp")) in {"udp", "icmp"}
	some port in management_ports
	secgroup_rule_covers_port(r.config, port)
	v := openstack_violation("OS-SG-NO-OPEN-MGMT-PORTS", r, sprintf("allows ingress on port %d from the internet", [port]))
}

# ── OS-VOLUME-ENCRYPTED-TYPE (advisory) ───────────────────────────────────────

volume_type_looks_encrypted(value) if {
	is_string(value)
	not startswith(value, "${")
	regex.match(`(?i)(encrypt|luks)`, value)
}

volume_type_looks_encrypted(value) if {
	is_string(value)
	startswith(value, "${")
	some variable in input.variables
	contains(value, sprintf("var.%s", [variable.name]))
	default_value := object.get(variable.config, "default", "")
	is_string(default_value)
	regex.match(`(?i)(encrypt|luks)`, default_value)
}

violations contains v if {
	some r in input.resources
	r.type == "openstack_blockstorage_volume_v3"
	not volume_type_looks_encrypted(object.get(r.config, "volume_type", ""))
	v := openstack_violation("OS-VOLUME-ENCRYPTED-TYPE", r, "volume_type cannot be confirmed as an encryption-backed Cinder type; verify it with the cloud operator")
}
