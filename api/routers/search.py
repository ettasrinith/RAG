from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from api.auth import verify_api_key
from api.deps import get_session, get_store
from core.vector_store import VectorStore
from services.search_service import SearchService
from sqlalchemy.orm import Session

router = APIRouter(prefix="/v1/documents", tags=["search"])


class SearchRequest(BaseModel):
    q: str = Field(default="", max_length=500)
    collections: list[str] = Field(default_factory=lambda: ["*"])
    page_size: int = Field(default=20, ge=1, le=100)
    page_token: str | None = None
    filter: str | None = None
    sort: str | None = Field(default=None, pattern=r"^(score|date|title)(:asc|:desc)?$")


class FacetValue(BaseModel):
    value: str
    count: int


class FacetGroup(BaseModel):
    field: str
    values: list[FacetValue]


class SearchResultItem(BaseModel):
    id: str
    title: str
    source_type: str
    uri: str | None = None
    authors: str | None = None
    tldr: str = ""
    snippet: str
    score: float
    score_breakdown: dict | None = None
    highlights: list[dict] | None = None
    collection_id: str = ""
    collection_name: str = ""


class SearchResponse(BaseModel):
    results: list[SearchResultItem]
    total: int
    facets: dict[str, list[FacetValue]] | None = None
    next_page_token: str | None = None


@router.post(":search", response_model=SearchResponse)
def search_documents(
    req: SearchRequest,
    session: Session = Depends(get_session),
    store: VectorStore = Depends(get_store),
    _auth: None = Depends(verify_api_key),
):
    svc = SearchService(session, store)
    result = svc.search(
        query=req.q,
        collections=req.collections,
        page_size=req.page_size,
        page_token=req.page_token,
        filter_expr=req.filter,
        sort=req.sort,
    )
    return SearchResponse(**result)
