"""Support Queue API routes with optimistic concurrency and state diff isolation."""

import logging
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from src.agents.response.pipeline import ResponsePipeline, get_response_pipeline
from src.agents.response.reviewer_agent import ReviewerAgent
from src.models.ticket import SupportTicket, TicketStatus
from src.security.pii_scrubber import get_pii_scrubber
from src.storage.audit_logger import get_audit_logger
from src.storage.state_diff_engine import capture_state
from src.storage.ticket_store import get_ticket_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/support", tags=["Support Queue"])


# ------------------------------------------------------------------------------
# Request / Response Schemas
# ------------------------------------------------------------------------------

class InquiryRequest(BaseModel):
    """Payload for submitting a new customer inquiry."""
    raw_query: str = Field(..., min_length=2, description="Raw user support question")
    customer_id: Optional[str] = Field(default="cust_anonymous", description="Customer ID")


class EditDraftRequest(BaseModel):
    """Payload for human operator editing a response draft."""
    proposed_draft: str = Field(..., min_length=5, description="Edited draft response")
    pre_state_hash: Optional[str] = Field(default=None, description="Cryptographic hash of ticket before edit (EC-HITL-02)")
    operator_id: Optional[str] = Field(default="support_specialist", description="Operator identity")


class ApproveTicketRequest(BaseModel):
    """Payload for human operator approving and dispatching a draft."""
    pre_state_hash: Optional[str] = Field(default=None, description="Cryptographic hash of ticket before approval (EC-HITL-02)")
    operator_id: Optional[str] = Field(default="support_specialist", description="Operator identity")
    final_draft: Optional[str] = Field(default=None, description="Optional edited draft before final dispatch")


class RejectTicketRequest(BaseModel):
    """Payload for rejecting a draft."""
    pre_state_hash: Optional[str] = Field(default=None, description="Cryptographic hash of ticket before rejection (EC-HITL-02)")
    operator_id: Optional[str] = Field(default="support_specialist", description="Operator identity")
    reason: Optional[str] = Field(default=None, description="Rejection rationale")


# ------------------------------------------------------------------------------
# Support Queue Endpoints
# ------------------------------------------------------------------------------

@router.get("/tickets", response_model=List[SupportTicket])
def list_tickets(status_filter: Optional[str] = Query(None, alias="status")):
    """List support tickets, optionally filtered by status (PENDING_APPROVAL, APPROVED, etc.)."""
    store = get_ticket_store()
    return store.list_tickets(status=status_filter)


@router.get("/tickets/{ticket_id}", response_model=SupportTicket)
def get_ticket(ticket_id: str):
    """Retrieve full details of a single ticket including agent deliberation logs."""
    store = get_ticket_store()
    ticket = store.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Ticket {ticket_id} not found.")
    return ticket


@router.post("/inquiries", response_model=SupportTicket, status_code=status.HTTP_201_CREATED)
async def submit_inquiry(req: InquiryRequest):
    """Submit a raw user inquiry through the multi-agent Response Loop into the support queue."""
    pipeline = get_response_pipeline()
    ticket = await pipeline.process_inquiry(raw_query=req.raw_query, user_id=req.customer_id)

    store = get_ticket_store()
    store.save_ticket(ticket)
    return ticket


@router.put("/tickets/{ticket_id}/edit", response_model=SupportTicket)
def edit_draft(ticket_id: str, req: EditDraftRequest):
    """Edit draft with strict human edit validation (EC-HITL-01) and concurrency check (EC-HITL-02)."""
    store = get_ticket_store()
    ticket = store.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Ticket {ticket_id} not found.")

    pre_snapshot = capture_state(ticket)

    # EC-HITL-02: Optimistic concurrency control via pre_state_hash
    if req.pre_state_hash and req.pre_state_hash != pre_snapshot["hash"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ticket has already been updated by another operator. Refreshing view.",
        )

    # EC-HITL-01: Human Edit Validation Gate (<= 3 sentences, >= 1 whitelisted URL, PII check)
    reviewer = ReviewerAgent()
    sentences = reviewer.split_sentences(req.proposed_draft)
    if len(sentences) > 3:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Edit violates sentence limit: contains {len(sentences)} sentences (maximum allowed: 3).",
        )
    if len(sentences) == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Edit draft cannot be empty.",
        )

    _, cited_url, is_valid_url, url_err = reviewer.validate_citations(req.proposed_draft, is_covered=True)
    if not is_valid_url or not cited_url:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Edit violates length (max 3 sentences) or lacks an official source link.",
        )

    # Re-scrub PII to ensure operator did not accidentally paste customer secrets
    scrubber = get_pii_scrubber()
    clean_draft = scrubber.scrub(req.proposed_draft)

    updated_ticket = ticket.model_copy(
        update={
            "proposed_draft": clean_draft,
            "sentence_count": len(sentences),
            "cited_url": cited_url,
            "status": TicketStatus.EDITED,
            "operator_id": req.operator_id or "support_specialist",
        }
    )

    post_snapshot = capture_state(updated_ticket)

    # EC-HITL-03: Log mutation and verify state isolation
    audit_logger = get_audit_logger()
    audit_logger.log_mutation(
        operator_id=req.operator_id or "support_specialist",
        entity_type="ticket",
        entity_id=ticket.ticket_id,
        action="EDIT_DRAFT",
        pre_snapshot=pre_snapshot,
        post_snapshot=post_snapshot,
    )

    store.save_ticket(updated_ticket)
    return updated_ticket


