from __future__ import annotations

import json
from pathlib import Path

import pytest

import agent.nodes.reporter as reporter_module
from agent.nodes.reporter import reporter


class _FakeLLMClient:
    def __init__(self, config: dict[str, object]) -> None:
        self.config = config

    def generate_review_notes(self, prompt: str, system_prompt: str | None = None) -> str:
        return "# Notes\n\nGenerated"


def test_reporter_writes_hcl_under_configured_output_base_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(reporter_module, "LLMClient", _FakeLLMClient)

    output_dir = tmp_path / "artifacts"
    state = {
        "config": {
            "output": {
                "base_dir": str(output_dir),
                "write_review_notes": True,
                "write_quarantine_report": True,
            }
        },
        "hcl_output": {
            "aws-migration/main.tf": 'resource "aws_vpc" "main" { cidr_block = "10.0.0.0/16" }'
        },
        "validation_result": {"passed": True},
        "messages": [],
        "quarantine_queue": [],
        "status": "running",
    }

    updated = reporter(state)  # type: ignore[arg-type]

    assert updated["status"] == "succeeded"
    assert (output_dir / "aws-migration" / "main.tf").exists()
    assert (output_dir / "review_notes.md").exists()
    assert (output_dir / "quarantine_report.json").exists()
    # compliance report is written next to the quarantine report even when the validator
    # left no compliance_result (then every control is not_applicable)
    compliance = json.loads((output_dir / "compliance_report.json").read_text(encoding="utf-8"))
    assert compliance["cloud"] == "aws"
    assert compliance["summary"]["not_applicable"] == compliance["summary"]["controls"]
    assert (output_dir / "compliance_report.md").read_text(encoding="utf-8").startswith("# Compliance Report - AWS")
    assert any("wrote_compliance_report=True" in message for message in updated["messages"])


def test_reporter_writes_compliance_result_from_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(reporter_module, "LLMClient", _FakeLLMClient)
    from vma.compliance import build_report, controls_for_cloud

    compliance_result = build_report(
        "gcp",
        [
            {
                "control": "GCP-DISK-CMEK",
                "level": "advisory",
                "resource": "google_compute_disk.data",
                "file": "gcp-migration/storage_web_disks.tf",
                "message": "no customer-managed KMS key",
            }
        ],
        [control.id for control in controls_for_cloud("gcp")],
        {"passed": True},
    )
    output_dir = tmp_path / "artifacts"
    state = {
        "config": {"output": {"base_dir": str(output_dir), "write_review_notes": False, "write_quarantine_report": False}},
        "hcl_output": {"gcp-migration/main.tf": 'resource "google_compute_network" "main" { name = "main" }'},
        "validation_result": {"passed": True},
        "compliance_result": compliance_result,
        "messages": [],
        "quarantine_queue": [],
        "status": "running",
    }

    updated = reporter(state)  # type: ignore[arg-type]

    assert updated["status"] == "succeeded"
    written = json.loads((output_dir / "compliance_report.json").read_text(encoding="utf-8"))
    assert written == json.loads(json.dumps(compliance_result))
    markdown = (output_dir / "compliance_report.md").read_text(encoding="utf-8")
    assert "### GCP-DISK-CMEK" in markdown
    assert updated["compliance_result"] is compliance_result


def test_reporter_compliance_report_honours_dry_run_and_toggle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(reporter_module, "LLMClient", _FakeLLMClient)

    def _state(output_cfg: dict[str, object]) -> dict[str, object]:
        return {
            "config": {"output": {"base_dir": str(tmp_path / "artifacts"), **output_cfg}},
            "hcl_output": {"aws-migration/main.tf": 'resource "aws_vpc" "main" { cidr_block = "10.0.0.0/16" }'},
            "validation_result": {"passed": True},
            "messages": [],
            "quarantine_queue": [],
            "status": "running",
        }

    updated = reporter(_state({"dry_run": True}))  # type: ignore[arg-type]
    assert not (tmp_path / "artifacts").exists()
    assert any("wrote_compliance_report=False" in message for message in updated["messages"])

    reporter(_state({"write_compliance_report": False}))  # type: ignore[arg-type]
    assert (tmp_path / "artifacts" / "quarantine_report.json").exists()
    assert not (tmp_path / "artifacts" / "compliance_report.json").exists()
    assert not (tmp_path / "artifacts" / "compliance_report.md").exists()


