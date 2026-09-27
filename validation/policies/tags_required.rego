# Every taggable resource must carry Environment, Owner and MigratedFrom (lowercase for GCP labels).
package vmwaremigration

import rego.v1

# resource type -> attribute holding the metadata map
tag_attribute := {
	"aws_instance": "tags",
	"aws_vpc": "tags",
	"aws_subnet": "tags",
	"aws_security_group": "tags",
	"aws_ebs_volume": "tags",
	"aws_placement_group": "tags",
	"aws_s3_bucket": "tags",
	"aws_internet_gateway": "tags",
	"aws_nat_gateway": "tags",
	"aws_route_table": "tags",
	"aws_eip": "tags",
	"azurerm_virtual_network": "tags",
	"azurerm_network_interface": "tags",
	"azurerm_linux_virtual_machine": "tags",
	"azurerm_windows_virtual_machine": "tags",
	"azurerm_managed_disk": "tags",
	"azurerm_network_security_group": "tags",
	"azurerm_availability_set": "tags",
	"azurerm_proximity_placement_group": "tags",
	"azurerm_public_ip": "tags",
	"azurerm_storage_account": "tags",
	"google_compute_instance": "labels",
	"google_compute_disk": "labels",
	"openstack_compute_instance_v2": "metadata",
	"openstack_blockstorage_volume_v3": "metadata",
}

required_keys := {
	"tags": {"Environment", "Owner", "MigratedFrom"},
	"labels": {"environment", "owner", "migrated_from"},
	"metadata": {"Environment", "Owner", "MigratedFrom"},
}

# Metadata built from a shared map (merge(var.common_tags, ...), local.tags) cannot be checked
# statically; accept it when it references a variables/locals map, deny anything else.
acceptable_expression(value) if {
	is_string(value)
	startswith(value, "${")
	some marker in {"common_tags", "common_labels", "var.", "local."}
	contains(value, marker)
}

deny contains msg if {
	some r in input.resources
	attr := tag_attribute[r.type]
	not r.config[attr]
	msg := sprintf("tags_required: %s has no %s (%s)", [r.address, attr, r.file])
}

deny contains msg if {
	some r in input.resources
	attr := tag_attribute[r.type]
	value := r.config[attr]
	is_object(value)
	some key in required_keys[attr]
	not value[key]
	msg := sprintf("tags_required: %s %s missing %s (%s)", [r.address, attr, key, r.file])
}

deny contains msg if {
	some r in input.resources
	attr := tag_attribute[r.type]
	value := r.config[attr]
	is_string(value)
	not acceptable_expression(value)
	msg := sprintf("tags_required: %s %s must be a map with the required keys (%s)", [r.address, attr, r.file])
}

# OpenStack networks carry a list of "Key=Value" tags.
deny contains msg if {
	some r in input.resources
	r.type == "openstack_networking_network_v2"
	tags := object.get(r.config, "tags", [])
	some key in {"Environment", "Owner", "MigratedFrom"}
	not some_tag_with_prefix(tags, sprintf("%s=", [key]))
	msg := sprintf("tags_required: %s tags list missing %s= (%s)", [r.address, key, r.file])
}

some_tag_with_prefix(tags, prefix) if {
	some tag in tags
	is_string(tag)
	startswith(tag, prefix)
}
