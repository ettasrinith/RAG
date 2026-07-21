"""Pydantic models for the research pipeline."""
from __future__ import annotations

from pydantic import BaseModel, Field


class PaperCard(BaseModel):
    """Ephemeral paper card returned by /research/discover.

    Not stored in the DB until the user selects it for indexing.
    """
    paper_id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    abstract: str = ""
    year: int | None = None
    venue: str = ""
    citation_count: int | None = None
    doi: str = ""
    arxiv_id: str = ""
    pdf_url: str = ""
    abs_url: str = ""
    source: str = ""  # arxiv / semantic_scholar / openalex
    already_indexed: bool = False


class DiscoverRequest(BaseModel):
    q: str = Field(..., min_length=1, max_length=500)
    sources: list[str] = Field(default_factory=lambda: ["arxiv", "semantic_scholar", "openalex"])
    limit_per_source: int = Field(default=30, ge=1, le=100)
    year_from: int | None = None
    year_to: int | None = None


class DiscoverResponse(BaseModel):
    papers: list[PaperCard]
    total_found: int
    already_indexed: int
    sources_queried: list[str]


class ResearchIndexRequest(BaseModel):
    papers: list[PaperCard] = Field(..., min_length=1)
    collection: str = Field(default="default", max_length=100)


class ResearchSearchRequest(BaseModel):
    q: str = Field(..., min_length=1, max_length=500)
    k: int = Field(default=10, ge=1, le=100)
    collection: str | None = None
    year_from: int | None = None
    year_to: int | None = None
    hybrid: bool = True


class ResearchDeleteRequest(BaseModel):
    paper_ids: list[str] = Field(..., min_length=1)


class ResearchCollectionRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class ChatScopeRequest(BaseModel):
    q: str = Field(..., min_length=1, max_length=2000)
    k: int = Field(default=8, ge=1, le=50)
    scope: str | None = Field(default=None, pattern="^(main|research)$")
    source: str | None = None
    repo: str | None = None
