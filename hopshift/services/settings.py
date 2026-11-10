"""Editable configuration overlay.

`config.yaml` stays the source of truth for everything an operator should change with a
deployment. A small allow-list of settings can also be changed from the UI by an admin; those
values live in SQLite and are applied on top of the file at run creation time. Every change is
audited by the caller.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from hopshift.services.db import Database, register_migration

register_migration(
    "settings_001_overrides",
    """
    CREATE TABLE IF NOT EXISTS settings (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      updated_by TEXT NOT NULL
    );
    """,
)


@dataclass(frozen=True)
class SettingSpec:
    key: str
    type: str  # string | integer | boolean | choice | list
    label: str
    help: str
    group: str
    options: tuple[str, ...] = ()
    minimum: int | None = None
    maximum: int | None = None
    choices_for_list: tuple[str, ...] = field(default=())


EDITABLE_SETTINGS: dict[str, SettingSpec] = {
    spec.key: spec
    for spec in (
        SettingSpec("generation.mode", "choice", "Generation mode", "How Terraform is produced from the CIM.", "Generation", options=("deterministic", "llm", "hybrid")),
        SettingSpec("llm.provider", "choice", "LLM provider", "Provider used for review notes and llm/hybrid generation.", "AI", options=("anthropic", "openai", "google")),
        SettingSpec("llm.models.anthropic", "string", "Anthropic model", "Model id used when the provider is Anthropic.", "AI"),
        SettingSpec("llm.models.openai", "string", "OpenAI model", "Model id used when the provider is OpenAI.", "AI"),
        SettingSpec("llm.models.google", "string", "Google model", "Model id used when the provider is Google.", "AI"),
        SettingSpec("llm.effort", "choice", "Reasoning effort", "Anthropic reasoning depth.", "AI", options=("low", "medium", "high", "xhigh", "max")),
        SettingSpec("output.llm_review_notes", "boolean", "AI review notes by default", "Write review notes with the model unless a run opts out.", "AI"),
        SettingSpec("validation.run_terraform_validate", "boolean", "terraform validate", "Run terraform init and validate on generated output.", "Validation"),
        SettingSpec("validation.run_tflint", "boolean", "tflint", "Run tflint on generated output.", "Validation"),
        SettingSpec("validation.run_opa", "boolean", "OPA policies", "Evaluate security and compliance policies.", "Validation"),
        SettingSpec("mcp.enabled", "boolean", "Terraform registry docs (MCP)", "Retrieve provider documentation for llm/hybrid generation.", "AI"),
        SettingSpec("runtime.default_pause_points", "list", "Default pause points", "Where new runs pause for review.", "Runs", choices_for_list=("review_cim", "approve_output")),
        SettingSpec("pipeline.abort_threshold_pct", "string", "Abort threshold", "Stop when more than this fraction of VMs is blocked (0..1).", "Runs"),
        SettingSpec("security.auth.mfa", "choice", "MFA policy", "Whether every user must enrol a second factor.", "Security", options=("optional", "required")),
        SettingSpec("security.auth.session_hours", "integer", "Session lifetime (hours)", "Absolute session expiry.", "Security", minimum=1, maximum=168),
        SettingSpec("security.auth.idle_minutes", "integer", "Idle timeout (minutes)", "Sessions end after this much inactivity.", "Security", minimum=5, maximum=1440),
        SettingSpec("security.auth.lockout_threshold", "integer", "Lockout threshold", "Failed logins before an account is locked.", "Security", minimum=3, maximum=20),
        SettingSpec("security.auth.lockout_minutes", "integer", "Lockout duration (minutes)", "How long a locked account stays locked.", "Security", minimum=1, maximum=1440),
        SettingSpec("security.retention.runs_days", "integer", "Run retention (days)", "Delete runs older than this; 0 keeps everything.", "Retention", minimum=0, maximum=3650),
        SettingSpec("security.retention.audit_days", "integer", "Audit retention (days)", "Prune audit entries older than this; 0 keeps everything.", "Retention", minimum=0, maximum=3650),
        SettingSpec("deploy.allow_apply", "boolean", "Allow apply", "Permit terraform apply from the platform.", "Deployments"),
        SettingSpec("deploy.allow_destroy", "boolean", "Allow destroy", "Permit terraform destroy from the platform.", "Deployments"),
        SettingSpec("deploy.timeout_minutes", "integer", "Terraform timeout (minutes)", "Maximum duration of a plan, apply or destroy.", "Deployments", minimum=1, maximum=720),
    )
}


class SettingsError(ValueError):
    pass


class SettingsStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def overrides(self) -> dict[str, Any]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
        return {row["key"]: json.loads(row["value"]) for row in rows}

    def update(self, values: dict[str, Any], actor: str) -> dict[str, Any]:
        """Validate and persist the given dotted keys. A value of None removes the override."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.db.connect() as conn:
            for key, raw in values.items():
                spec = EDITABLE_SETTINGS.get(key)
                if spec is None:
                    raise SettingsError(f"setting {key} is not editable from the UI")
                if raw is None:
                    conn.execute("DELETE FROM settings WHERE key = ?", (key,))
                    continue
                value = _coerce(spec, raw)
                conn.execute(
                    "INSERT INTO settings(key, value, updated_at, updated_by) VALUES (?,?,?,?)"
                    " ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at,"
                    " updated_by = excluded.updated_by",
                    (key, json.dumps(value), now, actor),
                )
        return self.overrides()

    def apply(self, base_config: dict[str, Any]) -> dict[str, Any]:
        config = copy.deepcopy(base_config)
        for key, value in self.overrides().items():
            _set_dotted(config, key, value)
        return config

    def effective_values(self, base_config: dict[str, Any]) -> dict[str, Any]:
        config = self.apply(base_config)
        return {key: _get_dotted(config, key) for key in EDITABLE_SETTINGS}

    @staticmethod
    def schema() -> list[dict[str, Any]]:
        return [
            {
                "key": spec.key, "type": spec.type, "label": spec.label, "help": spec.help, "group": spec.group,
                "options": list(spec.options or spec.choices_for_list), "minimum": spec.minimum, "maximum": spec.maximum,
            }
            for spec in EDITABLE_SETTINGS.values()
        ]


