# Target: AWS

Renders a flat Terraform root module for Amazon Web Services from the CIM: VPCs, subnets,
security groups, EC2 instances, EBS volumes and placement groups.

| | |
|---|---|
| Registry name | `aws` (`--cloud aws`, `options.cloud: "aws"`) |
| Package | `hopshift/targets/aws/` (`network.py`, `compute.py`, `storage.py`, `placement.py`, `runtime.py`, `sizing_table.py`) |
| Root module | `aws-migration/` |
| Provider | `hashicorp/aws` `~> 6.0`, Terraform `>= 1.5.0` |
| tflint | yes (ruleset available; runs in the validator) |
| Connections catalog key | `aws` |
| Guest architectures | `x86_64` (and `unknown`) |
| Tier | `tested` (see [support-matrix.md](../support-matrix.md)) |

## Files rendered

Renderers emit logical keys (`aws-migration/<type>/<name>.tf`) that the assembler flattens to
one directory, because Terraform only loads `.tf` files at the root of a module.

| File | Resources |
|---|---|
| `targets.tf` | `terraform` block with `required_version` and `required_providers`, `provider "aws"` with `region = var.aws_region` |
| `variables.tf` | the variables below |
| `networking_vpc.tf` | one `aws_vpc` per virtual switch (DNS support and hostnames on) and one `aws_default_security_group` per VPC that adopts the implicit default group with no rules |
| `networking_subnets.tf` | one `aws_subnet` per network segment, tagged with its `VlanId`; a `default` subnet when the source had no segments |
| `networking_security_groups.tf` | `aws_security_group.compute_unit` (`compute-unit-sg`): SSH 22/tcp from `10.0.0.0/8`, egress to `10.0.0.0/8`, in the first VPC |
| `compute_<vm>.tf` | one `aws_instance` per compute unit |
| `storage_<vm>_disks.tf` | one `aws_ebs_volume` and one `aws_volume_attachment` per storage volume (`/dev/sdf` onward) |
| `placement_placement_groups.tf` | one `aws_placement_group` per cluster; a comment when there are none |

Addressing is deterministic: the n-th switch becomes `10.(9+n).0.0/16`, its m-th segment
`10.(9+n).m.0/24`. Resource identifiers are the sanitised source names; a VM name that collapses
to the same identifier as another VM is refused before rendering.

### Instances

`aws_instance`:

- `ami` from `image_overrides` (see below), `instance_type` from the sizing table.
- `subnet_id` is the subnet of the first NIC's segment (or `default`).
- `vpc_security_group_ids = [aws_security_group.compute_unit.id]`.
- `associate_public_ip_address = false`, `ebs_optimized = true`.
- `placement_group` when the compute unit belongs to a cluster.
- `metadata_options` requiring IMDSv2 (`http_tokens = "required"`, hop limit 1).
- `root_block_device { encrypted = true }`.
- Tags: `Name` plus the required tags (`Environment = var.environment`, `Owner = var.owner`,
  `MigratedFrom`, `SourceVCenter`, and the extra keys from `required_tags` in `config.yaml`).
- A comment line with the source facts (guest OS, firmware, power state, architecture) and a
  `TODO` when the VM has a vTPM (NitroTPM needs a UEFI AMI).

### Volumes

`aws_ebs_volume`: `availability_zone = var.default_availability_zone`, size from the source,
`encrypted = true`, `type = "gp3"` for thin-provisioned source disks and `"gp2"` for thick ones
(omitted when unknown), tags `Name`, `Datastore`, `StorageEncrypted` and the required tags.
Shared and RDM-derived volumes get a `TODO` comment. `aws_volume_attachment` attaches them in
order starting at `/dev/sdf`.

### Placement

| Cluster semantics | Resource |
|---|---|
| `affinity` | `aws_placement_group` with `strategy = "cluster"` |
| `anti_affinity`, `ha`, `unknown` | `aws_placement_group` with `strategy = "spread"` (at most 7 instances per Availability Zone; the file carries a reminder) |

### Sizing

Exact vCPU bucket, then the smallest RAM entry at or above the request; larger requests get the
largest entry of the bucket; vCPU counts above 16 use the 16 bucket.

| vCPU | RAM (MiB) up to | Instance type |
|---|---|---|
| 1 | 1024 / 2048 | `t3.micro` / `t3.small` |
| 2 | 4096 / 8192 / 16384 | `t3.medium` / `t3.large` / `m5.large` |
| 4 | 8192 / 16384 / 32768 | `m5.xlarge` / `m5.xlarge` / `m5.2xlarge` |
| 8 | 16384 / 32768 / 65536 | `m5.2xlarge` / `m5.2xlarge` / `m5.4xlarge` |
| 16 | 32768 / 65536 / 131072 | `m5.4xlarge` / `m5.4xlarge` / `m5.8xlarge` |

