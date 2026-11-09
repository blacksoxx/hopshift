# AWS compliance controls (CIS Amazon Web Services Foundations Benchmark v3.0 references).
package vmwaremigration.compliance

import rego.v1

aws_controls := {
	"AWS-EC2-IMDSV2": "enforce",
	"AWS-EC2-NO-PUBLIC-IP": "enforce",
	"AWS-EC2-EBS-OPTIMIZED": "enforce",
	"AWS-EBS-ENCRYPTED": "enforce",
	"AWS-VPC-DEFAULT-SG-RESTRICTED": "enforce",
	"AWS-SG-NO-OPEN-INGRESS": "enforce",
	"AWS-VPC-FLOW-LOGS": "advisory",
	"AWS-EBS-ENCRYPTION-BY-DEFAULT": "advisory",
	"AWS-EC2-DETAILED-MONITORING": "advisory",
}

evaluated contains id if {
	"aws" in clouds
	some id, _ in aws_controls
}

aws_violation(id, r, message) := violation(id, aws_controls[id], r, message)

# ── AWS-EC2-IMDSV2 (CIS 5.6) ──────────────────────────────────────────────────

violations contains v if {
	some r in input.resources
	r.type == "aws_instance"
	count(object.get(r.config, "metadata_options", [])) == 0
	v := aws_violation("AWS-EC2-IMDSV2", r, "metadata_options block is missing; IMDSv2 must be required")
}

violations contains v if {
	some r in input.resources
	r.type == "aws_instance"
	some options in object.get(r.config, "metadata_options", [])
	object.get(options, "http_tokens", "optional") != "required"
	v := aws_violation("AWS-EC2-IMDSV2", r, "metadata_options.http_tokens must be \"required\"")
}

violations contains v if {
	some r in input.resources
	r.type == "aws_instance"
	some options in object.get(r.config, "metadata_options", [])
	object.get(options, "http_endpoint", "enabled") != "enabled"
	v := aws_violation("AWS-EC2-IMDSV2", r, "metadata_options.http_endpoint must be \"enabled\"")
}

violations contains v if {
	some r in input.resources
	r.type == "aws_instance"
	some options in object.get(r.config, "metadata_options", [])
	limit := object.get(options, "http_put_response_hop_limit", 1)
	is_number(limit)
	limit != 1
	v := aws_violation("AWS-EC2-IMDSV2", r, "metadata_options.http_put_response_hop_limit must be 1")
}

# ── AWS-EC2-NO-PUBLIC-IP ──────────────────────────────────────────────────────

violations contains v if {
	some r in input.resources
	r.type == "aws_instance"
	object.get(r.config, "associate_public_ip_address", null) != false
	v := aws_violation("AWS-EC2-NO-PUBLIC-IP", r, "associate_public_ip_address must be set to false")
}

violations contains v if {
	some r in input.resources
	r.type == "aws_eip"
	object.get(r.config, "instance", "") != ""
	v := aws_violation("AWS-EC2-NO-PUBLIC-IP", r, "Elastic IP must not be attached to a migrated instance")
}

violations contains v if {
	some r in input.resources
	r.type == "aws_eip_association"
	object.get(r.config, "instance_id", "") != ""
	v := aws_violation("AWS-EC2-NO-PUBLIC-IP", r, "Elastic IP must not be associated with a migrated instance")
}

# ── AWS-EC2-EBS-OPTIMIZED ─────────────────────────────────────────────────────

violations contains v if {
	some r in input.resources
	r.type == "aws_instance"
	object.get(r.config, "ebs_optimized", false) != true
	v := aws_violation("AWS-EC2-EBS-OPTIMIZED", r, "ebs_optimized must be true")
}

# ── AWS-EBS-ENCRYPTED (CIS 2.2.1) ─────────────────────────────────────────────

violations contains v if {
	some r in input.resources
	r.type == "aws_ebs_volume"
	object.get(r.config, "encrypted", false) != true
	v := aws_violation("AWS-EBS-ENCRYPTED", r, "encrypted must be true")
}

violations contains v if {
	some r in input.resources
	r.type == "aws_instance"
	count(object.get(r.config, "root_block_device", [])) == 0
	v := aws_violation("AWS-EBS-ENCRYPTED", r, "root_block_device { encrypted = true } must be declared")
}

