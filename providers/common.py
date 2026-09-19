from __future__ import annotations

import re

_UNSAFE_STEM_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_STEM_LENGTH = 100


def safe_file_stem(name: object, fallback: str = "resource") -> str:
    """Turn a VMware object name into a safe file-name stem.

    Discovery names are attacker-influenced input (VM names, port groups). Anything that
    is not alphanumeric, dot, underscore, or dash becomes an underscore, and leading
    dots/dashes are stripped so the result can never be a hidden file, a traversal
    segment, or a path containing separators.
    """
    text = _UNSAFE_STEM_CHARS.sub("_", str(name).strip())
    text = re.sub(r"_+", "_", text).strip("._-")
    if not text:
        return fallback
    return text[:_MAX_STEM_LENGTH]
