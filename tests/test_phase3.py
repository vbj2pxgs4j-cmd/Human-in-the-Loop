"""Automated verification tests for Phase 3: Weekly Loop Pipeline.

Validates:
1. Review Ingestion & PII Sanitization (date window filtering, immutable IDs, PII redaction)
2. Thematic Clustering Engine (K <= 5 hard cap, top 3 isolated, fee friction isolated, 100% review lineage)
3. EC-WEEK-01: Sparse Review Volume (N < 5, N < 3)
4. Weekly Pulse Generator (word count <= 250, 2-3 quotes, exactly 3 action ideas)
5. EC-WEEK-03: Word Count Overflow enforcement (<= 250 words)
6. EC-WEEK-04: Quote Lineage Disconnection verification (Review #ID validation)
7. Canonical Fee Explainer Generator (<= 6 bullets, >= 2 official links, last_checked_date)
8. EC-WEEK-02: Zero Fee Complaints Fallback handling
9. Unattended Pipeline Runner (end-to-end non-interactive execution)
"""

import re
from datetime import datetime, timedelta, timezone
import pytest

from src.agents.weekly.clustering_engine import ClusteringEngine, cluster_reviews
from src.agents.weekly.explainer_generator import (
    ExplainerGenerator,
    generate_canonical_explainer,
)
from src.agents.weekly.pulse_generator import (
    PulseGenerator,
    count_words,
    generate_weekly_pulse,
)
from src.agents.weekly.review_ingest import (
    ReviewIngestor,
    get_sample_reviews,
    ingest_reviews,
)
from src.agents.weekly.runner import (
    WeeklyRunner,
    get_weekly_runner,
    run_weekly_pipeline,
)
from src.models.explainer import CanonicalExplainer
from src.models.review import ThemeCluster, UserReview, WeeklyPulse


# ==============================================================================
# 1. Review Ingestion & Sanitization Tests (Criterion 3.1)
# ==============================================================================

class TestReviewIngestion:
    """Tests for batch review ingestion, date window filtering, and PII scrubbing."""

    @pytest.fixture
    def ingestor(self) -> ReviewIngestor:
        return ReviewIngestor()

    def test_pii_scrubbed_on_ingestion(self, ingestor: ReviewIngestor):
        """Review ingestion must deterministically scrub PAN, phone numbers, and emails."""
        raw_items = [
            {
                "id": "rev_pan",
                "text": "My PAN is ABCDE1234F and mobile is 9876543210. Why did you deduct Rs 15.93?",
                "rating": 1.0,
            },
            {
                "id": "rev_email",
                "text": "Contact me at investor@test.com regarding unauthorized quarterly AMC charges.",
                "rating": 2.0,
            },
        ]
        reviews = ingestor.ingest_reviews(raw_items)

        assert len(reviews) == 2
        # Check PII redactions
        assert "[REDACTED_PAN]" in reviews[0].sanitized_text
        assert "ABCDE1234F" not in reviews[0].sanitized_text
        assert "[REDACTED_PHONE]" in reviews[0].sanitized_text
        assert "9876543210" not in reviews[0].sanitized_text

        assert "[REDACTED_EMAIL]" in reviews[1].sanitized_text
        assert "investor@test.com" not in reviews[1].sanitized_text

    def test_date_window_filtering(self, ingestor: ReviewIngestor):
        """Reviews outside [T_start, T_end] window must be excluded."""
        t_base = datetime(2026, 11, 23, 12, 0, 0, tzinfo=timezone.utc)
        items = [
            {
                "id": "rev_past",
                "text": "Old complaint from last month.",
                "timestamp": t_base - timedelta(days=10),
            },
            {
                "id": "rev_inside_1",
                "text": "DP charge complaint in current week.",
                "timestamp": t_base + timedelta(days=1),
            },
            {
                "id": "rev_inside_2",
                "text": "AMC complaint in current week.",
                "timestamp": t_base + timedelta(days=2),
            },
            {
                "id": "rev_future",
                "text": "Future review.",
                "timestamp": t_base + timedelta(days=15),
            },
        ]

        start_window = t_base
        end_window = t_base + timedelta(days=7)

        filtered = ingestor.ingest_reviews(items, start_date=start_window, end_date=end_window)

        assert len(filtered) == 2
        assert {r.review_id for r in filtered} == {"rev_inside_1", "rev_inside_2"}

    def test_immutable_review_id_generation(self, ingestor: ReviewIngestor):
        """Reviews without IDs must be assigned sequential immutable review_ids."""
        items = ["Complaint without ID 1", "Complaint without ID 2"]
        reviews = ingestor.ingest_reviews(items, prefix="test_rev")

        assert len(reviews) == 2
        assert reviews[0].review_id == "test_rev_001"
        assert reviews[1].review_id == "test_rev_002"

    def test_sample_reviews_ready(self):
        """Sample reviews generator must yield grounded reviews with PII scrubbed."""
        samples = get_sample_reviews("2026-W47")
        assert len(samples) >= 15
        for s in samples:
            assert s.review_id.startswith("rev_")
            assert len(s.sanitized_text) > 10
            assert "9876543210" not in s.sanitized_text
            assert "ABCDE1234F" not in s.sanitized_text

    def test_load_from_json(self, ingestor: ReviewIngestor, tmp_path):
        """Review ingestion must support loading reviews directly from JSON files."""
        import json
        json_file = tmp_path / "reviews.json"
        raw_data = [
            {"id": "rev_j1", "text": "DP charge debited on selling shares."},
            {"id": "rev_j2", "text": "Quarterly AMC deduction issue."},
        ]
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(raw_data, f)

        loaded = ingestor.load_from_json(json_file)
        assert len(loaded) == 2
        assert loaded[0].review_id == "rev_j1"
        assert loaded[1].review_id == "rev_j2"


