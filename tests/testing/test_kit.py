"""The conformance kit itself: broken plugins produce readable reports (never tracebacks), a
minimal plugin passes, unregistered specs leave the registry untouched, and the pytest fixtures
give an external repository a two-line test."""
from __future__ import annotations

import json
import textwrap
from importlib.metadata import entry_points
from pathlib import Path

import pytest

from hopshift.cim.schema import (
    CanonicalInfrastructureModel,
    ComputeUnit,
    NetworkTopology,
    SourceEndpoint,
    SourcePlatform,
)
from hopshift.sources.registry import SourceSpec
from hopshift.targets import registry as targets
from hopshift.targets.registry import TargetSpec, UnknownTarget
from hopshift.testing import ConformanceReport, check_source, check_target
from hopshift.testing._common import PACKAGED_DISCOVERY_FIXTURE, REPO_ROOT, find_binary
from hopshift.testing.report import SkipCheck

pytest_plugins = ["pytester"]

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "discovery_multi_vm.json"


# ── fake target packages ──────────────────────────────────────────────────────

_GOOD_RUNTIME = '''
def render_runtime(cim, required_tags=None):
    tags = required_tags or {}
    providers = (
        'terraform {\\n  required_version = ">= 1.5.0"\\n  required_providers {\\n'
        '    random = {\\n      source  = "hashicorp/random"\\n      version = "~> 3.6"\\n    }\\n  }\\n}\\n\\n'
        'provider "random" {}\\n'
    )
    variables = (
        'variable "environment" {\\n  type    = string\\n  default = "%s"\\n}\\n\\n'
        'variable "owner" {\\n  type    = string\\n  default = "%s"\\n}\\n'
    ) % (tags.get("Environment", "dev"), tags.get("Owner", "platform"))
    return {"ROOT-migration/targets.tf": providers, "ROOT-migration/variables.tf": variables}
'''

_GOOD_NETWORK = '''
from hopshift.targets.common import hcl_string, safe_file_stem

def render_networking(cim):
    lines = []
    for switch in cim.network_topology.distributed_switches:
        for segment in switch.port_groups:
            ident = safe_file_stem(segment.name).replace("-", "_").replace(".", "_").lower()
            lines.append('resource "random_pet" "segment_%s" {\\n  prefix = %s\\n}\\n' % (ident, hcl_string(segment.name)))
    return {"ROOT-migration/networking/segments.tf": "".join(lines) or "# no segments\\n"}
'''

_GOOD_COMPUTE = '''
from hopshift.targets.common import hcl_string, safe_file_stem
from ROOT_pkg.sizing_table import get_instance_type

def render_compute(cim, required_tags=None):
    tags = required_tags or {}
    output = {}
    for unit in cim.compute_units:
        stem = safe_file_stem(unit.name)
        keepers = "".join('    %s = %s\\n' % (key, value if str(value).startswith("var.") else hcl_string(value)) for key, value in sorted(tags.items()))
        body = 'resource "random_pet" "%s" {\\n  prefix = %s\\n  keepers = {\\n    size = "%s"\\n%s  }\\n}\\n' % (
            stem.replace("-", "_").replace(".", "_").lower(), hcl_string(unit.name), get_instance_type(unit.vcpus, unit.ram_mb), keepers,
        )
        output["ROOT-migration/compute/%s.tf" % stem] = body
    return output
'''

_EMPTY_TAGGED = '''
def %s(cim, required_tags=None):
    return {}
'''

_GOOD_SIZING = '''
def get_instance_type(vcpus, ram_mb):
    if vcpus <= 0 or ram_mb <= 0:
        raise ValueError("vcpus and ram_mb must be > 0")
    if vcpus <= 2 and ram_mb <= 4096:
        return "fake.small"
    if vcpus <= 8 and ram_mb <= 32768:
        return "fake.medium"
    return "fake.large"
'''

_UNSAFE_NETWORK = '''
def render_networking(cim):
    return {"ROOT-migration/networking/net.tf": 'resource "null_resource" "bootstrap" {\\n  provisioner "local-exec" {\\n    command = "echo hi"\\n  }\\n}\\n'}
'''

