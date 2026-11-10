from __future__ import annotations

from datetime import datetime, timezone
from typing import cast

from loguru import logger

from hopshift.pipeline.state import AssessmentResource, AssessmentResult, MigrationState


def risk_assessor(state: MigrationState) -> MigrationState:
    """Build deterministic per-resource migration risk assessment."""
    next_state = cast(MigrationState, dict(state))

    discovery_data = next_state.get("discovery_data", {})
    if not isinstance(discovery_data, dict):
        raise ValueError("risk_assessor: discovery_data must be a mapping")

    cim = next_state.get("cim")
    if cim is None:
        raise ValueError("risk_assessor: cim must be present before assessment")

    resources: list[AssessmentResource] = []

    resources.extend(_assess_compute_units(cim))
    resources.extend(_assess_network_topology(cim))
    resources.extend(_assess_clusters(cim))
    resources.extend(_assess_generic_resources(discovery_data))

    summary = _summarize(resources)
    result: AssessmentResult = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_vcenter": cim.source_vcenter,
        "target_provider": cim.target_provider.value,
        "summary": summary,
        "resources": resources,
    }

    messages = list(next_state.get("messages", []))
    messages.append(
        "risk_assessor: assessed_resources={} safe={} caution={} elevated={} critical={}".format(
            summary["total_resources"],
            summary["safe"],
            summary["caution"],
            summary["elevated"],
            summary["critical"],
        )
    )

    next_state["assessment_result"] = result
    next_state["messages"] = messages
    next_state["status"] = "running"

    logger.info(
        "risk_assessor: assessed {} resources for provider {}",
        len(resources),
        cim.target_provider.value,
    )

    return next_state


def _assess_compute_units(cim: object) -> list[AssessmentResource]:
    resources: list[AssessmentResource] = []

    for compute_unit in cim.compute_units:
        reasons: list[str] = []
        missing_data: list[str] = []
        recommendations: list[str] = []

        score = 0

        if not compute_unit.id:
            missing_data.append("missing compute_unit.id")
            score += 20

        if not compute_unit.name:
            missing_data.append("missing compute_unit.name")
            score += 20

        if compute_unit.vcpus <= 0:
            missing_data.append("invalid vcpus")
            score += 20

        if compute_unit.ram_mb <= 0:
            missing_data.append("invalid ram_mb")
            score += 20

        if compute_unit.is_encrypted:
            reasons.append("encrypted VM cannot be migrated directly")
            recommendations.append("decrypt VM or define encrypted target workload migration plan")
            score += 80

        if compute_unit.blockers:
            reasons.append("migration blockers present: {}".format(", ".join(compute_unit.blockers)))
            recommendations.append("resolve blockers before migration")
            score += 50

        if compute_unit.migration_status.value == "needs_review" and not compute_unit.has_vtpm:
            reasons.append("marked needs_review by the translator")
            score += 15

        if compute_unit.has_vtpm:
            reasons.append("vTPM present; requires manual compatibility validation")
            recommendations.append("validate target cloud vTPM behavior and guest OS requirements")
            score += 25

        if not compute_unit.cluster_ref:
            reasons.append("no cluster assignment (standalone host or cluster not discovered)")
            recommendations.append("confirm whether HA/anti-affinity placement is required in the target cloud")
            score += 5

        risk_score = min(score, 100)
        risk_level = _risk_level_from_score(risk_score)

        resources.append(
            _make_resource(
                resource_type="vm",
                resource_id=str(compute_unit.id),
                resource_name=str(compute_unit.name),
                risk_level=risk_level,
                risk_score=risk_score,
                reasons=reasons,
                missing_data=missing_data,
                recommendations=recommendations,
            )
        )

        resources.extend(_assess_compute_unit_disks(compute_unit))
        resources.extend(_assess_compute_unit_nics(compute_unit))

    return resources


