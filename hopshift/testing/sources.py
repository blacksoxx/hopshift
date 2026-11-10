"""Source conformance: does a discovery translator produce a CIM every target can render?

`check_source(spec_or_name, payload)` records:

- `spec`, `spec.docs`      metadata sanity (label, blurb, tier, platform value, docs path)
- `payload`                the fixture carries one of the spec's schema names and passes the
                           ingest contract (a `virtual_machines` list of objects)
- `translate`              the translator returns a CanonicalInfrastructureModel
- `source.platform`        set (not unknown) and equal to the spec's platform when declared
- `vm_count`               one ComputeUnit per discovered VM (blockers are the pipeline's job)
- `blockers`               only canonical names (hopshift.cim.blockers.KNOWN_BLOCKERS); hard
                           blockers imply migration_status=blocked
- `ids`, `references`      unique non-empty ids; NIC and cluster references resolve
- `roundtrip`              the CIM survives a JSON round trip unchanged
- `render[<target>]`       every registered target renders a flat root module from the CIM
                           after the real ingest -> blocker_parser -> enricher -> sizer nodes
"""
from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any, TypeVar

from hopshift.cim.blockers import HARD_BLOCKERS, KNOWN_BLOCKERS
from hopshift.cim.schema import CanonicalInfrastructureModel, MigrationStatus, SourcePlatform
from hopshift.pipeline.generation.deterministic import render_deterministic
from hopshift.pipeline.nodes.ingest import validate_discovery_payload
from hopshift.sources import registry as sources
from hopshift.sources.registry import TIERS, SourceSpec
from hopshift.targets import registry as targets
from hopshift.testing._common import FixtureInput, existing_path, load_payload, pipeline_cim, required_tags
from hopshift.testing.report import ConformanceReport, SkipCheck
from hopshift.testing.targets import _check_layout

T = TypeVar("T")


def check_source(
    spec_or_name: SourceSpec | str,
    payload: FixtureInput,
    *,
    target_names: Sequence[str] | None = None,
) -> ConformanceReport:
    """Run every conformance check for a source against one discovery payload (a dict or a path).

    `target_names` limits the render checks; by default every registered target is rendered.
    Unknown source names raise `hopshift.sources.registry.UnknownSource`.
    """
    spec = spec_or_name if isinstance(spec_or_name, SourceSpec) else sources.get(spec_or_name)
    report = ConformanceReport(kind="source", subject=spec.name, label=spec.label)

    report.run("spec", lambda: _check_spec(spec))
    report.run("spec.docs", lambda: _check_docs(spec))

    try:
        data = load_payload(payload)
    except Exception as exc:  # noqa: BLE001 - unreadable payload is a report line, not a crash
        report.add_fail("payload", f"{type(exc).__name__}: {exc}")
        return report

    report.run("payload", lambda: _check_payload(spec, data))

    names = list(target_names) if target_names else targets.names()
    if not names:
        report.add_fail("targets", "no target is registered; nothing can be rendered")
        return report

    cim = _capture(report, "translate", lambda: _translate(spec, data, names[0]))
    downstream = ("source.platform", "vm_count", "blockers", "ids", "references", "roundtrip")
    if cim is None:
        for name in downstream:
            report.add_skip(name, "not run: translate failed")
        for name in names:
            report.add_skip(f"render[{name}]", "not run: translate failed")
        return report

    report.run("source.platform", lambda: _check_platform(spec, cim))
    report.run("vm_count", lambda: _check_vm_count(data, cim))
    report.run("blockers", lambda: _check_blockers(cim))
    report.run("ids", lambda: _check_ids(cim))
    report.run("references", lambda: _check_references(cim))
    report.run("roundtrip", lambda: _check_roundtrip(cim))
    for name in names:
        report.run(f"render[{name}]", lambda t=name: _check_render(spec, data, t))
    return report


def _capture(report: ConformanceReport, name: str, check: Callable[[], tuple[T, str]]) -> T | None:
    holder: list[T] = []

    def wrapped() -> str:
        value, message = check()
        holder.append(value)
        return message

    report.run(name, wrapped)
    return holder[0] if holder else None


# ── spec and payload ──────────────────────────────────────────────────────────


def _check_spec(spec: SourceSpec) -> str:
    problems: list[str] = []
    if not spec.label.strip():
        problems.append("label is empty")
    if not spec.blurb.strip():
        problems.append("blurb is empty (one line: what is discovered)")
    if spec.tier not in TIERS:
        problems.append(f"tier {spec.tier!r} is not one of {', '.join(TIERS)}")
    if not callable(spec.translate):
        problems.append("translate is not callable")
    if spec.platform:
        try:
            SourcePlatform(spec.platform)
        except ValueError:
            problems.append(f"platform {spec.platform!r} is not a SourcePlatform value ({', '.join(p.value for p in SourcePlatform)})")
    assert not problems, "; ".join(problems)
    return f"tier={spec.tier} platform={spec.platform or '-'} schemas={','.join(spec.schema_names)}"


def _check_docs(spec: SourceSpec) -> str:
    if not spec.docs:
        raise SkipCheck("no docs path declared on the spec")
    path = existing_path(spec.docs)
    assert path is not None, f"docs path {spec.docs!r} does not exist (relative to the CWD or the hopshift checkout)"
    return str(spec.docs)


def _check_payload(spec: SourceSpec, data: dict[str, Any]) -> str:
    metadata = data.get("metadata")
    schema_name = str(metadata.get("schema_name") or "").strip() if isinstance(metadata, dict) else ""
    assert schema_name, "metadata.schema_name is missing; cim_mapper selects the translator from it"
    accepted = {name.strip().lower() for name in spec.schema_names}
    assert schema_name.lower() in accepted, (
        f"metadata.schema_name {schema_name!r} is not one of the spec's schema_names {list(spec.schema_names)}"
    )
    warnings = validate_discovery_payload(data)  # raises ValueError on structural problems
    vms = data.get("virtual_machines", [])
    message = f"schema {schema_name}, {len(vms)} virtual_machines"
    if warnings:
        message += f"; ingest warnings: {' | '.join(warnings)}"
    return message


