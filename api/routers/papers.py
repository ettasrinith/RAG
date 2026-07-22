from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.deps import get_session, get_store
from api.schemas.papers import PaperSearchRequest, PaperSearchResponse, PaperDetail
from core.vector_store import VectorStore as LanceStore
from api.errors import not_found
from services.paper_service import PaperService

router = APIRouter(prefix="/v1/papers", tags=["papers"])


@router.post(":search")
def search_papers(
    req: PaperSearchRequest,
    session: Session = Depends(get_session),
    store: LanceStore = Depends(get_store),
):
    svc = PaperService(session, store)
    return svc.search(req)


@router.get("/{paper_id}")
def get_paper(
    paper_id: str,
    session: Session = Depends(get_session),
    store: LanceStore = Depends(get_store),
):
    svc = PaperService(session, store)
    return svc.get_detail(paper_id)