# ==============================================================================
# 2. Thematic Clustering Engine Tests (Criterion 3.2 & EC-WEEK-01)
# ==============================================================================

class TestThematicClustering:
    """Tests for vector clustering, cap constraints, ranking, and fee theme isolation."""

    @pytest.fixture
    def engine(self) -> ClusteringEngine:
        return ClusteringEngine()

    @pytest.fixture
    def reviews(self) -> list[UserReview]:
        return get_sample_reviews("2026-W47")

    def test_cluster_cap_constraint(self, engine: ClusteringEngine, reviews: list[UserReview]):
        """Cluster count must strictly not exceed MAX_THEMES_CAP = 5."""
        clusters = engine.cluster_reviews(reviews, week_identifier="2026-W47")

        assert 1 <= len(clusters) <= 5
        for c in clusters:
            assert c.week_identifier == "2026-W47"
            assert len(c.theme_title) >= 3
            assert c.review_count == len(c.review_ids)

    def test_top_three_themes_isolated(self, engine: ClusteringEngine, reviews: list[UserReview]):
        """Top 3 themes by volume/negative friction must be tagged with is_top_three=True."""
        clusters = engine.cluster_reviews(reviews, week_identifier="2026-W47")

        top_three = [c for c in clusters if c.is_top_three]
        expected_count = min(3, len(clusters))
        assert len(top_three) == expected_count

    def test_dominant_fee_friction_isolated(self, engine: ClusteringEngine, reviews: list[UserReview]):
        """Dominant recurring fee friction theme must be tagged with is_fee_confusion=True."""
        clusters = engine.cluster_reviews(reviews, week_identifier="2026-W47")

        fee_clusters = [c for c in clusters if c.is_fee_confusion]
        assert len(fee_clusters) == 1
        fee_theme = fee_clusters[0]

        # Should match DP charges or AMC
        assert any(term in fee_theme.theme_title.lower() for term in ["dp", "charges", "amc", "maintenance"])

    def test_complete_data_lineage(self, engine: ClusteringEngine, reviews: list[UserReview]):
        """100% of input reviews must be accounted for in the generated cluster review_ids."""
        clusters = engine.cluster_reviews(reviews, week_identifier="2026-W47")

        all_clustered_ids: set[str] = set()
        for c in clusters:
            all_clustered_ids.update(c.review_ids)

        expected_ids = {r.review_id for r in reviews}
        assert all_clustered_ids == expected_ids

    def test_sparse_review_volume_clustering(self, engine: ClusteringEngine):
        """EC-WEEK-01: When N < 5 or N < 3, clustering must handle sparse batches gracefully."""
        # 1. Very sparse: N = 2 reviews (< 3)
        sparse_two = [
            UserReview(
                review_id="rev_s1",
                sanitized_text="DP charge of Rs 15.93 debited on selling shares without notice.",
                timestamp=datetime.now(timezone.utc),
            ),
            UserReview(
                review_id="rev_s2",
                sanitized_text="Why was Rs 15.93 demat debit charged today?",
                timestamp=datetime.now(timezone.utc),
            ),
        ]
        clusters_two = engine.cluster_reviews(sparse_two, week_identifier="2026-W47")

        # N < 3 must collapse into a single consolidated theme without throwing ValueError
        assert len(clusters_two) == 1
        assert clusters_two[0].review_count == 2
        assert set(clusters_two[0].review_ids) == {"rev_s1", "rev_s2"}
        assert clusters_two[0].is_top_three is True

        # 2. Sparse: N = 4 reviews (< 5)
        sparse_four = [
            UserReview(
                review_id="rev_a",
                sanitized_text="DP charges debited on equity sell.",
                timestamp=datetime.now(timezone.utc),
            ),
            UserReview(
                review_id="rev_b",
                sanitized_text="App login OTP is extremely slow.",
                timestamp=datetime.now(timezone.utc),
            ),
            UserReview(
                review_id="rev_c",
                sanitized_text="Why was quarterly AMC debited from account?",
                timestamp=datetime.now(timezone.utc),
            ),
            UserReview(
                review_id="rev_d",
                sanitized_text="Biometric login failed again.",
                timestamp=datetime.now(timezone.utc),
            ),
        ]
        clusters_four = engine.cluster_reviews(sparse_four, week_identifier="2026-W47")
        assert len(clusters_four) <= 4
        all_ids = {rid for c in clusters_four for rid in c.review_ids}
        assert all_ids == {"rev_a", "rev_b", "rev_c", "rev_d"}


