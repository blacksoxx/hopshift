# Target: Proxmox VE

Renders a flat Terraform root module for Proxmox VE from the CIM with the
[bpg/proxmox](https://registry.terraform.io/providers/bpg/proxmox/latest) provider: KVM virtual
machines with their disks, VLAN-tagged NICs on a bridge, a per-VM firewall, HA groups and HA
resources.

| | |
|---|---|
| Registry name | `proxmox` (`--cloud proxmox`, `options.cloud: "proxmox"`) |
| Package | `hopshift/targets/proxmox/` (`network.py`, `compute.py`, `storage.py`, `placement.py`, `runtime.py`, `sizing_table.py`) |
| Root module | `proxmox-migration/` |
| Provider | `bpg/proxmox` `~> 0.121` (declared through `TargetSpec.extra["provider_sources"]`), Terraform `>= 1.5.0` |
| tflint | no ruleset; the validator skips tflint for this target unless `validation.run_tflint_proxmox: true` |
| Connections catalog key | `proxmox` (`api_token`, `password`) |
| Guest architectures | `x86_64` (and `unknown`) |
| Tier | `validated` (see [support-matrix.md](../support-matrix.md)) |

Proxmox differs from the hyperscalers in three ways that shape the output:

- there are no instance types: a VM gets exactly the cores and memory of the source VM;
- networking is node-level: NICs attach to a Linux bridge and carry an 802.1Q tag, there is no
  tenant network, subnet or security group object;
- disks live inside the VM resource and storage encryption is a property of the datastore.

## What is rendered

For the multi-VM fixture (`tests/fixtures/discovery_multi_vm.json`, VMs `web-01`, `db-01`,
`mgmt-jump`, cluster `prod-cluster`) the flat root module is:

```
proxmox-migration/
  compute_<vm>.tf                 one proxmox_virtual_environment_vm per VM (+ a locals block for the template lookup)
  firewall_<vm>.tf                proxmox_virtual_environment_firewall_options + _firewall_rules per VM
  network_vlans.tf                one proxmox_virtual_environment_network_linux_vlan per VLAN tag
  placement_placement_groups.tf   HA group per cluster, HA resource per clustered VM, affinity rules (PVE 9)
  storage_<vm>_disks.tf           disk inventory (comments): source VMDK, datastore, shared/RDM flags
  providers.tf                      terraform { required_providers } and the provider block
  variables.tf
```

### Compute (`proxmox_virtual_environment_vm`)

| Source | Rendered |
| --- | --- |
| name | `name` as a DNS label (lower-case, `[a-z0-9-]`, 63 chars; a comment keeps the original) |
| vCPUs, RAM | `cpu { cores = <vcpus>  sockets = 1  type = "x86-64-v2-AES" }`, `memory { dedicated = <ram_mb> }`; the sizing label (`kvm-4c-16g`) only appears in comments and review notes |
| firmware `efi` | `bios = "ovmf"` + `efi_disk { type = "4m", pre_enrolled_keys = true }` (Secure Boot) + `tpm_state { version = "v2.0" }` |
| firmware `bios` | `bios = "seabios"`; `tpm_state` only when the source VM had a vTPM |
| guest OS | `operating_system { type = "l26" }` for Linux, `win11`/`win10`/`win8`/`win7`/`w2k8` from the Windows release, `other` otherwise |
| disks | one `disk {}` block per volume in bus order: `scsi0` boot, `scsi1`... data; `datastore_id = var.datastore_id`, `size` in GB, `iothread = true`, `discard = "on"` |
| NICs | one `network_device {}` per adapter: `bridge = var.bridge`, `model = var.nic_model`, `vlan_id` from the port group, `firewall = true`, the source MAC address kept |
| tags | `["env-${var.environment}", "migratedfrom-<source>", "owner-${var.owner}", "source-<vcenter>"]`, sorted, lower-case `[a-z0-9_.+-]` (extra required tags become `<key>-<value>`) |
| description | source platform, vCenter, VM name, guest OS, cluster, annotation |
| agent | `agent { enabled = true }` (the guest must run `qemu-guest-agent`, see limitations) |

### Templates and `image_overrides`

Proxmox cannot boot a VMware VMDK directly: the disk is converted (`qemu-img convert`) and either
attached to a template VM that is cloned, or imported into the new VM. The compute renderer handles
the three states of `ComputeUnit.image_ref` (filled by the disk migration step or the operator):

| `image_ref` | Rendered |
| --- | --- |
| empty (default) | `locals { <vm>_template_id = lookup(var.image_overrides, "<vm>", var.default_template_id) }` and a `dynamic "clone"` block that only materialises when the lookup is non-null; `started = local.<vm>_template_id != null` keeps the VM stopped with empty disks until a template is configured or the disks are imported. A `TODO` comment marks the VM. |
| a number (`9001`) | `clone { vm_id = lookup(var.image_overrides, "<vm>", 9001)  full = true }`: the per-VM override still wins, the recorded template is the fallback |
| an import id (`local:import/web-01.qcow2`) | no clone; the boot disk gets `import_from = "<id>"` |

`var.image_overrides` is a `map(number)` keyed by the VMware VM name; `var.default_template_id`
(`number`, default `null`) applies to every VM without an entry. Disk blocks declared on a cloned
VM resize the inherited disks (they cannot shrink them); the sizes rendered are the source sizes.

### Network (`network_vlans.tf`)

Every port group with a single VLAN tag (1-4094) becomes a tag on the VM NICs (`vlan_id`) and one
`proxmox_virtual_environment_network_linux_vlan` named `"${var.bridge}.<vlan>"` on `var.proxmox_node`
(one per VLAN even when several port groups share it). The node-level interface documents the
segment and gives the node an attachment point in the VLAN; no address is assigned. The bridge
must be VLAN-aware (`bridge-vlan-aware yes` in `/etc/network/interfaces`). Port groups without a
single tag (untagged, trunks, ranges) are listed in a comment and their NICs stay untagged.

### Firewall model (`firewall_<vm>.tf`)

The Proxmox firewall is off by default and only filters NICs that opt in. Per VM the renderer emits:

- `proxmox_virtual_environment_firewall_options`: `enabled = true`, `input_policy = "DROP"`,
  `output_policy = "ACCEPT"`, `macfilter = true`, `dhcp = true`, `ndp = true`, `radv = false`,
  `log_level_in = "warning"`;
- `proxmox_virtual_environment_firewall_rules` with two inbound `ACCEPT` rules whose `source` is
  `join(",", var.management_cidrs)`: TCP 22 (SSH) for Linux and other guests or TCP 3389 (RDP) for
  Windows guests, and ICMP echo;
- `firewall = true` on every `network_device`.

`var.management_cidrs` defaults to the RFC 1918 ranges and its validation rejects `0.0.0.0/0` and
`::/0`. Application ports are not opened; add rules for them per VM. The cluster and node firewall
(`/etc/pve/firewall/cluster.fw`) must be enabled for VM rules to take effect.

### HA and placement (`placement_placement_groups.tf`)

| CIM | Rendered |
| --- | --- |
| cluster (HA on or unknown) | `proxmox_virtual_environment_hagroup` named after the cluster; `nodes` = `var.ha_nodes` or `[var.proxmox_node]` with no priority, `restricted = false`, `no_failback = false` |
| VM in such a cluster | `proxmox_virtual_environment_haresource { resource_id = "vm:${...vm_id}", state = "started" }` in that group |
| cluster with `ha_enabled = false` | comment only |
| semantics `anti_affinity` / `affinity` (2+ VMs) | `proxmox_virtual_environment_harule { type = "resource-affinity", affinity = "negative" / "positive" }` with `count = var.ha_rules_enabled ? 1 : 0` |
| semantics `ha`, `lb`, `unknown` | `TODO` comment: DRS spreading has no soft equivalent on Proxmox |
| VM without cluster | no HA resource (advisory `PVE-HA-ENABLED`) |

HA rules exist since Proxmox VE 9 (HA groups are the PVE 8 mechanism, still accepted by 9); keep
`var.ha_rules_enabled = false` on PVE 8. Negative affinity is strict: with fewer nodes than
members some VMs stay stopped.

## Variables

| Variable | Type | Default | Purpose |
| --- | --- | --- | --- |
| `proxmox_endpoint` | `string` | `null` | API URL; `null` reads `PROXMOX_VE_ENDPOINT` from the connection |
| `proxmox_insecure` | `bool` | `null` | skip TLS verification; `null` reads `PROXMOX_VE_INSECURE` |
| `proxmox_node` | `string` | `"pve"` | node that hosts the VMs and the VLAN interfaces |
| `datastore_id` | `string` | `"local-lvm"` | datastore for disks, EFI disk and TPM state |
| `bridge` | `string` | `"vmbr0"` | VLAN-aware bridge for the NICs |
| `nic_model` | `string` | `"virtio"` | `virtio`, `vmxnet3` (first boot of a VMware guest without VirtIO drivers), `e1000`, `e1000e`, `rtl8139` |
| `image_overrides` | `map(number)` | `{}` | template VM id per VMware VM name |
| `default_template_id` | `number` | `null` | template for VMs without an override |
| `management_cidrs` | `list(string)` | RFC 1918 | sources allowed to reach SSH/RDP and ICMP |
| `ha_nodes` | `list(string)` | `[]` | HA group members; empty means `proxmox_node` |
| `ha_rules_enabled` | `bool` | `false` | render PVE 9 affinity rules |
| `environment`, `owner` | `string` | CLI tags (sanitised) | become `env-*` / `owner-*` tags; validated as lower-case `[a-z0-9_.+-]` |

Credentials are never rendered: `provider "proxmox"` sets only `endpoint` and `insecure`, and the
stored connection exports `PROXMOX_VE_API_TOKEN` or `PROXMOX_VE_USERNAME` / `PROXMOX_VE_PASSWORD`
(see `docs/connections.md`).

## Compliance

Controls in `hopshift/validation/policies/compliance/proxmox.rego` (catalog in
`hopshift/services/compliance/controls.py`): enforce `PVE-FW-NO-OPEN-MGMT-PORTS`,
`PVE-VM-FIREWALL-ENABLED`, `PVE-VM-AGENT-ENABLED`, `PVE-VM-OWNERSHIP-TAGS`,
`PVE-VM-NO-SERIAL-CONSOLE`; advisory `PVE-DISK-ENCRYPTION`, `PVE-VM-SECURE-BOOT`, `PVE-HA-ENABLED`.
`ALL-TAGS-REQUIRED` accepts the Proxmox tag list (`env-`, `owner-`, `migratedfrom-` entries) and
the base `no_open_ingress` rule denies inbound `ACCEPT` rules from `0.0.0.0/0`, `::/0` or an empty
source. The rendered module passes every enforce control; the fixture reports three advisories
(`local-lvm` cannot be confirmed as encrypted, `db-01` boots with BIOS, `mgmt-jump` is not in a
cluster). See `docs/compliance.md`.

## Limitations

- **No disk encryption flag.** Proxmox encrypts at the datastore level (LUKS under LVM, ZFS native
  encryption, encrypted Ceph OSDs). `PVE-DISK-ENCRYPTION` stays advisory and recognises datastore
  names containing `encrypt`, `luks` or `crypt`; confirm the storage with the Proxmox operator.
- **Anti-affinity.** Proxmox VE 8 has none; PVE 9 has strict HA rules only. DRS-style soft spreading
  (`ha`, `lb`, `unknown` semantics) is a `TODO` comment.
- **Node selection.** Every VM, VLAN interface and HA group defaults to `var.proxmox_node`; the
  renderer has no view of the destination cluster's nodes or capacity. Set `ha_nodes` and move VMs
  with `migrate = true` or HA after the first apply.
- **Guest agent.** `agent { enabled = true }` makes the provider wait for the agent on start; a guest
  without `qemu-guest-agent` leads to long timeouts and failed shutdown/reboot operations. Install the
  agent in the source VM before the cut-over (VMs created without a template stay stopped).
- **Secure Boot keys.** EFI VMs get pre-enrolled Microsoft/distribution keys; guests with unsigned
  kernel modules must set `pre_enrolled_keys = false`.
- **Shared and RDM disks** are rendered as plain disks with a `TODO` (shared storage / LUN mapping
  are manual).
- **Node-level VLAN interfaces** make the node present in every guest VLAN (without an address);
  drop `network_vlans.tf` if that is not wanted. The NIC `vlan_id` tags are what isolate traffic.
- **Resource names.** bpg/proxmox added short `proxmox_*` aliases in 0.100 and keeps the
  `proxmox_virtual_environment_*` names until 1.0; the pin `~> 0.121` excludes 1.0.
