"""Build the compliance report from OPA compliance violations and render it as Markdown."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from vma.compliance.controls import (
    ALL_CLOUDS,
    FRAMEWORKS,
    Control,
    controls_for_cloud,
    get_control,
)

STATUSES: tuple[str, ...] = ("pass", "fail", "advisory", "not_applicable")

_FRAMEWORK_TITLES = {"cis": "CIS Benchmarks", "soc2": "SOC 2 TSC", "hipaa": "HIPAA Security Rule"}

_ATTESTATION_NOTE = (
    "SOC 2 and HIPAA are organisational attestations, not properties of Terraform. This report is "
    "technical evidence for the mapped criteria (configuration of the generated resources); policies, "
    "procedures, risk analysis and the audit itself remain the organisation's responsibility."
)


def build_report(
    cloud: str,
    violations: Sequence[Mapping[str, Any]],
    evaluated: Sequence[str],
    validation_result: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Turn OPA compliance output into the report stored in state and written by the reporter.

    - `violations`: data.vmwaremigration.compliance.violations (control, level, resource, file, message)
    - `evaluated`: control ids the policy bundle applied to the input; a catalog control that is not
      in this list (OPA disabled, evaluation failed, wrong cloud) is reported as not_applicable.
    """
    normalized_cloud = cloud.strip().lower() if isinstance(cloud, str) else ""
    validation = dict(validation_result or {})
    evaluated_ids = {str(item) for item in evaluated if str(item).strip()}

    by_control: dict[str, list[dict[str, str]]] = defaultdict(list)
    levels_seen: dict[str, str] = {}
    for raw in violations:
        control_id = str(raw.get("control", "")).strip()
        if not control_id:
            continue
        entry = {
            "resource": str(raw.get("resource", "")),
            "file": str(raw.get("file", "")),
            "message": str(raw.get("message", "")),
        }
        by_control[control_id].append(entry)
        levels_seen.setdefault(control_id, str(raw.get("level", "")))

    catalog = controls_for_cloud(normalized_cloud) if normalized_cloud in ALL_CLOUDS else []
    known_ids = {control.id for control in catalog}

    # Controls the policy bundle reported but the catalog does not know (drift); keep them visible.
    extra_ids = sorted((set(by_control) | evaluated_ids) - known_ids)
    extra_controls = [_unknown_control(control_id, levels_seen.get(control_id) or "advisory") for control_id in extra_ids]

    controls_payload: list[dict[str, Any]] = []
    for control in [*catalog, *extra_controls]:
        findings = sorted(by_control.get(control.id, []), key=lambda item: (item["resource"], item["message"]))
        status = _status_for(control, findings, control.id in evaluated_ids)
        controls_payload.append(
            {
                "id": control.id,
                "title": control.title,
                "description": control.description,
                "level": control.level,
                "status": status,
                "frameworks": {name: list(control.frameworks.get(name, [])) for name in FRAMEWORKS},
                "resources": sorted({item["resource"] for item in findings if item["resource"]}),
                "messages": [_format_finding(item) for item in findings],
                "remediation": control.remediation,
            }
        )

    warnings: list[str] = []
    if not evaluated_ids:
        warnings.append(
            "No compliance controls were evaluated (OPA disabled, unavailable, or the output matched no supported cloud); "
            "every control is reported as not_applicable."
        )
    if normalized_cloud not in ALL_CLOUDS:
        warnings.append(f"Unknown target cloud '{cloud}'; no catalog controls apply.")
    for item in validation.get("errors") or []:
        text = str(item)
        if text.startswith("opa ") or text.startswith("opa_client") or text.startswith("OPA "):
            warnings.append(text)

    summary = _count_statuses(controls_payload)
    frameworks_payload = {
        name: _count_statuses([control for control in controls_payload if control["frameworks"].get(name)])
        for name in FRAMEWORKS
    }

    return {
        "generated_at": _now(),
        "cloud": normalized_cloud or str(cloud),
        "gate_passed": bool(validation.get("passed", False)) if validation else None,
        "summary": summary,
        "controls": controls_payload,
        "frameworks": frameworks_payload,
        "warnings": warnings,
        "note": _ATTESTATION_NOTE,
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    cloud = str(report.get("cloud", "")).upper() or "UNKNOWN"
    summary = dict(report.get("summary") or {})
    controls = [dict(item) for item in report.get("controls") or []]
    frameworks = dict(report.get("frameworks") or {})
    gate = report.get("gate_passed")
    gate_text = "passed" if gate is True else "failed" if gate is False else "not evaluated"

    lines: list[str] = [
        f"# Compliance Report - {cloud}",
        "",
        f"- Generated: {report.get('generated_at', '')}",
        f"- Cloud: {report.get('cloud', '')}",
        f"- Validation gate: {gate_text}",
        "",
        "## Summary",
        "",
        "| Controls | Passed | Failed | Advisory findings | Not applicable |",
        "| --- | --- | --- | --- | --- |",
        "| {controls} | {passed} | {failed} | {advisory} | {not_applicable} |".format(
            **{key: summary.get(key, 0) for key in ("controls", "passed", "failed", "advisory", "not_applicable")}
        ),
        "",
        "## Framework coverage",
        "",
        "| Framework | Controls | Passed | Failed | Advisory findings | Not applicable |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for name in FRAMEWORKS:
        counts = dict(frameworks.get(name) or {})
        lines.append(
            "| {title} | {controls} | {passed} | {failed} | {advisory} | {not_applicable} |".format(
                title=_FRAMEWORK_TITLES.get(name, name),
                **{key: counts.get(key, 0) for key in ("controls", "passed", "failed", "advisory", "not_applicable")},
            )
        )

    lines.extend(
        [
            "",
            "## Controls",
            "",
            "| ID | Title | Level | Status | CIS | SOC 2 | HIPAA |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for control in controls:
        refs = dict(control.get("frameworks") or {})
        lines.append(
            "| {id} | {title} | {level} | {status} | {cis} | {soc2} | {hipaa} |".format(
                id=control.get("id", ""),
                title=_cell(control.get("title", "")),
                level=control.get("level", ""),
                status=control.get("status", ""),
                cis=_cell(", ".join(refs.get("cis") or []) or "-"),
                soc2=_cell(", ".join(refs.get("soc2") or []) or "-"),
                hipaa=_cell(", ".join(refs.get("hipaa") or []) or "-"),
            )
        )

    findings = [control for control in controls if control.get("status") in {"fail", "advisory"}]
    lines.extend(["", "## Findings", ""])
    if not findings:
        lines.append("No findings.")
    for control in findings:
        lines.append(f"### {control.get('id')} - {_cell(str(control.get('title', '')))} ({control.get('status')})")
        lines.append("")
        for message in control.get("messages") or []:
            lines.append(f"- {message}")
        if control.get("remediation"):
            lines.append("")
            lines.append(f"Remediation: {control['remediation']}")
        lines.append("")

    warnings = [str(item) for item in report.get("warnings") or []]
    if warnings:
        lines.extend(["## Warnings", ""])
        lines.extend(f"- {item}" for item in warnings)
        lines.append("")

    lines.extend(["## Note", "", str(report.get("note") or _ATTESTATION_NOTE), ""])
    return "\n".join(lines)


# ── helpers ───────────────────────────────────────────────────────────────────


def _status_for(control: Control, findings: list[dict[str, str]], was_evaluated: bool) -> str:
    if not was_evaluated and not findings:
        return "not_applicable"
    if not findings:
        return "pass"
    return "fail" if control.level == "enforce" else "advisory"


def _count_statuses(controls: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"controls": len(controls), "passed": 0, "failed": 0, "advisory": 0, "not_applicable": 0}
    for control in controls:
        status = control.get("status")
        if status == "pass":
            counts["passed"] += 1
        elif status == "fail":
            counts["failed"] += 1
        elif status == "advisory":
            counts["advisory"] += 1
        elif status == "not_applicable":
            counts["not_applicable"] += 1
    return counts


def _unknown_control(control_id: str, level: str) -> Control:
    known = get_control(control_id)
    if known is not None:
        return known
    normalized_level = "enforce" if level == "enforce" else "advisory"
    return Control(
        id=control_id,
        title=f"Unknown control {control_id}",
        description="Reported by the policy bundle but missing from vma/compliance/controls.py.",
        clouds=ALL_CLOUDS,
        level=normalized_level,  # type: ignore[arg-type]
        remediation="Add this control to the catalog so it carries a title, framework references and remediation.",
        frameworks={name: [] for name in FRAMEWORKS},
    )


def _format_finding(item: Mapping[str, str]) -> str:
    resource = item.get("resource") or "(unknown resource)"
    file_name = item.get("file") or ""
    message = item.get("message") or ""
    location = f"{resource} ({file_name})" if file_name else resource
    return f"{location}: {message}" if message else location


def _cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
