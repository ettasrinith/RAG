from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from api.schemas.documents import DocumentSearchRequest, DocumentSearchResponse, DocumentSearchResult, FacetCount
from core.config import load_config
from core.embedder import embed_query
from core.registry.models import CollectionModel, DocumentModel
from core.search.fusion import rrf_fuse
from core.search.reranker import rerank
from core.vector_store import VectorStore


class DocumentService:
    def __init__(self, session: Session, store: VectorStore):
        self.session = session
        self.store = store
        self.config = load_config()

    def search(self, req: DocumentSearchRequest) -> DocumentSearchResponse:
        query = req.q
        collections = req.collections
        page_size = req.page_size

        if not query:
            return DocumentSearchResponse(results=[], total=0, facets={})

        collection_ids = self._resolve_collections(collections)
        qvec = embed_query(query, model_name=self.config["embedding"]["model"])

        k = page_size * 3
        vector_hits = self.store.search(qvec, k=max(k * 2, 20))
        fts_hits = self.store.fts_search(query, k=max(k * 2, 20))

        if collection_ids != ["*"]:
            vector_hits = [h for h in vector_hits if h.get("collection_id") in collection_ids]
            fts_hits = [h for h in fts_hits if h.get("collection_id") in collection_ids]

        fused = rrf_fuse(vector_hits, fts_hits, top_n=k)

        do_rerank = self.config.get("search", {}).get("rerank", False)
        if do_rerank and query:
            fused = rerank(query, fused, top_k=page_size)

        results = fused[:page_size]
        total = len(fused)

        facets = self._build_facets(fused)

        return DocumentSearchResponse(
            results=[self._to_result(r) for r in results],
            total=total,
            facets=facets,
        )

    def _resolve_collections(self, collections: list[str]) -> list[str]:
        if "*" in collections:
            return ["*"]
        return collections

    def _build_facets(self, results: list[dict]) -> dict[str, list[FacetCount]]:
        source_types: dict[str, int] = {}
        for r in results:
            st = r.get("source", "unknown")
            source_types[st] = source_types.get(st, 0) + 1
        return {
            "source_type": [
                FacetCount(value=k, count=v) for k, v in sorted(source_types.items(), key=lambda x: -x[1])
            ],
        }

    def _to_result(self, r: dict) -> DocumentSearchResult:
        return DocumentSearchResult(
            id=r.get("id", ""),
            title=r.get("title", ""),
            source_type=r.get("source", ""),
            uri=r.get("url", ""),
            authors=r.get("author", ""),
            tldr=r.get("summary", ""),
            snippet=(r.get("text") or "")[:300],
            score=r.get("combined_score", 0.0),
            score_breakdown=r.get("score_breakdown"),
            collection_id=r.get("collection_id", ""),
            collection_name=r.get("collection_name", ""),
        )
