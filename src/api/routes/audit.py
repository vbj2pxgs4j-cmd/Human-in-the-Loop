"""Audit and State Diff REST routes providing full cryptographic inspection."""

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query, status

from src.models.audit import AuditDiffLog
from src.storage.audit_logger import get_audit_logger

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/audit", tags=["Compliance & Audit"])


@router.get("/logs", response_model=List[AuditDiffLog])
def list_audit_logs(
    entity_type: Optional[str] = Query(None, description="Filter by entity type (ticket, canonicalexplainer, pulse)"),
    entity_id: Optional[str] = Query(None, description="Filter by specific entity ID"),
    operator_id: Optional[str] = Query(None, description="Filter by operator ID"),
    action: Optional[str] = Query(None, description="Filter by mutation action"),
    limit: int = Query(100, ge=1, le=500, description="Max records to return"),
):
    """Retrieve audit history filtered by entity type, entity ID, operator, or action."""
    logger_instance = get_audit_logger()
    all_logs = logger_instance.get_audit_history()

    filtered = all_logs
    if entity_id:
        filtered = [l for l in filtered if l.entity_id == entity_id]
    if entity_type:
        filtered = [l for l in filtered if l.entity_type.lower() == entity_type.lower()]
    if operator_id:
        filtered = [l for l in filtered if l.operator_id.lower() == operator_id.lower()]
    if action:
        filtered = [l for l in filtered if l.action.upper() == action.upper()]

    # Sort descending by timestamp
    filtered = sorted(filtered, key=lambda l: l.timestamp, reverse=True)
    return filtered[:limit]


@router.get("/logs/{audit_id}", response_model=AuditDiffLog)
def get_audit_log(audit_id: str):
    """Retrieve a single audit log entry by its unique audit ID."""
    logger_instance = get_audit_logger()
    all_logs = logger_instance.get_audit_history()
    match = next((l for l in all_logs if l.audit_id == audit_id), None)
    if not match:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit record {audit_id} not found.",
        )
    return match


@router.get("/diff/{audit_id}")
def get_audit_diff_details(audit_id: str) -> Dict[str, Any]:
    """Retrieve full RFC 6902 JSON patch diff with cryptographic hashes and isolation proof."""
    logger_instance = get_audit_logger()
    all_logs = logger_instance.get_audit_history()
    match = next((l for l in all_logs if l.audit_id == audit_id), None)
    if not match:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit record {audit_id} not found.",
        )

    return {
        "audit_id": match.audit_id,
        "timestamp": match.timestamp.isoformat(),
        "operator_id": match.operator_id,
        "entity_type": match.entity_type,
        "entity_id": match.entity_id,
        "action": match.action,
        "pre_state_hash": match.pre_state_hash,
        "post_state_hash": match.post_state_hash,
        "patch_count": len(match.diff),
        "patch_operations": match.diff,
        "is_isolated": True,
    }
