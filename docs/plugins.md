# Writing plugins: targets and sources

hopshift migrates infrastructure from any source to any target through one canonical model, the
CIM (`hopshift/cim/schema.py`). Everything upstream of the CIM is a **source** (a translator for
one discovery format), everything downstream is a **target** (a renderer package for one
destination). Neither side knows about the other, so a new target works with every source and a
new source works with every target.

Both kinds are plain Python packages described by a spec object and found through a registry:

| | Target | Source |
|---|---|---|
| Spec | `hopshift.targets.registry.TargetSpec` | `hopshift.sources.registry.SourceSpec` |
| Registry | `hopshift.targets.registry` (`get`, `names`, `all_specs`) | `hopshift.sources.registry` (`get`, `for_schema`, `names`) |
| Built-ins register in | `hopshift/targets/__init__.py` | `hopshift/sources/__init__.py` |
| Entry-point group | `hopshift.targets` | `hopshift.sources` |
| Conformance | `hopshift.testing.check_target`, `hopshift targets check` | `hopshift.testing.check_source`, `hopshift sources check` |
| pytest fixture | `hopshift_target_conformance` | `hopshift_source_conformance` |

An entry point must resolve to a spec, or to a zero-argument callable returning one. The
registries load plugins lazily on first use and log (never raise) when a plugin fails to import;
`hopshift plugins list` shows every entry point with its load status.

## Tiers and the support matrix

Three tiers describe how far something has been proven. They apply to a spec (`TargetSpec.tier`,
`SourceSpec.tier`) and, more usefully, to a **source -> target pair** in `support.yaml`, which is
rendered to [support-matrix.md](support-matrix.md):

| Tier | Meaning | Evidence that earns it |
|---|---|---|
| `experimental` | renders, not yet validated end to end | `hopshift targets check <name>` passes (render, guards, parse, OPA, sizing) |
| `validated` | rendered and validated by terraform validate, tflint and OPA in CI | `hopshift targets check <name> --terraform` passes and the pair has an integration test that runs on every CI run |
| `tested` | exercised against real infrastructure | a documented lab or account run (plan and apply) with the evidence linked in `support.yaml` |

A pair moves up by adding the evidence and editing its `tier` in `support.yaml`, then running
`hopshift matrix render` and committing `docs/support-matrix.md` (`hopshift matrix check` runs in
CI and fails when the document is stale, or when a row names a source or target that is not
registered). A row for a target that is still being built can stay commented out.

## Target plugins

### Package layout

```
hopshift_nimbus/                  # any importable package name
    __init__.py                   # TARGET = TargetSpec(...)
    network.py                    # render_networking
    compute.py                    # render_compute
    storage.py                    # render_storage
    placement.py                  # render_placement
    runtime.py                    # render_runtime (providers + variables)
    sizing_table.py               # get_instance_type
docs/nimbus.md                    # what gets rendered, variables, sizing, caveats
tests/test_conformance.py         # two lines, see below
pyproject.toml                    # entry point
```

### TargetSpec

```python
from hopshift.targets.registry import TargetSpec

TARGET = TargetSpec(
    name="nimbus",                       # lower-case identifier: config, CLI, API, root directory
    label="Nimbus Cloud",                # shown in the UI
    blurb="Instances, volumes, networks, security groups",
    package="hopshift_nimbus",           # the package holding the six modules above
    tier="experimental",                 # tested | validated | experimental
    tflint=False,                        # True only when tflint has a ruleset for the provider
    connection_provider=None,            # key in the connections catalog, None until deploy is supported
    architectures=frozenset({"x86_64", "unknown"}),
    docs="docs/nimbus.md",               # checked by the kit: the file must exist
    extra={"provider_sources": {"nimbus/nimbus"}},   # Terraform provider sources the runtime emits
)
```

`spec.root` is `<name>-migration`: every rendered file lives in that directory.

### The five renderer functions

The deterministic assembler (`hopshift/pipeline/generation/deterministic.py`) calls them in this
order and flattens the result into one root module:

| Module | Function | Called with | Returns |
|---|---|---|---|
| `network` | `render_networking(cim)` | the sized CIM | `{"<root>/networking/<file>.tf": hcl, ...}` |
| `compute` | `render_compute(cim, required_tags=...)` | CIM, tag map | `{"<root>/compute/<vm>.tf": hcl, ...}` (one file per ComputeUnit) |
| `storage` | `render_storage(cim, required_tags=...)` | CIM, tag map | `{"<root>/storage/<vm>_disks.tf": hcl, ...}` |
| `placement` | `render_placement(cim, required_tags=...)` | CIM, tag map | `{"<root>/placement/<file>.tf": hcl}` |
| `runtime` | `render_runtime(cim, required_tags=...)` | CIM, tag map | `{"<root>/providers.tf": ..., "<root>/variables.tf": ...}` |

