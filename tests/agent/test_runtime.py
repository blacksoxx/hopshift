from __future__ import annotations

import json
from pathlib import Path

import pytest

import agent.nodes.reporter as reporter_module
from agent.runtime import MigrationRuntime, RunError, RunOptions, build_run_config

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "discovery_multi_vm.json"


class _FakeLLMClient:
    def __init__(self, config: dict[str, object]) -> None:
        self.config = config

    def generate_review_notes(self, prompt: str, system_prompt: str | None = None) -> str:
        return "# notes"


def _base_config() -> dict[str, object]:
    return {
        "generation": {"mode": "deterministic"},
        "mcp": {"enabled": False},
        "validation": {"run_terraform_validate": False, "run_tflint": False, "run_opa": False},
        "output": {"base_dir": "output"},
        "required_tags": {"MigratedFrom": "vmware-vcenter", "SourceVCenter": "{source_vcenter}"},
        "vsphere": {"hard_blockers": ["encrypted_vm_present", "rdm_disk_present", "shared_disk_present"]},
        "runtime": {"default_pause_points": ["review_cim", "approve_output"]},
    }


@pytest.fixture
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> MigrationRuntime:
    monkeypatch.setattr(reporter_module, "LLMClient", _FakeLLMClient)
    return MigrationRuntime(_base_config(), runs_dir=tmp_path / "runs", checkpoint_db=tmp_path / "runs" / "cp.sqlite")


def _discovery() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _options(**overrides: object) -> RunOptions:
    values: dict[str, object] = {"cloud": "aws", "environment": "dev", "owner": "platform"}
    values.update(overrides)
    return RunOptions(**values)  # type: ignore[arg-type]


def test_summarize_reports_compliance_counts() -> None:
    from agent.runtime import _summarize

    summary = _summarize(
        {
            "status": "running",
            "validation_result": {"passed": False, "errors": ["x"]},
            "compliance_result": {"summary": {"controls": 10, "passed": 7, "failed": 2, "advisory": 1, "not_applicable": 0}},
        }
    )

    assert summary["validation_passed"] is False
    assert summary["compliance_failed"] == 2
    assert summary["compliance_advisory"] == 1
    assert "compliance_failed" not in _summarize({"status": "running"})


def test_build_run_config_applies_options_like_the_cli() -> None:
    cfg = build_run_config(_base_config(), _options(skip_opa=True, no_mcp=True, dry_run=True, mode="deterministic"), "/tmp/out")

    assert cfg["target_cloud"] == "aws"
    assert cfg["generation"]["mode"] == "deterministic"
    assert cfg["validation"]["run_opa"] is False
    assert cfg["mcp"]["enabled"] is False
    assert cfg["output"] == {"base_dir": "/tmp/out", "dry_run": True, "llm_review_notes": True}
    assert cfg["required_tags"]["Environment"] == "dev" and cfg["required_tags"]["Owner"] == "platform"


def test_build_run_config_requires_provider_for_llm_modes() -> None:
    with pytest.raises(RunError, match="requires an llm_provider"):
        build_run_config(_base_config(), _options(mode="llm"), "/tmp/out")


def test_run_pauses_for_cim_review_then_output_approval_then_succeeds(runtime: MigrationRuntime) -> None:
    record = runtime.create_run(_discovery(), _options(), input_filename="lab.json")
    assert record.status == "created" and record.options["pause_points"] == ["review_cim", "approve_output"]

    record = runtime.start(record.run_id)
    assert record.status == "paused"
    assert record.paused_before == "hcl_generator" and record.pause_point == "review_cim"

    state = runtime.get_state(record.run_id)
    assert state["next"] == ["hcl_generator"]
    names = [unit["name"] for unit in state["values"]["sized_cim"]["compute_units"]]
    assert names == ["web-01", "db-01", "mgmt-jump"]
    assert "config" not in state["values"]

    # Operator edits the CIM while paused: rename a VM, drop another.
    edited = state["values"]["sized_cim"]
    edited["compute_units"] = [unit for unit in edited["compute_units"] if unit["name"] != "mgmt-jump"]
    edited["compute_units"][0]["name"] = "web-01-renamed"
    runtime.patch_state(record.run_id, {"sized_cim": edited})

    record = runtime.resume(record.run_id)
    assert record.status == "paused" and record.pause_point == "approve_output"
    assert runtime.artifacts(record.run_id) == []  # nothing written before approval

    record = runtime.resume(record.run_id)
    assert record.status == "succeeded"

    paths = {artifact["path"] for artifact in runtime.artifacts(record.run_id)}
    assert "aws-migration/compute_web-01-renamed.tf" in paths
    assert not any("mgmt-jump" in path for path in paths)
    assert "quarantine_report.json" in paths

    event_types = [event["type"] for event in runtime.events(record.run_id)]
    assert event_types[0] == "start" and "paused" in event_types and "patch" in event_types and event_types[-1] == "end"
    node_events = [event["node"] for event in runtime.events(record.run_id) if event["type"] == "node"]
    assert node_events[:4] == ["ingest", "blocker_parser", "enricher", "cim_mapper"]
    assert node_events[-1] == "reporter"

    listed = runtime.list_runs()
    assert [run.run_id for run in listed] == [record.run_id]


