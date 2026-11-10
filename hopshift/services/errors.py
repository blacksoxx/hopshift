"""Exceptions shared by platform services; api/app.py maps them to HTTP status codes."""
from __future__ import annotations


class PlatformError(Exception):
    """Base class; message is safe to show to the caller (never include secrets)."""


class NotFound(PlatformError):
    """404"""


class Conflict(PlatformError):
    """409"""


class Forbidden(PlatformError):
    """403"""


class Invalid(PlatformError):
    """400"""


class Unavailable(PlatformError):
    """503 (a required binary, key or backend is missing)"""
