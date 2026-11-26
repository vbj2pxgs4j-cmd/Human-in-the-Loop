"""Support Ticket, Agent Deliberation, and Routing Note models."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from pydantic import BaseModel, Field, field_validator


class RoutingCategory(str, Enum):
    """Classification categories for support tickets."""

    BROKERAGE = "BROKERAGE"
    STATUTORY_CHARGES = "STATUTORY_CHARGES"
    DP_CHARGES = "DP_CHARGES"
    ACCOUNT_MAINTENANCE = "ACCOUNT_MAINTENANCE"
    PAYMENT_GATEWAY = "PAYMENT_GATEWAY"
    OTHERS = "OTHERS"


class RoutingUrgency(str, Enum):
    """Urgency tiers for customer support resolution."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    ESCALATE = "ESCALATE"


class SentimentType(str, Enum):
    """Customer sentiment classification."""

    NEUTRAL = "NEUTRAL"
    CONFUSED = "CONFUSED"
    FRUSTRATED = "FRUSTRATED"


class TicketStatus(str, Enum):
    """Support ticket approval and lifecycle status."""

    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    EDITED = "EDITED"
    REJECTED = "REJECTED"
    NOT_COVERED = "NOT_COVERED"


class RoutingNote(BaseModel):
    """Internal metadata note produced alongside drafted replies for operator routing."""

    category: RoutingCategory = Field(..., description="Inquiry category")
    urgency: RoutingUrgency = Field(..., description="Operational urgency level")
    sentiment: SentimentType = Field(..., description="Customer sentiment score")
    reason: str = Field(..., min_length=3, description="Justification for routing and draft synthesis")


class AgentDeliberation(BaseModel):
    """Diagnostic audit trail of parallel multi-agent deliberations."""

    retrieval_agent_output: Dict[str, Any] = Field(
        default_factory=dict, description="Agent 1 retrieval signals (chunks, confidence, search terms)"
    )
    compliance_agent_output: Dict[str, Any] = Field(
        default_factory=dict, description="Agent 2 regulatory compliance inspection results"
    )
    drafting_agent_output: Dict[str, Any] = Field(
        default_factory=dict, description="Agent 3 draft proposal and routing metadata"
    )
    orchestrator_notes: str = Field(
        default="", description="Orchestrator synthesis or conflict resolution commentary"
    )


class SupportTicket(BaseModel):
    """Support ticket entity managed by the Response Loop and HITL Support Desk."""

    ticket_id: str = Field(..., description="Unique ticket identifier, e.g. tkt_10293")
    raw_query_redacted: str = Field(
        ..., min_length=1, description="PII-sanitized user query"
    )
    proposed_draft: str = Field(
        ..., description="Agent-proposed response draft (or explicit fallback text)"
    )
    sentence_count: int = Field(
        ge=0, le=3, description="Count of sentences in the proposed draft (strict <= 3 sentences)"
    )
    cited_url: Optional[str] = Field(
        default=None, description="Single authoritative Milestone 1 citation URL"
    )
    routing_note: Optional[RoutingNote] = Field(
        default=None, description="Internal routing and categorization note"
    )
    canonical_explainer_id: Optional[str] = Field(
        default=None, description="Referenced canonical explainer if fast-path matched"
    )
    deliberation: Optional[AgentDeliberation] = Field(
        default=None, description="Audit trace of agent mesh findings"
    )
    status: TicketStatus = Field(
        default=TicketStatus.PENDING_APPROVAL, description="Current workflow status"
    )
    created_at: datetime = Field(..., description="Ingestion timestamp")
    resolved_at: Optional[datetime] = Field(
        default=None, description="Timestamp of human approval or rejection"
    )
    operator_id: Optional[str] = Field(
        default=None, description="Identifier of the human operator who acted on the ticket"
    )
    is_covered: bool = Field(
        default=True, description="False if inquiry was deemed not covered by the official corpus"
    )
    searched_queries: List[str] = Field(
        default_factory=list, description="Search queries evaluated against the corpus if not covered"
    )

    @field_validator("cited_url")
    @classmethod
    def validate_cited_url(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            parsed = urlparse(v)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise ValueError(f"Invalid cited_url: {v}. Must be a valid HTTP/HTTPS URL.")
        return v
