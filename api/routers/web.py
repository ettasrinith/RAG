from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.auth import verify_api_key
from api.deps import get_llm
from core.llm import LLMClient
from services.web_search_service import WebSearchService

router = APIRouter(prefix="/v1/web", tags=["web"])


class WebSearchRequest(BaseModel):
    q: str = Field(..., min_length=1, max_length=500)
    sources: list[str] = Field(default_factory=lambda: ["arxiv", "semantic_scholar"])
    limit: int = Field(default=10, ge=1, le=50)


class WebSearchResult(BaseModel):
    id: str
    title: str
    authors: str
    year: int | None = None
    venue: str
    abstract: str
    citation_count: int = 0
    url: str
    source: str
    has_pdf: bool = False
    pdf_url: str | None = None


class WebSearchResponse(BaseModel):
    results: list[WebSearchResult]
    total: int


@router.post(":search")
def web_search(
    req: WebSearchRequest,
    _auth: None = Depends(verify_api_key),
):
    svc = WebSearchService()
    papers = svc.discover(req.q, sources=req.sources, limit=req.limit)
    return WebSearchResponse(
        results=[WebSearchResult(**p) for p in papers],
        total=len(papers),
    )
