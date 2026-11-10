# Target: openstack (OpenStack)

Registered in `hopshift/targets/__init__.py`; renderers in `hopshift/targets/openstack/`. Tier of
the target package: `validated`. Pair tiers live in the [support matrix](../support-matrix.md).

## What is rendered

Root module `openstack-migration/` (flat, one `.tf` per logical file):

| Renderer | Files | Resources |
|---|---|---|
| `network.render_networking` | `networking_*.tf` | `openstack_networking_network_v2` (one per distributed switch, tagged `Key=Value`), `openstack_networking_subnet_v2` (one per port group), `openstack_networking_router_v2` and `openstack_networking_router_interface_v2`, `openstack_networking_secgroup_v2` with `openstack_networking_secgroup_rule_v2` (ingress from `10.0.0.0/8` only) |
| `compute.render_compute` | `compute_<vm>.tf` | `openstack_compute_instance_v2` (Nova) attached to the rendered networks and security groups |
| `storage.render_storage` | `storage_<vm>_disks.tf` | `openstack_blockstorage_volume_v3` (Cinder, `var.encrypted_volume_type`) and `openstack_compute_volume_attach_v2` per non-boot disk |
| `placement.render_placement` | `placement_placement_groups.tf` | `openstack_compute_servergroup_v2` per DRS cluster (`affinity` policy for affinity clusters, `soft-anti-affinity` otherwise) |
| `runtime.render_runtime` | `targets.tf`, `variables.tf` | `terraform { required_providers { openstack = terraform-provider-openstack/openstack ~> 2.1 } }`, `provider "openstack"` |

Variables: `auth_url`, `user_name`, `password` (sensitive, `TF_VAR_password`), `tenant_name`,
`domain_name` (default `Default`), `region`, `external_network_id`, `default_image_name`,
`image_overrides` (Glance image name per VM name), `key_pair_name`, `encrypted_volume_type`
(default `encrypted`), `environment`, `owner`.

## Sizing

`sizing_table.get_instance_type(vcpus, ram_mb)`: vCPU buckets 1, 2, 4, 8, 16 with a
closest-ceiling RAM lookup onto the standard flavor names (`m1.tiny` family); adjust the table
to the flavors of the cloud you deploy to.

## Validation

terraform validate and the OPA bundle run on every render in CI; tflint has no ruleset for the
OpenStack provider (`tflint: false`, force it with `validation.run_tflint_openstack: true`). The
compliance controls `OS-*` and `ALL-TAGS-REQUIRED` report zero enforce violations;
`OS-VOLUME-ENCRYPTED-TYPE` is advisory because the volume type's encryption cannot be verified
statically. Deployments use the `openstack` connection provider (password, application
credential, clouds.yaml).

## Check it

```bash
hopshift targets check openstack
hopshift targets check openstack --terraform
```
