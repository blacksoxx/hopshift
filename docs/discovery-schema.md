# Discovery JSON Contract (proposal)

Status: **draft for discussion**. The agent, the Ansible playbook that produces the discovery
JSON, and this schema are being designed together. Nothing here is enforced yet beyond the
checks listed under "What the agent validates today".

## Why a contract

"Works on any provided JSON" only has a meaning once the allowed shape is written down. The
contract lets the playbook and the agent evolve independently: the playbook promises to emit
these fields, the agent promises to consume them, and property-based tests can generate any
payload the contract allows.

Two files in the repo are real samples of the current output: `discovery.json` (one encrypted
VM, quarantined) and `discovery-2.json` (the same VM, migratable). A synthetic multi-VM sample
with a cluster and two distributed switches lives in `tests/fixtures/discovery_multi_vm.json`.

## Current shape: `vmware-discovery-stage1` 1.0.0

Top level:

| Field | Type | Used by the agent |
|---|---|---|
| `metadata.schema_name` | string | logged only (proposed: validated) |
| `metadata.schema_version` | string | logged only (proposed: validated) |
| `metadata.generated_at` | string | `GeneratedAt` tag (stable per discovery run) |
| `metadata.vcenters_queried` | list[string] | fallback `source_vcenter` |
| `virtual_machines` | list[object] | required |

Per VM, fields the agent reads today:

| Field | Type | Effect |
|---|---|---|
| `discovery_key` / `moid` / `uuid` | string | ComputeUnit id (first non-empty) |
| `vm_name` / `name` | string | ComputeUnit name, file names, resource names |
| `vcpus`, `ram_mb` | int | sizing lookup (default 1 when absent, see gaps) |
| `cluster` | string or null | ComputeCluster and placement group |
| `source_vcenter` | string | CIM source_vcenter |
| `is_encrypted` | bool | hard blocker `encrypted_vm_present` |
| `has_rdm_disks` | bool | hard blocker `rdm_disk` |
| `has_shared_disks` | bool | hard blocker `shared_disk` |
| `vapp_config_present` | bool | blocker `vapp_config` (hard/soft mismatch, see gaps) |
| `has_vtpm` | bool | `needs_review` + TODO comment |
| `migration_blockers` | list[string] | merged with the flags above |
| `migration_blocked` | bool | translator status only (not used by blocker_parser) |
| `disks[]` | list[object] | StorageVolume per disk |
| `disks[].filename` / `label` / `unit_number` | string/int | volume id |
| `disks[].size_gb` | number | volume size (rounded up, min 1) |
| `disks[].datastore` | string | `Datastore` tag |
| `disks[].thin_provisioned` | bool | AWS volume type hint |
| `disks[].backing_type` | string | RDM detection (`rdm` or `RawDiskMapping`) |
| `disks[].sharing` / `multi_writer` | string/bool | shared-disk detection |
| `networks[]` | list[object] | NIC per adapter |
| `networks[].network_name` / `portgroup_name` / `label` | string | PortGroup name |
| `networks[].vlan_id` | string | PortGroup VLAN |
| `networks[].distributed_switch` / `switch_name` / `vds_name` / `dvs_name` | string | DistributedSwitch name |
| `networks[].mac_address` | string | NIC MAC |

Fields present in the real samples but currently ignored: `guest_os`, `guest_os_id`,
`firmware`, `power_state`, `is_template`, `snapshot_count`, `snapshots`, `all_ip_addresses`,
`ip_address`, `tags`, `custom_attributes`, `annotation`, `resource_pool`, `datacenter`,
`esxi_host`, `hw_version`, `cores_per_socket`, `cpu_reservation_mhz`, `memory_reservation_mb`,
`mounted_iso_present`, `fault_tolerance_state`, `tools_status`.

## Gaps in the current output that block correct rendering

1. **No switch name per NIC.** The real samples carry `network_name`, `portgroup_key` and an
   empty `vlan_id`, but no distributed switch field. The agent looks for `distributed_switch`,
   `switch_name`, `vds_name` or `dvs_name` and otherwise collapses everything into
   `default-dvs`. The 1:1 switch-to-VPC mapping cannot work until the playbook emits the switch.
