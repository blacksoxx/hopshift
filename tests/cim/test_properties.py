"""Property-based tests (hypothesis) for the deterministic building blocks.

These guard invariants that unit tests with fixed inputs cannot: every VM shape sizes to a
real instance type, bigger machines never size smaller, blocker detection returns only known
canonical names and is idempotent.
"""
from __future__ import annotations

from importlib import import_module

from hypothesis import given, settings
from hypothesis import strategies as st

from cim.blockers import _ALIASES, KNOWN_BLOCKERS, blockers_for_vm, is_hard, normalize_blocker

PROVIDERS = ("aws", "azure", "gcp", "openstack")

vcpus = st.integers(min_value=1, max_value=512)
ram_mb = st.integers(min_value=256, max_value=4_000_000)


@settings(max_examples=200)
@given(provider=st.sampled_from(PROVIDERS), cpu=vcpus, ram=ram_mb)
def test_every_shape_sizes_to_an_instance_type(provider: str, cpu: int, ram: int) -> None:
    sizing = import_module(f"providers.{provider}.sizing_table")
    instance = sizing.get_instance_type(cpu, ram)
    assert isinstance(instance, str) and instance.strip()


@settings(max_examples=200)
@given(provider=st.sampled_from(PROVIDERS), cpu=vcpus, ram=ram_mb, more_ram=st.integers(min_value=0, max_value=1_000_000))
def test_more_ram_in_the_same_bucket_never_picks_a_smaller_shape(provider: str, cpu: int, ram: int, more_ram: int) -> None:
    sizing = import_module(f"providers.{provider}.sizing_table")
    table = next(value for name, value in vars(sizing).items() if name.endswith("_SIZING_TABLE"))
    bucket = sizing._select_vcpu_bucket(cpu)
    options = table[bucket]
    order = {name: index for index, (_, name) in enumerate(options)}
    smaller = sizing.get_instance_type(cpu, ram)
    larger = sizing.get_instance_type(cpu, ram + more_ram)
    assert order[larger] >= order[smaller]


@given(st.sampled_from(sorted(_ALIASES)))
def test_blocker_normalisation_is_idempotent(alias: str) -> None:
    canonical = normalize_blocker(alias)
    assert canonical in KNOWN_BLOCKERS
    assert normalize_blocker(canonical) == canonical
    assert isinstance(is_hard(canonical), bool)


@given(st.text(min_size=0, max_size=40))
def test_unknown_blocker_spellings_are_rejected(value: str) -> None:
    canonical = normalize_blocker(value)
    assert canonical is None or canonical in KNOWN_BLOCKERS


flag_names = st.sampled_from(["is_encrypted", "has_rdm_disks", "has_shared_disks", "is_template", "has_vtpm", "vapp_config_present", "mounted_iso_present"])


@settings(max_examples=200)
@given(
    flags=st.dictionaries(flag_names, st.booleans(), max_size=7),
    listed=st.lists(st.sampled_from(sorted(_ALIASES) + ["bogus", ""]), max_size=5),
    power_state=st.sampled_from(["poweredOn", "poweredOff", "suspended", "", None]),
    snapshot_count=st.integers(min_value=0, max_value=5),
    architecture=st.sampled_from(["x86_64", "amd64", "X86_64", "ppc64le", "s390x", ""]),
)
def test_blockers_for_vm_returns_known_unique_blockers(flags: dict[str, bool], listed: list[str], power_state: str | None, snapshot_count: int, architecture: str) -> None:
    vm: dict[str, object] = {**flags, "migration_blockers": listed, "power_state": power_state, "snapshot_count": snapshot_count, "architecture": architecture}
    found = blockers_for_vm(vm)
    assert len(found) == len(set(found))
    assert set(found) <= KNOWN_BLOCKERS
    assert found == blockers_for_vm(vm)  # deterministic
    if flags.get("is_encrypted"):
        assert "encrypted_vm_present" in found
    if snapshot_count > 0:
        assert "snapshots_present" in found
