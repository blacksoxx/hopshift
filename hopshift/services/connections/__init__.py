"""Cloud connections: a catalog of auth methods per provider, encrypted credential storage,
verification against the cloud, and credential resolution for Terraform.

`hopshift.services.platform.Platform` imports this package before running migrations (so the tables in
`store.py` register) and then calls `build_connection_service(platform)`.
"""
from __future__ import annotations

from typing import Any

from . import store as _store  # noqa: F401 - registers the connections and device_flows migrations
from .models import CATALOG, Connection, VerifyResult, catalog_dict
from .service import ConnectionService


def build_connection_service(platform: Any) -> ConnectionService:
    return ConnectionService(platform)


__all__ = ["CATALOG", "Connection", "ConnectionService", "VerifyResult", "build_connection_service", "catalog_dict"]
