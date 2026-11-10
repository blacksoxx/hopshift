# Proxmox VE compliance controls (bpg/proxmox provider). CIS publishes no Proxmox benchmark; the
# SOC 2 / HIPAA references live in hopshift/services/compliance/controls.py.
package hopshift.compliance

import rego.v1

proxmox_controls := {
	"PVE-FW-NO-OPEN-MGMT-PORTS": "enforce",
	"PVE-VM-FIREWALL-ENABLED": "enforce",
	"PVE-VM-AGENT-ENABLED": "enforce",
	"PVE-VM-OWNERSHIP-TAGS": "enforce",
	"PVE-VM-NO-SERIAL-CONSOLE": "enforce",
	"PVE-DISK-ENCRYPTION": "advisory",
	"PVE-VM-SECURE-BOOT": "advisory",
	"PVE-HA-ENABLED": "advisory",
}

evaluated contains id if {
	"proxmox" in clouds
	some id, _ in proxmox_controls
}

proxmox_violation(id, r, message) := violation(id, proxmox_controls[id], r, message)

pve_vm := "proxmox_virtual_environment_vm"

# A value that designates the VM: the expression ${proxmox_virtual_environment_vm.<name>.vm_id} (or
# "vm:${...}") rendered by the module, or the literal vm_id when both sides pin one.
pve_references_vm(value, vm) if {
	is_string(value)
	contains(value, sprintf("%s.%s.", [vm.type, vm.name]))
}

pve_references_vm(value, vm) if {
	is_number(value)
	value == object.get(vm.config, "vm_id", null)
}

# ── PVE-FW-NO-OPEN-MGMT-PORTS ─────────────────────────────────────────────────
# Proxmox firewall rules: `source` is a comma-separated list of addresses, CIDRs, aliases or ipsets
# and an empty source matches every address; `dport` accepts numbers, service names, ranges (22:25)
# and comma-separated lists; `macro` names a predefined service (SSH, RDP, ...).

pve_port_names := {"ssh": 22, "rdp": 3389, "ms-wbt-server": 3389}

pve_dport_part_covers(part, port) if {
	trim_space(part) == sprintf("%d", [port])
}

pve_dport_part_covers(part, port) if {
	bounds := split(part, ":")
	count(bounds) == 2
	to_number(trim_space(bounds[0])) <= port
	port <= to_number(trim_space(bounds[1]))
}

pve_dport_part_covers(part, port) if {
	pve_port_names[lower(trim_space(part))] == port
}

# No port and no macro means every port.
pve_rule_covers_port(rule, port) if {
	not rule.dport
	not rule.macro
}

pve_rule_covers_port(rule, port) if {
	spec := rule.dport
	is_string(spec)
	some part in split(spec, ",")
	pve_dport_part_covers(part, port)
}

pve_rule_covers_port(rule, port) if {
	spec := rule.dport
	is_number(spec)
	spec == port
}

pve_rule_covers_port(rule, port) if {
	upper(rule.macro) == "SSH"
	port == 22
}

pve_rule_covers_port(rule, port) if {
	upper(rule.macro) == "RDP"
	port == 3389
}

pve_range_list_is_restricted(parts) if {
	count(parts) > 0
	every part in parts {
		trimmed := trim_space(part)
		trimmed != ""
		not trimmed in open_cidrs
	}
}

# A literal source that names at least one range and no open one.
pve_source_is_restricted(spec) if {
	is_string(spec)
	not startswith(spec, "${")
	pve_range_list_is_restricted(split(spec, ","))
}

# An expression (join(",", var.management_cidrs)) backed by a variable whose default is restricted.
pve_source_is_restricted(spec) if {
	is_string(spec)
	startswith(spec, "${")
	some v in input.variables
	contains(spec, sprintf("var.%s", [v.name]))
	default_value := object.get(v.config, "default", null)
	is_array(default_value)
	pve_range_list_is_restricted(default_value)
}

pve_source_is_restricted(spec) if {
	is_string(spec)
	startswith(spec, "${")
	some v in input.variables
	contains(spec, sprintf("var.%s", [v.name]))
	default_value := object.get(v.config, "default", null)
	is_string(default_value)
	pve_range_list_is_restricted(split(default_value, ","))
}