_UNSAFE_RUNTIME = '''
def render_runtime(cim, required_tags=None):
    return {
        "ROOT-migration/targets.tf": 'terraform {\\n  required_providers {\\n    null = {\\n      source = "hashicorp/null"\\n    }\\n  }\\n}\\n\\nprovider "null" {}\\n',
        "ROOT-migration/variables.tf": 'variable "environment" {\\n  type = string\\n}\\n',
    }
'''


def _write_package(root: Path, name: str, modules: dict[str, str]) -> str:
    package = f"{name}_pkg"
    directory = root / package
    directory.mkdir()
    (directory / "__init__.py").write_text("", encoding="utf-8")
    for module, source in modules.items():
        body = textwrap.dedent(source).replace("ROOT_pkg", package).replace("ROOT", name)
        (directory / f"{module}.py").write_text(body, encoding="utf-8")
    return package


def _good_modules() -> dict[str, str]:
    return {
        "network": _GOOD_NETWORK,
        "compute": _GOOD_COMPUTE,
        "storage": _EMPTY_TAGGED % "render_storage",
        "placement": _EMPTY_TAGGED % "render_placement",
        "runtime": _GOOD_RUNTIME,
        "sizing_table": _GOOD_SIZING,
    }


@pytest.fixture
def plugin_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "plugins"
    root.mkdir()
    monkeypatch.syspath_prepend(str(root))
    return root


# ── report ────────────────────────────────────────────────────────────────────


def test_report_records_pass_fail_skip_from_check_functions() -> None:
    report = ConformanceReport(kind="target", subject="demo", label="Demo")

    def failing() -> str:
        raise RuntimeError("boom")

    def skipping() -> str:
        raise SkipCheck("tool missing")

    def asserting() -> str:
        assert 1 == 2, "one is not two"
        return ""

    report.run("ok", lambda: "fine")
    report.run("broken", failing)
    report.run("later", skipping)
    report.run("checked", asserting)

    assert report.names("pass") == ["ok"]
    assert report.names("fail") == ["broken", "checked"]
    assert report.names("skip") == ["later"]
    assert not report.passed
    assert report.get("broken").message == "RuntimeError: boom"  # type: ignore[union-attr]
    assert report.get("checked").message == "one is not two"  # type: ignore[union-attr]
    rendered = report.render()
    assert rendered.splitlines()[0] == "target conformance: demo (Demo) - 1 passed, 2 failed, 1 skipped"
    assert "  FAIL  broken   RuntimeError: boom" in rendered
    assert "  SKIP  later    tool missing" in rendered
    payload = json.loads(json.dumps(report.to_dict()))
    assert payload["passed"] is False and payload["summary"] == {"passed": 1, "failed": 2, "skipped": 1}


# ── targets ───────────────────────────────────────────────────────────────────


def test_unknown_target_name_raises() -> None:
    with pytest.raises(UnknownTarget):
        check_target("does-not-exist")


def test_broken_target_fails_cleanly_with_readable_messages(plugin_root: Path) -> None:
    package = _write_package(plugin_root, "brokenplug", {})  # package exists, no renderer modules
    spec = TargetSpec(name="brokenplug", label="Broken plug", blurb="nothing works", package=package)

    report = check_target(spec, discovery_fixture=FIXTURE)

    assert not report.passed
    assert report.get("package").status == "pass"  # type: ignore[union-attr]
    for suffix in ("network", "compute", "storage", "placement", "runtime"):
        result = report.get(f"renderer.{suffix}")
        assert result is not None and result.status == "fail"
        assert result.message.startswith("ModuleNotFoundError: No module named 'brokenplug_pkg."), result.message
    assert report.get("sizing_table").status == "fail"  # type: ignore[union-attr]
    assert report.get("sizing.coverage").status == "skip"  # type: ignore[union-attr]
    assert report.get("pipeline[discovery_multi_vm.json]").status == "fail"  # type: ignore[union-attr]
    assert "sizing lookup module is missing" in report.get("pipeline[discovery_multi_vm.json]").message  # type: ignore[union-attr]
    assert report.get("render[discovery_multi_vm.json]").status == "skip"  # type: ignore[union-attr]
    assert "Traceback" not in report.render()
    # the temporary registration is gone again
    assert "brokenplug" not in targets.names()