def test_reporter_rejects_output_base_dir_when_file_exists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(reporter_module, "LLMClient", _FakeLLMClient)

    output_file = tmp_path / "not_a_dir"
    output_file.write_text("x", encoding="utf-8")

    state = {
        "config": {
            "output": {
                "base_dir": str(output_file),
                "write_review_notes": False,
                "write_quarantine_report": False,
            }
        },
        "hcl_output": {
            "aws-migration/main.tf": 'resource "aws_vpc" "main" { cidr_block = "10.0.0.0/16" }'
        },
        "validation_result": {"passed": True},
        "messages": [],
        "quarantine_queue": [],
        "status": "running",
    }

    with pytest.raises(ValueError, match="output base_dir must be a directory"):
        reporter(state)  # type: ignore[arg-type]


def test_reporter_overwrite_cleans_stale_provider_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(reporter_module, "LLMClient", _FakeLLMClient)

    output_dir = tmp_path / "artifacts"
    stale_file = output_dir / "aws-migration" / "compute" / "old.tf"
    stale_file.parent.mkdir(parents=True, exist_ok=True)
    stale_file.write_text("stale", encoding="utf-8")

    state = {
        "config": {
            "output": {
                "base_dir": str(output_dir),
                "overwrite": True,
                "write_review_notes": False,
                "write_quarantine_report": False,
            }
        },
        "hcl_output": {
            "aws-migration/main.tf": 'resource "aws_vpc" "main" { cidr_block = "10.0.0.0/16" }'
        },
        "validation_result": {"passed": True},
        "messages": [],
        "quarantine_queue": [],
        "status": "running",
    }

    reporter(state)  # type: ignore[arg-type]

    assert not stale_file.exists()
    assert (output_dir / "aws-migration" / "main.tf").exists()


def test_reporter_overwrite_preserves_terraform_state_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(reporter_module, "LLMClient", _FakeLLMClient)

    output_dir = tmp_path / "artifacts"
    provider_root = output_dir / "aws-migration"

    stale_tf = provider_root / "compute" / "old.tf"
    stale_tf.parent.mkdir(parents=True, exist_ok=True)
    stale_tf.write_text("stale", encoding="utf-8")

    tfstate = provider_root / "terraform.tfstate"
    tfstate.write_text('{"version": 4}', encoding="utf-8")

    tfstate_backup = provider_root / "terraform.tfstate.backup"
    tfstate_backup.write_text('{"version": 4}', encoding="utf-8")

    lock_file = provider_root / ".terraform.lock.hcl"
    lock_file.write_text("# lock", encoding="utf-8")

    plugin_marker = provider_root / ".terraform" / "plugins" / "marker.txt"
    plugin_marker.parent.mkdir(parents=True, exist_ok=True)
    plugin_marker.write_text("plugin", encoding="utf-8")

    state = {
        "config": {
            "output": {
                "base_dir": str(output_dir),
                "overwrite": True,
                "write_review_notes": False,
                "write_quarantine_report": False,
            }
        },
        "hcl_output": {
            "aws-migration/main.tf": 'resource "aws_vpc" "main" { cidr_block = "10.0.0.0/16" }'
        },
        "validation_result": {"passed": True},
        "messages": [],
        "quarantine_queue": [],
        "status": "running",
    }

    reporter(state)  # type: ignore[arg-type]

    assert not stale_tf.exists()
    assert (provider_root / "main.tf").exists()
    assert tfstate.exists()
    assert tfstate_backup.exists()
    assert lock_file.exists()
    assert plugin_marker.exists()


