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


_BARE_EXPRESSION = re.compile(r"^(?:var|local|module|data)\.[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+|\[[^\]]+\])*$")


def is_bare_expression(value: object) -> bool:
    """True when value is a Terraform reference such as var.owner that must not be quoted."""
    return bool(_BARE_EXPRESSION.match(str(value).strip()))


def hcl_string(value: object) -> str:
    """Render value as a safe HCL string literal.

    Escapes backslashes, quotes and newlines, and neutralizes `${` / `%{` so a VM name or
    annotation coming from discovery can never open a template expression.
    """
    text = str(value)
    text = text.replace("\\", "\\\\").replace('"', '\\"')
    text = text.replace("\r", "\\r").replace("\n", "\\n")
    text = text.replace("${", "$${").replace("%{", "%%{")
    return f'"{text}"'


def hcl_value(value: object) -> str:
    """Render a tag/metadata value: bare Terraform references stay bare, everything else is quoted."""
    if is_bare_expression(value):
        return str(value).strip()
    return hcl_string(value)


def hcl_map_key(value: object, fallback: str = "key") -> str:
    """Render a map key: identifiers stay bare, anything else becomes a quoted string."""
    text = str(value).strip()
    if re.match(r"^[A-Za-z_][A-Za-z0-9_-]*$", text):
        return text
    return hcl_string(text) if text else fallback
