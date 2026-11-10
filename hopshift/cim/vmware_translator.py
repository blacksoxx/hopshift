"""Backward-compatible import path; the implementation lives in hopshift.sources.vmware."""
from hopshift.sources.vmware import (  # noqa: F401
    SCHEMA_NAME,
    SUPPORTED_BLOCKERS,
    translate_vmware_discovery_to_cim,
)

__all__ = ["SCHEMA_NAME", "SUPPORTED_BLOCKERS", "translate_vmware_discovery_to_cim"]
