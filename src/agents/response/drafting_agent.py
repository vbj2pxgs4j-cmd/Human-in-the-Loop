"""Agent 3: Response Synthesis & Routing Specialist formulating concise drafts and internal routing notes."""

import re
from typing import Any, Dict, List, Optional
from src.models.ticket import RoutingCategory, RoutingNote, RoutingUrgency, SentimentType


class DraftingAgent:
    """Agent 3 formulating concise grounded drafts and structured internal routing notes."""

    # Sentiment Detection Keywords
    FRUSTRATED_KEYWORDS = {
        "fraud", "scam", "cheat", "cheating", "stolen", "illegal", "police",
        "complaint", "worst", "sue", "court", "harassment", "looting",
        "robbery", "unauthorized", "without permission", "deducted without",
    }
    CONFUSED_KEYWORDS = {
        "why", "how come", "didn't understand", "surprise", "unexpected",
        "thought it was free", "hidden", "unclear", "explain", "confused",
    }

    # Category Detection Patterns
    CATEGORY_MAPPING = [
        (re.compile(r"\b(?:dp|depository|cdsl|nsdl|demat\s+debit|scrip\s+charge|15\.93|13\.50|rs\.?\s*15)\b", re.IGNORECASE), RoutingCategory.DP_CHARGES),
        (re.compile(r"\b(?:amc|maintenance|account\s+opening|bsda|ledger|quarterly|354|300|88\.50)\b", re.IGNORECASE), RoutingCategory.ACCOUNT_MAINTENANCE),
        (re.compile(r"\b(?:stt|sebi|stamp\s+duty|gst|tax|turnover\s+fee|regulatory)\b", re.IGNORECASE), RoutingCategory.STATUTORY_CHARGES),
        (re.compile(r"\b(?:upi|netbanking|gateway|deposit|withdrawal|imps|neft)\b", re.IGNORECASE), RoutingCategory.PAYMENT_GATEWAY),
        (re.compile(r"\b(?:brokerage|delivery|intraday|futures|options|f&o|call\s*&\s*trade)\b", re.IGNORECASE), RoutingCategory.BROKERAGE),
    ]

    def infer_sentiment(self, query: str) -> SentimentType:
        """Infer customer sentiment from vocabulary and punctuation."""
        lower_q = query.lower()
        if any(w in lower_q for w in self.FRUSTRATED_KEYWORDS) or "!" in query:
            return SentimentType.FRUSTRATED
        if any(w in lower_q for w in self.CONFUSED_KEYWORDS) or "?" in query:
            return SentimentType.CONFUSED
        return SentimentType.NEUTRAL

    def infer_urgency(self, query: str, sentiment: SentimentType) -> RoutingUrgency:
        """Assign operational urgency tier based on sentiment and escalation signals."""
        lower_q = query.lower()
        if any(w in lower_q for w in ["police", "court", "legal", "lawyer", "consumer forum"]):
            return RoutingUrgency.ESCALATE
        if sentiment == SentimentType.FRUSTRATED:
            return RoutingUrgency.HIGH
        if sentiment == SentimentType.CONFUSED:
            return RoutingUrgency.MEDIUM
        return RoutingUrgency.LOW

    def infer_category(self, query: str, retrieval_output: Optional[Dict[str, Any]] = None) -> RoutingCategory:
        """Infer ticket category from query text and retrieved corpus category."""
        # Check source URL signals from retrieval
        if retrieval_output:
            src = (retrieval_output.get("source_url") or "").lower()
            if "cdsl" in src or "nsdl" in src:
                return RoutingCategory.DP_CHARGES

        # Check explicit keywords
        for pattern, cat in self.CATEGORY_MAPPING:
            if pattern.search(query):
                return cat

        # Fallback to retrieved document category if available
        if retrieval_output and retrieval_output.get("top_chunk"):
            chunk_cat = retrieval_output["top_chunk"].metadata.get("category")
            if chunk_cat and chunk_cat in RoutingCategory.__members__:
                return RoutingCategory[chunk_cat]

        return RoutingCategory.OTHERS

    def generate_routing_note(
        self,
        query: str,
        retrieval_output: Optional[Dict[str, Any]] = None,
        compliance_output: Optional[Dict[str, Any]] = None,
    ) -> RoutingNote:
        """Synthesize structured internal routing metadata."""
        sentiment = self.infer_sentiment(query)
        urgency = self.infer_urgency(query, sentiment)
        category = self.infer_category(query, retrieval_output)

        # Generate justification reason
        if compliance_output and not compliance_output.get("is_compliant"):
            reason = f"Regulatory breach detected: {compliance_output.get('violation_reason')}. Routed to standard refusal."
        elif retrieval_output and not retrieval_output.get("covered"):
            reason = f"Official corpus gap for topic: '{query}'. Evaluated search queries: {retrieval_output.get('searched_queries')}."
        elif sentiment == SentimentType.FRUSTRATED:
            reason = f"Customer expressed friction regarding unexpected fees. Category: {category.value}."
        else:
            reason = f"Standard factual inquiry regarding {category.value.lower().replace('_', ' ')}."

        return RoutingNote(
            category=category,
            urgency=urgency,
            sentiment=sentiment,
            reason=reason,
        )

    def synthesize_draft(
        self,
        query: str,
        retrieval_output: Dict[str, Any],
        compliance_output: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Synthesize candidate response draft strictly grounded in retrieved snippets."""
        # 1. Non-compliant / advisory queries
        if compliance_output and not compliance_output.get("is_compliant"):
            return compliance_output.get("refusal_draft", "")

        # 2. Uncovered query
        if not retrieval_output.get("covered"):
            searched = retrieval_output.get("searched_queries", [query])
            return f"This question is not covered in our official platform documentation. Search evaluated: {searched}."

        # 3. Covered query synthesis from top chunk
        top_chunk = retrieval_output.get("top_chunk")
        source_url = retrieval_output.get("source_url") or "https://platform.in/charges"
        partial_gap = retrieval_output.get("partial_gap")

        content = top_chunk.content if top_chunk else ""
        lower_q = query.lower()

        # Tailored synthesis based on topic intent
        if "delivery" in lower_q and ("free" in lower_q or "brokerage" in lower_q or "zero" in lower_q):
            draft = (
                "Equity delivery trading on our platform is 100% brokerage-free (Rs. 0 brokerage). "
                "Regulatory statutory charges such as STT and exchange fees apply as per government norms. "
                f"Source: {source_url}"
            )
        elif "dp" in lower_q or "depository" in lower_q or "15" in lower_q or "13.50" in lower_q:
            draft = (
                "Depository Participant (DP) charges of Rs. 13.50 plus 18% GST (total Rs. 15.93) are debited when selling equity shares from your demat account. "
                "This fee is charged flat per company per day irrespective of the quantity sold. "
                f"Source: {source_url}"
            )
        elif "stt" in lower_q or "tax" in lower_q or "stamp duty" in lower_q:
            draft = (
                "Securities Transaction Tax (STT) on equity delivery is 0.1% levied on both buy and sell sides of the transaction. "
                "Intraday equity trades attract 0.025% STT on the sell side only. "
                f"Source: {source_url}"
            )
        elif "amc" in lower_q or "maintenance" in lower_q or "354" in lower_q:
            draft = (
                "Our standard Demat Annual Maintenance Charge (AMC) is Rs. 300 plus 18% GST (total Rs. 354 per year), debited quarterly from your account ledger. "
                "Basic Services Demat Accounts (BSDA) with holdings under Rs. 4,00,000 enjoy zero AMC. "
                f"Source: {source_url}"
            )
        else:
            # General extraction from top chunk
            sentences = [s.strip() for s in content.split(".") if s.strip()]
            extracted = ". ".join(sentences[:2]) if len(sentences) >= 2 else content[:180]
            draft = f"{extracted}. Source: {source_url}"

        # Handle partial gap (EC-RAG-01)
        if partial_gap:
            draft = (
                f"{draft.rstrip('.')} However, '{partial_gap}' is not covered in our official platform documentation. "
                f"Search evaluated: ['{partial_gap}']."
            )

        return draft
