# Target: OpenStack

Renders a flat Terraform root module for OpenStack from the CIM: Neutron networks, subnets,
routers and a security group, Nova instances and server groups, Cinder volumes.

| | |
|---|---|
| Registry name | `openstack` (`--cloud openstack`, `options.cloud: "openstack"`) |
| Package | `hopshift/targets/openstack/` (`network.py`, `compute.py`, `storage.py`, `placement.py`, `runtime.py`, `sizing_table.py`) |
| Root module | `openstack-migration/` |
| Provider | `terraform-provider-openstack/openstack` `~> 2.1`, Terraform `>= 1.5.0` |
| tflint | no ruleset; the validator skips tflint for this target unless `validation.run_tflint_openstack: true` |
| Connections catalog key | `openstack` |
| Guest architectures | `x86_64` (and `unknown`) |
| Tier | `validated` (see [support-matrix.md](../support-matrix.md)) |

## Files rendered

| File | Resources |
|---|---|
| `providers.tf` | `terraform` block with `required_version` and `required_providers`, `provider "openstack"` with `auth_url`, `user_name`, `password`, `tenant_name`, `domain_name` and `region` bound to null-default variables, so the `OS_*` environment of the attached connection applies unless a variable is set |
| `variables.tf` | the variables below |
| `networking_vpc.tf` | one `openstack_networking_network_v2` per virtual switch (`admin_state_up`, not shared) with the required tags as `Key=Value` list entries |
| `networking_subnets.tf` | one `openstack_networking_subnet_v2` per network segment (IPv4, DHCP on, DNS `8.8.8.8` and `8.8.4.4`, the VLAN id kept in the description); a `default` subnet for a switch without segments |
| `networking_security_groups.tf` | `openstack_networking_secgroup_v2.compute_unit` (`compute-unit-sg`) with one `openstack_networking_secgroup_rule_v2` (ingress 22/tcp from `10.0.0.0/8`); per network an `openstack_networking_router_v2` on `var.external_network_id` and an `openstack_networking_router_interface_v2` on the first subnet of that network |
| `compute_<vm>.tf` | one `openstack_compute_instance_v2` per compute unit |
| `storage_<vm>_disks.tf` | one `openstack_blockstorage_volume_v3` and one `openstack_compute_volume_attach_v2` per storage volume |
| `placement_placement_groups.tf` | one `openstack_compute_servergroup_v2` per cluster; a comment when there are none |

Addressing: the m-th segment of the n-th switch becomes `10.(79+n).m.0/24`.

### Instances

`openstack_compute_instance_v2`:

- `name` is the source name, `flavor_name` from the sizing table.
- `image_name` from `image_overrides` (see below), `key_pair = var.key_pair_name`.
- `security_groups = [openstack_networking_secgroup_v2.compute_unit.name]`.
- One `network` block naming the network that owns the first NIC's segment (the first network
  when the segment is unknown).
- `scheduler_hints { group = ... }` pointing at the cluster's server group.
- `metadata`: `Name` plus the required tags; a source facts comment; a `TODO` when the VM has a
  vTPM (needs a flavor and image with vTPM traits).

### Volumes

`openstack_blockstorage_volume_v3`: size from the source,
`volume_type = var.encrypted_volume_type`, metadata `Name`, `Datastore`, `StorageEncrypted` and
the required tags. Shared and RDM-derived volumes get a `TODO`.
`openstack_compute_volume_attach_v2` attaches each volume to its instance.

### Placement

| Cluster semantics | Server group policy |
|---|---|
| `affinity` | `["affinity"]` |
| `anti_affinity`, `ha`, `unknown` | `["soft-anti-affinity"]` |

### Sizing

Exact vCPU bucket, then the smallest RAM entry at or above the request; larger requests get the
largest entry of the bucket; vCPU counts above 16 use the 16 bucket. The flavors must exist in
the target cloud.

| vCPU | RAM (MiB) up to | Flavor |
|---|---|---|
| 1 | 1024 / 2048 | `m1.tiny` / `m1.small` |
| 2 | 4096 / 8192 / 16384 | `m1.small` / `m1.medium` / `m1.large` |
| 4 | 8192 / 16384 / 32768 | `m1.medium` / `m1.large` / `m1.xlarge` |
| 8 | 16384 / 32768 / 65536 | `m1.large` / `m1.xlarge` / `m1.2xlarge` |
| 16 | 32768 / 65536 / 131072 | `m1.xlarge` / `m1.2xlarge` / `m1.4xlarge` |

## Variables

