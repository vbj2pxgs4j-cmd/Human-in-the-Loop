"""Automated verification tests for Phase 4: Bi-Directional Bridge & Knowledge Synchronization.

Validates:
1. Criterion 4.1: Canonical Explainer Store & Fast-Path Retrieval (similarity > 0.88, draft format <= 3 sentences)
2. Criterion 4.2: Question Frequency Tracker (sliding 7-day window, >= 5x/wk escalation trigger)
3. EC-BRID-01: Stale Explainer TTL Invalidation (> 60 days bypasses cache, admin invalidation)
4. EC-BRID-02: Astroturfing / Ticket Spamming Deduplication (same user/query in 24h counts as 1)
5. Criterion 4.3: Escalation Integration with Weekly Loop (escalated topics appear in Weekly Pulse <= 250w)
6. Criterion 4.4: Live Synchronization Verification (approval updates Response Loop behavior without restart)
"""

import asyncio
from datetime import datetime, timedelta, timezone
import pytest

from src.agents.response.pipeline import ResponsePipeline
from src.agents.weekly.explainer_generator import generate_canonical_explainer
from src.bridge.canonical_store import CanonicalStore, get_canonical_store
from src.bridge.frequency_tracker import FrequencyTracker, get_frequency_tracker
from src.bridge.sync_coordinator import SyncCoordinator, get_sync_coordinator
from src.models.explainer import CanonicalExplainer
from src.models.review import ThemeCluster, WeeklyPulse
from src.models.ticket import RoutingCategory, SupportTicket, TicketStatus


# ==============================================================================
# 1. Canonical Explainer Store & Fast-Path Retrieval (Criterion 4.1)
# ==============================================================================

class TestCanonicalStoreFastPath:
    """Tests for CanonicalStore semantic search, similarity threshold (0.88), and reusable draft formatting."""

    @pytest.fixture
    def store(self) -> CanonicalStore:
        s = CanonicalStore()
        s.clear()
        return s

    @pytest.fixture
    def dp_explainer(self) -> CanonicalExplainer:
        explainer = generate_canonical_explainer(force_topic="dp-charges")
        return explainer

    def test_canonical_explainer_fast_path_match(self, store: CanonicalStore, dp_explainer: CanonicalExplainer):
        """Approved explainer must be matched when cosine similarity > 0.88."""
        store.add_explainer(dp_explainer)
        store.approve_explainer(dp_explainer.explainer_id)

        # High-similarity query regarding DP charges on delivery sell
        query = "Why was Depository Participant DP charge of Rs 15.93 debited on selling shares?"
        match = store.find_matching_explainer(query)

        assert match is not None
        assert match.explainer.explainer_id == dp_explainer.explainer_id
        assert match.similarity_score > 0.88
        assert match.sentence_count <= 3
        assert match.cited_url in dp_explainer.source_urls
        assert "Source: https://" in match.reusable_draft

    def test_unapproved_draft_explainer_not_matched(self, store: CanonicalStore, dp_explainer: CanonicalExplainer):
        """Explainers in DRAFT status must not be served by the fast-path lookup."""
        # Add without approving (status remains DRAFT)
        store.add_explainer(dp_explainer)
        assert store.get_explainer(dp_explainer.explainer_id).status == "DRAFT"

        query = "Why was DP charge of Rs 15.93 debited on selling shares?"
        match = store.find_matching_explainer(query)

        # Must return None because explainer is not APPROVED
        assert match is None

    def test_non_matching_query_bypasses_fast_path(self, store: CanonicalStore, dp_explainer: CanonicalExplainer):
        """Unrelated query must not meet similarity threshold (0.88) and return None."""
        store.add_explainer(dp_explainer)
        store.approve_explainer(dp_explainer.explainer_id)

        # Unrelated query about cryptocurrency or IPO allotment
        unrelated_query = "How do I apply for the upcoming SME IPO allotment status?"
        match = store.find_matching_explainer(unrelated_query)

        assert match is None


# ==============================================================================
# 2. Question Frequency Tracker & Anti-Spam Deduplication (Criterion 4.2 & EC-BRID-02)
# ==============================================================================