def test_unsafe_target_is_caught_by_the_pipeline_guards(plugin_root: Path) -> None:
    modules = _good_modules()
    modules["network"] = _UNSAFE_NETWORK
    modules["runtime"] = _UNSAFE_RUNTIME
    package = _write_package(plugin_root, "unsafeplug", modules)
    spec = TargetSpec(name="unsafeplug", label="Unsafe plug", blurb="provisioners", package=package)

    report = check_target(spec, discovery_fixture=FIXTURE)

    assert not report.passed
    guards = report.get("guards[discovery_multi_vm.json]")
    assert guards is not None and guards.status == "fail"
    assert "forbidden provisioner block" in guards.message or "forbidden null_resource" in guards.message
    allowlist = report.get("pipeline.allowlist[discovery_multi_vm.json]")
    assert allowlist is not None and allowlist.status == "fail"
    assert "hashicorp/null" in allowlist.message and "_PROVIDER_SOURCE_ALLOWLIST" in allowlist.message
    if find_binary("opa"):
        opa = report.get("opa[discovery_multi_vm.json]")
        assert opa is not None and opa.status == "fail" and "no_code_execution" in opa.message


def test_minimal_plugin_target_passes_the_fast_checks(plugin_root: Path) -> None:
    package = _write_package(plugin_root, "goodplug", _good_modules())
    spec = TargetSpec(
        name="goodplug", label="Good plug", blurb="random pets", package=package,
        extra={"provider_sources": {"hashicorp/random"}},
    )

    report = check_target(spec, discovery_fixture=FIXTURE)

    assert report.passed, report.render()
    assert report.get("spec.docs").status == "skip"  # type: ignore[union-attr]
    assert report.get("spec.connection_provider").status == "skip"  # type: ignore[union-attr]
    assert report.get("sizing.monotonic").status == "skip"  # type: ignore[union-attr]
    assert report.get("render[discovery_multi_vm.json]").status == "pass"  # type: ignore[union-attr]
    assert report.get("layout[discovery_multi_vm.json]").status == "pass"  # type: ignore[union-attr]
    assert report.get("guards[discovery_multi_vm.json]").status == "pass"  # type: ignore[union-attr]
    assert report.get("pipeline.allowlist[discovery_multi_vm.json]").status == "pass"  # type: ignore[union-attr]
    assert report.get("compliance[discovery_multi_vm.json]").status == "skip"  # type: ignore[union-attr]
    assert report.get("terraform[discovery_multi_vm.json]").status == "skip"  # type: ignore[union-attr]
    assert "goodplug" not in targets.names()


def test_target_spec_with_bad_docs_and_connection_provider_is_reported(plugin_root: Path) -> None:
    package = _write_package(plugin_root, "metaplug", _good_modules())
    spec = TargetSpec(
        name="metaplug", label="Meta plug", blurb="metadata", package=package,
        docs="docs/targets/does-not-exist.md", connection_provider="nimbus",
    )

    report = check_target(spec, discovery_fixture=FIXTURE)

    assert report.get("spec.docs").status == "fail"  # type: ignore[union-attr]
    assert "does-not-exist.md" in report.get("spec.docs").message  # type: ignore[union-attr]
    assert report.get("spec.connection_provider").status == "fail"  # type: ignore[union-attr]
    assert "not in the connections catalog" in report.get("spec.connection_provider").message  # type: ignore[union-attr]


