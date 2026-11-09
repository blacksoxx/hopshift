from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from loguru import logger

from agent.llm_client import LLMClient
from agent.prompts import build_report_system_prompt, build_report_user_prompt
from agent.state import MigrationState
from validation.paths import ensure_safe_relative_path
from vma.compliance.report import build_report, render_markdown


def reporter(state: MigrationState) -> MigrationState:
    """Generate review notes and write runtime artifacts.

    Runs for every pipeline outcome. HCL files are written only when the final
    validation passed; the quarantine report and review notes are always written so a
    failed run still leaves an auditable trail. With output.dry_run=true nothing is
    written at all.
    """
    next_state = cast(MigrationState, dict(state))

    config = next_state.get("config", {})
    if not isinstance(config, dict):
        config = {}

    output_cfg = _get_mapping(config, "output")
    base_dir = Path(_get_str(output_cfg, "base_dir", "output")).resolve()
    write_review_notes = _get_bool(output_cfg, "write_review_notes", True)
    write_quarantine_report = _get_bool(output_cfg, "write_quarantine_report", True)
    write_compliance_report = _get_bool(output_cfg, "write_compliance_report", True)
    overwrite_output = _get_bool(output_cfg, "overwrite", True)
    review_notes_filename = _get_str(output_cfg, "review_notes_filename", "review_notes.md")
    quarantine_filename = _get_str(output_cfg, "quarantine_report_filename", "quarantine_report.json")
    compliance_json_filename = _get_str(output_cfg, "compliance_report_json_filename", "compliance_report.json")
    compliance_md_filename = _get_str(output_cfg, "compliance_report_markdown_filename", "compliance_report.md")
    dry_run = _get_bool(output_cfg, "dry_run", False)

    validation_result = next_state.get("validation_result", {})
    validation_passed = bool(validation_result.get("passed")) if isinstance(validation_result, dict) else False
    run_failed = next_state.get("status") == "failed" or not validation_passed

    hcl_output = _normalize_hcl_output(next_state.get("hcl_output", {}))
    messages = list(next_state.get("messages", []))
    hcl_files_written = 0

    if dry_run:
        messages.append("reporter: dry-run enabled; no files written")
    elif run_failed:
        messages.append(
            "reporter: validation did not pass; skipped writing {} HCL file(s), reports still written".format(
                len(hcl_output)
            )
        )
    else:
        _prepare_hcl_output_base_dir(base_dir=base_dir, hcl_output=hcl_output, overwrite=overwrite_output)
        _write_hcl_output(base_dir=base_dir, hcl_output=hcl_output)
        hcl_files_written = len(hcl_output)

    review_notes = _generate_review_notes(next_state, config)

    if write_review_notes and not dry_run:
        notes_path = base_dir / review_notes_filename
        notes_path.parent.mkdir(parents=True, exist_ok=True)
        notes_path.write_text(review_notes, encoding="utf-8")

    quarantine_queue = list(next_state.get("quarantine_queue", []))
    if write_quarantine_report and not dry_run:
        quarantine_path = base_dir / quarantine_filename
        quarantine_path.parent.mkdir(parents=True, exist_ok=True)
        quarantine_path.write_text(
            json.dumps(quarantine_queue, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )

    # The compliance report is written for every outcome (like the quarantine report) so a
    # failed gate still leaves per-control evidence. Without a validator result it is a
    # not_applicable report that says so.
    compliance_result = next_state.get("compliance_result")
    if not isinstance(compliance_result, dict):
        compliance_result = build_report(
            _detect_cloud(hcl_output, next_state), [], [], validation_result if isinstance(validation_result, dict) else {}
        )
        next_state["compliance_result"] = compliance_result

    if write_compliance_report and not dry_run:
        base_dir.mkdir(parents=True, exist_ok=True)
        (base_dir / compliance_json_filename).write_text(
            json.dumps(compliance_result, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )
        (base_dir / compliance_md_filename).write_text(render_markdown(compliance_result), encoding="utf-8")

    messages.append(
        "reporter: wrote_hcl_files={} wrote_review_notes={} wrote_quarantine_report={} wrote_compliance_report={}".format(
            hcl_files_written,
            write_review_notes and not dry_run,
            write_quarantine_report and not dry_run,
            write_compliance_report and not dry_run,
        )
    )

    next_state["review_notes"] = review_notes
    next_state["messages"] = messages
    next_state["status"] = "failed" if run_failed else "succeeded"

    logger.info(
        "reporter: completed with status={} hcl_files_written={} quarantine_items={} dry_run={}",
        next_state["status"],
        hcl_files_written,
        len(quarantine_queue),
        dry_run,
    )

    return next_state


def _generate_review_notes(state: MigrationState, config: dict[str, object]) -> str:
    cim = state.get("sized_cim") or state.get("cim")

    summary_payload = {
        "status": state.get("status", "unknown"),
        "compute_units": len(cim.compute_units) if cim is not None else 0,
        "clusters": len(cim.clusters) if cim is not None else 0,
        "network_switches": len(cim.network_topology.distributed_switches) if cim is not None else 0,
        "generated_hcl_files": len(_normalize_hcl_output(state.get("hcl_output", {}))),
        "quarantine_items": len(state.get("quarantine_queue", [])),
        "retry_count": int(state.get("retry_count", 0)),
        "validation_result": state.get("validation_result", {}),
        "messages_tail": list(state.get("messages", []))[-20:],
    }

    output_cfg = _get_mapping(config, "output")
    if not _get_bool(output_cfg, "llm_review_notes", True):
        logger.info("reporter: LLM review notes disabled by config; using deterministic notes")
        return _fallback_review_notes(summary_payload)

    system_prompt = build_report_system_prompt()
    user_prompt = build_report_user_prompt(summary_payload)

    try:
        client = LLMClient(config=config)
        notes = client.generate_review_notes(prompt=user_prompt, system_prompt=system_prompt)
        if notes.strip():
            return notes.strip()
    except Exception as exc:
        logger.warning("reporter: LLM review note generation failed: {}", str(exc))

    return _fallback_review_notes(summary_payload)


def _fallback_review_notes(summary_payload: dict[str, object]) -> str:
    return "\n".join(
        [
            "# Migration Review Notes",
            "",
            f"- Status: {summary_payload.get('status', 'unknown')}",
            f"- ComputeUnits processed: {summary_payload.get('compute_units', 0)}",
            f"- Clusters discovered: {summary_payload.get('clusters', 0)}",
            f"- Generated HCL files: {summary_payload.get('generated_hcl_files', 0)}",
            f"- Quarantine items: {summary_payload.get('quarantine_items', 0)}",
            f"- Retry count: {summary_payload.get('retry_count', 0)}",
            "",
            "## Validation Result",
            json.dumps(summary_payload.get("validation_result", {}), indent=2, ensure_ascii=True),
            "",
            "## Next Actions",
            "1. Review quarantine_report.json for blocked resources.",
            "2. Review validation errors and warnings, then rerun if needed.",
            "3. Validate generated HCL in target environment before apply.",
        ]
    )


_CLOUD_ROOTS = {
    "aws-migration/": "aws",
    "azure-migration/": "azure",
    "gcp-migration/": "gcp",
    "openstack-migration/": "openstack",
}


def _detect_cloud(hcl_output: dict[str, str], state: MigrationState) -> str:
    for path in hcl_output:
        for root, cloud in _CLOUD_ROOTS.items():
            if path.lstrip("/").startswith(root):
                return cloud
    target = state.get("target_provider")
    if target is None:
        cim = state.get("sized_cim") or state.get("cim")
        target = getattr(cim, "target_provider", None)
    if target is None:
        config = state.get("config", {})
        target = config.get("target_cloud") if isinstance(config, dict) else None
    value = getattr(target, "value", target)
    return str(value).strip().lower() if value else ""


def _normalize_hcl_output(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}

    normalized: dict[str, str] = {}
    for path, content in raw.items():
        key = str(path).strip().replace("\\", "/")
        value = str(content)
        if key and value:
            normalized[key] = value
    return normalized


def _write_hcl_output(base_dir: Path, hcl_output: dict[str, str]) -> None:
    if base_dir.exists() and not base_dir.is_dir():
        raise ValueError(f"reporter: output base_dir must be a directory: {base_dir}")

    base_dir.mkdir(parents=True, exist_ok=True)

    for raw_path, content in hcl_output.items():
        try:
            relative = Path(str(ensure_safe_relative_path(raw_path)))
        except ValueError as exc:
            raise ValueError(f"reporter: unsafe HCL output path: {raw_path}") from exc

        destination = (base_dir / relative).resolve()
        if destination.parent.exists() and not destination.parent.is_dir():
            raise ValueError(
                "reporter: cannot create HCL path because parent exists as a file: "
                f"{destination.parent}"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")


def _prepare_hcl_output_base_dir(base_dir: Path, hcl_output: dict[str, str], overwrite: bool) -> None:
    if base_dir.exists() and not base_dir.is_dir():
        raise ValueError(f"reporter: output base_dir must be a directory: {base_dir}")

    base_dir.mkdir(parents=True, exist_ok=True)

    if not overwrite:
        return

    provider_roots: set[str] = set()
    for raw_path in hcl_output.keys():
        relative = Path(raw_path)
        if not relative.parts:
            continue
        provider_roots.add(relative.parts[0])

    for provider_root in provider_roots:
        destination = base_dir / provider_root
        if not destination.exists():
            continue

        if destination.is_dir():
            _clean_generated_hcl_files(destination)
        else:
            destination.unlink()


def _clean_generated_hcl_files(provider_root_dir: Path) -> None:
    # Preserve Terraform state and plugin metadata between runs; only replace generated .tf files.
    for file_path in provider_root_dir.rglob("*.tf"):
        if file_path.is_file():
            file_path.unlink()

    nested_dirs = sorted(
        (path for path in provider_root_dir.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    )

    for dir_path in nested_dirs:
        if dir_path.name == ".terraform":
            continue
        try:
            dir_path.rmdir()
        except OSError:
            # Directory is not empty (e.g., contains state, lock files, or plugin metadata).
            continue


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


def _get_bool(source: dict[str, object], key: str, default: bool) -> bool:
    value = source.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y", "on"}:
            return True
        if lowered in {"false", "0", "no", "n", "off"}:
            return False
    return default