def _assess_compute_unit_disks(compute_unit: object) -> list[AssessmentResource]:
    resources: list[AssessmentResource] = []

    if not compute_unit.storage_volumes:
        resources.append(
            _make_resource(
                resource_type="disk",
                resource_id=f"{compute_unit.id}:none",
                resource_name=f"{compute_unit.name}::no-disks",
                risk_level="caution",
                risk_score=25,
                reasons=["no storage volumes discovered"],
                missing_data=["missing storage volume inventory"],
                recommendations=["verify disk inventory and datastore mapping before migration"],
            )
        )
        return resources

    for disk in compute_unit.storage_volumes:
        reasons: list[str] = []
        missing_data: list[str] = []
        recommendations: list[str] = []
        score = 0

        if not disk.id:
            missing_data.append("missing disk id")
            score += 20

        if disk.size_gb <= 0:
            missing_data.append("invalid disk size_gb")
            score += 20

        if not disk.datastore:
            missing_data.append("missing datastore")
            score += 15

        if disk.is_encrypted:
            reasons.append("encrypted disk requires encryption-aware migration path")
            recommendations.append("ensure target storage encryption and key management mapping")
            score += 35

        if disk.is_rdm:
            reasons.append("RDM disk detected")
            recommendations.append("replace RDM dependency with supported virtual disk strategy")
            score += 70

        if disk.is_shared:
            reasons.append("shared disk detected")
            recommendations.append("validate multi-attach semantics in target provider")
            score += 50

        if disk.thin_provisioned is True:
            reasons.append("thin provisioned disk may have performance variance")
            recommendations.append("validate capacity/performance policy for target disk type")
            score += 10

        risk_score = min(score, 100)
        resources.append(
            _make_resource(
                resource_type="disk",
                resource_id=f"{compute_unit.id}:{disk.id}",
                resource_name=f"{compute_unit.name}::{disk.id}",
                risk_level=_risk_level_from_score(risk_score),
                risk_score=risk_score,
                reasons=reasons,
                missing_data=missing_data,
                recommendations=recommendations,
            )
        )

    return resources


def _assess_compute_unit_nics(compute_unit: object) -> list[AssessmentResource]:
    resources: list[AssessmentResource] = []

    if not compute_unit.nics:
        resources.append(
            _make_resource(
                resource_type="network_interface",
                resource_id=f"{compute_unit.id}:none",
                resource_name=f"{compute_unit.name}::no-nics",
                risk_level="elevated",
                risk_score=45,
                reasons=["no NIC discovered"],
                missing_data=["missing network interface inventory"],
                recommendations=["verify VM network adapter inventory and mapping"],
            )
        )
        return resources

    for nic in compute_unit.nics:
        reasons: list[str] = []
        missing_data: list[str] = []
        recommendations: list[str] = []
        score = 0

        if not nic.name:
            missing_data.append("missing nic name")
            score += 15

        if not nic.port_group_ref:
            missing_data.append("missing port_group_ref")
            score += 25
            recommendations.append("map NIC to a valid target subnet or network")

        if not nic.mac_address:
            missing_data.append("missing mac_address")
            score += 5

        risk_score = min(score, 100)
        resources.append(
            _make_resource(
                resource_type="network_interface",
                resource_id=f"{compute_unit.id}:{nic.name or 'nic'}",
                resource_name=f"{compute_unit.name}::{nic.name or 'nic'}",
                risk_level=_risk_level_from_score(risk_score),
                risk_score=risk_score,
                reasons=reasons,
                missing_data=missing_data,
                recommendations=recommendations,
            )
        )

    return resources


def _assess_network_topology(cim: object) -> list[AssessmentResource]:
    resources: list[AssessmentResource] = []

    for switch in cim.network_topology.distributed_switches:
        score = 0
        reasons: list[str] = []
        missing_data: list[str] = []
        recommendations: list[str] = []

        if not switch.name:
            missing_data.append("missing distributed switch name")
            score += 20

        if not switch.port_groups:
            reasons.append("switch has no port groups")
            score += 15
            recommendations.append("verify network topology discovery completeness")

        resources.append(
            _make_resource(
                resource_type="network_switch",
                resource_id=str(switch.name),
                resource_name=str(switch.name),
                risk_level=_risk_level_from_score(min(score, 100)),
                risk_score=min(score, 100),
                reasons=reasons,
                missing_data=missing_data,
                recommendations=recommendations,
            )
        )

        for port_group in switch.port_groups:
            pg_score = 0
            pg_reasons: list[str] = []
            pg_missing: list[str] = []
            pg_recs: list[str] = []

            if not port_group.name:
                pg_missing.append("missing port group name")
                pg_score += 20

            if not port_group.vlan_id:
                pg_missing.append("missing vlan_id")
                pg_score += 20
                pg_recs.append("map port group to a target subnet and VLAN policy")

            resources.append(
                _make_resource(
                    resource_type="subnet",
                    resource_id=f"{switch.name}:{port_group.name}",
                    resource_name=str(port_group.name),
                    risk_level=_risk_level_from_score(min(pg_score, 100)),
                    risk_score=min(pg_score, 100),
                    reasons=pg_reasons,
                    missing_data=pg_missing,
                    recommendations=pg_recs,
                )
            )

    return resources