Contracts the kit checks and the pipeline relies on:

- **Keys are logical paths** `<root>/<resource_type>/<name>.tf` for the first four renderers; the
  assembler flattens them to `<root>/<resource_type>_<name>.tf`. `render_runtime` emits root files
  directly (`providers.tf` with the `terraform { required_providers { ... } }` and `provider`
  blocks, and `variables.tf`). Two logical keys must never flatten to the same name; names that
  differ only by case are rejected too.
- **Names come from the CIM and are untrusted.** Build file stems with
  `hopshift.targets.common.safe_file_stem`, Terraform identifiers with your own
  `_terraform_identifier`, and string literals with `hcl_string` / `hcl_value` (they escape
  quotes and neutralise `${`). The built-in renderers show the pattern.
- **Tags.** `required_tags` is the map every taggable resource must carry (`Environment`, `Owner`,
  `MigratedFrom`, plus whatever the operator configured). The assembler replaces the
  `Environment` and `Owner` values with `var.environment` / `var.owner` before calling the tagged
  renderers; `render_runtime` receives the literal values and must declare those two variables
  with them as defaults (`hopshift.targets.runtime_common.tag_variable_blocks` does this). Use
  `hcl_value` so bare `var.*` references are not quoted.
- **Determinism.** Same CIM, same output, byte for byte. No timestamps, no random names, no
  dict-order dependence.
- **Security rules** (`hopshift/pipeline/nodes/hcl_generator.py`, mirrored by the OPA bundle): no
  `provisioner` blocks, no `external` / `http` data sources, no `null_resource` / `local_file`,
  module sources must be local `./` paths, provider sources must be on the allow-list, no
  `0.0.0.0/0` ingress, no public IP attachments, no management ports open to the Internet.
- **Images.** The runtime declares `image_overrides` (`hopshift.targets.runtime_common.image_overrides_block`),
  a map from VM name to the image produced by the disk migration step; compute looks each VM up
  with a fallback variable.
- **Architectures.** The assembler refuses non-x86 ComputeUnits for every target today
  (`SUPPORTED_ARCHITECTURES_FOR_X86_TARGETS`); declare `architectures` on the spec honestly so
  the UI can warn before a run.

Provider sources are allow-listed. `hcl_generator._PROVIDER_SOURCE_ALLOWLIST` holds the sources of
the built-in hyperscalers and OpenStack; every registered target, plugin or built-in, adds its own
through `TargetSpec.extra["provider_sources"]` (the Proxmox target declares `bpg/proxmox` this way).
The pipeline guard and the kit's `guards` and `pipeline.allowlist` checks union the core list, the
common sources (`hashicorp/random`, `tls`, `time`) and the declared set; a source in none of them is
rejected with a message naming both places.

### Sizing table

`sizing_table.get_instance_type(vcpus: int, ram_mb: int) -> str` maps a shape to an instance type
or flavor. It must return a non-empty string for every positive pair (the kit tries 336 shapes
from 1 vCPU / 256 MB to 512 vCPU / 4 TB), be deterministic, and, when the table is bucketed by
vCPU, never pick a smaller shape for more RAM. The built-in pattern:

```python
_NIMBUS_SIZING_TABLE: dict[int, list[tuple[int, str]]] = {
    1: [(2048, "n1.small")],
    2: [(4096, "n1.medium"), (8192, "n1.large")],
    4: [(16384, "n2.xlarge"), (32768, "n2.2xlarge")],
}

def get_instance_type(vcpus: int, ram_mb: int) -> str:
    if vcpus <= 0 or ram_mb <= 0:
        raise ValueError("vcpus and ram_mb must be > 0")
    bucket = _select_vcpu_bucket(vcpus)              # exact, else next larger, else largest
    options = _NIMBUS_SIZING_TABLE[bucket]
    for ceiling, name in options:                    # closest RAM ceiling
        if ram_mb <= ceiling:
            return name
    return options[-1][1]
```

Keep the `*_SIZING_TABLE` / `_select_vcpu_bucket` names: the kit uses them to run the
monotonicity check (it is skipped for tables shaped differently).

