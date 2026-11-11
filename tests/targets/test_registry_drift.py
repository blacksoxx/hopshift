"""The compliance catalog and the connections catalog are explicit lists; they must not drift
from the built-in target registry."""
from __future__ import annotations

from hopshift.services.compliance.controls import ALL_CLOUDS, controls_for_cloud
from hopshift.services.connections.models import PROVIDERS
from hopshift.targets import registry as targets


def test_every_built_in_target_has_a_compliance_catalog() -> None:
    for spec in targets.all_specs():
        assert spec.name in ALL_CLOUDS, f"{spec.name} is registered but has no compliance catalog"
        assert controls_for_cloud(spec.name), f"{spec.name} has an empty control catalog"
    assert set(ALL_CLOUDS) == set(targets.names())


def test_every_built_in_target_connection_provider_is_in_the_catalog() -> None:
    for spec in targets.all_specs():
        assert spec.connection_provider is None or spec.connection_provider in PROVIDERS, spec.name
