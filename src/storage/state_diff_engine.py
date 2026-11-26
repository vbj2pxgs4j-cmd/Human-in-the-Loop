"""State isolation and cryptographic diff engine guaranteeing atomic single-entity mutations."""

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel

from src.config import Settings, get_settings
from src.models.audit import AuditDiffLog, PatchOperation, StateDiff

logger = logging.getLogger(__name__)


class StateIsolationError(Exception):
    """Raised when an operation mutates state outside the designated single entity boundary."""
    pass


def canonical_json_dumps(obj: Any) -> str:
    """Produce deterministic, sort-keyed JSON string representation for stable cryptographic hashing."""
    if isinstance(obj, BaseModel):
        data = obj.model_dump(mode="json")
    elif isinstance(obj, dict):
        data = obj
    else:
        raise TypeError(f"Object of type {type(obj)} cannot be canonicalized.")

    return json.dumps(data, sort_keys=True, default=str)


def compute_sha256(canonical_json: str) -> str:
    """Compute 64-character hexadecimal SHA-256 hash of canonical JSON string."""
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def capture_state(entity: Union[BaseModel, Dict[str, Any]]) -> Dict[str, Any]:
    """Capture an immutable state snapshot of an entity with its cryptographic SHA-256 hash."""
    if isinstance(entity, BaseModel):
        state_dict = entity.model_dump(mode="json")
        entity_type = entity.__class__.__name__.lower()
        # Find primary entity ID from common field conventions
        entity_id = (
            getattr(entity, "ticket_id", None)
            or getattr(entity, "explainer_id", None)
            or getattr(entity, "pulse_id", None)
            or getattr(entity, "review_id", None)
            or getattr(entity, "doc_id", None)
            or state_dict.get("id", "unknown_entity")
        )
    elif isinstance(entity, dict):
        state_dict = json.loads(json.dumps(entity, default=str))
        entity_type = state_dict.get("entity_type", "generic_entity")
        entity_id = (
            state_dict.get("ticket_id")
            or state_dict.get("explainer_id")
            or state_dict.get("pulse_id")
            or state_dict.get("review_id")
            or state_dict.get("doc_id")
            or state_dict.get("id")
            or state_dict.get("entity_id", "unknown_entity")
        )
    else:
        raise TypeError(f"Unsupported entity type for capture_state: {type(entity)}")

    canonical_str = canonical_json_dumps(state_dict)
    state_hash = compute_sha256(canonical_str)

    return {
        "entity_type": entity_type,
        "entity_id": str(entity_id),
        "state": state_dict,
        "hash": state_hash,
    }


def compute_diff(
    pre_state_dict: Dict[str, Any],
    post_state_dict: Dict[str, Any],
    prefix: str = "",
) -> List[Dict[str, Any]]:
    """Compute standard RFC 6902 JSON patch operations between two dictionary states."""
    patches: List[Dict[str, Any]] = []

    all_keys = set(pre_state_dict.keys()).union(set(post_state_dict.keys()))

    for key in sorted(all_keys):
        path = f"{prefix}/{key}"
        if key not in pre_state_dict:
            # Added field
            patches.append({"op": "add", "path": path, "value": post_state_dict[key]})
        elif key not in post_state_dict:
            # Removed field
            patches.append({"op": "remove", "path": path})
        else:
            val_pre = pre_state_dict[key]
            val_post = post_state_dict[key]

            if isinstance(val_pre, dict) and isinstance(val_post, dict):
                # Recurse into nested dictionary
                nested_patches = compute_diff(val_pre, val_post, prefix=path)
                patches.extend(nested_patches)
            elif val_pre != val_post:
                # Value modified
                patches.append({"op": "replace", "path": path, "value": val_post})

    return patches