class TestFrequencyTracker:
    """Tests for sliding 7-day window, escalation threshold (>= 5), and anti-spam deduplication."""

    @pytest.fixture
    def tracker(self) -> FrequencyTracker:
        t = FrequencyTracker()
        t.clear()
        return t

    def test_sliding_window_frequency_tracking(self, tracker: FrequencyTracker):
        """Frequency tracker must aggregate inquiries within the 7-day sliding window only."""
        now = datetime(2026, 11, 26, 12, 0, 0, tzinfo=timezone.utc)

        # 3 inquiries within last 3 days (different users)
        tracker.record_inquiry("What is call and trade fee?", user_id="u1", timestamp=now - timedelta(days=1))
        tracker.record_inquiry("Why was 50 rupees charged for phone trade?", user_id="u2", timestamp=now - timedelta(days=2))
        tracker.record_inquiry("Support desk call order fee Rs 50", user_id="u3", timestamp=now - timedelta(days=3))

        # 1 inquiry from 10 days ago (outside 7-day window)
        tracker.record_inquiry("Call and trade fee query", user_id="u4", timestamp=now - timedelta(days=10))

        counts = tracker.get_inquiry_counts(window_days=7, current_time=now)
        topic = "Call & Trade Desk Charges (Rs. 50 + GST)"

        assert counts.get(topic) == 3

    def test_frequency_escalation_threshold_trigger(self, tracker: FrequencyTracker):
        """Inquiries meeting or exceeding count >= 5 within 7 days trigger an escalation event."""
        now = datetime(2026, 11, 26, 12, 0, 0, tzinfo=timezone.utc)

        # Record 5 distinct user inquiries on Call & Trade within 7 days
        for i in range(1, 6):
            tracker.record_inquiry(
                f"Why did you charge Rs 50 for call & trade order {i}?",
                user_id=f"distinct_user_{i}",
                timestamp=now - timedelta(days=i),
            )

        # Record 2 inquiries on AMC (below threshold 5)
        tracker.record_inquiry("Quarterly AMC debit", user_id="user_amc_1", timestamp=now - timedelta(days=1))
        tracker.record_inquiry("AMC maintenance fee", user_id="user_amc_2", timestamp=now - timedelta(days=2))

        escalated = tracker.get_escalated_topics(window_days=7, threshold=5, current_time=now)

        assert len(escalated) == 1
        assert escalated[0]["topic"] == "Call & Trade Desk Charges (Rs. 50 + GST)"
        assert escalated[0]["count"] == 5

    def test_frequency_tracker_deduplication(self, tracker: FrequencyTracker):
        """EC-BRID-02: Single user / bot submitting the same question 10 times in 24h counts as 1 signal."""
        now = datetime(2026, 11, 26, 12, 0, 0, tzinfo=timezone.utc)

        # Spammer bot submits identical query 10 times in the same afternoon
        for minute_offset in range(10):
            tracker.record_inquiry(
                "Why did you charge me ₹20 for call-and-trade?",
                user_id="spammer_bot_01",
                timestamp=now - timedelta(minutes=minute_offset * 10),
            )

        # Deduplication must reduce 10 submissions in 24 hours to exactly 1 count
        counts = tracker.get_inquiry_counts(window_days=7, current_time=now)
        topic = "Call & Trade Desk Charges (Rs. 50 + GST)"

        assert counts.get(topic) == 1

        # Escalation threshold >= 5 must NOT be triggered by astroturfing spammer
        escalated = tracker.get_escalated_topics(window_days=7, threshold=5, current_time=now)
        assert len(escalated) == 0


# ==============================================================================
# 3. Stale Explainer TTL & Invalidation Tests (EC-BRID-01)
# ==============================================================================

class TestCanonicalExplainerTTL:
    """Tests for EC-BRID-01: TTL expiration (> 60 days) and administrative invalidation."""

    @pytest.fixture
    def store(self) -> CanonicalStore:
        s = CanonicalStore()
        s.clear()
        return s

    def test_canonical_explainer_ttl_invalidation(self, store: CanonicalStore):
        """EC-BRID-01: Explainer older than 60 days must be bypassed in fast-path lookup."""
        now = datetime(2026, 11, 26, 12, 0, 0, tzinfo=timezone.utc)
        stale_date = now - timedelta(days=75)  # 75 days old (> 60 days TTL)

        explainer = CanonicalExplainer(
            explainer_id="expl_dp_charges",
            topic_slug="dp-charges",
            title="Canonical Fee Explainer: DP Charges",
            bullet_points=[
                "Depository Participant (DP) charge is flat Rs. 13.50 + 18% GST per scrip per day.",
                "DP charges apply strictly to equity delivery sell transactions.",
            ],
            source_urls=["https://cdslindia.com/charges", "https://platform.in/charges"],
            last_checked_date=stale_date,
            status="APPROVED",
        )
        store.add_explainer(explainer)

        query = "Why was DP charge of Rs 15.93 debited on selling shares?"

        # 1. At current time (75 days after verification), explainer is stale and must return None
        match_stale = store.find_matching_explainer(query, current_time=now)
        assert match_stale is None

        # 2. If checked 30 days after verification (within 60-day window), it matches successfully
        fresh_time = stale_date + timedelta(days=30)
        match_fresh = store.find_matching_explainer(query, current_time=fresh_time)
        assert match_fresh is not None
        assert match_fresh.explainer.explainer_id == "expl_dp_charges"

    def test_admin_explainer_invalidation(self, store: CanonicalStore):
        """EC-BRID-01: Admin invalidation immediately sets status to ARCHIVED and bypasses cache."""
        explainer = generate_canonical_explainer(force_topic="amc-charges")
        store.add_explainer(explainer)
        store.approve_explainer(explainer.explainer_id)

        query = "What is the quarterly AMC fee for demat accounts?"

        # Match succeeds when approved
        pre_match = store.find_matching_explainer(query)
        assert pre_match is not None

        # Admin clicks Invalidate Explainer
        invalidation_result = store.invalidate_explainer(explainer.explainer_id)
        assert invalidation_result is True
        assert store.get_explainer(explainer.explainer_id).status == "ARCHIVED"

        # Subsequent fast-path lookup immediately returns None
        post_match = store.find_matching_explainer(query)
        assert post_match is None


