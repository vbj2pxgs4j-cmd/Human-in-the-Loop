"""Agent 2: Compliance & Policy Guard verifying SEBI regulations and zero advisory constraints."""

import logging
from typing import Any, Dict, Optional
from src.security.compliance_guard import ComplianceGuard, get_compliance_guard

logger = logging.getLogger(__name__)


class ComplianceAgent:
    """Agent 2 checking SEBI guidelines, facts-only constraint, and absence of speculative claims."""

    def __init__(self, guard: Optional[ComplianceGuard] = None):
        self.guard = guard or get_compliance_guard()

    def evaluate_query(self, query: str) -> Dict[str, Any]:
        """Inspect user query for financial advice, return expectations, or adversarial intent."""
        eval_result = self.guard.evaluate_query(query)
        if not eval_result["is_compliant"]:
            logger.warning(
                "Compliance breach flagged: reason='%s' query='%s'",
                eval_result["violation_reason"], query
            )
            return {
                "is_compliant": False,
                "violation_reason": eval_result["violation_reason"],
                "refusal_draft": eval_result["refusal_response"],
                "cited_url": "https://platform.in/charges",
            }

        return {
            "is_compliant": True,
            "violation_reason": None,
            "refusal_draft": None,
            "cited_url": None,
        }

    def validate_candidate_draft(self, draft_text: str) -> Dict[str, Any]:
        """Inspect proposed draft response to ensure zero leaked advisory or speculative terms."""
        is_valid, violation = self.guard.validate_response_text(draft_text)
        return {
            "is_valid": is_valid,
            "violation": violation,
        }