violations contains v if {
	some r in input.resources
	r.type == "aws_instance"
	some block_name in {"root_block_device", "ebs_block_device"}
	some device in object.get(r.config, block_name, [])
	object.get(device, "encrypted", false) != true
	v := aws_violation("AWS-EBS-ENCRYPTED", r, sprintf("%s must set encrypted = true", [block_name]))
}

# ── AWS-VPC-DEFAULT-SG-RESTRICTED (CIS 5.4) ───────────────────────────────────

default_sg_for_vpc(vpc) := sg if {
	some sg in input.resources
	sg.type == "aws_default_security_group"
	vpc_id := object.get(sg.config, "vpc_id", "")
	is_string(vpc_id)
	contains(vpc_id, sprintf("aws_vpc.%s.id", [vpc.name]))
}

violations contains v if {
	some r in input.resources
	r.type == "aws_vpc"
	not default_sg_for_vpc(r)
	v := aws_violation("AWS-VPC-DEFAULT-SG-RESTRICTED", r, "no aws_default_security_group adopts this VPC's default security group")
}

violations contains v if {
	some r in input.resources
	r.type == "aws_default_security_group"
	some direction in {"ingress", "egress"}
	count(object.get(r.config, direction, [])) > 0
	v := aws_violation("AWS-VPC-DEFAULT-SG-RESTRICTED", r, sprintf("default security group must have no %s rules", [direction]))
}

# ── AWS-SG-NO-OPEN-INGRESS (CIS 5.2 / 5.3) ────────────────────────────────────

violations contains v if {
	some r in input.resources
	r.type == "aws_security_group"
	some rule in object.get(r.config, "ingress", [])
	some cidr in array.concat(
		object.get(rule, "cidr_blocks", []),
		object.get(rule, "ipv6_cidr_blocks", []),
	)
	cidr in open_cidrs
	v := aws_violation("AWS-SG-NO-OPEN-INGRESS", r, sprintf("ingress allows %s", [cidr]))
}

violations contains v if {
	some r in input.resources
	r.type == "aws_security_group_rule"
	lower(object.get(r.config, "type", "")) == "ingress"
	some cidr in array.concat(
		object.get(r.config, "cidr_blocks", []),
		object.get(r.config, "ipv6_cidr_blocks", []),
	)
	cidr in open_cidrs
	v := aws_violation("AWS-SG-NO-OPEN-INGRESS", r, sprintf("ingress rule allows %s", [cidr]))
}

violations contains v if {
	some r in input.resources
	r.type == "aws_vpc_security_group_ingress_rule"
	some attr in {"cidr_ipv4", "cidr_ipv6"}
	object.get(r.config, attr, "") in open_cidrs
	v := aws_violation("AWS-SG-NO-OPEN-INGRESS", r, sprintf("%s is open to the internet", [attr]))
}

# ── AWS-VPC-FLOW-LOGS (CIS 3.7, advisory) ─────────────────────────────────────

flow_log_for_vpc(vpc) := fl if {
	some fl in input.resources
	fl.type == "aws_flow_log"
	vpc_id := object.get(fl.config, "vpc_id", "")
	is_string(vpc_id)
	contains(vpc_id, sprintf("aws_vpc.%s.id", [vpc.name]))
}

violations contains v if {
	some r in input.resources
	r.type == "aws_vpc"
	not flow_log_for_vpc(r)
	v := aws_violation("AWS-VPC-FLOW-LOGS", r, "no aws_flow_log captures traffic for this VPC")
}

# ── AWS-EBS-ENCRYPTION-BY-DEFAULT (CIS 2.2.1, advisory) ───────────────────────

ebs_encryption_by_default_enabled if {
	some r in input.resources
	r.type == "aws_ebs_encryption_by_default"
	object.get(r.config, "enabled", true) != false
}

violations contains v if {
	"aws" in clouds
	not ebs_encryption_by_default_enabled
	v := aws_violation("AWS-EBS-ENCRYPTION-BY-DEFAULT", provider_anchor("aws"), "no aws_ebs_encryption_by_default resource enables account-level EBS encryption")
}

# ── AWS-EC2-DETAILED-MONITORING (advisory) ────────────────────────────────────

violations contains v if {
	some r in input.resources
	r.type == "aws_instance"
	object.get(r.config, "monitoring", false) != true
	v := aws_violation("AWS-EC2-DETAILED-MONITORING", r, "monitoring (detailed CloudWatch metrics) is not enabled")
}