def validate_state_isolation(
    pre_snapshot: Dict[str, Any],
    post_snapshot: Dict[str, Any],
    target_entity_id: str,
) -> StateDiff:
    """Validate that pre and post snapshots touch strictly target_entity_id without cross-entity leakage."""
    pre_id = pre_snapshot.get("entity_id")
    post_id = post_snapshot.get("entity_id")

    if pre_id != target_entity_id:
        raise StateIsolationError(
            f"Pre-state entity ID '{pre_id}' does not match target entity ID '{target_entity_id}'."
        )

    if post_id != target_entity_id:
        raise StateIsolationError(
            f"Post-state entity ID '{post_id}' does not match target entity ID '{target_entity_id}'. Cross-entity mutation detected!"
        )

    patches = compute_diff(pre_snapshot["state"], post_snapshot["state"])

    # Verify no patches attempt to modify foreign entity IDs
    for patch in patches:
        if patch.get("path") in ("/entity_id", "/ticket_id", "/explainer_id", "/pulse_id"):
            if str(patch.get("value")) != target_entity_id:
                raise StateIsolationError(
                    f"Mutation attempted to reassign identity: {patch}. Violates single-entity isolation invariant."
                )

    return StateDiff(
        entity_type=pre_snapshot.get("entity_type", "entity"),
        entity_id=target_entity_id,
        pre_state_hash=pre_snapshot["hash"],
        post_state_hash=post_snapshot["hash"],
        diff=patches,
        is_isolated=True,
    )


class AuditDiffLogger:
    """Append-only audit diff logger writing immutable mutation logs to persistent JSON storage."""

    def __init__(self, log_path: Optional[Union[str, Path]] = None, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.log_path = Path(log_path or self.settings.AUDIT_LOG_PATH)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.log_path.exists():
            self._write_records([])

    def _read_records(self) -> List[Dict[str, Any]]:
        """Read all audit entries from the append-only JSON file."""
        if not self.log_path.exists():
            return []
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    return []
                return json.loads(content)
        except Exception as e:
            logger.error("Error reading audit log from %s: %s", self.log_path, e)
            return []

    def _write_records(self, records: List[Dict[str, Any]]) -> None:
        """Write records to file atomically."""
        with open(self.log_path, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, default=str)

    def log_mutation(
        self,
        operator_id: str,
        entity_type: str,
        entity_id: str,
        action: str,
        pre_snapshot: Dict[str, Any],
        post_snapshot: Dict[str, Any],
        audit_id: Optional[str] = None,
    ) -> AuditDiffLog:
        """Validate isolation and append an immutable mutation record to the audit diff log."""
        # 1. Enforce state isolation invariant
        diff_result = validate_state_isolation(pre_snapshot, post_snapshot, entity_id)

        # 2. Build audit record
        ts = datetime.now(timezone.utc)
        record_id = audit_id or f"aud_{int(ts.timestamp() * 1000)}"

        entry = AuditDiffLog(
            audit_id=record_id,
            timestamp=ts,
            operator_id=operator_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            pre_state_hash=pre_snapshot["hash"],
            post_state_hash=post_snapshot["hash"],
            diff=diff_result.diff,
        )

        # 3. Append to log atomically
        records = self._read_records()
        records.append(entry.model_dump(mode="json"))
        self._write_records(records)

        logger.info(
            "Logged audit mutation %s: operator=%s action=%s entity=%s#%s",
            record_id, operator_id, action, entity_type, entity_id
        )
        return entry

    def get_audit_history(self, entity_id: Optional[str] = None) -> List[AuditDiffLog]:
        """Fetch audit log records, optionally filtered by target entity ID."""
        raw_records = self._read_records()
        entries = [AuditDiffLog(**r) for r in raw_records]
        if entity_id:
            entries = [e for e in entries if e.entity_id == entity_id]
        return entries

    def clear(self) -> None:
        """Clear all audit records (primarily for test resets)."""
        self._write_records([])


# Global AuditLogger singleton
_default_audit_logger: Optional[AuditDiffLogger] = None


def get_audit_logger() -> AuditDiffLogger:
    """Retrieve global singleton AuditDiffLogger."""
    global _default_audit_logger
    if _default_audit_logger is None:
        _default_audit_logger = AuditDiffLogger()
    return _default_audit_logger
