"""Deterministic SEBI regulatory compliance guard and financial advisory refusal engine."""

import re
from typing import Any, Dict, List, Optional, Tuple


class ComplianceGuard:
    """Detects and rejects financial advice, stock recommendations, return projections, and adversarial prompts."""

    # Standard Regulatory Refusal Template (SEBI Compliance)
    STANDARD_REFUSAL_RESPONSE = (
        "We do not provide investment advice, trading recommendations, or return projections. "
        "For factual inquiries regarding platform fees, charges, or account maintenance, "
        "please refer to our official fee schedule: https://platform.in/charges"
    )

    # 1. Advisory & Trading Recommendation Patterns
    ADVISORY_PATTERNS = [
        # Explicit recommendation directives for stocks, funds, or assets
        r"\b(?:recommend|suggest|advice|advise)\b.*?\b(?:stocks?|shares?|mutual\s+funds?|funds?|etfs?|scrips?|portfolio)\b",
        r"\b(?:stocks?|shares?|mutual\s+funds?|funds?|etfs?)\b.*?\b(?:recommend(?:ation)?s?|suggest(?:ion)?s?|advice|advise|tips?|picks?)\b",
        r"\b(?:should\s+i|can\s+i|shall\s+we)\s+(?:buy|sell|hold|accumulate|exit|invest\s+in|purchase)\b",
        r"\b(?:which|what)\s+.*?\b(?:stock|share|company|fund|mutual\s+fund)\s+.*?\b(?:to|should\s+i|will|can)\s+(?:buy|sell|invest|purchase|surge|gain|perform)\b",
        r"\b(?:best|top|good)\s+.*?\b(?:stocks?|shares?|funds?|mutual\s+funds?)\s+.*?\b(?:to\s+buy|for\s+(?:tomorrow|2026|today|investment)|recommendations?)\b",
        r"\b(?:stock\s+tips?|trading\s+calls?|intraday\s+tips?|multibaggers?|stock\s+picks?)\b",
        r"\b(?:target\s+price|stop\s*loss|entry\s+levels?|price\s+targets?)\b",
        r"\b(?:is|are)\s+.*?\b(?:good|bad|worth)\s+(?:a\s+)?(?:buy|investment|purchase)\b",
        r"\b(?:will|can)\s+(?:nifty|sensex|banknifty|market)\s+(?:cross|hit|reach|fall|drop|touch|break)\b",
        r"\bportfolio\s+allocation\b",
    ]

    # 2. Return & Performance Figures Projections
    RETURN_PATTERNS = [
        r"\b(?:expected|guaranteed|promised|assured)\s+(?:returns?|profits?|gains?)\b",
        r"\b(?:cagr|annualized\s+return|monthly\s+return|profit\s+percentage|historical\s+returns?)\b",
        r"\b(?:how\s+much\s+(?:profit|money|return)\s+(?:will|can)\s+i\s+make)\b",
        r"\b(?:double\s+my\s+money|make\s+(?:₹|rs\.?|inr)?\s*[\d,]+)\b",
        r"\b(?:backtest|yield\s+percentage|15%\s+cagr)\b",
    ]

    # 3. Counterfactual & Historical Hypothetical Inquiries
    HYPOTHETICAL_PATTERNS = [
        r"\bif\s+.*?\b(?:rbi|market|fed|interest\s+rate|nifty|gold)\b.*?\b(?:surge|fall|buy|invest|stocks?)\b",
        r"\bif\s+i\s+had\s+invested\b",
        r"\bif\s+i\s+invest(?:ed)?\s+(?:₹|rs\.?|inr)?\s*[\d,]+\s+in\b",
        r"\bwhat\s+return\s+would\s+i\s+have\s+received\b",
    ]

    # 4. Adversarial Roleplay & Jailbreak Patterns
    JAILBREAK_PATTERNS = [
        r"ignore\s+(?:all\s+)?previous\s+instructions",
        r"\byou\s+are\s+(?:now\s+)?(?:dan|wealthguru|advisor|trader|guru|expert)",
        r"\bpretend\s+(?:you\s+are|to\s+be|we\s+are)\b",
        r"\bact\s+as\s+(?:a\s+)?(?:financial\s+advisor|stock\s+broker|expert)\b",
        r"\bjailbreak\b",
        r"\b(?:disregard|bypass|ignore)\s+.*?\b(?:rules?|compliance|sebi|restrictions?)\b",
        r"\b(?:alternate\s+universe|hypothetical\s+world|fictional\s+scenario)\b",
        r"\bpermission\s+to\s+bypass\b",
    ]

    # Prohibited words in outbound agent responses
    OUTBOUND_PROHIBITED_WORDS = [
        "multibagger",
        "guaranteed return",
        "target price",
        "should buy",
        "should sell",
        "recommend buying",
        "recommend selling",
        "expected return",
    ]

    def __init__(self):
        self.compiled_advisory = [re.compile(p, re.IGNORECASE) for p in self.ADVISORY_PATTERNS]
        self.compiled_returns = [re.compile(p, re.IGNORECASE) for p in self.RETURN_PATTERNS]
        self.compiled_hypothetical = [re.compile(p, re.IGNORECASE) for p in self.HYPOTHETICAL_PATTERNS]
        self.compiled_jailbreaks = [re.compile(p, re.IGNORECASE) for p in self.JAILBREAK_PATTERNS]

    def is_advisory_query(self, query: str) -> Tuple[bool, Optional[str]]:
        """Evaluate incoming query and return (True, reason) if it violates SEBI advisory blocks."""
        if not query or not query.strip():
            return False, None

        q = query.strip()

        # Check jailbreaks / prompt injection
        for p in self.compiled_jailbreaks:
            if p.search(q):
                return True, "Adversarial roleplay or jailbreak directive detected."

        # Check stock advisory and recommendation requests
        for p in self.compiled_advisory:
            if p.search(q):
                return True, "Financial advice or stock recommendation request detected."

        # Check return projections and profit claims
        for p in self.compiled_returns:
            if p.search(q):
                return True, "Return projection or performance guarantee request detected."

        # Check counterfactual / hypothetical returns
        for p in self.compiled_hypothetical:
            if p.search(q):
                return True, "Counterfactual return query detected."

        return False, None

    def get_refusal_response(self) -> str:
        """Return the standard SEBI regulatory refusal statement."""
        return self.STANDARD_REFUSAL_RESPONSE

    def evaluate_query(self, query: str) -> Dict[str, Any]:
        """Perform comprehensive query audit returning compliance status and response."""
        is_advice, reason = self.is_advisory_query(query)
        if is_advice:
            return {
                "is_compliant": False,
                "violation_reason": reason,
                "refusal_response": self.get_refusal_response(),
            }
        return {
            "is_compliant": True,
            "violation_reason": None,
            "refusal_response": None,
        }

    def validate_response_text(self, response_text: str) -> Tuple[bool, Optional[str]]:
        """Verify that an outbound draft response does not contain prohibited advisory terms."""
        lower_resp = response_text.lower()
        for term in self.OUTBOUND_PROHIBITED_WORDS:
            if term in lower_resp:
                return False, f"Outbound response contains prohibited advisory term: '{term}'"
        return True, None


# Global compliance guard singleton
_default_compliance_guard: ComplianceGuard | None = None


def get_compliance_guard() -> ComplianceGuard:
    """Retrieve global singleton ComplianceGuard."""
    global _default_compliance_guard
    if _default_compliance_guard is None:
        _default_compliance_guard = ComplianceGuard()
    return _default_compliance_guard


def is_advisory_query(query: str) -> Tuple[bool, Optional[str]]:
    """Convenience functional interface to check query compliance."""
    return get_compliance_guard().is_advisory_query(query)
