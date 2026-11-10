"""Target conformance: does a renderer package honour the contract the pipeline relies on?

`check_target` resolves a TargetSpec (by name through the registry, or an unregistered spec
object that is registered for the duration of the check), then records one result per check:

- `spec*`                 metadata sanity: label/blurb/architectures, docs path, connection catalog
- `package`, `renderer.*` the five renderer functions exist with the right signatures
- `sizing*`               get_instance_type exists, sizes every vCPU/RAM shape, is monotonic in RAM
- per discovery fixture:  `pipeline`, `render`, `layout`, `guards`, `pipeline.allowlist`, `parse`,
                          `determinism`, `opa`, `compliance`, `terraform`, `tflint`

The fixture checks run the real pipeline nodes (ingest, blocker_parser, enricher, cim_mapper,
sizer) and the real deterministic assembler, then the same security guards hcl_generator
applies, the HCL parser, the OPA bundle and, when asked, terraform init/validate and tflint.
"""
from __future__ import annotations

import inspect
import re
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from importlib import import_module
from pathlib import Path
from typing import Any, TypeVar

from hopshift.cim.schema import CanonicalInfrastructureModel
from hopshift.pipeline.generation.deterministic import render_deterministic
from hopshift.pipeline.nodes.hcl_generator import (
    _COMMON_PROVIDER_SOURCES,
    _PROVIDER_SOURCE_ALLOWLIST,
    _PROVIDER_SOURCE_SHAPE,
    _SOURCE_ASSIGNMENT,
    _enforce_dangerous_construct_guards,
    _enforce_security_guards,
    _ensure_runnable_hcl,
    _validate_output_paths,
)
from hopshift.pipeline.state import MigrationState
from hopshift.targets import registry as targets
from hopshift.targets.registry import TIERS, TargetSpec
from hopshift.testing._common import (
    DEFAULT_PLUGIN_CACHE,
    POLICIES_DIR,
    FixtureInput,
    existing_path,
    find_binary,
    pipeline_cim,
    required_tags,
    resolve_fixtures,
)
from hopshift.testing.report import ConformanceReport, SkipCheck
from hopshift.validation.hcl_parser import parse_hcl_files
from hopshift.validation.opa_client import OPAEvaluationResult, evaluate_policies
from hopshift.validation.paths import UnsafePathError, ensure_safe_relative_path
from hopshift.validation.tf_runner import validate_hcl

T = TypeVar("T")

TERRAFORM_ENV = "HOPSHIFT_CONFORMANCE_TERRAFORM"

# (module suffix, function name, accepts required_tags=) - mirrors the deterministic assembler.
RENDERERS: tuple[tuple[str, str, bool], ...] = (
    ("network", "render_networking", False),
    ("compute", "render_compute", True),
    ("storage", "render_storage", True),
    ("placement", "render_placement", True),
    ("runtime", "render_runtime", True),
)

# Shapes every sizing table must resolve (small, odd, huge). Mirrors tests/cim/test_properties.py
# without the hypothesis dependency so plugin repositories need nothing beyond pytest.
SIZING_VCPUS: tuple[int, ...] = (1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128, 256, 512)
SIZING_RAM_MB: tuple[int, ...] = (
    256, 512, 1024, 1536, 2048, 3072, 4096, 6144, 8192, 12288, 16384, 24576, 32768, 49152, 65536,
    98304, 131072, 262144, 524288, 1048576, 4_000_000,
)

_PROVIDERS_FILES = ("providers.tf", "targets.tf")
_PROVIDER_BLOCK = re.compile(r'^\s*provider\s+"', re.MULTILINE)


