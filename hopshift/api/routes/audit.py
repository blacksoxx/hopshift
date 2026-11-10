"""Audit log access (admin role): paged listing, chain verification and NDJSON export."""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, Iterator

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from hopshift.api.deps import Principal, get_platform, require_role
from hopshift.services.platform import Platform

router = APIRouter(tags=["audit"])


@router.get("/audit")
def list_audit(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    action: str | None = Query(default=None, max_length=80),
    actor: str | None = Query(default=None, max_length=128),
    since: str | None = Query(default=None, max_length=40),
    target_id: str | None = Query(default=None, max_length=128),
    target_type: str | None = Query(default=None, max_length=40),
    outcome: str | None = Query(default=None, max_length=20),
    platform: Platform = Depends(get_platform),
    _: Principal = Depends(require_role("admin")),
) -> dict[str, Any]:
    entries, total = platform.audit.list(
        limit=limit, offset=offset, action=action, actor=actor, since=since, target_id=target_id, target_type=target_type, outcome=outcome
    )
    return {"entries": [entry.to_dict() for entry in entries], "total": total, "limit": limit, "offset": offset}


@router.get("/audit/verify")
def verify_audit(platform: Platform = Depends(get_platform), _: Principal = Depends(require_role("admin"))) -> dict[str, Any]:
    """Recompute the hash chain; `ok` is false at the first altered or missing entry."""
    return asdict(platform.audit.verify())


@router.get("/audit/export")
def export_audit(platform: Platform = Depends(get_platform), _: Principal = Depends(require_role("admin"))) -> StreamingResponse:
    """Every entry, oldest first, one JSON object per line (evidence export for auditors)."""

    def generate() -> Iterator[str]:
        for entry in platform.audit.iter_all():
            yield json.dumps(entry.to_dict(), ensure_ascii=True, separators=(",", ":")) + "\n"

    return StreamingResponse(
        generate(), media_type="application/x-ndjson", headers={"Content-Disposition": 'attachment; filename="audit-log.ndjson"'}
    )