### Compliance controls in Rego

The OPA bundle in `hopshift/validation/policies/` has two layers. The generic gate rules
(`package hopshift`: `no_open_ingress`, `tags_required`, `no_code_execution`, `encryption_at_rest`,
`no_public_s3`) are keyed by resource type, so a new provider's types are not covered until a
rule names them. The compliance controls (`package hopshift.compliance`, one file per target
under `policies/compliance/`) give each requirement an id, a level and framework references, and
are what the compliance report shows.

A control file for a new target follows `openstack.rego`:

```rego
package hopshift.compliance

import rego.v1

nimbus_controls := {
    "NIMBUS-SG-NO-OPEN-MGMT-PORTS": "enforce",
    "NIMBUS-VOLUME-ENCRYPTED": "advisory",
}

clouds contains "nimbus" if {
    some r in input.resources
    startswith(r.type, "nimbus_")
}

evaluated contains id if {
    "nimbus" in clouds
    some id, _ in nimbus_controls
}

nimbus_violation(id, r, message) := violation(id, nimbus_controls[id], r, message)

violations contains v if {
    some r in input.resources
    r.type == "nimbus_security_group_rule"
    object.get(r.config, "cidr", "") in open_cidrs
    some port in management_ports
    port_spec_covers(object.get(r.config, "port", "*"), port)
    v := nimbus_violation("NIMBUS-SG-NO-OPEN-MGMT-PORTS", r, sprintf("allows ingress on port %d from the internet", [port]))
}
```

Every violation has the shape
`{"control": "<ID>", "level": "enforce" | "advisory", "resource": "<type>.<name>", "file": "<path>", "message": "..."}`
(`violation(...)` in `common.rego` builds it). `enforce` violations also become `deny` messages
and fail the gate; `advisory` ones are reported only. `evaluated` must list the ids that applied
so the report can tell "passed" from "not applicable". Register the ids in `controls` by adding
`nimbus_controls` to the `object.union_n` in `common.rego`, add the matching `Control(...)`
entries (title, description, clouds, level, remediation, CIS / SOC 2 / HIPAA references) to
`hopshift/services/compliance/controls.py`, and add compliant and violating snippets to
`tests/validation/test_compliance_policies.py`. The bundle is one directory evaluated with a
single `opa eval --data`, so controls live in the core repository; a plugin repository keeps a
copy and runs `opa test` on it, and the kit's `compliance` check is skipped until the core bundle
knows the target. Full details in [compliance.md](compliance.md).

### Connection catalog

Deployments resolve credentials through the connections catalog
(`hopshift/services/connections/models.py`, `CATALOG`). To let operators deploy a target from the
UI: add a `ProviderSpec` with one `MethodSpec` per sign-in method and `FieldSpec`s for every
field (mark secrets `secret=True`), add a provider module next to `aws.py` / `openstack.py` with
`verify(...)` (calls the cloud and returns the identity) and `terraform_env(...)` (the
environment variables the Terraform provider reads), then set `connection_provider="nimbus"` on
the spec. The kit fails `spec.connection_provider` when the key is not in the catalog; leave it
`None` until the catalog entry exists. See [connections.md](connections.md).

### Entry point and conformance

```toml
# pyproject.toml of the plugin
[project]
name = "hopshift-nimbus"
dependencies = ["hopshift"]

[project.entry-points."hopshift.targets"]
nimbus = "hopshift_nimbus:TARGET"
```

Run the kit from the shell or from pytest:

```bash
hopshift targets list
hopshift targets check nimbus                       # fast: pipeline, render, layout, guards, parse, determinism, OPA, sizing
hopshift targets check nimbus --terraform           # plus terraform init/validate (and tflint when spec.tflint)
hopshift targets check nimbus --input my-discovery.json --format json
```

```python
# tests/test_conformance.py in the plugin repository; the fixtures come from the `hopshift`
# pytest plugin that an installed hopshift registers automatically
def test_nimbus_conforms(hopshift_target_conformance):
    hopshift_target_conformance("nimbus")
```

`HOPSHIFT_CONFORMANCE_TERRAFORM=1 pytest` adds the terraform checks (binaries and network needed).
The report lists every check as `PASS`, `FAIL` or `SKIP` with a one-line message; the fixture
fails the test with the full report. Checks that are skipped with a reason (no `opa` binary, no
docs path, no compliance controls yet) do not fail the run. The same calls are available in
Python: `hopshift.testing.check_target(spec_or_name, discovery_fixture=..., run_terraform=...)`
returns a `ConformanceReport` (`.passed`, `.failures`, `.get(name)`, `.render()`, `.to_dict()`).