def check_target(
    spec_or_name: TargetSpec | str,
    *,
    discovery_fixture: FixtureInput | Sequence[FixtureInput] | None = None,
    run_terraform: bool = False,
    opa_bin: str | None = None,
    terraform_bin: str = "terraform",
    tflint_bin: str = "tflint",
    plugin_cache_dir: str | Path | None = None,
) -> ConformanceReport:
    """Run every conformance check for a target and return the report (never raises for a
    broken target; unknown names raise `hopshift.targets.registry.UnknownTarget`)."""
    spec = spec_or_name if isinstance(spec_or_name, TargetSpec) else targets.get(spec_or_name)
    report = ConformanceReport(kind="target", subject=spec.name, label=spec.label)

    with _registered(spec):
        report.run("spec", lambda: _check_spec(spec))
        report.run("spec.docs", lambda: _check_docs(spec))
        report.run("spec.connection_provider", lambda: _check_connection_provider(spec))
        report.run("package", lambda: _check_package(spec))
        for suffix, function_name, accepts_tags in RENDERERS:
            report.run(f"renderer.{suffix}", lambda s=suffix, f=function_name, t=accepts_tags: _check_renderer(spec, s, f, t))

        lookup = _capture(report, "sizing_table", lambda: _check_sizing_table(spec))
        if lookup is None:
            report.add_skip("sizing.coverage", "not run: sizing_table failed")
            report.add_skip("sizing.monotonic", "not run: sizing_table failed")
        else:
            report.run("sizing.coverage", lambda: _check_sizing_coverage(lookup))
            report.run("sizing.monotonic", lambda: _check_sizing_monotonic(spec, lookup))

        try:
            fixtures = resolve_fixtures(discovery_fixture)
        except Exception as exc:  # noqa: BLE001 - unreadable fixture is a report line, not a crash
            report.add_fail("fixtures", f"{type(exc).__name__}: {exc}")
            return report

        resolved_opa = opa_bin or find_binary("opa")
        cache = Path(plugin_cache_dir) if plugin_cache_dir else DEFAULT_PLUGIN_CACHE
        for label, payload in fixtures:
            _check_fixture(
                report, spec, label, payload,
                run_terraform=run_terraform, opa_bin=resolved_opa,
                terraform_bin=terraform_bin, tflint_bin=tflint_bin, plugin_cache_dir=cache,
            )
    return report


# ── registry handling ─────────────────────────────────────────────────────────


@contextmanager
def _registered(spec: TargetSpec) -> Iterator[None]:
    """Make `spec` resolvable through the registry while the check runs (the assembler and the
    sizer look targets up by name), restoring whatever was registered before."""
    targets.load_plugins()
    with targets._LOCK:
        previous = targets._REGISTRY.get(spec.name)
        targets._REGISTRY[spec.name] = spec
    try:
        yield
    finally:
        with targets._LOCK:
            if previous is None:
                targets._REGISTRY.pop(spec.name, None)
            else:
                targets._REGISTRY[spec.name] = previous


def _capture(report: ConformanceReport, name: str, check: Callable[[], tuple[T, str]]) -> T | None:
    """Like `report.run` for checks that also produce a value needed by later checks."""
    holder: list[T] = []

    def wrapped() -> str:
        value, message = check()
        holder.append(value)
        return message

    report.run(name, wrapped)
    return holder[0] if holder else None


# ── spec and package checks ───────────────────────────────────────────────────


def _check_spec(spec: TargetSpec) -> str:
    problems: list[str] = []
    if not spec.label.strip():
        problems.append("label is empty")
    if not spec.blurb.strip():
        problems.append("blurb is empty (one line: what gets rendered)")
    if spec.tier not in TIERS:
        problems.append(f"tier {spec.tier!r} is not one of {', '.join(TIERS)}")
    if not spec.package.strip():
        problems.append("package is empty")
    if not spec.architectures:
        problems.append("architectures is empty (which guest architectures can the target host?)")
    assert not problems, "; ".join(problems)
    return f"tier={spec.tier} root={spec.root}/ tflint={spec.tflint} architectures={','.join(sorted(spec.architectures))}"


def _check_docs(spec: TargetSpec) -> str:
    if not spec.docs:
        raise SkipCheck("no docs path declared on the spec")
    path = existing_path(spec.docs)
    assert path is not None, f"docs path {spec.docs!r} does not exist (relative to the CWD or the hopshift checkout)"
    return str(spec.docs)


