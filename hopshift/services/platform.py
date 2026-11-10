"""The Platform container wires the services the API and CLI use.

Optional services (security, connections, deployments) attach themselves when their package
is importable, through `build_<service>(platform)` factories, so each workstream can land
independently.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

from hopshift.services.audit import AuditLog
from hopshift.services.db import Database
from hopshift.services.secrets import DEFAULT_KEY_ENV, SecretBox
from hopshift.services.settings import SettingsStore

OPTIONAL_SERVICES: tuple[tuple[str, str, str], ...] = (
    ("auth", "hopshift.services.security", "build_auth_service"),
    ("connections", "hopshift.services.connections", "build_connection_service"),
    ("deployments", "hopshift.services.deploy", "build_deploy_service"),
)


@dataclass
class Platform:
    config: dict[str, Any]
    db: Database
    secrets: SecretBox
    audit: AuditLog
    settings: SettingsStore
    auth: Any | None = None
    connections: Any | None = None
    deployments: Any | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_config(cls, config: dict[str, Any], db_path: Path | str | None = None) -> "Platform":
        runtime_cfg = config.get("runtime") if isinstance(config.get("runtime"), dict) else {}
        security_cfg = config.get("security") if isinstance(config.get("security"), dict) else {}
        path = db_path if db_path is not None else runtime_cfg.get("platform_db") or "output/platform.sqlite"
        db = Database(path)
        secrets = SecretBox.from_env(str(security_cfg.get("secret_key_env") or DEFAULT_KEY_ENV))
        platform = cls(config=config, db=db, secrets=secrets, audit=AuditLog(db), settings=SettingsStore(db))
        platform.attach_optional_services()
        applied = db.migrate()
        if applied:
            logger.info("platform: applied migrations {}", ", ".join(applied))
        for attr, module_name, factory_name in OPTIONAL_SERVICES:
            module = platform.extras.get(f"module:{module_name}")
            if module is None:
                continue
            factory = getattr(module, factory_name, None)
            if callable(factory):
                setattr(platform, attr, factory(platform))
        if not secrets.available:
            logger.warning("platform: {} is not set; cloud connections cannot store credentials", secrets.env_var)
        return platform

    def attach_optional_services(self) -> None:
        """Import optional packages so their migrations register before `db.migrate()` runs."""
        for _attr, module_name, _factory in OPTIONAL_SERVICES:
            try:
                self.extras[f"module:{module_name}"] = importlib.import_module(module_name)
            except ModuleNotFoundError as exc:
                if exc.name and exc.name.startswith(module_name.split(".")[0]) and module_name.startswith(exc.name):
                    continue
                raise

    def effective_config(self) -> dict[str, Any]:
        return self.settings.apply(self.config)

    @property
    def auth_mode(self) -> str:
        security_cfg = self.config.get("security") if isinstance(self.config.get("security"), dict) else {}
        auth_cfg = security_cfg.get("auth") if isinstance(security_cfg.get("auth"), dict) else {}
        mode = str(auth_cfg.get("mode") or "required").lower()
        return mode if self.auth is not None else "disabled"
