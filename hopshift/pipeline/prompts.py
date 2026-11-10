from __future__ import annotations

import json

# JSON schema for the LLM's HCL output. A list of {path, content} objects instead of a
# path-keyed map, because structured-output schemas cannot express arbitrary keys.
HCL_FILES_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "files": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path under <provider>-migration/, ending in .tf"},
                    "content": {"type": "string", "description": "Complete HCL file content"},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["files"],
    "additionalProperties": False,
}

SCOPE_ALL = "all"
SCOPE_SHARED = "shared"
SCOPE_COMPUTE = "compute"


def build_hcl_system_prompt(provider: str) -> str:
    return (
        "You generate Terraform HCL only. "
        'Return exactly one JSON object of the form {"files": [{"path": "...", "content": "..."}]}. '
        "No markdown, no explanation. "
        f"Target provider: {provider}."
    )


def build_hcl_prompt_parts(
    provider: str,
    cim_json: str,
    documentation_context: str,
    validation_feedback: str,
    retry_count: int,
    required_tags: dict[str, str],
    source_vcenter: str,
    scope: str = SCOPE_ALL,
    compute_unit_ids: list[str] | None = None,
    existing_resources: list[str] | None = None,
) -> tuple[str, str]:
    """Return (stable_prefix, volatile_prompt).

    The stable prefix (requirements, full CIM, documentation) is identical for every batch
    and every retry of a run, so the client marks it cacheable. The volatile part carries
    the batch scope, the attempt index and the validation feedback.
    """
    root_dir = f"{provider}-migration"
    structure = (
        "{root_dir}/main.tf\n"
        "{root_dir}/networking/vpc.tf\n"
        "{root_dir}/networking/subnets.tf\n"
        "{root_dir}/networking/security_groups.tf\n"
        "{root_dir}/placement/placement_groups.tf\n"
        "{root_dir}/compute/{compute_unit_name}.tf\n"
        "{root_dir}/storage/{compute_unit_name}_disks.tf"
    ).replace("{root_dir}", root_dir)

    stable = (
        "Generate production-ready Terraform HCL for the given CIM.\n\n"
        "Hard requirements:\n"
        '1. Return a JSON object {"files": [{"path": "...", "content": "..."}]} and nothing else.\n'
        "2. Paths must follow this structure:\n"
        f"{structure}\n"
        "3. Every resource must include tags: "
        f"{json.dumps(required_tags, ensure_ascii=True)}\n"
        "4. Never generate public S3 ACLs, never generate ingress cidr_blocks with 0.0.0.0/0.\n"
        "5. Never use default VPC; always define explicit network resources.\n"
        "6. Preserve 1:1 NetworkTopology mapping (DistributedSwitch to VPC/VNet/Network, PortGroup to subnet).\n"
        "7. If a ComputeUnit has has_vtpm=true, add TODO comment in HCL for manual review.\n"
        "8. Keep ComputeUnit vcpus and ram_mb unchanged from CIM; use only provided sizing decisions.\n"
        f"9. Source vCenter for tags/context: {source_vcenter}.\n"
        "10. Never emit provisioner blocks, external or http data sources, null_resource, local_file, "
        "remote module sources, or providers other than the target cloud's.\n"
        f"11. {root_dir}/main.tf must be a complete runnable root module for terraform init/validate/plan.\n"
        "12. Do not assume files in subdirectories are loaded together as one module.\n"
        "13. If using local.common_tags in a file, declare it in that same file or pass it via module inputs.\n"
        "14. Do not output informational/comment-only Terraform files for compute/networking when ComputeUnits are present.\n"
        "15. Generated HCL must include concrete resource blocks needed to run terraform plan.\n\n"
        f"{_provider_hcl_constraints(provider)}"
        "CIM JSON (complete inventory for context):\n"
        f"{cim_json}\n\n"
        "MCP Documentation Context:\n"
        f"{documentation_context}\n"
    )

    volatile = (
        f"{_scope_instruction(scope, compute_unit_ids, existing_resources)}\n"
        f"This is retry attempt index: {retry_count}. Fix prior validation issues if provided.\n\n"
        "Validation Feedback:\n"
        f"{validation_feedback}\n"
    )
    return stable, volatile


def build_hcl_user_prompt(
    provider: str,
    cim_json: str,
    documentation_context: str,
    validation_feedback: str,
    retry_count: int,
    required_tags: dict[str, str],
    source_vcenter: str,
    scope: str = SCOPE_ALL,
    compute_unit_ids: list[str] | None = None,
    existing_resources: list[str] | None = None,
) -> str:
    """Single-string form of build_hcl_prompt_parts for clients without a cacheable prefix."""
    stable, volatile = build_hcl_prompt_parts(
        provider=provider,
        cim_json=cim_json,
        documentation_context=documentation_context,
        validation_feedback=validation_feedback,
        retry_count=retry_count,
        required_tags=required_tags,
        source_vcenter=source_vcenter,
        scope=scope,
        compute_unit_ids=compute_unit_ids,
        existing_resources=existing_resources,
    )
    return f"{stable}\n{volatile}"


def _scope_instruction(scope: str, compute_unit_ids: list[str] | None, existing_resources: list[str] | None) -> str:
    if scope == SCOPE_SHARED:
        return (
            "Scope for this response: ONLY the shared files - main.tf, networking/*.tf and placement/*.tf. "
            "Do not emit any compute/ or storage/ files."
        )
    if scope == SCOPE_COMPUTE:
        ids = ", ".join(compute_unit_ids or [])
        existing = "\n".join(f"- {address}" for address in (existing_resources or [])) or "- (none)"
        return (
            "Scope for this response: ONLY compute/ and storage/ files for these ComputeUnit ids: "
            f"{ids}. Do not emit main.tf, networking or placement files and do not redefine any of these "
            f"resources, which already exist and may be referenced by address:\n{existing}"
        )
    return "Scope for this response: all files for the complete CIM."


def _provider_hcl_constraints(provider: str) -> str:
    normalized_provider = provider.strip().lower()
    if normalized_provider != "gcp":
        return ""

    return (
        "Provider-specific constraints (GCP):\n"
        "16. Never use deprecated CentOS 7 image references (for example centos-cloud/centos-7).\n"
        "17. GCP label keys must be lowercase snake_case (for example environment, owner, migrated_from).\n\n"
    )


def build_report_system_prompt() -> str:
    return (
        "Write concise migration review notes in markdown. "
        "Include: summary, blockers/quarantine with the reason and a recommended remediation for each, "
        "validation outcomes, and next actions. Do not invent facts that are not in the run data."
    )


def build_report_user_prompt(summary_payload: dict[str, object]) -> str:
    return (
        "Generate review notes for this hopshift run. "
        "Be precise and concise.\n\n"
        "Run data (JSON):\n"
        f"{json.dumps(summary_payload, indent=2, ensure_ascii=True)}"
    )