violations contains v if {
	some r in input.resources
	r.type == "proxmox_virtual_environment_firewall_rules"
	some rule in object.get(r.config, "rule", [])
	lower(object.get(rule, "type", "")) == "in"
	upper(object.get(rule, "action", "")) == "ACCEPT"
	not lower(object.get(rule, "proto", "tcp")) in {"udp", "icmp"}
	some port in management_ports
	pve_rule_covers_port(rule, port)
	not pve_source_is_restricted(object.get(rule, "source", ""))
	v := proxmox_violation("PVE-FW-NO-OPEN-MGMT-PORTS", r, sprintf("rule %q accepts inbound port %d from the internet; restrict source to the management ranges", [object.get(rule, "comment", ""), port]))
}

# ── PVE-VM-FIREWALL-ENABLED ───────────────────────────────────────────────────
# The Proxmox VM firewall is off by default and only filters NICs that set firewall = true.

pve_vm_has_firewall_options(vm) if {
	some opts in input.resources
	opts.type == "proxmox_virtual_environment_firewall_options"
	pve_references_vm(object.get(opts.config, "vm_id", null), vm)
}

violations contains v if {
	some r in input.resources
	r.type == pve_vm
	not pve_vm_has_firewall_options(r)
	v := proxmox_violation("PVE-VM-FIREWALL-ENABLED", r, "has no proxmox_virtual_environment_firewall_options; the VM firewall is off and every inbound port is reachable")
}

violations contains v if {
	some r in input.resources
	r.type == "proxmox_virtual_environment_firewall_options"
	object.get(r.config, "enabled", false) != true
	v := proxmox_violation("PVE-VM-FIREWALL-ENABLED", r, "must set enabled = true")
}

violations contains v if {
	some r in input.resources
	r.type == "proxmox_virtual_environment_firewall_options"
	upper(object.get(r.config, "input_policy", "DROP")) == "ACCEPT"
	v := proxmox_violation("PVE-VM-FIREWALL-ENABLED", r, "input_policy must be DROP or REJECT so inbound traffic is denied by default")
}

violations contains v if {
	some r in input.resources
	r.type == pve_vm
	some index, nic in object.get(r.config, "network_device", [])
	object.get(nic, "firewall", false) != true
	v := proxmox_violation("PVE-VM-FIREWALL-ENABLED", r, sprintf("network_device net%d must set firewall = true, otherwise the VM firewall does not filter it", [index]))
}

# ── PVE-VM-AGENT-ENABLED ──────────────────────────────────────────────────────

pve_vm_agent_enabled(vm) if {
	some agent in object.get(vm.config, "agent", [])
	agent.enabled == true
}

violations contains v if {
	some r in input.resources
	r.type == pve_vm
	not pve_vm_agent_enabled(r)
	v := proxmox_violation("PVE-VM-AGENT-ENABLED", r, "agent { enabled = true } is missing; the QEMU guest agent is needed for clean shutdowns, IP reporting and consistent backups")
}

# ── PVE-VM-OWNERSHIP-TAGS ─────────────────────────────────────────────────────
# Proxmox tags are a list of lower-case strings; ownership is carried as env-*, owner-* and
# migratedfrom-* entries (ALL-TAGS-REQUIRED in common.rego mirrors the prefix check).

pve_required_tag_prefixes := {"env-", "owner-", "migratedfrom-"}

violations contains v if {
	some r in input.resources
	r.type == pve_vm
	tags := object.get(r.config, "tags", [])
	some prefix in pve_required_tag_prefixes
	not data.hopshift.some_tag_with_prefix(tags, prefix)
	v := proxmox_violation("PVE-VM-OWNERSHIP-TAGS", r, sprintf("tags list has no %s* tag", [prefix]))
}

violations contains v if {
	some r in input.resources
	r.type == pve_vm
	some tag in object.get(r.config, "tags", [])
	is_string(tag)
	not contains(tag, "${")
	not regex.match(`^[a-z0-9_.+-]+$`, tag)
	v := proxmox_violation("PVE-VM-OWNERSHIP-TAGS", r, sprintf("tag %q is not a lower-case Proxmox tag ([a-z0-9_.+-])", [tag]))
}

