# Target: Microsoft Azure

Renders a flat Terraform root module for Azure from the CIM: virtual networks, subnets, a
network security group, network interfaces and Linux virtual machines, managed disks,
proximity placement groups and availability sets.

| | |
|---|---|
| Registry name | `azure` (`--cloud azure`, `options.cloud: "azure"`) |
| Package | `hopshift/targets/azure/` (`network.py`, `compute.py`, `storage.py`, `placement.py`, `runtime.py`, `sizing_table.py`) |
| Root module | `azure-migration/` |
| Provider | `hashicorp/azurerm` `~> 4.0` (`features {}`), Terraform `>= 1.5.0` |
| tflint | yes (ruleset available; runs in the validator) |
| Connections catalog key | `azure` |
| Guest architectures | `x86_64` (and `unknown`) |
| Tier | `tested` (see [support-matrix.md](../support-matrix.md)) |

## Files rendered

| File | Resources |
|---|---|
| `targets.tf` | `terraform` block with `required_version` and `required_providers`, `provider "azurerm" { features {} }` |
| `variables.tf` | the variables below |
| `networking_vpc.tf` | one `azurerm_virtual_network` per virtual switch, named `${var.name_prefix}-<switch>` |
| `networking_subnets.tf` | one `azurerm_subnet` per network segment; a `default` subnet for a switch without segments (subnets are not taggable) |
| `networking_security_groups.tf` | `azurerm_network_security_group.compute_unit` with one inbound rule `AllowSshFromVnet` (22/tcp from `VirtualNetwork`, priority 100) and one `azurerm_subnet_network_security_group_association` per subnet |
| `compute_<vm>.tf` | one `azurerm_network_interface` and one `azurerm_linux_virtual_machine` per compute unit |
| `storage_<vm>_disks.tf` | one `azurerm_managed_disk` and one `azurerm_virtual_machine_data_disk_attachment` per storage volume (LUN 0 onward) |
| `placement_placement_groups.tf` | one `azurerm_proximity_placement_group` or `azurerm_availability_set` per cluster; a comment when there are none |

Addressing: the n-th switch becomes `10.(39+n).0.0/16`, its m-th segment `10.(39+n).m.0/24`.
Azure resource names are prefixed with `var.name_prefix` so several runs can share a resource
group.

### Virtual machines

`azurerm_network_interface`: one `ip_configuration` on the subnet of the first NIC's segment
(or `default`) with a dynamic private address and no public IP.

`azurerm_linux_virtual_machine`:

- `size` from the sizing table, `admin_username = var.admin_username`, `admin_ssh_key` with
  `var.admin_public_key`.
- `os_disk` `ReadWrite` caching on `StandardSSD_LRS`; `boot_diagnostics {}` (managed storage).
- `source_image_id` from `image_overrides` (see below); when the VM has no override, a dynamic
  `source_image_reference` block falls back to the marketplace image
  `Canonical / 0001-com-ubuntu-server-jammy / 22_04-lts / latest` so the configuration stays
  plan-able.
- `proximity_placement_group_id` for an `affinity` cluster, `availability_set_id` for any other
  cluster semantics.
- Tags: `Name` plus the required tags; a source facts comment; a `TODO` when the VM has a vTPM
  (consider `vtpm_enabled` with a Trusted Launch image).

### Disks

`azurerm_managed_disk`: `StandardSSD_LRS`, `create_option = "Empty"`, size from the source,
tags `Name`, `Datastore`, `StorageEncrypted` and the required tags. Managed disks are encrypted
at rest with platform-managed keys; `disk_encryption_set_id` for customer-managed keys is a
manual addition (advisory control `AZ-DISK-CMK`). Shared and RDM-derived volumes get a `TODO`.

### Placement

| Cluster semantics | Resource |
|---|---|
| `affinity` | `azurerm_proximity_placement_group` |
| `anti_affinity`, `ha`, `unknown` | `azurerm_availability_set` (2 fault domains, 5 update domains, managed) |

### Sizing

Exact vCPU bucket, then the smallest RAM entry at or above the request; larger requests get the
largest entry of the bucket; vCPU counts above 16 use the 16 bucket.

