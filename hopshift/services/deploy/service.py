"""DeployService: terraform plan / apply / destroy for a run, with approval gates.

Layout under a run folder (see docs/deployments.md):

    <run_dir>/deploy/workspace/              fresh copy of artifacts/<cloud>-migration/ per deployment
    <run_dir>/deploy/state/terraform.tfstate local backend (never inside artifacts/)
    <run_dir>/deploy/.terraform/             TF_DATA_DIR (providers, modules)
    <run_dir>/deploy/terraform.lock.hcl      provider lock carried between deployments
    <run_dir>/deploy/terraform.tfvars.json   operator-supplied variable values
    <run_dir>/deploy/<deployment_id>/        deployment.json, terraform.log, tfplan, plan.json

Gates: plan needs a succeeded run with a root module; apply needs `deploy.allow_apply`, a
succeeded plan of the same run whose artifacts are unchanged, and `confirmation == run_id`;
destroy needs `deploy.allow_destroy` and the same confirmation. One active deployment per run.
"""
from __future__ import annotations

import json
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from loguru import logger

from hopshift.services.deploy import variables as tfvars
from hopshift.services.deploy.store import (
    ACTIONS,
    ACTIVE_STATUSES,
    TERMINAL_STATUSES,
    Deployment,
    DeploymentStore,
    new_deployment_id,
    write_mirror,
)
from hopshift.services.deploy.terraform import (
    LogWriter,
    TerraformRunner,
    build_environment,
    compute_artifacts_hash,
    make_masker,
    redact_plan,
    render_backend_override,
    secret_env_values,
    summarize_output,
    summarize_plan,
)
from hopshift.services.errors import (
    Conflict,
    Forbidden,
    Invalid,
    NotFound,
    PlatformError,
    Unavailable,
)
from hopshift.services.secrets import mask_values

if TYPE_CHECKING:  # pragma: no cover - typing only; hopshift.pipeline.runtime pulls in langgraph
    from hopshift.pipeline.runtime import MigrationRuntime, RunRecord

RUNTIME_EXTRA = "runtime"
LOCAL_STATE_RELATIVE = "../state/terraform.tfstate"
CANCEL_WAIT_SECONDS = 3.0


@dataclass(frozen=True)
class RunPaths:
    run_id: str
    cloud: str
    run_dir: Path
    root_module: Path
    deploy_dir: Path

    @property
    def workspace(self) -> Path:
        return self.deploy_dir / "workspace"

    @property
    def state_file(self) -> Path:
        return self.deploy_dir / "state" / "terraform.tfstate"

    @property
    def data_dir(self) -> Path:
        return self.deploy_dir / ".terraform"

    @property
    def tfvars(self) -> Path:
        return self.deploy_dir / "terraform.tfvars.json"

    @property
    def lock_file(self) -> Path:
        return self.deploy_dir / "terraform.lock.hcl"

    def deployment_dir(self, deployment_id: str) -> Path:
        return self.deploy_dir / deployment_id


@dataclass
class ConnectionContext:
    id: str | None = None
    name: str | None = None
    provider: str | None = None
    env: dict[str, str] | None = None
    secret_values: list[str] | None = None