# ── PVE-VM-NO-SERIAL-CONSOLE ──────────────────────────────────────────────────

violations contains v if {
	some r in input.resources
	r.type == pve_vm
	count(object.get(r.config, "serial_device", [])) > 0
	v := proxmox_violation("PVE-VM-NO-SERIAL-CONSOLE", r, "declares a serial_device; the serial console bypasses the guest's network controls, remove it from migrated VMs")
}

# ── PVE-DISK-ENCRYPTION (advisory) ────────────────────────────────────────────
# Proxmox has no per-disk encryption flag: encryption is a property of the datastore (LUKS under
# LVM, ZFS native encryption, encrypted Ceph OSDs). Datastore ids are opaque names, so this can
# only be confirmed by name or by the variable default.

pve_datastore_looks_encrypted(value) if {
	is_string(value)
	not startswith(value, "${")
	regex.match(`(?i)(encrypt|luks|crypt)`, value)
}

pve_datastore_looks_encrypted(value) if {
	is_string(value)
	startswith(value, "${")
	some v in input.variables
	contains(value, sprintf("var.%s", [v.name]))
	default_value := object.get(v.config, "default", "")
	is_string(default_value)
	regex.match(`(?i)(encrypt|luks|crypt)`, default_value)
}

violations contains v if {
	some r in input.resources
	r.type == pve_vm
	some disk in object.get(r.config, "disk", [])
	datastore := object.get(disk, "datastore_id", "local-lvm")
	not pve_datastore_looks_encrypted(datastore)
	v := proxmox_violation("PVE-DISK-ENCRYPTION", r, sprintf("disk %s uses datastore %s, which cannot be confirmed as encrypted; place VM disks on a LUKS- or ZFS-encrypted datastore", [object.get(disk, "interface", "?"), datastore]))
}

# ── PVE-VM-SECURE-BOOT (advisory) ─────────────────────────────────────────────

pve_vm_uefi(vm) if {
	lower(object.get(vm.config, "bios", "seabios")) == "ovmf"
}

pve_vm_secure_efi_disk(vm) if {
	some efi in object.get(vm.config, "efi_disk", [])
	object.get(efi, "type", "2m") == "4m"
	object.get(efi, "pre_enrolled_keys", false) == true
}

violations contains v if {
	some r in input.resources
	r.type == pve_vm
	not pve_vm_uefi(r)
	v := proxmox_violation("PVE-VM-SECURE-BOOT", r, "boots with SeaBIOS; Secure Boot needs bios = \"ovmf\" with an efi_disk (type 4m, pre-enrolled keys) and a UEFI-capable guest")
}

violations contains v if {
	some r in input.resources
	r.type == pve_vm
	pve_vm_uefi(r)
	not pve_vm_secure_efi_disk(r)
	v := proxmox_violation("PVE-VM-SECURE-BOOT", r, "efi_disk must set type = \"4m\" and pre_enrolled_keys = true for Secure Boot")
}

violations contains v if {
	some r in input.resources
	r.type == pve_vm
	count(object.get(r.config, "tpm_state", [])) == 0
	v := proxmox_violation("PVE-VM-SECURE-BOOT", r, "has no tpm_state; add a vTPM 2.0 (tpm_state { version = \"v2.0\" }) for measured boot")
}

# ── PVE-HA-ENABLED (advisory) ─────────────────────────────────────────────────

pve_vm_is_ha_managed(vm) if {
	some ha in input.resources
	ha.type == "proxmox_virtual_environment_haresource"
	pve_references_vm(object.get(ha.config, "resource_id", ""), vm)
}

pve_vm_is_ha_managed(vm) if {
	some ha in input.resources
	ha.type == "proxmox_virtual_environment_haresource"
	object.get(ha.config, "resource_id", "") == sprintf("vm:%v", [object.get(vm.config, "vm_id", "")])
}

violations contains v if {
	some r in input.resources
	r.type == pve_vm
	not pve_vm_is_ha_managed(r)
	v := proxmox_violation("PVE-HA-ENABLED", r, "is not managed by Proxmox HA (no proxmox_virtual_environment_haresource references it); it does not restart on node failure")
}
