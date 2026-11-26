"""Thematic clustering engine for the Weekly Loop.

Generates dense vector embeddings, executes constrained clustering (hard cap <= 5 themes),
isolates top 3 themes by volume/negative friction, detects the dominant fee confusion theme,
and preserves 100% review ID data lineage. Handles sparse batches (EC-WEEK-01) and zero-fee batches (EC-WEEK-02).
"""

import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple
import numpy as np
from sklearn.cluster import KMeans

from src.config import Settings, get_settings
from src.models.review import ThemeCluster, UserReview
from src.retrieval.corpus_indexer import get_corpus_indexer

logger = logging.getLogger(__name__)


# Comprehensive domain keyword dictionaries for topic categorization
TOPIC_PATTERNS: Dict[str, Dict[str, Any]] = {
    "DP_CHARGES": {
        "title": "DP Charges Surprise on Equity Delivery Sales",
        "keywords": [
            "dp charge", "dp fee", "depository", "cdsl", "nsdl", "15.93",
            "13.50", "rs 15", "demat debit", "scrip charge", "per scrip",
            "selling shares", "sold shares", "sold 1 share", "delivery sell"
        ],
        "is_fee": True,
        "default_summary": (
            "Users perceive flat Depository Participant (DP) debits of Rs. 15.93 per scrip "
            "as unexpected hidden deductions on equity delivery sell trades."
        ),
    },
    "AMC_CHARGES": {
        "title": "Quarterly AMC & Demat Ledger Maintenance Deductions",
        "keywords": [
            "amc", "maintenance charge", "quarterly amc", "88.50", "354",
            "annual maintenance", "bsda", "ledger debit", "idle demat",
            "negative balance", "maintenance fee"
        ],
        "is_fee": True,
        "default_summary": (
            "Users complain of unexpected quarterly demat AMC debits (Rs. 88.50) from ledger balances, "
            "particularly on idle accounts where users expected free maintenance."
        ),
    },
    "APP_LOGIN_LATENCY": {
        "title": "App Login, Biometric & OTP Verification Latency",
        "keywords": [
            "otp", "login", "biometric", "fingerprint", "sms", "gateway",
            "opening bell", "9:15", "stuck", "timeout", "hangs", "crash",
            "lag", "slow loading"
        ],
        "is_fee": False,
        "default_summary": (
            "Severe friction around authentication latency, SMS OTP delivery delays during morning market open, "
            "and intermittent biometric login failures."
        ),
    },
    "KYC_ONBOARDING": {
        "title": "KYC Verification & Account Activation Delays",
        "keywords": [
            "kyc", "onboarding", "verification", "activation", "aadhaar",
            "penny drop", "digilocker", "bank account", "48 hours", "document"
        ],
        "is_fee": False,
        "default_summary": (
            "Delays exceeding 48 hours in automated KYC verification, DigiLocker timeouts, "
            "and uninformative error handling during bank penny-drop validation."
        ),
    },
    "STATUTORY_TAXES": {
        "title": "Statutory Taxes & Regulatory Charges Clarifications",
        "keywords": [
            "stt", "stamp duty", "turnover fee", "sebi charge", "exchange fee",
            "gst", "tax", "0.1%", "statutory", "contract note"
        ],
        "is_fee": True,
        "default_summary": (
            "Confusion regarding statutory and regulatory pass-through levies such as STT on equity delivery "
            "and exchange turnover fees itemized on contract notes."
        ),
    },
    "GENERAL_FEEDBACK": {
        "title": "General Platform Usability & Account Services",
        "keywords": [
            "support", "customer service", "help", "order", "funds", "portfolio",
            "watchlist", "ui", "interface"
        ],
        "is_fee": False,
        "default_summary": (
            "General customer feedback regarding account features, support turnaround time, and platform usability."
        ),
    },
}

ALL_FEE_KEYWORDS: Set[str] = {
    "dp", "depository", "cdsl", "nsdl", "amc", "maintenance", "brokerage",
    "stt", "tax", "charge", "charges", "fee", "fees", "cost", "deduction",
    "deducted", "hidden", "levy", "stamp duty", "gst", "turnover", "15.93",
    "13.50", "88.50", "354"
}


