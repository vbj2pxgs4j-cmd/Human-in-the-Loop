"""Canonical Fee Explainer schema with strict constraints."""

from datetime import datetime
from typing import List, Optional
from urllib.parse import urlparse
from pydantic import BaseModel, Field, field_validator, model_validator


class CanonicalExplainer(BaseModel):
    """Product-approved canonical fee explainer reused across the platform."""

    explainer_id: str = Field(..., description="Unique explainer identifier, e.g. expl_dp_charges")
    topic_slug: str = Field(..., min_length=3, description="URL-safe topic identifier, e.g. dp-charges")
    title: str = Field(..., min_length=5, description="Clear explanatory title")
    bullet_points: List[str] = Field(
        ..., description="Bulleted explanation items (strict <= 6 bullets)"
    )
    bullet_count: int = Field(default=0, ge=0, le=6, description="Count of bullet points")
    source_urls: List[str] = Field(
        ..., description="Authoritative official source links (strictly >= 2 links required)"
    )
    last_checked_date: datetime = Field(
        ..., description="ISO-8601 timestamp of last regulatory / documentation verification"
    )
    status: str = Field(
        default="DRAFT", description="Status lifecycle: DRAFT, APPROVED, ARCHIVED"
    )
    approved_at: Optional[datetime] = Field(default=None, description="Timestamp when approved by Product")
    approved_by: Optional[str] = Field(default=None, description="Product Manager operator identifier")
    embedding: Optional[List[float]] = Field(default=None, description="Dense embedding vector for fast lookup")

    @field_validator("bullet_points")
    @classmethod
    def validate_bullet_cap(cls, v: List[str]) -> List[str]:
        if len(v) > 6:
            raise ValueError(
                f"CanonicalExplainer exceeds hard cap of 6 bullets: currently {len(v)} bullets."
            )
        if len(v) == 0:
            raise ValueError("CanonicalExplainer must contain at least 1 bullet point.")
        return v

    @field_validator("source_urls")
    @classmethod
    def validate_source_urls(cls, v: List[str]) -> List[str]:
        unique_urls = set(v)
        if len(unique_urls) < 2:
            raise ValueError(
                f"CanonicalExplainer requires at least two (2) distinct official source links. Received {len(unique_urls)}."
            )
        for url in v:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise ValueError(f"Invalid source_url: {url}. Must be a valid HTTP/HTTPS URL.")
        return v

    @model_validator(mode="after")
    def sync_bullet_count(self) -> "CanonicalExplainer":
        self.bullet_count = len(self.bullet_points)
        if self.bullet_count > 6:
            raise ValueError(
                f"CanonicalExplainer bullet count exceeds hard cap of 6 bullets: {self.bullet_count}"
            )
        return self
