"""CLI groups targets / sources / plugins / matrix."""
from __future__ import annotations

import json
from importlib.metadata import EntryPoint
from pathlib import Path

import pytest
from click.testing import CliRunner

from hopshift.cli.main import cli
from hopshift.testing import matrix
from hopshift.testing._common import REPO_ROOT

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "discovery_multi_vm.json"


def test_targets_list_text_and_json() -> None:
    runner = CliRunner()

    text = runner.invoke(cli, ["targets", "list"])
    assert text.exit_code == 0, text.output
    header, _, *rows = text.output.splitlines()
    assert header.split() == ["NAME", "LABEL", "TIER", "TFLINT", "CONNECTION", "PACKAGE"]
    assert [row.split()[0] for row in rows] == ["aws", "azure", "gcp", "openstack", "proxmox"]
    assert "openstack  OpenStack" in text.output and "validated  no      openstack" in text.output
    assert "proxmox    Proxmox VE" in text.output and "validated  no      proxmox" in text.output

    as_json = runner.invoke(cli, ["targets", "list", "--format", "json"])
    assert as_json.exit_code == 0
    payload = json.loads(as_json.output)
    assert [item["name"] for item in payload] == ["aws", "azure", "gcp", "openstack", "proxmox"]
    assert payload[0]["connection_provider"] == "aws" and payload[0]["tflint"] is True


def test_targets_check_prints_the_report_and_exits_zero() -> None:
    result = CliRunner().invoke(cli, ["targets", "check", "openstack", "--input", str(FIXTURE)])

    assert result.exit_code == 0, result.output
    assert result.output.startswith("target conformance: openstack (OpenStack) - ")
    assert "PASS  render[discovery_multi_vm.json]" in result.output
    assert "SKIP  terraform[discovery_multi_vm.json]" in result.output


def test_targets_check_json_output() -> None:
    result = CliRunner().invoke(cli, ["targets", "check", "openstack", "--input", str(FIXTURE), "--format", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["subject"] == "openstack" and payload["passed"] is True
    assert {item["name"] for item in payload["checks"]} >= {"spec", "sizing_table", "render[discovery_multi_vm.json]"}


def test_targets_check_unknown_target_exits_non_zero() -> None:
    result = CliRunner().invoke(cli, ["targets", "check", "nope"])

    assert result.exit_code == 1
    assert "unknown target 'nope'" in result.output


def test_targets_check_exits_one_when_a_check_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    from hopshift.testing import targets as kit

    def fake_check_target(name, **kwargs):
        from hopshift.testing.report import ConformanceReport

        report = ConformanceReport(kind="target", subject=name)
        report.add_fail("renderer.compute", "ModuleNotFoundError: No module named 'x.compute'")
        return report

    monkeypatch.setattr(kit, "check_target", fake_check_target)
    result = CliRunner().invoke(cli, ["targets", "check", "aws"])

    assert result.exit_code == 1
    assert "FAIL  renderer.compute  ModuleNotFoundError" in result.output


def test_sources_list_and_check() -> None:
    runner = CliRunner()

    listed = runner.invoke(cli, ["sources", "list"])
    assert listed.exit_code == 0, listed.output
    assert listed.output.splitlines()[0].split() == ["NAME", "LABEL", "TIER", "PLATFORM", "SCHEMAS"]
    assert "vmware  VMware vSphere  validated  vmware_vsphere  vmware-discovery-stage1, vmware-discovery" in listed.output

    checked = runner.invoke(cli, ["sources", "check", "vmware", "--input", str(FIXTURE)])
    assert checked.exit_code == 0, checked.output
    assert checked.output.startswith("source conformance: vmware (VMware vSphere) - ")
    assert "PASS  render[aws]" in checked.output

    missing_input = runner.invoke(cli, ["sources", "check", "vmware"])
    assert missing_input.exit_code == 2 and "--input" in missing_input.output

    unknown = runner.invoke(cli, ["sources", "check", "nope", "--input", str(FIXTURE)])
    assert unknown.exit_code == 1 and "unknown source 'nope'" in unknown.output


def test_plugins_list_without_plugins() -> None:
    result = CliRunner().invoke(cli, ["plugins", "list"])

    assert result.exit_code == 0, result.output
    assert "no plugins installed" in result.output or result.output.startswith("GROUP")


def test_plugins_list_reports_load_status(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "nimbus_plugin.py").write_text(
        "from hopshift.targets.registry import TargetSpec\n"
        'TARGET = TargetSpec(name="nimbus", label="Nimbus Cloud", blurb="x", package="nimbus_plugin")\n',
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    fake = {
        "hopshift.targets": [
            EntryPoint("nimbus", "nimbus_plugin:TARGET", "hopshift.targets"),
            EntryPoint("broken", "nimbus_plugin:MISSING", "hopshift.targets"),
        ],
        "hopshift.sources": [EntryPoint("wrong", "hopshift.targets.registry:TargetSpec", "hopshift.sources")],
    }
    monkeypatch.setattr("importlib.metadata.entry_points", lambda group=None, **kw: fake.get(group, []))

    result = CliRunner().invoke(cli, ["plugins", "list"])

    assert result.exit_code == 1, result.output  # a broken plugin makes the listing exit non-zero
    lines = result.output.splitlines()
    assert lines[0].split() == ["GROUP", "NAME", "ENTRY", "POINT", "DISTRIBUTION", "STATUS", "DETAIL"]
    rows = {line.split()[1]: line for line in lines[2:]}
    assert rows["nimbus"].split()[:5] == ["hopshift.targets", "nimbus", "nimbus_plugin:TARGET", "-", "ok"]
    assert rows["nimbus"].endswith("nimbus (Nimbus Cloud, experimental)")
    assert rows["broken"].split()[:5] == ["hopshift.targets", "broken", "nimbus_plugin:MISSING", "-", "error"]
    assert "AttributeError" in rows["broken"]
    assert rows["wrong"].split()[:2] == ["hopshift.sources", "wrong"] and "error" in rows["wrong"] and "TypeError" in rows["wrong"]

    as_json = CliRunner().invoke(cli, ["plugins", "list", "--format", "json"])
    payload = json.loads(as_json.output)
    assert [(item["name"], item["status"]) for item in payload] == [("broken", "error"), ("nimbus", "ok"), ("wrong", "error")]


def test_matrix_check_and_render(tmp_path: Path) -> None:
    runner = CliRunner()

    check = runner.invoke(cli, ["matrix", "check"])
    assert check.exit_code == 0, check.output
    assert "support matrix is current" in check.output

    output = tmp_path / "support-matrix.md"
    render = runner.invoke(cli, ["matrix", "render", "--output", str(output)])
    assert render.exit_code == 0, render.output
    assert output.read_text(encoding="utf-8") == matrix.MATRIX_DOC.read_text(encoding="utf-8")

    bad = tmp_path / "support.yaml"
    bad.write_text("pairs:\n  - source: vmware\n    target: nimbus\n    tier: validated\n", encoding="utf-8")
    failed = runner.invoke(cli, ["matrix", "check", "--support", str(bad), "--output", str(output)])
    assert failed.exit_code == 1
    assert "unknown target 'nimbus'" in failed.output

    output.write_text("stale\n", encoding="utf-8")
    stale = runner.invoke(cli, ["matrix", "check", "--output", str(output)])
    assert stale.exit_code == 1 and "is stale" in stale.output
