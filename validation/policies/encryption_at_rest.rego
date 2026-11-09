# Enforce encryption at rest per storage resource on parsed HCL.
package vmwaremigration

import rego.v1

# ── AWS ───────────────────────────────────────────────────────────────────────

deny contains msg if {
	some r in input.resources
	r.type == "aws_ebs_volume"
	object.get(r.config, "encrypted", false) != true
	msg := sprintf("encryption_at_rest: %s must set encrypted = true (%s)", [r.address, r.file])
}

deny contains msg if {
	some r in input.resources
	r.type == "aws_instance"
	count(object.get(r.config, "root_block_device", [])) == 0
	msg := sprintf("encryption_at_rest: %s must declare root_block_device { encrypted = true } (%s)", [r.address, r.file])
}

deny contains msg if {
	some r in input.resources
	r.type == "aws_instance"
	some block_name in {"root_block_device", "ebs_block_device"}
	some device in object.get(r.config, block_name, [])
	object.get(device, "encrypted", false) != true
	msg := sprintf("encryption_at_rest: %s %s must set encrypted = true (%s)", [r.address, block_name, r.file])
}

# ── Azure ─────────────────────────────────────────────────────────────────────

deny contains msg if {
	some r in input.resources
	r.type == "azurerm_managed_disk"
	object.get(r.config, "encryption_settings_enabled", true) == false
	msg := sprintf("encryption_at_rest: %s disables encryption (%s)", [r.address, r.file])
}

# ── OpenStack ─────────────────────────────────────────────────────────────────

deny contains msg if {
	some r in input.resources
	r.type == "openstack_blockstorage_volume_v3"
	object.get(r.config, "volume_type", "") == ""
	msg := sprintf("encryption_at_rest: %s must use an encrypted volume_type (%s)", [r.address, r.file])
}
