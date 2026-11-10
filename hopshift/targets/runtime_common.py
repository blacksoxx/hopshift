from __future__ import annotations

from hopshift.targets.common import hcl_string, is_bare_expression


def variable_block(
    name: str,
    type_: str,
    description: str,
    default: object | None = None,
    sensitive: bool = False,
) -> str:
    """Render a multi-line variable block. default=None means the variable is required."""
    lines = [f'variable "{name}" {{']
    lines.append(f"  type        = {type_}")
    lines.append(f"  description = {hcl_string(description)}")
    if default is not None:
        lines.append(f"  default     = {_default_literal(default)}")
    if sensitive:
        lines.append("  sensitive   = true")
    lines.append("}")
    return "\n".join(lines) + "\n"


def tag_variable_blocks(environment_default: str, owner_default: str) -> str:
    return "".join(
        [
            variable_block("environment", "string", "Environment tag applied to every resource.", environment_default),
            "\n",
            variable_block("owner", "string", "Owner tag applied to every resource.", owner_default),
        ]
    )


def literal_default(value: object | None, fallback: str) -> str:
    """Use the tag value as a variable default unless it is itself a Terraform reference."""
    text = str(value).strip() if value is not None else ""
    if not text or is_bare_expression(text):
        return fallback
    return text


def image_overrides_block(description: str) -> str:
    return variable_block("image_overrides", "map(string)", description, {})


def _default_literal(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        if not value:
            return "{}"
        inner = "\n".join(f"    {key} = {hcl_string(val)}" for key, val in value.items())
        return "{\n" + inner + "\n  }"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(hcl_string(item) for item in value) + "]"
    return hcl_string(value)