@router.post("/tickets/{ticket_id}/approve", response_model=SupportTicket)
def approve_ticket(ticket_id: str, req: ApproveTicketRequest):
    """Approve and dispatch ticket draft (EC-HITL-01, EC-HITL-02, EC-HITL-03)."""
    store = get_ticket_store()
    ticket = store.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Ticket {ticket_id} not found.")

    pre_snapshot = capture_state(ticket)

    # EC-HITL-02: Optimistic concurrency control via pre_state_hash
    if req.pre_state_hash and req.pre_state_hash != pre_snapshot["hash"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ticket has already been updated by another operator. Refreshing view.",
        )

    active_draft = req.final_draft if req.final_draft is not None else ticket.proposed_draft
    reviewer = ReviewerAgent()
    sentences = reviewer.split_sentences(active_draft)

    # EC-HITL-01: Length and link validation
    if len(sentences) > 3:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Edit violates length (max 3 sentences) or lacks an official source link. Contains {len(sentences)} sentences.",
        )

    if ticket.is_covered:
        _, cited_url, is_valid_url, _ = reviewer.validate_citations(active_draft, is_covered=True)
        if not is_valid_url or not cited_url:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Edit violates length (max 3 sentences) or lacks an official source link.",
            )
    else:
        cited_url = ticket.cited_url

    now = datetime.now(timezone.utc)
    updated_ticket = ticket.model_copy(
        update={
            "status": TicketStatus.APPROVED,
            "operator_id": req.operator_id or "support_specialist",
            "resolved_at": now,
            "proposed_draft": active_draft,
            "sentence_count": len(sentences),
            "cited_url": cited_url,
        }
    )

    post_snapshot = capture_state(updated_ticket)

    # EC-HITL-03: State Diff isolation and audit logging
    audit_logger = get_audit_logger()
    audit_logger.log_mutation(
        operator_id=req.operator_id or "support_specialist",
        entity_type="ticket",
        entity_id=ticket.ticket_id,
        action="APPROVE_TICKET",
        pre_snapshot=pre_snapshot,
        post_snapshot=post_snapshot,
    )

    store.save_ticket(updated_ticket)
    return updated_ticket


@router.post("/tickets/{ticket_id}/reject", response_model=SupportTicket)
def reject_ticket(ticket_id: str, req: RejectTicketRequest):
    """Reject ticket draft (EC-HITL-02, EC-HITL-03)."""
    store = get_ticket_store()
    ticket = store.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Ticket {ticket_id} not found.")

    pre_snapshot = capture_state(ticket)

    # EC-HITL-02: Optimistic concurrency control via pre_state_hash
    if req.pre_state_hash and req.pre_state_hash != pre_snapshot["hash"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ticket has already been updated by another operator. Refreshing view.",
        )

    now = datetime.now(timezone.utc)
    updated_ticket = ticket.model_copy(
        update={
            "status": TicketStatus.REJECTED,
            "operator_id": req.operator_id or "support_specialist",
            "resolved_at": now,
        }
    )

    post_snapshot = capture_state(updated_ticket)

    # EC-HITL-03: State Diff isolation and audit logging
    audit_logger = get_audit_logger()
    audit_logger.log_mutation(
        operator_id=req.operator_id or "support_specialist",
        entity_type="ticket",
        entity_id=ticket.ticket_id,
        action="REJECT_TICKET",
        pre_snapshot=pre_snapshot,
        post_snapshot=post_snapshot,
    )

    store.save_ticket(updated_ticket)
    return updated_ticket
