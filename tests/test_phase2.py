"""Automated verification tests for Phase 2: Response Loop Pipeline.

Validates:
1. Agent 1 (Corpus Retrieval Specialist) relevance threshold τ_rel = 0.72 and fallback triggering
2. Agent 2 (Compliance Guard) regulatory breach detection and standard refusal
3. Agent 3 (Drafting Agent) grounded draft synthesis and structured internal routing notes
4. Orchestrator parallel execution and signal arbitration
5. Reviewer Agent quality control gate (sentence caps <= 3, single whitelisted URL, abbreviation handling)
6. End-to-end Pipeline integration from ingress to final reviewed SupportTicket
"""

import asyncio
import pytest

from src.agents.response.compliance_agent import ComplianceAgent
from src.agents.response.drafting_agent import DraftingAgent
from src.agents.response.orchestrator import Orchestrator
from src.agents.response.pipeline import ResponsePipeline, get_response_pipeline, run_response_loop
from src.agents.response.retrieval_agent import RetrievalAgent
from src.agents.response.reviewer_agent import ReviewerAgent
from src.models.ticket import (
    RoutingCategory,
    RoutingUrgency,
    SentimentType,
    SupportTicket,
    TicketStatus,
)


# ==============================================================================
# 1. Agent 1 (Corpus Retrieval Specialist) Tests
# ==============================================================================

class TestRetrievalAgent:
    """Tests for Agent 1 evaluating Milestone 1 corpus coverage and relevance thresholds."""

    @pytest.fixture
    def agent(self) -> RetrievalAgent:
        return RetrievalAgent()

    def test_covered_query_clears_threshold(self, agent: RetrievalAgent):
        """Valid queries clear relevance threshold tau_rel = 0.72 with official source URLs."""
        query = "What is the brokerage fee for equity delivery trading?"
        result = agent.evaluate_query(query)

        assert result["covered"] is True
        assert result["relevance_score"] >= 0.72
        assert result["top_chunk"] is not None
        assert result["source_url"] == "https://platform.in/charges"
        assert len(result["searched_queries"]) >= 1

    def test_uncovered_query_triggers_not_covered_flag(self, agent: RetrievalAgent):
        """Questions outside Milestone 1 disclosures fail threshold and preserve evaluated terms."""
        query = "What is the platform fee for trading US stocks?"
        result = agent.evaluate_query(query)

        assert result["covered"] is False
        assert result["relevance_score"] < 0.72
        assert result["top_chunk"] is None
        assert result["source_url"] is None
        assert "US stocks" in result["searched_queries"][0]

    def test_compound_query_partial_gap(self, agent: RetrievalAgent):
        """EC-RAG-01: Multi-part query where Part A is covered but Part B is absent."""
        query = "What is the STT on equity delivery, and what is the fee for trading US stocks?"
        result = agent.evaluate_query(query)

        # Primary intent is covered, but secondary sub-intent is flagged as gap
        assert result["covered"] is True
        assert result["partial_gap"] is not None
        assert "US stocks" in result["partial_gap"]


# ==============================================================================
# 2. Agent 2 (Compliance Guard) Tests
# ==============================================================================

class TestComplianceAgent:
    """Tests for Agent 2 inspecting queries for regulatory compliance."""

    @pytest.fixture
    def agent(self) -> ComplianceAgent:
        return ComplianceAgent()

    def test_advisory_query_blocked(self, agent: ComplianceAgent):
        query = "Should I buy Suzlon shares tomorrow for 20% returns?"
        result = agent.evaluate_query(query)

        assert result["is_compliant"] is False
        assert result["violation_reason"] is not None
        assert "We do not provide investment advice" in result["refusal_draft"]
        assert result["cited_url"] == "https://platform.in/charges"

    def test_clean_query_passes(self, agent: ComplianceAgent):
        query = "Why was DP charge of Rs. 15.93 debited on selling shares?"
        result = agent.evaluate_query(query)

        assert result["is_compliant"] is True
        assert result["violation_reason"] is None
        assert result["refusal_draft"] is None


# ==============================================================================
# 3. Agent 3 (Drafting Agent) Tests
# ==============================================================================