### Minimal complete example

A target that renders every ComputeUnit as a `random_pet` (it passes the fast checks, which is
what `experimental` means; a real target renders real resources):

```
hopshift-nimbus/
    pyproject.toml
    hopshift_nimbus/__init__.py
    hopshift_nimbus/network.py
    hopshift_nimbus/compute.py
    hopshift_nimbus/storage.py
    hopshift_nimbus/placement.py
    hopshift_nimbus/runtime.py
    hopshift_nimbus/sizing_table.py
    docs/nimbus.md
    tests/test_conformance.py
```

```python
# hopshift_nimbus/__init__.py
from hopshift.targets.registry import TargetSpec

TARGET = TargetSpec(
    name="nimbus", label="Nimbus Cloud", blurb="random pets standing in for instances",
    package="hopshift_nimbus", docs="docs/nimbus.md", extra={"provider_sources": {"hashicorp/random"}},
)
```

```python
# hopshift_nimbus/network.py
from hopshift.cim.schema import CanonicalInfrastructureModel
from hopshift.targets.common import hcl_string, safe_file_stem


def render_networking(cim: CanonicalInfrastructureModel) -> dict[str, str]:
    lines = []
    for switch in cim.network_topology.distributed_switches:
        for segment in switch.port_groups:
            ident = safe_file_stem(segment.name).replace("-", "_").replace(".", "_").lower()
            lines.append(f'resource "random_pet" "segment_{ident}" {{\n  prefix = {hcl_string(segment.name)}\n}}\n')
    return {"nimbus-migration/networking/segments.tf": "".join(lines) or "# no segments\n"}
```

```python
# hopshift_nimbus/compute.py
from hopshift.cim.schema import CanonicalInfrastructureModel
from hopshift.targets.common import hcl_string, hcl_value, safe_file_stem
from hopshift_nimbus.sizing_table import get_instance_type


def render_compute(cim: CanonicalInfrastructureModel, required_tags: dict[str, str] | None = None) -> dict[str, str]:
    tags = required_tags or {}
    output: dict[str, str] = {}
    for unit in cim.compute_units:
        stem = safe_file_stem(unit.name)
        keepers = "".join(f"    {key} = {hcl_value(value)}\n" for key, value in sorted(tags.items()))
        output[f"nimbus-migration/compute/{stem}.tf"] = (
            f'resource "random_pet" "{stem.replace("-", "_").replace(".", "_").lower()}" {{\n'
            f"  prefix = {hcl_string(unit.name)}\n"
            f'  keepers = {{\n    size = "{get_instance_type(unit.vcpus, unit.ram_mb)}"\n{keepers}  }}\n}}\n'
        )
    return output
```

```python
# hopshift_nimbus/storage.py and placement.py: nothing to render yet
def render_storage(cim, required_tags=None) -> dict[str, str]:
    return {}
```

```python
# hopshift_nimbus/runtime.py
from hopshift.targets.runtime_common import literal_default, tag_variable_blocks


def render_runtime(cim, required_tags=None) -> dict[str, str]:
    tags = required_tags or {}
    providers_tf = (
        'terraform {\n  required_version = ">= 1.5.0"\n  required_providers {\n'
        '    random = {\n      source  = "hashicorp/random"\n      version = "~> 3.6"\n    }\n  }\n}\n\n'
        'provider "random" {}\n'
    )
    variables_tf = tag_variable_blocks(literal_default(tags.get("Environment"), "dev"), literal_default(tags.get("Owner"), "platform-team"))
    return {"nimbus-migration/providers.tf": providers_tf, "nimbus-migration/variables.tf": variables_tf}
```

```python
# hopshift_nimbus/sizing_table.py
def get_instance_type(vcpus: int, ram_mb: int) -> str:
    if vcpus <= 0 or ram_mb <= 0:
        raise ValueError("vcpus and ram_mb must be > 0")
    if vcpus <= 2 and ram_mb <= 4096:
        return "n1.small"
    if vcpus <= 8 and ram_mb <= 32768:
        return "n1.medium"
    return "n1.large"
```

```python
# tests/test_conformance.py
def test_nimbus_conforms(hopshift_target_conformance):
    hopshift_target_conformance("nimbus")
```

## Source plugins

### SourceSpec