def test_reporter_on_failed_validation_writes_reports_but_not_hcl(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Regression: failed runs used to leave no artifacts at all. Now the quarantine report
    and review notes are always written, while unvalidated HCL is never written."""
    monkeypatch.setattr(reporter_module, "LLMClient", _FakeLLMClient)

    output_dir = tmp_path / "artifacts"
    state = {
        "config": {"output": {"base_dir": str(output_dir)}},
        "hcl_output": {"aws-migration/main.tf": 'resource "aws_vpc" "main" {}'},
        "validation_result": {"passed": False, "errors": ["terraform validate failed: boom"]},
        "messages": [],
        "quarantine_queue": [
            {
                "compute_unit_id": "cu-1",
                "compute_unit_name": "app-1",
                "reasons": ["validation_failed"],
                "stage": "validator",
            }
        ],
        "status": "failed",
    }

    updated = reporter(state)  # type: ignore[arg-type]

    assert updated["status"] == "failed"
    assert not (output_dir / "aws-migration").exists()
    assert (output_dir / "review_notes.md").exists()
    assert (output_dir / "quarantine_report.json").exists()
    assert (output_dir / "compliance_report.json").exists()
    assert (output_dir / "compliance_report.md").exists()
    assert any("skipped writing" in message for message in updated["messages"])


def test_reporter_treats_missing_validation_result_as_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(reporter_module, "LLMClient", _FakeLLMClient)

    output_dir = tmp_path / "artifacts"
    state = {
        "config": {"output": {"base_dir": str(output_dir)}},
        "hcl_output": {"aws-migration/main.tf": 'resource "aws_vpc" "main" {}'},
        "messages": [],
        "quarantine_queue": [],
        "status": "running",
    }

    updated = reporter(state)  # type: ignore[arg-type]

    assert updated["status"] == "failed"
    assert not (output_dir / "aws-migration" / "main.tf").exists()


def test_reporter_dry_run_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(reporter_module, "LLMClient", _FakeLLMClient)

    output_dir = tmp_path / "artifacts"
    state = {
        "config": {"output": {"base_dir": str(output_dir), "dry_run": True}},
        "hcl_output": {"aws-migration/main.tf": 'resource "aws_vpc" "main" {}'},
        "validation_result": {"passed": True},
        "messages": [],
        "quarantine_queue": [],
        "status": "running",
    }

    updated = reporter(state)  # type: ignore[arg-type]

    assert updated["status"] == "succeeded"
    assert updated["review_notes"]
    assert not output_dir.exists()
    assert any("dry-run" in message for message in updated["messages"])


def test_reporter_rejects_traversal_in_hcl_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(reporter_module, "LLMClient", _FakeLLMClient)

    state = {
        "config": {"output": {"base_dir": str(tmp_path / "artifacts")}},
        "hcl_output": {"aws-migration/../../escape.tf": "# nope"},
        "validation_result": {"passed": True},
        "messages": [],
        "quarantine_queue": [],
        "status": "running",
    }

    with pytest.raises(ValueError, match="unsafe HCL output path"):
        reporter(state)  # type: ignore[arg-type]


def test_reporter_skips_llm_when_review_notes_disabled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class _NeverCalled:
        def __init__(self, config: dict[str, object]) -> None:
            raise AssertionError("LLMClient must not be constructed when llm_review_notes is false")

    monkeypatch.setattr(reporter_module, "LLMClient", _NeverCalled)
    state = {
        "config": {"output": {"base_dir": str(tmp_path / "out"), "llm_review_notes": False}},
        "hcl_output": {"aws-migration/main.tf": 'resource "aws_vpc" "main" {}'},
        "validation_result": {"passed": True},
        "messages": [],
        "quarantine_queue": [],
        "status": "running",
    }

    updated = reporter(state)  # type: ignore[arg-type]

    assert updated["status"] == "succeeded"
    assert updated["review_notes"].startswith("# Migration Review Notes")
