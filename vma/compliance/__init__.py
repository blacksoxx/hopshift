"""Compliance-as-code: the control catalog and the report built from OPA compliance results.

The policy engine stays OPA (validation/policies/compliance/*.rego). This package only
describes the controls (ids, levels, framework references, remediation) and turns the
evaluated violations into the compliance_report.json / compliance_report.md artifacts.
"""

from vma.compliance.controls import (
    ALL_CLOUDS,
    CONTROLS,
    CONTROLS_BY_ID,
    FRAMEWORKS,
    Control,
    controls_for_cloud,
    get_control,
)
from vma.compliance.report import STATUSES, build_report, render_markdown

__all__ = [
    "ALL_CLOUDS",
    "CONTROLS",
    "CONTROLS_BY_ID",
    "FRAMEWORKS",
    "STATUSES",
    "Control",
    "build_report",
    "controls_for_cloud",
    "get_control",
    "render_markdown",
]
