"""Every registered target passes the conformance kit (hopshift.testing.check_target).

The fast part (pipeline, render, layout, guards, parse, determinism, OPA, sizing) always runs.
The terraform-backed part is skipped unless HOPSHIFT_CONFORMANCE_TERRAFORM=1;
tests/integration/test_conformance_terraform.py runs it with the real binaries in the
integration job.
"""
from __future__ import annotations

import os

import pytest

from hopshift.targets import registry as targets
from hopshift.testing._common import REPO_ROOT, find_binary
from hopshift.testing.targets import TERRAFORM_ENV, check_target

TARGETS = targets.names()
TERRAFORM_REQUESTED = os.environ.get(TERRAFORM_ENV, "").strip().lower() in {"1", "true", "yes", "on"}
FIXTURE_LABELS = ["discovery_multi_vm.json"] + (["discovery-2.json"] if (REPO_ROOT / "discovery-2.json").exists() else [])


@pytest.mark.parametrize("name", TARGETS)
def test_target_passes_fast_conformance(name: str) -> None:
    report = check_target(name)

    assert report.passed, report.render()
    for label in FIXTURE_LABELS:
        for check in ("pipeline", "render", "layout", "guards", "pipeline.allowlist", "parse", "determinism"):
            assert report.get(f"{check}[{label}]").status == "pass", report.render()  # type: ignore[union-attr]
        if find_binary("opa"):
            assert report.get(f"opa[{label}]").status == "pass", report.render()  # type: ignore[union-attr]
            assert report.get(f"compliance[{label}]").status == "pass", report.render()  # type: ignore[union-attr]
    for check in ("spec", "spec.docs", "package", "sizing_table", "sizing.coverage"):
        assert report.get(check).status == "pass", report.render()  # type: ignore[union-attr]
    # pass-through sizing (proxmox) has no vCPU buckets; the kit skips the RAM monotonicity check for it
    assert report.get("sizing.monotonic").status in {"pass", "skip"}, report.render()  # type: ignore[union-attr]
    # terraform is not part of the fast run
    assert report.get(f"terraform[{FIXTURE_LABELS[0]}]").status == "skip"  # type: ignore[union-attr]


@pytest.mark.skipif(not TERRAFORM_REQUESTED, reason=f"set {TERRAFORM_ENV}=1 to run terraform init/validate (needs the binaries and network)")
@pytest.mark.parametrize("name", TARGETS)
def test_target_passes_terraform_conformance(name: str) -> None:
    report = check_target(name, run_terraform=True)

    assert report.passed, report.render()
    assert report.get(f"terraform[{FIXTURE_LABELS[0]}]").status == "pass", report.render()  # type: ignore[union-attr]