class ClusteringEngine:
    """Constrained thematic clustering engine with lineage tracking and fee friction isolation."""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.max_themes = self.settings.MAX_THEMES_CAP  # Hard cap <= 5
        self.top_themes_count = self.settings.TOP_THEMES_COUNT  # Top 3

    def _get_embeddings(self, texts: List[str]) -> np.ndarray:
        """Compute or retrieve normalized dense semantic vectors."""
        indexer = get_corpus_indexer()
        embeddings = indexer.model.encode(
            texts,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return embeddings

    def _score_text_for_topics(self, text: str) -> Dict[str, int]:
        """Count keyword hits for each topic in a given text."""
        lower_text = text.lower()
        scores: Dict[str, int] = {}
        for topic_key, topic_info in TOPIC_PATTERNS.items():
            hit_count = sum(1 for kw in topic_info["keywords"] if kw in lower_text)
            scores[topic_key] = hit_count
        return scores

    def _determine_cluster_topic(self, reviews: List[UserReview]) -> Tuple[str, str, bool, float]:
        """Determine best-fitting topic, summary, fee status, and fee density for a review group."""
        combined_scores: Dict[str, int] = {k: 0 for k in TOPIC_PATTERNS}
        fee_mention_count = 0

        for r in reviews:
            text = r.sanitized_text.lower()
            # Topic scores
            for k, hits in self._score_text_for_topics(text).items():
                combined_scores[k] += hits

            # Fee mention check
            words = set(re.findall(r"\b\w+\b", text))
            if words.intersection(ALL_FEE_KEYWORDS) or any(k in text for k in ["dp charge", "amc", "15.93"]):
                fee_mention_count += 1

        fee_density = fee_mention_count / max(1, len(reviews))

        # Best matching topic
        best_topic = max(combined_scores.keys(), key=lambda k: combined_scores[k])
        if combined_scores[best_topic] == 0:
            best_topic = "GENERAL_FEEDBACK"

        topic_info = TOPIC_PATTERNS[best_topic]
        title = topic_info["title"]
        summary = topic_info["default_summary"]
        is_fee_topic = topic_info["is_fee"] or fee_density >= 0.35

        return title, summary, is_fee_topic, fee_density

    def cluster_reviews(
        self,
        reviews: List[UserReview],
        week_identifier: str = "2026-W47",
    ) -> List[ThemeCluster]:
        """Cluster reviews into at most 5 themes, isolating top 3 and fee friction theme.

        Guarantees 100% data lineage and adheres to constraints EC-WEEK-01 and EC-WEEK-02.
        """
        n_reviews = len(reviews)
        if n_reviews == 0:
            logger.warning("Zero reviews provided to cluster_reviews.")
            return []

        # ----------------------------------------------------------------------
        # EC-WEEK-01: Sparse Review Volume Handling
        # ----------------------------------------------------------------------
        if n_reviews < 3:
            # Single consolidated theme
            title, summary, is_fee, fee_density = self._determine_cluster_topic(reviews)
            cluster = ThemeCluster(
                cluster_id=f"cluster_{week_identifier.lower().replace('-', '_')}_01",
                week_identifier=week_identifier,
                theme_title=title,
                review_ids=[r.review_id for r in reviews],
                review_count=n_reviews,
                is_top_three=True,
                is_fee_confusion=is_fee and fee_density >= 0.15,
                summary=summary,
            )
            return [cluster]

        # Determine effective cluster count K <= min(5, n_reviews)
        k_clusters = min(self.max_themes, n_reviews)

        # Generate semantic embeddings
        texts = [r.sanitized_text for r in reviews]
        embeddings = self._get_embeddings(texts)

        # Execute K-Means
        kmeans = KMeans(
            n_clusters=k_clusters,
            random_state=42,
            n_init=10,
        )
        labels = kmeans.fit_predict(embeddings)

        # Partition reviews by cluster label
        grouped_reviews: Dict[int, List[UserReview]] = {i: [] for i in range(k_clusters)}
        for review, label in zip(reviews, labels):
            grouped_reviews[label].append(review)

        # Filter out any empty clusters (defensive safeguard)
        active_groups = [revs for revs in grouped_reviews.values() if revs]

        # ----------------------------------------------------------------------
        # Characterize Each Cluster
        # ----------------------------------------------------------------------
        candidate_clusters: List[Dict[str, Any]] = []
        for idx, rev_group in enumerate(active_groups):
            title, summary, is_fee, fee_density = self._determine_cluster_topic(rev_group)
            rev_ids = [r.review_id for r in rev_group]

            # Calculate severity and ranking score
            ratings = [r.rating for r in rev_group if r.rating is not None]
            avg_rating = float(np.mean(ratings)) if ratings else 2.5
            volume = len(rev_group)

            # High volume and lower ratings yield higher priority
            severity_factor = max(0.5, 5.0 - avg_rating)
            rank_score = (volume * 1.5) + (severity_factor * volume)

            candidate_clusters.append({
                "index": idx,
                "title": title,
                "summary": summary,
                "review_ids": rev_ids,
                "volume": volume,
                "is_fee": is_fee,
                "fee_density": fee_density,
                "rank_score": rank_score,
                "avg_rating": avg_rating,
            })

        # Ensure unique titles if multiple clusters mapped to the same topic
        used_titles: Set[str] = set()
        for cand in candidate_clusters:
            base_title = cand["title"]
            if base_title in used_titles:
                cand["title"] = f"{base_title} (Part {cand['index'] + 1})"
            used_titles.add(cand["title"])

        # ----------------------------------------------------------------------
        # Rank Themes: Isolate Top 3 and Fee Friction Theme
        # ----------------------------------------------------------------------
        # Sort descending by rank_score
        candidate_clusters.sort(key=lambda c: c["rank_score"], reverse=True)

        # Identify dominant fee confusion theme
        # EC-WEEK-02: Overall fee friction across entire batch
        total_fee_reviews = sum(
            1 for r in reviews
            if set(re.findall(r"\b\w+\b", r.sanitized_text.lower())).intersection(ALL_FEE_KEYWORDS)
        )
        batch_fee_density = total_fee_reviews / n_reviews
        has_fee_friction = batch_fee_density >= 0.15

        fee_cluster_index: Optional[int] = None
        if has_fee_friction:
            # Find candidate with highest fee density
            fee_candidates = [c for c in candidate_clusters if c["fee_density"] > 0]
            if fee_candidates:
                top_fee_cand = max(fee_candidates, key=lambda c: (c["fee_density"], c["volume"]))
                fee_cluster_index = top_fee_cand["index"]

        # Build final ThemeCluster objects
        final_clusters: List[ThemeCluster] = []
        for rank_pos, cand in enumerate(candidate_clusters, start=1):
            is_top_3 = rank_pos <= self.top_themes_count
            is_fee_conf = (cand["index"] == fee_cluster_index) if fee_cluster_index is not None else False

            cluster_id = f"cluster_{week_identifier.lower().replace('-', '_')}_{rank_pos:02d}"
            cluster = ThemeCluster(
                cluster_id=cluster_id,
                week_identifier=week_identifier,
                theme_title=cand["title"],
                review_ids=cand["review_ids"],
                review_count=cand["volume"],
                is_top_three=is_top_3,
                is_fee_confusion=is_fee_conf,
                summary=cand["summary"],
            )
            final_clusters.append(cluster)

        # Enforce hard cap <= 5
        if len(final_clusters) > self.max_themes:
            final_clusters = final_clusters[:self.max_themes]

        logger.info(
            "Created %d theme clusters for %s (top 3 marked: %d, fee friction marked: %s)",
            len(final_clusters),
            week_identifier,
            sum(1 for c in final_clusters if c.is_top_three),
            any(c.is_fee_confusion for c in final_clusters),
        )

        return final_clusters


def cluster_reviews(
    reviews: List[UserReview],
    week_identifier: str = "2026-W47",
) -> List[ThemeCluster]:
    """Convenience functional interface for thematic clustering."""
    engine = ClusteringEngine()
    return engine.cluster_reviews(reviews, week_identifier=week_identifier)