2. **No DRS rules.** `cluster` is a name only, so every cluster has `semantics: unknown` and
   placement falls back to spread/anti-affinity. Rules are needed for affinity vs anti-affinity.
3. **Missing `vcpus`/`ram_mb` silently default to 1** and size to the smallest instance. They
   should be required, or their absence should be a `needs_review`.
4. **Blocker vocabulary is inconsistent** between the playbook (`rdm_disk_present`), the
   agent (`rdm_disk`) and the config. One canonical list is needed.
5. **Guest OS is dropped**, so every VM gets a generic Ubuntu/Debian/AL2023 image reference.
   The OS and firmware are needed to choose the imported image and boot mode.

## Proposed 1.1.0 additions

Backward compatible: every new field is optional; consumers treat absence as "unknown".

Per VM:

```json
{
  "guest_os": "CentOS 7 (64-bit)",
  "guest_os_id": "centos7_64Guest",
  "guest_family": "linux",
  "firmware": "bios",
  "power_state": "poweredOn",
  "is_template": false,
  "snapshot_count": 0,
  "mounted_iso_present": false,
  "ip_addresses": ["10.10.20.5"],
  "tags": [{"category": "owner", "name": "platform-team"}],
  "custom_attributes": [{"key": "CostCenter", "value": "CC-42"}],
  "annotation": "free text, treated as untrusted",
  "cpu_reservation_mhz": 0,
  "memory_reservation_mb": 0,
  "cores_per_socket": 1
}
```

Per NIC (replaces the four ad-hoc switch keys with one):

```json
{
  "label": "Network adapter 1",
  "network_name": "pg-web",
  "network_type": "dvportgroup | standard | opaque",
  "switch_name": "dvs-prod",
  "switch_type": "distributed | standard",
  "portgroup_key": "dvportgroup-1234",
  "vlan_id": "110",
  "vlan_type": "vlan | trunk | pvlan | none",
  "mac_address": "00:50:56:aa:00:01",
  "connected": true
}
```

New top-level collections so topology does not have to be inferred from VMs:

```json
{
  "clusters": [
    {
      "name": "prod-cluster",
      "datacenter": "lab-dc",
      "ha_enabled": true,
      "drs_enabled": true,
      "drs_rules": [
        {"name": "web-anti-affinity", "type": "anti_affinity", "enabled": true, "vm_names": ["web-01", "web-02"]},
        {"name": "db-affinity", "type": "affinity", "enabled": true, "vm_names": ["db-01", "db-02"]}
      ]
    }
  ],
  "distributed_switches": [
    {
      "name": "dvs-prod",
      "datacenter": "lab-dc",
      "port_groups": [
        {"name": "pg-web", "key": "dvportgroup-1234", "vlan_id": "110", "vlan_type": "vlan"}
      ]
    }
  ],
  "datastores": [
    {"name": "vsan-ds", "type": "vsan", "capacity_gb": 8192, "free_gb": 3000}
  ]
}
```

Per disk: add `"controller_type"`, `"disk_mode"` (persistent / independent_persistent /
independent_nonpersistent) and keep `"backing_type"` as the raw vSphere class name.

## What the agent validates today

- Root must be an object with a `virtual_machines` list. Anything else is rejected at ingest.
- Non-object entries in `virtual_machines` are skipped by the enricher.
- Everything else is optional and defaulted.

Proposed for Phase 1: validate `metadata.schema_name` and a supported `schema_version` range,
require `vm_name`, `vcpus`, `ram_mb` per VM, and reject or flag a payload that yields zero
migratable VMs as a distinct outcome rather than a plain success.

## Open questions for the playbook

- Which vSphere API calls provide the DVS name per NIC cheaply? (`network.backing.port.switchUuid`
  on `VirtualEthernetCard` resolved through `DistributedVirtualSwitch.uuid`.)
- Should DRS rules be emitted per cluster or per VM (`drs_rule_names` on the VM)? Per cluster is
  proposed above.
- Are `annotation` and `custom_attributes` safe to emit? They are free text authored inside
  vSphere; the agent treats them as untrusted and quotes them, but they will reach cloud tags.