# ==============================================================================
# 3. Weekly Pulse Generator Tests (Criterion 3.3, EC-WEEK-03, EC-WEEK-04)
# ==============================================================================

class TestWeeklyPulseGenerator:
    """Tests for executive weekly pulse generation, length caps, and quote-to-review lineage."""

    @pytest.fixture
    def generator(self) -> PulseGenerator:
        return PulseGenerator()

    @pytest.fixture
    def setup_data(self) -> tuple[list[UserReview], list[ThemeCluster]]:
        reviews = get_sample_reviews("2026-W47")
        clusters = cluster_reviews(reviews, "2026-W47")
        return reviews, clusters

    def test_weekly_pulse_word_count_cap(
        self,
        generator: PulseGenerator,
        setup_data: tuple[list[UserReview], list[ThemeCluster]],
    ):
        """EC-WEEK-03: Weekly Pulse text must strictly stay within <= 250 words."""
        reviews, clusters = setup_data
        pulse = generator.generate_pulse(reviews, clusters, week_identifier="2026-W47")

        assert pulse.word_count <= 250
        assert count_words(pulse.pulse_text) <= 250
        assert len(pulse.pulse_text) > 50

    def test_supporting_quotes_and_action_ideas(
        self,
        generator: PulseGenerator,
        setup_data: tuple[list[UserReview], list[ThemeCluster]],
    ):
        """Weekly Pulse must contain 2-3 quotes citing (Review #ID) and strictly 3 action ideas."""
        reviews, clusters = setup_data
        pulse = generator.generate_pulse(reviews, clusters, week_identifier="2026-W47")

        # 2 to 3 quotes
        assert 2 <= len(pulse.supporting_quotes) <= 3
        for q in pulse.supporting_quotes:
            assert re.search(r'\(Review\s*#rev_\d+\)', q) is not None

        # Exactly 3 action ideas
        assert len(pulse.action_ideas) == 3
        for idea in pulse.action_ideas:
            assert len(idea) >= 10

    def test_quote_review_id_lineage(
        self,
        generator: PulseGenerator,
        setup_data: tuple[list[UserReview], list[ThemeCluster]],
    ):
        """EC-WEEK-04: Every cited quote must trace back to a valid review in the batch."""
        reviews, clusters = setup_data
        pulse = generator.generate_pulse(reviews, clusters, week_identifier="2026-W47")

        # Lineage validator must pass
        assert PulseGenerator.validate_quote_lineage(pulse, reviews) is True

    def test_quote_lineage_detects_tampered_review_id(
        self,
        generator: PulseGenerator,
        setup_data: tuple[list[UserReview], list[ThemeCluster]],
    ):
        """EC-WEEK-04: If a quote has a non-existent review ID, lineage validation must fail."""
        reviews, clusters = setup_data
        pulse = generator.generate_pulse(reviews, clusters, week_identifier="2026-W47")

        # Tamper quote with fake review ID
        tampered_quotes = list(pulse.supporting_quotes)
        tampered_quotes[0] = '"Fake complaint." (Review #rev_non_existent)'
        tampered_pulse = pulse.model_copy(update={"supporting_quotes": tampered_quotes})

        assert PulseGenerator.validate_quote_lineage(tampered_pulse, reviews) is False

    def test_pulse_with_escalated_topics(
        self,
        generator: PulseGenerator,
        setup_data: tuple[list[UserReview], list[ThemeCluster]],
    ):
        """Weekly Pulse must incorporate escalated support topics while maintaining <= 250 words cap."""
        reviews, clusters = setup_data
        escalated = [
            "Why was DP charge of Rs 15.93 debited on selling shares?",
            "What is the quarterly AMC fee for demat accounts?",
        ]
        pulse = generator.generate_pulse(
            reviews,
            clusters,
            week_identifier="2026-W47",
            escalated_topics=escalated,
        )

        assert pulse.word_count <= 250
        assert "High-Frequency Support Inquiries" in pulse.pulse_text
        assert len(pulse.action_ideas) == 3


