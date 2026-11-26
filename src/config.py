"""Centralized application configuration using pydantic-settings."""

from pathlib import Path
from typing import List
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings and configuration parameters."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application Environment
    ENVIRONMENT: str = Field(default="development", description="Runtime environment")
    DEBUG: bool = Field(default=True, description="Debug mode flag")

    # API Gateway
    API_HOST: str = Field(default="0.0.0.0", description="API host interface")
    API_PORT: int = Field(default=8000, description="API port")

    # Corpus & Retrieval Paths
    CORPUS_DATA_DIR: Path = Field(
        default=Path("data/corpus"), description="Directory holding raw corpus files"
    )
    INDEX_CACHE_DIR: Path = Field(
        default=Path("data/index"), description="Directory holding index files"
    )
    VECTOR_INDEX_PATH: Path = Field(
        default=Path("data/index/corpus_index.pkl"),
        description="Path to serialized vector & BM25 index",
    )

    # Embedding & Retrieval Models
    EMBEDDING_MODEL_NAME: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2",
        description="Sentence Transformer model identifier",
    )
    RETRIEVAL_SIMILARITY_THRESHOLD: float = Field(
        default=0.72,
        ge=0.0,
        le=1.0,
        description="Minimum cosine similarity relevance threshold (tau_rel)",
    )
    CANONICAL_SIMILARITY_THRESHOLD: float = Field(
        default=0.88,
        ge=0.0,
        le=1.0,
        description="Cosine similarity threshold for canonical explainer fast match",
    )
    HYBRID_BM25_WEIGHT: float = Field(
        default=0.4, ge=0.0, le=1.0, description="BM25 score weighting in hybrid search"
    )
    HYBRID_DENSE_WEIGHT: float = Field(
        default=0.6, ge=0.0, le=1.0, description="Dense score weighting in hybrid search"
    )

    # System Hard Constraints & Caps
    RESPONSE_MAX_SENTENCES: int = Field(
        default=3, description="Maximum sentence count for support response drafts"
    )
    WEEKLY_PULSE_MAX_WORDS: int = Field(
        default=250, description="Maximum word count for executive weekly pulse"
    )
    EXPLAINER_MAX_BULLETS: int = Field(
        default=6, description="Maximum bullets for canonical fee explainers"
    )
    EXPLAINER_MIN_LINKS: int = Field(
        default=2, description="Minimum official links required in canonical explainers"
    )
    MAX_THEMES_CAP: int = Field(
        default=5, description="Maximum thematic clusters allowed in weekly review analysis"
    )
    TOP_THEMES_COUNT: int = Field(
        default=3, description="Number of top priority themes isolated"
    )
    FREQUENCY_ESCALATION_THRESHOLD: int = Field(
        default=5,
        description="Support inquiry frequency in a 7-day window to trigger pulse escalation",
    )

    # Storage & Audit
    AUDIT_LOG_PATH: Path = Field(
        default=Path("data/audit_diff_log.json"),
        description="Path to append-only audit diff log",
    )

    # Whitelisted Domains for Grounded Citations
    WHITELISTED_DOMAINS: List[str] = Field(
        default_factory=lambda: [
            "platform.in",
            "sebi.gov.in",
            "nseindia.com",
            "bseindia.com",
            "cdslindia.com",
        ],
        description="Domains permitted for factual citations",
    )

    # API Security & CORS
    SUPPORT_API_KEY: str = Field(
        default="hitl_live_sk_7f8a9b2c3d4e5f6a1b2c3d4e5f6a7b8c",
        description="API Key for HITL support operations and external client access",
    )
    CORS_ORIGINS: List[str] = Field(
        default_factory=lambda: [
            "https://investment-assistant-alpha.vercel.app",
            "https://web-production-a65a2102.up.railway.app",
            "http://localhost:3000",
            "http://localhost:8000",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:8000",
            "*",
        ],
        description="Allowed CORS origins",
    )

    # Weekly Scheduler Settings
    ENABLE_IN_APP_SCHEDULER: bool = Field(
        default=True,
        description="Enable background in-app scheduler for Weekly Loop execution",
    )
    WEEKLY_LOOP_INTERVAL_SECONDS: int = Field(
        default=604800,
        description="Interval in seconds between automated Weekly Loop cycles (7 days = 604800s)",
    )
    REQUIRE_CRON_API_KEY: bool = Field(
        default=True,
        description="Whether POST /api/product/run-weekly strictly requires a valid API key",
    )


# Global settings singleton accessor
_settings_instance: Settings | None = None


def get_settings() -> Settings:
    """Retrieve or initialize application settings."""
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = Settings()
    return _settings_instance