def _check_connection_provider(spec: TargetSpec) -> str:
    if spec.connection_provider is None:
        raise SkipCheck("connection_provider=None: deployments through stored connections are not offered")
    from hopshift.services.connections.models import CATALOG  # lazy: pulls the cloud SDKs

    assert spec.connection_provider in CATALOG, (
        f"connection_provider {spec.connection_provider!r} is not in the connections catalog "
        f"(known: {', '.join(sorted(CATALOG))}); contribute a ProviderSpec or set connection_provider=None"
    )
    methods = ", ".join(method.key for method in CATALOG[spec.connection_provider].methods)
    return f"{spec.connection_provider}: {methods}"


def _check_package(spec: TargetSpec) -> str:
    module = import_module(spec.package)
    location = getattr(module, "__file__", None) or "namespace package"
    return f"{spec.package} ({location})"


def _check_renderer(spec: TargetSpec, suffix: str, function_name: str, accepts_tags: bool) -> str:
    module_name = f"{spec.package}.{suffix}"
    module = import_module(module_name)
    function = getattr(module, function_name, None)
    assert callable(function), f"{module_name} must define {function_name}(cim{', required_tags=None' if accepts_tags else ''}) -> dict[str, str]"

    parameters = list(inspect.signature(function).parameters.values())
    positional = [
        p for p in parameters
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.VAR_POSITIONAL)
    ]
    assert positional, f"{module_name}.{function_name} must take the CIM as its first positional argument"
    if accepts_tags:
        accepts = any(p.name == "required_tags" for p in parameters) or any(p.kind == p.VAR_KEYWORD for p in parameters)
        assert accepts, f"{module_name}.{function_name} must accept required_tags= (the assembler passes it as a keyword)"
    return f"{module_name}.{function_name}"


# ── sizing checks ─────────────────────────────────────────────────────────────


