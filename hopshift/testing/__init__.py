"""Conformance kit for hopshift plugins.

Any target (renderer package) or source (discovery translator) can be checked against the
contracts the pipeline relies on:

    from hopshift.testing import check_target, check_source

    report = check_target("aws")                 # fast: render, guards, parse, OPA, sizing
    report = check_target("aws", run_terraform=True)
    report = check_source("vmware", payload)
    assert report.passed, report.render()

The same checks are exposed as pytest fixtures (`hopshift_target_conformance`,
`hopshift_source_conformance`, `hopshift_discovery_fixture`) through the `hopshift` pytest
plugin, and as CLI commands (`hopshift targets check`, `hopshift sources check`).
"""
from __future__ import annotations

from hopshift.testing.report import CheckResult, ConformanceReport
from hopshift.testing.sources import check_source
from hopshift.testing.targets import check_target

__all__ = ["CheckResult", "ConformanceReport", "check_source", "check_target"]
