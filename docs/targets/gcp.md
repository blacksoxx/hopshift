# Target: Google Cloud

Renders a flat Terraform root module for Google Cloud from the CIM: VPC networks, subnetworks
with flow logs, firewall rules, Compute Engine instances, persistent disks and placement
policies.

| | |
|---|---|
| Registry name | `gcp` (`--cloud gcp`, `options.cloud: "gcp"`) |
| Package | `hopshift/targets/gcp/` (`network.py`, `compute.py`, `storage.py`, `placement.py`, `runtime.py`, `sizing_table.py`) |
| Root module | `gcp-migration/` |
| Provider | `hashicorp/google` `~> 6.0`, Terraform `>= 1.5.0` |
| tflint | yes (ruleset available; runs in the validator) |
| Connections catalog key | `gcp` |
| Guest architectures | `x86_64` (and `unknown`) |
| Tier | `tested` (see [support-matrix.md](../support-matrix.md)) |

## Files rendered

| File | Resources |
|---|---|
| `providers.tf` | `terraform` block with `required_version` and `required_providers`, `provider "google"` with `project`, `region` and `zone` from variables |
| `variables.tf` | the variables below |
| `networking_vpc.tf` | one `google_compute_network` per virtual switch (`auto_create_subnetworks = false`, `REGIONAL` routing, description naming the source switch) |
| `networking_subnets.tf` | one `google_compute_subnetwork` per network segment with `private_ip_google_access = true` and a `log_config` block (5 s aggregation, 0.5 sampling, all metadata); a `default` subnetwork for a switch without segments |
| `networking_security_groups.tf` | per network: `google_compute_firewall` `<network>_allow_ssh_internal` (ingress 22/tcp from `10.0.0.0/8`) and `<network>_egress_internal` (egress, all protocols, to `10.0.0.0/8`) |
| `compute_<vm>.tf` | one `google_compute_instance` per compute unit |
| `storage_<vm>_disks.tf` | one `google_compute_disk` and one `google_compute_attached_disk` per storage volume |
| `placement_placement_groups.tf` | one `google_compute_resource_policy` per cluster; a comment when there are none |

Addressing: networks have no CIDR on GCP; the m-th segment of the n-th switch becomes
`10.(59+n).m.0/24`. GCP names (instances, networks, subnetworks, disks, policies, firewalls)
are lowercased, limited to `[a-z0-9-]`, prefixed when they would start with a digit and cut at
63 characters.

### Instances

`google_compute_instance`:

- `machine_type` from the sizing table, `project = var.project_id`, `zone = var.zone`.
- `can_ip_forward = false`; `resource_policies` pointing at the cluster's placement policy.
- `boot_disk.initialize_params`: image from `image_overrides` (see below), 20 GB `pd-balanced`.
- `network_interface.subnetwork` is the subnetwork of the first NIC's segment (or `default`),
  with no `access_config`, so the instance has no external IP.
- `shielded_instance_config` with secure boot, vTPM and integrity monitoring on.
- `service_account`: `var.service_account_email` when set, otherwise the default Compute Engine
  account; scopes limited to `logging.write`, `monitoring.write`, `devstorage.read_only`.
- `metadata`: `enable-oslogin = "TRUE"`, `block-project-ssh-keys = "TRUE"`,
  `serial-port-enable = "FALSE"`.
- `labels`: `name` plus the required tags as lowercase labels (`environment`, `owner`,
  `migrated_from`, `source_vcenter`, and the extra `required_tags` keys normalised to label
  syntax). Networks, subnetworks, firewalls and resource policies carry no labels.
- A source facts comment; a `TODO` when the VM has a vTPM (confirm the imported image supports
  UEFI).

### Disks

`google_compute_disk`: `pd-balanced`, size from the source, `zone = var.zone`, labels `name`,
`datastore`, `storage_encrypted` and the required labels. Disks are encrypted with
Google-managed keys; a `disk_encryption_key` block with `var.default_kms_key_self_link` is
rendered only when that variable is set. Shared and RDM-derived volumes get a `TODO`.
`google_compute_attached_disk` attaches each disk to its instance.

### Placement

| Cluster semantics | Resource |
|---|---|
| any | `google_compute_resource_policy` with `group_placement_policy { availability_domain_count = 2 }` (spread) |
| `affinity` | same, plus a `TODO` to consider `collocation = "COLLOCATED"` after checking machine-type support |

### Sizing

Exact vCPU bucket, then the smallest RAM entry at or above the request; larger requests get the
largest entry of the bucket; vCPU counts above 16 use the 16 bucket.