| vCPU | RAM (MiB) up to | VM size |
|---|---|---|
| 1 | 1024 / 2048 | `Standard_B1s` / `Standard_B1ms` |
| 2 | 4096 / 8192 / 16384 | `Standard_B2s` / `Standard_D2s_v5` / `Standard_D2as_v5` |
| 4 | 8192 / 16384 / 32768 | `Standard_D4s_v5` / `Standard_D4s_v5` / `Standard_D4as_v5` |
| 8 | 16384 / 32768 / 65536 | `Standard_D8s_v5` / `Standard_D8s_v5` / `Standard_D8as_v5` |
| 16 | 32768 / 65536 / 131072 | `Standard_D16s_v5` / `Standard_D16s_v5` / `Standard_D16as_v5` |

## Variables

| Variable | Default | Purpose |
|---|---|---|
| `location` | `westeurope` | region for every resource |
| `resource_group_name` | required | existing resource group that holds the migrated resources |
| `name_prefix` | `migr` | prefix on Azure resource names |
| `admin_username` | `azureuser` | admin user on each VM |
| `admin_public_key` | required | SSH public key for the admin user |
| `image_overrides` | `{}` | `map(string)`: managed image or gallery image id per source VM name |
| `environment` | the `--environment` value (`dev` when it was an expression) | `Environment` tag |
| `owner` | the `--owner` value (`platform-team` when it was an expression) | `Owner` tag |

Set them through `PUT /api/runs/{id}/deploy/variables` or `TF_VAR_*`.

## Image handling

`source_image_id = lookup(var.image_overrides, "<vm name>", <fallback>)` where the fallback is
the CIM's `image_ref` when the discovery carried one, otherwise `null`; with `null` the
marketplace `source_image_reference` above is used. hopshift does not move disks yet (roadmap
item 1): produce managed images with Azure Migrate or an imported VHD and pass them in
`image_overrides`.

## Compliance controls

Evaluated by `hopshift/validation/policies/compliance/azure.rego` (see
[compliance.md](../compliance.md)).

| Control | Level | Satisfied by the renderer |
|---|---|---|
| `ALL-TAGS-REQUIRED` | enforce | required tags on every taggable resource |
| `AZ-NIC-NO-PUBLIC-IP` | enforce | NICs without `public_ip_address_id` |
| `AZ-NSG-NO-OPEN-MGMT-PORTS` | enforce | SSH rule sourced from `VirtualNetwork` only |
| `AZ-STORAGE-SECURE-TRANSPORT` | enforce | no storage accounts are rendered; applies to any you add |
| `AZ-STORAGE-NO-PUBLIC-ACCESS` | enforce | same |
| `AZ-VM-ENCRYPTION-AT-HOST` | advisory | not rendered: needs the `Microsoft.Compute/EncryptionAtHost` subscription feature |
| `AZ-VM-BOOT-DIAGNOSTICS` | advisory | `boot_diagnostics {}` on every VM |
| `AZ-DISK-CMK` | advisory | not rendered: needs a disk encryption set |
| `AZ-NSG-FLOW-LOGS` | advisory | not rendered: needs Network Watcher and a storage account |

In `llm`/`hybrid` modes `hashicorp/azurerm` and `hashicorp/azuread` (plus `hashicorp/random`,
`hashicorp/tls`, `hashicorp/time`) are the accepted provider sources.

## Connections

Catalog provider `azure`, methods `service_principal_secret`, `service_principal_certificate`,
`managed_identity`, `oidc` (workload identity federation), `cli` (mounted `~/.azure`) and
`device_code` (verification only, not Terraform-ready). Every method takes `subscription_id`,
`tenant_id` and `environment` (public, US Government, China). Credentials are resolved into
`ARM_*` variables. See [connections.md](../connections.md).

## Tier and evidence

`tested`:

- `tests/integration/test_terraform_validate.py`: both sample inventories rendered for
  `azure`, real `terraform init` and `validate` plus `tflint`, zero `enforce` violations from
  the real OPA bundle.
- `tests/validation/test_compliance_policies.py`: snippets per control.
- `tests/generation/test_deterministic.py`, `tests/nodes/test_hcl_generator.py`: layout and
  the Azure managed disk normalisation of the `llm` path.

## Known limitations

- Every compute unit is rendered as `azurerm_linux_virtual_machine`, including Windows guests
  (`guest_family: windows` is carried in the CIM and the source comment, not in the resource
  type). Review Windows workloads before apply.
- The resource group must exist; the module does not create it.
- One NSG for every subnet; per-workload rules are a manual step after review.
- The OS disk comes from the image; every source disk becomes a data disk.
