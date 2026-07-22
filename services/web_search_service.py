from __future__ import annotations

import json
import time
from typing import Any
from urllib.parse import quote

import httpx

from core.config import load_config


class WebSearchService:
    def __init__(self):
        self.config = load_config()
        self._cache: dict[str, dict] = {}

    def search_arxiv(self, query: str, max_results: int = 10) -> list[dict]:
        cache_key = f"arxiv:{query}:{max_results}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        params = {
            "search_query": f"all:{quote(query)}",
            "start": 0,
            "max_results": max_results,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
        try:
            resp = httpx.get("http://export.arxiv.org/api/query", params=params, timeout=30)
            resp.raise_for_status()
            papers = self._parse_arxiv_atom(resp.text)
            self._cache[cache_key] = papers
            return papers
        except Exception:
            return []

    def search_semantic_scholar(self, query: str, limit: int = 10) -> list[dict]:
        cache_key = f"s2:{query}:{limit}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            resp = httpx.get(
                "https://api.semanticscholar.org/graph/v1/paper/search",
                params={"query": query, "limit": limit, "fields": "title,authors,year,venue,abstract,citationCount,externalIds,url"},
                timeout=30,
                headers={"User-Agent": "KnowledgeHub/1.0"},
            )
            resp.raise_for_status()
            data = resp.json()
            papers = []
            for p in data.get("data", []):
                papers.append({
                    "id": p.get("paperId", ""),
                    "title": p.get("title", ""),
                    "authors": ", ".join(a.get("name", "") for a in p.get("authors", [])),
                    "year": p.get("year"),
                    "venue": p.get("venue", ""),
                    "abstract": (p.get("abstract") or "")[:500],
                    "citation_count": p.get("citationCount", 0),
                    "url": f"https://www.semanticscholar.org/paper/{p.get('paperId', '')}",
                    "source": "semantic_scholar",
                })
            self._cache[cache_key] = papers
            return papers
        except Exception:
            return []

    def _parse_arxiv_atom(self, xml_text: str) -> list[dict]:
        import xml.etree.ElementTree as ET
        ns = {
            "atom": "http://www.w3.org/2005/Atom",
            "arxiv": "http://arxiv.org/schemas/atom",
        }
        papers = []
        try:
            root = ET.fromstring(xml_text)
            for entry in root.findall("atom:entry", ns):
                paper_id = entry.find("atom:id", ns)
                paper_id = paper_id.text.strip() if paper_id is not None else ""
                if paper_id.startswith("http"):
                    paper_id = paper_id.split("/")[-1]

                title = entry.find("atom:title", ns)
                title = " ".join((title.text or "").strip().split()) if title is not None else ""

                summary = entry.find("atom:summary", ns)
                summary = " ".join((summary.text or "").strip().split()) if summary is not None else ""

                authors = []
                for author in entry.findall("atom:author", ns):
                    name = author.find("atom:name", ns)
                    if name is not None:
                        authors.append(name.text.strip())

                published = entry.find("atom:published", ns)
                year = int(published.text[:4]) if published is not None else None

                papers.append({
                    "id": paper_id,
                    "title": title,
                    "authors": ", ".join(authors),
                    "year": year,
                    "venue": "arXiv",
                    "abstract": summary[:500],
                    "citation_count": 0,
                    "url": f"https://arxiv.org/abs/{paper_id}",
                    "source": "arxiv",
                    "has_pdf": True,
                    "pdf_url": f"https://arxiv.org/pdf/{paper_id}",
                })
        except Exception:
            pass
        return papers

    def discover(self, query: str, sources: list[str] | None = None, limit: int = 10) -> list[dict]:
        sources = sources or ["arxiv", "semantic_scholar"]
        all_papers: list[dict] = []
        seen_ids: set[str] = set()

        for source in sources:
            if source == "arxiv":
                papers = self.search_arxiv(query, max_results=limit)
            elif source == "semantic_scholar":
                papers = self.search_semantic_scholar(query, limit=limit)
            else:
                continue
            for p in papers:
                pid = p.get("id", "")
                if pid not in seen_ids:
                    seen_ids.add(pid)
                    all_papers.append(p)

        return all_papers[:limit]