def _check_sizing_table(spec: TargetSpec) -> tuple[Callable[[int, int], str], str]:
    module_name = f"{spec.package}.sizing_table"
    module = import_module(module_name)
    lookup = getattr(module, "get_instance_type", None)
    assert callable(lookup), f"{module_name} must define get_instance_type(vcpus: int, ram_mb: int) -> str"

    parameters = list(inspect.signature(lookup).parameters.values())
    positional = [p for p in parameters if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    variadic = any(p.kind == p.VAR_POSITIONAL for p in parameters)
    assert len(positional) >= 2 or variadic, f"{module_name}.get_instance_type must accept (vcpus, ram_mb)"
    return lookup, f"{module_name}.get_instance_type"


def _check_sizing_coverage(lookup: Callable[[int, int], str]) -> str:
    for vcpus in SIZING_VCPUS:
        for ram_mb in SIZING_RAM_MB:
            value = lookup(vcpus, ram_mb)
            assert isinstance(value, str) and value.strip(), f"get_instance_type({vcpus}, {ram_mb}) returned {value!r}"
            assert lookup(vcpus, ram_mb) == value, f"get_instance_type({vcpus}, {ram_mb}) is not deterministic"
    return f"{len(SIZING_VCPUS) * len(SIZING_RAM_MB)} vCPU/RAM shapes resolve to an instance type"


def _check_sizing_monotonic(spec: TargetSpec, lookup: Callable[[int, int], str]) -> str:
    module = import_module(f"{spec.package}.sizing_table")
    table = next(
        (value for name, value in vars(module).items() if name.endswith("_SIZING_TABLE") and isinstance(value, dict)),
        None,
    )
    select_bucket = getattr(module, "_select_vcpu_bucket", None)
    if table is None or not callable(select_bucket):
        raise SkipCheck("table is not bucketed (no *_SIZING_TABLE dict with _select_vcpu_bucket); RAM monotonicity not checked")

    for vcpus in SIZING_VCPUS:
        bucket = select_bucket(vcpus)
        options = table[bucket]
        order = {name: index for index, (_, name) in enumerate(options)}
        last = -1
        for ram_mb in sorted(SIZING_RAM_MB):
            chosen = lookup(vcpus, ram_mb)
            assert chosen in order, f"get_instance_type({vcpus}, {ram_mb}) = {chosen!r} is not in the {bucket}-vCPU bucket"
            assert order[chosen] >= last, f"more RAM picked a smaller shape: vcpus={vcpus} ram_mb={ram_mb} -> {chosen}"
            last = order[chosen]
    return f"{len(table)} vCPU buckets; more RAM never picks a smaller shape"


# ── fixture checks ────────────────────────────────────────────────────────────


def _check_fixture(
    report: ConformanceReport,
    spec: TargetSpec,
    label: str,
    payload: dict[str, Any],
    *,
    run_terraform: bool,
    opa_bin: str | None,
    terraform_bin: str,
    tflint_bin: str,
    plugin_cache_dir: Path,
) -> None:
    def tag(name: str) -> str:
        return f"{name}[{label}]"

    def skip_rest(names: Sequence[str], reason: str) -> None:
        for name in names:
            report.add_skip(tag(name), reason)

    cim = _capture(report, tag("pipeline"), lambda: _run_pipeline(payload, spec.name))
    downstream = ("render", "layout", "guards", "pipeline.allowlist", "parse", "determinism", "opa", "compliance", "terraform", "tflint")
    if cim is None:
        skip_rest(downstream, "not run: pipeline failed")
        return

    files = _capture(report, tag("render"), lambda: _render(spec, cim))
    if files is None:
        skip_rest(downstream[1:], "not run: render failed")
        return

    report.run(tag("layout"), lambda: _check_layout(spec, files))
    report.run(tag("guards"), lambda: _check_guards(spec, files))
    report.run(tag("pipeline.allowlist"), lambda: _check_pipeline_allowlist(spec, files))
    report.run(tag("parse"), lambda: _check_parse(files))
    report.run(tag("determinism"), lambda: _check_determinism(spec, cim, files))

    opa_result = _capture(report, tag("opa"), lambda: _check_opa(files, opa_bin))
    if opa_result is None:
        report.add_skip(tag("compliance"), "not run: OPA not evaluated")
    else:
        report.run(tag("compliance"), lambda: _check_compliance(spec, opa_result))

    _check_terraform(
        report, spec, label, files,
        run_terraform=run_terraform, terraform_bin=terraform_bin, tflint_bin=tflint_bin, plugin_cache_dir=plugin_cache_dir,
    )


def _run_pipeline(payload: dict[str, Any], target: str) -> tuple[CanonicalInfrastructureModel, str]:
    state: MigrationState = pipeline_cim(payload, target)
    cim = state["sized_cim"]
    quarantined = len(state.get("quarantine_queue", []))
    assert cim.compute_units, f"fixture yields no migratable ComputeUnit ({quarantined} quarantined)"
    return cim, (
        f"{len(cim.compute_units)} compute units, {len(cim.clusters)} clusters, "
        f"{len(cim.network_topology.distributed_switches)} switches, {quarantined} quarantined"
    )


def _render(spec: TargetSpec, cim: CanonicalInfrastructureModel) -> tuple[dict[str, str], str]:
    files = render_deterministic(provider=spec.name, cim=cim, required_tags=required_tags(cim))
    assert isinstance(files, dict) and files, "render_deterministic returned no files"
    for path, content in files.items():
        assert isinstance(path, str) and isinstance(content, str), f"{path!r}: renderers must return str -> str"
    return files, f"{len(files)} files"


def _check_layout(spec: TargetSpec, files: dict[str, str]) -> str:
    root = spec.root
    problems: list[str] = []
    seen_folded: dict[str, str] = {}
    for path in files:
        try:
            ensure_safe_relative_path(path)
        except UnsafePathError as exc:
            problems.append(str(exc))
            continue
        if not path.startswith(root + "/"):
            problems.append(f"{path}: outside {root}/")
        elif "/" in path[len(root) + 1 :]:
            problems.append(f"{path}: nested directory; the root module must be flat")
        if not path.endswith(".tf"):
            problems.append(f"{path}: not a .tf file")
        folded = path.lower()
        if folded in seen_folded:
            problems.append(f"{path} and {seen_folded[folded]} differ only by case (collide on case-insensitive filesystems)")
        seen_folded[folded] = path

    names = {path[len(root) + 1 :] for path in files if path.startswith(root + "/")}
    if "variables.tf" not in names:
        problems.append("variables.tf is missing (render_runtime must emit it)")
    providers_file = next((name for name in _PROVIDERS_FILES if name in names), None)
    if providers_file is None:
        problems.append("providers.tf (or targets.tf) with the terraform { required_providers } block is missing")
    else:
        content = files[f"{root}/{providers_file}"]
        if "required_providers" not in content:
            problems.append(f"{providers_file} has no required_providers block")
        if not _PROVIDER_BLOCK.search(content):
            problems.append(f"{providers_file} has no provider block")
    assert not problems, "; ".join(problems)
    return f"{len(files)} flat .tf files under {root}/ including {providers_file} and variables.tf"


def _check_guards(spec: TargetSpec, files: dict[str, str]) -> str:
    """The guards hcl_generator applies before validation, with the plugin's declared provider
    sources accepted where the core allow-list has no entry for the target."""
    _validate_output_paths(provider=spec.name, hcl_output=files)
    _enforce_dangerous_construct_guards(files)
    if spec.name in _PROVIDER_SOURCE_ALLOWLIST:
        _enforce_security_guards(provider=spec.name, hcl_output=files)
    else:
        problems = _provider_source_problems(spec, files)
        assert not problems, "; ".join(problems)
    _ensure_runnable_hcl(provider=spec.name, hcl_output=files)
    return "no provisioners, external/http data sources, null_resource/local_file, remote modules or unsafe patterns"


def _provider_source_problems(spec: TargetSpec, files: dict[str, str]) -> list[str]:
    declared = {str(item).strip().lower() for item in spec.extra.get("provider_sources", ())}
    allowed = _PROVIDER_SOURCE_ALLOWLIST.get(spec.name, set()) | _COMMON_PROVIDER_SOURCES | declared
    problems: list[str] = []
    for path, content in files.items():
        for match in _SOURCE_ASSIGNMENT.finditer(content):
            raw = match.group(1).strip()
            source = raw.lower()
            if source.startswith("./"):
                if ".." in source.split("/"):
                    problems.append(f"{path}: module source escapes the output root: {raw}")
                continue
            host, _, remainder = source.partition("/")
            if host == "registry.terraform.io" and remainder:
                source = remainder
            if _PROVIDER_SOURCE_SHAPE.match(source):
                if source not in allowed:
                    problems.append(
                        f"{path}: provider source {raw!r} is not allowed; declare it in TargetSpec.extra['provider_sources']"
                    )
                continue
            problems.append(f"{path}: remote or non-local source {raw!r} is not allowed")
    return problems


def _provider_sources_used(files: dict[str, str]) -> set[str]:
    used: set[str] = set()
    for content in files.values():
        for match in _SOURCE_ASSIGNMENT.finditer(content):
            source = match.group(1).strip().lower()
            host, _, remainder = source.partition("/")
            if host == "registry.terraform.io" and remainder:
                source = remainder
            if _PROVIDER_SOURCE_SHAPE.match(source):
                used.add(source)
    return used


def _check_pipeline_allowlist(spec: TargetSpec, files: dict[str, str]) -> str:
    """hcl_generator accepts provider sources from its per-target allow-list, the common set and
    the sources the target declares in TargetSpec.extra["provider_sources"]; anything else in the
    output would be rejected by the pipeline and is reported here."""
    used = _provider_sources_used(files)
    declared = {str(item).strip().lower() for item in spec.extra.get("provider_sources", ())}
    allowed = _PROVIDER_SOURCE_ALLOWLIST.get(spec.name, set()) | _COMMON_PROVIDER_SOURCES | declared
    unknown = sorted(used - allowed)
    assert not unknown, (
        f"the pipeline guard would reject {', '.join(unknown)} for {spec.name}: declare the source in "
        f"TargetSpec.extra['provider_sources'] (or, for a built-in hyperscaler, in "
        f"hopshift.pipeline.nodes.hcl_generator._PROVIDER_SOURCE_ALLOWLIST)"
    )
    return ", ".join(sorted(used)) if used else "no provider sources referenced"


def _check_parse(files: dict[str, str]) -> str:
    model = parse_hcl_files(files)
    errors = model["parse_errors"]
    assert not errors, "; ".join(f"{item['file']}: {item['error']}" for item in errors)
    assert model["resources"], "no resource blocks were parsed from the output"
    return f"{len(model['resources'])} resources, {len(model['variables'])} variables, {len(model['required_providers'])} required providers"


def _check_determinism(spec: TargetSpec, cim: CanonicalInfrastructureModel, files: dict[str, str]) -> str:
    again = render_deterministic(provider=spec.name, cim=cim, required_tags=required_tags(cim))
    changed = sorted(path for path in set(files) | set(again) if files.get(path) != again.get(path))
    assert not changed, f"rendering twice differs: {', '.join(changed[:5])}"
    return "identical output on a second render"


def _check_opa(files: dict[str, str], opa_bin: str | None) -> tuple[OPAEvaluationResult, str]:
    if opa_bin is None:
        raise SkipCheck("opa binary not found; install opa to evaluate the policy bundle")
    result = evaluate_policies(hcl_output=files, policies_dir=POLICIES_DIR, opa_bin=opa_bin)
    assert result.passed, "; ".join(result.deny_messages or result.errors)
    assert not result.enforce_violations, "; ".join(
        f"{item['control']}: {item['message']} ({item['resource']})" for item in result.enforce_violations
    )
    return result, f"gate passed, {len(result.evaluated)} compliance controls evaluated, 0 enforce violations"


def _check_compliance(spec: TargetSpec, result: OPAEvaluationResult) -> str:
    from hopshift.services.compliance.controls import ALL_CLOUDS, controls_for_cloud

    if spec.name not in ALL_CLOUDS:
        raise SkipCheck(f"no compliance controls in the bundle for {spec.name} (see docs/plugins.md, 'Compliance controls')")
    expected = {control.id for control in controls_for_cloud(spec.name)}
    evaluated = set(result.evaluated)
    assert evaluated == expected, (
        f"controls evaluated by the bundle differ from the catalog: {sorted(evaluated ^ expected)}"
    )
    advisory = sorted({str(item["control"]) for item in result.advisory_violations})
    message = f"{len(expected)} controls evaluated"
    if advisory:
        message += f"; advisory findings: {', '.join(advisory)}"
    return message


def _check_terraform(
    report: ConformanceReport,
    spec: TargetSpec,
    label: str,
    files: dict[str, str],
    *,
    run_terraform: bool,
    terraform_bin: str,
    tflint_bin: str,
    plugin_cache_dir: Path,
) -> None:
    terraform_name = f"terraform[{label}]"
    tflint_name = f"tflint[{label}]"
    if not run_terraform:
        report.add_skip(terraform_name, f"run_terraform=False (set {TERRAFORM_ENV}=1 or pass --terraform)")
        report.add_skip(tflint_name, "run_terraform=False")
        return

    terraform = find_binary(terraform_bin)
    if terraform is None:
        report.add_skip(terraform_name, f"{terraform_bin} binary not found")
        report.add_skip(tflint_name, f"{terraform_bin} binary not found")
        return

    tflint = find_binary(tflint_bin) if spec.tflint else None
    result = validate_hcl(
        hcl_output=files,
        terraform_bin=terraform,
        tflint_bin=tflint or tflint_bin,
        run_tflint=tflint is not None,
        plugin_cache_dir=str(plugin_cache_dir),
    )
    if result.terraform_validate_passed:
        report.add_pass(terraform_name, "terraform init and validate passed")
    else:
        report.add_fail(terraform_name, "; ".join(result.errors) or "terraform validate failed")

    if not spec.tflint:
        report.add_skip(tflint_name, "spec.tflint=False: no ruleset for this provider")
    elif tflint is None:
        report.add_skip(tflint_name, f"{tflint_bin} binary not found")
    elif result.tflint_passed:
        report.add_pass(tflint_name, "tflint passed")
    else:
        report.add_fail(tflint_name, "; ".join(result.errors) or "tflint failed")
