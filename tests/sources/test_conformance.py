"""Every registered source passes the conformance kit (hopshift.testing.check_source) against
its discovery fixtures, and every registered target renders the resulting CIM."""
from __future__ import annotations

from pathlib import Path

import pytest

from hopshift.sources import registry as sources
from hopshift.sources.registry import SourceSpec
from hopshift.targets import registry as targets
from hopshift.testing._common import REPO_ROOT, existing_path
from hopshift.testing.sources import check_source

# Built-in sources and the fixtures that exercise them; plugins declare theirs through
# SourceSpec.extra["fixture"] (a path or a list of paths).
BUILTIN_FIXTURES: dict[str, list[Path]] = {
    "vmware": [REPO_ROOT / "tests" / "fixtures" / "discovery_multi_vm.json", REPO_ROOT / "discovery-2.json"],
}


def _fixtures_for(spec: SourceSpec) -> list[Path]:
    paths = list(BUILTIN_FIXTURES.get(spec.name, []))
    declared = spec.extra.get("fixture") or spec.extra.get("fixtures") or []
    for item in [declared] if isinstance(declared, (str, Path)) else list(declared):
        resolved = existing_path(str(item))
        if resolved is not None:
            paths.append(resolved)
    return [path for path in paths if path.exists()]


@pytest.mark.parametrize("name", sources.names())
def test_source_passes_conformance(name: str) -> None:
    spec = sources.get(name)
    fixtures = _fixtures_for(spec)
    if not fixtures:
        pytest.skip(f"no discovery fixture known for source {name}; declare SourceSpec.extra['fixture']")

    for fixture in fixtures:
        report = check_source(spec, fixture)

        assert report.passed, report.render()
        for check in ("payload", "translate", "source.platform", "vm_count", "blockers", "ids", "references", "roundtrip"):
            assert report.get(check).status == "pass", report.render()  # type: ignore[union-attr]
        for target in targets.names():
            assert report.get(f"render[{target}]").status == "pass", report.render()  # type: ignore[union-attr]
