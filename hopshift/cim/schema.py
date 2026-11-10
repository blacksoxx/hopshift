"""Canonical Infrastructure Model (CIM) 1.1.

The CIM is the contract between any source hypervisor and any target cloud. Attribute names
keep their original spelling for compatibility, but every VMware-specific term also accepts a
neutral alias on input, and the classes carry neutral names with the VMware names as aliases:

- VirtualSwitch  (alias DistributedSwitch)   a switch on any hypervisor
- NetworkSegment (alias PortGroup)           a VLAN / port group / subnet-like segment
- StorageVolume.datastore  (alias storage_pool)
- StorageVolume.is_rdm     (alias is_passthrough)

Source platform and CPU architecture are first-class so that non-x86 sources (IBM Power, Z)
can be routed or blocked instead of silently sized onto x86 instances.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

CIM_SCHEMA_VERSION = "1.1"

_STRICT = ConfigDict(extra="forbid", str_strip_whitespace=True, populate_by_name=True)


class TargetProvider(str):
    """Target name (lower-case identifier). Not an enum: targets are plugins, see hopshift.targets.registry.

    `TargetProvider("AWS") == "aws"`; `.value` is kept so older call sites keep working.
    """

    def __new__(cls, value: object) -> "TargetProvider":
        text = str(value.value if hasattr(value, "value") else value).strip().lower()
        if not text:
            raise ValueError("target provider must not be empty")
        return super().__new__(cls, text)

    @property
    def value(self) -> str:
        return str(self)


TargetProvider.AWS = TargetProvider("aws")  # type: ignore[attr-defined]
TargetProvider.AZURE = TargetProvider("azure")  # type: ignore[attr-defined]
TargetProvider.GCP = TargetProvider("gcp")  # type: ignore[attr-defined]
TargetProvider.OPENSTACK = TargetProvider("openstack")  # type: ignore[attr-defined]


class MigrationStatus(str, Enum):
    READY = "ready"
    BLOCKED = "blocked"
    NEEDS_REVIEW = "needs_review"


class ClusterSemantics(str, Enum):
    HA = "ha"
    ANTI_AFFINITY = "anti_affinity"
    AFFINITY = "affinity"
    LB = "lb"
    UNKNOWN = "unknown"


class SourcePlatform(str, Enum):
    VMWARE_VSPHERE = "vmware_vsphere"
    HYPERV = "hyperv"
    POWERVM = "powervm"
    ZVM = "zvm"
    NUTANIX_AHV = "nutanix_ahv"
    KVM = "kvm"
    UNKNOWN = "unknown"


class Architecture(str, Enum):
    X86_64 = "x86_64"
    AARCH64 = "aarch64"
    PPC64LE = "ppc64le"
    S390X = "s390x"
    UNKNOWN = "unknown"


# Value of the MigratedFrom tag per source platform. The VMware value is unchanged so existing
# tags, policies and documentation keep working.
MIGRATED_FROM_TAG: dict[SourcePlatform, str] = {
    SourcePlatform.VMWARE_VSPHERE: "vmware-vcenter",
    SourcePlatform.HYPERV: "hyperv",
    SourcePlatform.POWERVM: "ibm-powervm",
    SourcePlatform.ZVM: "ibm-zvm",
    SourcePlatform.NUTANIX_AHV: "nutanix-ahv",
    SourcePlatform.KVM: "kvm",
    SourcePlatform.UNKNOWN: "unknown-source",
}

# Architectures the x86 targets can run without an emulation or a specialised offering.
SUPPORTED_ARCHITECTURES_FOR_X86_TARGETS: frozenset[Architecture] = frozenset({Architecture.X86_64, Architecture.UNKNOWN})


class SourceEndpoint(BaseModel):
    """Where the inventory came from: a vCenter, an HMC, a Prism Central, SCVMM, ..."""

    model_config = _STRICT

    platform: SourcePlatform = SourcePlatform.UNKNOWN
    name: str = ""
    hostname: str | None = None
    schema_name: str | None = None
    schema_version: str | None = None
    discovered_at: str | None = None


class NetworkSegment(BaseModel):
    """A layer-2 segment: VMware port group, Hyper-V VLAN on a vSwitch, PowerVM VLAN on a SEA."""

    model_config = _STRICT

    name: str
    vlan_id: str = ""
    segment_type: str | None = None
    key: str | None = None


PortGroup = NetworkSegment


class VirtualSwitch(BaseModel):
    model_config = _STRICT

    name: str
    port_groups: list[NetworkSegment] = Field(
        default_factory=list,
        validation_alias=AliasChoices("port_groups", "segments"),
    )
    switch_type: str | None = None

    @property
    def segments(self) -> list[NetworkSegment]:
        return self.port_groups


DistributedSwitch = VirtualSwitch


class NetworkTopology(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    distributed_switches: list[VirtualSwitch] = Field(
        default_factory=list,
        validation_alias=AliasChoices("distributed_switches", "switches"),
    )

    @property
    def switches(self) -> list[VirtualSwitch]:
        return self.distributed_switches


class NIC(BaseModel):
    model_config = _STRICT

    name: str
    port_group_ref: str = Field(validation_alias=AliasChoices("port_group_ref", "segment_ref"))
    mac_address: str | None = None
    connected: bool | None = None
    ip_addresses: list[str] = Field(default_factory=list)
    network_type: str | None = None


class StorageVolume(BaseModel):
    model_config = _STRICT

    id: str
    size_gb: int = Field(ge=1)
    datastore: str | None = Field(default=None, validation_alias=AliasChoices("datastore", "storage_pool"))
    thin_provisioned: bool | None = None
    is_encrypted: bool = False
    is_shared: bool = False
    is_rdm: bool = Field(default=False, validation_alias=AliasChoices("is_rdm", "is_passthrough"))
    disk_mode: str | None = None
    controller_type: str | None = None
    unit_number: int | None = None
    backing_type: str | None = None

    @property
    def storage_pool(self) -> str | None:
        return self.datastore

    @property
    def is_passthrough(self) -> bool:
        return self.is_rdm


class ComputeCluster(BaseModel):
    model_config = _STRICT

    name: str
    semantics: ClusterSemantics = ClusterSemantics.UNKNOWN
    ha_enabled: bool | None = None
    drs_enabled: bool | None = None
    datacenter: str | None = None


class ComputeUnit(BaseModel):
    model_config = _STRICT

    id: str
    name: str
    vcpus: int = Field(ge=1)
    ram_mb: int = Field(ge=1)
    migration_status: MigrationStatus = MigrationStatus.READY
    blockers: list[str] = Field(default_factory=list)
    cluster_ref: str | None = None
    is_encrypted: bool = False
    has_vtpm: bool = False
    nics: list[NIC] = Field(default_factory=list)
    storage_volumes: list[StorageVolume] = Field(default_factory=list)

    # 1.1
    architecture: Architecture = Architecture.UNKNOWN
    guest_os: str | None = None
    guest_os_id: str | None = None
    guest_family: Literal["linux", "windows", "other"] | None = None
    firmware: Literal["bios", "efi"] | None = None
    power_state: Literal["on", "off", "suspended"] | None = None
    is_template: bool = False
    snapshot_count: int = Field(default=0, ge=0)
    ip_addresses: list[str] = Field(default_factory=list)
    source_tags: dict[str, str] = Field(default_factory=dict)
    custom_attributes: dict[str, str] = Field(default_factory=dict)
    annotation: str | None = None
    cpu_reservation_mhz: int | None = None
    memory_reservation_mb: int | None = None
    cores_per_socket: int | None = None
    source_endpoint: str | None = None
    # Target image produced by the disk migration step (AMI id, managed image id, GCE image,
    # Glance image name). Empty until the operator or the import pipeline fills it in.
    image_ref: str | None = None


class CanonicalInfrastructureModel(BaseModel):
    model_config = _STRICT

    cim_schema_version: Literal["1.0", "1.1"] = CIM_SCHEMA_VERSION
    # Deprecated alias for source.name, kept because tags and renderers reference it.
    source_vcenter: str = ""
    source: SourceEndpoint = Field(default_factory=SourceEndpoint)
    target_provider: str = Field(description="Target name registered in hopshift.targets (lower-case identifier)")

    @field_validator("target_provider", mode="before")
    @classmethod
    def _normalize_target(cls, value: object) -> str:
        return str(TargetProvider(value))
    network_topology: NetworkTopology
    clusters: list[ComputeCluster] = Field(default_factory=list)
    compute_units: list[ComputeUnit] = Field(default_factory=list)

    @property
    def migrated_from(self) -> str:
        return MIGRATED_FROM_TAG[self.source.platform]

    @property
    def source_name(self) -> str:
        return self.source.name or self.source_vcenter
