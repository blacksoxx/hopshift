"""Terraform-backed conformance: the kit's terraform/tflint checks pass for every registered
target with the real binaries (same skip rules and plugin cache as test_terraform_validate.py)."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from hopshift.targets import registry as targets
from hopshift.testing._common import PACKAGED_DISCOVERY_FIXTURE
from hopshift.testing.targets import check_target

PLUGIN_CACHE = Path.home() / ".cache" / "hopshift" / "terraform-plugins"

pytestmark = [
    pytest.mark.skipif(shutil.which("terraform") is None, reason="terraform binary not installed"),
    pytest.mark.skipif(
        os.environ.get("HOPSHIFT_SKIP_TERRAFORM_INTEGRATION") == "1",
        reason="HOPSHIFT_SKIP_TERRAFORM_INTEGRATION=1",
    ),
]


@pytest.mark.parametrize("name", targets.names())
def test_target_conformance_with_terraform(name: str) -> None:
    spec = targets.get(name)
    report = check_target(name, discovery_fixture=PACKAGED_DISCOVERY_FIXTURE, run_terraform=True, plugin_cache_dir=PLUGIN_CACHE)

    assert report.passed, report.render()
    label = PACKAGED_DISCOVERY_FIXTURE.name
    assert report.get(f"terraform[{label}]").status == "pass", report.render()  # type: ignore[union-attr]
    tflint = report.get(f"tflint[{label}]")
    assert tflint is not None
    if spec.tflint and shutil.which("tflint"):
        assert tflint.status == "pass", report.render()
    else:
        assert tflint.status == "skip", report.render()
