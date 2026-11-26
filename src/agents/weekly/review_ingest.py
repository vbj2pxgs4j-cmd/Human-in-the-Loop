"""Review Ingestion and Sanitization component for the Weekly Loop.

Loads user reviews, applies deterministic PII scrubbing, enforces immutable review IDs,
and segments reviews by ingestion date window [T_start, T_end].
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from src.models.review import UserReview
from src.security.pii_scrubber import scrub_pii

logger = logging.getLogger(__name__)


def _parse_timestamp(ts: Any) -> datetime:
    """Normalize input timestamp into a timezone-aware UTC datetime."""
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)
    if isinstance(ts, str):
        # Clean ISO formatting
        cleaned = ts.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(cleaned)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            pass
    # Fallback to current UTC time if unparseable
    return datetime.now(timezone.utc)


class ReviewIngestor:
    """Batch loader, PII sanitizer, and date-window segmenter for user reviews."""

    def __init__(self):
        pass

    def sanitize_and_build_review(
        self,
        raw_item: Union[Dict[str, Any], UserReview, str],
        index: int = 1,
        prefix: str = "rev",
    ) -> UserReview:
        """Sanitize a raw review item and convert into an immutable UserReview."""
        if isinstance(raw_item, UserReview):
            # Scrub text to ensure zero PII leakage even on pre-built objects
            sanitized_text = scrub_pii(raw_item.sanitized_text)
            return raw_item.model_copy(update={"sanitized_text": sanitized_text})

        if isinstance(raw_item, str):
            review_id = f"{prefix}_{index:03d}"
            sanitized_text = scrub_pii(raw_item)
            return UserReview(
                review_id=review_id,
                sanitized_text=sanitized_text,
                timestamp=datetime.now(timezone.utc),
                rating=3.0,
                platform="PlayStore",
                metadata={},
            )

        if isinstance(raw_item, dict):
            # Extract or generate review_id
            review_id = str(raw_item.get("review_id") or raw_item.get("id") or f"{prefix}_{index:03d}")
            raw_text = str(raw_item.get("sanitized_text") or raw_item.get("text") or raw_item.get("content") or "")
            sanitized_text = scrub_pii(raw_text)

            ts_raw = raw_item.get("timestamp") or raw_item.get("created_at") or raw_item.get("date")
            timestamp = _parse_timestamp(ts_raw)

            rating_raw = raw_item.get("rating") or raw_item.get("score")
            try:
                rating = float(rating_raw) if rating_raw is not None else None
                if rating is not None and (rating < 1.0 or rating > 5.0):
                    rating = max(1.0, min(5.0, rating))
            except (ValueError, TypeError):
                rating = None

            platform = str(raw_item.get("platform") or "PlayStore")
            metadata = raw_item.get("metadata") or {}

            return UserReview(
                review_id=review_id,
                sanitized_text=sanitized_text,
                timestamp=timestamp,
                rating=rating,
                platform=platform,
                metadata=metadata,
            )

        raise TypeError(f"Unsupported review item format: {type(raw_item)}")

    def ingest_reviews(
        self,
        reviews_data: List[Union[Dict[str, Any], UserReview, str]],
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        prefix: str = "rev",
    ) -> List[UserReview]:
        """Ingest, sanitize, and filter a batch of reviews within window [T_start, T_end]."""
        parsed_reviews: List[UserReview] = []
        utc_start = _parse_timestamp(start_date) if start_date is not None else None
        utc_end = _parse_timestamp(end_date) if end_date is not None else None

        for idx, item in enumerate(reviews_data, start=1):
            review = self.sanitize_and_build_review(item, index=idx, prefix=prefix)

            # Date window filtering
            if utc_start and review.timestamp < utc_start:
                continue
            if utc_end and review.timestamp > utc_end:
                continue

            parsed_reviews.append(review)

        logger.info(
            "Ingested %d reviews after PII sanitization and window filtering (input: %d)",
            len(parsed_reviews),
            len(reviews_data),
        )
        return parsed_reviews

    def load_from_json(
        self,
        file_path: Union[str, Path],
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> List[UserReview]:
        """Load review items from a JSON file and ingest with window filtering."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Review file not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict) and "reviews" in data:
            data = data["reviews"]

        if not isinstance(data, list):
            raise ValueError(f"JSON review file must contain a list of reviews: {path}")

        return self.ingest_reviews(data, start_date=start_date, end_date=end_date)


