from __future__ import annotations

from sqlalchemy.orm import Session

from api.schemas.papers import PaperSearchRequest, PaperSearchResponse, PaperResult, PaperDetail
from core.config import load_config
from core.embedder import embed_query
from core.registry.models import PaperModel, DocumentModel, CollectionModel
from core.search.fusion import rrf_fuse
from core.search.reranker import rerank
from core.vector_store import VectorStore
from api.errors import not_found


class PaperService:
    def __init__(self, session: Session, store: VectorStore):
        self.session = session
        self.store = store
        self.config = load_config()

    def search(self, req: PaperSearchRequest) -> PaperSearchResponse:
        config = self.config
        if not req.q and not req.title and not req.author:
            return PaperSearchResponse(results=[], total=0)

        query = req.q or req.title or req.author or ""
        qvec = embed_query(query, model_name=config["embedding"]["model"])
        k = req.page_size * 3

        vector_hits = self.store.search(qvec, k=max(k * 2, 20))
        fts_hits = self.store.fts_search(query, k=max(k * 2, 20))

        if req.advanced and req.title:
            fts_title = self.store.fts_search(req.title, k=max(k * 2, 20))
            fts_hits = fts_hits + [h for h in fts_title if h not in fts_hits]

        if req.advanced and req.author:
            vector_hits = [h for h in vector_hits if req.author.lower() in (h.get("author", "") or "").lower()]
            fts_hits = [h for h in fts_hits if req.author.lower() in (h.get("author", "") or "").lower()]

        fused = rrf_fuse(vector_hits, fts_hits, top_n=k)

        do_rerank = config.get("search", {}).get("rerank", False)
        if do_rerank and query:
            fused = rerank(query, fused, top_k=req.page_size)

        results = []
        for h in fused[:req.page_size]:
            doc_id = h.get("doc_id", "")
            paper = None
            if doc_id:
                paper = self.session.query(PaperModel).filter(PaperModel.document_id == doc_id).first()

            results.append(PaperResult(
                id=paper.id if paper else (h.get("id") or ""),
                document_id=doc_id,
                title=h.get("title") or "",
                authors=h.get("author") or "",
                abstract=(h.get("text") or "")[:500],
                tldr=h.get("summary") or "",
                venue=h.get("venue") or "",
                year=h.get("year"),
                citation_count=h.get("citation_count") or 0,
                doi=h.get("doi") or "",
                url=h.get("url") or "",
                score=h.get("combined_score") or 0.0,
                has_pdf=bool(h.get("has_pdf", False)),
            ))

        return PaperSearchResponse(results=results, total=len(fused))

    def get_detail(self, paper_id: str) -> PaperDetail:
        paper = self.session.query(PaperModel).filter(PaperModel.id == paper_id).first()
        if not paper:
            raise not_found("Paper", paper_id)

        doc = self.session.query(DocumentModel).filter(DocumentModel.id == paper.document_id).first()

        related = self._find_related(paper, doc)

        return PaperDetail(
            id=paper.id,
            document_id=paper.document_id,
            title=doc.title if doc else "",
            authors=doc.authors if doc else "",
            abstract=paper.abstract or "",
            tldr=doc.tldr if doc else "",
            venue=paper.venue or "",
            year=paper.year,
            citation_count=paper.citation_count or 0,
            doi=paper.doi or "",
            url=doc.uri if doc else "",
            related_papers=related,
            prior_work=[],
            derivative_work=[],
        )

    def _find_related(self, paper: PaperModel, doc: DocumentModel | None, top_k: int = 5) -> list[PaperResult]:
        if not doc:
            return []
        related_ids = paper.related_paper_ids or []
        results = []
        for rid in related_ids[:top_k]:
            rel_paper = self.session.query(PaperModel).filter(PaperModel.id == rid).first()
            if rel_paper:
                rel_doc = self.session.query(DocumentModel).filter(DocumentModel.id == rel_paper.document_id).first()
                results.append(PaperResult(
                    id=rel_paper.id,
                    document_id=rel_paper.document_id,
                    title=rel_doc.title if rel_doc else "",
                    authors=rel_doc.authors if rel_doc else "",
                    abstract=(rel_paper.abstract or "")[:300],
                    tldr=rel_doc.tldr if rel_doc else "",
                    venue=rel_paper.venue or "",
                    year=rel_paper.year,
                    citation_count=rel_paper.citation_count or 0,
                    doi=rel_paper.doi or "",
                    url=rel_doc.uri if rel_doc else "",
                    has_pdf=False,
                ))
        return results