class TestDraftingAgent:
    """Tests for Agent 3 synthesizing grounded drafts and internal routing notes."""

    @pytest.fixture
    def agent(self) -> DraftingAgent:
        return DraftingAgent()

    def test_routing_note_generation(self, agent: DraftingAgent):
        """Routing notes assign valid category, urgency, sentiment, and reason."""
        query = "Why did you deduct Rs 15 from my account? I thought delivery was free!"
        retrieval_output = {
            "covered": True,
            "source_url": "https://cdslindia.com/charges",
            "top_chunk": None,
        }
        note = agent.generate_routing_note(query, retrieval_output)

        assert note.category == RoutingCategory.DP_CHARGES
        assert note.sentiment in (SentimentType.CONFUSED, SentimentType.FRUSTRATED)
        assert note.urgency in (RoutingUrgency.MEDIUM, RoutingUrgency.HIGH)
        assert len(note.reason) > 5

    def test_frustrated_ticket_routing(self, agent: DraftingAgent):
        """EC-RESP-03: Frustrated ticket with aggressive vocabulary tags HIGH urgency."""
        query = "You fraud company, why was ₹354 debited without permission? I will file a police complaint!"
        note = agent.generate_routing_note(query)

        assert note.sentiment == SentimentType.FRUSTRATED
        assert note.urgency in (RoutingUrgency.HIGH, RoutingUrgency.ESCALATE)
        assert note.category == RoutingCategory.ACCOUNT_MAINTENANCE

    def test_draft_synthesis_grounded(self, agent: DraftingAgent):
        """Draft synthesized strictly from retrieved facts with official source URL."""
        query = "Is equity delivery free or what is the brokerage charge?"
        retrieval_output = {
            "covered": True,
            "source_url": "https://platform.in/charges",
            "top_chunk": None,
        }
        draft = agent.synthesize_draft(query, retrieval_output)

        assert "brokerage-free" in draft or "Rs. 0" in draft
        assert "https://platform.in/charges" in draft


# ==============================================================================
# 4. Orchestrator Agent Tests
# ==============================================================================

class TestOrchestrator:
    """Tests for Orchestrator running parallel agent mesh and conflict resolution."""

    @pytest.mark.asyncio
    async def test_orchestrator_parallel_execution(self):
        """Orchestrator runs Agent 1 and Agent 2 concurrently and returns deliberation."""
        orchestrator = Orchestrator()
        result = await orchestrator.run("What is the STT rate on equity delivery?")

        assert result["is_covered"] is True
        assert result["cited_url"] in ("https://sebi.gov.in/charges", "https://platform.in/charges")
        assert result["routing_note"].category == RoutingCategory.STATUTORY_CHARGES
        assert result["deliberation"] is not None
        assert result["deliberation"].retrieval_agent_output["covered"] is True
        assert result["deliberation"].compliance_agent_output["is_compliant"] is True

    @pytest.mark.asyncio
    async def test_orchestrator_uncovered_fallback(self):
        """Orchestrator emits standard fallback when inquiry is not covered."""
        orchestrator = Orchestrator()
        result = await orchestrator.run("What is the platform fee for trading US stocks?")

        assert result["is_covered"] is False
        assert result["cited_url"] is None
        assert "not covered in our official platform documentation" in result["draft"]
        assert "US stocks" in result["draft"]


# ==============================================================================
# 5. Reviewer Agent (Quality Gate) Tests
# ==============================================================================

