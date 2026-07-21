from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class DocumentSearchRequest(BaseModel):
    q: str = Field(..., min_length=0, max_length=500)
    collections: list[str] = Field(default_factory=lambda: ["*"])
    page_size: int = Field(default=20, ge=1, le=100)
    page_token: str | None = None
    filter: str | None = None
    sort: str | None = None


class DocumentSearchResult(BaseModel):
    id: str
    title: str
    source_type: str
    uri: str
    authors: str
    tldr: str
    snippet: str
    score: float
    score_breakdown: dict[str, float] | None = None
    highlights: list[dict[str, int]] | None = None
    collection_id: str
    collection_name: str


class FacetCount(BaseModel):
    value: str
    count: int


class DocumentSearchResponse(BaseModel):
    results: list[DocumentSearchResult]
    total: int
    facets: dict[str, list[FacetCount]] | None = None
    next_page_token: str | None = None


class IngestRequest(BaseModel):
    source: str = Field(..., pattern=r"^(upload|github|website|arxiv|notes|folder)$")
    source_config: dict[str, Any] = Field(default_factory=dict)
    collection_id: str | None = None
    collection_name: str | None = None
    chunk_size: int | None = None
    chunk_overlap: int | None = None
    embedding_model: str | None = None
    contextual_summaries: bool = False


class IngestResponse(BaseModel):
    job_id: str
    collection_id: str
    status: str = "accepted"


class UploadResponse(BaseModel):
    job_id: str
    collection_id: str
    collection_name: str
    file_count: int
    status: str = "accepted"


class GitHubLookupRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=500)


class GitHubLookupResponse(BaseModel):
    owner: str
    repo: str
    full_name: str | None = None
    description: str | None = None
    stars: int | None = None
    default_branch: str | None = None
    error: str | None = None