# ==============================================================================
# 4. Weekly Loop Escalation Integration (Criterion 4.3)
# ==============================================================================

class TestWeeklyLoopEscalationIntegration:
    """Tests for injecting high-frequency support topics into the Weekly Pulse executive report."""

    def test_escalated_topics_injected_into_weekly_pulse(self):
        """Escalated support topics (>= 5x/wk) appear in Weekly Pulse under <= 250 words cap."""
        coordinator = SyncCoordinator()
        coordinator.tracker.clear()

        now = datetime.now(timezone.utc)

        # Simulate 6 distinct users complaining about Call & Trade charges this week
        for i in range(1, 7):
            coordinator.tracker.record_inquiry(
                f"Why was I charged Rs 50 for phone trade order {i}?",
                user_id=f"user_ct_{i}",
                timestamp=now - timedelta(days=i % 5),
            )

        # Trigger weekly loop with automatic escalation injection
        result = coordinator.run_weekly_loop_with_escalations(week_identifier="2026-W47")

        pulse: WeeklyPulse = result["pulse"]

        # 1. Weekly Pulse must contain the escalated support topic
        assert "High-Frequency Support Inquiries" in pulse.pulse_text
        assert "Call & Trade" in pulse.pulse_text

        # 2. Strict word count cap <= 250 words must still be respected
        assert pulse.word_count <= 250

        # 3. Exactly 3 action ideas
        assert len(pulse.action_ideas) == 3


# ==============================================================================
# 5. Live Synchronization Verification (Criterion 4.4)
# ==============================================================================

class TestLiveSynchronization:
    """Tests live bi-directional sync: explainer approval immediately updates Response Loop without restart."""

    @pytest.mark.asyncio
    async def test_live_synchronization_without_restart(self):
        """Approval of an explainer in Weekly Loop immediately routes subsequent queries to fast-path."""
        store = CanonicalStore()
        store.clear()
        tracker = FrequencyTracker()
        tracker.clear()

        pipeline = ResponsePipeline(canonical_store=store, frequency_tracker=tracker)
        coordinator = SyncCoordinator(canonical_store=store, frequency_tracker=tracker)

        query = "Why was DP charge of Rs. 15.93 debited when selling shares?"

        # --- STEP 1: Before explainer approval ---
        # Query goes through 3-agent parallel mesh (fresh drafting)
        ticket_before = await pipeline.process_inquiry(query, ticket_id="tkt_pre_sync")

        assert isinstance(ticket_before, SupportTicket)
        assert ticket_before.canonical_explainer_id is None
        assert "Fast-path" not in (ticket_before.deliberation.orchestrator_notes or "")

        # --- STEP 2: Product Manager approves Canonical Explainer in Weekly Loop ---
        explainer = generate_canonical_explainer(force_topic="dp-charges")
        approved_explainer = coordinator.approve_and_sync_explainer(explainer, approved_by="prod_lead")

        assert approved_explainer.status == "APPROVED"
        assert store.get_explainer(explainer.explainer_id).status == "APPROVED"

        # --- STEP 3: After approval (No System Restart) ---
        # Subsequent query on the same pipeline instance immediately hits fast-path
        ticket_after = await pipeline.process_inquiry(query, ticket_id="tkt_post_sync")

        assert isinstance(ticket_after, SupportTicket)
        assert ticket_after.status == TicketStatus.PENDING_APPROVAL
        assert ticket_after.canonical_explainer_id == explainer.explainer_id
        assert ticket_after.sentence_count <= 3
        assert ticket_after.cited_url == "https://cdslindia.com/charges"
        assert "Fast-path" in ticket_after.deliberation.orchestrator_notes
        assert "Reused product-approved canonical explainer" in ticket_after.routing_note.reason
