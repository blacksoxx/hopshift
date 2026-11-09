"""Terraform process execution: environment, backend override, streamed and masked logs.

`TerraformRunner` runs one command at a time in a workspace, streams stdout/stderr line by line
into `terraform.log` through a masking function, enforces a deadline by killing the process
group, and supports cancellation (SIGTERM, then SIGKILL after a grace period).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from loguru import logger

from vma.secrets import mask_values

MASK = "***"
KILL_GRACE_SECONDS = 10.0
# Cloud credential variables that must not leak from the API process into a deployment that
# runs with a connection (the connection supplies its own).
CLOUD_ENV_PREFIXES: tuple[str, ...] = ("AWS_", "ARM_", "GOOGLE_", "OS_")
SUPPORTED_BACKENDS: tuple[str, ...] = ("s3", "azurerm", "gcs")

# `key = value` / `key: value` where the key looks like a secret; the value is replaced.
_SECRET_ASSIGNMENT = re.compile(r"(?i)((?:secret|password|token)[^\n=:]*[=:]\s*)(\S+)")
_SECRET_ENV_KEY = re.compile(r"(?i)(secret|password|token|private_key|credentials)")
_PLAN_LINE = re.compile(r"Plan: (\d+) to add, (\d+) to change, (\d+) to destroy")
_APPLY_LINE = re.compile(r"Apply complete! Resources: (\d+) added, (\d+) changed, (\d+) destroyed")
_DESTROY_LINE = re.compile(r"Destroy complete! Resources: (\d+) destroyed")


def make_masker(secret_values: list[str]) -> Callable[[str], str]:
    values = [value for value in secret_values if value and len(value) >= 4]

    def mask(text: str) -> str:
        masked = mask_values(text, values) if values else text
        return _SECRET_ASSIGNMENT.sub(lambda match: match.group(1) + MASK, masked)

    return mask


def secret_env_values(env: dict[str, str]) -> list[str]:
    """Values of secret-looking environment variables, for masking."""
    return [value for key, value in env.items() if _SECRET_ENV_KEY.search(key) and value]


def build_environment(
    *,
    data_dir: Path,
    connection_env: dict[str, str] | None,
    plugin_cache_dir: str | None,
    strip_cloud_variables: bool,
) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not (strip_cloud_variables and key.upper().startswith(CLOUD_ENV_PREFIXES))
    }
    env.update({str(key): str(value) for key, value in (connection_env or {}).items() if value is not None})
    env["TF_DATA_DIR"] = str(data_dir)
    env["TF_IN_AUTOMATION"] = "1"
    env["TF_INPUT"] = "0"
    if plugin_cache_dir:
        cache = Path(plugin_cache_dir).expanduser()
        try:
            cache.mkdir(parents=True, exist_ok=True)
            env["TF_PLUGIN_CACHE_DIR"] = str(cache)
        except OSError as exc:
            logger.warning("deploy: cannot create terraform plugin cache dir {}: {}", cache, exc)
    return env


def render_backend_override(remote_state: dict[str, Any] | None, local_state_path: str) -> str:
    """`backend_override.tf`: Terraform merges *_override.tf over the generated providers.tf."""
    cfg = remote_state if isinstance(remote_state, dict) else {}
    if cfg.get("enabled"):
        backend_type = str(cfg.get("type") or "").strip()
        if backend_type not in SUPPORTED_BACKENDS:
            raise ValueError(f"deploy.remote_state.type must be one of {', '.join(SUPPORTED_BACKENDS)}")
        config = cfg.get("config") if isinstance(cfg.get("config"), dict) else {}
        lines = [f'  backend "{backend_type}" {{']
        for key in sorted(config):
            lines.append(f"    {key} = {_hcl_literal(config[key])}")
        lines.append("  }")
    else:
        lines = ['  backend "local" {', f"    path = {_hcl_literal(local_state_path)}", "  }"]
    return "\n".join(["# Written by the platform before every deployment; do not edit.", "terraform {", *lines, "}", ""])


def _hcl_literal(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        inner = ", ".join(f"{key} = {_hcl_literal(val)}" for key, val in value.items())
        return "{ " + inner + " }"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_hcl_literal(item) for item in value) + "]"
    return json.dumps(str(value))


@dataclass
class CommandResult:
    args: list[str]
    returncode: int
    captured: str = ""
    timed_out: bool = False
    cancelled: bool = False
    duration: float = 0.0
    error_lines: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out and not self.cancelled

    def error_summary(self) -> str:
        if self.timed_out:
            return f"terraform {self.args[0]} timed out"
        if self.cancelled:
            return f"terraform {self.args[0]} was cancelled"
        detail = next((line for line in self.error_lines if line.lower().startswith("error")), None)
        detail = detail or (self.error_lines[-1] if self.error_lines else "")
        return f"terraform {self.args[0]} failed with exit code {self.returncode}" + (f": {detail}" if detail else "")


class LogWriter:
    """Append-only, line-oriented log file shared by every command of one deployment."""

    def __init__(self, path: Path, mask: Callable[[str], str]) -> None:
        self.path = path
        self.mask = mask
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

    def write(self, line: str) -> None:
        text = self.mask(line.rstrip("\r\n"))
        with self._lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(text + "\n")


class TerraformRunner:
    def __init__(
        self,
        binary: str,
        cwd: Path,
        env: dict[str, str],
        log: LogWriter,
        deadline: float | None = None,
    ) -> None:
        self.binary = binary
        self.cwd = cwd
        self.env = env
        self.log = log
        self.deadline = deadline
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[str] | None = None
        self._cancelled = False
        self._timed_out = False

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def run(self, *args: str, capture: bool = False) -> CommandResult:
        """Run `terraform <args>`; stream output into the log unless `capture` (then return it)."""
        argv = [self.binary, *args]
        self.log.write(f"$ terraform {' '.join(args)}")
        started = time.monotonic()
        remaining = None if self.deadline is None else self.deadline - started
        if remaining is not None and remaining <= 0:
            self._timed_out = True
            self.log.write("## deadline reached before the command could start")
            return CommandResult(list(args), returncode=-1, timed_out=True)

        with self._lock:
            if self._cancelled:
                return CommandResult(list(args), returncode=-1, cancelled=True)
            proc = subprocess.Popen(
                argv,
                cwd=str(self.cwd),
                env=self.env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                start_new_session=True,  # own process group: timeouts and cancel reach child processes too
            )
            self._proc = proc

        timer: threading.Timer | None = None
        if remaining is not None:
            timer = threading.Timer(remaining, self._on_timeout)
            timer.daemon = True
            timer.start()

        captured: list[str] = []
        tail: list[str] = []
        try:
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = raw.rstrip("\r\n")
                if capture:
                    captured.append(line)
                else:
                    self.log.write(line)
                if line.strip():
                    tail.append(self.log.mask(line))
                    del tail[:-20]
            returncode = proc.wait()
        finally:
            if timer is not None:
                timer.cancel()
            with self._lock:
                self._proc = None

        duration = time.monotonic() - started
        result = CommandResult(
            list(args), returncode=returncode, captured="\n".join(captured), timed_out=self._timed_out,
            cancelled=self._cancelled, duration=duration, error_lines=tail,
        )
        status = "timed out" if result.timed_out else "cancelled" if result.cancelled else f"exit code {returncode}"
        self.log.write(f"## terraform {args[0]}: {status} after {duration:.1f}s")
        return result

    def cancel(self) -> None:
        """SIGTERM the process group now; SIGKILL whatever is left after the grace period."""
        with self._lock:
            self._cancelled = True
            proc = self._proc
        if proc is None:
            return
        self.log.write("## cancel requested")
        _signal_group(proc, signal.SIGTERM)
        killer = threading.Timer(KILL_GRACE_SECONDS, _signal_group, args=(proc, signal.SIGKILL))
        killer.daemon = True
        killer.start()

    def _on_timeout(self) -> None:
        with self._lock:
            self._timed_out = True
            proc = self._proc
        if proc is not None:
            self.log.write("## timeout reached; killing terraform")
            _signal_group(proc, signal.SIGKILL)


def _signal_group(proc: subprocess.Popen[str], sig: signal.Signals) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, sig)  # start_new_session makes the pid the group id
    except ProcessLookupError:
        pass
    except OSError as exc:  # pragma: no cover - platform specific
        logger.warning("deploy: could not signal terraform process group: {}", exc)
        try:
            proc.send_signal(sig)
        except OSError:
            pass


# ── summaries ────────────────────────────────────────────────────────────────


def empty_summary() -> dict[str, Any]:
    return {"add": 0, "change": 0, "destroy": 0, "replace": 0, "resources": []}


def summarize_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Counts and per-resource actions from `terraform show -json tfplan` output."""
    summary = empty_summary()
    for item in plan.get("resource_changes") or []:
        if not isinstance(item, dict):
            continue
        change = item.get("change") if isinstance(item.get("change"), dict) else {}
        actions = [str(action) for action in (change.get("actions") or [])]
        if not actions or actions in (["no-op"], ["read"]):
            continue
        if "create" in actions and "delete" in actions:
            summary["replace"] += 1
        elif actions == ["create"]:
            summary["add"] += 1
        elif actions == ["update"]:
            summary["change"] += 1
        elif actions == ["delete"]:
            summary["destroy"] += 1
        summary["resources"].append({"address": item.get("address"), "type": item.get("type"), "actions": actions})
    return summary


def summarize_output(lines: list[str], resources: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Counts from the final `Apply complete!` / `Destroy complete!` / `Plan:` line of a log."""
    summary = empty_summary()
    summary["resources"] = list(resources or [])
    for line in reversed(lines):
        match = _APPLY_LINE.search(line) or _PLAN_LINE.search(line)
        if match:
            summary["add"], summary["change"], summary["destroy"] = (int(group) for group in match.groups())
            return summary
        match = _DESTROY_LINE.search(line)
        if match:
            summary["destroy"] = int(match.group(1))
            return summary
    return summary


def redact_plan(plan: dict[str, Any], sensitive_variables: set[str]) -> dict[str, Any]:
    """Blank the values of sensitive input variables in plan JSON (Terraform keeps them in clear)."""
    variables = plan.get("variables")
    if isinstance(variables, dict):
        for name in list(variables):
            if name in sensitive_variables and isinstance(variables[name], dict):
                variables[name] = {"value": MASK}
    return plan


def compute_artifacts_hash(root: Path) -> str:
    """sha256 over the sorted relative paths and contents of every .tf file in the root module."""
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.tf")):
        if not path.is_file():
            continue
        digest.update(str(path.relative_to(root)).replace("\\", "/").encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()
