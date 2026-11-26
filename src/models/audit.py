"""Audit and State Isolation models: AuditDiffLog, StateDiff, and PatchOperation."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class PatchOperation(BaseModel):
    """RFC 6902 compliant JSON patch operation descriptor."""

    op: str = Field(..., description="Operation type: add, remove, replace, move, copy, test")
    path: str = Field(..., description="Target JSON pointer path within the entity object")
    value: Optional[Any] = Field(default=None, description="New value for add or replace operations")
    from_path: Optional[str] = Field(default=None, description="Source path for move or copy operations")


class AuditDiffLog(BaseModel):
    """Immutable audit entry recording a human or system mutation with cryptographic diff."""

    audit_id: str = Field(..., description="Unique audit record identifier, e.g. aud_8492049")
    timestamp: datetime = Field(..., description="ISO timestamp when mutation occurred")
    operator_id: str = Field(..., description="Operator user ID or system identifier")
    entity_type: str = Field(..., description="Entity category: ticket, explainer, pulse")
    entity_id: str = Field(..., description="Target entity ID mutated")
    action: str = Field(..., description="Action performed: APPROVE, EDIT_AND_APPROVE, REJECT")
    pre_state_hash: str = Field(..., min_length=64, max_length=64, description="SHA-256 hash of pre-mutation state")
    post_state_hash: str = Field(..., min_length=64, max_length=64, description="SHA-256 hash of post-mutation state")
    diff: List[Dict[str, Any]] = Field(..., description="Standard RFC 6902 JSON patch list")


class StateDiff(BaseModel):
    """Computed state difference between two entity snapshots validating isolation."""

    entity_type: str = Field(..., description="Entity type evaluated")
    entity_id: str = Field(..., description="Entity ID evaluated")
    pre_state_hash: str = Field(..., description="SHA-256 hash of pre-state")
    post_state_hash: str = Field(..., description="SHA-256 hash of post-state")
    diff: List[Dict[str, Any]] = Field(default_factory=list, description="Computed RFC 6902 patch operations")
    is_isolated: bool = Field(
        default=True,
        description="True if diff touches exclusively target entity and no adjacent state",
    )
