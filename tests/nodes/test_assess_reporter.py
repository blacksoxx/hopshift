from __future__ import annotations

import json
from pathlib import Path

from agent.nodes.assess_reporter import assess_reporter


def test_assess_reporter_writes_json_and_markdown(tmp_path: Path) -> None:
    state = {
        "config": {
            "output": {
                "base_dir": str(tmp_path),
                "assessment_report_json_filename": "assessment_report.json",
                "assessment_report_markdown_filename": "assessment_report.md",
            }
        },
        "assessment_result": {
            "generated_at": "2026-05-07T00:00:00Z",
            "source_vcenter": "vc01",
            "target_provider": "aws",
            "summary": {
                "total_resources": 1,
                "safe": 1,
                "caution": 0,
                "elevated": 0,
                "critical": 0,
            },
            "resources": [
                {
                    "resource_type": "vm",
                    "resource_id": "vm-1",
                    "resource_name": "vm-1",
                    "risk_level": "safe",
                    "risk_score": 0,
                    "safe_to_migrate": True,
                    "reasons": ["no explicit migration risk detected"],
                    "missing_data": [],
                    "recommendations": ["no action required"],
                }
            ],
        },
        "messages": [],
        "status": "running",
    }

    updated = assess_reporter(state)  # type: ignore[arg-type]

    assert updated["status"] == "succeeded"
    assert (tmp_path / "assessment_report.json").exists()
    assert (tmp_path / "assessment_report.md").exists()

    payload = json.loads((tmp_path / "assessment_report.json").read_text(encoding="utf-8"))
    assert payload["summary"]["total_resources"] == 1
