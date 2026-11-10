# Target: azure (Microsoft Azure)

Registered in `hopshift/targets/__init__.py`; renderers in `hopshift/targets/azure/`. Tier of the
target package: `tested`. Pair tiers live in the [support matrix](../support-matrix.md).

## What is rendered

Root module `azure-migration/` (flat, one `.tf` per logical file):

| Renderer | Files | Resources |
|---|---|---|
| `network.render_networking` | `networking_*.tf` | `azurerm_virtual_network` (one per distributed switch), `azurerm_subnet` (one per port group), `azurerm_network_security_group` (SSH from `VirtualNetwork` only) and `azurerm_subnet_network_security_group_association` |
| `compute.render_compute` | `compute_<vm>.tf` | `azurerm_network_interface` (no public IP) and `azurerm_linux_virtual_machine` with managed boot diagnostics |
| `storage.render_storage` | `storage_<vm>_disks.tf` | `azurerm_managed_disk` and `azurerm_virtual_machine_data_disk_attachment` per non-boot disk |
| `placement.render_placement` | `placement_placement_groups.tf` | `azurerm_availability_set` (anti-affinity / HA) or `azurerm_proximity_placement_group` (affinity) per DRS cluster |
| `runtime.render_runtime` | `targets.tf`, `variables.tf` | `terraform { required_providers { azurerm = hashicorp/azurerm ~> 4.0 } }`, `provider "azurerm" { features {} }` |

Variables: `location` (default `westeurope`), `resource_group_name`, `name_prefix`,
`admin_username`, `admin_public_key`, `image_overrides` (managed image id per VM name),
`environment`, `owner`.

## Sizing

`sizing_table.get_instance_type(vcpus, ram_mb)`: vCPU buckets 1, 2, 4, 8, 16 with a
closest-ceiling RAM lookup; `Standard_B1s` to `Standard_B2s` for the smallest shapes,
`Standard_D*s_v5` / `Standard_D*as_v5` above.

## Validation

terraform validate, tflint (`tflint: true`, azurerm ruleset) and the OPA bundle run on every render
in CI; the compliance controls `AZ-*` and `ALL-TAGS-REQUIRED` report zero enforce violations.
`AZ-VM-ENCRYPTION-AT-HOST` stays advisory because it needs the `Microsoft.Compute/EncryptionAtHost`
subscription feature. Deployments use the `azure` connection provider (service principal secret or
certificate, managed identity, OIDC, CLI, device code).

## Check it

```bash
hopshift targets check azure
hopshift targets check azure --terraform
```