def ingest_reviews(
    reviews_data: List[Union[Dict[str, Any], UserReview, str]],
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> List[UserReview]:
    """Convenience functional interface for review ingestion."""
    ingestor = ReviewIngestor()
    return ingestor.ingest_reviews(reviews_data, start_date=start_date, end_date=end_date)


def get_sample_reviews(
    week_identifier: str = "2026-W47",
    base_date: Optional[datetime] = None,
) -> List[UserReview]:
    """Provide a realistic, grounded batch of customer reviews for testing and unattended runs."""
    base = base_date or datetime(2026, 11, 23, 10, 0, 0, tzinfo=timezone.utc)

    raw_samples = [
        # Cluster 1: DP Charges Surprise on Equity Sell (Dominant Fee Confusion)
        {
            "review_id": "rev_001",
            "text": "Charged Rs 15.93 without warning on selling shares! You claimed equity delivery is zero brokerage, then what is this hidden demat debit? Call me on 9876543210 to refund.",
            "rating": 1.0,
            "platform": "PlayStore",
            "metadata": {"app_version": "5.4.1"},
        },
        {
            "review_id": "rev_002",
            "text": "Why was Rs 15 deducted from my funds when I sold 10 shares of Tata Motors? Delivery was supposed to be completely free!",
            "rating": 1.0,
            "platform": "PlayStore",
            "metadata": {"app_version": "5.4.1"},
        },
        {
            "review_id": "rev_003",
            "text": "Depository charge of Rs 13.50 + GST was debited 3 times because I sold 3 different stocks today. Why is it charged per company?",
            "rating": 2.0,
            "platform": "AppStore",
            "metadata": {"app_version": "5.4.0"},
        },
        {
            "review_id": "rev_004",
            "text": "Sold 1 share of Suzlon worth Rs 60 and got debited Rs 15.93 DP charge. That is 25% of my trade value! Clarify DP charges properly in the app.",
            "rating": 1.0,
            "platform": "PlayStore",
            "metadata": {"app_version": "5.4.2"},
        },
        {
            "review_id": "rev_005",
            "text": "Unexpected charge in my account statement labeled CDSL DP fee. Please explain why this is charged on delivery sell.",
            "rating": 2.0,
            "platform": "Web",
            "metadata": {"browser": "Chrome"},
        },
        {
            "review_id": "rev_006",
            "text": "Zero brokerage is misleading marketing if you deduct Rs 15.93 on every stock sell without upfront confirmation on order screen.",
            "rating": 1.0,
            "platform": "PlayStore",
            "metadata": {"app_version": "5.4.2"},
        },

        # Cluster 2: Account Maintenance Charges (AMC) & Ledger Deductions
        {
            "review_id": "rev_007",
            "text": "Quarterly AMC of Rs 88.50 debited from ledger. I have zero trades this month! Why charge maintenance for an idle demat account?",
            "rating": 2.0,
            "platform": "PlayStore",
            "metadata": {"app_version": "5.4.0"},
        },
        {
            "review_id": "rev_008",
            "text": "Why was annual maintenance fee Rs 354 charged on my account? My PAN is ABCDE1234F. I thought account opening and maintenance was free for life.",
            "rating": 1.0,
            "platform": "AppStore",
            "metadata": {"app_version": "5.4.1"},
        },
        {
            "review_id": "rev_009",
            "text": "Surprise maintenance fee of 75 rupees plus GST debited today without SMS or email notice. My balance went negative.",
            "rating": 2.0,
            "platform": "PlayStore",
            "metadata": {"app_version": "5.4.1"},
        },
        {
            "review_id": "rev_010",
            "text": "Demat AMC deducted even though my total holding is below Rs 2 lakhs. Aren't BSDA accounts supposed to have zero AMC under SEBI rules?",
            "rating": 2.0,
            "platform": "Web",
            "metadata": {"browser": "Firefox"},
        },

        # Cluster 3: App Login, Biometric & OTP Verification Latency
        {
            "review_id": "rev_011",
            "text": "Login OTP takes 2 minutes to arrive. By the time I enter it, market has opened and stock prices moved! Fix your SMS gateway.",
            "rating": 1.0,
            "platform": "PlayStore",
            "metadata": {"app_version": "5.4.2"},
        },
        {
            "review_id": "rev_012",
            "text": "Biometric fingerprint login fails repeatedly after latest update. Every morning I have to manually type password and wait for OTP.",
            "rating": 2.0,
            "platform": "PlayStore",
            "metadata": {"app_version": "5.4.2"},
        },
        {
            "review_id": "rev_013",
            "text": "App hangs on opening bell at 9:15 AM. Order screen gets stuck loading and missed placing my opening order.",
            "rating": 1.0,
            "platform": "AppStore",
            "metadata": {"app_version": "5.4.0"},
        },
        {
            "review_id": "rev_014",
            "text": "OTP timeout issue is frustrating. The resend button is disabled for 60 seconds and SMS never comes on time.",
            "rating": 2.0,
            "platform": "PlayStore",
            "metadata": {"app_version": "5.4.1"},
        },

        # Cluster 4: KYC Verification & Account Activation Delays
        {
            "review_id": "rev_015",
            "text": "KYC document verification is taking more than 48 hours. Submitted Aadhaar and bank statement but status still shows In Progress.",
            "rating": 2.0,
            "platform": "PlayStore",
            "metadata": {"app_version": "5.4.2"},
        },
        {
            "review_id": "rev_016",
            "text": "Bank account penny drop failed during onboarding verification. No error message explaining why verification was rejected.",
            "rating": 2.0,
            "platform": "PlayStore",
            "metadata": {"app_version": "5.4.1"},
        },
        {
            "review_id": "rev_017",
            "text": "DigiLocker KYC integration errored out twice during account setup. Had to upload documents manually.",
            "rating": 3.0,
            "platform": "Web",
            "metadata": {"browser": "Chrome"},
        },

        # Cluster 5: Statutory Taxes & STT Clarifications
        {
            "review_id": "rev_018",
            "text": "What is this 0.1% STT charge on delivery trade? Why does government tax both buying and selling equities?",
            "rating": 3.0,
            "platform": "AppStore",
            "metadata": {"app_version": "5.4.2"},
        },
        {
            "review_id": "rev_019",
            "text": "Contract note shows exchange transaction fee and SEBI charges on top of GST. Please provide a clear tax calculator before trade execution.",
            "rating": 3.0,
            "platform": "PlayStore",
            "metadata": {"app_version": "5.4.1"},
        },
        {
            "review_id": "rev_020",
            "text": "Stamp duty was debited on my delivery buy order. Thought delivery investment was completely charge free.",
            "rating": 3.0,
            "platform": "PlayStore",
            "metadata": {"app_version": "5.4.0"},
        },
    ]

    ingestor = ReviewIngestor()
    reviews: List[UserReview] = []
    for idx, sample in enumerate(raw_samples):
        # Stagger timestamps across the week
        delta_hours = idx * 6
        ts = base.replace(hour=10 + (idx % 8))
        sample_dict = dict(sample)
        sample_dict["timestamp"] = ts
        reviews.append(ingestor.sanitize_and_build_review(sample_dict, index=idx + 1))

    return reviews