| vCPU | RAM (MiB) up to | Machine type |
|---|---|---|
| 1 | 1024 / 2048 | `e2-micro` / `e2-small` |
| 2 | 4096 / 8192 / 16384 | `e2-medium` / `e2-standard-2` / `n2-standard-2` |
| 4 | 8192 / 16384 / 32768 | `e2-standard-4` / `n2-standard-4` / `n2-highmem-4` |
| 8 | 16384 / 32768 / 65536 | `e2-standard-8` / `n2-standard-8` / `n2-highmem-8` |
| 16 | 32768 / 65536 / 131072 | `n2-standard-16` / `n2-standard-16` / `n2-highmem-16` |

## Variables

| Variable | Default | Purpose |
|---|---|---|
| `project_id` | required | project that holds the migrated resources |
| `region` | `europe-west1` | region for subnetworks and placement policies |
| `zone` | `europe-west1-b` | zone for instances and disks; must be in `region` |
| `default_image` | `projects/debian-cloud/global/images/family/debian-12` | fallback boot image when a VM has no `image_overrides` entry |
| `image_overrides` | `{}` | `map(string)`: image self link per source VM name |
| `service_account_email` | `""` | dedicated service account for the instances; empty keeps the default account with limited scopes |
| `default_kms_key_self_link` | `""` | Cloud KMS key for customer-managed disk encryption; empty uses Google-managed keys |
| `environment` | the `--environment` value (`dev` when it was an expression) | `environment` label |
| `owner` | the `--owner` value (`platform-team` when it was an expression) | `owner` label |

Set them through `PUT /api/runs/{id}/deploy/variables` or `TF_VAR_*`.

## Image handling

`image = lookup(var.image_overrides, "<vm name>", <fallback>)` where the fallback is the CIM's
`image_ref` when the discovery carried one, otherwise `var.default_image`. hopshift does not
move disks yet (roadmap item 1): produce the images with Migrate to Virtual Machines or an
image import and pass them in `image_overrides`. Imported images must carry the
`UEFI_COMPATIBLE` guest OS feature, because Shielded VM is on.

## Compliance controls

Evaluated by `hopshift/validation/policies/compliance/gcp.rego` (see
[compliance.md](../compliance.md)).

| Control | Level | Satisfied by the renderer |
|---|---|---|
| `ALL-TAGS-REQUIRED` | enforce | required labels on instances and disks |
| `GCP-VM-NO-EXTERNAL-IP` | enforce | no `access_config` |
| `GCP-VM-SHIELDED` | enforce | `shielded_instance_config` |
| `GCP-VM-OSLOGIN` | enforce | `enable-oslogin` metadata |
| `GCP-VM-SERIAL-PORT-DISABLED` | enforce | `serial-port-enable = "FALSE"` |
| `GCP-VM-BLOCK-PROJECT-SSH-KEYS` | enforce | `block-project-ssh-keys` metadata |
| `GCP-VM-NO-IP-FORWARD` | enforce | `can_ip_forward = false` |
| `GCP-VM-LIMITED-SCOPES` | enforce | three narrow scopes |
| `GCP-SUBNET-FLOW-LOGS` | enforce | `log_config` on every subnetwork |
| `GCP-SUBNET-PRIVATE-GOOGLE-ACCESS` | enforce | `private_ip_google_access = true` |
| `GCP-FW-NO-OPEN-MGMT-PORTS` | enforce | SSH from `10.0.0.0/8` only |
| `GCP-VM-DEDICATED-SA` | advisory | satisfied when `service_account_email` is set |
| `GCP-DISK-CMEK` | advisory | satisfied when `default_kms_key_self_link` is set |

In `llm`/`hybrid` modes `hashicorp/google` and `hashicorp/google-beta` (plus `hashicorp/random`,
`hashicorp/tls`, `hashicorp/time`) are the accepted provider sources.

## Connections

Catalog provider `gcp`, methods `service_account_key`, `adc` (application default credentials
or the metadata server), `impersonation` and `workload_identity_federation`. Every method takes
`project_id` and optional `region` and `zone`. Credentials are resolved into `GOOGLE_*`
variables. See [connections.md](../connections.md).

## Tier and evidence

`tested`:

- `tests/integration/test_terraform_validate.py`: both sample inventories rendered for `gcp`,
  real `terraform init` and `validate` plus `tflint`, zero `enforce` violations from the real
  OPA bundle.
- `tests/validation/test_compliance_policies.py`: snippets per control.
- `tests/generation/test_deterministic.py`, `tests/nodes/test_hcl_generator.py`: layout and
  the GCP normalisation and fallback of the `llm` path.

## Check it

The conformance kit runs every renderer contract, guard and policy check for this target;
`--terraform` adds a real `terraform init` and `validate` (and `tflint` where the registry enables it):

```bash
hopshift targets check gcp
hopshift targets check gcp --terraform
```

See [the support matrix](../support-matrix.md) and [plugins](../plugins.md) for what each check means.

## Known limitations

- The boot disk is always 20 GB `pd-balanced` from the image; the source's first disk becomes a
  data disk like the others.
- Placement is always spread; collocated placement is left as a `TODO`.
- One firewall pair per network; per-workload rules are a manual step after review.
