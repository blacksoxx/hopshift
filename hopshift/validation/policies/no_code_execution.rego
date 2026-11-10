# Generated Terraform must never execute code on the operator machine or fetch remote content.
# This duplicates the Python guard in hcl_generator as policy-as-code.
package hopshift

import rego.v1

deny contains msg if {
	some r in input.resources
	r.config.provisioner
	msg := sprintf("no_code_execution: %s declares a provisioner (%s)", [r.address, r.file])
}

deny contains msg if {
	some r in input.resources
	r.type in {"null_resource", "local_file", "local_sensitive_file"}
	msg := sprintf("no_code_execution: resource type %s is not allowed (%s)", [r.type, r.file])
}

deny contains msg if {
	some d in input.data_sources
	d.type in {"external", "http"}
	msg := sprintf("no_code_execution: data source %s is not allowed (%s)", [d.address, d.file])
}

deny contains msg if {
	some m in input.modules
	source := object.get(m.config, "source", "")
	not startswith(source, "./")
	msg := sprintf("no_code_execution: module %s uses a non-local source %q (%s)", [m.name, source, m.file])
}

deny contains msg if {
	some e in input.parse_errors
	msg := sprintf("structure: %s could not be parsed as HCL: %s", [e.file, e.error])
}
