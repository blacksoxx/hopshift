"""pytest plugin: run the hopshift conformance kit from any repository.

Registered through the `pytest11` entry point `hopshift`, so installing hopshift makes the
fixtures available everywhere (no conftest needed). A target plugin repository needs two lines:

    def test_proxmox_conforms(hopshift_target_conformance):
        hopshift_target_conformance("proxmox")

A source plugin passes its own fixture:

    def test_hyperv_conforms(hopshift_source_conformance):
        hopshift_source_conformance("hyperv", "tests/fixtures/hyperv.json")

Set HOPSHIFT_CONFORMANCE_TERRAFORM=1 to include terraform init/validate (and tflint for targets
that declare a ruleset); the binaries must be installed and the first run needs network access
to download providers. The imports below are lazy so loading the plugin costs nothing for test
sessions that never use it.
"""
from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

TERRAFORM_ENV = "HOPSHIFT_CONFORMANCE_TERRAFORM"


def terraform_requested() -> bool:
    return os.environ.get(TERRAFORM_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


@pytest.fixture(scope="session")
def hopshift_discovery_fixture() -> Path:
    """Path to the VMware multi-VM discovery fixture shipped with hopshift (four VMs: one
    quarantined for an RDM disk, two switches, one DRS cluster)."""
    from hopshift.testing._common import PACKAGED_DISCOVERY_FIXTURE

    return PACKAGED_DISCOVERY_FIXTURE


@pytest.fixture
def hopshift_target_conformance() -> Callable[..., Any]:
    """Callable running `hopshift.testing.check_target`; fails the test with the full report
    when any check fails and returns the report otherwise."""

    def run(
        spec_or_name: Any,
        *,
        discovery_fixture: Any | Sequence[Any] | None = None,
        run_terraform: bool | None = None,
        **kwargs: Any,
    ) -> Any:
        from hopshift.testing.targets import check_target

        if run_terraform is None:
            run_terraform = terraform_requested()
        report = check_target(spec_or_name, discovery_fixture=discovery_fixture, run_terraform=run_terraform, **kwargs)
        if not report.passed:
            pytest.fail(report.render(), pytrace=False)
        return report

    return run


@pytest.fixture
def hopshift_source_conformance() -> Callable[..., Any]:
    """Callable running `hopshift.testing.check_source(spec_or_name, payload)`; fails the test
    with the full report when any check fails and returns the report otherwise."""

    def run(spec_or_name: Any, payload: Any, **kwargs: Any) -> Any:
        from hopshift.testing.sources import check_source

        report = check_source(spec_or_name, payload, **kwargs)
        if not report.passed:
            pytest.fail(report.render(), pytrace=False)
        return report

    return run
