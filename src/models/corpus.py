"""Corpus models for Milestone 1 public documentation and search results."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator, HttpUrl
from urllib.parse import urlparse


class CorpusDocument(BaseModel):
    """Authoritative Milestone 1 public platform document."""

    doc_id: str = Field(..., description="Unique immutable document identifier")
    title: str = Field(..., min_length=3, description="Document title")
    source_url: str = Field(..., description="Official whitelisted source URL")
    category: str = Field(..., description="Classification category (e.g., BROKERAGE, DP_CHARGES)")
    content: str = Field(..., min_length=10, description="Full markdown or plain text content")
    last_updated: datetime = Field(..., description="Timestamp of document freshness")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary immutable metadata")

    @field_validator("source_url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(f"Invalid source_url: {v}. Must be a valid HTTP/HTTPS URL.")
        return v


class CorpusChunk(BaseModel):
    """Segmented passage derived from a CorpusDocument for indexing and retrieval."""

    chunk_id: str = Field(..., description="Unique chunk identifier, e.g. doc_id#chunk_0")
    doc_id: str = Field(..., description="Parent document identifier")
    content: str = Field(..., min_length=5, description="Chunk text content")
    source_url: str = Field(..., description="Inherited authoritative source URL")
    chunk_index: int = Field(ge=0, description="0-indexed position within parent document")
    token_count: int = Field(ge=1, description="Word/token count of the chunk")
    embedding: Optional[List[float]] = Field(default=None, description="Dense vector embedding")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional context metadata")


class SearchResult(BaseModel):
    """Retrieved search result chunk with relevance scores and grounding metadata."""

    chunk_id: str = Field(..., description="Retrieved chunk identifier")
    doc_id: str = Field(..., description="Parent document identifier")
    content: str = Field(..., description="Chunk content text")
    source_url: str = Field(..., description="Authoritative grounding source URL")
    score: float = Field(..., description="Hybrid relevance score combining BM25 and dense similarity")
    bm25_score: float = Field(default=0.0, description="Lexical BM25 component score")
    dense_score: float = Field(default=0.0, description="Semantic dense cosine similarity component score")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Chunk metadata")
