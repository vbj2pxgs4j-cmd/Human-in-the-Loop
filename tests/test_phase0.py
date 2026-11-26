"""Unit and integration verification tests for Phase 0.

Validates:
1. Environment & configuration management (pydantic-settings, .env.example)
2. Core Pydantic data schemas & constraints (word caps, bullet caps, URL validations, enums)
3. Milestone 1 corpus curation, completeness, and metadata freshness
4. Hybrid retrieval engine (semantic chunking, BM25, dense embeddings, search accuracy)
5. Index serialization and cache persistence
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from pydantic import ValidationError

from src.config import Settings, get_settings
from src.models.corpus import CorpusChunk, CorpusDocument, SearchResult
from src.models.review import ThemeCluster, UserReview, WeeklyPulse
from src.models.explainer import CanonicalExplainer
from src.models.ticket import (
    AgentDeliberation,
    RoutingCategory,
    RoutingNote,
    RoutingUrgency,
    SentimentType,
    SupportTicket,
    TicketStatus,
)
from src.models.audit import AuditDiffLog, PatchOperation, StateDiff
from src.retrieval.corpus_indexer import CorpusIndexer, simple_tokenize


# ==============================================================================
# 1. Configuration & Environment Tests
# ==============================================================================

def test_settings_initialization():
    """Verify application settings load with required default parameters and constraints."""
    settings = get_settings()
    assert settings.ENVIRONMENT in ("development", "production", "test")
    assert settings.RETRIEVAL_SIMILARITY_THRESHOLD == 0.72
    assert settings.CANONICAL_SIMILARITY_THRESHOLD == 0.88
    assert settings.RESPONSE_MAX_SENTENCES == 3
    assert settings.WEEKLY_PULSE_MAX_WORDS == 250
    assert settings.EXPLAINER_MAX_BULLETS == 6
    assert settings.EXPLAINER_MIN_LINKS == 2
    assert settings.MAX_THEMES_CAP == 5
    assert settings.TOP_THEMES_COUNT == 3
    assert settings.FREQUENCY_ESCALATION_THRESHOLD == 5
    assert len(settings.WHITELISTED_DOMAINS) >= 3
    assert "platform.in" in settings.WHITELISTED_DOMAINS


def test_env_example_contains_all_core_settings():
    """Ensure .env.example defines all critical configuration keys."""
    env_example_path = Path(".env.example")
    assert env_example_path.exists(), ".env.example must be present in project root"

    content = env_example_path.read_text(encoding="utf-8")
    expected_keys = [
        "ENVIRONMENT",
        "EMBEDDING_MODEL_NAME",
        "RETRIEVAL_SIMILARITY_THRESHOLD",
        "CANONICAL_SIMILARITY_THRESHOLD",
        "RESPONSE_MAX_SENTENCES",
        "WEEKLY_PULSE_MAX_WORDS",
        "EXPLAINER_MAX_BULLETS",
        "MAX_THEMES_CAP",
        "FREQUENCY_ESCALATION_THRESHOLD",
    ]
    for key in expected_keys:
        assert key in content, f"Missing key {key} in .env.example"


# ==============================================================================
# 2. Pydantic Schema Validation Tests
# ==============================================================================

class TestCorpusModels:
    """Tests for CorpusDocument, CorpusChunk, and SearchResult models."""

    def test_corpus_document_valid(self):
        doc = CorpusDocument(
            doc_id="doc_test_01",
            title="Equity Brokerage Tariff",
            source_url="https://platform.in/charges",
            category="BROKERAGE",
            content="Equity delivery is free with zero brokerage across all exchanges.",
            last_updated=datetime.now(timezone.utc),
            metadata={"version": "1.0"},
        )
        assert doc.doc_id == "doc_test_01"
        assert doc.source_url == "https://platform.in/charges"

    def test_corpus_document_invalid_url(self):
        with pytest.raises(ValidationError):
            CorpusDocument(
                doc_id="doc_test_bad",
                title="Invalid URL Document",
                source_url="not-a-valid-url",
                category="BROKERAGE",
                content="Some sample content.",
                last_updated=datetime.now(timezone.utc),
            )

    def test_corpus_chunk_and_search_result(self):
        chunk = CorpusChunk(
            chunk_id="doc_test_01#chunk_0",
            doc_id="doc_test_01",
            content="Sample text content for chunk.",
            source_url="https://platform.in/charges",
            chunk_index=0,
            token_count=6,
        )
        assert chunk.chunk_id == "doc_test_01#chunk_0"

        res = SearchResult(
            chunk_id=chunk.chunk_id,
            doc_id=chunk.doc_id,
            content=chunk.content,
            source_url=chunk.source_url,
            score=0.895,
            bm25_score=0.91,
            dense_score=0.88,
        )
        assert res.score == 0.895
        assert res.source_url == "https://platform.in/charges"


class TestReviewAndWeeklyPulseModels:
    """Tests for UserReview, ThemeCluster, and WeeklyPulse models."""

    def test_user_review_valid(self):
        review = UserReview(
            review_id="rev_101",
            sanitized_text="Charged Rs 15 without warning on selling shares! [REDACTED_PHONE]",
            timestamp=datetime.now(timezone.utc),
            rating=1.0,
            platform="PlayStore",
        )
        assert review.review_id == "rev_101"
        assert review.rating == 1.0

    def test_theme_cluster_count_sync(self):
        cluster = ThemeCluster(
            cluster_id="cluster_01",
            week_identifier="2026-W47",
            theme_title="DP Charges Surprise on Equity Sell",
            review_ids=["rev_101", "rev_102", "rev_103"],
            review_count=1,  # will be auto-synced to 3
            is_top_three=True,
            is_fee_confusion=True,
        )
        assert cluster.review_count == 3

    def test_weekly_pulse_valid(self):
        text = (
            "This week user feedback was dominated by DP charge confusion on delivery sales. "
            "Users perceived the Rs 15 fee as a hidden deduction rather than an exchange depository levy. "
            "AMC deductions also triggered minor friction for low-balance accounts."
        )
        pulse = WeeklyPulse(
            pulse_id="pulse_2026_w47",
            week_identifier="2026-W47",
            pulse_text=text,
            word_count=len(text.split()),
            supporting_quotes=[
                "Why was Rs 15 deducted when delivery is free? (Review #rev_101)",
                "Unexpected charge in my account statement! (Review #rev_102)",
            ],
            action_ideas=[
                "Introduce an in-app post-trade fee breakdown popup.",
                "Publish a visual explainer in the help desk for DP charges.",
                "Send email notification 48 hours prior to quarterly AMC debit.",
            ],
            top_theme_ids=["cluster_01", "cluster_02"],
        )
        assert pulse.word_count <= 250
        assert len(pulse.action_ideas) == 3

    def test_weekly_pulse_word_cap_exceeded(self):
        """WeeklyPulse must reject text exceeding 250 words."""
        overflow_text = "word " * 255
        with pytest.raises(ValidationError):
            WeeklyPulse(
                pulse_id="pulse_overflow",
                week_identifier="2026-W47",
                pulse_text=overflow_text,
                word_count=255,
                supporting_quotes=["A quote (Review #rev_01)"],
                action_ideas=["Idea 1", "Idea 2", "Idea 3"],
            )

    def test_weekly_pulse_action_ideas_count_constraint(self):
        """WeeklyPulse must enforce exactly 3 action ideas."""
        text = "Valid pulse report under 250 words."
        # 2 action ideas instead of 3
        with pytest.raises(ValidationError):
            WeeklyPulse(
                pulse_id="pulse_bad_actions",
                week_identifier="2026-W47",
                pulse_text=text,
                word_count=len(text.split()),
                supporting_quotes=["A quote (Review #rev_01)"],
                action_ideas=["Idea 1", "Idea 2"],
            )


class TestCanonicalExplainerModel:
    """Tests for CanonicalExplainer constraints (<= 6 bullets, >= 2 source links)."""

    def test_canonical_explainer_valid(self):
        explainer = CanonicalExplainer(
            explainer_id="expl_dp_charges",
            topic_slug="dp-charges-explained",
            title="Understanding Depository Participant (DP) Charges",
            bullet_points=[
                "DP charges are collected by CDSL/NSDL depositories when shares are debited from your demat account.",
                "The fee is flat Rs. 13.50 + 18% GST (total Rs. 15.93) per company per day on selling.",
                "Selling 1 share or 500 shares of the same company on the same day incurs only one DP charge.",
                "Equity intraday trades and buying shares incur zero DP charges.",
            ],
            source_urls=[
                "https://cdslindia.com/charges",
                "https://platform.in/charges",
            ],
            last_checked_date=datetime.now(timezone.utc),
            status="APPROVED",
        )
        assert explainer.bullet_count == 4
        assert len(explainer.source_urls) >= 2

    def test_canonical_explainer_bullet_cap_exceeded(self):
        """CanonicalExplainer must reject more than 6 bullet points."""
        with pytest.raises(ValidationError):
            CanonicalExplainer(
                explainer_id="expl_overflow",
                topic_slug="overflow-slug",
                title="Overflow Explainer",
                bullet_points=[f"Bullet point {i}" for i in range(1, 8)],  # 7 bullets
                source_urls=[
                    "https://cdslindia.com/charges",
                    "https://platform.in/charges",
                ],
                last_checked_date=datetime.now(timezone.utc),
            )

    def test_canonical_explainer_requires_two_source_urls(self):
        """CanonicalExplainer must reject fewer than 2 distinct source URLs."""
        with pytest.raises(ValidationError):
            CanonicalExplainer(
                explainer_id="expl_missing_urls",
                topic_slug="missing-urls",
                title="Single URL Explainer",
                bullet_points=["Point 1", "Point 2"],
                source_urls=["https://platform.in/charges"],  # Only 1 URL
                last_checked_date=datetime.now(timezone.utc),
            )


class TestTicketAndAuditModels:
    """Tests for SupportTicket, RoutingNote, and Audit models."""

    def test_support_ticket_valid(self):
        note = RoutingNote(
            category=RoutingCategory.DP_CHARGES,
            urgency=RoutingUrgency.MEDIUM,
            sentiment=SentimentType.CONFUSED,
            reason="User confused regarding Rs 15.93 debit on selling TCS shares.",
        )
        ticket = SupportTicket(
            ticket_id="tkt_10293",
            raw_query_redacted="Why was Rs 15 debited from my account after selling shares yesterday?",
            proposed_draft="Depository Participant (DP) charges of Rs. 13.50 + 18% GST apply when selling equity delivery shares from your demat account. This fee is levied flat per company per day regardless of the quantity sold. Official schedule: https://platform.in/charges",
            sentence_count=3,
            cited_url="https://platform.in/charges",
            routing_note=note,
            status=TicketStatus.PENDING_APPROVAL,
            created_at=datetime.now(timezone.utc),
        )
        assert ticket.ticket_id == "tkt_10293"
        assert ticket.sentence_count <= 3
        assert ticket.routing_note.category == RoutingCategory.DP_CHARGES

    def test_audit_diff_log_valid(self):
        audit = AuditDiffLog(
            audit_id="aud_8492049",
            timestamp=datetime.now(timezone.utc),
            operator_id="agent_rahul",
            entity_type="ticket",
            entity_id="tkt_10293",
            action="APPROVE",
            pre_state_hash="a" * 64,
            post_state_hash="b" * 64,
            diff=[
                {"op": "replace", "path": "/status", "value": "APPROVED"}
            ],
        )
        assert audit.audit_id == "aud_8492049"
        assert len(audit.diff) == 1
        assert audit.diff[0]["op"] == "replace"


# ==============================================================================
# 3. Milestone 1 Corpus Curation & Freshness Tests
# ==============================================================================

def test_milestone1_corpus_loading():
    """Verify that all Milestone 1 documents in data/corpus are present and valid."""
    corpus_dir = Path("data/corpus")
    assert corpus_dir.exists(), "data/corpus directory must exist"

    files = list(corpus_dir.glob("*.json"))
    assert len(files) >= 4, f"Expected at least 4 corpus documents, found {len(files)}"

    loaded_categories = set()
    for file_path in files:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            doc = CorpusDocument(**data)
            assert doc.doc_id
            assert doc.title
            assert doc.source_url.startswith("http")
            assert len(doc.content) > 50
            loaded_categories.add(doc.category)

    # All required core categories must be present
    expected_categories = {"BROKERAGE", "STATUTORY_CHARGES", "DP_CHARGES", "ACCOUNT_MAINTENANCE"}
    assert expected_categories.issubset(loaded_categories), f"Missing categories: {expected_categories - loaded_categories}"


def test_corpus_source_urls_whitelisted():
    """Verify that all corpus documents cite official whitelisted domains."""
    settings = get_settings()
    corpus_dir = Path("data/corpus")

    for file_path in corpus_dir.glob("*.json"):
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            doc = CorpusDocument(**data)
            url_domain = doc.source_url.split("/")[2]
            assert any(
                allowed in url_domain for allowed in settings.WHITELISTED_DOMAINS
            ), f"Source URL {doc.source_url} not in whitelisted domains {settings.WHITELISTED_DOMAINS}"


def test_corpus_metadata_freshness():
    """Verify EC-RAG-03: Corpus documents must have recent last_updated timestamp (< 90 days)."""
    corpus_dir = Path("data/corpus")
    now = datetime.now(timezone.utc)
    max_age_days = 90

    for file_path in corpus_dir.glob("*.json"):
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            doc = CorpusDocument(**data)
            doc_date = doc.last_updated
            if doc_date.tzinfo is None:
                doc_date = doc_date.replace(tzinfo=timezone.utc)
            # Ensure document is not stale (> 90 days in the past from reference baseline)
            # Reference baseline allows recent 2026 updates
            age_days = abs((now - doc_date).days)
            assert age_days <= max_age_days, f"Document {doc.doc_id} is stale: {age_days} days old"


# ==============================================================================
# 4. Hybrid Corpus Indexing & Baseline Retrieval Tests
# ==============================================================================

def test_semantic_chunking_logic():
    """Verify semantic chunking splits long documents into passages of 250-400 words with overlap."""
    indexer = CorpusIndexer()
    sample_content = "\n\n".join([f"Section {i}: " + ("Trade terms and fee disclosures. " * 30) for i in range(1, 10)])
    doc = CorpusDocument(
        doc_id="doc_large_test",
        title="Large Brokerage Document",
        source_url="https://platform.in/charges",
        category="BROKERAGE",
        content=sample_content,
        last_updated=datetime.now(timezone.utc),
    )

    chunks = indexer.chunk_document(doc, chunk_size=300, overlap=50)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.doc_id == "doc_large_test"
        assert chunk.chunk_id.startswith("doc_large_test#chunk_")
        assert chunk.source_url == "https://platform.in/charges"
        assert chunk.token_count <= 400


def test_hybrid_corpus_indexing_and_search():
    """Verify indexing Milestone 1 corpus and performing hybrid BM25 + Dense search."""
    indexer = CorpusIndexer()
    indexer.load_and_index_corpus(corpus_dir="data/corpus", force_reindex=True)

    assert len(indexer.documents) >= 4
    assert len(indexer.chunks) >= 4
    assert indexer.chunk_embeddings is not None
    assert indexer.bm25 is not None

    # Test 1: Equity delivery brokerage query
    query_delivery = "Is equity delivery free or what is the brokerage charge?"
    results_delivery = indexer.search_corpus(query_delivery, top_k=3)
    assert len(results_delivery) > 0
    top_result = results_delivery[0]
    assert "platform.in/charges" in top_result.source_url
    assert "brokerage" in top_result.content.lower() or "free" in top_result.content.lower()
    assert top_result.score > 0.5

    # Test 2: Depository Participant (DP) charge query
    query_dp = "Why was DP charge of Rs 15 deducted when I sold shares?"
    results_dp = indexer.search_corpus(query_dp, top_k=3)
    assert len(results_dp) > 0
    dp_top = results_dp[0]
    assert "13.50" in dp_top.content or "dp" in dp_top.content.lower()
    assert dp_top.source_url in ("https://cdslindia.com/charges", "https://platform.in/charges")

    # Test 3: STT tax query
    query_stt = "What is the Securities Transaction Tax rate for delivery trades?"
    results_stt = indexer.search_corpus(query_stt, top_k=3)
    assert len(results_stt) > 0
    stt_top = results_stt[0]
    assert "stt" in stt_top.content.lower() or "0.1%" in stt_top.content
    assert "sebi.gov.in/charges" in stt_top.source_url or "platform.in" in stt_top.source_url

    # Test 4: Demat AMC query
    query_amc = "What is the annual maintenance charge AMC for demat account?"
    results_amc = indexer.search_corpus(query_amc, top_k=3)
    assert len(results_amc) > 0
    amc_top = results_amc[0]
    assert "amc" in amc_top.content.lower() or "300" in amc_top.content or "bsda" in amc_top.content.lower()


def test_index_save_and_load(tmp_path: Path):
    """Verify that serialized index roundtrips cleanly without loss of search capability."""
    indexer = CorpusIndexer()
    indexer.load_and_index_corpus(corpus_dir="data/corpus", force_reindex=True)

    cache_path = tmp_path / "test_corpus_index.pkl"
    indexer.save_index(cache_path)
    assert cache_path.exists()

    new_indexer = CorpusIndexer()
    success = new_indexer.load_index(cache_path)
    assert success is True
    assert len(new_indexer.chunks) == len(indexer.chunks)
    assert len(new_indexer.documents) == len(indexer.documents)

    # Confirm search works on reloaded index
    results = new_indexer.search_corpus("brokerage charges equity delivery", top_k=2)
    assert len(results) > 0
    assert results[0].score > 0.5


# ==============================================================================
# 5. Schema & Retrieval Boundary Edge Cases (100% Coverage Suite)
# ==============================================================================

def test_explainer_validation_edge_cases():
    """Verify empty bullets, invalid URLs, and count sync validations in CanonicalExplainer."""
    # Empty bullets
    with pytest.raises(ValidationError):
        CanonicalExplainer(
            explainer_id="expl_empty",
            topic_slug="empty-slug",
            title="Empty Explainer",
            bullet_points=[],
            source_urls=["https://platform.in/charges", "https://sebi.gov.in/charges"],
            last_checked_date=datetime.now(timezone.utc),
        )

    # Invalid source URL scheme (e.g. ftp:// or missing netloc)
    with pytest.raises(ValidationError):
        CanonicalExplainer(
            explainer_id="expl_bad_url",
            topic_slug="bad-url",
            title="Bad URL Explainer",
            bullet_points=["Point 1", "Point 2"],
            source_urls=["ftp://invalid-scheme.com", "https://platform.in/charges"],
            last_checked_date=datetime.now(timezone.utc),
        )


def test_ticket_cited_url_validation():
    """Verify invalid cited_url scheme raises ValidationError in SupportTicket."""
    with pytest.raises(ValidationError):
        SupportTicket(
            ticket_id="tkt_bad_url",
            raw_query_redacted="Query",
            proposed_draft="Draft text.",
            sentence_count=1,
            cited_url="invalid_url_without_scheme",
            created_at=datetime.now(timezone.utc),
        )


def test_retrieval_edge_cases(tmp_path: Path):
    """Verify retrieval edge cases: empty queries, min_score threshold, long chunking, and index errors."""
    indexer = CorpusIndexer()
    indexer.load_and_index_corpus(corpus_dir="data/corpus")

    # Empty query returns empty list
    assert indexer.search_corpus("") == []
    assert indexer.search_corpus("   ") == []

    # High min_score filters out lower results
    high_score_res = indexer.search_corpus("equity delivery brokerage", min_score=0.999)
    assert len(high_score_res) == 0

    # Test singleton get_corpus_indexer
    from src.retrieval.corpus_indexer import get_corpus_indexer
    singleton = get_corpus_indexer(force_reinit=True)
    assert singleton is not None
    assert len(singleton.chunks) > 0

    # Test error handling when corpus directory does not exist
    bad_indexer = CorpusIndexer()
    with pytest.raises(FileNotFoundError):
        bad_indexer.load_and_index_corpus(corpus_dir="non_existent_directory_xyz", force_reindex=True)

    # Test error handling when directory has no JSON files
    empty_dir = tmp_path / "empty_corpus"
    empty_dir.mkdir()
    with pytest.raises(ValueError):
        bad_indexer.load_and_index_corpus(corpus_dir=empty_dir, force_reindex=True)

    # Test document with long section exceeding chunk_size triggering sliding window
    long_section = "Word " * 450
    doc = CorpusDocument(
        doc_id="doc_long_sliding",
        title="Long Section Document",
        source_url="https://platform.in/charges",
        category="BROKERAGE",
        content=long_section,
        last_updated=datetime.now(timezone.utc),
    )
    chunks = indexer.chunk_document(doc, chunk_size=300, overlap=50)
    assert len(chunks) >= 2

