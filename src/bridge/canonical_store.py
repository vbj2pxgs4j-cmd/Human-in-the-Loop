"""Canonical Explainer Store with semantic embeddings, fast-path lookup, and TTL validation.

Enables the Response Loop to reuse product-approved canonical fee explainers when similarity > 0.88.
Enforces EC-BRID-01: TTL expiration (> 60 days) and administrative invalidation.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np

from src.config import Settings, get_settings
from src.models.explainer import CanonicalExplainer
from src.retrieval.corpus_indexer import get_corpus_indexer

logger = logging.getLogger(__name__)


# Standard canonical question triggers corresponding to explainer topics
CANONICAL_TOPIC_TRIGGERS: Dict[str, List[str]] = {
    "dp-charges": [
        "Why was DP charge of Rs 15.93 debited on selling shares?",
        "Why was DP charge of Rs. 15.93 debited when selling shares?",
        "What is the DP charge for selling equity shares from demat?",
        "Depository Participant DP charge debited on equity delivery sell",
        "Why was 15 rupees deducted on selling shares?",
        "Why was CDSL DP charge debited on delivery sell?",
    ],
    "amc-charges": [
        "What is the quarterly AMC fee for demat accounts?",
        "Why was AMC annual maintenance charge debited from account?",
        "What are the demat AMC charges and BSDA guidelines?",
        "Quarterly AMC of Rs 88.50 debited from ledger",
        "Why was annual maintenance fee Rs 354 charged on my account?",
    ],
    "statutory-stt-charges": [
        "What is the STT charge on equity delivery trades?",
        "What is Securities Transaction Tax and stamp duty on stock trades?",
        "Why was STT and GST deducted on my trade?",
        "Statutory taxes and STT charges on delivery",
    ],
    "brokerage-delivery": [
        "What is the brokerage fee for equity delivery trading?",
        "Is equity delivery trading zero brokerage on your platform?",
        "What are the F&O and intraday brokerage charges?",
        "Zero brokerage equity delivery terms",
    ],
}


@dataclass
class CanonicalMatchResult:
    """Encapsulates the matched canonical explainer and synthesized reusable draft."""

    explainer: CanonicalExplainer
    similarity_score: float
    reusable_draft: str
    sentence_count: int
    cited_url: str


class CanonicalStore:
    """Knowledge store for human-approved Canonical Explainers with dense vector lookup."""

    # Maximum age in days before an approved explainer is deemed stale (EC-BRID-01)
    TTL_DAYS: int = 60

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.threshold: float = self.settings.CANONICAL_SIMILARITY_THRESHOLD  # 0.88
        self._explainers: Dict[str, CanonicalExplainer] = {}
        self._embeddings: Dict[str, List[np.ndarray]] = {}

    def _get_embedding(self, text: str) -> np.ndarray:
        """Compute normalized dense vector embedding using SentenceTransformer."""
        indexer = get_corpus_indexer()
        vec = indexer.model.encode(
            text,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return np.asarray(vec, dtype=np.float32)

    def add_explainer(self, explainer: CanonicalExplainer) -> None:
        """Register a canonical explainer in the store and ensure its passage embeddings are indexed."""
        # Index multi-target passages: title, bullets, full text, and canonical triggers
        passages: List[str] = [explainer.title]
        passages.extend(explainer.bullet_points)
        passages.append(f"{explainer.title}\n" + "\n".join(explainer.bullet_points))

        # Add topic-specific canonical question triggers
        triggers = CANONICAL_TOPIC_TRIGGERS.get(explainer.topic_slug, [])
        passages.extend(triggers)

        indexer = get_corpus_indexer()
        embeddings_mat = indexer.model.encode(
            passages,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )

        vectors = [np.asarray(embeddings_mat[i], dtype=np.float32) for i in range(len(passages))]

        if explainer.embedding is None or len(explainer.embedding) == 0:
            explainer = explainer.model_copy(update={"embedding": vectors[0].tolist()})

        self._explainers[explainer.explainer_id] = explainer
        self._embeddings[explainer.explainer_id] = vectors
        logger.info(
            "Registered explainer %s with %d indexed semantic passages (status=%s, topic=%s)",
            explainer.explainer_id,
            len(vectors),
            explainer.status,
            explainer.topic_slug,
        )

    def approve_explainer(
        self,
        explainer_id: str,
        approved_by: str = "product_manager",
    ) -> Optional[CanonicalExplainer]:
        """Approve an explainer into canonical status, making it live for fast-path reuse."""
        if explainer_id not in self._explainers:
            logger.warning("Attempted to approve non-existent explainer: %s", explainer_id)
            return None

        now = datetime.now(timezone.utc)
        explainer = self._explainers[explainer_id]
        approved = explainer.model_copy(
            update={
                "status": "APPROVED",
                "approved_by": approved_by,
                "approved_at": now,
            }
        )
        self._explainers[explainer_id] = approved
        logger.info("Explainer %s approved by %s; now live in canonical store", explainer_id, approved_by)
        return approved

    def invalidate_explainer(self, explainer_id: str) -> bool:
        """EC-BRID-01: Admin invalidation clearing the explainer from active canonical serving."""
        if explainer_id not in self._explainers:
            return False

        explainer = self._explainers[explainer_id]
        archived = explainer.model_copy(update={"status": "ARCHIVED"})
        self._explainers[explainer_id] = archived
        logger.info("Admin invalidated canonical explainer %s; status set to ARCHIVED", explainer_id)
        return True

    def get_explainer(self, explainer_id: str) -> Optional[CanonicalExplainer]:
        """Retrieve explainer by ID."""
        return self._explainers.get(explainer_id)

    def list_approved_explainers(self) -> List[CanonicalExplainer]:
        """Return all explainers with APPROVED status."""
        return [e for e in self._explainers.values() if e.status == "APPROVED"]

    def list_all_explainers(self) -> List[CanonicalExplainer]:
        """Return all explainers regardless of approval status."""
        return list(self._explainers.values())

    def is_stale(
        self,
        explainer: CanonicalExplainer,
        current_time: Optional[datetime] = None,
    ) -> bool:
        """EC-BRID-01: Check if an approved explainer exceeds TTL_DAYS (60 days) freshness ceiling."""
        now = current_time or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        last_checked = explainer.last_checked_date
        if last_checked.tzinfo is None:
            last_checked = last_checked.replace(tzinfo=timezone.utc)
        age = now - last_checked
        return age > timedelta(days=self.TTL_DAYS)

    def _format_reusable_draft(self, explainer: CanonicalExplainer) -> Tuple[str, int, str]:
        """Synthesize concise draft (<= 3 sentences) citing exactly 1 official source link."""
        from src.agents.response.reviewer_agent import ReviewerAgent

        reviewer = ReviewerAgent()
        bullets = [b.strip() for b in explainer.bullet_points if not b.startswith("Note:")]
        if not bullets:
            bullets = explainer.bullet_points

        cited_url = explainer.source_urls[0] if explainer.source_urls else "https://platform.in/charges"

        p1 = bullets[0].rstrip(".")
        candidate = f"{p1}. Source: {cited_url}"

        # Try incorporating second bullet if it fits comfortably within <= 3 sentences
        if len(bullets) > 1:
            p2 = bullets[1].rstrip(".")
            candidate_two = f"{p1}. {p2}. Source: {cited_url}"
            if len(reviewer.split_sentences(candidate_two)) <= 3:
                candidate = candidate_two

        sentences = reviewer.split_sentences(candidate)
        sentence_count = len(sentences)

        return candidate, sentence_count, cited_url

    def find_matching_explainer(
        self,
        query: str,
        threshold: Optional[float] = None,
        current_time: Optional[datetime] = None,
    ) -> Optional[CanonicalMatchResult]:
        """Fast-path lookup: check if query matches an approved, fresh canonical explainer.

        Returns CanonicalMatchResult if cosine similarity > threshold (0.88), else None.
        Enforces EC-BRID-01 freshness TTL (> 60 days bypasses cache).
        """
        clean_q = query.strip()
        if not clean_q or not self._explainers:
            return None

        sim_threshold = threshold if threshold is not None else self.threshold
        query_vec = self._get_embedding(clean_q)

        best_score = -1.0
        best_explainer: Optional[CanonicalExplainer] = None

        for explainer_id, explainer in self._explainers.items():
            # 1. Must be APPROVED
            if explainer.status != "APPROVED":
                continue

            # 2. EC-BRID-01: Must not exceed 60-day TTL freshness ceiling
            if self.is_stale(explainer, current_time=current_time):
                logger.info(
                    "Bypassing stale explainer %s (last_checked=%s > %d days)",
                    explainer_id,
                    explainer.last_checked_date,
                    self.TTL_DAYS,
                )
                continue

            # 3. Compute max cosine similarity across indexed passages
            vectors = self._embeddings.get(explainer_id, [])
            if not vectors:
                continue

            scores = [float(np.dot(query_vec, v)) for v in vectors]
            max_cand_score = max(scores) if scores else -1.0

            if max_cand_score > best_score:
                best_score = max_cand_score
                best_explainer = explainer

        if best_explainer is not None and best_score > sim_threshold:
            draft, sent_count, cited_url = self._format_reusable_draft(best_explainer)
            logger.info(
                "Fast-path match found: explainer=%s, score=%.4f (threshold=%.2f)",
                best_explainer.explainer_id,
                best_score,
                sim_threshold,
            )
            return CanonicalMatchResult(
                explainer=best_explainer,
                similarity_score=round(best_score, 4),
                reusable_draft=draft,
                sentence_count=sent_count,
                cited_url=cited_url,
            )

        return None

    def clear(self) -> None:
        """Clear all stored explainers and embeddings (primarily for test resets)."""
        self._explainers.clear()
        self._embeddings.clear()


# Global singleton CanonicalStore
_canonical_store_instance: Optional[CanonicalStore] = None


def get_canonical_store() -> CanonicalStore:
    """Retrieve global singleton CanonicalStore."""
    global _canonical_store_instance
    if _canonical_store_instance is None:
        _canonical_store_instance = CanonicalStore()
    return _canonical_store_instance