```python
from hopshift.sources.registry import SourceSpec
from hopshift_hyperv.translator import translate

SOURCE = SourceSpec(
    name="hyperv",                                   # lower-case identifier
    label="Microsoft Hyper-V",
    blurb="VMs, VHDX disks, virtual switches, failover clusters",
    schema_names=("hyperv-discovery-stage1",),       # metadata.schema_name values this source accepts
    translate=translate,                             # (discovery: dict, target: str) -> CanonicalInfrastructureModel
    platform="hyperv",                               # a hopshift.cim.schema.SourcePlatform value
    tier="experimental",
    collector="PowerShell module hopshift-discovery-hyperv",
    docs="docs/hyperv.md",
    extra={"fixture": "tests/fixtures/hyperv.json"}, # used by the conformance tests
)
```

```toml
[project.entry-points."hopshift.sources"]
hyperv = "hopshift_hyperv:SOURCE"
```

The pipeline picks the translator from the payload's `metadata.schema_name`
(`hopshift.sources.resolve_translator`); a payload without it falls back to the VMware schema.

### Discovery schema contract

The ingest node (`hopshift/pipeline/nodes/ingest.py`) enforces the minimum every collector must
produce, whatever the platform:

- the root is a JSON object with `metadata` (`schema_name`, `schema_version`, `generated_at`) and a
  `virtual_machines` list; every entry is an object;
- each VM has a name (`vm_name` or `name`), a stable id (`discovery_key`, `moid` or `uuid`),
  `vcpus` and `ram_mb` (missing values default to 1 with a warning, which makes sizing wrong);
- optional lists `disks[]` and `networks[]`, flags for blockers, `power_state`, `architecture`,
  and the optional 1.1 collections `clusters[]` and `distributed_switches[]`.

`blocker_parser` and `enricher` run **before** the translator: hard-blocked VMs are removed from
`virtual_machines` and quarantined, names, sizes, `disks[]` and `networks[]` are normalised. The
translator still has to cope with the raw payload (the kit calls it on the unfiltered fixture).
The field names of the VMware schema are documented in [discovery-schema.md](discovery-schema.md);
a new collector may use its own names as long as the translator maps them.

### Translator contract

`translate(discovery: dict, target: str) -> CanonicalInfrastructureModel` (`cim_schema_version` 1.1):

- set `source` (`SourceEndpoint`): `platform` is a `SourcePlatform` value (add one to the enum and
  to `MIGRATED_FROM_TAG` when the platform is new), plus name, hostname, schema name/version and
  `discovered_at`. `cim.migrated_from` becomes the `MigratedFrom` tag on every resource;
- set `target_provider` to the `target` argument (the CIM normalises it with `TargetProvider`);
- one `ComputeUnit` per VM in the payload, blocked ones included (quarantine is the pipeline's
  job); `id` non-empty and unique; `architecture` set from the collector (`x86_64`, `aarch64`,
  `ppc64le`, `s390x`), `guest_family`, `firmware`, `power_state`, `snapshot_count` when known;
- `blockers` contains canonical names only (`hopshift.cim.blockers.KNOWN_BLOCKERS`) and
  `migration_status` is `blocked` when any hard blocker applies, `needs_review` for soft ones;
- `storage_volumes` with unique ids per unit; `nics` whose `port_group_ref` names a segment of
  the `network_topology`; `cluster_ref` names an entry of `clusters` with its `ClusterSemantics`;
- the model must survive `model_validate_json(model_dump_json())` unchanged (no custom types).

### Blockers

`hopshift/cim/blockers.py` is the single vocabulary. `blockers_for_vm(vm, platform)` combines the
explicit `migration_blockers` list (any spelling in `_ALIASES`) with the platform's flag table
(`FLAG_TO_BLOCKER[platform]`, falling back to generic flags such as `is_encrypted`,
`has_passthrough_disks`, `has_shared_disks`, `is_template`), `power_state`, snapshots and
`architecture`. A collector that emits different flag names adds a row to `FLAG_TO_BLOCKER` in the
core; a translator that needs a new blocker adds it to `HARD_BLOCKERS` or `SOFT_BLOCKERS` and
`_ALIASES` with a test. Never invent blocker strings in the translator: the kit rejects them.

### Fixtures and conformance

Ship at least one discovery fixture produced by the real collector (secrets and hostnames
redacted) and point `SourceSpec.extra["fixture"]` at it. Then:

```bash
hopshift sources list
hopshift sources check hyperv --input tests/fixtures/hyperv.json
```

