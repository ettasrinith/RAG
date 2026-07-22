from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PaperSearchRequest(BaseModel):
    q: str = Field(..., min_length=0, max_length=500)
    collections: list[str] = Field(default_factory=lambda: ["*"])
    page_size: int = Field(default=20, ge=1, le=100)
    page_token: str | None = None
    filter: str | None = None
    advanced: bool = False
    title: str | None = None
    author: str | None = None
    abstract: str | None = None


class PaperResult(BaseModel):
    id: str
    document_id: str
    title: str
    authors: str = ""
    abstract: str = ""
    tldr: str = ""
    venue: str = ""
    year: int | None = None
    citation_count: int = 0
    doi: str = ""
    url: str = ""
    score: float | None = None
    has_pdf: bool = False


class PaperDetail(BaseModel):
    id: str
    document_id: str
    title: str = ""
    authors: str = ""
    abstract: str = ""
    tldr: str = ""
    venue: str = ""
    year: int | None = None
    citation_count: int = 0
    doi: str = ""
    url: str = ""
    related_papers: list[PaperResult] = []
    prior_work: list[PaperResult] = []
    derivative_work: list[PaperResult] = []


class PaperSearchResponse(BaseModel):
    results: list[PaperResult]
    total: int
    next_page_token: str | None = None