def test_run_without_pause_points_completes_in_one_call(runtime: MigrationRuntime) -> None:
    runtime.default_pause_points = []
    record = runtime.create_run(_discovery(), _options(dry_run=True))

    record = runtime.start(record.run_id)

    assert record.status == "succeeded"
    assert runtime.artifacts(record.run_id) == []  # dry run writes nothing
    assert runtime.events(record.run_id)[-1]["summary"]["hcl_files"] == 12


def test_rerun_from_node_forks_and_completes(runtime: MigrationRuntime) -> None:
    runtime.default_pause_points = []
    record = runtime.start(runtime.create_run(_discovery(), _options()).run_id)
    assert record.status == "succeeded"
    before = len(runtime.events(record.run_id))

    record = runtime.rerun_from(record.run_id, "sizer")

    assert record.status == "succeeded"
    events = runtime.events(record.run_id)[before:]
    assert events[0]["type"] == "rerun" and events[0]["node"] == "sizer"
    assert [event["node"] for event in events if event["type"] == "node"][0] == "sizer"


def test_lifecycle_guards(runtime: MigrationRuntime) -> None:
    record = runtime.create_run(_discovery(), _options())

    with pytest.raises(RunError, match="only a paused run"):
        runtime.resume(record.run_id)
    with pytest.raises(RunError, match="can only be patched while paused"):
        runtime.patch_state(record.run_id, {"sized_cim": {}})
    with pytest.raises(RunError, match="unknown run"):
        runtime.get_run("nope")
    with pytest.raises(RunError, match="unknown pause points"):
        runtime.create_run(_discovery(), _options(pause_points=["later"]))
    with pytest.raises(ValueError, match="virtual_machines"):
        runtime.create_run({"not": "a payload"}, _options())


def test_patch_rejects_unknown_keys_and_invalid_cim(runtime: MigrationRuntime) -> None:
    record = runtime.start(runtime.create_run(_discovery(), _options()).run_id)
    assert record.status == "paused"

    with pytest.raises(RunError, match="not patchable"):
        runtime.patch_state(record.run_id, {"hcl_output": {}})
    with pytest.raises(RunError, match="invalid sized_cim"):
        runtime.patch_state(record.run_id, {"sized_cim": {"compute_units": "nope"}})


def test_node_failure_marks_run_error(runtime: MigrationRuntime, monkeypatch: pytest.MonkeyPatch) -> None:
    import agent.graph as graph_module
    import agent.nodes.sizer as sizer_module

    def _boom(state):
        raise RuntimeError("sizing table unavailable")

    monkeypatch.setattr(sizer_module, "sizer", _boom)
    monkeypatch.setattr(graph_module, "sizer", _boom)
    runtime.default_pause_points = []

    record = runtime.start(runtime.create_run(_discovery(), _options()).run_id)

    assert record.status == "error"
    assert "sizing table unavailable" in (record.error or "")
    assert runtime.events(record.run_id)[-1]["type"] == "error"


def test_empty_pause_list_means_no_pauses_and_notes_can_be_disabled(runtime: MigrationRuntime) -> None:
    record = runtime.create_run(_discovery(), _options(pause_points=[], llm_review_notes=False, dry_run=True))
    assert record.options["pause_points"] == []

    record = runtime.start(record.run_id)

    assert record.status == "succeeded"
    config = json.loads((Path(record.run_dir) / "config.json").read_text(encoding="utf-8"))
    assert config["output"]["llm_review_notes"] is False
