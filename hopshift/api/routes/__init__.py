"""Routers mounted under /hopshift.api. Add an area by creating a module exposing `router` and listing it here."""
from __future__ import annotations

from importlib import import_module

from fastapi import APIRouter

ROUTE_MODULES: tuple[str, ...] = (
    "hopshift.api.routes.meta",
    "hopshift.api.routes.runs",
    "hopshift.api.routes.assess",
    "hopshift.api.routes.settings",
    "hopshift.api.routes.auth",
    "hopshift.api.routes.users",
    "hopshift.api.routes.audit",
    "hopshift.api.routes.connections",
    "hopshift.api.routes.deploy",
)


def all_routers() -> list[APIRouter]:
    routers: list[APIRouter] = []
    for name in ROUTE_MODULES:
        try:
            module = import_module(name)
        except ModuleNotFoundError as exc:
            if exc.name == name:
                continue  # workstream not landed yet
            raise
        router = getattr(module, "router", None)
        if isinstance(router, APIRouter):
            routers.append(router)
    return routers
