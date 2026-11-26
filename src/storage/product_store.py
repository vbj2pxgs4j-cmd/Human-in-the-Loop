"""In-memory and persisted storage for Product Intelligence artifacts (WeeklyPulse, Themes, Explainers)."""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.agents.weekly.explainer_generator import generate_canonical_explainer
from src.bridge.canonical_store import get_canonical_store
from src.models.explainer import CanonicalExplainer
from src.models.review import ThemeCluster, WeeklyPulse

logger = logging.getLogger(__name__)


class ProductStore:
    """Storage repository for product intelligence: weekly pulse, theme clusters, and explainers."""

    def __init__(self, auto_seed: bool = True):
        self._latest_pulse: Optional[WeeklyPulse] = None
        self._latest_themes: List[ThemeCluster] = []
        if auto_seed:
            self._seed_default_data()

    def _seed_default_data(self) -> None:
        """Seed representative weekly pulse, themes, and explainers."""
        try:
            from src.agents.weekly.runner import run_weekly_pipeline
            # Run weekly pipeline on sample reviews to generate fully valid models
            bundle = run_weekly_pipeline()
            self._latest_pulse = bundle.get("pulse")
            self._latest_themes = bundle.get("clusters", [])

            # Register explainers into CanonicalStore
            store = get_canonical_store()

            # Seed an approved DP charges explainer
            dp_expl = generate_canonical_explainer(force_topic="dp-charges")
            store.add_explainer(dp_expl)
            store.approve_explainer(dp_expl.explainer_id, approved_by="product_lead_seed")

            # Seed a draft AMC explainer awaiting Product approval
            amc_expl = generate_canonical_explainer(force_topic="amc-charges")
            store.add_explainer(amc_expl)

            # Seed statutory taxes explainer
            stt_expl = generate_canonical_explainer(force_topic="statutory-stt-charges")
            store.add_explainer(stt_expl)

            logger.info(
                "ProductStore seeded successfully: pulse=%s, themes=%d, canonical_explainers seeded",
                self._latest_pulse.pulse_id if self._latest_pulse else None,
                len(self._latest_themes),
            )
        except Exception as e:
            logger.error("Error seeding default product data: %s", e, exc_info=True)

    def get_latest_pulse(self) -> Optional[WeeklyPulse]:
        """Fetch current weekly pulse."""
        return self._latest_pulse

    def save_pulse(self, pulse: WeeklyPulse) -> WeeklyPulse:
        """Save updated weekly pulse."""
        self._latest_pulse = pulse
        return pulse

    def list_themes(self) -> List[ThemeCluster]:
        """Fetch current theme clusters."""
        return list(self._latest_themes)

    def set_themes(self, themes: List[ThemeCluster]) -> None:
        """Set active theme clusters."""
        self._latest_themes = list(themes)

    def list_explainers(self) -> List[CanonicalExplainer]:
        """Fetch all explainers (both draft and approved) from CanonicalStore."""
        store = get_canonical_store()
        return list(store._explainers.values())

    def run_fresh_cycle(self, week_identifier: Optional[str] = None) -> Dict[str, Any]:
        """Execute fresh unattended Weekly Loop pipeline and update stored intelligence."""
        from src.agents.weekly.runner import run_weekly_pipeline
        bundle = run_weekly_pipeline(week_identifier=week_identifier)
        self._latest_pulse = bundle.get("pulse")
        self._latest_themes = bundle.get("clusters", [])

        explainer = bundle.get("explainer")
        if explainer:
            store = get_canonical_store()
            store.add_explainer(explainer)

        return bundle

    def clear(self) -> None:
        """Reset product store state."""
        self._latest_pulse = None
        self._latest_themes.clear()


# Global singleton ProductStore
_product_store_instance: Optional[ProductStore] = None


def get_product_store() -> ProductStore:
    """Retrieve global singleton ProductStore."""
    global _product_store_instance
    if _product_store_instance is None:
        _product_store_instance = ProductStore(auto_seed=True)
    return _product_store_instance