def test_check_target_accepts_a_dict_payload_and_reports_unreadable_fixtures(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    report = check_target("openstack", discovery_fixture=payload)
    assert report.get("render[payload[0]]").status == "pass", report.render()  # type: ignore[union-attr]

    report = check_target("openstack", discovery_fixture=tmp_path / "missing.json")
    assert report.get("fixtures").status == "fail"  # type: ignore[union-attr]
    assert "missing.json" in report.get("fixtures").message  # type: ignore[union-attr]


def test_packaged_fixture_matches_the_repository_fixture() -> None:
    assert json.loads(PACKAGED_DISCOVERY_FIXTURE.read_text(encoding="utf-8")) == json.loads(FIXTURE.read_text(encoding="utf-8"))


# ── sources ───────────────────────────────────────────────────────────────────


def _dropping_translator(discovery: dict, target: str) -> CanonicalInfrastructureModel:
    vms = discovery.get("virtual_machines", [])[1:]  # loses the first VM
    return CanonicalInfrastructureModel(
        source=SourceEndpoint(platform=SourcePlatform.KVM, name="kvm-host"),
        target_provider=target,
        network_topology=NetworkTopology(),
        compute_units=[ComputeUnit(id=str(index), name=str(vm.get("vm_name")), vcpus=1, ram_mb=1024, blockers=["weird_flag"]) for index, vm in enumerate(vms)],
    )


def test_source_translator_contract_violations_are_reported() -> None:
    spec = SourceSpec(
        name="kvmlike", label="KVM-like", blurb="drops a VM", schema_names=("kvm-discovery",),
        translate=_dropping_translator, platform="hyperv",
    )
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["metadata"]["schema_name"] = "kvm-discovery"

    report = check_source(spec, payload, target_names=["openstack"])

    assert not report.passed
    assert report.get("payload").status == "pass"  # type: ignore[union-attr]
    assert report.get("source.platform").status == "fail"  # type: ignore[union-attr]
    assert "the spec declares 'hyperv'" in report.get("source.platform").message  # type: ignore[union-attr]
    assert report.get("vm_count").status == "fail"  # type: ignore[union-attr]
    assert "4 VMs discovered but 3 ComputeUnits" in report.get("vm_count").message  # type: ignore[union-attr]
    assert report.get("blockers").status == "fail"  # type: ignore[union-attr]
    assert "weird_flag" in report.get("blockers").message  # type: ignore[union-attr]
    assert report.get("render[openstack]").status == "pass"  # type: ignore[union-attr]


def test_source_payload_with_the_wrong_schema_fails_the_payload_check() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["metadata"]["schema_name"] = "something-else"

    report = check_source("vmware", payload)

    assert report.get("payload").status == "fail"  # type: ignore[union-attr]
    assert "something-else" in report.get("payload").message  # type: ignore[union-attr]
    # the translator still runs so the remaining checks stay informative
    assert report.get("translate").status == "pass"  # type: ignore[union-attr]


# ── pytest plugin ─────────────────────────────────────────────────────────────


def _inner_args() -> list[str]:
    args = ["-q", "-p", "no:cacheprovider"]
    if not any(entry.name == "hopshift" for entry in entry_points(group="pytest11")):
        args += ["-p", "hopshift.testing.pytest_plugin"]  # not installed as an entry point in this checkout
    return args


def test_pytest_fixture_gives_a_two_line_conformance_test(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        """
        def test_openstack_conforms(hopshift_target_conformance):
            hopshift_target_conformance("openstack")

        def test_discovery_fixture_is_the_packaged_file(hopshift_discovery_fixture):
            assert hopshift_discovery_fixture.name == "discovery_multi_vm.json"
            assert hopshift_discovery_fixture.exists()

        def test_vmware_source_conforms(hopshift_source_conformance, hopshift_discovery_fixture):
            hopshift_source_conformance("vmware", hopshift_discovery_fixture, target_names=["openstack"])
        """
    )

    result = pytester.runpytest_inprocess(*_inner_args())

    result.assert_outcomes(passed=3)


def test_pytest_fixture_fails_with_the_rendered_report(pytester: pytest.Pytester, plugin_root: Path) -> None:
    package = _write_package(plugin_root, "brokenfix", {})
    pytester.syspathinsert(str(plugin_root))
    pytester.makepyfile(
        f"""
        from hopshift.targets.registry import TargetSpec

        def test_broken(hopshift_target_conformance):
            hopshift_target_conformance(TargetSpec(name="brokenfix", label="Broken", blurb="x", package="{package}"))
        """
    )

    result = pytester.runpytest_inprocess(*_inner_args())

    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*FAIL  renderer.network*ModuleNotFoundError*"])
