from __future__ import annotations

from pathlib import Path

import validation.opa_client as opa_module
from validation.opa_client import OPAClient, _extract_compliance, _extract_deny_messages


def test_extract_deny_messages_returns_empty_when_no_deny_present() -> None:
    payload = {
        "result": [
            {
                "expressions": [
                    {
                        "value": {
                            "vmwaremigration": {
                                "requires_metadata_block": False,
                                "some_other_flag": True,
                            }
                        }
                    }
                ]
            }
        ]
    }

    assert _extract_deny_messages(payload) == []


def test_extract_deny_messages_collects_all_deny_strings() -> None:
    payload = {
        "result": [
            {
                "expressions": [
                    {
                        "value": {
                            "vmwaremigration": {
                                "deny": [
                                    "tags_required: Environment tag missing",
                                    "no_open_ingress: open ingress is forbidden",
                                ]
                            }
                        }
                    }
                ]
            }
        ]
    }

    assert _extract_deny_messages(payload) == [
        "tags_required: Environment tag missing",
        "no_open_ingress: open ingress is forbidden",
    ]


def test_opa_binary_retries_without_v0_compatible_flag(monkeypatch, tmp_path: Path) -> None:
    policies_dir = tmp_path / "policies"
    policies_dir.mkdir(parents=True, exist_ok=True)
    (policies_dir / "dummy.rego").write_text("package vmwaremigration\n", encoding="utf-8")

    calls: list[list[str]] = []

    def _fake_run_command(command: list[str], timeout_seconds: int) -> opa_module._CommandResult:
        calls.append(command)
        if "--v0-compatible" in command:
            return opa_module._CommandResult(
                returncode=1,
                stdout="",
                stderr="unknown flag: --v0-compatible",
            )

        return opa_module._CommandResult(
            returncode=0,
            stdout='{"result":[{"expressions":[{"value":{"vmwaremigration":{"deny":[]}}}]}]}',
            stderr="",
        )

    monkeypatch.setattr(opa_module, "_run_command", _fake_run_command)

    client = OPAClient(mode="binary", opa_bin="opa", timeout_seconds=30)
    result = client.evaluate(input_data={"generated_files": {}}, policies_dir=policies_dir)

    assert result.passed is True
    assert len(calls) == 2
    assert "--v0-compatible" in calls[0]
    assert "--v0-compatible" not in calls[1]


_COMPLIANCE_DOC = {
    "vmwaremigration": {
        "deny": ["compliance AWS-EC2-IMDSV2: metadata_options block is missing (aws_instance.web)"],
        "compliance": {
            "deny": ["compliance AWS-EC2-IMDSV2: metadata_options block is missing (aws_instance.web)"],
            "evaluated": ["AWS-EC2-IMDSV2", "ALL-TAGS-REQUIRED"],
            "violations": [
                {
                    "control": "AWS-VPC-FLOW-LOGS",
                    "level": "advisory",
                    "resource": "aws_vpc.main",
                    "file": "aws-migration/networking_vpc.tf",
                    "message": "no aws_flow_log captures traffic for this VPC",
                },
                {
                    "control": "AWS-EC2-IMDSV2",
                    "level": "enforce",
                    "resource": "aws_instance.web",
                    "file": "aws-migration/compute_web.tf",
                    "message": "metadata_options block is missing",
                },
            ],
        },
    }
}


def test_extract_compliance_from_binary_and_server_shapes() -> None:
    binary_payload = {"result": [{"expressions": [{"value": _COMPLIANCE_DOC, "text": "data"}]}]}
    server_payload = {"result": _COMPLIANCE_DOC}

    for payload in (binary_payload, server_payload):
        violations, evaluated = _extract_compliance(payload)

        assert evaluated == ["ALL-TAGS-REQUIRED", "AWS-EC2-IMDSV2"]
        assert [item["control"] for item in violations] == ["AWS-EC2-IMDSV2", "AWS-VPC-FLOW-LOGS"]
        assert violations[0]["level"] == "enforce" and violations[0]["file"] == "aws-migration/compute_web.tf"
        # the compliance deny set is collected by the unchanged deny walker exactly once per package
        assert _extract_deny_messages(payload).count(
            "compliance AWS-EC2-IMDSV2: metadata_options block is missing (aws_instance.web)"
        ) == 2


def test_opa_server_mode_returns_compliance_data(monkeypatch) -> None:
    import io
    import json

    class _Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.close()

    def _fake_urlopen(req, timeout):  # noqa: ANN001
        assert req.full_url == "http://opa.local:8181/v1/data"
        return _Response(json.dumps({"result": _COMPLIANCE_DOC}).encode("utf-8"))

    monkeypatch.setattr(opa_module.url_request, "urlopen", _fake_urlopen)

    client = OPAClient(mode="server", opa_server_url="http://opa.local:8181")
    result = client.evaluate(input_data={"resources": []}, policies_dir=Path("unused"))

    assert result.passed is False
    assert result.evaluated == ["ALL-TAGS-REQUIRED", "AWS-EC2-IMDSV2"]
    assert [item["control"] for item in result.enforce_violations] == ["AWS-EC2-IMDSV2"]
    assert [item["control"] for item in result.advisory_violations] == ["AWS-VPC-FLOW-LOGS"]
