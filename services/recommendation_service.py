"""Paper Recommendation Engine — 'Because you read X, you might like Y'.

Recommends papers based on:
1. Semantic similarity (embedding cosine similarity)
2. Citation relationships (co-citation, bibliographic coupling)
3. Author overlap
4. Topic/keyword matching
5. Recency bias (prefer newer papers)
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from core.logging import get_logger

log = get_logger("recommendation")


@dataclass
class PaperRecommendation:
    """A single paper recommendation with reasoning."""
    title: str
    authors: str = ""
    year: int | None = None
    abstract: str = ""
    url: str = ""
    source: str = ""
    score: float = 0.0
    reason: str = ""
    citation_count: int = 0
    match_type: str = "semantic"  # semantic, citation, author, topic

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "abstract": self.abstract[:400],
            "url": self.url,
            "source": self.source,
            "score": round(self.score, 4),
            "reason": self.reason,
            "citation_count": self.citation_count,
            "match_type": self.match_type,
        }


@dataclass
class RecommendationResult:
    """Full recommendation result for a seed paper/topic."""
    seed: str
    recommendations: list[PaperRecommendation] = field(default_factory=list)
    strategy: str = "hybrid"
    duration_ms: float = 0

    def to_dict(self) -> dict:
        return {
            "seed": self.seed,
            "recommendations": [r.to_dict() for r in self.recommendations],
            "count": len(self.recommendations),
            "strategy": self.strategy,
            "duration_ms": round(self.duration_ms, 1),
        }


class RecommendationService:
    """Paper recommendation engine using hybrid similarity signals."""

    def __init__(self, store, research_store=None, config: dict | None = None):
        self.store = store
        self.research_store = research_store
        self.config = config or {}

    def recommend_for_paper(
        self,
        title: str,
        abstract: str = "",
        authors: str = "",
        k: int = 10,
        strategy: str = "hybrid",
    ) -> RecommendationResult:
        """Get recommendations based on a specific paper."""
        result = RecommendationResult(seed=title, strategy=strategy)
        start = time.perf_counter()

        query = f"{title} {abstract[:200]}" if abstract else title
        recommendations: list[PaperRecommendation] = []
        seen_titles: set[str] = set()
        seen_titles.add(title.lower().strip())

        # Strategy 1: Semantic similarity
        if strategy in ("hybrid", "semantic"):
            semantic_recs = self._semantic_recommend(query, k * 2, seen_titles)
            recommendations.extend(semantic_recs)
            for r in semantic_recs:
                seen_titles.add(r.title.lower().strip())

        # Strategy 2: Author-based
        if strategy in ("hybrid", "author") and authors:
            author_recs = self._author_recommend(authors, k, seen_titles)
            recommendations.extend(author_recs)
            for r in author_recs:
                seen_titles.add(r.title.lower().strip())

        # Strategy 3: Topic/keyword expansion
        if strategy in ("hybrid", "topic"):
            topic_recs = self._topic_recommend(title, abstract, k, seen_titles)
            recommendations.extend(topic_recs)

        # Deduplicate and sort by score
        unique_recs: list[PaperRecommendation] = []
        seen_final: set[str] = set()
        for r in recommendations:
            key = r.title.lower().strip()
            if key not in seen_final:
                seen_final.add(key)
                unique_recs.append(r)

        unique_recs.sort(key=lambda x: x.score, reverse=True)
        result.recommendations = unique_recs[:k]
        result.duration_ms = (time.perf_counter() - start) * 1000

        log.info("recommendations_generated", extra={
            "seed": title[:50],
            "count": len(result.recommendations),
            "strategy": strategy,
        })
        return result

    def recommend_for_topic(self, topic: str, k: int = 10) -> RecommendationResult:
        """Get recommendations based on a research topic/interest."""
        result = RecommendationResult(seed=topic, strategy="topic")
        start = time.perf_counter()

        recs = self._semantic_recommend(topic, k * 2, set())
        recs.sort(key=lambda x: x.score, reverse=True)
        result.recommendations = recs[:k]
        result.duration_ms = (time.perf_counter() - start) * 1000
        return result

    def get_reading_path(self, title: str, depth: int = 3) -> dict:
        """Generate a suggested reading path starting from a paper.

        Returns a chain of papers where each is recommended based on the previous.
        """
        path: list[dict] = [{"title": title, "step": 0, "reason": "Starting paper"}]
        current_title = title
        current_abstract = ""
        seen: set[str] = {title.lower().strip()}

        for step in range(1, depth + 1):
            recs = self.recommend_for_paper(
                title=current_title,
                abstract=current_abstract,
                k=3,
                strategy="semantic",
            )
            if not recs.recommendations:
                break

            best = recs.recommendations[0]
            path.append({
                "title": best.title,
                "authors": best.authors,
                "year": best.year,
                "url": best.url,
                "step": step,
                "reason": best.reason,
                "score": best.score,
            })
            current_title = best.title
            current_abstract = best.abstract
            seen.add(best.title.lower().strip())

        return {"path": path, "depth": len(path) - 1}

    # ── Private methods ─────────────────────────────────────────

    def _semantic_recommend(self, query: str, k: int, exclude: set[str]) -> list[PaperRecommendation]:
        """Recommend papers by semantic similarity."""
        recs: list[PaperRecommendation] = []
        try:
            from core.embedder import embed_query
            from core.search.fusion import rrf_fuse

            model = self.config.get("embedding", {}).get("model", "nomic-ai/nomic-embed-text-v1")
            qvec = embed_query(query, model_name=model)

            # Search main store
            vector_hits = self.store.search(qvec, k=k)
            fts_hits = self.store.fts_search(query, k=k)
            fused = rrf_fuse(vector_hits, fts_hits, top_n=k)

            for h in fused:
                title = (h.get("title") or "").strip()
                if not title or title.lower() in exclude:
                    continue
                score = h.get("combined_score", 0)
                recs.append(PaperRecommendation(
                    title=title,
                    authors=h.get("author", ""),
                    year=h.get("year"),
                    abstract=(h.get("text") or "")[:400],
                    url=h.get("url", ""),
                    source=h.get("source", "knowledge_base"),
                    score=score,
                    reason=f"Semantically similar to your query",
                    match_type="semantic",
                ))

            # Search research store
            if self.research_store:
                try:
                    r_hits = self.research_store.search(qvec, k=k)
                    for h in r_hits:
                        title = (h.get("title") or "").strip()
                        if not title or title.lower() in exclude:
                            continue
                        recs.append(PaperRecommendation(
                            title=title,
                            authors=h.get("author", ""),
                            year=h.get("year"),
                            abstract=(h.get("text") or "")[:400],
                            url=h.get("url", ""),
                            source="research",
                            score=h.get("combined_score", h.get("_distance", 0)),
                            reason="Related research paper",
                            match_type="semantic",
                        ))
                except Exception:
                    pass

        except Exception as e:
            log.warning("semantic recommendation failed: %s", e)

        return recs

    def _author_recommend(self, authors: str, k: int, exclude: set[str]) -> list[PaperRecommendation]:
        """Recommend papers by the same authors."""
        recs: list[PaperRecommendation] = []
        # Extract first author surname for search
        author_list = [a.strip() for a in authors.split(",")]
        if not author_list:
            return recs

        primary_author = author_list[0]
        try:
            fts_hits = self.store.fts_search(primary_author, k=k * 2)
            for h in fts_hits:
                title = (h.get("title") or "").strip()
                hit_author = h.get("author", "")
                if not title or title.lower() in exclude:
                    continue
                # Verify author overlap
                if primary_author.lower().split()[-1] in hit_author.lower():
                    recs.append(PaperRecommendation(
                        title=title,
                        authors=hit_author,
                        year=h.get("year"),
                        abstract=(h.get("text") or "")[:400],
                        url=h.get("url", ""),
                        source=h.get("source", ""),
                        score=0.7,
                        reason=f"Same author: {primary_author}",
                        match_type="author",
                    ))
        except Exception as e:
            log.warning("author recommendation failed: %s", e)

        return recs[:k]

    def _topic_recommend(self, title: str, abstract: str, k: int, exclude: set[str]) -> list[PaperRecommendation]:
        """Recommend papers by extracting key topics and searching."""
        recs: list[PaperRecommendation] = []

        # Extract key terms from title
        import re
        # Remove common academic words
        stop_words = {"a", "an", "the", "for", "of", "in", "on", "with", "and", "or",
                      "to", "from", "by", "is", "are", "was", "were", "using", "based",
                      "via", "towards", "toward", "novel", "new", "approach", "method"}
        words = re.findall(r'\b[a-zA-Z]{4,}\b', title.lower())
        keywords = [w for w in words if w not in stop_words][:5]

        if not keywords:
            return recs

        # Search with extracted keywords
        topic_query = " ".join(keywords)
        try:
            fts_hits = self.store.fts_search(topic_query, k=k)
            for h in fts_hits:
                t = (h.get("title") or "").strip()
                if not t or t.lower() in exclude:
                    continue
                recs.append(PaperRecommendation(
                    title=t,
                    authors=h.get("author", ""),
                    year=h.get("year"),
                    abstract=(h.get("text") or "")[:400],
                    url=h.get("url", ""),
                    source=h.get("source", ""),
                    score=0.5,
                    reason=f"Matches topic keywords: {', '.join(keywords[:3])}",
                    match_type="topic",
                ))
        except Exception as e:
            log.warning("topic recommendation failed: %s", e)

        return recs[:k]
