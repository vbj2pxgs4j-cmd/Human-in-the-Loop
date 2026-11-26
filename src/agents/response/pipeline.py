"""End-to-end Response Loop Pipeline connecting ingress to reviewed draft proposal."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from src.agents.response.orchestrator import Orchestrator
from src.agents.response.reviewer_agent import ReviewerAgent
from src.bridge.canonical_store import CanonicalStore, get_canonical_store
from src.bridge.frequency_tracker import FrequencyTracker, get_frequency_tracker
from src.models.ticket import (
    AgentDeliberation,
    RoutingCategory,
    RoutingNote,
    RoutingUrgency,
    SentimentType,
    SupportTicket,
    TicketStatus,
)
from src.security.pii_scrubber import scrub_pii

logger = logging.getLogger(__name__)


class ResponsePipeline:
    """End-to-end customer support inquiry processing pipeline with fast-path canonical reuse."""

    def __init__(
        self,
        orchestrator: Optional[Orchestrator] = None,
        reviewer_agent: Optional[ReviewerAgent] = None,
        canonical_store: Optional[CanonicalStore] = None,
        frequency_tracker: Optional[FrequencyTracker] = None,
    ):
        self.orchestrator = orchestrator or Orchestrator()
        self.reviewer_agent = reviewer_agent or ReviewerAgent()
        self.canonical_store = (
            canonical_store if canonical_store is not None else get_canonical_store()
        )
        self.frequency_tracker = (
            frequency_tracker if frequency_tracker is not None else get_frequency_tracker()
        )

    async def process_inquiry(
        self,
        raw_query: str,
        ticket_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> SupportTicket:
        """Process raw query: PII scrub, record frequency, check fast-path explainer, or run agent mesh."""
        now = datetime.now(timezone.utc)
        tid = ticket_id or f"tkt_{int(now.timestamp() * 1000)}"

        # 1. Ingress PII Sanitization
        sanitized_query = scrub_pii(raw_query)

        # 2. Record inquiry in FrequencyTracker for Weekly Loop escalation monitoring
        if self.frequency_tracker is not None:
            self.frequency_tracker.record_inquiry(sanitized_query, user_id=user_id, timestamp=now)

        # 3. Phase 4 Fast-Path: Check approved Canonical Explainer Store (similarity > 0.88, TTL fresh)
        canonical_match = (
            self.canonical_store.find_matching_explainer(sanitized_query)
            if self.canonical_store is not None
            else None
        )

        if canonical_match:
            topic_slug = canonical_match.explainer.topic_slug
            if "dp" in topic_slug:
                category = RoutingCategory.DP_CHARGES
            elif "amc" in topic_slug:
                category = RoutingCategory.ACCOUNT_MAINTENANCE
            elif "stt" in topic_slug or "tax" in topic_slug:
                category = RoutingCategory.STATUTORY_CHARGES
            elif "brokerage" in topic_slug:
                category = RoutingCategory.BROKERAGE
            else:
                category = RoutingCategory.OTHERS

            routing_note = RoutingNote(
                category=category,
                urgency=RoutingUrgency.LOW,
                sentiment=SentimentType.NEUTRAL,
                reason=(
                    f"Reused product-approved canonical explainer '{canonical_match.explainer.explainer_id}' "
                    f"via fast-path lookup (similarity={canonical_match.similarity_score:.4f})."
                ),
            )

            deliberation = AgentDeliberation(
                orchestrator_notes=(
                    f"Fast-path canonical match (score={canonical_match.similarity_score:.4f}): "
                    f"{canonical_match.explainer.explainer_id}. Bypassed fresh 3-agent drafting."
                ),
            )

            ticket = SupportTicket(
                ticket_id=tid,
                raw_query_redacted=sanitized_query,
                proposed_draft=canonical_match.reusable_draft,
                sentence_count=canonical_match.sentence_count,
                cited_url=canonical_match.cited_url,
                routing_note=routing_note,
                canonical_explainer_id=canonical_match.explainer.explainer_id,
                deliberation=deliberation,
                status=TicketStatus.PENDING_APPROVAL,
                created_at=now,
                is_covered=True,
                searched_queries=[sanitized_query],
            )

            logger.info(
                "Fast-path reused explainer %s for ticket %s (score=%.4f)",
                canonical_match.explainer.explainer_id,
                ticket.ticket_id,
                canonical_match.similarity_score,
            )
            return ticket

        # 4. Fallback / Standard: Parallel Multi-Agent Mesh & Orchestrator Execution
        orch_result = await self.orchestrator.run(sanitized_query)

        # 5. Reviewer Agent Quality Control Gate
        review_result = self.reviewer_agent.review_draft(
            draft_text=orch_result["draft"],
            is_covered=orch_result["is_covered"],
            cited_url=orch_result["cited_url"],
        )

        # 6. Determine Ticket Status
        if not orch_result["is_covered"]:
            status = TicketStatus.NOT_COVERED
        else:
            status = TicketStatus.PENDING_APPROVAL

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
            ticket.ticket_id,
            ticket.status.value,
            ticket.sentence_count,
            ticket.cited_url,
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


def run_response_loop(
    raw_query: str, ticket_id: Optional[str] = None, user_id: Optional[str] = None
) -> SupportTicket:
    """Synchronous convenience wrapper to execute Response Loop pipeline."""
    pipeline = get_response_pipeline()
    return asyncio.run(pipeline.process_inquiry(raw_query, ticket_id=ticket_id, user_id=user_id))
