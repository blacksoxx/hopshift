from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from loguru import logger

try:
    from rich.console import Console
    from rich.table import Table
except Exception:  # pragma: no cover - optional dependency fallback
    Console = None  # type: ignore[assignment]
    Table = None  # type: ignore[assignment]

from hopshift.pipeline.state import AssessmentResult, MigrationState


def assess_reporter(state: MigrationState) -> MigrationState:
    """Write assessment artifacts and render a colored terminal summary table."""
    next_state = cast(MigrationState, dict(state))

    assessment_result = next_state.get("assessment_result")
    if not isinstance(assessment_result, dict):
        raise ValueError("assess_reporter: assessment_result must be present")

    config = next_state.get("config", {})
    if not isinstance(config, dict):
        config = {}

    output_cfg = _get_mapping(config, "output")
    base_dir = Path(_get_str(output_cfg, "base_dir", "output")).resolve()
    json_filename = _get_str(output_cfg, "assessment_report_json_filename", "assessment_report.json")
    md_filename = _get_str(output_cfg, "assessment_report_markdown_filename", "assessment_report.md")

    base_dir.mkdir(parents=True, exist_ok=True)

    assessment_payload = cast(AssessmentResult, assessment_result)

    json_path = base_dir / json_filename
    json_path.write_text(json.dumps(assessment_payload, indent=2, ensure_ascii=True), encoding="utf-8")

    md_path = base_dir / md_filename
    md_path.write_text(_render_markdown(assessment_payload), encoding="utf-8")

    _render_terminal_table(assessment_payload)

    messages = list(next_state.get("messages", []))
    messages.append(
        "assess_reporter: wrote_json={} wrote_markdown={} resources={}".format(
            json_path,
            md_path,
            assessment_payload["summary"]["total_resources"],
        )
    )

    next_state["messages"] = messages
    next_state["status"] = "succeeded"

    logger.info(
        "assess_reporter: wrote assessment artifacts to {} (resources={})",
        base_dir,
        assessment_payload["summary"]["total_resources"],
    )

    return next_state


def _render_terminal_table(assessment: AssessmentResult) -> None:
    if Console is None or Table is None:
        summary = assessment["summary"]
        print(
            "Migration Risk Assessment: total={total} safe={safe} caution={caution} elevated={elevated} critical={critical}".format(
                total=summary["total_resources"],
                safe=summary["safe"],
                caution=summary["caution"],
                elevated=summary["elevated"],
                critical=summary["critical"],
            )
        )
        return

    table = Table(title="Migration Risk Assessment")
    table.add_column("Type", style="bold")
    table.add_column("Name")
    table.add_column("Risk", justify="center")
    table.add_column("Score", justify="right")
    table.add_column("Reason")

    level_style = {
        "safe": "green",
        "caution": "yellow",
        "elevated": "dark_orange3",
        "critical": "red",
    }

    for resource in assessment["resources"]:
        level = resource["risk_level"]
        reason = resource["reasons"][0] if resource["reasons"] else "no explicit migration risk detected"
        table.add_row(
            resource["resource_type"],
            resource["resource_name"],
            level.upper(),
            str(resource["risk_score"]),
            reason,
            style=level_style.get(level, "white"),
        )

    summary = assessment["summary"]
    console = Console()
    console.print(table)
    console.print(
        "Summary: total={total} safe={safe} caution={caution} elevated={elevated} critical={critical}".format(
            total=summary["total_resources"],
            safe=summary["safe"],
            caution=summary["caution"],
            elevated=summary["elevated"],
            critical=summary["critical"],
        )
    )


def _render_markdown(assessment: AssessmentResult) -> str:
    summary = assessment["summary"]

    lines = [
        "# Migration Assessment Report",
        "",
        f"- GeneratedAt: {assessment['generated_at']}",
        f"- SourceVCenter: {assessment['source_vcenter']}",
        f"- TargetProvider: {assessment['target_provider']}",
        "",
        "## Summary",
        f"- TotalResources: {summary['total_resources']}",
        f"- Safe: {summary['safe']}",
        f"- Caution: {summary['caution']}",
        f"- Elevated: {summary['elevated']}",
        f"- Critical: {summary['critical']}",
        "",
        "## Resource Risks",
        "",
        "| Type | Resource | Risk | Score | SafeToMigrate | Reason | MissingData |",
        "|---|---|---|---:|---|---|---|",
    ]

    for resource in assessment["resources"]:
        reason = resource["reasons"][0] if resource["reasons"] else "none"
        missing = "; ".join(resource["missing_data"]) if resource["missing_data"] else "none"
        lines.append(
            "| {rtype} | {name} | {level} | {score} | {safe} | {reason} | {missing} |".format(
                rtype=resource["resource_type"],
                name=resource["resource_name"],
                level=resource["risk_level"],
                score=resource["risk_score"],
                safe=resource["safe_to_migrate"],
                reason=reason.replace("|", "/"),
                missing=missing.replace("|", "/"),
            )
        )

    return "\n".join(lines) + "\n"


def _get_mapping(source: dict[str, object], key: str) -> dict[str, object]:
    value = source.get(key)
    if isinstance(value, dict):
        return cast(dict[str, object], value)
    return {}


def _get_str(source: dict[str, object], key: str, default: str) -> str:
    value = source.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default
