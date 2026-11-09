from __future__ import annotations

import json

import pytest

from vma.compliance import (
    CONTROLS,
    CONTROLS_BY_ID,
    FRAMEWORKS,
    build_report,
    controls_for_cloud,
    render_markdown,
)
from vma.compliance.controls import ALL_CLOUDS


def _violation(control: str, level: str, resource: str = "aws_instance.web", message: str = "boom") -> dict[str, str]:
    return {"control": control, "level": level, "resource": resource, "file": "aws-migration/compute_web.tf", "message": message}


def _aws_ids() -> list[str]:
    return [control.id for control in controls_for_cloud("aws")]


def test_catalog_is_consistent() -> None:
    assert len({control.id for control in CONTROLS}) == len(CONTROLS)
    for control in CONTROLS:
        assert control.level in {"enforce", "advisory"}
        assert control.clouds and set(control.clouds) <= set(ALL_CLOUDS)
        assert control.title and control.description and control.remediation
        assert set(control.frameworks) == set(FRAMEWORKS)
        # every control is evidence for at least one framework criterion
        assert any(control.frameworks[name] for name in FRAMEWORKS), control.id
    for cloud in ALL_CLOUDS:
        assert "ALL-TAGS-REQUIRED" in {control.id for control in controls_for_cloud(cloud)}
    # CIS publishes no OpenStack benchmark
    assert all(not control.frameworks["cis"] for control in controls_for_cloud("openstack") if control.clouds == ("openstack",))


def test_report_marks_pass_fail_and_advisory() -> None:
    evaluated = _aws_ids()
    violations = [
        _violation("AWS-EC2-IMDSV2", "enforce", message="metadata_options block is missing"),
        _violation("AWS-EC2-IMDSV2", "enforce", resource="aws_instance.db", message="metadata_options block is missing"),
        _violation("AWS-VPC-FLOW-LOGS", "advisory", resource="aws_vpc.main", message="no aws_flow_log"),
    ]

    report = build_report("aws", violations, evaluated, {"passed": False, "errors": ["compliance AWS-EC2-IMDSV2: ..."]})

    by_id = {control["id"]: control for control in report["controls"]}
    assert set(by_id) == set(evaluated)
    assert report["cloud"] == "aws"
    assert report["gate_passed"] is False
    assert by_id["AWS-EC2-IMDSV2"]["status"] == "fail"
    assert by_id["AWS-EC2-IMDSV2"]["resources"] == ["aws_instance.db", "aws_instance.web"]
    assert by_id["AWS-EC2-IMDSV2"]["messages"] == [
        "aws_instance.db (aws-migration/compute_web.tf): metadata_options block is missing",
        "aws_instance.web (aws-migration/compute_web.tf): metadata_options block is missing",
    ]
    assert by_id["AWS-EC2-IMDSV2"]["remediation"] == CONTROLS_BY_ID["AWS-EC2-IMDSV2"].remediation
    assert by_id["AWS-EC2-IMDSV2"]["frameworks"]["cis"] == ["AWS 5.6"]
    assert by_id["AWS-VPC-FLOW-LOGS"]["status"] == "advisory"
    assert by_id["AWS-EBS-ENCRYPTED"]["status"] == "pass"

    summary = report["summary"]
    assert summary["controls"] == len(evaluated)
    assert summary["failed"] == 1
    assert summary["advisory"] == 1
    assert summary["not_applicable"] == 0
    assert summary["passed"] == len(evaluated) - 2
    assert report["warnings"] == []

    cis = report["frameworks"]["cis"]
    assert cis["controls"] == sum(1 for control in controls_for_cloud("aws") if control.frameworks["cis"])
    assert cis["failed"] == 1  # IMDSv2 carries a CIS reference
    assert cis["advisory"] == 1  # flow logs carry a CIS reference