class DeployService:
    def __init__(
        self,
        platform: Any,
        runtime_provider: Callable[[], "MigrationRuntime"] | None = None,
        max_workers: int = 2,
    ) -> None:
        self.platform = platform
        self.store = DeploymentStore(platform.db)
        self._runtime_provider = runtime_provider
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="vma-deploy")
        self._lock = threading.RLock()
        self._runners: dict[str, TerraformRunner] = {}
        self._cancelled: set[str] = set()
        interrupted = self.store.fail_interrupted(_now())
        if interrupted:
            logger.warning("deploy: marked {} interrupted deployment(s) as failed", interrupted)

    # ── runtime binding ───────────────────────────────────────────────────────

    def bind_runtime(self, runtime: "MigrationRuntime") -> None:
        self.platform.extras[RUNTIME_EXTRA] = runtime

    @property
    def runtime(self) -> "MigrationRuntime":
        runtime = self.platform.extras.get(RUNTIME_EXTRA)
        if runtime is None and self._runtime_provider is not None:
            runtime = self._runtime_provider()
        if runtime is None:
            raise Unavailable("deployments: no run runtime is bound to the platform")
        return runtime

    # ── queries ───────────────────────────────────────────────────────────────

    def list(self, run_id: str) -> list[dict[str, Any]]:
        self._run_record(run_id)
        return [item.to_dict() for item in self.store.list(run_id)]

    def get(self, run_id: str, deployment_id: str) -> dict[str, Any]:
        return self._deployment(run_id, deployment_id).to_dict()

    def has_active(self, run_id: str) -> bool:
        return self.store.active_for(run_id) is not None

    def log(self, run_id: str, deployment_id: str, since: int = 0) -> dict[str, Any]:
        deployment = self._deployment(run_id, deployment_id)
        path = Path(deployment.log_path)
        lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
        start = max(0, int(since))
        return {"lines": lines[start:], "next": max(start, len(lines)), "done": deployment.status in TERMINAL_STATUSES}

    def plan_json(self, run_id: str, deployment_id: str) -> dict[str, Any]:
        deployment = self._deployment(run_id, deployment_id)
        path = Path(deployment.log_path).parent / "plan.json"
        if deployment.action != "plan" or not path.is_file():
            raise NotFound(f"deployment {deployment_id} has no plan output")
        return json.loads(path.read_text(encoding="utf-8"))

    def variables(self, run_id: str) -> list[dict[str, Any]]:
        paths = self._paths(self._run_record(run_id))
        return tfvars.merged_view(self._variable_specs(paths), tfvars.read_tfvars(paths.tfvars))

    def set_variables(self, run_id: str, values: dict[str, Any], actor: Any = "system", context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if not isinstance(values, dict):
            raise Invalid("values must be an object of variable name to value")
        paths = self._paths(self._run_record(run_id))
        specs = self._variable_specs(paths)
        merged = tfvars.merge_values(specs, tfvars.read_tfvars(paths.tfvars), values)
        tfvars.write_tfvars(paths.tfvars, merged)
        self._audit("variables.updated", actor, run_id, context, keys=sorted(values))
        return tfvars.merged_view(specs, merged)

    def state_summary(self, run_id: str) -> dict[str, Any]:
        paths = self._paths(self._run_record(run_id))
        remote = self._deploy_config().get("remote_state")
        if isinstance(remote, dict) and remote.get("enabled"):
            return {"exists": False, "remote": True, "backend": str(remote.get("type") or "")}
        if not paths.state_file.is_file():
            return {"exists": False, "remote": False}
        try:
            data = json.loads(paths.state_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise Invalid(f"state file is not valid JSON: {exc}") from exc
        return {
            "exists": True,
            "remote": False,
            "path": str(paths.state_file),
            "serial": data.get("serial"),
            "terraform_version": data.get("terraform_version"),
            "lineage": data.get("lineage"),
            "resources": _state_resources(data),
        }

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def create(
        self,
        run_id: str,
        *,
        action: str,
        connection_id: str | None = None,
        plan_id: str | None = None,
        confirmation: str | None = None,
        actor: Any = "system",
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        record = self._run_record(run_id)
        subject, _kind = _actor_fields(actor)
        paths = self._paths(record)
        config = self._deploy_config()
        binary = str(config.get("terraform_bin") or "terraform")
        if shutil.which(binary) is None and not Path(binary).is_file():
            raise Unavailable(f"terraform binary not found: {binary} (deploy.terraform_bin)")
        plan_record: Deployment | None = None
        try:
            if action not in ACTIONS:
                raise Invalid(f"action must be one of {', '.join(ACTIONS)}")
            if record.status != "succeeded":
                raise Invalid(f"run {run_id} is {record.status}; only a succeeded run can be deployed")
            if not any(paths.root_module.glob("*.tf")):
                raise Invalid(f"run {run_id} has no Terraform root module under artifacts/")
            if action == "apply":
                if not config.get("allow_apply", True):
                    raise Forbidden("terraform apply is disabled (deploy.allow_apply)")
                plan_record = self._require_plan(run_id, plan_id, paths)
                self._require_confirmation(run_id, confirmation)
            elif action == "destroy":
                if not config.get("allow_destroy", True):
                    raise Forbidden("terraform destroy is disabled (deploy.allow_destroy)")
                self._require_confirmation(run_id, confirmation)
            connection = self._resolve_connection(connection_id, record.cloud)
        except PlatformError as exc:
            self._audit("deployment.denied", actor, run_id, context, outcome="denied", action=action, reason=str(exc), plan_id=plan_id)
            raise

        with self._lock:
            active = self.store.active_for(run_id)
            if active is not None:
                raise Conflict(f"run {run_id} already has an active deployment ({active.id}, {active.status})")
            deployment_id = new_deployment_id()
            deployment = Deployment(
                id=deployment_id, run_id=run_id, action=action, status="queued",
                connection_id=connection.id, connection_name=connection.name, provider=connection.provider or record.cloud,
                requested_by=subject, approved_by=subject if action in ("apply", "destroy") else None,
                plan_id=plan_record.id if plan_record else None, created_at=_now(), started_at=None, finished_at=None,
                exit_code=None, summary=None, error=None,
                log_path=str(paths.deployment_dir(deployment_id) / "terraform.log"), artifacts_hash=None,
            )
            self.store.insert(deployment)
            write_mirror(paths.deployment_dir(deployment_id) / "deployment.json", deployment)
        self._audit(
            "deployment.requested", actor, run_id, context,
            deployment_id=deployment_id, action=action, connection=connection.id, plan_id=deployment.plan_id,
        )
        self._executor.submit(self._execute, deployment, paths, connection, plan_record, binary, config, actor, context)
        return deployment.to_dict()

    def cancel(self, run_id: str, deployment_id: str, actor: Any = "system", context: dict[str, Any] | None = None) -> dict[str, Any]:
        deployment = self._deployment(run_id, deployment_id)
        if deployment.status not in ACTIVE_STATUSES:
            raise Conflict(f"deployment {deployment_id} is {deployment.status}; only queued or running deployments can be cancelled")
        with self._lock:
            # Atomic with the queued -> running transition in _execute (same lock): either the
            # runner is registered and gets a signal, or the row is still queued and we close it here.
            self._cancelled.add(deployment_id)
            runner = self._runners.get(deployment_id)
            current = self.store.get(deployment_id)
            if runner is None and current is not None and current.status == "queued":
                self._finish(current, self._paths_for(current), status="cancelled", error="cancelled before start", exit_code=None)
        if runner is not None:
            runner.cancel()
        self._audit("deployment.cancelled", actor, run_id, context, deployment_id=deployment_id, action=deployment.action)
        deadline = time.monotonic() + CANCEL_WAIT_SECONDS
        while time.monotonic() < deadline:
            current = self.store.get(deployment_id)
            if current is None or current.status in TERMINAL_STATUSES:
                break
            time.sleep(0.05)
        return self.get(run_id, deployment_id)

    # ── execution (worker thread) ─────────────────────────────────────────────

    def _execute(
        self,
        deployment: Deployment,
        paths: RunPaths,
        connection: ConnectionContext,
        plan_record: Deployment | None,
        binary: str,
        config: dict[str, Any],
        actor: Any,
        context: dict[str, Any] | None,
    ) -> None:
        deployment_dir = paths.deployment_dir(deployment.id)
        env = build_environment(
            data_dir=paths.data_dir,
            connection_env=connection.env,
            plugin_cache_dir=self._plugin_cache_dir(),
            strip_cloud_variables=connection.id is not None,
        )
        secrets = [*(connection.secret_values or []), *secret_env_values(connection.env or {})]
        mask = make_masker(secrets)
        log = LogWriter(deployment_dir / "terraform.log", mask)
        timeout = float(config.get("timeout_minutes") or 60) * 60
        runner = TerraformRunner(binary, paths.workspace, env, log, deadline=time.monotonic() + timeout)
        with self._lock:
            current = self.store.get(deployment.id)
            if current is not None and current.status != "queued":
                return  # closed by cancel() before we started
            if deployment.id in self._cancelled:
                self._finish(deployment, paths, status="cancelled", error="cancelled before start", exit_code=None)
                return
            deployment.status = "running"
            deployment.started_at = _now()
            self.store.update(deployment.id, status="running", started_at=deployment.started_at)
            write_mirror(deployment_dir / "deployment.json", deployment)
            self._runners[deployment.id] = runner
        try:
            log.write(f"## deployment {deployment.id}: terraform {deployment.action} for run {deployment.run_id}"
                      + (f" with connection {connection.name or connection.id}" if connection.id else " with the process environment"))
            deployment.artifacts_hash = compute_artifacts_hash(paths.root_module)
            self._prepare_workspace(paths, config, log)
            status, exit_code, summary, error = self._run_action(deployment, paths, runner, plan_record, log, secrets)
        except Exception as exc:  # noqa: BLE001 - every failure must land in the record
            logger.exception("deploy: deployment {} failed", deployment.id)
            status, exit_code, summary, error = "failed", None, None, mask(f"{exc.__class__.__name__}: {exc}")
            log.write(f"## error: {error}")
        finally:
            with self._lock:
                self._runners.pop(deployment.id, None)
        if runner.cancelled or deployment.id in self._cancelled:
            status, error = "cancelled", error or "cancelled by operator"
        # Audit first, then flip the status: a client that observes the final status must also
        # find the audit entry (the HTTP tests and any evidence export rely on that ordering).
        counts = {key: (summary or {}).get(key, 0) for key in ("add", "change", "destroy", "replace")}
        self._audit(
            "deployment.finished", actor, deployment.run_id, context,
            outcome="success" if status == "succeeded" else status,
            deployment_id=deployment.id, action=deployment.action, status=status, exit_code=exit_code, **counts,
        )
        self._finish(deployment, paths, status=status, error=error, exit_code=exit_code, summary=summary)

    def _run_action(
        self, deployment: Deployment, paths: RunPaths, runner: TerraformRunner, plan_record: Deployment | None, log: LogWriter, secrets: list[str]
    ) -> tuple[str, int | None, dict[str, Any] | None, str | None]:
        deployment_dir = paths.deployment_dir(deployment.id)
        init = runner.run("init", "-reconfigure", "-no-color", "-input=false")
        self._persist_lock_file(paths)
        if not init.ok:
            return _failure(init)

        if deployment.action == "plan":
            plan = runner.run("plan", "-detailed-exitcode", "-no-color", "-input=false", "-out=tfplan")
            if plan.timed_out or plan.cancelled or plan.returncode not in (0, 2):  # 0 no changes, 2 changes, 1 error
                return _failure(plan)
            plan_file = paths.workspace / "tfplan"
            if plan_file.is_file():
                shutil.copy2(plan_file, deployment_dir / "tfplan")
            show = runner.run("show", "-json", "tfplan", capture=True)
            if not show.ok:
                return _failure(show)
            summary = self._write_plan_json(show.captured, deployment_dir, paths, log, secrets)
            if plan.returncode == 0:
                log.write("## no changes: the infrastructure matches the configuration")
            return "succeeded", plan.returncode, summary, None

        if deployment.action == "apply":
            assert plan_record is not None
            source = paths.deployment_dir(plan_record.id) / "tfplan"
            if not source.is_file():
                raise Invalid(f"plan {plan_record.id} has no saved plan file; run plan again")
            shutil.copy2(source, paths.workspace / "tfplan")
            apply = runner.run("apply", "-no-color", "-input=false", "tfplan")
            if not apply.ok:
                return _failure(apply)
            resources = (plan_record.summary or {}).get("resources") if plan_record.summary else None
            return "succeeded", apply.returncode, summarize_output(_log_lines(log), resources), None

        destroy = runner.run("destroy", "-auto-approve", "-no-color", "-input=false")
        if not destroy.ok:
            return _failure(destroy)
        return "succeeded", destroy.returncode, summarize_output(_log_lines(log)), None

    def _prepare_workspace(self, paths: RunPaths, config: dict[str, Any], log: LogWriter) -> None:
        """Fresh copy of the root module so artifacts are never mutated; state and plugins live outside."""
        if paths.workspace.exists():
            shutil.rmtree(paths.workspace)
        shutil.copytree(paths.root_module, paths.workspace)
        paths.state_file.parent.mkdir(parents=True, exist_ok=True)
        paths.data_dir.mkdir(parents=True, exist_ok=True)
        for stray in (".terraform", "terraform.tfstate", "terraform.tfstate.backup"):
            target = paths.workspace / stray
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
        try:
            override = render_backend_override(config.get("remote_state"), LOCAL_STATE_RELATIVE, run_id=paths.run_id)
        except ValueError as exc:
            raise Invalid(str(exc)) from exc
        (paths.workspace / "backend_override.tf").write_text(override, encoding="utf-8")
        if paths.tfvars.is_file():
            shutil.copy2(paths.tfvars, paths.workspace / "terraform.tfvars.json")
        if paths.lock_file.is_file():
            shutil.copy2(paths.lock_file, paths.workspace / ".terraform.lock.hcl")
        remote = config.get("remote_state") if isinstance(config.get("remote_state"), dict) else {}
        backend = "remote" if remote.get("enabled") else "local"
        log.write(f"## workspace prepared from {paths.root_module.name} ({backend} state, tfvars {'present' if paths.tfvars.is_file() else 'absent'})")

    def _persist_lock_file(self, paths: RunPaths) -> None:
        lock = paths.workspace / ".terraform.lock.hcl"
        if lock.is_file():
            shutil.copy2(lock, paths.lock_file)

    def _write_plan_json(self, text: str, deployment_dir: Path, paths: RunPaths, log: LogWriter, secrets: list[str]) -> dict[str, Any]:
        try:
            plan = json.loads(text)
        except json.JSONDecodeError as exc:
            raise Invalid(f"terraform show -json produced invalid JSON: {exc}") from exc
        sensitive = {spec["name"] for spec in self._variable_specs(paths, strict=False) if spec.get("sensitive")}
        plan = redact_plan(plan if isinstance(plan, dict) else {}, sensitive)
        # Only literal secret values are masked here: the key/value regex would corrupt JSON.
        rendered = mask_values(json.dumps(plan, indent=1, ensure_ascii=True), secrets)
        (deployment_dir / "plan.json").write_text(rendered, encoding="utf-8")
        summary = summarize_plan(plan)
        log.write(f"## plan summary: {summary['add']} to add, {summary['change']} to change, {summary['destroy']} to destroy, {summary['replace']} to replace")
        return summary

    def _finish(
        self, deployment: Deployment, paths: RunPaths, *, status: str, error: str | None, exit_code: int | None,
        summary: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            deployment.status = status
            deployment.finished_at = _now()
            deployment.exit_code = exit_code
            deployment.summary = summary
            deployment.error = error
            self.store.update(
                deployment.id, status=status, finished_at=deployment.finished_at, exit_code=exit_code,
                summary=summary, error=error, artifacts_hash=deployment.artifacts_hash,
            )
            write_mirror(paths.deployment_dir(deployment.id) / "deployment.json", deployment)
            self._cancelled.discard(deployment.id)
        logger.info("deploy: deployment {} ({}) for run {} {}", deployment.id, deployment.action, deployment.run_id, status)

    # ── gates and helpers ─────────────────────────────────────────────────────

    def _require_plan(self, run_id: str, plan_id: str | None, paths: RunPaths) -> Deployment:
        if not plan_id:
            raise Invalid("apply requires plan_id (a succeeded plan of this run)")
        plan = self.store.get(plan_id)
        if plan is None or plan.run_id != run_id or plan.action != "plan":
            raise Invalid(f"plan {plan_id} is not a plan of run {run_id}")
        if plan.status != "succeeded":
            raise Invalid(f"plan {plan_id} is {plan.status}; only a succeeded plan can be applied")
        if plan.exit_code == 0:
            raise Invalid(f"plan {plan_id} found no changes; nothing to apply")
        if plan.artifacts_hash and plan.artifacts_hash != compute_artifacts_hash(paths.root_module):
            raise Invalid(f"the generated Terraform changed since plan {plan_id}; run plan again")
        return plan

    @staticmethod
    def _require_confirmation(run_id: str, confirmation: str | None) -> None:
        if (confirmation or "").strip() != run_id:
            raise Forbidden("confirmation must equal the run id")

    def _resolve_connection(self, connection_id: str | None, cloud: str) -> ConnectionContext:
        connections = self.platform.connections
        if connections is None:
            if connection_id:
                raise Invalid("cloud connections are not available on this platform; omit connection_id")
            return ConnectionContext()
        if not connection_id:
            raise Invalid("connection_id is required")
        record = connections.get(connection_id)  # NotFound propagates
        provider = _field(record, "provider")
        if provider and str(provider).lower() != cloud.lower():
            raise Invalid(f"connection {connection_id} is for {provider}, the run targets {cloud}")
        env = connections.terraform_env(connection_id)  # Invalid propagates (missing secret, expired SSO, ...)
        secrets_fn = getattr(connections, "secret_values", None)
        secret_values = [str(value) for value in (secrets_fn(connection_id) if callable(secrets_fn) else []) if value]
        return ConnectionContext(
            id=connection_id, name=_field(record, "name"), provider=str(provider) if provider else None,
            env={str(key): str(value) for key, value in dict(env or {}).items()}, secret_values=secret_values,
        )

    def _deploy_config(self) -> dict[str, Any]:
        config = self.platform.effective_config()
        deploy = config.get("deploy") if isinstance(config.get("deploy"), dict) else {}
        return dict(deploy)

    def _plugin_cache_dir(self) -> str | None:
        config = self.platform.effective_config()
        validation = config.get("validation") if isinstance(config.get("validation"), dict) else {}
        value = validation.get("terraform_plugin_cache_dir")
        return str(value) if value else None

    def _run_record(self, run_id: str) -> "RunRecord":
        return self.runtime.get_run(run_id)  # RunError (404) propagates

    def _paths(self, record: "RunRecord") -> RunPaths:
        run_dir = self.runtime.store.run_dir(record.run_id)  # record.run_dir may be a container path
        return RunPaths(
            run_id=record.run_id, cloud=record.cloud, run_dir=run_dir,
            root_module=run_dir / "artifacts" / f"{record.cloud}-migration", deploy_dir=run_dir / "deploy",
        )

    def _paths_for(self, deployment: Deployment) -> RunPaths:
        return self._paths(self._run_record(deployment.run_id))

    def _deployment(self, run_id: str, deployment_id: str) -> Deployment:
        self._run_record(run_id)
        deployment = self.store.get(deployment_id)
        if deployment is None or deployment.run_id != run_id:
            raise NotFound(f"unknown deployment {deployment_id} for run {run_id}")
        return deployment

    def _variable_specs(self, paths: RunPaths, strict: bool = True) -> list[dict[str, Any]]:
        path = paths.root_module / "variables.tf"
        if not path.is_file():
            return []
        try:
            return tfvars.parse_variables_tf(path.read_text(encoding="utf-8"))
        except Invalid:
            if strict:
                raise
            return []

    def _audit(self, event: str, actor: Any, run_id: str, context: dict[str, Any] | None, outcome: str = "success", **details: Any) -> None:
        subject, kind = _actor_fields(actor)
        ctx = context or {}
        try:
            self.platform.audit.record(
                event, actor=subject, actor_kind=kind, target_type="run", target_id=run_id, outcome=outcome,
                details={key: value for key, value in details.items() if value is not None},
                ip=ctx.get("ip"), user_agent=ctx.get("user_agent"),
            )
        except Exception as exc:  # noqa: BLE001 - auditing must never break a deployment thread
            logger.error("deploy: audit record {} failed: {}", event, exc)


# ── module helpers ───────────────────────────────────────────────────────────


def _failure(result: Any) -> tuple[str, int | None, None, str]:
    status = "failed"
    return status, (None if result.returncode < 0 else result.returncode), None, result.error_summary()


def _log_lines(log: LogWriter) -> list[str]:
    return log.path.read_text(encoding="utf-8").splitlines() if log.path.is_file() else []


def _state_resources(state: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for resource in state.get("resources") or []:
        if not isinstance(resource, dict):
            continue
        prefix = f"{resource['module']}." if resource.get("module") else ""
        prefix += "data." if resource.get("mode") == "data" else ""
        base = f"{prefix}{resource.get('type')}.{resource.get('name')}"
        instances = resource.get("instances") if isinstance(resource.get("instances"), list) else []
        if not instances:
            items.append({"address": base, "type": resource.get("type")})
            continue
        for instance in instances:
            key = instance.get("index_key") if isinstance(instance, dict) else None
            suffix = "" if key is None else (f"[{json.dumps(key)}]" if isinstance(key, str) else f"[{key}]")
            items.append({"address": base + suffix, "type": resource.get("type")})
    return items


def _actor_fields(actor: Any) -> tuple[str, str]:
    subject = getattr(actor, "subject", None)
    if subject:
        return str(subject), str(getattr(actor, "kind", None) or "user")
    text = str(actor or "system")
    return text, "system" if text == "system" else "user"


def _field(record: Any, name: str) -> Any:
    if isinstance(record, dict):
        return record.get(name)
    return getattr(record, name, None)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


__all__ = ["ConnectionContext", "DeployService", "RunPaths"]