```python
def test_hyperv_conforms(hopshift_source_conformance):
    hopshift_source_conformance("hyperv", "tests/fixtures/hyperv.json")
```

`check_source` verifies the spec, the payload (schema name, ingest contract), the translation
(`source.platform`, VM count, canonical blockers, unique ids, resolvable references, JSON round
trip) and finally renders the CIM with **every registered target** after the real
`ingest -> blocker_parser -> enricher -> sizer` nodes. The built-in VMware source is the reference:
`hopshift/sources/vmware.py`, [sources/vmware.md](sources/vmware.md).

### Minimal complete example

```
hopshift-hyperv/
    pyproject.toml                       # [project.entry-points."hopshift.sources"] hyperv = "hopshift_hyperv:SOURCE"
    hopshift_hyperv/__init__.py          # SOURCE = SourceSpec(...) as above
    hopshift_hyperv/translator.py
    tests/fixtures/hyperv.json
    tests/test_conformance.py            # two lines, as above
    docs/hyperv.md
```

```python
# hopshift_hyperv/translator.py
from typing import Any

from hopshift.cim.blockers import HARD_BLOCKERS, blockers_for_vm
from hopshift.cim.schema import (
    NIC, Architecture, CanonicalInfrastructureModel, ComputeUnit, MigrationStatus, NetworkSegment,
    NetworkTopology, SourceEndpoint, SourcePlatform, StorageVolume, VirtualSwitch,
)


def translate(discovery: dict[str, Any], target: str) -> CanonicalInfrastructureModel:
    metadata = discovery.get("metadata") or {}
    vms = [vm for vm in discovery.get("virtual_machines", []) if isinstance(vm, dict)]

    switches: dict[str, dict[str, NetworkSegment]] = {}
    for vm in vms:
        for adapter in vm.get("networks", []) or []:
            switch = str(adapter.get("switch_name") or "default")
            name = str(adapter.get("network_name") or f"{switch}-vlan-{adapter.get('vlan_id', 0)}")
            switches.setdefault(switch, {}).setdefault(name, NetworkSegment(name=name, vlan_id=str(adapter.get("vlan_id") or "")))

    units = []
    for vm in vms:
        blockers = blockers_for_vm(vm, platform=SourcePlatform.HYPERV)
        status = MigrationStatus.BLOCKED if set(blockers) & HARD_BLOCKERS else MigrationStatus.NEEDS_REVIEW if blockers else MigrationStatus.READY
        units.append(ComputeUnit(
            id=str(vm.get("vm_id") or vm.get("vm_name")),
            name=str(vm.get("vm_name")),
            vcpus=int(vm.get("vcpus") or 1),
            ram_mb=int(vm.get("ram_mb") or 1),
            migration_status=status,
            blockers=blockers,
            architecture=Architecture.X86_64,
            nics=[NIC(name=f"nic{i}", port_group_ref=str(a.get("network_name") or f"{a.get('switch_name', 'default')}-vlan-{a.get('vlan_id', 0)}"))
                  for i, a in enumerate(vm.get("networks", []) or [])],
            storage_volumes=[StorageVolume(id=str(d.get("path") or f"disk-{i}"), size_gb=max(1, int(d.get("size_gb") or 1)))
                             for i, d in enumerate(vm.get("disks", []) or [])],
        ))

    return CanonicalInfrastructureModel(
        source=SourceEndpoint(platform=SourcePlatform.HYPERV, name=str(metadata.get("host") or ""),
                              schema_name=metadata.get("schema_name"), schema_version=metadata.get("schema_version"),
                              discovered_at=metadata.get("generated_at")),
        source_vcenter=str(metadata.get("host") or ""),
        target_provider=target,
        network_topology=NetworkTopology(distributed_switches=[VirtualSwitch(name=s, port_groups=list(p.values())) for s, p in switches.items()]),
        compute_units=units,
    )
```

## Checklist before asking for a tier

- `hopshift targets check <name>` / `hopshift sources check <name> --input <fixture>` pass with
  no `FAIL` lines; read the `SKIP` lines and make sure each one is intentional.
- `experimental -> validated`: `--terraform` passes, the pair has an integration test in CI, the
  provider sources are on the core allow-list, compliance controls exist for the target and the
  renderers satisfy every `enforce` control.
- `validated -> tested`: a plan and apply against a real account or lab, documented and linked
  from `support.yaml` (`evidence`), with the caveats in `notes`.
- `support.yaml` updated, `hopshift matrix render` run, `docs/support-matrix.md` committed.
