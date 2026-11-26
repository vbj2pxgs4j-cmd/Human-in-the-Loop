"""Review and Weekly Loop models: UserReview, ThemeCluster, and WeeklyPulse."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class UserReview(BaseModel):
    """Sanitized user review ingested from app stores or user feedback touchpoints."""

    review_id: str = Field(..., description="Unique immutable review identifier, e.g. rev_001")
    sanitized_text: str = Field(..., min_length=1, description="PII-sanitized review text")
    timestamp: datetime = Field(..., description="Review submission date and time")
    rating: Optional[float] = Field(default=None, ge=1.0, le=5.0, description="Star rating 1-5")
    platform: str = Field(default="PlayStore", description="Source platform (PlayStore, AppStore, Web)")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadata such as app version")


class ThemeCluster(BaseModel):
    """Thematic grouping of reviews constrained by the weekly clustering engine."""

    cluster_id: str = Field(..., description="Cluster identifier, e.g. cluster_w47_01")
    week_identifier: str = Field(..., description="ISO week identifier, e.g. 2026-W47")
    theme_title: str = Field(..., min_length=3, description="Descriptive title of the friction theme")
    review_ids: List[str] = Field(..., min_length=1, description="Child review IDs for 100% data lineage")
    review_count: int = Field(..., ge=1, description="Number of constituent reviews in this cluster")
    is_top_three: bool = Field(default=False, description="Flag indicating if this theme is in top 3 by volume/severity")
    is_fee_confusion: bool = Field(default=False, description="Flag indicating if this theme represents fee/charge confusion")
    summary: str = Field(default="", description="Brief synthesis of user complaints in this cluster")

    @model_validator(mode="after")
    def sync_review_count(self) -> "ThemeCluster":
        if self.review_count != len(self.review_ids):
            self.review_count = len(self.review_ids)
        return self


class WeeklyPulse(BaseModel):
    """Executive weekly intelligence report constrained to <= 250 words, quotes, and 3 action ideas."""

    pulse_id: str = Field(..., description="Unique pulse identifier, e.g. pulse_2026_w47")
    week_identifier: str = Field(..., description="ISO week format, e.g. 2026-W47")
    pulse_text: str = Field(..., min_length=10, description="Executive synthesis text")
    word_count: int = Field(..., ge=1, le=250, description="Word count (strict <= 250 constraint)")
    supporting_quotes: List[str] = Field(
        ..., min_length=1, description="Verbatim quotes with Review #ID citations"
    )
    action_ideas: List[str] = Field(
        ..., description="Concrete product action recommendations (strictly 3 ideas required)"
    )
    top_theme_ids: List[str] = Field(default_factory=list, description="IDs of top themes summarized")
    fee_confusion_theme_id: Optional[str] = Field(default=None, description="Dominant fee confusion theme ID")
    approval_status: str = Field(
        default="PENDING_APPROVAL",
        description="Approval state: PENDING_APPROVAL, APPROVED, EDITED, REJECTED",
    )
    approved_at: Optional[datetime] = Field(default=None, description="Timestamp of human approval")
    approved_by: Optional[str] = Field(default=None, description="Identifier of the approving Product Manager")

    @field_validator("pulse_text")
    @classmethod
    def validate_pulse_word_cap(cls, v: str) -> str:
        words = v.split()
        if len(words) > 250:
            raise ValueError(
                f"WeeklyPulse pulse_text exceeds hard cap of 250 words: currently {len(words)} words."
            )
        return v

    @field_validator("action_ideas")
    @classmethod
    def validate_action_ideas_count(cls, v: List[str]) -> List[str]:
        if len(v) != 3:
            raise ValueError(
                f"WeeklyPulse requires exactly three (3) concrete action ideas. Received {len(v)}."
            )
        return v

    @model_validator(mode="after")
    def sync_word_count(self) -> "WeeklyPulse":
        self.word_count = len(self.pulse_text.split())
        return self