# ==============================================================================
# 4. Canonical Fee Explainer Generator Tests (Criterion 3.4 & EC-WEEK-02)
# ==============================================================================

class TestCanonicalFeeExplainerGenerator:
    """Tests for Canonical Fee Explainer generation, bullet caps, and official link citations."""

    @pytest.fixture
    def generator(self) -> ExplainerGenerator:
        return ExplainerGenerator()

    def test_explainer_constraints_with_fee_cluster(self, generator: ExplainerGenerator):
        """Explainer must satisfy: <= 6 bullets, >= 2 official source links, last_checked_date."""
        fee_cluster = ThemeCluster(
            cluster_id="cluster_w47_01",
            week_identifier="2026-W47",
            theme_title="DP Charges Surprise on Equity Sell",
            review_ids=["rev_001", "rev_002"],
            review_count=2,
            is_top_three=True,
            is_fee_confusion=True,
            summary="Users confused about DP charges on delivery sell.",
        )

        explainer = generator.generate_explainer(fee_cluster=fee_cluster)

        assert isinstance(explainer, CanonicalExplainer)
        assert explainer.topic_slug == "dp-charges"
        assert 1 <= explainer.bullet_count <= 6
        assert len(explainer.bullet_points) <= 6
        assert len(set(explainer.source_urls)) >= 2
        assert explainer.status == "DRAFT"
        assert explainer.last_checked_date <= datetime.now(timezone.utc)
        assert explainer.embedding is not None

        # Verify whitelisted domains
        for url in explainer.source_urls:
            assert any(d in url for d in ["platform.in", "cdslindia.com", "sebi.gov.in"])

    def test_zero_fee_complaints_fallback(self, generator: ExplainerGenerator):
        """EC-WEEK-02: If zero fee complaints in batch, fallback to top historical fee topic with disclaimer."""
        # Non-fee cluster (e.g. App login latency only)
        non_fee_cluster = ThemeCluster(
            cluster_id="cluster_w47_02",
            week_identifier="2026-W47",
            theme_title="App Login & OTP Timeout Latency",
            review_ids=["rev_011", "rev_012"],
            review_count=2,
            is_top_three=True,
            is_fee_confusion=False,
            summary="Users experiencing SMS OTP timeout.",
        )

        explainer = generator.generate_explainer(
            fee_cluster=non_fee_cluster,
            zero_fee_fallback=True,
        )

        assert isinstance(explainer, CanonicalExplainer)
        # Check disclaimer note
        expected_note = (
            "Note: Zero fee complaints detected in current weekly batch. "
            "Explainer generated for top historical query topic."
        )
        assert any(expected_note in b for b in explainer.bullet_points)
        assert explainer.bullet_count <= 6
        assert len(set(explainer.source_urls)) >= 2

    def test_explainer_templates_coverage(self, generator: ExplainerGenerator):
        """Test synthesis of explainers across all canonical fee topic domains."""
        topics = ["amc-charges", "statutory-stt-charges", "brokerage-delivery"]
        for topic in topics:
            explainer = generator.generate_explainer(force_topic=topic)
            assert explainer.topic_slug == topic
            assert 1 <= explainer.bullet_count <= 6
            assert len(set(explainer.source_urls)) >= 2
            assert explainer.embedding is not None