def _coerce(spec: SettingSpec, raw: Any) -> Any:
    if spec.type == "boolean":
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str) and raw.lower() in {"true", "false"}:
            return raw.lower() == "true"
        raise SettingsError(f"{spec.key} must be a boolean")
    if spec.type == "integer":
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise SettingsError(f"{spec.key} must be an integer") from exc
        if spec.minimum is not None and value < spec.minimum:
            raise SettingsError(f"{spec.key} must be at least {spec.minimum}")
        if spec.maximum is not None and value > spec.maximum:
            raise SettingsError(f"{spec.key} must be at most {spec.maximum}")
        return value
    if spec.type == "choice":
        value = str(raw)
        if value not in spec.options:
            raise SettingsError(f"{spec.key} must be one of {', '.join(spec.options)}")
        return value
    if spec.type == "list":
        if not isinstance(raw, list):
            raise SettingsError(f"{spec.key} must be a list")
        values = [str(item) for item in raw]
        bad = [item for item in values if spec.choices_for_list and item not in spec.choices_for_list]
        if bad:
            raise SettingsError(f"{spec.key}: unknown values {', '.join(bad)}")
        return values
    value = str(raw)
    if spec.key == "pipeline.abort_threshold_pct":
        try:
            number = float(value)
        except ValueError as exc:
            raise SettingsError("abort threshold must be a number between 0 and 1") from exc
        if not 0 <= number <= 1:
            raise SettingsError("abort threshold must be between 0 and 1")
        return number
    if len(value) > 200:
        raise SettingsError(f"{spec.key} is too long")
    return value


def _set_dotted(config: dict[str, Any], key: str, value: Any) -> None:
    parts = key.split(".")
    node = config
    for part in parts[:-1]:
        child = node.get(part)
        if not isinstance(child, dict):
            child = {}
            node[part] = child
        node = child
    node[parts[-1]] = value


def _get_dotted(config: dict[str, Any], key: str) -> Any:
    node: Any = config
    for part in key.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node