def test_report_without_evaluation_is_not_applicable_with_warning() -> None:
    report = build_report("gcp", [], [], {"passed": True, "warnings": ["validator: OPA validation skipped by config"]})

    assert {control["status"] for control in report["controls"]} == {"not_applicable"}
    assert report["summary"]["not_applicable"] == len(controls_for_cloud("gcp"))
    assert report["summary"]["passed"] == 0
    assert any("not_applicable" in warning for warning in report["warnings"])
    assert report["gate_passed"] is True


def test_report_keeps_unknown_controls_visible() -> None:
    report = build_report("azure", [_violation("AZ-NEW-THING", "enforce", resource="azurerm_x.y")], ["AZ-NEW-THING"], {})

    by_id = {control["id"]: control for control in report["controls"]}
    assert by_id["AZ-NEW-THING"]["status"] == "fail"
    assert by_id["AZ-NEW-THING"]["title"].startswith("Unknown control")
    assert by_id["AZ-NIC-NO-PUBLIC-IP"]["status"] == "not_applicable"


def test_report_for_unknown_cloud_has_no_controls_and_warns() -> None:
    report = build_report("alicloud", [], [], {})

    assert report["controls"] == []
    assert report["summary"] == {"controls": 0, "passed": 0, "failed": 0, "advisory": 0, "not_applicable": 0}
    assert any("alicloud" in warning for warning in report["warnings"])


def test_report_is_json_serializable_and_sorted() -> None:
    report = build_report("openstack", [_violation("OS-VOLUME-ENCRYPTED-TYPE", "advisory", resource="openstack_blockstorage_volume_v3.b"), _violation("OS-VOLUME-ENCRYPTED-TYPE", "advisory", resource="openstack_blockstorage_volume_v3.a")], [c.id for c in controls_for_cloud("openstack")], {"passed": True})

    encoded = json.loads(json.dumps(report))
    volume_control = next(control for control in encoded["controls"] if control["id"] == "OS-VOLUME-ENCRYPTED-TYPE")
    assert volume_control["resources"] == ["openstack_blockstorage_volume_v3.a", "openstack_blockstorage_volume_v3.b"]
    assert encoded["generated_at"].endswith("Z")


def test_render_markdown_lists_summary_controls_and_findings() -> None:
    evaluated = _aws_ids()
    report = build_report(
        "aws",
        [_violation("AWS-EC2-IMDSV2", "enforce", message="metadata_options block is missing"), _violation("AWS-VPC-FLOW-LOGS", "advisory", resource="aws_vpc.main", message="no aws_flow_log")],
        evaluated,
        {"passed": False},
    )

    markdown = render_markdown(report)

    assert markdown.startswith("# Compliance Report - AWS")
    assert "| Controls | Passed | Failed | Advisory findings | Not applicable |" in markdown
    assert "| AWS-EC2-IMDSV2 | EC2 instances require IMDSv2 | enforce | fail | AWS 5.6 |" in markdown
    assert "### AWS-EC2-IMDSV2 - EC2 instances require IMDSv2 (fail)" in markdown
    assert "- aws_instance.web (aws-migration/compute_web.tf): metadata_options block is missing" in markdown
    assert "### AWS-VPC-FLOW-LOGS - VPC flow logs enabled (advisory)" in markdown
    assert "Remediation: " in markdown
    assert "## Framework coverage" in markdown and "| SOC 2 TSC |" in markdown and "| HIPAA Security Rule |" in markdown
    assert "organisational attestations" in markdown
    # passing controls do not get a findings section
    assert "### AWS-EBS-ENCRYPTED" not in markdown


def test_render_markdown_without_findings_says_so() -> None:
    report = build_report("azure", [], [c.id for c in controls_for_cloud("azure")], {"passed": True})

    markdown = render_markdown(report)

    assert "No findings." in markdown
    assert "## Warnings" not in markdown


@pytest.mark.parametrize("cloud", ALL_CLOUDS)
def test_every_cloud_has_enforce_controls(cloud: str) -> None:
    assert any(control.level == "enforce" and control.clouds != ALL_CLOUDS for control in controls_for_cloud(cloud))
