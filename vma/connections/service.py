"""ConnectionService: catalog, CRUD, verification, Terraform credential resolution, device flows.

Secrets enter through `create`/`update` and the device flows, are encrypted with the
platform SecretBox before they reach SQLite, and leave only through `terraform_env` and
`secret_values` (callers that run Terraform and mask its logs). Every mutation and every
verification is recorded in the audit log without secret values.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger

from vma.errors import Conflict, Invalid, NotFound, Unavailable
from vma.secrets import SecretsUnavailable

from . import aws, azure, gcp, openstack
from .models import (
    CATALOG,
    Connection,
    MethodSpec,
    VerifyResult,
    catalog_dict,
    method_spec,
    safe_error,
    validate_against_catalog,
)
from .store import ConnectionStore, DeviceFlow, utcnow

PROVIDER_MODULES: dict[str, Any] = {"aws": aws, "azure": azure, "gcp": gcp, "openstack": openstack}
CREDENTIAL_REFRESH_MARGIN = timedelta(minutes=5)
MAX_NAME_LENGTH = 80
ROTATION_MESSAGE = "generate one with `vma secrets generate-key`"


class ConnectionService:
    def __init__(self, platform: Any) -> None:
        self.platform = platform
        self.store = ConnectionStore(platform.db)
        # connection id -> (updated_at it was resolved for, expiry, env) for temporary credentials
        self._resolved: dict[str, tuple[str, datetime, dict[str, str]]] = {}
        self._lock = threading.Lock()

    # ── catalog and reads ─────────────────────────────────────────────────

    def catalog(self) -> dict[str, Any]:
        return catalog_dict()

    def list(self) -> list[Connection]:
        return self.store.list()

    def get(self, connection_id: str) -> Connection:
        return self.store.get(connection_id)

    def to_public(self, connection: Connection) -> dict[str, Any]:
        provider = CATALOG.get(connection.provider)
        spec = provider.method(connection.auth_method) if provider else None
        return {
            "id": connection.id, "name": connection.name, "provider": connection.provider, "auth_method": connection.auth_method,
            "provider_label": provider.label if provider else connection.provider, "method_label": spec.label if spec else connection.auth_method,
            "config": dict(connection.config), "status": connection.status, "last_checked_at": connection.last_checked_at,
            "last_check": dict(connection.last_check) if connection.last_check else None,
            "created_by": connection.created_by, "created_at": connection.created_at, "updated_at": connection.updated_at,
            "has_secret": connection.has_secret, "secret_fields": sorted(connection.secret_keys),
            "terraform_ready": bool(spec.terraform_ready) if spec else False, "device_flow": bool(spec.device_flow) if spec else False,
        }

    # ── mutations ─────────────────────────────────────────────────────────

    def create(
        self, *, name: str, provider: str, auth_method: str, config: dict[str, Any] | None, secret: dict[str, Any] | None,
        actor: str, actor_kind: str = "user", audit_context: dict[str, str | None] | None = None,
    ) -> Connection:
        spec = self._spec(provider, auth_method)
        clean_name = self._clean_name(name)
        clean_config, clean_secret = self._validate(spec, config, secret, caller_supplied_secret=secret)
        if self.store.find_by_name(clean_name) is not None:
            raise Conflict(f"a connection named {clean_name!r} already exists")
        now = utcnow()
        connection = Connection(
            id=uuid.uuid4().hex, name=clean_name, provider=provider, auth_method=auth_method, config=clean_config,
            secret_token=self._encrypt(clean_secret), secret_keys=sorted(clean_secret), status="unverified",
            last_checked_at=None, last_check=None, created_by=actor, created_at=now, updated_at=now,
        )
        self.store.insert(connection)
        self._audit("connection.created", connection, actor, actor_kind, audit_context, provider=provider, auth_method=auth_method, secret_fields=sorted(clean_secret))
        logger.info("connection {} created ({} / {}) by {}", connection.id, provider, auth_method, actor)
        return connection

    def update(
        self, connection_id: str, *, name: str | None = None, config: dict[str, Any] | None = None, secret: dict[str, Any] | None = None,
        actor: str, actor_kind: str = "user", audit_context: dict[str, str | None] | None = None,
    ) -> Connection:
        connection = self.get(connection_id)
        spec = self._spec(connection.provider, connection.auth_method)
        changed: list[str] = []
        if name is not None:
            clean_name = self._clean_name(name)
            if clean_name.lower() != connection.name.lower():
                existing = self.store.find_by_name(clean_name)
                if existing is not None and existing.id != connection.id:
                    raise Conflict(f"a connection named {clean_name!r} already exists")
            if clean_name != connection.name:
                changed.append("name")
            connection.name = clean_name
        credentials_changed = config is not None or secret is not None
        if credentials_changed:
            if config is not None and not isinstance(config, dict):
                raise Invalid("config must be an object")
            if secret is not None and not isinstance(secret, dict):
                raise Invalid("secret must be an object")
            merged_config = _merge(connection.config, config or {})
            merged_secret = _merge(self._decrypt(connection), secret or {})  # Unavailable if the key cannot decrypt it
            clean_config, clean_secret = self._validate(spec, merged_config, merged_secret, caller_supplied_secret=secret)
            if clean_config != connection.config:
                changed.append("config")
            connection.config = clean_config
            if secret is not None:
                connection.secret_token = self._encrypt(clean_secret)
                connection.secret_keys = sorted(clean_secret)
                changed.append("secret")
            elif clean_secret and sorted(clean_secret) != sorted(connection.secret_keys):
                connection.secret_keys = sorted(clean_secret)
            connection.status = "unverified"
        connection.updated_at = utcnow()
        self.store.update(connection)
        self._invalidate(connection.id)
        self._audit("connection.updated", connection, actor, actor_kind, audit_context, fields=changed)
        return connection

    def delete(self, connection_id: str, actor: str, actor_kind: str = "user", audit_context: dict[str, str | None] | None = None) -> None:
        connection = self.get(connection_id)
        self.store.delete(connection.id)
        self._invalidate(connection.id)
        self._audit("connection.deleted", connection, actor, actor_kind, audit_context)
        logger.info("connection {} deleted by {}", connection.id, actor)

    # ── verification and credential resolution ────────────────────────────

    def test(
        self, connection_id: str, actor: str | None = None, actor_kind: str = "user", audit_context: dict[str, str | None] | None = None,
    ) -> dict[str, Any]:
        connection = self.get(connection_id)
        checked_at = utcnow()
        known_secrets: list[str] = []
        try:
            secret = self._decrypt(connection)
            known_secrets = _string_values(secret)
            result = self._module(connection).verify(connection.auth_method, connection.config, secret, connection_id=connection.id)
        except Unavailable as exc:
            result = VerifyResult(False, {}, str(exc))
        except Exception as exc:  # noqa: BLE001 - any failure is reported as a failed check
            result = VerifyResult(False, {}, safe_error(exc, known_secrets))
        status = "ok" if result.ok else "failed"
        last_check = {"identity": dict(result.identity), "message": result.message}
        self.store.set_check(connection.id, status, checked_at, last_check)
        self._audit(
            "connection.tested", connection, actor or "system", actor_kind if actor else "system", audit_context,
            outcome="success" if result.ok else "failure", status=status, message=result.message,
        )
        logger.info("connection {} test: {} ({})", connection.id, status, result.message)
        return {"ok": result.ok, "identity": dict(result.identity), "message": result.message, "checked_at": checked_at}

    def terraform_env(self, connection_id: str) -> dict[str, str]:
        connection = self.get(connection_id)
        cached = self._cached_env(connection)
        if cached is not None:
            return dict(cached)
        secret = self._decrypt(connection)
        try:
            resolved = self._module(connection).terraform_env(connection.auth_method, connection.config, secret, connection_id=connection.id)
        except ValueError as exc:
            raise Invalid(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - resolution failures become a safe Unavailable
            raise Unavailable(f"could not resolve credentials for connection {connection.name!r}: {safe_error(exc, _string_values(secret))}") from exc
        if resolved.expires_at:
            self._remember(connection, resolved.env, resolved.expires_at)
        return dict(resolved.env)

    def secret_values(self, connection_id: str) -> list[str]:
        connection = self.get(connection_id)
        values: set[str] = set()
        try:
            values.update(_string_values(self._decrypt(connection)))
        except Unavailable:
            pass
        module = self._module(connection)
        if connection.provider == "openstack" and connection.auth_method == "clouds_yaml":
            values.update(openstack.clouds_yaml_secret_values(connection.config))
        env: dict[str, str] = {}
        try:
            env = self.terraform_env(connection.id)
        except (Invalid, Unavailable):
            pass
        for key in getattr(module, "SECRET_ENV_KEYS", ()):
            if env.get(key):
                values.add(env[key])
        return sorted((value for value in values if value), key=len, reverse=True)

    # ── device flows ──────────────────────────────────────────────────────

    def device_start(
        self, connection_id: str, actor: str | None = None, actor_kind: str = "user", audit_context: dict[str, str | None] | None = None,
    ) -> dict[str, Any]:
        connection = self.get(connection_id)
        spec = self._spec(connection.provider, connection.auth_method)
        if not spec.device_flow:
            raise Invalid(f"{connection.provider}/{connection.auth_method} does not use a device flow")
        flow_id = uuid.uuid4().hex
        flow_token: str | None = None
        try:
            if connection.provider == "aws":
                self._require_secrets()
                public, flow_secret, expires_at = aws.device_start(connection.config)
                flow_token = self.platform.secrets.encrypt_json(flow_secret)
            else:
                public, expires_at = azure.device_start(connection.config, connection_id=connection.id, flow_id=flow_id)
        except Unavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            raise Unavailable(f"could not start the device sign-in: {safe_error(exc)}") from exc
        flow = DeviceFlow(flow_id, connection.id, connection.provider, utcnow(), expires_at, "pending", public, flow_token)
        self.store.insert_flow(flow)
        self._audit("connection.device_started", connection, actor or "system", actor_kind if actor else "system", audit_context, flow_id=flow_id)
        return {"flow_id": flow_id, **public}

    def device_poll(
        self, connection_id: str, flow_id: str, actor: str | None = None, actor_kind: str = "user", audit_context: dict[str, str | None] | None = None,
    ) -> dict[str, Any]:
        connection = self.get(connection_id)
        flow = self.store.get_flow(flow_id)
        if flow.connection_id != connection.id:
            raise NotFound(f"unknown device flow {flow_id}")
        if flow.status != "pending":
            return {"status": flow.status, "message": str(flow.payload.get("message") or flow.status)}
        if flow.expired:
            self._finish_flow(flow, "expired", "the device code expired; start again")
            return {"status": "expired", "message": "the device code expired; start again"}
        try:
            if connection.provider == "aws":
                flow_secret = self.platform.secrets.decrypt_json(flow.secret_token or "")
                result = aws.device_poll(connection.config, flow_secret)
            else:
                result = azure.device_poll(connection_id=connection.id, flow_id=flow_id)
        except SecretsUnavailable as exc:
            result = {"status": "error", "message": str(exc)}
        except Exception as exc:  # noqa: BLE001
            result = {"status": "error", "message": safe_error(exc)}
        status = str(result.get("status") or "error")
        message = str(result.get("message") or "")
        if status == "pending":
            return {"status": "pending", "message": message}
        if status != "complete":
            self._finish_flow(flow, status, message)
            self._audit("connection.device_completed", connection, actor or "system", actor_kind if actor else "system", audit_context, outcome="failure", flow_id=flow_id, status=status, message=message)
            return {"status": status, "message": message}
        if result.get("secret"):
            merged = {**self._decrypt_or_empty(connection), **result["secret"]}
            self.store.set_secret(connection.id, self._encrypt(merged), sorted(merged))
        self._invalidate(connection.id, forget_device_session=False)
        self._finish_flow(flow, "complete", "signed in")
        check = self.test(connection.id, actor=actor, actor_kind=actor_kind, audit_context=audit_context)
        outcome = "success" if check["ok"] else "failure"
        self._audit("connection.device_completed", connection, actor or "system", actor_kind if actor else "system", audit_context, outcome=outcome, flow_id=flow_id, status="complete", verified=check["ok"])
        if not check["ok"]:
            self.store.set_flow_status(flow_id, "error", {**flow.payload, "message": check["message"]})
            return {"status": "error", "message": f"signed in, but verification failed: {check['message']}"}
        return {"status": "complete", "message": check["message"] or "signed in"}

    # ── key rotation ──────────────────────────────────────────────────────

    def rotate_secrets(self) -> int:
        self._require_secrets()
        count = 0
        for table, row_id, token in self.store.encrypted_tokens():
            self.store.replace_token(table, row_id, self.platform.secrets.rotate(token))
            count += 1
        with self._lock:
            self._resolved.clear()
        self.platform.audit.record("connection.secrets_rotated", target_type="connection", details={"rotated": count})
        logger.info("connections: re-encrypted {} secret token(s)", count)
        return count

    # ── helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _spec(provider: str, auth_method: str) -> MethodSpec:
        try:
            return method_spec(str(provider), str(auth_method))
        except ValueError as exc:
            raise Invalid(str(exc)) from exc

    @staticmethod
    def _module(connection: Connection) -> Any:
        module = PROVIDER_MODULES.get(connection.provider)
        if module is None:
            raise Invalid(f"unknown provider {connection.provider!r}")
        return module

    @staticmethod
    def _clean_name(name: Any) -> str:
        value = str(name or "").strip()
        if not value or len(value) > MAX_NAME_LENGTH:
            raise Invalid(f"name must be between 1 and {MAX_NAME_LENGTH} characters")
        return value

    def _validate(
        self, spec: MethodSpec, config: dict[str, Any] | None, secret: dict[str, Any] | None, *, caller_supplied_secret: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if config is not None and not isinstance(config, dict):
            raise Invalid("config must be an object")
        if secret is not None and not isinstance(secret, dict):
            raise Invalid("secret must be an object")
        if caller_supplied_secret:
            internal = [key for key in caller_supplied_secret if key in spec.internal_secret_keys]
            if internal:
                raise Invalid(f"secret field(s) {', '.join(internal)} are managed by the device-code flow and cannot be set directly")
        try:
            clean_config, clean_secret = validate_against_catalog(spec, config or {}, secret or {})
        except ValueError as exc:
            raise Invalid(str(exc)) from exc
        if clean_secret and not self.platform.secrets.available:
            self._require_secrets()
        return clean_config, clean_secret

    def _require_secrets(self) -> None:
        if not self.platform.secrets.available:
            raise Unavailable(f"cannot store credentials: set {self.platform.secrets.env_var} ({ROTATION_MESSAGE}) and restart the service")

    def _encrypt(self, secret: dict[str, Any]) -> str | None:
        if not secret:
            return None
        self._require_secrets()
        return self.platform.secrets.encrypt_json(secret)

    def _decrypt(self, connection: Connection) -> dict[str, Any]:
        if not connection.secret_token:
            return {}
        try:
            data = self.platform.secrets.decrypt_json(connection.secret_token)
        except SecretsUnavailable as exc:
            raise Unavailable(f"connection {connection.name!r}: {exc}") from exc
        return dict(data) if isinstance(data, dict) else {}

    def _decrypt_or_empty(self, connection: Connection) -> dict[str, Any]:
        try:
            return self._decrypt(connection)
        except Unavailable:
            return {}

    def _audit(
        self, action: str, connection: Connection, actor: str, actor_kind: str, context: dict[str, str | None] | None, *, outcome: str = "success", **details: Any,
    ) -> None:
        payload = {"name": connection.name, "provider": connection.provider, "auth_method": connection.auth_method, **details}
        self.platform.audit.record(
            action, actor=actor or "system", actor_kind=actor_kind or "system", target_type="connection", target_id=connection.id,
            outcome=outcome, details=payload, ip=(context or {}).get("ip"), user_agent=(context or {}).get("user_agent"),
        )

    def _invalidate(self, connection_id: str, *, forget_device_session: bool = True) -> None:
        """Drop cached temporary credentials (and, after an update or delete, the device sign-in)."""
        with self._lock:
            self._resolved.pop(connection_id, None)
        if forget_device_session:
            azure.forget_device_session(connection_id)

    def _remember(self, connection: Connection, env: dict[str, str], expires_at: str) -> None:
        try:
            expiry = datetime.fromisoformat(expires_at)
        except ValueError:
            return
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        with self._lock:
            self._resolved[connection.id] = (connection.updated_at, expiry, dict(env))

    def _cached_env(self, connection: Connection) -> dict[str, str] | None:
        with self._lock:
            entry = self._resolved.get(connection.id)
            if entry is None:
                return None
            updated_at, expiry, env = entry
            if updated_at != connection.updated_at or expiry - CREDENTIAL_REFRESH_MARGIN <= datetime.now(timezone.utc):
                self._resolved.pop(connection.id, None)
                return None
            return env

    def _finish_flow(self, flow: DeviceFlow, status: str, message: str) -> None:
        self.store.set_flow_status(flow.flow_id, status, {**flow.payload, "message": message}, clear_secret=True)


def _merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Apply a partial update: None removes a key, anything else replaces it."""
    merged = dict(base)
    for key, value in patch.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


def _string_values(data: dict[str, Any]) -> list[str]:
    return [str(value) for value in data.values() if isinstance(value, str) and value]
