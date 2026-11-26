"""Orchestrator Agent coordinating parallel multi-agent evaluation and conflict resolution."""

import asyncio
import logging
from typing import Any, Dict, Optional

from src.agents.response.compliance_agent import ComplianceAgent
from src.agents.response.drafting_agent import DraftingAgent
from src.agents.response.retrieval_agent import RetrievalAgent
from src.models.ticket import AgentDeliberation, RoutingNote

logger = logging.getLogger(__name__)


class Orchestrator:
    """Coordinates parallel fan-out across Agent 1, 2, and 3, resolving fallback or regulatory blocks."""

    def __init__(
        self,
        retrieval_agent: Optional[RetrievalAgent] = None,
        compliance_agent: Optional[ComplianceAgent] = None,
        drafting_agent: Optional[DraftingAgent] = None,
    ):
        self.retrieval_agent = retrieval_agent or RetrievalAgent()
        self.compliance_agent = compliance_agent or ComplianceAgent()
        self.drafting_agent = drafting_agent or DraftingAgent()

    async def run(self, sanitized_query: str) -> Dict[str, Any]:
        """Execute parallel multi-agent evaluation using asyncio.gather."""
        # 1. Parallel Fan-Out: Run Agent 1 (Retrieval) and Agent 2 (Compliance) concurrently
        loop = asyncio.get_event_loop()
        retrieval_task = loop.run_in_executor(
            None, self.retrieval_agent.evaluate_query, sanitized_query
        )
        compliance_task = loop.run_in_executor(
            None, self.compliance_agent.evaluate_query, sanitized_query
        )

        retrieval_output, compliance_output = await asyncio.gather(
            retrieval_task, compliance_task
        )

        # 2. Decision Logic & Signal Arbitration
        # Case A: Regulatory Breach (Compliance Violation)
        if not compliance_output.get("is_compliant"):
            logger.info("Orchestrator: Regulatory breach. Enforcing compliance refusal.")
            draft = compliance_output.get("refusal_draft")
            cited_url = compliance_output.get("cited_url") or "https://platform.in/charges"
            is_covered = True
            searched_queries = []
            orchestrator_notes = (
                f"Regulatory violation detected: {compliance_output.get('violation_reason')}. "
                "Bypassed corpus synthesis and applied deterministic refusal."
            )

        # Case B: Uncovered Inquiry (Corpus Gap)
        elif not retrieval_output.get("covered"):
            logger.info("Orchestrator: Corpus gap detected. Emitting fallback protocol.")
            searched_queries = retrieval_output.get("searched_queries", [sanitized_query])
            draft = f"This question is not covered in our official platform documentation. Search evaluated: {searched_queries}."
            cited_url = None
            is_covered = False
            orchestrator_notes = (
                f"Question fell below relevance threshold ({retrieval_output.get('relevance_score'):.4f}). "
                "Emitted standard fallback protocol detailing evaluated search terms."
            )

        # Case C: Compliant & Covered Inquiry
        else:
            logger.info("Orchestrator: Inquiry covered and compliant. Invoking drafting agent.")
            draft = self.drafting_agent.synthesize_draft(
                sanitized_query, retrieval_output, compliance_output
            )
            cited_url = retrieval_output.get("source_url")
            is_covered = True
            searched_queries = retrieval_output.get("searched_queries", [])
            orchestrator_notes = (
                f"Synthesized draft grounded in Milestone 1 document: {retrieval_output.get('top_chunk').doc_id if retrieval_output.get('top_chunk') else 'unknown'} "
                f"with relevance score {retrieval_output.get('relevance_score'):.4f}."
            )

        # 3. Generate Structured Internal Routing Note
        routing_note = self.drafting_agent.generate_routing_note(
            sanitized_query, retrieval_output, compliance_output
        )

        # 4. Construct Agent Deliberation Audit Trail
        deliberation = AgentDeliberation(
            retrieval_agent_output={
                "covered": retrieval_output.get("covered"),
                "relevance_score": round(float(retrieval_output.get("relevance_score", 0.0)), 4),
                "source_url": retrieval_output.get("source_url"),
                "searched_queries": retrieval_output.get("searched_queries", []),
            },
            compliance_agent_output={
                "is_compliant": compliance_output.get("is_compliant"),
                "violation_reason": compliance_output.get("violation_reason"),
            },
            drafting_agent_output={
                "candidate_draft": draft,
                "routing_note": routing_note.model_dump(mode="json"),
            },
            orchestrator_notes=orchestrator_notes,
        )

        return {
            "query": sanitized_query,
            "draft": draft,
            "cited_url": cited_url,
            "is_covered": is_covered,
            "searched_queries": searched_queries,
            "routing_note": routing_note,
            "deliberation": deliberation,
        }
