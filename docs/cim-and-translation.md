# CIM And Translation

The Canonical Infrastructure Model (CIM) is defined in cim/schema.py and is the contract between any
source hypervisor and any target cloud. Translators produce it; sizing, placement, blockers, the
assessment and every renderer consume it. Nothing downstream of the CIM knows a source field name.

`cim/cim.schema.json` is generated from the models (`python -m cim.schema_export`); a test fails
when it drifts.

## Version 1.1

Attribute names keep their original spelling so existing code and output are unchanged. Every
VMware-specific term also has a neutral alias so other translators can use neutral vocabulary:

| Neutral | Accepted alias | Meaning |
|---|---|---|
| `VirtualSwitch` | `DistributedSwitch` | a switch on any hypervisor |
| `NetworkSegment` | `PortGroup` | a VLAN / port group / subnet-like segment |
| `NetworkTopology.switches` | `distributed_switches` | |
| `VirtualSwitch.segments` | `port_groups` | |
| `StorageVolume.storage_pool` | `datastore` | |
| `StorageVolume.is_passthrough` | `is_rdm` | raw device / pass-through disk |
| `NIC.segment_ref` | `port_group_ref` | |

## Core Models

- CanonicalInfrastructureModel
  - cim_schema_version: "1.1" ("1.0" documents still validate)
  - source: SourceEndpoint (platform, name, hostname, schema_name, schema_version, discovered_at)
  - source_vcenter: deprecated alias of source.name, kept for tags and renderers
  - target_provider
  - network_topology, clusters, compute_units
  - migrated_from (property): value of the MigratedFrom tag derived from source.platform

- SourcePlatform: vmware_vsphere | hyperv | powervm | zvm | nutanix_ahv | kvm | unknown
- Architecture: x86_64 | aarch64 | ppc64le | s390x | unknown

- ComputeUnit
  - id, name, vcpus, ram_mb, migration_status, blockers, cluster_ref, is_encrypted, has_vtpm, nics, storage_volumes
  - 1.1: architecture, guest_os, guest_os_id, guest_family (linux | windows | other), firmware (bios | efi),
    power_state (on | off | suspended), is_template, snapshot_count, ip_addresses, source_tags,
    custom_attributes, annotation, cpu_reservation_mhz, memory_reservation_mb, cores_per_socket,
    source_endpoint (per-unit source when several were discovered), image_ref

  `image_ref` is the target image produced by the disk migration step (AMI id, managed image id,
  GCE image, Glance image name). Renderers use it as the per-VM image fallback when set; otherwise the
  `image_overrides` variable and the provider default apply.

- StorageVolume: id, size_gb, datastore, thin_provisioned, is_encrypted, is_shared, is_rdm,
  1.1: disk_mode, controller_type, unit_number, backing_type
- NIC: name, port_group_ref, mac_address, 1.1: connected, ip_addresses, network_type
- VirtualSwitch: name, port_groups, 1.1: switch_type
- NetworkSegment: name, vlan_id, 1.1: segment_type, key
- ComputeCluster: name, semantics, 1.1: ha_enabled, drs_enabled, datacenter

## Translators

`cim/translators/` holds one module per source. A translator is a function
`(discovery_data, target_provider) -> CanonicalInfrastructureModel` registered under the discovery
`metadata.schema_name`. `cim_mapper` resolves it with `cim.translators.resolve_translator` and fails
with the list of known schemas when none matches.

Registered today: `vmware-discovery-stage1` (cim/translators/vmware.py). `cim/vmware_translator.py`
re-exports it for older imports.

### Adding a source hypervisor

1. Write `cim/translators/<platform>.py` producing the CIM; set `source.platform` and each unit's
   `architecture`.
2. Register it in `cim/translators/__init__.py` under the collector's schema name.
3. Add the platform's flag-to-blocker table to `cim/blockers.py` if its collector emits different flags.
4. Add a fixture under tests/fixtures and a translator test. No renderer or policy changes are needed.

## VMware Translation Rules

- `virtual_machines[]` drives ComputeUnit creation; id from discovery_key, moid, uuid; name from vm_name, name.
- vcpus and ram_mb default to 1 when absent (ingest warns).
- architecture is x86_64 unless the record says otherwise; non-x86 records get the hard blocker
  `unsupported_architecture` and the deterministic renderer refuses them for the four x86 clouds.
- guest_family is derived from guest_os / guest_os_id; firmware and power_state are normalized.
- Blockers come from cim/blockers.py: the explicit `migration_blockers` list plus VM flags
  (is_encrypted, has_rdm_disks, has_shared_disks, is_template, vapp_config_present, has_vtpm,
  mounted_iso_present), plus powered_off and snapshots_present derived from power_state and snapshots.
  Hard blockers -> blocked; soft blockers -> needs_review.
- Network: each discovered switch (switch_name, distributed_switch, vds_name, dvs_name) becomes one
  VirtualSwitch, each network a NetworkSegment; records without a switch field collapse into
  `default-dvs`. A top-level `distributed_switches[]` declaration (schema 1.1) is merged first and
  takes precedence.
- Clusters: from VM `cluster` values, merged with a top-level `clusters[]` declaration when present.
  DRS rules set semantics: any enabled anti-affinity rule -> anti_affinity, else affinity -> affinity,
  else ha_enabled -> ha, else unknown.
- Storage: one StorageVolume per disk; is_rdm from backing types containing `rdm` or `RawDiskMapping`;
  is_shared from multi_writer or an explicit non-default sharing mode (absent means not shared).

## Blocker Filtering

blocker_parser runs before translation on the raw records, using the same registry, and removes
hard-blocked VMs into the quarantine queue. The translator marks the remaining units ready or
needs_review.
