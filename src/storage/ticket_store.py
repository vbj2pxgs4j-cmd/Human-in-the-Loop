"""In-memory and persisted storage for Support Tickets."""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from src.models.ticket import (
    AgentDeliberation,
    RoutingCategory,
    RoutingNote,
    RoutingUrgency,
    SentimentType,
    SupportTicket,
    TicketStatus,
)

logger = logging.getLogger(__name__)


class TicketStore:
    """Storage repository for support tickets with seeding and filtering."""

    def __init__(self, seed: bool = True):
        self._tickets: Dict[str, SupportTicket] = {}
        if seed:
            self._seed_default_tickets()

    def _seed_default_tickets(self) -> None:
        """Seed representative tickets covering various categories and workflow statuses."""
        now = datetime.now(timezone.utc)

        t1 = SupportTicket(
            ticket_id="tkt_10291",
            raw_query_redacted="Why was DP charge of Rs. 15.93 debited on selling shares? [REDACTED_PHONE]",
            proposed_draft=(
                "Depository Participant (DP) charges of Rs. 13.50 plus 18% GST (total Rs. 15.93) are debited "
                "when selling equity shares from your demat account. This fee is charged flat per company per day "
                "irrespective of the quantity sold. Source: https://cdslindia.com/charges"
            ),
            sentence_count=3,
            cited_url="https://cdslindia.com/charges",
            routing_note=RoutingNote(
                category=RoutingCategory.DP_CHARGES,
                urgency=RoutingUrgency.MEDIUM,
                sentiment=SentimentType.CONFUSED,
                reason="Standard factual inquiry regarding depository debit fee upon delivery sell.",
            ),
            canonical_explainer_id=None,
            deliberation=AgentDeliberation(
                retrieval_agent_output={"relevance_score": 0.89, "covered": True},
                compliance_agent_output={"is_compliant": True},
                drafting_agent_output={"category": "DP_CHARGES"},
                orchestrator_notes="Clear DP charge query grounded in CDSL schedule.",
            ),
            status=TicketStatus.PENDING_APPROVAL,
            created_at=now,
            is_covered=True,
            searched_queries=["Why was DP charge of Rs. 15.93 debited on selling shares?"],
        )

        t2 = SupportTicket(
            ticket_id="tkt_10292",
            raw_query_redacted="Quarterly AMC of Rs 88.50 debited from ledger. I have zero trades this month! [REDACTED_PAN]",
            proposed_draft=(
                "Our standard Demat Annual Maintenance Charge (AMC) is Rs. 300 plus 18% GST (total Rs. 354 per year), "
                "debited quarterly from your account ledger at Rs. 88.50 per quarter. Basic Services Demat Accounts "
                "(BSDA) with holdings under Rs. 4,00,000 enjoy zero AMC. Source: https://platform.in/terms"
            ),
            sentence_count=3,
            cited_url="https://platform.in/terms",
            routing_note=RoutingNote(
                category=RoutingCategory.ACCOUNT_MAINTENANCE,
                urgency=RoutingUrgency.HIGH,
                sentiment=SentimentType.FRUSTRATED,
                reason="Customer expressed friction regarding quarterly ledger maintenance fee.",
            ),
            canonical_explainer_id=None,
            deliberation=AgentDeliberation(
                retrieval_agent_output={"relevance_score": 0.92, "covered": True},
                compliance_agent_output={"is_compliant": True},
                drafting_agent_output={"category": "ACCOUNT_MAINTENANCE"},
                orchestrator_notes="Frustrated user query on quarterly AMC debit.",
            ),
            status=TicketStatus.PENDING_APPROVAL,
            created_at=now,
            is_covered=True,
            searched_queries=["Quarterly AMC of Rs 88.50 debited from ledger."],
        )

        t3 = SupportTicket(
            ticket_id="tkt_10293",
            raw_query_redacted="Is equity delivery trading zero brokerage on your platform?",
            proposed_draft=(
                "Equity delivery trading on our platform is 100% brokerage-free (Rs. 0 brokerage). "
                "Regulatory statutory charges such as STT and exchange fees apply as per government norms. "
                "Source: https://platform.in/charges"
            ),
            sentence_count=3,
            cited_url="https://platform.in/charges",
            routing_note=RoutingNote(
                category=RoutingCategory.BROKERAGE,
                urgency=RoutingUrgency.LOW,
                sentiment=SentimentType.NEUTRAL,
                reason="Standard factual inquiry regarding equity delivery brokerage.",
            ),
            canonical_explainer_id=None,
            deliberation=AgentDeliberation(
                retrieval_agent_output={"relevance_score": 0.95, "covered": True},
                compliance_agent_output={"is_compliant": True},
                drafting_agent_output={"category": "BROKERAGE"},
                orchestrator_notes="Zero brokerage delivery query.",
            ),
            status=TicketStatus.APPROVED,
            created_at=now,
            resolved_at=now,
            operator_id="operator_seed",
            is_covered=True,
            searched_queries=["Is equity delivery trading zero brokerage on your platform?"],
        )

        t4 = SupportTicket(
            ticket_id="tkt_10294",
            raw_query_redacted="What is the platform fee for trading US stocks and global ETFs?",
            proposed_draft=(
                "This question is not covered in our official platform documentation. "
                "Search evaluated: ['US stocks and global ETFs', 'trading US stocks']."
            ),
            sentence_count=2,
            cited_url=None,
            routing_note=RoutingNote(
                category=RoutingCategory.OTHERS,
                urgency=RoutingUrgency.LOW,
                sentiment=SentimentType.NEUTRAL,
                reason="Official corpus gap for topic: 'US stocks and global ETFs'.",
            ),
            canonical_explainer_id=None,
            deliberation=AgentDeliberation(
                retrieval_agent_output={"relevance_score": 0.35, "covered": False},
                compliance_agent_output={"is_compliant": True},
                drafting_agent_output={"category": "OTHERS"},
                orchestrator_notes="Topic not covered by Milestone 1 disclosures.",
            ),
            status=TicketStatus.NOT_COVERED,
            created_at=now,
            is_covered=False,
            searched_queries=["US stocks and global ETFs", "trading US stocks"],
        )

        for t in [t1, t2, t3, t4]:
            self._tickets[t.ticket_id] = t

    def get_ticket(self, ticket_id: str) -> Optional[SupportTicket]:
        """Fetch ticket by ID."""
        return self._tickets.get(ticket_id)

    def list_tickets(self, status: Optional[str] = None) -> List[SupportTicket]:
        """List tickets, optionally filtered by status."""
        tickets = list(self._tickets.values())
        if status:
            stat_upper = status.upper()
            tickets = [t for t in tickets if t.status.value == stat_upper]
        return sorted(tickets, key=lambda t: t.created_at, reverse=True)

    def save_ticket(self, ticket: SupportTicket) -> SupportTicket:
        """Save or update ticket in store."""
        self._tickets[ticket.ticket_id] = ticket
        return ticket

    def delete_ticket(self, ticket_id: str) -> bool:
        """Remove ticket by ID."""
        if ticket_id in self._tickets:
            del self._tickets[ticket_id]
            return True
        return False

    def clear(self) -> None:
        """Clear all stored tickets."""
        self._tickets.clear()


# Global singleton TicketStore
_ticket_store_instance: Optional[TicketStore] = None


def get_ticket_store() -> TicketStore:
    """Retrieve global singleton TicketStore."""
    global _ticket_store_instance
    if _ticket_store_instance is None:
        _ticket_store_instance = TicketStore(seed=True)
    return _ticket_store_instance
