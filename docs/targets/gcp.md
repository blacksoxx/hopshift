# Target: gcp (Google Cloud)

Registered in `hopshift/targets/__init__.py`; renderers in `hopshift/targets/gcp/`. Tier of the
target package: `tested`. Pair tiers live in the [support matrix](../support-matrix.md).

## What is rendered

Root module `gcp-migration/` (flat, one `.tf` per logical file):

| Renderer | Files | Resources |
|---|---|---|
| `network.render_networking` | `networking_*.tf` | `google_compute_network` (one per distributed switch, custom subnet mode), `google_compute_subnetwork` (one per port group, flow logs and private Google access on), `google_compute_firewall` (ingress from `10.0.0.0/8` only) |
| `compute.render_compute` | `compute_<vm>.tf` | `google_compute_instance` without `access_config`, `can_ip_forward = false`, Shielded VM, OS Login, project SSH keys blocked, serial port disabled, limited service-account scopes |
| `storage.render_storage` | `storage_<vm>_disks.tf` | `google_compute_disk` (CMEK through `var.default_kms_key_self_link` when set) and `google_compute_attached_disk` per non-boot disk |
| `placement.render_placement` | `placement_placement_groups.tf` | `google_compute_resource_policy` with a group placement policy spread over two availability domains per DRS cluster (affinity clusters get the same policy plus a TODO comment about `COLLOCATED`) |
| `runtime.render_runtime` | `targets.tf`, `variables.tf` | `terraform { required_providers { google = hashicorp/google ~> 6.0 } }`, `provider "google"` |

Variables: `project_id`, `region` (default `europe-west1`), `zone` (default `europe-west1-b`),
`default_image`, `image_overrides` (image per VM name), `service_account_email`,
`default_kms_key_self_link`, `environment`, `owner`.

## Sizing

`sizing_table.get_instance_type(vcpus, ram_mb)`: vCPU buckets 1, 2, 4, 8, 16 with a
closest-ceiling RAM lookup; `e2-micro` through `n2-highmem-16`.

## Validation

terraform validate, tflint (`tflint: true`, google ruleset) and the OPA bundle run on every render in
CI; the compliance controls `GCP-*` and `ALL-TAGS-REQUIRED` report zero enforce violations.
Imported images must carry the `UEFI_COMPATIBLE` guest OS feature for Shielded VM. Deployments
use the `gcp` connection provider (service account key, application default credentials,
impersonation, workload identity federation).

## Check it

```bash
hopshift targets check gcp
hopshift targets check gcp --terraform
```
