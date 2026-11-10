# Source: vmware (VMware vSphere)

Registered in `hopshift/sources/__init__.py`; translator in `hopshift/sources/vmware.py`
(`translate_vmware_discovery_to_cim`). Tier of the source: `tested`. Pair tiers live in the
[support matrix](../support-matrix.md).

## Discovery input

Accepted `metadata.schema_name` values: `vmware-discovery-stage1` (the Ansible collection's
schema, see [discovery-schema.md](../discovery-schema.md)) and `vmware-discovery`. The payload
is an object with `metadata` and a `virtual_machines` list; optional 1.1 collections
(`clusters[]` with DRS rules, `distributed_switches[]`) are used when present and inferred from
the VM records otherwise.

## Translation

| Discovery | CIM |
|---|---|
| `metadata`, `source_vcenter` | `source` (`platform: vmware_vsphere`, name, hostname, schema name/version, discovered_at); `MigratedFrom` tag `vmware-vcenter` |
| each VM | one `ComputeUnit` (id from `discovery_key`/`moid`/`uuid`, vCPU/RAM, guest OS and family, firmware, power state, template flag, snapshot count, IPs, tags, custom attributes, reservations, `architecture` always set) |
| `disks[]` | `StorageVolume` per disk (size, datastore, thin provisioning, sharing, RDM backing, unit number) |
| `networks[]` | `NIC` per adapter, referencing the port group; port groups grouped by distributed switch into `NetworkTopology` |
| `cluster`, `clusters[]` | `ComputeCluster` with `ClusterSemantics` from the DRS rules (anti-affinity, affinity, HA, unknown) |

## Blockers

Canonical names from `hopshift/cim/blockers.py`. Hard blockers quarantine the VM in
`blocker_parser` and mark the ComputeUnit `blocked`: `encrypted_vm_present`, `rdm_disk`,
`shared_disk`, `vm_template`, `unsupported_architecture`. Soft blockers mark it `needs_review`:
`vapp_config`, `vtpm_present`, `mounted_iso_present`, `snapshots_present`, `powered_off`. VM
flags (`is_encrypted`, `has_rdm_disks`, `has_shared_disks`, `is_template`, `vapp_config_present`,
`has_vtpm`, `mounted_iso_present`), `power_state`, `snapshot_count` and `architecture` are mapped
through `blockers_for_vm`.

## Fixtures and checks

`tests/fixtures/discovery_multi_vm.json` (four VMs, one quarantined for an RDM disk, two switches,
one DRS cluster) and `discovery-2.json` at the repository root. The same multi-VM fixture ships in
the package as `hopshift/testing/fixtures/discovery_multi_vm.json` for plugin repositories.

```bash
hopshift sources check vmware --input tests/fixtures/discovery_multi_vm.json
```