## Variables

| Variable | Default | Purpose |
|---|---|---|
| `aws_region` | `us-east-1` | region for every resource |
| `default_availability_zone` | `us-east-1a` | zone of the EBS volumes; must be in `aws_region` |
| `default_ami_id` | `""` | fallback AMI when a VM has no `image_overrides` entry; leave empty to force per-VM images |
| `image_overrides` | `{}` | `map(string)`: AMI id per source VM name |
| `environment` | the `--environment` value (`dev` when it was an expression) | `Environment` tag |
| `owner` | the `--owner` value (`platform-team` when it was an expression) | `Owner` tag |

Set them at deployment time through `PUT /api/runs/{id}/deploy/variables` (written to
`terraform.tfvars.json`) or with `TF_VAR_*` when you run Terraform yourself.

## Image handling

Every instance reads its image as
`lookup(var.image_overrides, "<vm name>", <fallback>)`. The fallback is the CIM's `image_ref`
for that unit when the discovery carried one, otherwise `var.default_ami_id`. hopshift does not
export or import disks yet (roadmap item 1 in the [README](../../README.md)): produce the AMIs
with AWS VM Import/Export and pass them in `image_overrides`, or set `default_ami_id` for a
landing-zone test.

## Compliance controls

Evaluated by `hopshift/validation/policies/compliance/aws.rego` and reported with every run
(see [compliance.md](../compliance.md) for references and remediation text).

| Control | Level | Satisfied by the renderer |
|---|---|---|
| `ALL-TAGS-REQUIRED` | enforce | required tags on every taggable resource |
| `AWS-EC2-IMDSV2` | enforce | `metadata_options` block |
| `AWS-EC2-NO-PUBLIC-IP` | enforce | `associate_public_ip_address = false` |
| `AWS-EC2-EBS-OPTIMIZED` | enforce | `ebs_optimized = true` |
| `AWS-EBS-ENCRYPTED` | enforce | encrypted volumes and root devices |
| `AWS-VPC-DEFAULT-SG-RESTRICTED` | enforce | `aws_default_security_group` per VPC |
| `AWS-SG-NO-OPEN-INGRESS` | enforce | ingress limited to `10.0.0.0/8` |
| `AWS-VPC-FLOW-LOGS` | advisory | not rendered: needs a log destination and IAM role |
| `AWS-EBS-ENCRYPTION-BY-DEFAULT` | advisory | not rendered: account-wide setting |
| `AWS-EC2-DETAILED-MONITORING` | advisory | not rendered: `monitoring = true` is a cost decision |

The gate rules (`no_open_ingress`, `no_public_s3`, `encryption_at_rest`, `tags_required`,
`no_code_execution`) run as well. In `llm`/`hybrid` modes only `hashicorp/aws` (plus
`hashicorp/random`, `hashicorp/tls`, `hashicorp/time`) is an accepted provider source.

## Connections

Catalog provider `aws`, methods `access_keys`, `profile`, `assume_role`, `environment`, `sso`
(IAM Identity Center device flow) and `web_identity`; every method takes `region` and an
optional `endpoint_url` (LocalStack, private endpoints). Credentials are resolved into `AWS_*`
variables for Terraform. Field lists, verification calls and the LocalStack recipe are in
[connections.md](../connections.md) and [deployments.md](../deployments.md).

## Tier and evidence

`tested`:

- `tests/integration/test_terraform_validate.py`: both sample inventories rendered for `aws`,
  then real `terraform init` and `validate` plus `tflint`; the real OPA bundle reports zero
  `enforce` violations and the evaluated control ids equal the catalog for `aws`.
- `tests/validation/test_compliance_policies.py`: compliant and violating snippets per control.
- `tests/generation/test_deterministic.py`, `tests/nodes/test_hcl_generator.py`: file layout,
  flattening, guards and the AWS module synthesis of the `llm` path.
- Deployments: `tests/services/test_deploy_service.py` and `tests/api/test_deploy_api.py` with
  a fake `terraform`; the LocalStack recipe exercises a real plan and apply.

## Check it

The conformance kit runs every renderer contract, guard and policy check for this target;
`--terraform` adds a real `terraform init` and `validate` (and `tflint` where the registry enables it):

```bash
hopshift targets check aws
hopshift targets check aws --terraform
```

See [the support matrix](../support-matrix.md) and [plugins](../plugins.md) for what each check means.

## Known limitations

- Subnets do not pin an Availability Zone while volumes use `default_availability_zone`; keep
  them consistent (set the zone on the subnets, or let every instance land in that zone) or the
  attachment fails at apply.
- One security group for every instance; per-workload rules are a manual step after review.
- Spread placement groups hold at most 7 instances per Availability Zone.
- The boot disk is the AMI's root device; the source's first disk still becomes a data volume.
