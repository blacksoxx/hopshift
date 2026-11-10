# Target: aws (Amazon Web Services)

Registered in `hopshift/targets/__init__.py`; renderers in `hopshift/targets/aws/`. Tier of the
target package: `tested`. Pair tiers live in the [support matrix](../support-matrix.md).

## What is rendered

Root module `aws-migration/` (flat, one `.tf` per logical file):

| Renderer | Files | Resources |
|---|---|---|
| `network.render_networking` | `networking_vpc.tf`, `networking_subnets.tf`, `networking_security_groups.tf` | `aws_vpc` (one per distributed switch), `aws_default_security_group` (no rules), `aws_subnet` (one per port group), `aws_security_group` (ingress from `10.0.0.0/8` only) |
| `compute.render_compute` | `compute_<vm>.tf` | `aws_instance` with IMDSv2 required, no public IP, EBS-optimised, encrypted root volume |
| `storage.render_storage` | `storage_<vm>_disks.tf` | `aws_ebs_volume` (encrypted) and `aws_volume_attachment` per non-boot disk |
| `placement.render_placement` | `placement_placement_groups.tf` | `aws_placement_group` per DRS cluster (`spread` for anti-affinity, `cluster` for affinity) |
| `runtime.render_runtime` | `targets.tf`, `variables.tf` | `terraform { required_providers { aws = hashicorp/aws ~> 6.0 } }`, `provider "aws"` |

Variables: `aws_region` (default `us-east-1`), `default_availability_zone`, `default_ami_id`,
`image_overrides` (AMI per VM name, produced by AWS VM Import/Export), `environment`, `owner`.

## Sizing

`sizing_table.get_instance_type(vcpus, ram_mb)`: vCPU buckets 1, 2, 4, 8, 16 (next larger bucket
when there is no exact match, largest bucket above 16) and a closest-ceiling RAM lookup inside
the bucket; `t3.micro` through `m5.8xlarge`.

## Validation

terraform validate, tflint (`tflint: true`, AWS ruleset) and the OPA bundle run on every render in
CI; the compliance controls `AWS-*` and `ALL-TAGS-REQUIRED` report zero enforce violations
(see [compliance.md](../compliance.md)). Deployments use the `aws` connection provider (access
keys, named profile, assume role, process environment, SSO, web identity).

## Check it

```bash
hopshift targets check aws
hopshift targets check aws --terraform
```
