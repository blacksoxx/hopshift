# Deny publicly readable object storage on every provider (file name kept for CI checks).
package vmwaremigration

import rego.v1

public_acls := {"public-read", "public-read-write", "authenticated-read"}

public_principals := {"allUsers", "allAuthenticatedUsers"}

# ── AWS S3 ────────────────────────────────────────────────────────────────────

deny contains msg if {
	some r in input.resources
	r.type in {"aws_s3_bucket", "aws_s3_bucket_acl"}
	object.get(r.config, "acl", "") in public_acls
	msg := sprintf("no_public_s3: %s uses public ACL %s (%s)", [r.address, r.config.acl, r.file])
}

deny contains msg if {
	some r in input.resources
	r.type == "aws_s3_bucket_public_access_block"
	some flag in {"block_public_acls", "block_public_policy", "ignore_public_acls", "restrict_public_buckets"}
	object.get(r.config, flag, true) == false
	msg := sprintf("no_public_s3: %s sets %s = false (%s)", [r.address, flag, r.file])
}

deny contains msg if {
	some r in input.resources
	r.type == "aws_s3_bucket_policy"
	policy := object.get(r.config, "policy", "")
	is_string(policy)
	regex.match(`"Principal"\s*:\s*"\*"`, policy)
	msg := sprintf("no_public_s3: %s grants access to Principal * (%s)", [r.address, r.file])
}

# ── GCP Cloud Storage ─────────────────────────────────────────────────────────

deny contains msg if {
	some r in input.resources
	r.type in {"google_storage_bucket_iam_member", "google_storage_bucket_iam_binding", "google_storage_bucket_access_control", "google_storage_default_object_access_control"}
	some member in array.concat(
		[object.get(r.config, "member", ""), object.get(r.config, "entity", "")],
		object.get(r.config, "members", []),
	)
	member in public_principals
	msg := sprintf("no_public_s3: %s grants %s (%s)", [r.address, member, r.file])
}

# ── Azure Blob Storage ────────────────────────────────────────────────────────

deny contains msg if {
	some r in input.resources
	r.type == "azurerm_storage_container"
	lower(object.get(r.config, "container_access_type", "private")) in {"blob", "container"}
	msg := sprintf("no_public_s3: %s allows anonymous blob access (%s)", [r.address, r.file])
}

deny contains msg if {
	some r in input.resources
	r.type == "azurerm_storage_account"
	# azurerm 4.x defaults this to true, so it must be set to false explicitly.
	object.get(r.config, "allow_nested_items_to_be_public", true) != false
	msg := sprintf("no_public_s3: %s must set allow_nested_items_to_be_public = false (%s)", [r.address, r.file])
}
