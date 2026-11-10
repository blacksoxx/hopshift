# Source: VMware vSphere

The built-in source. It translates the JSON written by the VMware discovery Ansible collection
(schema `vmware-discovery-stage1`) into the Canonical Infrastructure Model.

| | |
|---|---|
| Registry name | `vmware` |
| Schema names accepted | `vmware-discovery-stage1` (the collector's name), `vmware-discovery` (alias) |
| Source platform in the CIM | `vmware_vsphere`; `MigratedFrom` tag value `vmware-vcenter` |
| Collector | Ansible collection producing `vmware-discovery-stage1` 1.x |
| Module | `hopshift/sources/vmware.py` (`hopshift/cim/vmware_translator.py` re-exports it for older imports) |
| Registered in | `hopshift/sources/__init__.py` as a `SourceSpec` |
| Tier | `tested` (see [support-matrix.md](../support-matrix.md)) |

Registered sources and their schema names are listed by `GET /api/meta` (`sources`).

## What it expects

The payload contract is written down in [discovery-schema.md](../discovery-schema.md). The
short version:

- The root is an object with a `virtual_machines` list of objects. Anything else is rejected at
  `ingest`.
- `metadata.schema_name` selects this translator. When it is missing, `vmware-discovery-stage1`
  is assumed. `metadata.schema_version` must have major version 1; other values only warn.
- `metadata.generated_at` feeds the `GeneratedAt` tag, `metadata.vcenters_queried[0]` is the
  fallback source name when no VM carries `source_vcenter`.
- Per VM the translator reads: `discovery_key` / `moid` / `uuid` (id), `vm_name` / `name`,
  `vcpus`, `ram_mb`, `cluster`, `source_vcenter`, the blocker flags (`is_encrypted`,
  `has_rdm_disks`, `has_shared_disks`, `is_template`, `vapp_config_present`, `has_vtpm`,
  `mounted_iso_present`), `migration_blockers[]`, `migration_blocked`, `architecture`, `guest_os`,
  `guest_os_id`, `firmware`, `power_state`, `snapshot_count` / `snapshots[]`, `ip_address` /
  `all_ip_addresses`, `tags`, `custom_attributes`, `annotation`, `cpu_reservation_mhz`,
  `memory_reservation_mb`, `cores_per_socket`, `image_ref`, `disks[]` and `networks[]`.
- Optional 1.1 top-level collections `clusters[]` (with `drs_rules`) and
  `distributed_switches[]` are merged first and take precedence over what is inferred from the
  VM records.

`ingest` warns (it does not stop) when `metadata` is missing, when the schema name or major
version is unexpected, when `vcpus` or `ram_mb` are missing (they default to 1 and sizing will
be wrong) and when the inventory is empty.

Two real samples live in the repository: `discovery.json` (one encrypted VM, quarantined) and
`discovery-2.json` (the same VM, migratable). `tests/fixtures/discovery_multi_vm.json` is a
synthetic inventory with a cluster, two distributed switches and an RDM-backed VM.

## What it translates

| Discovery | CIM | Rule |
|---|---|---|
| `virtual_machines[]` | `ComputeUnit` | one per record; `vcpus` and `ram_mb` default to 1 when absent |
| `architecture` | `ComputeUnit.architecture` | `x86_64` unless the record says `aarch64`/`arm64`, `ppc64le`, `s390x`; anything else is `unknown`. Non-x86 records get the hard blocker `unsupported_architecture` and the deterministic renderer refuses them for the four built-in targets |
| `guest_os`, `guest_os_id` | `guest_family` | `windows`, `linux` (CentOS, Ubuntu, RHEL, Debian, SLES, Rocky, Alma, Oracle, Fedora, Amazon) or `other` |
| `firmware`, `power_state` | `firmware`, `power_state` | normalised to `bios`/`efi` and `on`/`off`/`suspended` |
| blocker flags, `migration_blockers[]` | `blockers`, `migration_status` | canonical names from `hopshift/cim/blockers.py`; any hard blocker (or `migration_blocked: true`) makes the unit `blocked`, any other blocker or `has_vtpm` makes it `needs_review`, otherwise `ready` |
| `disks[]` | `StorageVolume` | id from `filename` / `label` / `unit_number`; `size_gb` rounded up, minimum 1; `is_rdm` when `backing_type` contains `rdm` or `RawDiskMapping`; `is_shared` from `multi_writer` or a `sharing` value other than `sharingNone`; `is_encrypted` follows the VM flag; `disk_mode`, `controller_type`, `unit_number`, `backing_type` kept |
| `networks[]` | `NIC` | name from `label`; segment from `network_name` / `portgroup_name` / `port_group` / `label`; `mac_address`, `connected`, `ip_addresses`, `network_type` kept |
| `networks[].switch_name` (or `distributed_switch`, `vds_name`, `dvs_name`) | `VirtualSwitch` | one switch per distinct name; records without a switch field collapse into `default-dvs`; each distinct segment becomes a `NetworkSegment` with its `vlan_id`, `segment_type` and `portgroup_key` |
| `distributed_switches[]` (1.1) | `VirtualSwitch`, `NetworkSegment` | declared switches and port groups are merged first |
| `cluster`, `clusters[]` (1.1) | `ComputeCluster` | one per distinct name; `ha_enabled`, `drs_enabled`, `datacenter` from the declaration |
| `clusters[].drs_rules[]` | `ClusterSemantics` | any enabled anti-affinity rule wins (`anti_affinity`), else affinity (`affinity`), else `ha` when `ha_enabled`, else `unknown` |
| `tags`, `custom_attributes`, `annotation` | `source_tags`, `custom_attributes`, `annotation` | free text, treated as untrusted and escaped before it reaches Terraform |

Every value that reaches a Terraform file goes through `hopshift/targets/common.py`: names
become safe file stems and identifiers, strings are escaped so a VM name or annotation can
never open a `${...}` template expression.

## Blockers

Defined in `hopshift/cim/blockers.py` for the `vmware_vsphere` platform. The playbook, the
config file and older code used different spellings (`rdm_disk_present`, `rdm_disk`); every
spelling is normalised to the canonical name, so `vsphere.hard_blockers` in `config.yaml`,
`blocker_parser`, the translator and the risk assessor agree.

| Canonical blocker | Level | Set by |
|---|---|---|
| `encrypted_vm_present` | hard | `is_encrypted` |
| `rdm_disk` | hard | `has_rdm_disks` |
| `shared_disk` | hard | `has_shared_disks` |
| `vm_template` | hard | `is_template` |
| `unsupported_architecture` | hard | `architecture` not x86_64 |
| `vapp_config` | soft | `vapp_config_present` |
| `vtpm_present` | soft | `has_vtpm` |
| `mounted_iso_present` | soft | `mounted_iso_present` |
| `snapshots_present` | soft | `snapshot_count > 0` or a non-empty `snapshots[]` |
| `powered_off` | soft | `power_state` is `poweredOff`, `off` or `stopped` |

`blocker_parser` runs before translation on the raw records with the same registry and moves
hard-blocked VMs into the quarantine queue with their reasons. Soft blockers keep the VM in the
run as `needs_review`; renderers add a `TODO` comment where it matters (vTPM, shared and RDM
disks).

## Known gaps in the collector output

Tracked in [discovery-schema.md](../discovery-schema.md):

1. No switch name per NIC in the 1.0.0 output, so every segment lands on `default-dvs` and the
   1:1 switch-to-network mapping cannot work until the playbook emits `switch_name` or the
   `distributed_switches[]` collection.
2. No DRS rules, so every cluster has `semantics: unknown` and placement falls back to spread
   or anti-affinity.
3. Missing `vcpus` / `ram_mb` default to 1 and size to the smallest instance (ingest warns).
4. Guest OS is not used to choose an image; every VM uses the target's default image unless
   `image_overrides` or `image_ref` names one.

## Tier and evidence

`tested`:

- `tests/cim/test_vmware_translator.py` and `tests/cim/test_cim_11.py`: translation rules,
  1.1 fields, declared collections and precedence.
- `tests/cim/test_properties.py`: property-based tests (hypothesis) over generated payloads.
- `tests/nodes/`: ingest, blocker parsing, validation and reporting with the samples.
- `tests/integration/test_terraform_validate.py`: both samples translated and rendered for
  every built-in target, then validated with real `terraform`, `tflint` and `opa`.

These run on every pull request ([ci.md](../ci.md)).

## Related

- [discovery-schema.md](../discovery-schema.md): the full field contract and the proposed 1.1.0 fields.
- [cim-and-translation.md](../cim-and-translation.md): the CIM models.
- [plugins.md](../plugins.md): writing another source.
