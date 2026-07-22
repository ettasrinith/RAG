from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from api.filters import FilterParser
from api.pagination import decode_page_token, encode_page_token
from core.config import load_config
from core.embedder import embed_query
from core.registry.models import CollectionModel
from core.search.fusion import rrf_fuse
from core.search.highlight import extract_highlights
from core.search.reranker import rerank
from core.vector_store import VectorStore


class SearchService:
    def __init__(self, session: Session, store: VectorStore):
        self.session = session
        self.store = store
        self.config = load_config()

    def search(
        self,
        query: str,
        collections: list[str] | None = None,
        page_size: int = 20,
        page_token: str | None = None,
        filter_expr: str | None = None,
        sort: str | None = None,
    ) -> dict[str, Any]:
        last_score, offset, _ = decode_page_token(page_token) if page_token else (0.0, 0, None)

        if not query:
            return {"results": [], "total": 0, "facets": {}, "next_page_token": None}

        collection_ids = self._resolve_collections(collections or ["*"])

        qvec = embed_query(query, model_name=self.config["embedding"]["model"])
        k = (offset + page_size) * 3

        vector_hits = self.store.search(qvec, k=max(k * 2, 20))
        fts_hits = self.store.fts_search(query, k=max(k * 2, 20))

        if collection_ids != ["*"]:
            vector_hits = [h for h in vector_hits if h.get("collection_id") in collection_ids]
            fts_hits = [h for h in fts_hits if h.get("collection_id") in collection_ids]

        fused = rrf_fuse(vector_hits, fts_hits, top_n=k)

        if filter_expr:
            try:
                parser = FilterParser(filter_expr)
                conditions = parser.parse()
                for cond in conditions:
                    fused = [r for r in fused if self._matches_filter(r, cond)]
            except Exception:
                pass

        do_rerank = self.config.get("search", {}).get("rerank", False)
        if do_rerank and query:
            fused = rerank(query, fused, top_k=k)

        total = len(fused)
        page = fused[offset:offset + page_size]
        next_token = None
        if offset + page_size < total:
            last = page[-1].get("combined_score", 0.0) if page else 0.0
            next_token = encode_page_token(last, offset + page_size)

        facets = self._build_facets(fused)

        results = [self._to_result(r, query) for r in page]

        return {
            "results": results,
            "total": total,
            "facets": facets,
            "next_page_token": next_token,
        }

    def _resolve_collections(self, collections: list[str]) -> list[str]:
        if "*" in collections:
            return ["*"]
        return collections

    def _matches_filter(self, row: dict, condition) -> bool:
        field_map = {
            "source_type": "source",
            "source": "source",
            "year": "year",
            "venue": "venue",
            "repo": "repo",
        }
        col = field_map.get(condition.field)
        if not col:
            return True
        val = row.get(col)
        if val is None:
            return condition.op == "!="
        if condition.op == "=":
            return str(val) == str(condition.value)
        elif condition.op == "!=":
            return str(val) != str(condition.value)
        elif condition.op == ">=":
            try:
                return float(val) >= float(condition.value)
            except (ValueError, TypeError):
                return False
        elif condition.op == "<=":
            try:
                return float(val) <= float(condition.value)
            except (ValueError, TypeError):
                return False
        return True

    def _build_facets(self, results: list[dict]) -> dict[str, list[dict]]:
        source_types: dict[str, int] = {}
        repos: dict[str, int] = {}
        years: dict[str, int] = {}
        for r in results:
            st = r.get("source", "unknown")
            source_types[st] = source_types.get(st, 0) + 1
            rp = r.get("repo", "")
            if rp:
                repos[rp] = repos.get(rp, 0) + 1
            yr = r.get("year")
            if yr:
                key = str(yr)
                years[key] = years.get(key, 0) + 1

        facets = {}
        if source_types:
            facets["source_type"] = [
                {"value": k, "count": v}
                for k, v in sorted(source_types.items(), key=lambda x: -x[1])
            ]
        if repos:
            facets["repo"] = [
                {"value": k, "count": v}
                for k, v in sorted(repos.items(), key=lambda x: -x[1])
            ]
        if years:
            facets["year"] = [
                {"value": k, "count": v}
                for k, v in sorted(years.items(), key=lambda x: -x[1])
            ]
        return facets

    def _to_result(self, r: dict, query: str) -> dict:
        text = r.get("text", "")
        highlights = extract_highlights(text, query)
        snippet = text[:300] if not highlights else text[max(0, highlights[0]["char_start"] - 80):max(0, highlights[0]["char_start"] - 80) + 300]

        return {
            "id": r.get("id", ""),
            "title": r.get("title", ""),
            "source_type": r.get("source", ""),
            "uri": r.get("url", ""),
            "authors": r.get("author", ""),
            "tldr": r.get("summary", ""),
            "snippet": snippet,
            "score": r.get("combined_score", 0.0),
            "score_breakdown": r.get("score_breakdown"),
            "highlights": highlights,
            "collection_id": r.get("collection_id", ""),
            "collection_name": r.get("collection_name", ""),
        }
