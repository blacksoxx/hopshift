"""support.yaml -> docs/support-matrix.md: the committed document is current, names are
cross-checked against the registries, commented rows are tolerated and surfaced as hints."""
from __future__ import annotations

from pathlib import Path

import pytest

from hopshift.testing import matrix

GOOD = """
pairs:
  - source: vmware
    target: openstack
    tier: experimental
    evidence: local lab
    notes: with | a pipe
"""


def test_committed_support_matrix_document_is_current() -> None:
    assert matrix.check() == [], "run `hopshift matrix render` and commit docs/support-matrix.md"


def test_support_yaml_declares_the_validated_vmware_pairs() -> None:
    loaded = matrix.load()

    assert {(pair.source, pair.target): pair.tier for pair in loaded.pairs} == {
        ("vmware", "aws"): "validated",
        ("vmware", "azure"): "validated",
        ("vmware", "gcp"): "validated",
        ("vmware", "openstack"): "validated",
        ("vmware", "proxmox"): "validated",
    }
    assert all(pair.evidence for pair in loaded.pairs)


def test_unknown_names_bad_tier_duplicates_and_extra_keys_fail(tmp_path: Path) -> None:
    support = tmp_path / "support.yaml"
    support.write_text(
        """
pairs:
  - source: vmware
    target: nimbus
    tier: validated
  - source: hyperv
    target: aws
    tier: gold
    colour: blue
  - source: vmware
    target: aws
    tier: tested
  - source: vmware
    target: aws
    tier: tested
  - target: aws
""",
        encoding="utf-8",
    )

    with pytest.raises(matrix.SupportMatrixError) as excinfo:
        matrix.load(support)

    message = str(excinfo.value)
    assert "unknown target 'nimbus'" in message
    assert "unknown source 'hyperv'" in message
    assert "tier 'gold'" in message
    assert "unexpected keys colour" in message
    assert "duplicate pair vmware -> aws" in message
    assert "pairs[4]: missing source, tier" in message


def test_malformed_file_fails(tmp_path: Path) -> None:
    support = tmp_path / "support.yaml"
    support.write_text("pairs: not-a-list\n", encoding="utf-8")
    with pytest.raises(matrix.SupportMatrixError, match="`pairs` list"):
        matrix.load(support)
    with pytest.raises(matrix.SupportMatrixError, match="does not exist"):
        matrix.load(tmp_path / "nope.yaml")


def test_commented_rows_are_tolerated_and_listed_as_pending(tmp_path: Path) -> None:
    support = tmp_path / "support.yaml"
    support.write_text(
        GOOD
        + """
  # Nimbus is being built in parallel.
  # - source: vmware
  #   target: nimbus
  #   tier: experimental
  #   notes: "pending registration"
""",
        encoding="utf-8",
    )

    loaded = matrix.load(support)
    pending = matrix.pending_pairs(support)

    assert [(pair.source, pair.target) for pair in loaded.pairs] == [("vmware", "openstack")]
    assert [(pair.source, pair.target, pair.tier, pair.notes) for pair in pending] == [("vmware", "nimbus", "experimental", "pending registration")]
    assert matrix.hints(support) == []  # nimbus is not registered, so no hint
    assert matrix.pending_pairs(matrix.SUPPORT_FILE) == []  # every built-in target has a real row


def test_hint_when_a_commented_pair_becomes_registered(tmp_path: Path) -> None:
    support = tmp_path / "support.yaml"
    support.write_text(GOOD + "  # - source: vmware\n  #   target: aws\n  #   tier: experimental\n", encoding="utf-8")

    hints = matrix.hints(support)

    assert len(hints) == 1 and "vmware -> aws" in hints[0] and "uncomment" in hints[0]


def test_render_has_legend_badges_grid_and_escaped_cells(tmp_path: Path) -> None:
    support = tmp_path / "support.yaml"
    support.write_text(GOOD, encoding="utf-8")

    document = matrix.render(matrix.load(support))

    assert matrix.GENERATED_MARKER in document
    for tier in matrix.TIERS:
        assert matrix.badge(tier) in document
        assert matrix.LEGEND[tier] in document
    assert "| Source \\ Target | `aws` | `azure` | `gcp` | `openstack` |" in document
    assert "| `vmware` | - | - | - | ![experimental]" in document
    assert "with \\| a pipe" in document


def test_write_and_check_detect_a_stale_document(tmp_path: Path) -> None:
    support = tmp_path / "support.yaml"
    support.write_text(GOOD, encoding="utf-8")
    document = tmp_path / "docs" / "support-matrix.md"

    assert matrix.check(document, support) == [f"{document} is missing; run `hopshift matrix render`"]
    written = matrix.write(document, support)
    assert written == document and matrix.check(document, support) == []

    document.write_text(document.read_text(encoding="utf-8") + "\nedited by hand\n", encoding="utf-8")
    assert matrix.check(document, support) == [f"{document} is stale; run `hopshift matrix render`"]

    support.write_text(GOOD.replace("target: openstack", "target: nimbus"), encoding="utf-8")
    problems = matrix.check(document, support)
    assert len(problems) == 1 and "unknown target 'nimbus'" in problems[0]
