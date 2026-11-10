from __future__ import annotations

import re
from pathlib import PurePosixPath

_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")


class UnsafePathError(ValueError):
    """Raised when a generated output path could escape its output root."""


def ensure_safe_relative_path(raw: object) -> PurePosixPath:
    """Return a normalized relative POSIX path or raise UnsafePathError.

    Rejects empty paths, NUL bytes, absolute paths (POSIX or Windows drive), and any
    `..` segment. Backslashes are treated as separators so Windows-style output from an
    LLM is normalized rather than smuggled through as a single file name.
    """
    text = str(raw).strip().replace("\\", "/")
    if not text:
        raise UnsafePathError("output path is empty")
    if "\x00" in text:
        raise UnsafePathError("output path contains a NUL byte")
    if text.startswith("/") or _WINDOWS_DRIVE.match(text):
        raise UnsafePathError(f"absolute output path is not allowed: {raw!s}")

    path = PurePosixPath(text)
    if not path.parts:
        raise UnsafePathError("output path is empty")
    if any(part == ".." for part in path.parts):
        raise UnsafePathError(f"output path traversal is not allowed: {raw!s}")

    return path
