from __future__ import annotations

from typing import Literal, TypedDict

from cim.schema import CanonicalInfrastructureModel, TargetProvider

JSONValue = (
    None
    | bool
    | int
    | float
    | str
    | list["JSONValue"]
    | dict[str, "JSONValue"]
)


class QuarantineItem(TypedDict):
    compute_unit_id: str
    compute_unit_name: str
    reasons: list[str]
    stage: Literal["blocker_parser", "validator"]


class ValidationResult(TypedDict, total=False):
    passed: bool
    terraform_validate_passed: bool
    tflint_passed: bool
    opa_passed: bool
    errors: list[str]
    warnings: list[str]


class AssessmentResource(TypedDict):
    resource_type: str
    resource_id: str
    resource_name: str
    risk_level: Literal["safe", "caution", "elevated", "critical"]
    risk_score: int
    safe_to_migrate: bool
    reasons: list[str]
    missing_data: list[str]
    recommendations: list[str]


class AssessmentSummary(TypedDict):
    total_resources: int
    safe: int
    caution: int
    elevated: int
    critical: int


class AssessmentResult(TypedDict):
    generated_at: str
    source_vcenter: str
    target_provider: str
    summary: AssessmentSummary
    resources: list[AssessmentResource]


class MigrationState(TypedDict, total=False):
    discovery_data: dict[str, JSONValue]
    config: dict[str, JSONValue]
    target_provider: TargetProvider

    cim: CanonicalInfrastructureModel
    sized_cim: CanonicalInfrastructureModel
    mcp_context: str
    hcl_output: dict[str, str]
    validation_result: ValidationResult
    review_notes: str
    assessment_result: AssessmentResult

    quarantine_queue: list[QuarantineItem]
    messages: list[str]
    retry_count: int
    status: Literal["pending", "running", "succeeded", "failed"]
