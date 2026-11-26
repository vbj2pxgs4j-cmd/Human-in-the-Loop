"""End-to-end Response Loop Pipeline connecting ingress to reviewed draft proposal."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from src.agents.response.orchestrator import Orchestrator
from src.agents.response.reviewer_agent import ReviewerAgent
from src.models.ticket import SupportTicket, TicketStatus
from src.security.pii_scrubber import scrub_pii

logger = logging.getLogger(__name__)


class ResponsePipeline:
    """End-to-end customer support inquiry processing pipeline."""

    def __init__(
        self,
        orchestrator: Optional[Orchestrator] = None,
        reviewer_agent: Optional[ReviewerAgent] = None,
    ):
        self.orchestrator = orchestrator or Orchestrator()
        self.reviewer_agent = reviewer_agent or ReviewerAgent()

    async def process_inquiry(
        self, raw_query: str, ticket_id: Optional[str] = None
    ) -> SupportTicket:
        """Process raw user query through ingress PII scrubbing, parallel agents, and reviewer quality gate."""
        # 1. Ingress PII Sanitization
        sanitized_query = scrub_pii(raw_query)

        # 2. Parallel Multi-Agent Mesh & Orchestrator Execution
        orch_result = await self.orchestrator.run(sanitized_query)

        # 3. Reviewer Agent Quality Control Gate
        review_result = self.reviewer_agent.review_draft(
            draft_text=orch_result["draft"],
            is_covered=orch_result["is_covered"],
            cited_url=orch_result["cited_url"],
        )

        # 4. Determine Ticket Status
        if not orch_result["is_covered"]:
            status = TicketStatus.NOT_COVERED
        else:
            status = TicketStatus.PENDING_APPROVAL

        # 5. Assemble Final SupportTicket
        now = datetime.now(timezone.utc)
        tid = ticket_id or f"tkt_{int(now.timestamp() * 1000)}"

        ticket = SupportTicket(
            ticket_id=tid,
            raw_query_redacted=sanitized_query,
            proposed_draft=review_result["approved_draft"],
            sentence_count=review_result["sentence_count"],
            cited_url=review_result["cited_url"],
            routing_note=orch_result["routing_note"],
            canonical_explainer_id=None,
            deliberation=orch_result["deliberation"],
            status=status,
            created_at=now,
            is_covered=orch_result["is_covered"],
            searched_queries=orch_result["searched_queries"],
        )

        logger.info(
            "Response pipeline completed ticket %s: status=%s sentences=%d cited_url=%s",
            ticket.ticket_id, ticket.status.value, ticket.sentence_count, ticket.cited_url
        )
        return ticket


# Global singleton pipeline accessor
_default_pipeline: Optional[ResponsePipeline] = None


def get_response_pipeline() -> ResponsePipeline:
    """Retrieve global singleton ResponsePipeline."""
    global _default_pipeline
    if _default_pipeline is None:
        _default_pipeline = ResponsePipeline()
    return _default_pipeline


def run_response_loop(raw_query: str, ticket_id: Optional[str] = None) -> SupportTicket:
    """Synchronous convenience wrapper to execute Response Loop pipeline."""
    pipeline = get_response_pipeline()
    return asyncio.run(pipeline.process_inquiry(raw_query, ticket_id=ticket_id))
