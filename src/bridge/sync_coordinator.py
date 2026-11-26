"""Bi-Directional Bridge Sync Coordinator connecting Response Loop and Weekly Loop.

Coordinates:
1. Direction 1 (Weekly Loop -> Response Loop): Human-approved canonical explainers immediately
   become fast-path lookup answers for customer support.
2. Direction 2 (Response Loop -> Weekly Loop): High-frequency support inquiries (>= 5x/wk)
   escalate into the Weekly Pulse under 'High-Frequency Support Issues'.
3. Real-time synchronization without system restart.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.agents.weekly.runner import WeeklyRunner, get_weekly_runner
from src.bridge.canonical_store import CanonicalStore, get_canonical_store
from src.bridge.frequency_tracker import FrequencyTracker, get_frequency_tracker
from src.config import Settings, get_settings
from src.models.explainer import CanonicalExplainer

logger = logging.getLogger(__name__)


class SyncCoordinator:
    """Bi-directional synchronization coordinator managing the operational knowledge bridge."""

    def __init__(
        self,
        canonical_store: Optional[CanonicalStore] = None,
        frequency_tracker: Optional[FrequencyTracker] = None,
        weekly_runner: Optional[WeeklyRunner] = None,
        settings: Optional[Settings] = None,
    ):
        self.settings = settings or get_settings()
        self.store = canonical_store or get_canonical_store()
        self.tracker = frequency_tracker or get_frequency_tracker()
        self.runner = weekly_runner or get_weekly_runner()

    # --------------------------------------------------------------------------
    # Direction 1: Weekly Loop -> Response Loop (Canonical Explainer Reuse)
    # --------------------------------------------------------------------------

    def approve_and_sync_explainer(
        self,
        explainer: CanonicalExplainer,
        approved_by: str = "product_manager",
    ) -> CanonicalExplainer:
        """Approve a Weekly Loop fee explainer and immediately sync into the canonical store.

        The explainer becomes instantly available for Response Loop fast-path retrieval without system restart.
        """
        # Register if not already present
        if self.store.get_explainer(explainer.explainer_id) is None:
            self.store.add_explainer(explainer)

        # Approve and activate
        approved = self.store.approve_explainer(
            explainer_id=explainer.explainer_id,
            approved_by=approved_by,
        )
        if approved is None:
            raise ValueError(f"Failed to approve explainer: {explainer.explainer_id}")

        logger.info(
            "Direction 1 Sync Complete: Explainer %s approved and active in canonical store",
            explainer.explainer_id,
        )
        return approved

    def invalidate_canonical_explainer(self, explainer_id: str) -> bool:
        """EC-BRID-01: Invalidate an explainer, immediately removing it from Response Loop serving."""
        success = self.store.invalidate_explainer(explainer_id)
        if success:
            logger.info("Direction 1 Sync: Invalidated explainer %s from active serving", explainer_id)
        return success

    # --------------------------------------------------------------------------
    # Direction 2: Response Loop -> Weekly Loop (Frequency Escalation Trigger)
    # --------------------------------------------------------------------------

    def get_escalations_for_weekly_pulse(
        self,
        window_days: int = 7,
        threshold: Optional[int] = None,
    ) -> List[str]:
        """Fetch support topics meeting or exceeding the >= 5/week escalation threshold.

        Formatted for direct injection into the Weekly Pulse executive report.
        """
        return self.tracker.get_escalated_topic_titles(
            window_days=window_days,
            threshold=threshold,
        )

    def run_weekly_loop_with_escalations(
        self,
        week_identifier: Optional[str] = None,
        reviews_data: Optional[List[Any]] = None,
    ) -> Dict[str, Any]:
        """Trigger an unattended Weekly Loop run with automatically injected support escalations."""
        escalated_topics = self.get_escalations_for_weekly_pulse()
        logger.info(
            "Direction 2 Sync: Triggering Weekly Loop for %s with %d escalated support topics",
            week_identifier or "current week",
            len(escalated_topics),
        )

        return self.runner.run_pipeline(
            reviews_data=reviews_data,
            week_identifier=week_identifier,
            escalated_topics=escalated_topics if escalated_topics else None,
        )


# Global singleton SyncCoordinator
_sync_coordinator_instance: Optional[SyncCoordinator] = None


def get_sync_coordinator() -> SyncCoordinator:
    """Retrieve global singleton SyncCoordinator."""
    global _sync_coordinator_instance
    if _sync_coordinator_instance is None:
        _sync_coordinator_instance = SyncCoordinator()
    return _sync_coordinator_instance
