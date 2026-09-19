from __future__ import annotations

import pytest

from validation.paths import UnsafePathError, ensure_safe_relative_path


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("aws-migration/main.tf", "aws-migration/main.tf"),
        ("aws-migration\\compute\\app.tf", "aws-migration/compute/app.tf"),
        ("  aws-migration/storage/x.tf  ", "aws-migration/storage/x.tf"),
        ("aws-migration//compute/app.tf", "aws-migration/compute/app.tf"),
    ],
)
def test_accepts_and_normalizes_relative_paths(raw: str, expected: str) -> None:
    assert ensure_safe_relative_path(raw).as_posix() == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "/etc/passwd",
        "C:\\Windows\\x.tf",
        "aws-migration/../../escape.tf",
        "..",
        "aws-migration\\..\\..\\escape.tf",
        "aws-migration/compute/x.tf\x00.txt",
    ],
)
def test_rejects_unsafe_paths(raw: str) -> None:
    with pytest.raises(UnsafePathError):
        ensure_safe_relative_path(raw)


def test_unsafe_path_error_is_a_value_error() -> None:
    assert issubclass(UnsafePathError, ValueError)
