"""Question Frequency Tracker with sliding 7-day window, topic normalization, and anti-spam deduplication.

Tracks recurring support questions, identifies inquiries with frequency >= 5 per week,
and enforces EC-BRID-02: deduplication of same-user/same-query submissions within 24-hour windows.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from src.config import Settings, get_settings

logger = logging.getLogger(__name__)


# Standardized topic normalization patterns
TOPIC_NORMALIZATION_RULES: List[Tuple[re.Pattern, str]] = [
    (
        re.compile(
            r"\b(?:call[\s\-_]*(?:&|and)?[\s\-_]*trade|phone[\s\-_]*(?:order|trade)|call[\s\-_]*order|(?:rs\.?|₹)\s*50|50\s*(?:rs|rupees))\b",
            re.IGNORECASE,
        ),
        "Call & Trade Desk Charges (Rs. 50 + GST)",
    ),
    (
        re.compile(r"\b(?:dp|depository|cdsl|nsdl|15\.93|13\.50|rs\.?\s*15|demat\s+debit|scrip\s+charge)\b", re.IGNORECASE),
        "Depository Participant (DP) Charges on Equity Delivery Sales",
    ),
    (
        re.compile(r"\b(?:amc|maintenance|annual\s+maintenance|quarterly\s+amc|88\.50|354|bsda|ledger\s+debit)\b", re.IGNORECASE),
        "Quarterly Demat Account Maintenance Charges (AMC)",
    ),
    (
        re.compile(r"\b(?:stt|stamp\s+duty|turnover\s+fee|sebi\s+charges?|0\.1%|statutory\s+tax)\b", re.IGNORECASE),
        "Securities Transaction Tax (STT) & Statutory Levies",
    ),
    (
        re.compile(r"\b(?:auto\s*square\s*off|rms\s+square|square\s*off\s*fee|intraday\s+square)\b", re.IGNORECASE),
        "RMS Auto-Square Off Charges (Rs. 50 + GST)",
    ),
    (
        re.compile(r"\b(?:upi|netbanking|gateway\s+fee|imps\s+charge|deposit\s+fee)\b", re.IGNORECASE),
        "Payment Gateway & Fund Transfer Fees",
    ),
    (
        re.compile(r"\b(?:brokerage|zero\s+brokerage|delivery\s+commission|intraday\s+brokerage)\b", re.IGNORECASE),
        "Brokerage Rates & Commission Structure",
    ),
]


@dataclass
class InquiryRecord:
    """Record of an individual customer support inquiry."""

    inquiry_id: str
    raw_query: str
    normalized_topic: str
    user_id: str
    timestamp: datetime


class FrequencyTracker:
    """Sliding-window support question frequency monitor with EC-BRID-02 anti-spam deduplication."""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.default_window_days: int = 7
        self.escalation_threshold: int = self.settings.FREQUENCY_ESCALATION_THRESHOLD  # 5 occurrences
        self._records: List[InquiryRecord] = []

    def normalize_topic(self, query: str) -> str:
        """Map raw or sanitized query to a canonical topic key."""
        clean = query.strip()
        for pattern, topic in TOPIC_NORMALIZATION_RULES:
            if pattern.search(clean):
                return topic

        # Fallback to key noun phrase or snippet
        words = re.findall(r"\b[A-Za-z0-9_-]+\b", clean)
        snippet = " ".join(words[:4]) if words else "General Inquiry"
        return f"Support Inquiry: {snippet.capitalize()}"

    def record_inquiry(
        self,
        query: str,
        user_id: Optional[str] = None,
        timestamp: Optional[datetime] = None,
        inquiry_id: Optional[str] = None,
    ) -> InquiryRecord:
        """Record an incoming customer inquiry for sliding-window frequency tracking."""
        ts = timestamp or datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        uid = user_id or f"anon_{len(self._records) + 1}"
        iid = inquiry_id or f"inq_{len(self._records) + 1:05d}"
        topic = self.normalize_topic(query)

        record = InquiryRecord(
            inquiry_id=iid,
            raw_query=query,
            normalized_topic=topic,
            user_id=uid,
            timestamp=ts,
        )
        self._records.append(record)
        return record

    def get_inquiry_counts(
        self,
        window_days: int = 7,
        current_time: Optional[datetime] = None,
    ) -> Dict[str, int]:
        """Aggregate unique deduplicated inquiry counts per topic within sliding window.

        Enforces EC-BRID-02: deduplicates same-user submissions on the same topic within 24h.
        """
        now = current_time or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        cutoff = now - timedelta(days=window_days)

        # Set of unique (user_id, topic, day_bucket) signals
        deduped_signals: Set[Tuple[str, str, int]] = set()
        topic_counts: Dict[str, int] = {}

        for rec in self._records:
            if rec.timestamp < cutoff or rec.timestamp > now:
                continue

            # Day bucket (integer days since epoch)
            day_bucket = int(rec.timestamp.timestamp() // 86400)
            signal_key = (rec.user_id, rec.normalized_topic, day_bucket)

            if signal_key not in deduped_signals:
                deduped_signals.add(signal_key)
                topic_counts[rec.normalized_topic] = topic_counts.get(rec.normalized_topic, 0) + 1

        return topic_counts

    def get_escalated_topics(
        self,
        window_days: int = 7,
        threshold: Optional[int] = None,
        current_time: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """Return topics that meet or exceed the weekly frequency escalation threshold (count >= 5)."""
        esc_threshold = threshold if threshold is not None else self.escalation_threshold
        counts = self.get_inquiry_counts(window_days=window_days, current_time=current_time)

        escalated: List[Dict[str, Any]] = []
        for topic, count in sorted(counts.items(), key=lambda item: item[1], reverse=True):
            if count >= esc_threshold:
                escalated.append({
                    "topic": topic,
                    "count": count,
                    "threshold": esc_threshold,
                    "window_days": window_days,
                })
                logger.info(
                    "Topic escalated to weekly product loop: '%s' (frequency=%d, threshold=%d)",
                    topic,
                    count,
                    esc_threshold,
                )

        return escalated

    def get_escalated_topic_titles(
        self,
        window_days: int = 7,
        threshold: Optional[int] = None,
        current_time: Optional[datetime] = None,
    ) -> List[str]:
        """Convenience method returning formatted strings for injection into Weekly Pulse."""
        escalated = self.get_escalated_topics(
            window_days=window_days,
            threshold=threshold,
            current_time=current_time,
        )
        return [f"{e['topic']} ({e['count']} customer inquiries)" for e in escalated]

    def clear(self) -> None:
        """Clear all inquiry history (for testing)."""
        self._records.clear()


# Global singleton FrequencyTracker
_frequency_tracker_instance: Optional[FrequencyTracker] = None


def get_frequency_tracker() -> FrequencyTracker:
    """Retrieve global singleton FrequencyTracker."""
    global _frequency_tracker_instance
    if _frequency_tracker_instance is None:
        _frequency_tracker_instance = FrequencyTracker()
    return _frequency_tracker_instance
