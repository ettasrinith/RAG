"""Deep Research Service — Multi-step agentic research with synthesis.

Implements a deep research pipeline:
1. Decompose complex question into sub-queries
2. Search multiple sources (internal KB + external academic APIs)
3. Cross-reference and deduplicate findings
4. Synthesize a comprehensive cited report
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Iterator

from core.logging import get_logger

log = get_logger("deep_research")

DECOMPOSE_PROMPT = """You are a research assistant. Break down this complex research question into 3-5 focused sub-queries that would help gather comprehensive information.

Question: {question}

Return a JSON array of sub-queries, e.g.:
["sub-query 1", "sub-query 2", "sub-query 3"]

Return ONLY the JSON array, nothing else."""

SYNTHESIS_PROMPT = """You are an expert research analyst. Synthesize the following research findings into a comprehensive, well-structured report.

## Original Question
{question}

## Research Findings
{findings}

## Instructions
- Write a detailed, well-organized research report
- Use clear section headers (##)
- Cite sources using [1], [2], etc. matching the source list
- Highlight key findings, agreements, and contradictions
- Note any gaps in the available evidence
- End with a "Summary" section and "Sources" list
- Be thorough but concise — aim for quality over quantity"""


@dataclass
class ResearchStep:
    """A single step in the deep research process."""
    step_type: str  # "decompose", "search", "analyze", "synthesize"
    query: str = ""
    results: list[dict] = field(default_factory=list)
    duration_ms: float = 0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "step_type": self.step_type,
            "query": self.query,
            "result_count": len(self.results),
            "duration_ms": round(self.duration_ms, 1),
            "metadata": self.metadata,
        }


@dataclass
class DeepResearchResult:
    """Full result of a deep research session."""
    question: str
    sub_queries: list[str] = field(default_factory=list)
    steps: list[ResearchStep] = field(default_factory=list)
    report: str = ""
    sources: list[dict] = field(default_factory=list)
    total_duration_ms: float = 0
    papers_found: int = 0

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "sub_queries": self.sub_queries,
            "steps": [s.to_dict() for s in self.steps],
            "report": self.report,
            "sources": self.sources[:20],
            "total_duration_ms": round(self.total_duration_ms, 1),
            "papers_found": self.papers_found,
        }


class DeepResearchService:
    """Multi-step agentic research: decompose → search → cross-reference → synthesize."""

    def __init__(self, llm_client, store, research_store=None, config: dict | None = None):
        self.llm = llm_client
        self.store = store
        self.research_store = research_store
        self.config = config or {}

    def run(self, question: str, depth: int = 3) -> DeepResearchResult:
        """Run the full deep research pipeline (non-streaming)."""
        result = DeepResearchResult(question=question)
        start = time.perf_counter()

        # Step 1: Decompose
        sub_queries = self._decompose(question)
        result.sub_queries = sub_queries

        # Step 2: Search each sub-query
        all_findings: list[dict] = []
        seen_titles: set[str] = set()

        for sq in sub_queries[:depth + 2]:
            step = ResearchStep(step_type="search", query=sq)
            step_start = time.perf_counter()

            findings = self._search_multi(sq)
            step.duration_ms = (time.perf_counter() - step_start) * 1000

            # Deduplicate
            for f in findings:
                title = (f.get("title") or "").lower().strip()
                if title and title not in seen_titles:
                    seen_titles.add(title)
                    all_findings.append(f)
                    step.results.append(f)

            result.steps.append(step)

        result.papers_found = len(all_findings)
        result.sources = all_findings[:20]

        # Step 3: Synthesize
        synth_step = ResearchStep(step_type="synthesize", query=question)
        synth_start = time.perf_counter()
        result.report = self._synthesize(question, all_findings)
        synth_step.duration_ms = (time.perf_counter() - synth_start) * 1000
        result.steps.append(synth_step)

        result.total_duration_ms = (time.perf_counter() - start) * 1000
        log.info("deep_research_complete", extra={
            "sub_queries": len(sub_queries),
            "papers": len(all_findings),
            "duration_ms": round(result.total_duration_ms),
        })
        return result

    def stream(self, question: str, depth: int = 3) -> Iterator[dict]:
        """Stream the deep research process as SSE events."""
        start = time.perf_counter()

        yield {"type": "status", "stage": "decompose", "message": "Breaking down question..."}

        # Step 1: Decompose
        sub_queries = self._decompose(question)
        yield {"type": "decomposed", "sub_queries": sub_queries}

        # Step 2: Search
        all_findings: list[dict] = []
        seen_titles: set[str] = set()

        for i, sq in enumerate(sub_queries[:depth + 2]):
            yield {"type": "status", "stage": "search", "message": f"Searching: {sq}", "progress": (i + 1) / (depth + 2)}

            findings = self._search_multi(sq)

            new_findings = []
            for f in findings:
                title = (f.get("title") or "").lower().strip()
                if title and title not in seen_titles:
                    seen_titles.add(title)
                    all_findings.append(f)
                    new_findings.append(f)

            yield {
                "type": "search_results",
                "query": sq,
                "results": new_findings[:5],
                "total_found": len(new_findings),
            }

        yield {"type": "status", "stage": "synthesize", "message": "Synthesizing report...", "progress": 0.9}

        # Step 3: Synthesize
        report = self._synthesize(question, all_findings)

        total_ms = (time.perf_counter() - start) * 1000
        yield {
            "type": "report",
            "report": report,
            "sources": all_findings[:20],
            "papers_found": len(all_findings),
            "duration_ms": round(total_ms),
        }
        yield {"type": "done", "duration_ms": round(total_ms)}

    # ── Private methods ─────────────────────────────────────────

    def _decompose(self, question: str) -> list[str]:
        """Use LLM to decompose a complex question into sub-queries."""
        try:
            prompt = DECOMPOSE_PROMPT.format(question=question)
            result = self.llm.complete(prompt, system_prompt="You are a research query decomposition expert. Return only JSON.")
            # Parse JSON array
            import re
            json_match = re.search(r'\[[\s\S]*?\]', result)
            if json_match:
                queries = json.loads(json_match.group())
                if isinstance(queries, list) and queries:
                    return [str(q) for q in queries[:5]]
        except Exception as e:
            log.warning("decompose failed: %s", e)

        # Fallback: use the original question with variations
        return [
            question,
            f"{question} methodology",
            f"{question} recent advances",
        ]

    def _search_multi(self, query: str, k: int = 8) -> list[dict]:
        """Search across internal KB and external academic sources."""
        results: list[dict] = []

        # Internal vector search
        try:
            from core.embedder import embed_query
            from core.search.fusion import rrf_fuse

            qvec = embed_query(query, model_name=self.config.get("embedding", {}).get("model", "nomic-ai/nomic-embed-text-v1"))
            vector_hits = self.store.search(qvec, k=k)
            fts_hits = self.store.fts_search(query, k=k)
            fused = rrf_fuse(vector_hits, fts_hits, top_n=k)

            for h in fused:
                results.append({
                    "title": h.get("title", ""),
                    "snippet": (h.get("text") or "")[:400],
                    "source": h.get("source", "knowledge_base"),
                    "url": h.get("url", ""),
                    "score": h.get("combined_score", 0),
                })
        except Exception as e:
            log.warning("internal search failed: %s", e)

        # External academic search
        try:
            from services.web_search_service import WebSearchService
            svc = WebSearchService()
            papers = svc.discover(query, sources=["arxiv", "semantic_scholar"], limit=5)
            for p in papers:
                results.append({
                    "title": p.get("title", ""),
                    "snippet": (p.get("abstract") or "")[:400],
                    "source": p.get("source", "academic"),
                    "url": p.get("url", ""),
                    "authors": p.get("authors", ""),
                    "year": p.get("year"),
                    "citation_count": p.get("citation_count", 0),
                })
        except Exception as e:
            log.warning("external search failed: %s", e)

        return results

    def _synthesize(self, question: str, findings: list[dict]) -> str:
        """Synthesize findings into a comprehensive report."""
        if not findings:
            return "No relevant findings were discovered for this question."

        # Format findings for the LLM
        findings_text = ""
        for i, f in enumerate(findings[:15], 1):
            title = f.get("title", "Untitled")
            snippet = f.get("snippet", "")
            source = f.get("source", "")
            url = f.get("url", "")
            authors = f.get("authors", "")
            year = f.get("year", "")

            findings_text += f"\n[{i}] **{title}**"
            if authors:
                findings_text += f" — {authors}"
            if year:
                findings_text += f" ({year})"
            if source:
                findings_text += f" [{source}]"
            if url:
                findings_text += f"\n    URL: {url}"
            findings_text += f"\n    {snippet}\n"

        prompt = SYNTHESIS_PROMPT.format(question=question, findings=findings_text)

        try:
            report = self.llm.complete(
                prompt,
                system_prompt="You are an expert research analyst. Write comprehensive, well-cited research reports.",
            )
            return report
        except Exception as e:
            log.warning("synthesis failed: %s", e)
            # Fallback: return raw findings
            return f"## Research Findings for: {question}\n\n" + findings_text