class TestReviewerAgent:
    """Tests for Reviewer Agent sentence segmentation, abbreviation protection, and citations."""

    @pytest.fixture
    def reviewer(self) -> ReviewerAgent:
        return ReviewerAgent()

    def test_sentence_tokenizer_abbreviations_and_decimals(self, reviewer: ReviewerAgent):
        """EC-RESP-01: Financial abbreviations (Rs., e.g., i.e.) and decimals must NOT cause false splits."""
        draft = (
            "Brokerage is Rs. 20 or 0.05% (whichever is lower) per executed order. "
            "E.g., for an intraday trade of ₹10,000, fee is Rs. 5. "
            "Source: https://platform.in/charges"
        )
        sentences = reviewer.split_sentences(draft)
        assert len(sentences) == 3, f"Expected 3 sentences, got {len(sentences)}: {sentences}"

    def test_sentence_cap_enforcement(self, reviewer: ReviewerAgent):
        """Reviewer enforces hard cap of <= 3 sentences."""
        long_draft = (
            "Sentence one here. "
            "Sentence two explains details. "
            "Sentence three adds context. "
            "Sentence four exceeds the cap. "
            "Source: https://platform.in/charges"
        )
        res = reviewer.review_draft(long_draft, is_covered=True, cited_url="https://platform.in/charges")
        assert res["sentence_count"] <= 3
        assert "https://platform.in/charges" in res["approved_draft"]

    def test_strict_single_whitelisted_citation(self, reviewer: ReviewerAgent):
        """EC-RESP-02: Enforces exactly one whitelisted source URL."""
        # Draft with redundant URLs
        draft_multiple_urls = (
            "Equity delivery is free as per https://platform.in/charges. "
            "Statutory taxes also apply: https://sebi.gov.in/charges."
        )
        res = reviewer.review_draft(draft_multiple_urls, is_covered=True)
        assert res["cited_url"] in ("https://platform.in/charges", "https://sebi.gov.in/charges")

    def test_reviewer_pii_sweep(self, reviewer: ReviewerAgent):
        """Reviewer sweeps and cleans any residual PII before approval."""
        draft_with_pii = (
            "Your account with phone 9876543210 has zero equity delivery brokerage. "
            "Source: https://platform.in/charges"
        )
        res = reviewer.review_draft(draft_with_pii, is_covered=True)
        assert "[REDACTED_PHONE]" in res["approved_draft"]
        assert "9876543210" not in res["approved_draft"]


# ==============================================================================
# 6. End-to-End Response Pipeline Integration Tests
# ==============================================================================

class TestResponsePipeline:
    """Integration tests for the complete Response Loop pipeline."""

    @pytest.fixture
    def pipeline(self) -> ResponsePipeline:
        return get_response_pipeline()

    @pytest.mark.asyncio
    async def test_end_to_end_delivery_inquiry(self, pipeline: ResponsePipeline):
        """Valid customer inquiry produces approved ticket with <= 3 sentences and official citation."""
        raw_query = "Hello, my phone is 9876543210. Is equity delivery free on your platform?"
        ticket = await pipeline.process_inquiry(raw_query)

        assert isinstance(ticket, SupportTicket)
        assert ticket.status == TicketStatus.PENDING_APPROVAL
        assert ticket.sentence_count <= 3
        assert ticket.cited_url == "https://platform.in/charges"
        assert ticket.routing_note.category == RoutingCategory.BROKERAGE
        # Ingress PII must be scrubbed in raw_query_redacted
        assert "[REDACTED_PHONE]" in ticket.raw_query_redacted
        assert "9876543210" not in ticket.raw_query_redacted

    @pytest.mark.asyncio
    async def test_end_to_end_uncovered_inquiry(self, pipeline: ResponsePipeline):
        """Uncovered inquiry produces NOT_COVERED status with evaluated search terms."""
        raw_query = "What is the fee for trading Bitcoin and Ethereum crypto?"
        ticket = await pipeline.process_inquiry(raw_query)

        assert ticket.status == TicketStatus.NOT_COVERED
        assert ticket.is_covered is False
        assert ticket.cited_url is None
        assert "not covered in our official platform documentation" in ticket.proposed_draft
        assert len(ticket.searched_queries) > 0

    @pytest.mark.asyncio
    async def test_end_to_end_advisory_inquiry(self, pipeline: ResponsePipeline):
        """Advisory inquiry produces compliant refusal draft citing official fee schedule."""
        raw_query = "Which stock should I buy tomorrow to get 20% returns?"
        ticket = await pipeline.process_inquiry(raw_query)

        assert "We do not provide investment advice" in ticket.proposed_draft
        assert ticket.cited_url == "https://platform.in/charges"
        assert ticket.sentence_count <= 3

    def test_run_response_loop_synchronous_wrapper(self):
        """Verify synchronous entrypoint wrapper."""
        ticket = run_response_loop("What is the DP charge on selling shares?")
        assert isinstance(ticket, SupportTicket)
        assert ticket.sentence_count <= 3
        assert ticket.cited_url in ("https://cdslindia.com/charges", "https://platform.in/charges")