# ── translation ───────────────────────────────────────────────────────────────


def _translate(spec: SourceSpec, data: dict[str, Any], target: str) -> tuple[CanonicalInfrastructureModel, str]:
    cim = spec.translate(json.loads(json.dumps(data)), target)
    assert isinstance(cim, CanonicalInfrastructureModel), (
        f"translate returned {type(cim).__name__}, expected CanonicalInfrastructureModel"
    )
    assert cim.target_provider == target, f"target_provider is {cim.target_provider!r}, expected {target!r}"
    return cim, (
        f"{len(cim.compute_units)} compute units, {len(cim.clusters)} clusters, "
        f"{len(cim.network_topology.distributed_switches)} switches (CIM {cim.cim_schema_version})"
    )


def _check_platform(spec: SourceSpec, cim: CanonicalInfrastructureModel) -> str:
    platform = cim.source.platform
    assert platform != SourcePlatform.UNKNOWN, "source.platform is unknown; the translator must set it"
    if spec.platform:
        assert platform.value == spec.platform, f"source.platform is {platform.value!r}, the spec declares {spec.platform!r}"
    name = cim.source_name or "(no source name)"
    return f"{platform.value}, source {name}, MigratedFrom={cim.migrated_from}"


def _check_vm_count(data: dict[str, Any], cim: CanonicalInfrastructureModel) -> str:
    discovered = len(data.get("virtual_machines", []))
    translated = len(cim.compute_units)
    assert translated == discovered, (
        f"{discovered} VMs discovered but {translated} ComputeUnits translated; blocked VMs must be kept "
        "(the blocker_parser node quarantines them before translation)"
    )
    return f"{translated} ComputeUnits for {discovered} VMs"


def _check_blockers(cim: CanonicalInfrastructureModel) -> str:
    unknown: dict[str, list[str]] = {}
    inconsistent: list[str] = []
    for unit in cim.compute_units:
        extra = sorted(set(unit.blockers) - KNOWN_BLOCKERS)
        if extra:
            unknown[unit.name] = extra
        if set(unit.blockers) & HARD_BLOCKERS and unit.migration_status != MigrationStatus.BLOCKED:
            inconsistent.append(f"{unit.name} ({unit.migration_status.value})")
    problems: list[str] = []
    if unknown:
        problems.append(
            "non-canonical blockers: " + "; ".join(f"{name}: {', '.join(items)}" for name, items in unknown.items())
            + " (use hopshift.cim.blockers.normalize_blocker / blockers_for_vm)"
        )
    if inconsistent:
        problems.append("units with a hard blocker are not marked blocked: " + ", ".join(inconsistent))
    assert not problems, "; ".join(problems)
    counts = {status.value: 0 for status in MigrationStatus}
    for unit in cim.compute_units:
        counts[unit.migration_status.value] += 1
    return ", ".join(f"{count} {status}" for status, count in counts.items()) + "; all blockers canonical"


def _check_ids(cim: CanonicalInfrastructureModel) -> str:
    problems: list[str] = []
    seen: dict[str, str] = {}
    for unit in cim.compute_units:
        if not unit.id.strip():
            problems.append(f"{unit.name}: empty id")
        elif unit.id in seen:
            problems.append(f"{unit.name} and {seen[unit.id]} share id {unit.id!r}")
        seen[unit.id] = unit.name
        volume_ids = [volume.id for volume in unit.storage_volumes]
        if len(volume_ids) != len(set(volume_ids)):
            problems.append(f"{unit.name}: duplicate storage volume ids")
    assert not problems, "; ".join(problems)
    return f"{len(seen)} unique ComputeUnit ids"


def _check_references(cim: CanonicalInfrastructureModel) -> str:
    segments = {segment.name for switch in cim.network_topology.distributed_switches for segment in switch.port_groups}
    clusters = {cluster.name for cluster in cim.clusters}
    problems: list[str] = []
    for unit in cim.compute_units:
        for nic in unit.nics:
            if nic.port_group_ref not in segments:
                problems.append(f"{unit.name}: NIC {nic.name} references unknown segment {nic.port_group_ref!r}")
        if unit.cluster_ref and unit.cluster_ref not in clusters:
            problems.append(f"{unit.name}: cluster_ref {unit.cluster_ref!r} is not in clusters")
    assert not problems, "; ".join(problems)
    return f"{len(segments)} segments, {len(clusters)} clusters; every NIC and cluster reference resolves"


def _check_roundtrip(cim: CanonicalInfrastructureModel) -> str:
    again = CanonicalInfrastructureModel.model_validate_json(cim.model_dump_json())
    assert again == cim, "CIM changed after a JSON round trip (model_dump_json -> model_validate_json)"
    return "model_dump_json -> model_validate_json is lossless"


def _check_render(spec: SourceSpec, data: dict[str, Any], target: str) -> str:
    target_spec = targets.get(target)
    state = pipeline_cim(data, target, translate=spec.translate)
    cim = state["sized_cim"]
    quarantined = len(state.get("quarantine_queue", []))
    if not cim.compute_units:
        raise SkipCheck(f"every VM was quarantined ({quarantined}); nothing to render")
    files = render_deterministic(provider=target, cim=cim, required_tags=required_tags(cim))
    _check_layout(target_spec, files)
    return f"{len(files)} files for {len(cim.compute_units)} compute units ({quarantined} quarantined)"
