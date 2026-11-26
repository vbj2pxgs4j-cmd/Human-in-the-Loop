"""Weekly Pulse generator component for the Weekly Loop.

Synthesizes an executive product intelligence report strictly constrained to <= 250 words,
containing 2-3 verbatim user quotes citing (Review #ID), exactly 3 concrete action recommendations,
and guaranteeing 100% data lineage (EC-WEEK-03, EC-WEEK-04).
"""

import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from src.config import Settings, get_settings
from src.models.review import ThemeCluster, UserReview, WeeklyPulse

logger = logging.getLogger(__name__)


def count_words(text: str) -> int:
    """Measure exact word count using whitespace splitting matching Pydantic validator."""
    return len(text.strip().split())


class PulseGenerator:
    """Executive weekly intelligence report generator with strict length caps and quote lineage."""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.max_words = self.settings.WEEKLY_PULSE_MAX_WORDS  # 250 words

    def _select_supporting_quotes(
        self,
        reviews: List[UserReview],
        clusters: List[ThemeCluster],
        max_quotes: int = 3,
    ) -> List[str]:
        """Select 2-3 verbatim quotes directly from top theme reviews with parenthetical citations."""
        review_map = {r.review_id: r for r in reviews}
        selected_quotes: List[str] = []
        used_review_ids: Set[str] = set()

        # Prioritize reviews from the fee confusion theme and top 3 themes
        priority_clusters = [c for c in clusters if c.is_fee_confusion] + [
            c for c in clusters if c.is_top_three and not c.is_fee_confusion
        ]
        if not priority_clusters:
            priority_clusters = clusters

        for cluster in priority_clusters:
            for rev_id in cluster.review_ids:
                if rev_id in used_review_ids:
                    continue
                rev = review_map.get(rev_id)
                if not rev or not rev.sanitized_text:
                    continue

                text = rev.sanitized_text.strip()
                # Find a punchy sentence or short snippet (<= 140 chars)
                sentences = [
                    s.strip()
                    for s in re.split(r"[.!?]+", text)
                    if 15 <= len(s.strip()) <= 130
                ]
                quote_body = sentences[0] if sentences else text[:110].strip()
                if quote_body:
                    # Clean punctuation at ends
                    clean_quote = quote_body.strip('"\' ')
                    formatted = f'"{clean_quote}." (Review #{rev_id})'
                    selected_quotes.append(formatted)
                    used_review_ids.add(rev_id)

                if len(selected_quotes) >= max_quotes:
                    break
            if len(selected_quotes) >= max_quotes:
                break

        # Fallback if no quotes selected from clusters
        if len(selected_quotes) < 2 and reviews:
            for rev in reviews:
                if rev.review_id not in used_review_ids and rev.sanitized_text:
                    snippet = rev.sanitized_text[:90].strip().strip('"\' ')
                    formatted = f'"{snippet}." (Review #{rev.review_id})'
                    selected_quotes.append(formatted)
                    used_review_ids.add(rev.review_id)
                    if len(selected_quotes) >= 2:
                        break

        return selected_quotes[:max_quotes]

    def _generate_action_ideas(
        self,
        top_clusters: List[ThemeCluster],
        has_fee_confusion: bool,
    ) -> List[str]:
        """Generate strictly three (3) concrete product recommendations addressing friction."""
        ideas: List[str] = []

        if has_fee_confusion:
            ideas.append(
                "Implement an in-app upfront fee breakdown modal on the sell confirmation screen explaining DP charges."
            )

        # Examine top cluster titles to generate targeted action ideas
        titles = " ".join([c.theme_title for c in top_clusters]).lower()

        if "amc" in titles or "maintenance" in titles:
            ideas.append(
                "Send proactive notification 7 days before quarterly AMC deductions detailing BSDA eligibility."
            )
        if "otp" in titles or "login" in titles or "latency" in titles:
            ideas.append(
                "Add secondary SMS/WhatsApp gateway redundancy to eliminate morning login authentication timeouts."
            )
        if "kyc" in titles or "onboarding" in titles:
            ideas.append(
                "Automate instant penny-drop failure diagnostics with clear actionable guidance for rejected bank accounts."
            )
        if "tax" in titles or "stt" in titles:
            ideas.append(
                "Add a pre-trade tax estimator widget detailing statutory STT and exchange fees."
            )

        # Fill up or trim to strictly 3 ideas
        default_fallback_ideas = [
            "Introduce an in-app post-trade fee breakdown popup for first-time delivery sellers.",
            "Upgrade authentication gateway with multi-provider failover during peak morning hours.",
            "Revamp onboarding verification with automated real-time document validation checks.",
        ]

        for fallback in default_fallback_ideas:
            if len(ideas) >= 3:
                break
            if fallback not in ideas:
                ideas.append(fallback)

        return ideas[:3]

    def _enforce_word_cap(self, text: str, max_words: int = 250) -> str:
        """EC-WEEK-03: Truncate / trim narrative text to guarantee word count <= 250 words."""
        words = text.split()
        if len(words) <= max_words:
            return text

        # Sentence-by-sentence trimming while preserving core executive message
        sentences = [s.strip() for s in text.split(". ") if s.strip()]
        trimmed_sentences: List[str] = []
        curr_count = 0

        for sent in sentences:
            sent_words = sent.split()
            if curr_count + len(sent_words) + 1 <= max_words:
                trimmed_sentences.append(sent)
                curr_count += len(sent_words)
            else:
                break

        if trimmed_sentences:
            result = ". ".join(trimmed_sentences)
            if not result.endswith("."):
                result += "."
            return result

        # Hard slice fallback
        return " ".join(words[:max_words])

    def generate_pulse(
        self,
        reviews: List[UserReview],
        clusters: List[ThemeCluster],
        week_identifier: str = "2026-W47",
        escalated_topics: Optional[List[str]] = None,
    ) -> WeeklyPulse:
        """Synthesize executive weekly report adhering to word cap, quotes, and 3 action ideas."""
        top_clusters = [c for c in clusters if c.is_top_three] or clusters[:3]
        fee_cluster = next((c for c in clusters if c.is_fee_confusion), None)
        fee_theme_id = fee_cluster.cluster_id if fee_cluster else None

        # 1. Select supporting quotes with strict review ID lineage (EC-WEEK-04)
        quotes = self._select_supporting_quotes(reviews, clusters, max_quotes=3)

        # 2. Formulate strictly 3 action ideas
        action_ideas = self._generate_action_ideas(top_clusters, fee_cluster is not None)

        # 3. Draft executive synthesis narrative
        top_titles = [c.theme_title for c in top_clusters[:3]]
        titles_str = "; ".join(top_titles) if top_titles else "General feedback"

        # Build concise executive synthesis (< 180 words initially to allow headroom)
        narrative_parts = [
            f"Executive Intelligence Pulse for week {week_identifier}.",
            f"Analysis of {len(reviews)} customer touchpoints across {len(clusters)} distinct operational themes.",
            f"Top friction drivers: {titles_str}.",
        ]

        if fee_cluster:
            narrative_parts.append(
                f"Fee confusion represented the primary user grievance: {fee_cluster.summary}"
            )
        else:
            narrative_parts.append(
                "Fee inquiries remained within normal baselines; focus centered on platform reliability and onboarding."
            )

        # Optional Phase 4 Bridge Integration: Escalated High-Frequency Topics
        if escalated_topics:
            esc_str = ", ".join(escalated_topics[:2])
            narrative_parts.append(
                f"High-Frequency Support Inquiries escalated to product: {esc_str}."
            )

        narrative_parts.append(
            "Customer sentiment demands immediate clarity on transaction debits and authentication resilience."
        )

        pulse_text = " ".join(narrative_parts)

        # 4. Enforce strict <= 250 words cap (EC-WEEK-03)
        pulse_text = self._enforce_word_cap(pulse_text, max_words=self.max_words)
        word_count = count_words(pulse_text)

        pulse_id = f"pulse_{week_identifier.lower().replace('-', '_')}"

        pulse = WeeklyPulse(
            pulse_id=pulse_id,
            week_identifier=week_identifier,
            pulse_text=pulse_text,
            word_count=word_count,
            supporting_quotes=quotes,
            action_ideas=action_ideas,
            top_theme_ids=[c.cluster_id for c in top_clusters],
            fee_confusion_theme_id=fee_theme_id,
            approval_status="PENDING_APPROVAL",
        )

        logger.info(
            "Generated WeeklyPulse %s: %d words, %d quotes, %d action ideas",
            pulse_id,
            pulse.word_count,
            len(pulse.supporting_quotes),
            len(pulse.action_ideas),
        )

        return pulse

    @staticmethod
    def validate_quote_lineage(pulse: WeeklyPulse, reviews: List[UserReview]) -> bool:
        """EC-WEEK-04 Lineage Check: Verifies that every quote references a legitimate review ID.

        Confirms that the cited text exists within the referenced review in the active batch.
        """
        review_map = {r.review_id: r.sanitized_text for r in reviews}
        quote_pattern = re.compile(r'\s*\(Review\s*#([A-Za-z0-9_\-]+)\)')

        for quote in pulse.supporting_quotes:
            match = quote_pattern.search(quote)
            if not match:
                logger.error("Quote missing valid (Review #ID) format: %s", quote)
                return False

            cited_id = match.group(1)
            if cited_id not in review_map:
                logger.error("Cited review ID '%s' does not exist in batch reviews.", cited_id)
                return False

            # Extract the quoted snippet text
            quote_text = quote[: match.start()].strip().strip('"\' ')
            # Remove trailing period if present
            quote_clean = quote_text.rstrip(".")
            actual_text = review_map[cited_id]

            # Verify substantial substring presence
            if quote_clean.lower() not in actual_text.lower():
                # Allow minor punctuation variation or words presence check
                words = [w.lower() for w in re.findall(r"\b\w+\b", quote_clean)]
                matches = sum(1 for w in words if w in actual_text.lower())
                if not words or (matches / len(words)) < 0.85:
                    logger.error(
                        "Quote content '%s' not grounded in review %s: '%s'",
                        quote_clean,
                        cited_id,
                        actual_text,
                    )
                    return False

        return True


def generate_weekly_pulse(
    reviews: List[UserReview],
    clusters: List[ThemeCluster],
    week_identifier: str = "2026-W47",
    escalated_topics: Optional[List[str]] = None,
) -> WeeklyPulse:
    """Convenience functional interface for generating WeeklyPulse."""
    generator = PulseGenerator()
    return generator.generate_pulse(
        reviews=reviews,
        clusters=clusters,
        week_identifier=week_identifier,
        escalated_topics=escalated_topics,
    )