def _assess_clusters(cim: object) -> list[AssessmentResource]:
    resources: list[AssessmentResource] = []

    for cluster in cim.clusters:
        reasons: list[str] = []
        missing_data: list[str] = []
        recommendations: list[str] = []
        score = 0

        if not cluster.name:
            missing_data.append("missing cluster name")
            score += 20

        semantics = str(cluster.semantics.value)
        if semantics == "unknown":
            reasons.append("cluster semantics unknown")
            recommendations.append("classify affinity/anti-affinity semantics before migration")
            score += 15

        resources.append(
            _make_resource(
                resource_type="cluster",
                resource_id=str(cluster.name),
                resource_name=str(cluster.name),
                risk_level=_risk_level_from_score(min(score, 100)),
                risk_score=min(score, 100),
                reasons=reasons,
                missing_data=missing_data,
                recommendations=recommendations,
            )
        )

    return resources


def _assess_generic_resources(discovery_data: dict[str, object]) -> list[AssessmentResource]:
    resources: list[AssessmentResource] = []

    for collection_name, value in discovery_data.items():
        if collection_name in {"metadata", "virtual_machines"}:
            continue
        if not isinstance(value, list):
            continue

        for index, item in enumerate(value, start=1):
            if not isinstance(item, dict):
                continue

            resource_id = _first_non_empty(item, ["id", "uuid", "moid", "discovery_key", "name"]) or str(index)
            resource_name = _first_non_empty(item, ["name", "display_name", "resource_name", "id"]) or f"{collection_name}-{index}"

            reasons: list[str] = []
            missing_data: list[str] = []
            recommendations: list[str] = []
            score = 0

            if "id" not in item and "uuid" not in item and "name" not in item:
                missing_data.append("missing id/name fields")
                score += 20

            if bool(item.get("migration_blocked")):
                reasons.append("resource is marked migration_blocked")
                recommendations.append("resolve blocking state before migration")
                score += 50

            if bool(item.get("is_encrypted") or item.get("encrypted")):
                reasons.append("resource indicates encryption")
                recommendations.append("validate encryption compatibility and key handling")
                score += 25

            if bool(item.get("has_shared_disks") or item.get("shared")):
                reasons.append("shared dependency detected")
                recommendations.append("validate shared-resource support in target platform")
                score += 25

            if bool(item.get("has_rdm_disks") or item.get("rdm")):
                reasons.append("RDM-like dependency detected")
                recommendations.append("replace unsupported raw mapping strategy")
                score += 30

            risk_score = min(score, 100)
            resources.append(
                _make_resource(
                    resource_type=_singularize(collection_name),
                    resource_id=str(resource_id),
                    resource_name=str(resource_name),
                    risk_level=_risk_level_from_score(risk_score),
                    risk_score=risk_score,
                    reasons=reasons,
                    missing_data=missing_data,
                    recommendations=recommendations,
                )
            )

    return resources


def _first_non_empty(item: dict[str, object], keys: list[str]) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _singularize(name: str) -> str:
    normalized = str(name).strip().lower()
    if normalized.endswith("ies") and len(normalized) > 3:
        return normalized[:-3] + "y"
    if normalized.endswith("s") and len(normalized) > 1:
        return normalized[:-1]
    return normalized or "resource"


def _make_resource(
    resource_type: str,
    resource_id: str,
    resource_name: str,
    risk_level: str,
    risk_score: int,
    reasons: list[str],
    missing_data: list[str],
    recommendations: list[str],
) -> AssessmentResource:
    normalized_reasons = reasons if reasons else ["no explicit migration risk detected"]
    normalized_recommendations = recommendations if recommendations else ["no action required"]

    return {
        "resource_type": resource_type,
        "resource_id": resource_id,
        "resource_name": resource_name,
        "risk_level": cast(str, risk_level),
        "risk_score": risk_score,
        "safe_to_migrate": risk_level in {"safe", "caution"},
        "reasons": normalized_reasons,
        "missing_data": missing_data,
        "recommendations": normalized_recommendations,
    }


def _risk_level_from_score(score: int) -> str:
    if score <= 20:
        return "safe"
    if score <= 45:
        return "caution"
    if score <= 70:
        return "elevated"
    return "critical"


def _summarize(resources: list[AssessmentResource]) -> dict[str, int]:
    summary = {
        "total_resources": len(resources),
        "safe": 0,
        "caution": 0,
        "elevated": 0,
        "critical": 0,
    }

    for resource in resources:
        level = resource["risk_level"]
        if level in summary:
            summary[level] += 1

    return summary