| Variable | Default | Purpose |
|---|---|---|
| `auth_url` | `null` (reads `OS_AUTH_URL`) | Keystone v3 endpoint |
| `user_name` | `null` (reads `OS_USERNAME`) | user name |
| `password` | `null` (reads `OS_PASSWORD`), `sensitive` | password; set it as `TF_VAR_password` or through the deploy variables (masked) to override |
| `tenant_name` | `null` (reads `OS_PROJECT_NAME`) | project name |
| `domain_name` | `null` (reads `OS_USER_DOMAIN_NAME`) | Keystone domain |
| `region` | `null` (reads `OS_REGION_NAME`) | region name |
| `external_network_id` | required | external (provider) network for the routers |
| `default_image_name` | `""` | fallback Glance image when a VM has no `image_overrides` entry |
| `image_overrides` | `{}` | `map(string)`: Glance image name per source VM name |
| `key_pair_name` | `""` | Nova key pair injected into instances |
| `encrypted_volume_type` | `encrypted` | Cinder volume type backed by an encryption provider |
| `environment` | the `--environment` value (`dev` when it was an expression) | `Environment` tag |
| `owner` | the `--owner` value (`platform-team` when it was an expression) | `Owner` tag |

The six provider variables default to `null`, so a deployment with an attached connection
authenticates with the `OS_*` environment the connection exports (password, application
credential or `clouds.yaml`) and needs no credential variables. Setting any of them through
`PUT /api/runs/{id}/deploy/variables` (or `TF_VAR_*`) overrides the environment for that
argument. Values set through the deploy variables are stored in `terraform.tfvars.json` and
masked in the variables view and the logs when the variable is `sensitive`.

## Image handling

`image_name = lookup(var.image_overrides, "<vm name>", <fallback>)` where the fallback is the
CIM's `image_ref` when the discovery carried one, otherwise `var.default_image_name`. hopshift
does not move disks yet (roadmap item 1): convert the migrated disks, upload them to Glance and
pass the image names in `image_overrides`.

## Compliance controls

Evaluated by `hopshift/validation/policies/compliance/openstack.rego` (see
[compliance.md](../compliance.md)). CIS publishes no OpenStack benchmark, so these controls
carry SOC 2 and HIPAA references only.

| Control | Level | Satisfied by the renderer |
|---|---|---|
| `ALL-TAGS-REQUIRED` | enforce | `Key=Value` tags on networks, metadata on instances and volumes |
| `OS-SG-NO-OPEN-MGMT-PORTS` | enforce | SSH from `10.0.0.0/8` only |
| `OS-VOLUME-ENCRYPTED-TYPE` | advisory | `var.encrypted_volume_type`; volume types are opaque names, so the control checks the name or variable default and the cloud operator must confirm it is LUKS-backed |

The gate rule `encryption_at_rest` requires a `volume_type` on every volume. In `llm`/`hybrid`
modes `terraform-provider-openstack/openstack` (plus `hashicorp/random`, `hashicorp/tls`,
`hashicorp/time`) is the accepted provider source.

## Connections

Catalog provider `openstack`, methods `password`, `application_credential` and `clouds_yaml`
(a named cloud from a mounted `clouds.yaml`). Every method takes `auth_url` (Keystone v3) and
optional `region_name` and `interface`. Verification is a project-scoped Keystone token request;
credentials are resolved into `OS_*` variables. See [connections.md](../connections.md) and the
note on provider variables above.

## Tier and evidence

`validated`:

- `tests/integration/test_terraform_validate.py`: both sample inventories rendered for
  `openstack`, real `terraform init` and `validate`, zero `enforce` violations from the real OPA
  bundle and the evaluated control ids equal to the catalog. The suite also runs plain `tflint`
  when the binary is installed; there is no OpenStack ruleset, which is why the validator node
  skips tflint for this target by default. `tested` would need a run against a real OpenStack
  cloud, which has not been recorded yet.
- `tests/validation/test_compliance_policies.py`: snippets per control.
- `tests/generation/test_deterministic.py`, `tests/nodes/test_hcl_generator.py`: layout and
  the OpenStack normalisation and fallback of the `llm` path.

## Check it

The conformance kit runs every renderer contract, guard and policy check for this target;
`--terraform` adds a real `terraform init` and `validate` (and `tflint` where the registry enables it):

```bash
hopshift targets check openstack
hopshift targets check openstack --terraform
```

See [the support matrix](../support-matrix.md) and [plugins](../plugins.md) for what each check means.

## Known limitations

- Provider credentials come from variables (see above), which duplicates the connection.
- Each router attaches only the first subnet of its network; add interfaces for the others.
- DNS servers are fixed to `8.8.8.8` and `8.8.4.4`.
- Flavor and image names must exist in the target cloud; nothing is created for them.
- One security group for every instance; per-workload rules are a manual step after review.
