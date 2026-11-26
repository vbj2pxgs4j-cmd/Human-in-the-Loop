"""Product Intelligence API routes: weekly pulse, theme clusters, and canonical explainers."""

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from src.agents.weekly.scheduler import get_weekly_scheduler
from src.bridge.canonical_store import get_canonical_store
from src.config import get_settings
from src.models.explainer import CanonicalExplainer
from src.models.review import ThemeCluster, WeeklyPulse
from src.storage.audit_logger import get_audit_logger
from src.storage.product_store import get_product_store
from src.storage.state_diff_engine import capture_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/product", tags=["Product Intelligence"])


# ------------------------------------------------------------------------------
# Request / Response Schemas
# ------------------------------------------------------------------------------

class ApproveExplainerRequest(BaseModel):
    """Payload for approving an explainer into canonical store."""
    approved_by: Optional[str] = Field(default="product_manager", description="Approving operator ID")
    pre_state_hash: Optional[str] = Field(default=None, description="Pre-state hash for concurrency check")


class InvalidateExplainerRequest(BaseModel):
    """Payload for invalidating/archiving a canonical explainer."""
    operator_id: Optional[str] = Field(default="product_manager", description="Operator ID")
    pre_state_hash: Optional[str] = Field(default=None, description="Pre-state hash for concurrency check")


class PulseRunRequest(BaseModel):
    """Optional configuration for triggering a fresh weekly pulse run."""
    week_identifier: Optional[str] = Field(default=None, description="Target ISO week identifier, e.g. 2026-W47")


# ------------------------------------------------------------------------------
# Product Endpoints
# ------------------------------------------------------------------------------

@router.get("/pulse", response_model=Optional[WeeklyPulse])
def get_latest_pulse():
    """Retrieve the latest unattended Weekly Pulse."""
    store = get_product_store()
    pulse = store.get_latest_pulse()
    if not pulse:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No Weekly Pulse generated yet. Trigger a run via POST /api/product/pulse/run.",
        )
    return pulse


@router.get("/themes", response_model=List[ThemeCluster])
def list_themes():
    """List customer review theme clusters with quote lineage and review IDs."""
    store = get_product_store()
    return store.list_themes()


@router.get("/explainers", response_model=List[CanonicalExplainer])
def list_explainers():
    """List all Canonical Fee Explainers (both draft and approved)."""
    canonical_store = get_canonical_store()
    return canonical_store.list_all_explainers()


@router.get("/explainers/{explainer_id}", response_model=CanonicalExplainer)
def get_explainer(explainer_id: str):
    """Retrieve details of a single canonical explainer."""
    canonical_store = get_canonical_store()
    explainer = canonical_store.get_explainer(explainer_id)
    if not explainer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Canonical Explainer {explainer_id} not found.",
        )
    return explainer


@router.post("/explainers/{explainer_id}/approve", response_model=CanonicalExplainer)
def approve_explainer(explainer_id: str, req: ApproveExplainerRequest):
    """1-click approve an explainer into canonical store (EC-HITL-02, EC-HITL-03)."""
    canonical_store = get_canonical_store()
    explainer = canonical_store.get_explainer(explainer_id)
    if not explainer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Explainer {explainer_id} not found.",
        )

    pre_snapshot = capture_state(explainer)

    # EC-HITL-02 concurrency check
    if req.pre_state_hash and req.pre_state_hash != pre_snapshot["hash"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Explainer has already been modified by another operator. Refreshing view.",
        )

    approved = canonical_store.approve_explainer(
        explainer_id=explainer_id,
        approved_by=req.approved_by or "product_manager",
    )
    if not approved:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to approve explainer {explainer_id}.",
        )

    post_snapshot = capture_state(approved)

    # EC-HITL-03: Log mutation and verify single-entity isolation
    audit_logger = get_audit_logger()
    audit_logger.log_mutation(
        operator_id=req.approved_by or "product_manager",
        entity_type="canonicalexplainer",
        entity_id=explainer_id,
        action="APPROVE_EXPLAINER",
        pre_snapshot=pre_snapshot,
        post_snapshot=post_snapshot,
    )

    return approved


@router.post("/explainers/{explainer_id}/invalidate", response_model=CanonicalExplainer)
def invalidate_explainer(explainer_id: str, req: InvalidateExplainerRequest):
    """Admin invalidate a canonical explainer (EC-BRID-01, EC-HITL-03)."""
    canonical_store = get_canonical_store()
    explainer = canonical_store.get_explainer(explainer_id)
    if not explainer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Explainer {explainer_id} not found.",
        )

    pre_snapshot = capture_state(explainer)

    # EC-HITL-02 concurrency check
    if req.pre_state_hash and req.pre_state_hash != pre_snapshot["hash"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Explainer has already been modified by another operator. Refreshing view.",
        )

    ok = canonical_store.invalidate_explainer(explainer_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to invalidate explainer {explainer_id}.",
        )

    updated = canonical_store.get_explainer(explainer_id)
    post_snapshot = capture_state(updated)

    # EC-HITL-03: Log mutation and verify single-entity isolation
    audit_logger = get_audit_logger()
    audit_logger.log_mutation(
        operator_id=req.operator_id or "product_manager",
        entity_type="canonicalexplainer",
        entity_id=explainer_id,
        action="INVALIDATE_EXPLAINER",
        pre_snapshot=pre_snapshot,
        post_snapshot=post_snapshot,
    )

    return updated


def verify_cron_api_key(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    authorization: Optional[str] = Header(None),
    api_key: Optional[str] = Query(None),
) -> Optional[str]:
    """Verify API key for scheduled or manual Weekly Loop execution.

    Accepts API key via:
    - 'X-API-Key' header
    - 'Authorization: Bearer <key>' header
    - '?api_key=<key>' query parameter
    """
    settings = get_settings()
    provided_key = x_api_key or api_key
    if not provided_key and authorization and authorization.startswith("Bearer "):
        provided_key = authorization.replace("Bearer ", "").strip()

    expected_key = settings.SUPPORT_API_KEY

    # If key was supplied, validate it strictly
    if provided_key:
        if provided_key != expected_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key provided for Weekly Loop execution.",
            )
        return provided_key

    # Strictly require API key when accessing /run-weekly if REQUIRE_CRON_API_KEY is True
    if request.url.path.endswith("/run-weekly") and settings.REQUIRE_CRON_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required for scheduled Weekly Loop. Provide via 'X-API-Key' header, 'Authorization: Bearer <key>', or '?api_key=<key>'.",
        )

    return None


@router.post("/run-weekly")
@router.post("/pulse/run")
async def trigger_weekly_run(
    request: Request,
    req: Optional[PulseRunRequest] = None,
    api_key: Optional[str] = Depends(verify_cron_api_key),
):
    """Trigger unattended Weekly Loop execution and refresh pulse intelligence.

    Supports external cron jobs (GitHub Actions, Hosted Cron) with API Key authentication,
    as well as in-app dashboard triggers. Runs completely start-to-finish without manual steps.
    """
    scheduler = get_weekly_scheduler()
    week_id = req.week_identifier if req else None
    source = "cron_api" if request.url.path.endswith("/run-weekly") else "pulse_run_api"

    result = await scheduler.trigger_cycle_now(week_identifier=week_id, source=source)
    return result


@router.get("/schedule/status")
def get_schedule_status():
    """Retrieve runtime diagnostics, interval, and execution history of the Weekly Scheduler."""
    scheduler = get_weekly_scheduler()
    return scheduler.get_status()
