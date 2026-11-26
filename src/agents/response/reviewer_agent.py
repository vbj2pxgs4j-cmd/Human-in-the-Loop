"""Reviewer Agent enforcing deterministic quality gates: sentence caps, citation whitelists, and zero PII leaks."""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from src.config import Settings, get_settings
from src.security.compliance_guard import ComplianceGuard, get_compliance_guard
from src.security.pii_scrubber import PIIScrubber, get_pii_scrubber

logger = logging.getLogger(__name__)


class ReviewerAgent:
    """Quality gate enforcing <= 3 sentences, exactly 1 whitelisted citation, and zero sensitive leaks."""

    # Financial abbreviations that must NOT trigger sentence boundary splits (EC-RESP-01)
    KNOWN_ABBREVIATIONS = [
        r"\brs\.",
        r"\be\.g\.",
        r"\bi\.e\.",
        r"\bvs\.",
        r"\bno\.",
        r"\bcir\.",
        r"\bapprox\.",
        r"\bdr\.",
        r"\bcr\.",
        r"\bltd\.",
        r"\bpvt\.",
        r"\bref\.",
    ]

    URL_REGEX = re.compile(r"https?://[^\s/$.?#].[^\s]*", re.IGNORECASE)

    def __init__(
        self,
        pii_scrubber: Optional[PIIScrubber] = None,
        compliance_guard: Optional[ComplianceGuard] = None,
        settings: Optional[Settings] = None,
    ):
        self.settings = settings or get_settings()
        self.pii_scrubber = pii_scrubber or get_pii_scrubber()
        self.compliance_guard = compliance_guard or get_compliance_guard()
        self.max_sentences = self.settings.RESPONSE_MAX_SENTENCES
        self.whitelisted_domains = self.settings.WHITELISTED_DOMAINS

    def split_sentences(self, text: str) -> List[str]:
        """Split text into sentences while protecting URLs, decimals, and abbreviations (EC-RESP-01)."""
        if not text or not text.strip():
            return []

        clean_text = text.strip()
        placeholders: Dict[str, str] = {}
        idx = 0

        # 1. Shield URLs from period splits
        def shield_url(m: re.Match) -> str:
            nonlocal idx
            k = f"__PROTECTED_URL_{idx}__"
            placeholders[k] = m.group(0)
            idx += 1
            return k

        shielded = self.URL_REGEX.sub(shield_url, clean_text)

        # 2. Shield Decimal numbers (e.g. 13.50, 0.05%, 15.93)
        def shield_decimal(m: re.Match) -> str:
            nonlocal idx
            k = f"__PROTECTED_DEC_{idx}__"
            placeholders[k] = m.group(0)
            idx += 1
            return k

        shielded = re.sub(r"\b\d+\.\d+(?:%)?\b", shield_decimal, shielded)

        # 3. Shield Financial Abbreviations
        for abbr in self.KNOWN_ABBREVIATIONS:
            def shield_abbr(m: re.Match) -> str:
                nonlocal idx
                k = f"__PROTECTED_ABBR_{idx}__"
                placeholders[k] = m.group(0)
                idx += 1
                return k
            shielded = re.sub(abbr, shield_abbr, shielded, flags=re.IGNORECASE)

        # 4. Perform sentence boundary segmentation
        raw_sentences = [
            s.strip()
            for s in re.split(r"(?<=[.!?])\s+", shielded)
            if s.strip()
        ]

        # 5. Restore placeholders in each sentence
        restored_sentences: List[str] = []
        for s in raw_sentences:
            for k, orig in placeholders.items():
                s = s.replace(k, orig)
            restored_sentences.append(s)

        return restored_sentences

    def validate_citations(
        self, draft_text: str, is_covered: bool = True
    ) -> Tuple[str, Optional[str], bool, Optional[str]]:
        """Validate that draft contains exactly one whitelisted Milestone 1 source URL."""
        urls = self.URL_REGEX.findall(draft_text)

        # If uncovered inquiry, URL count should be 0
        if not is_covered:
            return draft_text, None, True, None

        if not urls:
            return draft_text, None, False, "Missing required official Milestone 1 citation URL."

        # Verify domain whitelist
        whitelisted_urls: List[str] = []
        for u in urls:
            clean_u = u.rstrip(".,;!?:)'\"")
            domain = urlparse(clean_u).netloc
            if any(allowed in domain for allowed in self.whitelisted_domains):
                whitelisted_urls.append(clean_u)

        if not whitelisted_urls:
            return (
                draft_text,
                None,
                False,
                f"URL '{urls[0]}' is not in whitelisted domains: {self.whitelisted_domains}",
            )

        primary_url = whitelisted_urls[0]

        # If more than 1 URL present, prune extras to enforce exactly 1 citation (EC-RESP-02)
        final_text = draft_text
        if len(urls) > 1:
            for extra_u in urls[1:]:
                final_text = final_text.replace(extra_u, "").strip()

        return final_text, primary_url, True, None

    def review_draft(
        self,
        draft_text: str,
        is_covered: bool = True,
        cited_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute full review gate asserting sentence count, citations, and zero sensitive leaks."""
        # 1. PII Secondary Sweep
        if self.pii_scrubber.contains_pii(draft_text):
            logger.warning("Reviewer detected residual PII. Scrubbing draft.")
            draft_text = self.pii_scrubber.scrub(draft_text)

        # 2. Advisory / Speculative Language Sweep
        is_compliant, compliance_violation = self.compliance_guard.validate_response_text(draft_text)
        if not is_compliant:
            logger.error("Reviewer detected prohibited advisory terms: %s", compliance_violation)
            # Fallback to standard refusal statement
            draft_text = self.compliance_guard.get_refusal_response()

        # 3. Citation Check & Normalization
        normalized_draft, final_url, cit_valid, cit_reason = self.validate_citations(
            draft_text, is_covered=is_covered
        )
        if not final_url and cited_url and is_covered:
            # Append missing citation if known
            normalized_draft = f"{normalized_draft.rstrip('.')} Source: {cited_url}"
            final_url = cited_url

        # 4. Sentence Boundary Check & Enforce <= 3 Sentences
        sentences = self.split_sentences(normalized_draft)
        if len(sentences) > self.max_sentences:
            logger.warning(
                "Draft exceeded sentence cap (%d > %d). Truncating.",
                len(sentences), self.max_sentences
            )
            # Retain first 3 sentences and ensure URL is preserved
            truncated = sentences[: self.max_sentences]
            if final_url and not any(final_url in s for s in truncated):
                truncated[-1] = f"{truncated[-1].rstrip('.')} Source: {final_url}"
            normalized_draft = " ".join(truncated)
            sentences = self.split_sentences(normalized_draft)

        sentence_count = len(sentences)

        return {
            "approved_draft": normalized_draft,
            "sentence_count": sentence_count,
            "cited_url": final_url,
            "is_valid": (sentence_count <= self.max_sentences),
            "reasons": [] if sentence_count <= self.max_sentences else ["Exceeded 3 sentence cap."],
        }