# ==============================================================================
# 5. Unattended Pipeline Runner Tests (Criterion 3.5 & End-to-End)
# ==============================================================================

class TestUnattendedWeeklyRunner:
    """Tests for complete non-interactive pipeline execution without user prompts."""

    @pytest.fixture
    def runner(self) -> WeeklyRunner:
        return get_weekly_runner()

    def test_unattended_pipeline_execution(self, runner: WeeklyRunner):
        """Pipeline must run start-to-finish without prompts and produce all valid models."""
        reviews = get_sample_reviews("2026-W47")

        result = runner.run_pipeline(
            reviews_data=reviews,
            week_identifier="2026-W47",
        )

        assert result is not None
        assert result["week_identifier"] == "2026-W47"
        assert len(result["reviews"]) == len(reviews)
        assert 1 <= len(result["clusters"]) <= 5

        # WeeklyPulse assertions
        pulse: WeeklyPulse = result["pulse"]
        assert pulse.word_count <= 250
        assert 2 <= len(pulse.supporting_quotes) <= 3
        assert len(pulse.action_ideas) == 3
        assert pulse.approval_status == "PENDING_APPROVAL"

        # CanonicalExplainer assertions
        explainer: CanonicalExplainer = result["explainer"]
        assert 1 <= explainer.bullet_count <= 6
        assert len(set(explainer.source_urls)) >= 2
        assert explainer.status == "DRAFT"

        # Metadata assertions
        metadata = result["metadata"]
        assert metadata["unattended_execution"] is True
        assert metadata["lineage_valid"] is True
        assert "pulse_state_hash" in metadata
        assert "explainer_state_hash" in metadata

    def test_run_weekly_pipeline_functional_default(self):
        """Calling run_weekly_pipeline() with zero arguments runs completely on defaults."""
        result = run_weekly_pipeline()

        assert result is not None
        assert "pulse" in result
        assert "explainer" in result
        assert result["metadata"]["unattended_execution"] is True

    def test_sparse_reviews_unattended_execution(self, runner: WeeklyRunner):
        """EC-WEEK-01 & unattended: Sparse reviews run start-to-finish without interactive failure."""
        sparse_batch = [
            "DP fee Rs 15 charged on selling shares [REDACTED_PHONE]",
            "Another DP charge complaint",
        ]
        result = runner.run_pipeline(
            reviews_data=sparse_batch,
            week_identifier="2026-W48",
        )

        assert len(result["reviews"]) == 2
        assert len(result["clusters"]) == 1
        assert result["pulse"].word_count <= 250
        assert result["explainer"].bullet_count <= 6
