"""Helpers shared by the target and source conformance checks: fixtures, the real pipeline
nodes, external binaries. Nothing here is specific to one target or source."""
from __future__ import annotations

import json
import shutil
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from hopshift.cim.schema import CanonicalInfrastructureModel, TargetProvider
from hopshift.pipeline.nodes.blocker_parser import blocker_parser
from hopshift.pipeline.nodes.cim_mapper import cim_mapper
from hopshift.pipeline.nodes.enricher import enricher
from hopshift.pipeline.nodes.ingest import ingest
from hopshift.pipeline.nodes.sizer import sizer
from hopshift.pipeline.state import MigrationState
from hopshift.sources.registry import Translator

PACKAGE_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
PACKAGED_DISCOVERY_FIXTURE = PACKAGE_FIXTURES_DIR / "discovery_multi_vm.json"

# The development checkout: hopshift/testing/_common.py -> hopshift/testing -> hopshift -> repo root.
REPO_ROOT = Path(__file__).resolve().parents[2]
_REPO_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "discovery_multi_vm.json"
_REPO_DISCOVERY_2 = REPO_ROOT / "discovery-2.json"

POLICIES_DIR = REPO_ROOT / "hopshift" / "validation" / "policies"
DEFAULT_PLUGIN_CACHE = Path.home() / ".cache" / "hopshift" / "terraform-plugins"

Payload = dict[str, Any]
FixtureInput = str | Path | Mapping[str, Any]


def default_discovery_fixtures() -> list[Path]:
    """The multi-VM fixture (repository copy when present, else the packaged one) plus
    `discovery-2.json` from the repository root when it exists."""
    fixtures = [_REPO_FIXTURE if _REPO_FIXTURE.exists() else PACKAGED_DISCOVERY_FIXTURE]
    if _REPO_DISCOVERY_2.exists():
        fixtures.append(_REPO_DISCOVERY_2)
    return fixtures


def resolve_fixtures(discovery_fixture: FixtureInput | Sequence[FixtureInput] | None) -> list[tuple[str, Payload]]:
    """Normalise the `discovery_fixture` argument to (label, payload) pairs."""
    if discovery_fixture is None:
        items: list[FixtureInput] = list(default_discovery_fixtures())
    elif isinstance(discovery_fixture, (str, Path, Mapping)):
        items = [discovery_fixture]
    else:
        items = list(discovery_fixture)

    resolved: list[tuple[str, Payload]] = []
    for index, item in enumerate(items):
        if isinstance(item, Mapping):
            resolved.append((f"payload[{index}]", dict(item)))
        else:
            path = Path(item)
            resolved.append((path.name, load_payload(path)))
    return resolved


def load_payload(source: FixtureInput) -> Payload:
    if isinstance(source, Mapping):
        return dict(source)
    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"discovery fixture not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"discovery fixture {path} must contain a JSON object")
    return payload


def initial_state(payload: Payload, target: str) -> MigrationState:
    return {
        "discovery_data": json.loads(json.dumps(payload)),  # nodes mutate; keep the caller's payload intact
        "config": {},
        "target_provider": TargetProvider(target),
        "quarantine_queue": [],
        "messages": [],
        "status": "pending",
    }


def prefilter(payload: Payload, target: str) -> MigrationState:
    """ingest -> blocker_parser -> enricher, exactly as the graph runs them before translation."""
    state = initial_state(payload, target)
    for node in (ingest, blocker_parser, enricher):
        state = node(state)
    return state


def pipeline_cim(payload: Payload, target: str, translate: Translator | None = None) -> MigrationState:
    """Run the real deterministic nodes up to the sized CIM.

    With `translate` given, the translator is called directly instead of being resolved from the
    source registry (so an unregistered SourceSpec can be checked); otherwise cim_mapper picks
    the translator from `metadata.schema_name`.
    """
    state = prefilter(payload, target)
    if translate is None:
        state = cim_mapper(state)
    else:
        cim = translate(dict(state["discovery_data"]), target)
        if not isinstance(cim, CanonicalInfrastructureModel):
            raise TypeError(f"translator returned {type(cim).__name__}, expected CanonicalInfrastructureModel")
        state["cim"] = cim
    return sizer(state)


def required_tags(cim: CanonicalInfrastructureModel) -> dict[str, str]:
    return {"Environment": "test", "Owner": "platform", "MigratedFrom": cim.migrated_from}


def find_binary(name: str) -> str | None:
    """A binary on PATH or next to the interpreter (the venv `bin/opa` convention of this repo)."""
    found = shutil.which(name)
    if found:
        return found
    sibling = Path(sys.executable).parent / name
    return str(sibling) if sibling.exists() else None


def existing_path(raw: str) -> Path | None:
    """Resolve a repository-relative path against the CWD first, then the hopshift checkout."""
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        return candidate if candidate.exists() else None
    for base in (Path.cwd(), REPO_ROOT):
        resolved = base / candidate
        if resolved.exists():
            return resolved
    return None
