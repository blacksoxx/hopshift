# Compliance-as-code: shared plumbing for the per-cloud control files in this directory.
#
# Every control emits `violations` entries shaped as
#   {"control": "<id>", "level": "enforce" | "advisory", "resource": <address>, "file": <path>, "message": "..."}
# Enforce-level violations are also surfaced as `deny` messages so the existing gate
# (validation.opa_client collects every `deny` set under data) fails without any change to
# how denies are collected. Advisory violations are reported only.
#
# `evaluated` lists the control ids that apply to the input, derived from the cloud(s) whose
# provider types are present; `controls` maps every known control id to its level so the
# Python catalog (hopshift/services/compliance/controls.py) can be checked against the policy bundle.
package hopshift.compliance

import rego.v1

# ── cloud detection ───────────────────────────────────────────────────────────

clouds contains "aws" if {
	some r in input.resources
	startswith(r.type, "aws_")
}

clouds contains "aws" if {
	some p in input.providers
	p.name == "aws"
}

clouds contains "aws" if {
	some p in input.required_providers
	p.source == "hashicorp/aws"
}

clouds contains "azure" if {
	some r in input.resources
	startswith(r.type, "azurerm_")
}

clouds contains "azure" if {
	some p in input.providers
	p.name == "azurerm"
}

clouds contains "azure" if {
	some p in input.required_providers
	p.source == "hashicorp/azurerm"
}

clouds contains "gcp" if {
	some r in input.resources
	startswith(r.type, "google_")
}

clouds contains "gcp" if {
	some p in input.providers
	p.name in {"google", "google-beta"}
}

clouds contains "gcp" if {
	some p in input.required_providers
	p.source in {"hashicorp/google", "hashicorp/google-beta"}
}

clouds contains "openstack" if {
	some r in input.resources
	startswith(r.type, "openstack_")
}

clouds contains "openstack" if {
	some p in input.providers
	p.name == "openstack"
}

clouds contains "openstack" if {
	some p in input.required_providers
	p.source == "terraform-provider-openstack/openstack"
}

# ── catalog ───────────────────────────────────────────────────────────────────

common_controls := {"ALL-TAGS-REQUIRED": "enforce"}

controls := object.union_n([common_controls, aws_controls, azure_controls, gcp_controls, openstack_controls])

evaluated contains id if {
	count(clouds) > 0
	some id, _ in common_controls
}

# ── helpers shared by the cloud files ─────────────────────────────────────────

violation(control, level, r, message) := {
	"control": control,
	"level": level,
	"resource": r.address,
	"file": r.file,
	"message": message,
}

# Account/project-level findings are anchored on the provider block when there is one.
provider_anchor(name) := {"address": sprintf("provider.%s", [name]), "file": p.file} if {
	some p in input.providers
	p.name == name
} else := {"address": sprintf("provider.%s", [name]), "file": ""}

open_cidrs := {"0.0.0.0/0", "::/0"}

management_ports := {22, 3389}

# True when a Terraform port specification ("22", "22-23", "*", 22) covers `port`.
port_spec_covers(spec, port) if {
	spec == "*"
}

port_spec_covers(spec, port) if {
	is_number(spec)
	spec == port
}

port_spec_covers(spec, port) if {
	is_string(spec)
	spec == sprintf("%d", [port])
}

port_spec_covers(spec, port) if {
	is_string(spec)
	parts := split(spec, "-")
	count(parts) == 2
	to_number(trim_space(parts[0])) <= port
	port <= to_number(trim_space(parts[1]))
}

# A ${...} expression that references a module variable whose default is a non-empty string.
expression_backed_by_variable_default(value, variable_name) if {
	is_string(value)
	startswith(value, "${")
	contains(value, sprintf("var.%s", [variable_name]))
	some v in input.variables
	v.name == variable_name
	default_value := object.get(v.config, "default", "")
	is_string(default_value)
	trim_space(default_value) != ""
}

# ── gate ──────────────────────────────────────────────────────────────────────

deny contains msg if {
	some v in violations
	v.level == "enforce"
	msg := sprintf("compliance %s: %s (%s)", [v.control, v.message, v.resource])
}

# ── ALL-TAGS-REQUIRED ─────────────────────────────────────────────────────────
# Mirrors hopshift/validation/policies/tags_required.rego (the gate rule stays there); the control
# gives the requirement an id, a level and framework references for the report. Resource
# types added by the hardened renderers are appended to the shared table.

tag_attribute := object.union(
	data.hopshift.tag_attribute,
	{"aws_default_security_group": "tags", "aws_flow_log": "tags"},
)

required_keys := data.hopshift.required_keys

violations contains v if {
	some r in input.resources
	attr := tag_attribute[r.type]
	not r.config[attr]
	v := violation("ALL-TAGS-REQUIRED", common_controls["ALL-TAGS-REQUIRED"], r, sprintf("has no %s", [attr]))
}

violations contains v if {
	some r in input.resources
	attr := tag_attribute[r.type]
	value := r.config[attr]
	is_object(value)
	some key in required_keys[attr]
	not value[key]
	v := violation("ALL-TAGS-REQUIRED", common_controls["ALL-TAGS-REQUIRED"], r, sprintf("%s missing %s", [attr, key]))
}

violations contains v if {
	some r in input.resources
	attr := tag_attribute[r.type]
	value := r.config[attr]
	is_string(value)
	not data.hopshift.acceptable_expression(value)
	v := violation("ALL-TAGS-REQUIRED", common_controls["ALL-TAGS-REQUIRED"], r, sprintf("%s must be a map with the required keys", [attr]))
}

violations contains v if {
	some r in input.resources
	r.type == "openstack_networking_network_v2"
	tags := object.get(r.config, "tags", [])
	some key in {"Environment", "Owner", "MigratedFrom"}
	not data.hopshift.some_tag_with_prefix(tags, sprintf("%s=", [key]))
	v := violation("ALL-TAGS-REQUIRED", common_controls["ALL-TAGS-REQUIRED"], r, sprintf("tags list missing %s=", [key]))
}
