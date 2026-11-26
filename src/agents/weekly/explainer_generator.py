"""Canonical Fee Explainer generator component for the Weekly Loop.

Synthesizes product-approved canonical fee explainers grounded in Milestone 1 disclosures.
Enforces strict constraints: <= 6 bullets, >= 2 official source links, current ISO-8601 last_checked_date,
and handles zero-fee complaint batches with historical fallback (EC-WEEK-02).
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.config import Settings, get_settings
from src.models.explainer import CanonicalExplainer
from src.models.review import ThemeCluster
from src.retrieval.corpus_indexer import get_corpus_indexer

logger = logging.getLogger(__name__)


# Template definitions strictly grounded in Milestone 1 official documentation
EXPLAINER_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "dp-charges": {
        "title": "Canonical Fee Explainer: Depository Participant (DP) Charges on Equity Delivery Sales",
        "topic_slug": "dp-charges",
        "bullets": [
            "Depository Participant (DP) charge is an administrative fee of flat Rs. 13.50 + 18% GST (total Rs. 15.93) levied whenever shares are debited from your demat account upon selling.",
            "DP charges apply strictly to equity delivery sell transactions; buying shares and intraday trades incur zero DP charges.",
            "The fee is charged flat per company (scrip) per trading day, irrespective of whether you sell 1 share or 1,000 shares.",
            "Selling shares of multiple distinct companies on the same day incurs a separate DP charge per company.",
            "The collected fee is split between depositories (CDSL/NSDL) and the platform to maintain secure digital demat infrastructure.",
        ],
        "source_urls": [
            "https://cdslindia.com/charges",
            "https://platform.in/charges",
        ],
    },
    "amc-charges": {
        "title": "Canonical Fee Explainer: Demat Annual Maintenance Charges (AMC) & BSDA Rules",
        "topic_slug": "amc-charges",
        "bullets": [
            "Standard Demat Annual Maintenance Charge (AMC) is flat Rs. 300 per year + 18% GST (total Rs. 354 per year).",
            "AMC is debited on a quarterly schedule at Rs. 75 + 18% GST (Rs. 88.50 per quarter) directly from your account ledger.",
            "Basic Services Demat Accounts (BSDA) with total portfolio holdings under Rs. 4,00,000 qualify for Rs. 0 annual maintenance.",
            "Trading and demat account opening on the platform is 100% free with zero documentation or subscription charges.",
            "Physical quarterly account holding statements delivered by post incur a Rs. 20 + GST courier charge, while digital statements via email are free.",
        ],
        "source_urls": [
            "https://platform.in/terms",
            "https://platform.in/charges",
        ],
    },
    "statutory-stt-charges": {
        "title": "Canonical Fee Explainer: Securities Transaction Tax (STT) & Regulatory Levies",
        "topic_slug": "statutory-stt-charges",
        "bullets": [
            "Securities Transaction Tax (STT) is a statutory central tax of 0.1% levied on both buy and sell sides of equity delivery trade value.",
            "Intraday equity trades incur a lower STT rate of 0.025% charged strictly on the sell side (zero on buy side).",
            "State stamp duty of 0.015% is collected centrally on equity delivery buy transactions only.",
            "Standard 18% GST applies strictly on brokerage, SEBI turnover fees, exchange transaction fees, and DP charges, never on share value or STT.",
        ],
        "source_urls": [
            "https://sebi.gov.in/charges",
            "https://platform.in/charges",
        ],
    },
    "brokerage-delivery": {
        "title": "Canonical Fee Explainer: Zero Brokerage Equity Delivery & F&O Tariffs",
        "topic_slug": "brokerage-delivery",
        "bullets": [
            "Equity delivery trading on our platform is 100% brokerage-free with flat Rs. 0 commission on all buy and sell trades.",
            "Equity intraday trades incur flat Rs. 20 or 0.05% per executed order (whichever is lower).",
            "Futures and Options (F&O) contracts are charged at flat Rs. 20 per executed order across all derivative segments.",
            "Call & Trade desk orders and automated RMS square-off orders incur an additional charge of Rs. 50 + 18% GST per order.",
        ],
        "source_urls": [
            "https://platform.in/charges",
            "https://sebi.gov.in/charges",
        ],
    },
}


class ExplainerGenerator:
    """Synthesizer for product-approved canonical fee explainers."""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.max_bullets = self.settings.EXPLAINER_MAX_BULLETS  # 6 bullets
        self.min_links = self.settings.EXPLAINER_MIN_LINKS      # 2 links

    def _match_template_key(self, theme_title: str) -> str:
        """Map a theme title or query to the best-matching canonical explainer template."""
        lower = theme_title.lower()
        if any(w in lower for w in ["dp", "cdsl", "nsdl", "15.93", "13.50", "depository"]):
            return "dp-charges"
        if any(w in lower for w in ["amc", "maintenance", "quarterly", "88.50", "354"]):
            return "amc-charges"
        if any(w in lower for w in ["stt", "stamp", "tax", "turnover", "regulatory"]):
            return "statutory-stt-charges"
        if any(w in lower for w in ["brokerage", "delivery", "f&o", "intraday"]):
            return "brokerage-delivery"
        return "dp-charges"

    def _compute_embedding(self, text: str) -> Optional[List[float]]:
        """Compute dense vector representation of explainer for Phase 4 fast lookup."""
        try:
            indexer = get_corpus_indexer()
            vec = indexer.model.encode(
                text,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            return vec.tolist()
        except Exception as e:
            logger.warning("Failed to compute explainer embedding: %s", e)
            return None

    def generate_explainer(
        self,
        fee_cluster: Optional[ThemeCluster] = None,
        force_topic: Optional[str] = None,
        zero_fee_fallback: bool = False,
    ) -> CanonicalExplainer:
        """Generate a canonical fee explainer adhering to <= 6 bullets and >= 2 official links.

        Handles EC-WEEK-02 by falling back to historical fee topic if zero fee complaints detected.
        """
        # Determine topic key
        if force_topic and force_topic in EXPLAINER_TEMPLATES:
            template_key = force_topic
            is_fallback = zero_fee_fallback
        elif fee_cluster and fee_cluster.is_fee_confusion:
            template_key = self._match_template_key(fee_cluster.theme_title)
            is_fallback = False
        else:
            # EC-WEEK-02: Zero fee complaints detected in batch
            template_key = "dp-charges"
            is_fallback = True

        template = EXPLAINER_TEMPLATES[template_key]
        title = template["title"]
        bullets = list(template["bullets"])
        source_urls = list(template["source_urls"])

        # EC-WEEK-02 Note enforcement if zero fee complaints were detected
        if is_fallback:
            fallback_note = (
                "Note: Zero fee complaints detected in current weekly batch. "
                "Explainer generated for top historical query topic."
            )
            # Insert disclaimer as the first bullet while respecting the <= 6 cap
            bullets = [fallback_note] + bullets

        # Enforce <= 6 bullets constraint
        if len(bullets) > self.max_bullets:
            bullets = bullets[:self.max_bullets]

        # Enforce >= 2 unique valid source URLs
        unique_urls = list(dict.fromkeys(source_urls))
        if len(unique_urls) < self.min_links:
            # Fallback to general platform charges URL to ensure >= 2 links
            unique_urls.append("https://platform.in/charges")

        topic_slug = template["topic_slug"]
        explainer_id = f"expl_{topic_slug.replace('-', '_')}"
        last_checked = datetime.now(timezone.utc)

        # Compute embedding text over title and bullets
        combined_text = f"{title}\n" + "\n".join(bullets)
        embedding = self._compute_embedding(combined_text)

        explainer = CanonicalExplainer(
            explainer_id=explainer_id,
            topic_slug=topic_slug,
            title=title,
            bullet_points=bullets,
            bullet_count=len(bullets),
            source_urls=unique_urls,
            last_checked_date=last_checked,
            status="DRAFT",
            embedding=embedding,
        )

        logger.info(
            "Synthesized CanonicalExplainer %s: %d bullets, %d official links (fallback=%s)",
            explainer_id,
            explainer.bullet_count,
            len(explainer.source_urls),
            is_fallback,
        )

        return explainer


def generate_canonical_explainer(
    fee_cluster: Optional[ThemeCluster] = None,
    force_topic: Optional[str] = None,
    zero_fee_fallback: bool = False,
) -> CanonicalExplainer:
    """Convenience functional interface for generating CanonicalExplainer."""
    generator = ExplainerGenerator()
    return generator.generate_explainer(
        fee_cluster=fee_cluster,
        force_topic=force_topic,
        zero_fee_fallback=zero_fee_fallback,
    )
