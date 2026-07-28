"""Literature Review Generator — Automated related work section synthesis.

Given a topic, searches indexed papers and external sources, then generates
a structured literature review / related work section with proper citations.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Iterator

from core.logging import get_logger

log = get_logger("literature_review")

REVIEW_SYSTEM_PROMPT = """You are an expert academic writer specializing in literature reviews.
Write in a formal academic style. Always cite sources using [1], [2], etc.
Structure the review thematically, not just paper-by-paper.
Identify trends, gaps, and connections between works."""

REVIEW_PROMPT = """Write a comprehensive literature review / related work section on the topic:

## Topic
{topic}

## Available Papers (cite as [1], [2], etc.)
{papers}

## Requirements
{requirements}

## Output Format
Write a well-structured literature review with:
1. An introductory paragraph framing the research area
2. Thematic subsections (use ### headers) grouping related works
3. Critical analysis — compare approaches, note strengths/limitations
4. A concluding paragraph identifying research gaps and future directions
5. A "References" section listing all cited works

Length: approximately {length} words.
"""

REQUIREMENTS_DEFAULT = """- Focus on methodology, findings, and contributions
- Compare and contrast different approaches
- Note the evolution of the field over time
- Identify consensus and disagreements
- Highlight under-explored areas"""


@dataclass
class LiteratureReviewResult:
    """Result of literature review generation."""
    topic: str
    review_text: str = ""
    papers_used: list[dict] = field(default_factory=list)
    sections: list[str] = field(default_factory=list)
    word_count: int = 0
    duration_ms: float = 0

    def to_dict(self) -> dict:
        return {
            "topic": self.topic,
            "review": self.review_text,
            "papers_used": self.papers_used,
            "sections": self.sections,
            "word_count": self.word_count,
            "duration_ms": round(self.duration_ms, 1),
        }


class LiteratureReviewService:
    """Generate structured literature reviews from indexed and external papers."""

    def __init__(self, llm_client, store, research_store=None, config: dict | None = None):
        self.llm = llm_client
        self.store = store
        self.research_store = research_store
        self.config = config or {}

    def generate(
        self,
        topic: str,
        max_papers: int = 15,
        length: str = "800-1200",
        focus: str = "",
        include_external: bool = True,
    ) -> LiteratureReviewResult:
        """Generate a literature review (non-streaming)."""
        result = LiteratureReviewResult(topic=topic)
        start = time.perf_counter()

        # Gather papers
        papers = self._gather_papers(topic, max_papers, include_external)
        result.papers_used = papers

        if not papers:
            result.review_text = f"No relevant papers found for topic: {topic}"
            result.duration_ms = (time.perf_counter() - start) * 1000
            return result

        # Generate review
        requirements = focus if focus else REQUIREMENTS_DEFAULT
        review = self._generate_review(topic, papers, requirements, length)
        result.review_text = review
        result.word_count = len(review.split())

        # Extract sections
        import re
        result.sections = re.findall(r'^###?\s+(.+)$', review, re.MULTILINE)

        result.duration_ms = (time.perf_counter() - start) * 1000
        log.info("lit_review_complete", extra={
            "topic": topic[:50],
            "papers": len(papers),
            "words": result.word_count,
            "duration_ms": round(result.duration_ms),
        })
        return result

    def stream(
        self,
        topic: str,
        max_papers: int = 15,
        length: str = "800-1200",
        focus: str = "",
        include_external: bool = True,
    ) -> Iterator[dict]:
        """Stream the literature review generation process."""
        start = time.perf_counter()

        yield {"type": "status", "stage": "gathering", "message": "Gathering relevant papers..."}

        # Gather papers
        papers = self._gather_papers(topic, max_papers, include_external)
        yield {
            "type": "papers_found",
            "papers": [{"title": p.get("title", ""), "source": p.get("source", ""), "year": p.get("year")} for p in papers],
            "count": len(papers),
        }

        if not papers:
            yield {"type": "error", "message": f"No relevant papers found for: {topic}"}
            return

        yield {"type": "status", "stage": "generating", "message": "Writing literature review..."}

        # Generate review
        requirements = focus if focus else REQUIREMENTS_DEFAULT
        review = self._generate_review(topic, papers, requirements, length)

        duration_ms = (time.perf_counter() - start) * 1000
        yield {
            "type": "review",
            "review": review,
            "papers_used": papers,
            "word_count": len(review.split()),
            "duration_ms": round(duration_ms),
        }
        yield {"type": "done", "duration_ms": round(duration_ms)}

    # ── Private methods ─────────────────────────────────────────

    def _gather_papers(self, topic: str, max_papers: int, include_external: bool) -> list[dict]:
        """Gather relevant papers from internal index and external sources."""
        papers: list[dict] = []
        seen_titles: set[str] = set()

        # Internal search
        try:
            from core.embedder import embed_query
            from core.search.fusion import rrf_fuse

            model = self.config.get("embedding", {}).get("model", "nomic-ai/nomic-embed-text-v1")
            qvec = embed_query(topic, model_name=model)
            vector_hits = self.store.search(qvec, k=max_papers * 2)
            fts_hits = self.store.fts_search(topic, k=max_papers * 2)
            fused = rrf_fuse(vector_hits, fts_hits, top_n=max_papers * 2)

            for h in fused:
                title = (h.get("title") or "").lower().strip()
                if title and title not in seen_titles:
                    seen_titles.add(title)
                    papers.append({
                        "title": h.get("title", ""),
                        "abstract": (h.get("text") or "")[:600],
                        "source": h.get("source", "knowledge_base"),
                        "url": h.get("url", ""),
                        "author": h.get("author", ""),
                        "year": h.get("year"),
                    })
        except Exception as e:
            log.warning("internal paper search failed: %s", e)

        # Research store
        if self.research_store:
            try:
                from core.embedder import embed_query
                model = self.config.get("embedding", {}).get("model", "nomic-ai/nomic-embed-text-v1")
                qvec = embed_query(topic, model_name=model)
                r_hits = self.research_store.search(qvec, k=max_papers)
                for h in r_hits:
                    title = (h.get("title") or "").lower().strip()
                    if title and title not in seen_titles:
                        seen_titles.add(title)
                        papers.append({
                            "title": h.get("title", ""),
                            "abstract": (h.get("text") or "")[:600],
                            "source": "research",
                            "url": h.get("url", ""),
                            "author": h.get("author", ""),
                            "year": h.get("year"),
                        })
            except Exception as e:
                log.warning("research store search failed: %s", e)

        # External academic search
        if include_external:
            try:
                from services.web_search_service import WebSearchService
                svc = WebSearchService()
                ext_papers = svc.discover(topic, sources=["arxiv", "semantic_scholar"], limit=max_papers)
                for p in ext_papers:
                    title = (p.get("title") or "").lower().strip()
                    if title and title not in seen_titles:
                        seen_titles.add(title)
                        papers.append({
                            "title": p.get("title", ""),
                            "abstract": (p.get("abstract") or "")[:600],
                            "source": p.get("source", "external"),
                            "url": p.get("url", ""),
                            "author": p.get("authors", ""),
                            "year": p.get("year"),
                            "citation_count": p.get("citation_count", 0),
                        })
            except Exception as e:
                log.warning("external paper search failed: %s", e)

        return papers[:max_papers]

    def _generate_review(self, topic: str, papers: list[dict], requirements: str, length: str) -> str:
        """Generate the actual review text using LLM."""
        # Format papers for prompt
        papers_text = ""
        for i, p in enumerate(papers, 1):
            title = p.get("title", "Untitled")
            abstract = p.get("abstract", "")
            author = p.get("author", "")
            year = p.get("year", "")
            source = p.get("source", "")

            papers_text += f"\n[{i}] {title}"
            if author:
                papers_text += f" — {author}"
            if year:
                papers_text += f" ({year})"
            papers_text += f" [{source}]"
            if abstract:
                papers_text += f"\n    {abstract}\n"

        prompt = REVIEW_PROMPT.format(
            topic=topic,
            papers=papers_text,
            requirements=requirements,
            length=length,
        )

        try:
            return self.llm.complete(prompt, system_prompt=REVIEW_SYSTEM_PROMPT)
        except Exception as e:
            log.warning("review generation failed: %s", e)
            return f"## Literature Review: {topic}\n\n[Generation failed: {e}]\n\n### Papers Found\n{papers_text}"
