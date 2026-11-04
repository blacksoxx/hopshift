"""Backward-compatible import path; the implementation lives in cim.translators.vmware."""
from cim.translators.vmware import (  # noqa: F401
    SCHEMA_NAME,
    SUPPORTED_BLOCKERS,
    translate_vmware_discovery_to_cim,
)

__all__ = ["SCHEMA_NAME", "SUPPORTED_BLOCKERS", "translate_vmware_discovery_to_cim"]
