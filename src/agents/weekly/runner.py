"""Unattended Weekly Loop pipeline runner executing batch ingestion, clustering, pulse, and explainer.

Executes start-to-finish in a single non-interactive invocation without requiring any human prompts.
Packages outputs with full data lineage and cryptographic state snapshots.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from src.agents.weekly.clustering_engine import ClusteringEngine
from src.agents.weekly.explainer_generator import ExplainerGenerator
from src.agents.weekly.pulse_generator import PulseGenerator
from src.agents.weekly.review_ingest import ReviewIngestor, get_sample_reviews
from src.config import Settings, get_settings
from src.models.explainer import CanonicalExplainer
from src.models.review import ThemeCluster, UserReview, WeeklyPulse
from src.storage.state_diff_engine import capture_state

logger = logging.getLogger(__name__)


class WeeklyRunner:
    """Orchestrates the unattended Weekly Loop pipeline from ingress to stage artifacts."""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.ingestor = ReviewIngestor()
        self.clustering_engine = ClusteringEngine(settings=self.settings)
        self.pulse_generator = PulseGenerator(settings=self.settings)
        self.explainer_generator = ExplainerGenerator(settings=self.settings)

    def run_pipeline(
        self,
        reviews_data: Optional[List[Union[Dict[str, Any], UserReview, str]]] = None,
        week_identifier: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        escalated_topics: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Execute the Weekly Loop end-to-end without manual intervention.

        Returns structured dictionary containing all generated models, metadata, and state snapshots.
        """
        # Determine week identifier (default e.g. 2026-W47)
        if not week_identifier:
            now = datetime.now(timezone.utc)
            year, week_num, _ = now.isocalendar()
            week_identifier = f"{year}-W{week_num:02d}"

        logger.info("Starting Unattended Weekly Loop Pipeline for %s", week_identifier)

        # ----------------------------------------------------------------------
        # 1. Review Ingestion & PII Sanitization
        # ----------------------------------------------------------------------
        if reviews_data is None:
            raw_reviews = get_sample_reviews(week_identifier=week_identifier)
        else:
            raw_reviews = self.ingestor.ingest_reviews(
                reviews_data=reviews_data,
                start_date=start_date,
                end_date=end_date,
            )

        logger.info("Step 1 Complete: Ingested %d sanitized reviews.", len(raw_reviews))

        # ----------------------------------------------------------------------
        # 2. Constrained Thematic Clustering (Hard cap <= 5 themes)
        # ----------------------------------------------------------------------
        clusters = self.clustering_engine.cluster_reviews(
            reviews=raw_reviews,
            week_identifier=week_identifier,
        )

        top_clusters = [c for c in clusters if c.is_top_three]
        fee_cluster = next((c for c in clusters if c.is_fee_confusion), None)

        logger.info(
            "Step 2 Complete: Formed %d clusters (top 3: %d, fee theme identified: %s)",
            len(clusters),
            len(top_clusters),
            fee_cluster is not None,
        )

        # ----------------------------------------------------------------------
        # 3. Weekly Pulse Generation (<= 250 words, quotes with IDs, 3 actions)
        # ----------------------------------------------------------------------
        pulse = self.pulse_generator.generate_pulse(
            reviews=raw_reviews,
            clusters=clusters,
            week_identifier=week_identifier,
            escalated_topics=escalated_topics,
        )

        # Verify lineage
        lineage_valid = self.pulse_generator.validate_quote_lineage(pulse, raw_reviews)
        if not lineage_valid:
            logger.warning("Lineage validation check failed for WeeklyPulse quotes.")

        logger.info("Step 3 Complete: Weekly Pulse created (%d words).", pulse.word_count)

        # ----------------------------------------------------------------------
        # 4. Canonical Fee Explainer Generation (<= 6 bullets, >= 2 links)
        # ----------------------------------------------------------------------
        explainer = self.explainer_generator.generate_explainer(
            fee_cluster=fee_cluster,
            zero_fee_fallback=(fee_cluster is None),
        )

        logger.info("Step 4 Complete: Canonical Fee Explainer created (%d bullets).", explainer.bullet_count)

        # ----------------------------------------------------------------------
        # 5. Cryptographic State Snapshots & Packaging
        # ----------------------------------------------------------------------
        pulse_snapshot = capture_state(pulse)
        explainer_snapshot = capture_state(explainer)

        result_bundle: Dict[str, Any] = {
            "week_identifier": week_identifier,
            "reviews": raw_reviews,
            "clusters": clusters,
            "pulse": pulse,
            "explainer": explainer,
            "top_themes": top_clusters,
            "fee_confusion_theme": fee_cluster,
            "metadata": {
                "review_count": len(raw_reviews),
                "cluster_count": len(clusters),
                "pulse_word_count": pulse.word_count,
                "explainer_bullet_count": explainer.bullet_count,
                "explainer_link_count": len(explainer.source_urls),
                "lineage_valid": lineage_valid,
                "pulse_state_hash": pulse_snapshot["hash"],
                "explainer_state_hash": explainer_snapshot["hash"],
                "execution_timestamp": datetime.now(timezone.utc).isoformat(),
                "unattended_execution": True,
            },
        }

        logger.info(
            "Weekly Loop Pipeline completed successfully for %s. State hashes: pulse=%s, explainer=%s",
            week_identifier,
            pulse_snapshot["hash"][:8],
            explainer_snapshot["hash"][:8],
        )

        return result_bundle


# Convenience singleton and runner function
_runner_instance: Optional[WeeklyRunner] = None


def get_weekly_runner() -> WeeklyRunner:
    """Retrieve singleton WeeklyRunner instance."""
    global _runner_instance
    if _runner_instance is None:
        _runner_instance = WeeklyRunner()
    return _runner_instance


def run_weekly_pipeline(
    reviews_data: Optional[List[Union[Dict[str, Any], UserReview, str]]] = None,
    week_identifier: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    escalated_topics: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Execute the Weekly Loop pipeline in a single unattended call."""
    runner = get_weekly_runner()
    return runner.run_pipeline(
        reviews_data=reviews_data,
        week_identifier=week_identifier,
        start_date=start_date,
        end_date=end_date,
        escalated_topics=escalated_topics,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    bundle = run_weekly_pipeline()
    print("=== WEEKLY PULSE ===")
    print(f"ID: {bundle['pulse'].pulse_id} ({bundle['pulse'].word_count} words)")
    print(bundle["pulse"].pulse_text)
    print("\nQuotes:", bundle["pulse"].supporting_quotes)
    print("\nAction Ideas:", bundle["pulse"].action_ideas)
    print("\n=== CANONICAL EXPLAINER ===")
    print(f"ID: {bundle['explainer'].explainer_id}")
    print(f"Title: {bundle['explainer'].title}")
    for b in bundle["explainer"].bullet_points:
        print(f"- {b}")
    print("Links:", bundle["explainer"].source_urls)
